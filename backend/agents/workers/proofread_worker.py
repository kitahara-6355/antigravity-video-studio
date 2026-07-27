"""
ProofreadWorker — AI校閲ステージ

固有名詞辞書 + Gemini AI による字幕校閲。
テキスト整形 (18文字/行分割) を含む。
"""

import logging
import asyncio
import time

from agents.pipeline_types import PipelineStageWorker, PipelineContext, StageResult

logger = logging.getLogger(__name__)


class ProofreadWorker(PipelineStageWorker):
    def __init__(self):
        super().__init__("AI校閲", "📝", 1)

    def get_definition_of_done(self) -> str:
        return "全セグメントが校閲済みで、固有名詞誤りがゼロであること"

    async def execute(self, ctx: PipelineContext) -> StageResult:
        """AI校閲を実行

        入力契約:
            ctx.segments: list[dict] — 必須。各dictに text を含む
        出力契約:
            ctx.segments: list[dict] — 校閲済みテキストで更新
            ctx.skipped_features: list[str] — API障害時にスキップ理由を追加
            ctx.warnings: list[str] — API枠制限時に警告を追加
        """
        start = time.time()

        # ctx.segments の型保証と不正な要素の除外、および Segment オブジェクトの dict への変換
        has_segment_objects = False
        if ctx.segments is not None:
            if isinstance(ctx.segments, list):
                valid_segments = []
                for seg in ctx.segments:
                    if isinstance(seg, dict):
                        valid_segments.append(seg)
                    elif hasattr(seg, "to_dict") and hasattr(seg, "from_dict"):
                        valid_segments.append(seg.to_dict())
                        has_segment_objects = True
                    else:
                        logger.warning(f"Ignored invalid segment element: {type(seg)}")
                ctx.segments = valid_segments
            else:
                logger.warning("ctx.segments is not a list. Resetting to empty list.")
                ctx.segments = []
        else:
            ctx.segments = []

        logger.info(f"📊 [T-014] ProofreadWorker入口: ctx.segments={len(ctx.segments)}件")

        # T-018: セグメントなしでも安全に完了
        if not ctx.segments:
            return StageResult(
                stage_name=self.name, success=True,
                detail="セグメントなし — 校閲スキップ",
                data={"dict": 0, "ai": 0, "total": 0, "model_used": "none"},
                duration_seconds=round(time.time() - start, 1),
            )

        dict_corrections = 0
        ai_corrections = 0

        try:
            from proper_noun_dict import apply_dictionary
            for seg in ctx.segments:
                corrected, corrections = apply_dictionary(seg.get("text", ""))
                if corrections:
                    seg["text"] = corrected
                    dict_corrections += len(corrections)
        except Exception as e:
            logger.debug(f"固有名詞辞書適用スキップ: {e}")

        try:
            from subtitle_engine.ai_proofreader import proofread_segments
            original = [s.get("text", "") for s in ctx.segments]
            # UX-01: 同期AI呼び出しをスレッドプールにオフロード
            # → ステータスAPIの応答性を確保し、フロントエンドのタイムアウトを防止
            loop = asyncio.get_running_loop()
            # P-02: return_stats=Trueでリトライ統計を取得
            result = await loop.run_in_executor(
                None, lambda: proofread_segments(ctx.segments, return_stats=True)
            )
            ctx.segments, retry_stats = result
            for i, seg in enumerate(ctx.segments):
                if i < len(original) and seg.get("text", "") != original[i]:
                    ai_corrections += 1
            # P-02: リトライ統計の可視化
            if retry_stats.get("total_retries", 0) > 0:
                logger.info(f"🔄 AI校閲リトライ発生: {retry_stats['total_retries']}回 "
                            f"(失敗バッチ: {retry_stats['failed_batches']}/{retry_stats['total_batches']})")
            if retry_stats.get("failed_batches", 0) > 0:
                ctx.warnings.append(
                    f"AI校閲: {retry_stats['failed_batches']}/{retry_stats['total_batches']}バッチが"
                    f"リトライ上限({retry_stats['total_retries']}回)後に失敗しました。一部セグメントは未校閲です。"
                )
            if retry_stats.get("skipped"):
                ctx.skipped_features.append("AI校閲(Gemini)")
        except Exception as e:
            logger.warning(f"Gemini AI proofread skipped: {e}")
            ctx.skipped_features.append("AI校閲(Gemini)")

        # ━━━ FIX-3A: テキスト整形（旧 src/clean_linguistic.py 復元） ━━━
        # 長文を18文字/行に分割し、字幕の画面はみ出しを防止
        format_stats = ""
        try:
            from subtitle_engine.text_formatter import format_segments, get_max_chars_from_template
            before_count = len(ctx.segments)
            # T-016 B案: format_segments前にsourceStart/sourceEndを保護
            # format_segmentsはstart/endを文字数按分で再計算するが、
            # sourceStart/sourceEnd is 元のWhisperタイムスタンプとして不変であるべき
            source_timestamps = {}
            for i, seg in enumerate(ctx.segments):
                if "sourceStart" in seg or "sourceEnd" in seg:
                    source_timestamps[i] = {
                        "sourceStart": seg.get("sourceStart"),
                        "sourceEnd": seg.get("sourceEnd"),
                    }
            max_chars = get_max_chars_from_template()
            ctx.segments = format_segments(ctx.segments, max_chars=max_chars)
            # sourceStart/sourceEnd再注入: 分割されたセグメントにも元の範囲を維持
            if source_timestamps:
                for seg in ctx.segments:
                    # 片方でも欠けている場合は再注入
                    if "sourceStart" not in seg or "sourceEnd" not in seg:
                        seg_start = seg.get("start", 0)
                        if seg_start is not None:
                            for orig_idx, ts in source_timestamps.items():
                                ts_start = ts.get("sourceStart")
                                ts_end = ts.get("sourceEnd")
                                
                                match_start = True
                                match_end = True
                                if ts_start is not None:
                                    match_start = (ts_start - 1e-5) <= seg_start
                                if ts_end is not None:
                                    match_end = seg_start <= (ts_end + 1e-5)
                                    
                                if (ts_start is not None or ts_end is not None) and match_start and match_end:
                                    seg["sourceStart"] = ts_start
                                    seg["sourceEnd"] = ts_end
                                    break
            after_count = len(ctx.segments)
            if after_count != before_count:
                format_stats = f" / 整形{before_count}→{after_count}箇所"
        except Exception as e:
            logger.warning(f"テキスト整形スキップ: {e}")

        total = dict_corrections + ai_corrections
        # 使用モデルを取得（UI可視化用）
        try:
            from subtitle_engine.ai_proofreader import _get_current_model
            model_used = _get_current_model()
        except Exception:
            model_used = "unknown"
        # UX-15: API枠枯渇等でAI校閲がスキップされた場合、detailに警告を表示
        skip_warn = ""
        if "AI校閲(Gemini)" in ctx.skipped_features:
            skip_warn = " ⚠️ AI校閲スキップ(API枠制限)"
            ctx.warnings.append("AI校閲がAPI枠制限によりスキップされました。品質に影響する可能性があります。")
        # 元が Segment オブジェクトだった場合は、元の型に復元する
        if ctx.segments and has_segment_objects:
            try:
                from agents.pipeline_types import Segment
                restored_segments = []
                for seg in ctx.segments:
                    if isinstance(seg, dict):
                        restored_segments.append(Segment.from_dict(seg))
                    else:
                        restored_segments.append(seg)
                ctx.segments = restored_segments
            except (ImportError, KeyError, TypeError, ValueError) as e:
                logger.error(f"Failed to restore Segment objects: {e}")

        logger.info(f"📊 [T-014] ProofreadWorker出口: ctx.segments={len(ctx.segments)}件")
        return StageResult(
            stage_name=self.name, success=True,
            detail=f"辞書{dict_corrections}件 + AI{ai_corrections}件 = {total}件修正{format_stats}{skip_warn}",
            data={"dict": dict_corrections, "ai": ai_corrections, "total": total, "model_used": model_used},
            duration_seconds=round(time.time() - start, 1),
        )
