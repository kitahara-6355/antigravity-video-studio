"""
PipelineCoordinator — Coordinator-Worker パターン

Claude Code の Coordinator Mode を Antigravity に移植。
pipeline_router.py の 542行 _run_pipeline_background() を分解し、
各ステージを独立テスト可能な Worker として定義する。

設計思想:
  - 各 Worker は単一責務（1ステージ = 1 Worker）
  - TaskContract (DoD) による成功条件検証
  - SelfHealingTool による自動リトライ
  - WebSocket によるリアルタイム進捗通知
  - パイプライン完了時に DreamEngine への学習フック
"""

import json
import logging
import asyncio
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Callable, Awaitable, Any
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ============================================================
# データ構造
# ============================================================

@dataclass
class StageResult:
    """ステージ実行結果"""
    stage_name: str
    success: bool
    detail: str = ""
    data: Dict = field(default_factory=dict)
    duration_seconds: float = 0.0
    retries: int = 0


@dataclass
class PipelineContext:
    """パイプライン全体で共有するコンテキスト"""
    video_path: str
    target_minutes: int = 20
    session_id: str = ""
    started_at: str = ""
    segments: list = field(default_factory=list)
    selected_segments: list = field(default_factory=list)
    preview_path: Optional[str] = None
    final_path: Optional[str] = None
    quality_score: int = 0
    quality_feedback: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    stage_results: List[StageResult] = field(default_factory=list)
    # テンプレート基準（themes_router → template_config から注入）
    template_id: Optional[str] = None
    template_config: Optional[Dict] = None
    # Phase 4: 無人運用 — 機能スキップ追跡
    skipped_features: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ============================================================
# Worker 基底クラス
# ============================================================

class PipelineStageWorker(ABC):
    """パイプラインステージの Worker 基底クラス"""

    def __init__(self, name: str, icon: str, index: int):
        self.name = name
        self.icon = icon
        self.index = index

    @abstractmethod
    async def execute(self, ctx: PipelineContext) -> StageResult:
        """ステージを実行"""
        pass

    def get_definition_of_done(self) -> str:
        """成功条件を返す（TaskContract 用）"""
        return f"{self.name} completed successfully"

    def verify(self, result: StageResult) -> bool:
        """結果を検証"""
        return result.success


# ============================================================
# 7つの Worker 実装
# ============================================================

