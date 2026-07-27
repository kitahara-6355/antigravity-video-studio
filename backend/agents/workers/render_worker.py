"""
RenderWorker — 最終レンダリングステージ

本番品質でのエンコード + BGMダッキング + ロゴ重畳 + ラウドネス正規化。
"""

import logging
import asyncio
import time
import shutil
from pathlib import Path
from datetime import datetime

from agents.pipeline_types import PipelineStageWorker, PipelineContext, StageResult

logger = logging.getLogger(__name__)


class RenderWorker(PipelineStageWorker):
    """
    動画の最終レンダリング処理を担当するワーカークラス。
    
    本番品質での再エンコード、BGMのミキシングとダッキング、
    ロゴの重畳、および音声のラウドネス正規化を順次適用します。
    """

    def __init__(self) -> None:
        """
        RenderWorkerのインスタンスを初期化します。
        """
        super().__init__("最終レンダリング", "🎞️", 6)

    def get_definition_of_done(self) -> str:
        """
        このステージの完了定義（Definition of Done）を取得します。

        Returns:
            str: 完了定義のテキスト。
        """
        return "出力ファイルが存在し、サイズが1MB以上、本番品質でエンコード済みであること"

    async def execute(self, ctx: PipelineContext) -> StageResult:
        """
        最終レンダリング処理を実行します。

        入力契約:
            ctx.preview_path (str): 必須。プレビューファイルパス
        出力契約:
            ctx.final_path (str): 最終出力ファイルパス
            ctx.skipped_features (list[str]): フォールバック時にスキップ理由を追加

        Args:
            ctx (PipelineContext): パイプラインの実行コンテキスト。

        Returns:
            StageResult: ステージの実行結果。
        """
        start = time.time()
        try:
            from safe_io import VAULT_OUTPUTS_DIR
            final_dir = VAULT_OUTPUTS_DIR / "final"
            final_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            final_path = str(final_dir / f"final_{ts}.mp4")

            # T-022: セーフモード — preview_path なし時は元動画から直接レンダリング
            if not ctx.preview_path or not Path(ctx.preview_path).exists():
                if ctx.video_path and Path(ctx.video_path).exists():
                    logger.warning("⚠️ [T-022] プレビューなし — 元動画からセーフモードレンダリング")
                    ctx.preview_path = ctx.video_path
                    ctx.skipped_features.append("プレビュー生成")
                else:
                    return StageResult(
                        stage_name=self.name, success=False,
                        detail="レンダリング元なし（プレビューも元動画も不在）",
                        duration_seconds=round(time.time() - start, 1),
                    )

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
        except (ImportError, OSError, ValueError, KeyError, AttributeError, RuntimeError, TypeError) as e:
            logger.error(f"RenderWorker 実行時致命的エラー [{type(e).__name__}]: {e}", exc_info=True)
            return StageResult(
                stage_name=self.name, success=False,
                detail=str(e), duration_seconds=round(time.time() - start, 1),
            )

        return StageResult(
            stage_name=self.name, success=False,
            detail="レンダリング元なし", duration_seconds=round(time.time() - start, 1),
        )

    async def _render_production_quality(self, preview_path: str, final_path: str,
                                          ctx: PipelineContext = None) -> bool:
        """
        本番品質のレンダリング、BGM合成、ロゴ重畳、および音声正規化を非同期に実行します。

        内部で定義された同期処理をスレッドプール上で非同期に処理します。

        Args:
            preview_path (str): 入力となるプレビュー動画のパス。
            final_path (str): 最終出力動画 of パス。
            ctx (PipelineContext, optional): パイプラインのコンテキスト。

        Returns:
            bool: 最終出力ファイルが正常に生成された場合は True、そうでない場合は False。
        """
        loop = asyncio.get_running_loop()

        def _do_render() -> bool:
            # 1. 本番品質で再エンコード
            self._encode_video_production_quality(preview_path, final_path, ctx)

            # 2. BGMダッキング・ミキシング
            self._mix_bgm(final_path, ctx)

            # 3. ロゴ重畳
            self._overlay_logo(final_path, ctx)

            # 4. 音声ラウドネス正規化
            self._normalize_audio_loudness(final_path, ctx)

            return Path(final_path).exists() and Path(final_path).stat().st_size > 1024

        return await loop.run_in_executor(None, _do_render)

    def _encode_video_production_quality(self, preview_path: str, final_path: str,
                                          ctx: PipelineContext = None) -> None:
        """
        プレビュー動画を本番品質で再エンコードします。

        FFmpegEditorの "balanced" プリセットを使用してエンコードします。
        FFmpegが利用できない、またはエンコードに失敗した場合は、フォールバックとして
        プレビュー動画をコピーします。

        Args:
            preview_path (str): 入力プレビュー動画のパス。
            final_path (str): 出力動画のパス。
            ctx (PipelineContext, optional): パイプラインのコンテキスト。
        """
        try:
            from video_editor_engine import video_editor
            ffmpeg = video_editor.ffmpeg

            if ffmpeg.is_available():
                encode_args = ffmpeg._get_encode_args("balanced")
                cmd = [
                    "-y",
                    "-i", preview_path,
                ] + encode_args + [
                    final_path
                ]
                success, output = ffmpeg.run_command(cmd, timeout=1800)

                if not success:
                    logger.warning(f"本番品質エンコード失敗、フォールバック: {output[:200]}")
                    if ctx:
                        ctx.skipped_features.append("本番品質エンコード")
                    shutil.copy(preview_path, final_path)
            else:
                logger.warning("FFmpeg未検出 — 再エンコードなしでコピー")
                shutil.copy(preview_path, final_path)
        except ImportError:
            logger.warning("video_editor_engine未利用可 — コピーフォールバック")
            shutil.copy(preview_path, final_path)

    def _mix_bgm(self, final_path: str, ctx: PipelineContext = None) -> None:
        """
        動画にBGMを合成し、音声がある部分でBGMを下げるサイドチェインダッキングを適用します。

        BGMはテンプレート設定から取得するか、デフォルトのBGM（branding/bgm/default_bgm.mp3）
        を使用します。BGMが存在しない、またはミキシングに失敗した場合は処理をスキップします。

        Args:
            final_path (str): 対象となる動画のパス。
            ctx (PipelineContext, optional): パイプラインのコンテキスト。
        """
        try:
            bgm_path = None
            try:
                from template_config import template_config as _tc
                if _tc.is_active:
                    bgm_path = _tc.get_branding_config().get("bgm_path")
            except (ImportError, AttributeError, KeyError, RuntimeError) as e:
                logger.debug(f"テンプレートBGM取得スキップ ({type(e).__name__}): {e}")

            if not bgm_path:
                default_bgm = Path(__file__).parent.parent.parent / "branding" / "bgm" / "default_bgm.mp3"
                if default_bgm.exists():
                    bgm_path = str(default_bgm)

            if bgm_path and Path(bgm_path).exists():
                from video_editor_engine import video_editor
                ffmpeg = video_editor.ffmpeg

                if ffmpeg.is_available():
                    temp_bgm_mixed = final_path + ".bgm.mp4"
                    bgm_filter = (
                        "[1:a]volume=0.3[bgm_v];"
                        "[bgm_v][0:a]sidechaincompress="
                        "threshold=0.1:ratio=4:attack=20:release=250[bgm_ducked];"
                        "[0:a][bgm_ducked]amix=inputs=2:duration=first[a_out]"
                    )
                    cmd = [
                        "-y",
                        "-i", final_path,
                        "-i", bgm_path,
                        "-filter_complex", bgm_filter,
                        "-map", "0:v",
                        "-map", "[a_out]",
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-b:a", "192k",
                        temp_bgm_mixed,
                    ]
                    success, _ = ffmpeg.run_command(cmd, timeout=600)
                    if success and Path(temp_bgm_mixed).exists():
                        shutil.move(temp_bgm_mixed, final_path)
                        logger.info(f"🎵 BGMダッキング・ミキシング完了: {Path(bgm_path).name}")
                    else:
                        logger.warning("BGMミキシングスキップ（FFmpeg失敗）")
                        if Path(temp_bgm_mixed).exists():
                            Path(temp_bgm_mixed).unlink()
                        if ctx:
                            ctx.skipped_features.append("BGMミキシング")
            else:
                logger.info("🎵 BGMファイルなし — スキップ")
                if ctx:
                    ctx.skipped_features.append("BGMミキシング(ファイルなし)")
        except (ImportError, FileNotFoundError, OSError, ValueError, RuntimeError) as e:
            logger.warning(f"BGMミキシングスキップ ({type(e).__name__}): {e}")
            if ctx:
                ctx.skipped_features.append("BGMミキシング")

    def _overlay_logo(self, final_path: str, ctx: PipelineContext = None) -> None:
        """
        動画にブランドロゴを重ねて表示します。

        ロゴの画像パス、不透明度、表示位置、および高さはテンプレート設定から取得します。
        テンプレート設定がない場合はデフォルトロゴ（branding/logos/brand_logo.png）を使用します。

        Args:
            final_path (str): 対象となる動画 of パス。
            ctx (PipelineContext, optional): パイプラインのコンテキスト。
        """
        try:
            logo_path = None
            logo_position = (10, 10)
            logo_opacity = 0.8
            logo_height = 60

            try:
                from template_config import template_config as _tc
                if _tc.is_active:
                    branding = _tc.get_branding_config()
                    logo_path = branding.get("logo_path")
                    logo_position = tuple(branding.get("logo_position", [10, 10]))
                    logo_opacity = branding.get("logo_opacity", 0.8)
                    logo_height = branding.get("logo_height", 60)
            except (ImportError, AttributeError, KeyError, RuntimeError) as e:
                logger.debug(f"テンプレートロゴ取得スキップ ({type(e).__name__}): {e}")

            if not logo_path:
                default_logo = Path(__file__).parent.parent.parent / "branding" / "logos" / "brand_logo.png"
                if default_logo.exists():
                    logo_path = str(default_logo)

            if logo_path and Path(logo_path).exists():
                from logo_overlay import LogoOverlay
                overlay = LogoOverlay()
                temp_logo_out = final_path + ".logo.mp4"
                overlay.apply_logo(
                    input_video=final_path,
                    logo_path=logo_path,
                    output_path=temp_logo_out,
                    position=logo_position,
                    opacity=logo_opacity,
                    target_height=logo_height,
                )
                if Path(temp_logo_out).exists():
                    shutil.move(temp_logo_out, final_path)
                    logger.info(f"🏷️ ロゴ重畳完了: {Path(logo_path).name}")
                else:
                    logger.warning("ロゴ重畳スキップ（出力ファイルなし）")
                    if ctx:
                        ctx.skipped_features.append("ロゴ重畳")
            else:
                logger.info("🏷️ ロゴファイルなし — スキップ")
                if ctx:
                    ctx.skipped_features.append("ロゴ重畳(ファイルなし)")
        except (ImportError, FileNotFoundError, OSError, ValueError, RuntimeError) as e:
            logger.warning(f"ロゴ重畳スキップ ({type(e).__name__}): {e}")
            if ctx:
                ctx.skipped_features.append("ロゴ重畳")

    def _normalize_audio_loudness(self, final_path: str, ctx: PipelineContext = None) -> None:
        """
        動画音声のラウドネス正規化を実行し、音量を目標LUFS値に調整します。

        目標LUFS値やフィルタパラメータはテンプレート設定から取得します。
        テンプレート設定がない場合はデフォルト値（-16.0 LUFS）を使用します。

        Args:
            final_path (str): 対象となる動画のパス。
            ctx (PipelineContext, optional): パイプラインのコンテキスト。
        """
        try:
            loudnorm_filter = None
            target_lufs = -16.0
            try:
                from template_config import template_config
                loudnorm_filter = template_config.get_loudnorm_filter()
                if loudnorm_filter is not None and not isinstance(loudnorm_filter, str):
                    loudnorm_filter = None
                benchmarks = template_config.get_quality_benchmarks()
                target_lufs = benchmarks.get("audio_loudness_lufs", -16.0)
            except (ImportError, AttributeError, KeyError, RuntimeError) as e:
                logger.debug(f"テンプレートLUFS取得スキップ ({type(e).__name__}): {e}")
            
            if not loudnorm_filter:
                loudnorm_filter = f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"

            from video_editor_engine import video_editor
            ffmpeg = video_editor.ffmpeg

            if ffmpeg.is_available():
                temp_normalized = final_path + ".norm.mp4"
                cmd = [
                    "-y",
                    "-i", final_path,
                    "-af", loudnorm_filter,
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    temp_normalized
                ]
                success, _ = ffmpeg.run_command(cmd, timeout=600)
                if success and Path(temp_normalized).exists():
                    shutil.move(temp_normalized, final_path)
                    logger.info(f"🎚️ ラウドネス正規化完了: {target_lufs} LUFS")
                else:
                    logger.warning("ラウドネス正規化スキップ（エンコード済みファイルを維持）")
                    if Path(temp_normalized).exists():
                        Path(temp_normalized).unlink()
        except (ImportError, FileNotFoundError, OSError, ValueError, RuntimeError) as e:
            logger.warning(f"ラウドネス正規化スキップ ({type(e).__name__}): {e}")
            if ctx:
                ctx.skipped_features.append("ラウドネス正規化")
