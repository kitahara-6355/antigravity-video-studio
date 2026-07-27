"""
YouTubeOptWorker — YouTube最適化ステージ

Gemini API によるメタデータ生成。
フォールバック: キーワード抽出 + チャプター自動生成。
"""

import json
import logging
import time
import re
from typing import Any, Union, Optional

from agents.pipeline_types import PipelineStageWorker, PipelineContext, StageResult

logger = logging.getLogger(__name__)


class YouTubeOptWorker(PipelineStageWorker):
    def __init__(self) -> None:
        super().__init__("YouTube最適化", "📊", 4)

    def get_definition_of_done(self) -> str:
        return "タイトルが1案以上生成され、説明文とタグが含まれていること"

    def _get_attribute_or_key(self, s: Any, key: str, default: Any = None) -> Any:
        """オブジェクトの属性または辞書のキーから安全に値を取得する"""
        if hasattr(s, key):
            val = getattr(s, key)
            return val if val is not None else default
        elif isinstance(s, dict):
            return s.get(key, default)
        return default

    def _extract_all_text(self, ctx: PipelineContext) -> str:
        """PipelineContext の segments からテキストを抽出して結合する"""
        return " ".join(self._get_attribute_or_key(s, "text", "") for s in (ctx.segments or [])[:20])

    async def _generate_ai_metadata(self, all_text: str) -> tuple[dict, str]:
        """Gemini APIによるメタデータ生成"""
        from gemini_client_factory import get_gemini_client
        from google.genai import types

        client = get_gemini_client()
        prompt = (
            "以下の動画字幕テキストから、YouTube投稿用のメタデータをJSON形式で生成してください。\n"
            "要件:\n"
            "- titles: タイトル5案（30文字以内、興味を引く表現）\n"
            "- tags: 15-20個（大カテゴリ→小カテゴリ→固有名詞の順）\n"
            "- description: 200-500文字（末尾にハッシュタグ3-5個）\n"
            "- chapters: [{\"time\": \"0:00\", \"title\": \"チャプター名\"}]\n\n"
            f"字幕テキスト（抜粋）:\n{all_text[:3000]}"
        )

        try:
            from model_governance import model_governance as _mg
            model_name = _mg._resolve_model("youtube_optimization")
        except (ImportError, AttributeError) as e:
            logger.warning(f"モデル解決でエラーが発生したため、デフォルトを使用します: {e}")
            model_name = "gemini-2.5-flash"  # フォールバック

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        metadata = json.loads(response.text)
        return metadata, model_name

    def _extract_fallback_tags(self, all_text: str) -> list[str]:
        """字幕テキストからフォールバック用タグを抽出"""
        words = re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]{2,}', all_text)
        unique_words = list(dict.fromkeys(words))[:15]
        return unique_words if len(unique_words) >= 5 else ["動画", "Vlog", "日本語", "YouTube", "コンテンツ"]

    def _create_fallback_chapters(self, segments: list) -> list[dict]:
        """セグメント情報からフォールバック用チャプターを生成"""
        chapters = [{"time": "0:00", "title": "オープニング"}]
        if not segments:
            return chapters

        last_seg = segments[-1]
        total_sec = self._get_attribute_or_key(last_seg, "end", self._get_attribute_or_key(last_seg, "sourceEnd", 300))
        interval = 300  # 5分
        t = interval
        ch_idx = 1
        while t < total_sec:
            mins = int(t // 60)
            secs = int(t % 60)
            nearby = [s for s in segments if abs(self._get_attribute_or_key(s, "start", 0) - t) < 30]
            title = f"パート{ch_idx + 1}"
            if nearby:
                title = self._get_attribute_or_key(nearby[0], "text", title)[:20]
            chapters.append({"time": f"{mins}:{secs:02d}", "title": title})
            t += interval
            ch_idx += 1
        return chapters

    def _generate_fallback_metadata(self, all_text: str, segments: list) -> dict:
        """フォールバックによるメタデータ生成（キーワード抽出 + チャプター自動生成）"""
        fallback_tags = self._extract_fallback_tags(all_text)
        chapters = self._create_fallback_chapters(segments)

        return {
            "titles": [f"{all_text[:30]}..."],
            "tags": fallback_tags,
            "description": all_text[:200] + "\n\n#動画 #Vlog #YouTube",
            "chapters": chapters,
        }

    async def execute(self, ctx: PipelineContext) -> StageResult:
        """YouTube最適化メタデータを生成

        入力契約:
            ctx.segments: list[dict] — 必須。各dictに text を含む（先頭20個を使用）
        出力契約:
            ctx.metadata: dict — titles, tags, description, chapters を含む
        """
        start = time.time()
        all_text = self._extract_all_text(ctx)

        # ━━━ Gemini API でメタデータ生成（429なら即フォールバック） ━━━
        try:
            from google.genai.errors import APIError
        except ImportError:
            class APIError(Exception):
                pass

        try:
            metadata, model_name = await self._generate_ai_metadata(all_text)
            ctx.metadata = metadata
            self._run_cross_media_analysis(ctx)
            titles = metadata.get("titles", [])
            return StageResult(
                stage_name=self.name, success=True,
                detail=f"AI生成: タイトル{len(titles)}案 / タグ{len(metadata.get('tags',[]))}個",
                data={"metadata": metadata, "model_used": model_name},
                duration_seconds=round(time.time() - start, 1),
            )
        except (
            APIError,
            json.JSONDecodeError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            ImportError,
            RuntimeError,
        ) as e:
            logger.warning(f"YouTube AI生成スキップ (詳細: {e})", exc_info=True)
            ctx.skipped_features.append("YouTube最適化(Gemini)")

        # ━━━ フォールバック: キーワード抽出 + チャプター自動生成 ━━━
        fallback_metadata = self._generate_fallback_metadata(all_text, ctx.segments)
        ctx.metadata = fallback_metadata
        self._run_cross_media_analysis(ctx)
        return StageResult(
            stage_name=self.name, success=True,
            detail=f"フォールバック: タグ{len(fallback_metadata['tags'])}個 / チャプター{len(fallback_metadata['chapters'])}個",
            duration_seconds=round(time.time() - start, 1),
        )

    def _run_cross_media_analysis(self, ctx: PipelineContext) -> None:
        """クロスメディア相関分析を実行し、結果をメタデータに追加する"""
        try:
            from services.cross_media_service import CrossMediaService
            service = CrossMediaService()

            # ctxからYouTubeアナリティクスとSNSデータを安全に取得
            metadata_source = getattr(ctx, "metadata_source", {}) or {}
            youtube_analytics = metadata_source.get("youtube_analytics", {})
            sns_data = metadata_source.get("sns_data", None)

            # 相関分析を実行
            correlation_result = service.analyze_cross_media_correlation(youtube_analytics, sns_data)

            # メタデータに結果を埋め込む
            if not isinstance(ctx.metadata, dict):
                ctx.metadata = {}
            ctx.metadata["cross_media_correlation"] = correlation_result
        except (KeyError, AttributeError, ValueError, TypeError, ImportError) as e:
            logger.warning(f"クロスメディア相関分析でエラーが発生しましたが、処理を継続します: {e}")