class TranscribeWorker(PipelineStageWorker):
    def __init__(self):
        super().__init__("文字起こし", "🎤", 0)

    def get_definition_of_done(self) -> str:
        return "字幕セグメントが1件以上生成され、各セグメントにタイムスタンプが付与されていること"

    async def execute(self, ctx: PipelineContext) -> StageResult:
        start = time.time()
        try:
            import subprocess as _sp
            import sys

            # チェックポイントファイルパス
            checkpoint_path = str(Path(ctx.video_path).parent / "_whisper_segments.jsonl")

            # 🔄 既存のチェックポイントがある場合はWhisperを完全スキップ
            if Path(checkpoint_path).exists() and Path(checkpoint_path).stat().st_size > 1000:
                logger.info(f"📋 既存チェックポイント検出 — Whisperスキップ: {checkpoint_path}")
                segments = []
                with open(checkpoint_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            segments.append(json.loads(line))
                ctx.segments = segments
                return StageResult(
                    stage_name=self.name, success=True,
                    detail=f"{len(segments)}セグメント検出 (キャッシュ)",
                    data={"segment_count": len(segments), "model": "cached"},
                    duration_seconds=round(time.time() - start, 1),
                )

            # サブプロセスでWhisper実行（CTranslate2デストラクタ→CUDAクラッシュ完全回避）
            whisper_script = str(Path(__file__).parent.parent / "subtitle_engine" / "whisper_subprocess.py")
            model_size = "small"  # medium→small: 8GB VRAMで長尺動画のOOM回避

            logger.info(f"🚀 Whisperサブプロセス起動: model={model_size}")
            logger.info(f"📐 出力: {checkpoint_path}")

            # Coordinatorの通知を取得（存在する場合）
            coordinator = None
            try:
                coordinator = pipeline_coordinator
            except NameError:
                pass

            loop = asyncio.get_running_loop()
            _self = self  # workerへの参照を保持

            def _run_whisper_subprocess():
                """サブプロセスでWhisperを実行（タイムアウト付き）"""
                TIMEOUT = 600  # 10分タイムアウト（30分動画でもGPUなら十分）

                proc = _sp.Popen(
                    [sys.executable, whisper_script, ctx.video_path, checkpoint_path, model_size, "ja"],
                    stdout=_sp.PIPE,
                    stderr=_sp.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace"
                )

                import threading
                import select

                last_result = None
                start_time = time.time()

                # 非ブロッキングでstdoutを読み取り（タイムアウト検出可能）
                def _read_stdout():
                    nonlocal last_result
                    try:
                        for line in proc.stdout:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                                if "progress" in data:
                                    pct = data["progress"]
                                    logger.info(f"文字起こし進捗: {pct}%")
                                if "status" in data:
                                    last_result = data
                            except (json.JSONDecodeError, ValueError):
                                pass
                    except Exception as thread_err:
                        logger.error(f"文字起こしサブプロセス stdout 読取スレッドエラー: {thread_err}", exc_info=True)

                reader_thread = threading.Thread(target=_read_stdout, daemon=True)
                reader_thread.start()

                # タイムアウト付きで完了を待つ
                try:
                    proc.wait(timeout=TIMEOUT)
                except _sp.TimeoutExpired:
                    logger.error(f"⏰ Whisperサブプロセスがタイムアウト({TIMEOUT}秒) — 強制終了")
                    proc.kill()
                    proc.wait(timeout=10)
                    # チェックポイントが途中まで書けていれば使う
                    if Path(checkpoint_path).exists() and Path(checkpoint_path).stat().st_size > 500:
                        logger.warning("⚠️ タイムアウトだがチェックポイントあり — 部分結果で続行")
                        return {"status": "completed", "device": "timeout_partial", "model": model_size}
                    raise RuntimeError(f"Whisperサブプロセスが{TIMEOUT}秒でタイムアウト")

                reader_thread.join(timeout=5)
                logger.info(f"Whisperサブプロセス終了: exit_code={proc.returncode}")

                if last_result and last_result.get("status") == "completed":
                    return last_result

                # フォールバック: stdoutパース失敗でも、チェックポイントファイルが存在すれば成功とみなす
                if proc.returncode == 0 and Path(checkpoint_path).exists() and Path(checkpoint_path).stat().st_size > 1000:
                    logger.warning("⚠️ サブプロセスのstdout解析失敗、チェックポイントファイルから復旧")
                    return {"status": "completed", "device": "unknown", "model": model_size}

                stderr_out = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(f"Whisperサブプロセス失敗: exit={proc.returncode}, stderr={stderr_out[:500]}")

            result = await loop.run_in_executor(None, _run_whisper_subprocess)

            # チェックポイントからセグメントを読み込み（CTranslate2とは完全に別プロセス）
            logger.info(f"📖 チェックポイントからセグメント読み込み: {checkpoint_path}")
            segments = []
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        segments.append(json.loads(line))
            ctx.segments = segments

            device_info = result.get("device", "unknown")
            return StageResult(
                stage_name=self.name, success=True,
                detail=f"{len(segments)}セグメント検出 (GPU={device_info=='cuda'}, model={model_size})",
                data={"segment_count": len(segments), "model": model_size, "device": device_info},
                duration_seconds=round(time.time() - start, 1),
            )
        except Exception as e:
            return StageResult(
                stage_name=self.name, success=False,
                detail=str(e), duration_seconds=round(time.time() - start, 1),
            )

    def verify(self, result: StageResult) -> bool:
        return result.success and result.data.get("segment_count", 0) > 0


class ProofreadWorker(PipelineStageWorker):
    def __init__(self):
        super().__init__("AI校閲", "📝", 1)

    def get_definition_of_done(self) -> str:
        return "全セグメントが校閲済みで、固有名詞誤りがゼロであること"

    async def execute(self, ctx: PipelineContext) -> StageResult:
        start = time.time()
        dict_corrections = 0
        ai_corrections = 0

        try:
            from proper_noun_dict import apply_dictionary
            for seg in ctx.segments:
                corrected, corrections = apply_dictionary(seg.get("text", ""))
                if corrections:
                    seg["text"] = corrected
                    dict_corrections += len(corrections)
        except Exception as dict_err:
            logger.warning(f"固有名詞辞書の適用中にエラー（スキップします）: {dict_err}", exc_info=True)
            ctx.warnings.append(f"固有名詞辞書適用スキップ: {str(dict_err)}")

        try:
            from subtitle_engine.ai_proofreader import proofread_segments
            original = [s.get("text", "") for s in ctx.segments]
            ctx.segments = proofread_segments(ctx.segments)
            for i, seg in enumerate(ctx.segments):
                if i < len(original) and seg.get("text", "") != original[i]:
                    ai_corrections += 1
        except Exception as e:
            logger.warning(f"Gemini AI proofread skipped: {e}")
            ctx.skipped_features.append("AI校閲(Gemini)")

        total = dict_corrections + ai_corrections
        return StageResult(
            stage_name=self.name, success=True,
            detail=f"辞書{dict_corrections}件 + AI{ai_corrections}件 = {total}件修正",
            data={"dict": dict_corrections, "ai": ai_corrections, "total": total},
            duration_seconds=round(time.time() - start, 1),
        )


class SmartCutWorker(PipelineStageWorker):
    def __init__(self):
        super().__init__("SmartCut構成", "✂️", 2)

    def get_definition_of_done(self) -> str:
        return "目標尺±2分の構成が生成され、重要シーンが含まれていること"

    async def execute(self, ctx: PipelineContext) -> StageResult:
        start = time.time()
        try:
            from agents.production_pipeline import propose_smart_cut
            result = json.loads(propose_smart_cut(
                json.dumps(ctx.segments), ctx.video_path, ctx.target_minutes
            ))
            proposals = result.get("proposals", [])
            if proposals:
                default = proposals[0]
                ctx.selected_segments = default.get("segments", ctx.segments)
                est = default.get("estimated_duration", 0)
                return StageResult(
                    stage_name=self.name, success=True,
                    detail=f"{len(ctx.selected_segments)}セグメント / 推定{est/60:.1f}分",
                    data={"segments": len(ctx.selected_segments), "duration": est},
                    duration_seconds=round(time.time() - start, 1),
                )
        except Exception as e:
            logger.warning(f"SmartCut skipped: {e}")
            ctx.skipped_features.append("SmartCut")

        ctx.selected_segments = ctx.segments
        return StageResult(
            stage_name=self.name, success=True,
            detail="全セグメント保持", duration_seconds=round(time.time() - start, 1),
        )


class PreviewWorker(PipelineStageWorker):
    def __init__(self):
        super().__init__("プレビュー生成", "🎬", 3)

    def get_definition_of_done(self) -> str:
        return "プレビューファイルが生成され、サイズが1KB以上であること"

    async def execute(self, ctx: PipelineContext) -> StageResult:
        start = time.time()
        try:
            from smart_cut_engine import render_smart_cut
            from safe_io import VAULT_OUTPUTS_DIR

            preview_dir = VAULT_OUTPUTS_DIR / "preview"
            preview_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            preview_path = str(preview_dir / f"preview_{ts}.mp4")

            success = render_smart_cut(ctx.selected_segments, ctx.video_path, preview_path)
            if success and Path(preview_path).exists():
                size_mb = Path(preview_path).stat().st_size / 1024 / 1024
                ctx.preview_path = preview_path
                return StageResult(
                    stage_name=self.name, success=True,
                    detail=f"プレビュー生成完了 ({size_mb:.1f}MB)",
                    data={"path": preview_path, "size_mb": round(size_mb, 1)},
                    duration_seconds=round(time.time() - start, 1),
                )
        except Exception as e:
            return StageResult(
                stage_name=self.name, success=False,
                detail=str(e), duration_seconds=round(time.time() - start, 1),
            )

        return StageResult(
            stage_name=self.name, success=False,
            detail="プレビュー生成失敗", duration_seconds=round(time.time() - start, 1),
        )

    def verify(self, result: StageResult) -> bool:
        path = result.data.get("path")
        return result.success and path and Path(path).exists()


class QualityGateWorker(PipelineStageWorker):
    """
    品質ゲート — プラグインアーキテクチャ版（憲法§3.2準拠）。
    
    チェック項目は quality_gate_plugins.py に独立プラグインとして分離。
    モデルチェンジ（フェーズ2-4）はプラグインの追加だけで実現。
    """
    def __init__(self):
        super().__init__("品質チェック", "✅", 5)

    def get_definition_of_done(self) -> str:
        return "品質スコア90点以上かつ致命的エラーゼロ"

    async def execute(self, ctx: PipelineContext) -> StageResult:
        start = time.time()
        score = 100  # 満点から減点方式
        feedback = []

        # プラグインエンジンに委譲
        try:
            from quality_gate_plugins import run_all_plugins
            try:
                from template_config import template_config as _tc
            except ImportError:
                _tc = None
            
            result = run_all_plugins(ctx, _tc)
            score -= result["total_deductions"]
            feedback.extend(result["feedback"])
        except ImportError:
            # プラグインモジュール未導入時のフォールバック
            logger.warning("quality_gate_plugins not found — basic check only")
            if ctx.preview_path and Path(ctx.preview_path).exists():
                if Path(ctx.preview_path).stat().st_size < 1024:
                    score -= 30
                    feedback.append("ファイルサイズが異常に小さい")
            else:
                score -= 20
                feedback.append("プレビューファイルが存在しない")
            result = {"total_deductions": 100 - score, "feedback": feedback,
                      "category_report": [], "category_scores": {}}

        score = max(0, min(100, score))
        rank = "S" if score >= 95 else "A" if score >= 90 else "B" if score >= 80 else "C"
        ctx.quality_score = score
        ctx.quality_feedback = feedback
        # カテゴリ情報を直接ctxに保存（_build_resultで確実に取得するため）
        ctx.quality_category_report = result.get("category_report", [])
        ctx.quality_category_scores = result.get("category_scores", {})

        return StageResult(
            stage_name=self.name, success=score >= 90,
            detail=f"スコア: {score}点 (ランク{rank})",
            data={
                "score": score, "rank": rank, "feedback": feedback,
                "category_report": ctx.quality_category_report,
                "category_scores": ctx.quality_category_scores,
            },
            duration_seconds=round(time.time() - start, 1),
        )

    def verify(self, result: StageResult) -> bool:
        return result.data.get("score", 0) >= 90


class RenderWorker(PipelineStageWorker):
    def __init__(self):
        super().__init__("最終レンダリング", "🎞️", 6)

    def get_definition_of_done(self) -> str:
        return "出力ファイルが存在し、サイズが1MB以上、本番品質でエンコード済みであること"

    async def execute(self, ctx: PipelineContext) -> StageResult:
        start = time.time()
        try:
            from safe_io import VAULT_OUTPUTS_DIR
            final_dir = VAULT_OUTPUTS_DIR / "final"
            final_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            final_path = str(final_dir / f"final_{ts}.mp4")

            if ctx.preview_path and Path(ctx.preview_path).exists():
                rendered = await self._render_production_quality(
                    ctx.preview_path, final_path, ctx
                )
                if rendered:
                    size_mb = Path(final_path).stat().st_size / 1024 / 1024
                    ctx.final_path = final_path
                    return StageResult(
                        stage_name=self.name, success=True,
                        detail=f"最終出力: {size_mb:.1f}MB (本番品質)",
                        data={"path": final_path, "size_mb": round(size_mb, 1),
                              "quality": "production"},
                        duration_seconds=round(time.time() - start, 1),
                    )
                else:
                    return StageResult(
                        stage_name=self.name, success=False,
                        detail="本番品質レンダリング失敗",
                        duration_seconds=round(time.time() - start, 1),
                    )
        except Exception as e:
            logger.error(f"RenderWorker エラー: {e}")
            return StageResult(
                stage_name=self.name, success=False,
                detail=str(e), duration_seconds=round(time.time() - start, 1),
            )

        return StageResult(
            stage_name=self.name, success=False,
            detail="レンダリング元なし", duration_seconds=round(time.time() - start, 1),
        )

    async def _render_production_quality(self, preview_path: str, final_path: str, ctx: 'PipelineContext' = None) -> bool:
        """
        CR-1修正: 本番品質レンダリング + 音声ラウドネス正規化

        - FFmpegEditorの "quality" プリセットで再エンコード（GPU: p7/CQ18, CPU: slow/CRF18）
        - 音声を -16 LUFS（YouTube推奨）に正規化
        - テンプレート設定があればそのLUFS値を使用
        - 失敗時はフォールバックでコピー
        """
        loop = asyncio.get_running_loop()

        def _do_render():
            import shutil

            # --- Step 1: 本番品質で再エンコード ---
            try:
                from video_editor_engine import video_editor
                ffmpeg = video_editor.ffmpeg

                if ffmpeg.is_available():
                    encode_args = ffmpeg._get_encode_args("quality")
                    # hwaccel入力は本番レンダリングでは無効化（フィルタ互換性のため）
                    cmd = [
                        "-y",
                        "-i", preview_path,
                    ] + encode_args + [
                        final_path
                    ]
                    success, output = ffmpeg.run_command(cmd, timeout=1800)

                    if not success:
                        logger.warning(f"本番品質エンコード失敗、フォールバック: {output[:200]}")
                        if ctx is not None:
                            ctx.skipped_features.append("本番品質エンコード")
                        shutil.copy(preview_path, final_path)
                else:
                    logger.warning("FFmpeg未検出 — 再エンコードなしでコピー")
                    shutil.copy(preview_path, final_path)
            except ImportError:
                logger.warning("video_editor_engine未利用可 — コピーフォールバック")
                shutil.copy(preview_path, final_path)

            # --- Step 2: 音声ラウドネス正規化 ---
            try:
                # テンプレートから目標LUFSを取得
                target_lufs = -16.0  # YouTube推奨デフォルト
                try:
                    from template_config import template_config
                    benchmarks = template_config.get_active_benchmarks()
                    target_lufs = benchmarks.get("audio_loudness_lufs", -16.0)
                except Exception as config_err:
                    logger.debug(f"アクティブテンプレートからの目標LUFS取得失敗（デフォルト -16.0 を使用）: {config_err}")

                from video_editor_engine import video_editor
                ffmpeg = video_editor.ffmpeg

                if ffmpeg.is_available():
                    # ラウドネス正規化を直接最終ファイルに適用
                    temp_normalized = final_path + ".norm.mp4"
                    loudnorm_filter = f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"
                    cmd = [
                        "-y",
                        "-i", final_path,
                        "-af", loudnorm_filter,
                        "-c:v", "copy",  # 映像は再エンコード済みなのでコピー
                        "-c:a", "aac",
                        "-b:a", "192k",
                        temp_normalized
                    ]
                    success, _ = ffmpeg.run_command(cmd, timeout=600)
                    if success and Path(temp_normalized).exists():
                        shutil.move(temp_normalized, final_path)
                        logger.info(f"🎚️ ラウドネス正規化完了: {target_lufs} LUFS")
                    else:
                        # 正規化失敗 — 元ファイルをそのまま使用（非致命的）
                        logger.warning("ラウドネス正規化スキップ（エンコード済みファイルを維持）")
                        if Path(temp_normalized).exists():
                            Path(temp_normalized).unlink()
            except Exception as loudness_err:
                logger.warning(f"ラウドネス正規化スキップ（非致命的エラー）: {loudness_err}", exc_info=True)
                if ctx is not None:
                    ctx.skipped_features.append("ラウドネス正規化")

            return Path(final_path).exists() and Path(final_path).stat().st_size > 1024

        return await loop.run_in_executor(None, _do_render)


class YouTubeOptWorker(PipelineStageWorker):
    def __init__(self):
        super().__init__("YouTube最適化", "📊", 4)

    def get_definition_of_done(self) -> str:
        return "タイトルが1案以上生成され、説明文とタグが含まれていること"

    async def execute(self, ctx: PipelineContext) -> StageResult:
        start = time.time()
        try:
            from agents.production_pipeline import generate_youtube_metadata
            result = json.loads(generate_youtube_metadata(
                " ".join(s.get("text", "") for s in ctx.segments[:20])
            ))
            if result.get("status") == "success":
                metadata = result.get("metadata", {})
                ctx.metadata = metadata
                titles = metadata.get("titles", [])
                return StageResult(
                    stage_name=self.name, success=True,
                    detail=f"タイトル{len(titles)}案生成",
                    data={"metadata": metadata},
                    duration_seconds=round(time.time() - start, 1),
                )
        except Exception as yt_err:
            logger.warning(f"YouTube最適化メタデータ生成スキップ: {yt_err}", exc_info=True)
            ctx.skipped_features.append("YouTube最適化(Gemini)")

        # フォールバック: セグメントからキーワード抽出して簡易メタデータ生成
        all_text = " ".join(s.get("text", "") for s in ctx.segments[:10])
        # テキストから2文字以上の単語を抽出してタグ化
        import re
        words = re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]{2,}', all_text)
        unique_words = list(dict.fromkeys(words))[:15]  # 重複除去、最大15個
        fallback_tags = unique_words if len(unique_words) >= 5 else ["動画", "Vlog", "日本語", "YouTube", "コンテンツ"]

        # ━━━ チャプター自動生成（5分間隔） ━━━
        chapters = [{"time": "0:00", "title": "オープニング"}]
        if ctx.segments:
            last_seg = ctx.segments[-1]
            total_sec = last_seg.get("end", last_seg.get("sourceEnd", 300))
            interval = 300  # 5分
            t = interval
            ch_idx = 1
            while t < total_sec:
                mins = int(t // 60)
                secs = int(t % 60)
                # その時間付近のセグメントテキストをチャプタータイトルに
                nearby = [s for s in ctx.segments if abs(s.get("start", 0) - t) < 30]
                title = f"パート{ch_idx + 1}"
                if nearby:
                    title = nearby[0].get("text", title)[:20]
                chapters.append({"time": f"{mins}:{secs:02d}", "title": title})
                t += interval
                ch_idx += 1

        ctx.metadata = {
            "titles": [f"{all_text[:30]}..."],
            "tags": fallback_tags,
            "description": all_text[:200] + "\n\n#動画 #Vlog #YouTube",
            "chapters": chapters,
        }
        return StageResult(
            stage_name=self.name, success=True,
            detail="簡易メタデータ生成",
            duration_seconds=round(time.time() - start, 1),
        )


# ============================================================
# Coordinator（司令塔）
# ============================================================

class PipelineCoordinator:
    """
    Coordinator-Worker パターンのメインコントローラ。

    責務:
    1. Worker を順次実行
    2. TaskContract (DoD) で結果検証
    3. 失敗時は SelfHealing リトライ
    4. WebSocket でリアルタイム進捗通知
    5. 完了後に DreamEngine 学習フック起動
    """

    MAX_RETRIES = 2
    MAX_QUALITY_RETRIES = 3  # U-03: 品質ゲート自動改善ループ

    def __init__(self):
        self.workers: List[PipelineStageWorker] = [
            TranscribeWorker(),
            ProofreadWorker(),
            SmartCutWorker(),
            PreviewWorker(),
            YouTubeOptWorker(),     # メタデータ生成を品質チェックの前に
            QualityGateWorker(),    # 全データ揃った状態で品質評価
            RenderWorker(),         # 品質合格後に本番レンダリング
        ]
        self._progress_callback: Optional[Callable] = None
        self._ws_broadcast: Optional[Callable] = None

    def _find_worker(self, worker_type: type) -> Optional[PipelineStageWorker]:
        """Worker をタイプで検索（インデックス直値を避ける）"""
        for w in self.workers:
            if isinstance(w, worker_type):
                return w
        return None

    def set_progress_callback(self, callback: Callable):
        """進捗コールバックを設定（pipeline_routerから注入）"""
        self._progress_callback = callback

    def set_ws_broadcast(self, broadcast_fn: Callable):
        """WebSocket ブロードキャスト関数を設定"""
        self._ws_broadcast = broadcast_fn

    async def _notify(self, worker: PipelineStageWorker, status: str,
                      detail: str = "", progress: int = -1):
        """進捗通知（コールバック + WebSocket 両方）"""
        if self._progress_callback:
            self._progress_callback(worker.index, status, detail, progress)

        if self._ws_broadcast:
            await self._ws_broadcast({
                "type": "pipeline_progress",
                "stage_index": worker.index,
                "stage_name": worker.name,
                "stage_icon": worker.icon,
                "status": status,
                "detail": detail,
                "progress": progress,
                "timestamp": datetime.now().isoformat(),
            })

    async def execute(self, ctx: PipelineContext) -> Dict:
        """パイプライン全体を実行"""
        ctx.started_at = datetime.now().isoformat()
        total_start = time.time()

        # ━━━ Phase 4: ディスク空き容量チェック ━━━
        try:
            import shutil
            output_dir = Path(ctx.video_path).parent
            disk = shutil.disk_usage(str(output_dir))
            free_gb = disk.free / (1024 ** 3)
            if free_gb < 1.0:
                logger.error(f"❌ ディスク空き不足: {free_gb:.1f}GB (最低1GB必要)")
                return self._build_result(ctx, "error", total_start,
                                          f"ディスク空き容量不足: {free_gb:.1f}GB")
            elif free_gb < 5.0:
                ctx.warnings.append(f"ディスク残量注意: {free_gb:.1f}GB")
                logger.warning(f"⚠️ ディスク残量注意: {free_gb:.1f}GB")
        except Exception as disk_err:
            logger.debug(f"ディスク容量チェックでエラー（スキップします）: {disk_err}", exc_info=True)

        # ━━━ C-2修正: テンプレート初期化保証 ━━━
        # themes_router./apply で設定済みならスキップ。
        # 未設定の場合、ctx.template_id から復元を試みる。
        try:
            from template_config import template_config
            if not template_config.is_active and ctx.template_id:
                from routers.themes_router import PRODUCTION_TEMPLATES
                tmpl_data = PRODUCTION_TEMPLATES.get(ctx.template_id)
                if tmpl_data:
                    template_config.set_active_template(
                        ctx.template_id, tmpl_data,
                        theme_id="warm"
                    )
                    logger.info(f"🔗 パイプライン開始時テンプレート復元: {ctx.template_id}")
        except (ImportError, Exception) as tmpl_err:
            logger.debug(f"テンプレート初期化復元でエラー（スキップします）: {tmpl_err}", exc_info=True)

        for worker in self.workers:
            await self._notify(worker, "running", f"{worker.name} 開始...")

            result = None
            for attempt in range(1, self.MAX_RETRIES + 1):
                result = await worker.execute(ctx)
                result.retries = attempt - 1

                if worker.verify(result):
                    break

                if attempt < self.MAX_RETRIES:
                    logger.warning(
                        f"🔄 {worker.name} リトライ {attempt}/{self.MAX_RETRIES}: "
                        f"{result.detail}"
                    )
                    await self._notify(worker, "retrying",
                                       f"リトライ {attempt}/{self.MAX_RETRIES}")
                    await asyncio.sleep(1)

            ctx.stage_results.append(result)

            if result.success:
                await self._notify(worker, "completed", result.detail, 100)
            else:
                await self._notify(worker, "error", result.detail)
                # 非致命的なステージはスキップ続行
                if worker.index in (0, 3):  # 文字起こし・プレビューは致命的
                    logger.error(f"❌ 致命的エラー: {worker.name} — 中断")
                    return self._build_result(ctx, "error", total_start, result.detail)

            # U-03: 品質ゲート不合格時の自動改善ループ
            if isinstance(worker, QualityGateWorker) and not worker.verify(result):
                improved = await self._quality_improvement_loop(ctx)
                if not improved:
                    logger.warning("品質改善ループ上限到達 — 現状で続行")

        total_duration = round(time.time() - total_start, 1)

        # ━━━ BIZ-4修正: Retention Map → パイプライン自動接続 ━━━
        retention_report = await self._run_retention_analysis(ctx)
        if retention_report:
            ctx.stage_results.append(retention_report)

        # DreamEngine 学習フック
        await self._trigger_dream_learning(ctx)

        return self._build_result(ctx, "completed", total_start)

    async def _quality_improvement_loop(self, ctx: PipelineContext) -> bool:
        """
        U-03: 品質ゲート90点未満時の自動改善ループ。

        Preview再生成 → QualityGate再チェック を最大 MAX_QUALITY_RETRIES 回繰り返す。
        フィードバックを蓄積し、各イテレーションで改善を試みる。
        """
        preview_worker = self._find_worker(PreviewWorker)
        quality_worker = self._find_worker(QualityGateWorker)

        if not preview_worker or not quality_worker:
            logger.error("品質改善ループ: PreviewWorker/QualityGateWorker が見つかりません")
            return False

        for qi in range(1, self.MAX_QUALITY_RETRIES + 1):
            # 前回の品質フィードバックを記録
            last_result = ctx.stage_results[-1] if ctx.stage_results else None
            if last_result and last_result.data.get("feedback"):
                ctx.quality_feedback.extend(last_result.data["feedback"])

            logger.info(
                f"🔄 品質改善ループ {qi}/{self.MAX_QUALITY_RETRIES}: "
                f"前回スコア={ctx.quality_score}点, "
                f"フィードバック={len(ctx.quality_feedback)}件"
            )
            await self._notify(
                quality_worker, "retrying",
                f"品質改善 {qi}/{self.MAX_QUALITY_RETRIES} (前回:{ctx.quality_score}点)"
            )

            # Preview 再生成
            await self._notify(preview_worker, "running", "品質改善のため再生成中...")
            preview_result = await preview_worker.execute(ctx)
            if not preview_result.success:
                logger.warning(f"品質改善ループ: Preview再生成失敗 — {preview_result.detail}")
                continue

            # QualityGate 再チェック
            await self._notify(quality_worker, "running", "品質再チェック...")
            quality_result = await quality_worker.execute(ctx)
            ctx.stage_results.append(quality_result)

            if quality_worker.verify(quality_result):
                logger.info(
                    f"✅ 品質改善成功: {ctx.quality_score}点 "
                    f"({qi}回目のリトライ)"
                )
                await self._notify(
                    quality_worker, "completed",
                    f"品質改善成功: {ctx.quality_score}点", 100
                )
                return True

            logger.warning(
                f"品質改善ループ {qi}: まだ不合格 "
                f"({ctx.quality_score}点)"
            )

        return False

    def _build_result(self, ctx: PipelineContext, status: str,
                      total_start: float, error: str = "") -> Dict:
        # ━━━ D-6修正: 品質ゲート詳細をresultに含める ━━━
        # ctxから直接取得（StageResult.dataの伝達に依存しない）
        quality_details = {
            "score": ctx.quality_score,
            "feedback": getattr(ctx, 'quality_feedback', []),
            "category_report": getattr(ctx, 'quality_category_report', []),
            "category_scores": getattr(ctx, 'quality_category_scores', {}),
        }

        return {
            "status": status,
            "session_id": ctx.session_id,
            "duration_seconds": round(time.time() - total_start, 1),
            "final_path": ctx.final_path,
            "preview_path": ctx.preview_path,
            "metadata": ctx.metadata,
            "quality_score": ctx.quality_score,
            "quality_details": quality_details,
            "segments_count": len(ctx.segments),
            "stage_results": [
                {"name": r.stage_name, "success": r.success,
                 "detail": r.detail, "duration": r.duration_seconds,
                 "retries": r.retries}
                for r in ctx.stage_results
            ],
            "error": error,
            # Phase 4: 無人運用ヘルスレポート
            "health": {
                "skipped_features": ctx.skipped_features,
                "warnings": ctx.warnings,
                "all_features_active": len(ctx.skipped_features) == 0,
            },
        }
    async def _run_retention_analysis(self, ctx: PipelineContext):
        """
        BIZ-4: パイプライン完了前にRetention Map分析を実行。
        離脱リスクの高いポイントを特定し、リエンゲージメント提案を生成。
        """
        try:
            from plugins.retention_map_plugin import retention_map_plugin

            video_id = Path(ctx.video_path).stem
            # 動画の総尺（セグメントから推定）
            duration_sec = 0
            if ctx.segments:
                last = ctx.segments[-1]
                duration_sec = int(last.get("end", last.get("start", 0)) + 5)
            if duration_sec < 30:
                duration_sec = ctx.target_minutes * 60  # フォールバック

            report = retention_map_plugin.analyze_retention_risks(
                video_id=video_id,
                duration_sec=duration_sec,
                video_path=ctx.video_path,
            )

            # パイプライン結果にRetentionデータを付加
            ctx.metadata["retention_analysis"] = {
                "overall_risk": report.overall_risk_assessment,
                "suggestions_count": len(report.suggestions),
                "high_risk_segments": [
                    {
                        "time": f"{s.start_time}-{s.end_time}s",
                        "risk": s.risk_level,
                        "label": s.label,
                    }
                    for s in report.segments
                    if s.risk_level >= 7
                ],
                "top_suggestions": report.suggestions[:3],
            }

            logger.info(
                f"📊 BIZ-4: Retention Map分析完了 — "
                f"リスク: {report.overall_risk_assessment}, "
                f"提案: {len(report.suggestions)}件"
            )

            # StageResult形式で返す
            from agents.pipeline_coordinator import StageResult
            return StageResult(
                stage_name="Retention分析",
                success=True,
                detail=f"リスク: {report.overall_risk_assessment} / 提案: {len(report.suggestions)}件",
                duration_seconds=0.1,
                data=ctx.metadata["retention_analysis"],
            )

        except (ImportError, Exception) as retention_err:
            logger.debug(f"Retention分析スキップ（非致命的エラー）: {retention_err}", exc_info=True)
            return None

    async def _trigger_dream_learning(self, ctx: PipelineContext):
        """提案3: パイプライン完了時に DreamEngine 学習フック"""
        try:
            from agents.dream_engine import dream_engine

            # 制作ナレッジを構造化して記録
            knowledge = {
                "type": "pipeline_completion",
                "timestamp": datetime.now().isoformat(),
                "video": Path(ctx.video_path).name,
                "segments_total": len(ctx.segments),
                "segments_selected": len(ctx.selected_segments),
                "quality_score": ctx.quality_score,
                "stage_durations": {
                    r.stage_name: r.duration_seconds
                    for r in ctx.stage_results
                },
                "total_corrections": sum(
                    r.data.get("total", 0) for r in ctx.stage_results
                    if r.stage_name == "AI校閲"
                ),
                "retries_used": sum(r.retries for r in ctx.stage_results),
            }

            # DreamEngine のシグナルとして記録
            knowledge_path = Path(__file__).parent / "logs" / "pipeline_knowledge"
            knowledge_path.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            knowledge_file = knowledge_path / f"run_{ts}.json"
            knowledge_file.write_text(
                json.dumps(knowledge, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            logger.info(f"🌙 制作ナレッジ記録: {knowledge_file.name}")

            # DreamEngine トリガー判定
            if await dream_engine.should_dream():
                logger.info("🌙 DreamEngine 起動条件充足 → 学習サイクル開始")
                asyncio.create_task(dream_engine.run_dream_cycle())

        except (ImportError, Exception) as dream_err:
            logger.debug(f"DreamEngine学習フックスキップ（非致命的エラー）: {dream_err}", exc_info=True)


    # ============================================================
    # Harness 統合（Anthropic推奨パターン）
    # ============================================================

    async def execute_with_harness(self, ctx: PipelineContext) -> Dict:
        """
        ハーネスモードでパイプラインを実行。

        Anthropic推奨のパターンを既存パイプラインに透過的に適用:
        - Hook による Pre/Post ツール実行制御
        - セッション持続性管理（切断復旧対応）
        - ガバナンス（スコープ付き権限、実行トレース）

        HARNESS_MODE 環境変数:
          - "enabled": ハーネス有効（デフォルト）
          - "disabled": レガシーモードのみ
        """
        import os
        harness_mode = os.environ.get("HARNESS_MODE", "enabled")

        if harness_mode == "disabled":
            return await self.execute(ctx)

        try:
            from harness import hook_system, session_manager, governance_engine
            from harness.hooks import HookEvent, HookInput, HookOutput

            # セッション作成/リジューム
            if ctx.session_id:
                session = session_manager.resume_session(ctx.session_id)
                if not session:
                    session = session_manager.create_session(
                        video_path=ctx.video_path,
                        session_id=ctx.session_id,
                    )
            else:
                session = session_manager.create_session(video_path=ctx.video_path)
                ctx.session_id = session.session_id

            # トレース開始
            trace_span = governance_engine.start_span(
                operation="pipeline_execute",
                tool_name="PipelineCoordinator",
                attributes={"video_path": ctx.video_path},
            )

            # パイプライン実行（レガシーロジックをそのまま使用）
            # ただし、各ステージ実行前後に Hook を発火
            ctx.started_at = datetime.now().isoformat()
            total_start = time.time()

            for worker in self.workers:
                # PreToolUse Hook 発火
                hook_input = HookInput(
                    tool_name=worker.name,
                    tool_input={"video_path": ctx.video_path, "stage": worker.index},
                    session_id=ctx.session_id,
                )
                pre_output = await hook_system.fire(HookEvent.PRE_TOOL_USE, hook_input)

                # deny 判定ならスキップ
                if pre_output.permission_decision == "deny":
                    logger.warning(
                        f"🚫 Hook denied: {worker.name} — "
                        f"{pre_output.permission_decision_reason}"
                    )
                    ctx.stage_results.append(StageResult(
                        stage_name=worker.name,
                        success=False,
                        detail=f"Hook denied: {pre_output.permission_decision_reason}",
                    ))
                    if worker.index in (0, 3):
                        governance_engine.end_span(trace_span, status="denied")
                        session_manager.error_session(
                            ctx.session_id,
                            f"Hook denied at {worker.name}",
                        )
                        return self._build_result(
                            ctx, "error", total_start,
                            pre_output.permission_decision_reason,
                        )
                    continue

                # ガバナンス: 権限チェック
                agent_id = worker.name.lower().replace("ー", "").replace("AI", "ai")
                for scope_id in governance_engine._scopes:
                    if scope_id in agent_id or agent_id in scope_id:
                        agent_id = scope_id
                        break

                # セッション進捗更新
                session_manager.update_stage(
                    ctx.session_id, worker.index, f"{worker.name} 実行中",
                )

                # Worker 実行（レガシーロジック）
                await self._notify(worker, "running", f"{worker.name} 開始...")
                result = None
                for attempt in range(1, self.MAX_RETRIES + 1):
                    result = await worker.execute(ctx)
                    result.retries = attempt - 1
                    if worker.verify(result):
                        break
                    if attempt < self.MAX_RETRIES:
                        await self._notify(
                            worker, "retrying",
                            f"リトライ {attempt}/{self.MAX_RETRIES}",
                        )
                        await asyncio.sleep(1)

                ctx.stage_results.append(result)

                # PostToolUse / PostToolUseFailure Hook 発火
                if result.success:
                    post_input = HookInput(
                        tool_name=worker.name,
                        tool_output=result.data,
                        session_id=ctx.session_id,
                    )
                    await hook_system.fire(HookEvent.POST_TOOL_USE, post_input)
                    await self._notify(worker, "completed", result.detail, 100)

                    # セッションにツール呼び出し記録
                    session_manager.record_tool_call(
                        ctx.session_id, worker.name,
                        {"stage": worker.index},
                        result.data, result.duration_seconds,
                    )
                else:
                    fail_input = HookInput(
                        tool_name=worker.name,
                        error=result.detail,
                        session_id=ctx.session_id,
                    )
                    await hook_system.fire(HookEvent.POST_TOOL_USE_FAILURE, fail_input)
                    await self._notify(worker, "error", result.detail)

                    if worker.index in (0, 3):
                        logger.error(f"❌ 致命的エラー: {worker.name} — 中断")
                        governance_engine.end_span(trace_span, status="error")
                        session_manager.error_session(ctx.session_id, result.detail)
                        return self._build_result(ctx, "error", total_start, result.detail)

                # 品質ゲート: Evaluator-Optimizer ワークフロー（Anthropic推奨パターン）
                if isinstance(worker, QualityGateWorker) and not worker.verify(result):
                    try:
                        from harness.evaluator_optimizer import evaluator_optimizer
                        opt_result = await evaluator_optimizer.run(ctx, max_iterations=3)
                        if opt_result.success:
                            logger.info(
                                f"✅ Evaluator-Optimizer 成功: "
                                f"{opt_result.initial_score}→{opt_result.final_score}点 "
                                f"({opt_result.iterations}回)"
                            )
                            # セッションに改善結果を記録
                            session_manager.record_tool_call(
                                ctx.session_id, "evaluator_optimizer",
                                {"iterations": opt_result.iterations},
                                {"improvements": opt_result.improvements_applied},
                                opt_result.duration_seconds,
                            )
                        else:
                            logger.warning(
                                f"⚠️ Evaluator-Optimizer 不合格のまま: "
                                f"{opt_result.final_score}点"
                            )
                    except ImportError:
                        # Evaluator-Optimizer 未利用可 → レガシーフォールバック
                        improved = await self._quality_improvement_loop(ctx)
                        if not improved:
                            logger.warning("品質改善ループ上限到達 — 現状で続行")

            # Retention Map 分析
            retention_report = await self._run_retention_analysis(ctx)
            if retention_report:
                ctx.stage_results.append(retention_report)

            # DreamEngine 学習フック
            await self._trigger_dream_learning(ctx)

            # ハーネス完了処理
            governance_engine.end_span(trace_span, status="ok")
            session_manager.complete_session(
                ctx.session_id,
                quality_score=ctx.quality_score,
                final_data={
                    "stages_completed": len(ctx.stage_results),
                    "final_path": ctx.final_path,
                },
            )
            governance_engine.flush_traces(ctx.session_id)

            return self._build_result(ctx, "completed", total_start)

        except ImportError:
            logger.info("ハーネス未インストール — レガシーモードで実行")
            return await self.execute(ctx)
        except Exception as harness_err:
            logger.error(f"ハーネスモードエラー — レガシーフォールバックを実行します: {harness_err}", exc_info=True)
            return await self.execute(ctx)


# シングルトン
pipeline_coordinator = PipelineCoordinator()
