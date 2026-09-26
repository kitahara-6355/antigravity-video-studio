"""
RenderWorker — 最終レンダリングステージ

本番品質でのエンコード + BGMダッキング + ロゴ重畳 + ラウドネス正規化。
"""

import logging
import asyncio
import time
import shutil
import uuid
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

    @staticmethod
    def _指紋(path: str) -> str | None:
        """プレビューの指紋（無ければ None）。書き出しの前後で同じものを書いたかを見る。"""
        import hashlib

        p = Path(path)
        if not p.is_file():
            return None
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _承認を確かめる(ctx: PipelineContext) -> tuple[bool, str]:
        """この実行が承認を通っているか。**確かめられなければ書き出さない。**"""
        run_dir = getattr(ctx, "run_dir", None)
        if not run_dir:
            return False, ("実行記録を指していないので承認を確かめられません"
                           "（本線は `python -m backend.agents.pipeline_coordinator <動画>` → "
                           "`--approve` → `--export`）")
        from backend.revenue.approval_gate import export_allowed

        return export_allowed(run_dir)

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

        # **承認していない動画は書き出せない**（R2-C1・2026-09-25）。
        # 門は coordinator にもあるが、**書き出すのはここ**なので、ここでも引く。
        # harness の `render_final` のように worker を直接呼ぶ経路が素通りしていた
        # （2026-09-24 の gate-verifier が `vault-outputs/final/` への抜け道として報告）。
        # 承認は実行記録の隣にあるので、**記録を指せない文脈では書き出さない**（fail-closed）。
        許可, 理由 = self._承認を確かめる(ctx)
        if not 許可:
            logger.warning(f"🚫 承認の門: {理由}")
            return StageResult(
                stage_name=self.name, success=False,
                detail=f"承認の門: {理由}",
                duration_seconds=round(time.time() - start, 1),
            )

        try:
            from safe_io import VAULT_OUTPUTS_DIR
            final_dir = VAULT_OUTPUTS_DIR / "final"
            final_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            # **名前は実走ごとに一意**（2026-09-26・gate-verifier 7周目の F2）。以前は
            # `final_<秒>.mp4` で、承認済みの2本を同じ秒に書き出すと同じ名前を取り合い、
            # 片方の承認済み動画が消えて証跡が相手の動画を指した
            run_tag = Path(ctx.run_dir).name if getattr(ctx, "run_dir", None) else uuid.uuid4().hex[:8]
            final_path = str(final_dir / f"final_{ts}_{run_tag}.mp4")

            # **承認したプレビューからしか書き出さない**（2026-09-26・gate-verifier 6周目の U3）。
            # 以前は T-022 のセーフモードで、プレビューが無ければ素材から直接レンダリングした。
            # 門の確認の後にプレビューが消えると（容量不足のとき本線のフックが実際に消す）、
            # **人が見ていない動画**が completed で出ていた。見ていないものは書き出さない
            if not ctx.preview_path or not Path(ctx.preview_path).exists():
                return StageResult(
                    stage_name=self.name, success=False,
                    detail=("承認したプレビューがありません（素材から直接は書き出さない — "
                            "見ていないものは書き出さない）"),
                    duration_seconds=round(time.time() - start, 1),
                )
            始めの指紋 = self._指紋(ctx.preview_path)

            # 名前を**排他的に取る** — 既に同じ名前があれば上書きせずに断る（同じ実走の二重書き出し）
            try:
                with open(final_path, "xb"):
                    pass
            except FileExistsError:
                return StageResult(
                    stage_name=self.name, success=False,
                    detail=f"同じ名前の完成品が既にあります（上書きしない）: {final_path}",
                    duration_seconds=round(time.time() - start, 1),
                )

            # **取った名前は、書き出しに成功したときだけ残す**（2026-09-26・gate-verifier 8周目）。
            # 以前は、名前を取った後にプレビューが消えると 0 バイトの完成品が置き場に残り、
            # 指紋の読み直しで落ちても書いたものが残った。どこで抜けても最後に消す
            成功 = False
            try:
                if not Path(ctx.preview_path).exists():
                    return StageResult(
                        stage_name=self.name, success=False,
                        detail="名前を取った後に承認したプレビューが消えました（書き出さない）",
                        duration_seconds=round(time.time() - start, 1),
                    )
                rendered = await self._render_production_quality(
                    ctx.preview_path, final_path, ctx
                )
                if not rendered:
                    return StageResult(
                        stage_name=self.name, success=False,
                        detail="本番品質レンダリング失敗",
                        duration_seconds=round(time.time() - start, 1),
                    )
                if self._指紋(ctx.preview_path) != 始めの指紋:
                    # 門の確認と書き出しの間の窓を閉じる — **書いた後にもう一度プレビューを見る**
                    logger.warning("🚫 書き出しの途中でプレビューが変わりました。書いたものを捨てます")
                    return StageResult(
                        stage_name=self.name, success=False,
                        detail="書き出しの途中で承認したプレビューが変わりました（書いたものは捨てた）",
                        duration_seconds=round(time.time() - start, 1),
                    )
                size_mb = Path(final_path).stat().st_size / 1024 / 1024
                ctx.final_path = final_path
                成功 = True
                return StageResult(
                    stage_name=self.name, success=True,
                    detail=f"最終出力: {size_mb:.1f}MB (本番品質)",
                    data={"path": final_path, "size_mb": round(size_mb, 1),
                          "quality": "production"},
                    duration_seconds=round(time.time() - start, 1),
                )
            finally:
                if not 成功:
                    Path(final_path).unlink(missing_ok=True)   # 取った名前・書きかけを置き場に残さない
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
