"""
RenderWorker — 最終レンダリングステージ

本番品質でのエンコード + BGMダッキング + ロゴ重畳 + ラウドネス正規化。
"""

import logging
import asyncio
import os
import subprocess
import time
import shutil
import uuid
from pathlib import Path
from datetime import datetime

from agents.pipeline_types import PipelineStageWorker, PipelineContext, StageResult

logger = logging.getLogger(__name__)

# 既定の曲の置き場（置いてあればそれを使う。無ければ曲の台帳から引く）
DEFAULT_BGM = Path(__file__).parent.parent.parent / "branding" / "bgm" / "default_bgm.mp3"
# テンプレート・既定の曲を敷くときの音量と下げ方（曲の台帳の「美麗の書道対談」の BGM と同じ・2026-11-12 北原さん）
MAINLINE_BGM_DEFAULTS = {"volume_db": -22, "duck": True, "duck_ratio": 3, "fade": 3.0, "loop_crossfade": 4.0}
# 曲の繰り返しを重ねてつなぐのは、この回数まで（入力が増えすぎるので、超えたら単純な繰り返し）
MAX_BGM_REPEATS = 40


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
                    detail=f"最終出力: {size_mb:.1f}MB（{self._encode_label(ctx)}）",
                    data={"path": final_path, "size_mb": round(size_mb, 1),
                          # **実際に使った設定を名乗る**（D-47）。以前は何で書いても "production" だった
                          "quality": (getattr(ctx, "render_encode", None) or {}).get("mode"),
                          "encode": getattr(ctx, "render_encode", None)},
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

    @staticmethod
    def _encode_setting(ctx: PipelineContext = None) -> tuple[str, str]:
        """**書き出しのモードから、エンコードの設定の名前を引く**（D-47）。

        以前は `ctx.render_mode` をどこからも読まず、safe でも production でも "balanced" で
        書いていた（モードは記録上の区別でしかなかった）。設定は `backend/config/render_modes.json`。
        知らないモード・読めない設定は、控えめな側（fallback_mode）に倒す。
        """
        import json

        mode = getattr(ctx, "render_mode", None) or "production"
        try:
            cfg = json.loads((Path(__file__).resolve().parents[2] / "config" / "render_modes.json")
                             .read_text(encoding="utf-8"))
            modes = cfg["modes"]
            if mode not in modes:
                mode = cfg.get("fallback_mode", "safe")
            return mode, str(modes[mode]["encode"])
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.warning(f"書き出しのモードの設定を読めません（balanced で書く）: {e}")
            return "safe", "balanced"

    @staticmethod
    def _encode_label(ctx: PipelineContext = None) -> str:
        used = getattr(ctx, "render_encode", None) or {}
        if used.get("fallback"):
            return f"{used.get('mode')}・焼き直せずプレビューの写し"
        return f"{used.get('mode')}・{used.get('encode')}" if used else "設定の記録なし"

    def _encode_video_production_quality(self, preview_path: str, final_path: str,
                                          ctx: PipelineContext = None) -> None:
        """
        プレビュー動画を、書き出しのモードに合わせた設定で再エンコードします（D-47）。

        production は "quality"、safe は "balanced"（`backend/config/render_modes.json`）。
        実際に使った設定は `ctx.render_encode` に残し、書き出しの記録に載せます。
        FFmpegが利用できない、またはエンコードに失敗した場合は、フォールバックとして
        プレビュー動画をコピーします（そのことも `render_encode.fallback` に残る）。

        Args:
            preview_path (str): 入力プレビュー動画のパス。
            final_path (str): 出力動画のパス。
            ctx (PipelineContext, optional): パイプラインのコンテキスト。
        """
        try:
            from video_editor_engine import video_editor
            ffmpeg = video_editor.ffmpeg

            mode, encode = self._encode_setting(ctx)
            used = {"mode": mode, "encode": encode, "fallback": False}
            if ctx is not None:
                ctx.render_encode = used
            if ffmpeg.is_available():
                encode_args = ffmpeg._get_encode_args(encode)
                used["args"] = [a for a in encode_args if a not in ("-c:a", "aac")]
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
                    used["fallback"] = True
                    shutil.copy(preview_path, final_path)
            else:
                logger.warning("FFmpeg未検出 — 再エンコードなしでコピー")
                used["fallback"] = True
                shutil.copy(preview_path, final_path)
        except ImportError:
            logger.warning("video_editor_engine未利用可 — コピーフォールバック")
            if ctx is not None:
                ctx.render_encode = {"mode": getattr(ctx, "render_mode", None), "encode": None, "fallback": True}
            shutil.copy(preview_path, final_path)

    def _bgm_spec(self) -> tuple[dict | None, dict | None]:
        """敷く BGM の指定（remix と同じ形）と、何の曲かの控え。曲が無ければ (None, None)。

        探す順: テンプレートの bgm_path → 既定の曲（branding/bgm/default_bgm.mp3）→
        曲の台帳（backend/config/music.json の mainline。曲は環境変数 AVS_MUSIC_DIR の場所から）。
        """
        from backend.program_package import music as mu

        bgm_path, origin = None, None
        try:
            from template_config import template_config as _tc
            if _tc.is_active:
                bgm_path, origin = _tc.get_branding_config().get("bgm_path"), "テンプレート"
        except (ImportError, AttributeError, KeyError, RuntimeError) as e:
            logger.debug(f"テンプレートBGM取得スキップ ({type(e).__name__}): {e}")
        if not (bgm_path and Path(bgm_path).exists()):
            bgm_path, origin = (str(DEFAULT_BGM), "既定の曲") if DEFAULT_BGM.exists() else (None, None)
        if bgm_path:
            spec = {"op_music": None, "ed_music": None, "peak_db": -1.5,
                    "bgm": {**MAINLINE_BGM_DEFAULTS, "path": str(bgm_path), "provisional": False}}
            return spec, {"from": origin, "file": Path(bgm_path).name, "title": None, "artist": None,
                          "source": None, "provisional": False}
        try:
            spec = mu.mainline_bgm(mu.load_ledger(), os.environ.get("AVS_MUSIC_DIR"))
        except (mu.MusicError, OSError, ValueError, KeyError) as e:
            logger.info(f"🎵 曲の台帳の BGM は使えません: {e}")
            return None, None
        track = (spec.get("tracks") or {}).get("bgm") or {}
        return spec, {"from": "曲の台帳", "file": Path(spec["bgm"]["path"]).name, "title": track.get("title"),
                      "artist": track.get("artist"), "source": track.get("source"),
                      "provisional": bool(spec["bgm"].get("provisional"))}

    def _mix_bgm(self, final_path: str, ctx: PipelineContext = None) -> None:
        """
        動画の全体に BGM を小さく敷き、話している間は自動で下げます（サイドチェイン）。

        音の組み立ては番組の仕上げ（backend/program_package/remix.py）と同じ物を使います
        （曲の繰り返しは重ねてつなぐ・最後に音割れ止め）。映像は写すだけです。
        曲が無い、またはミキシングに失敗した場合は、記録（skipped_features）に出して曲なしで続けます。
        入れた曲は `ctx.render_bgm` に残り、書き出しの記録に載ります。

        Args:
            final_path (str): 対象となる動画のパス。
            ctx (PipelineContext, optional): パイプラインのコンテキスト。
        """
        temp_bgm_mixed = final_path + ".bgm.mp4"
        try:
            spec, used = self._bgm_spec()
            if not spec:
                logger.info("🎵 BGMファイルなし — スキップ")
                if ctx:
                    ctx.skipped_features.append("BGMミキシング(ファイルなし)")
                return

            from video_editor_engine import video_editor

            from backend.program_package import remix as rx
            ffmpeg = video_editor.ffmpeg
            if not ffmpeg.is_available():
                logger.warning("BGMミキシングスキップ（FFmpeg が使えない）")
                if ctx:
                    ctx.skipped_features.append("BGMミキシング")
                return

            total = rx.duration(final_path)
            bgm = dict(spec["bgm"])
            bgm["fade"] = min(float(bgm.get("fade", 3.0)), total / 4)   # 短い動画でも出し入れが収まるように
            song = rx.duration(bgm["path"])
            step = song - float(bgm.get("loop_crossfade", 4.0))
            if step > 0 and total / step <= MAX_BGM_REPEATS:
                bgm["_len"] = song   # 曲の繰り返しを重ねてつなぐ（多すぎるときは単純な繰り返し）
            extra, graph = rx.graph({**spec, "bgm": bgm}, {"program": 0.0, "body": 0.0, "ed": 0.0}, total)
            cmd = [
                "-y",
                "-i", final_path,
                *extra,
                "-filter_complex", graph,
                "-map", "0:v:0",
                "-map", "[a]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-t", f"{total:.3f}",
                temp_bgm_mixed,
            ]
            success, _ = ffmpeg.run_command(cmd, timeout=600)
            if success and Path(temp_bgm_mixed).exists():
                shutil.move(temp_bgm_mixed, final_path)
                if ctx:
                    ctx.render_bgm = used
                logger.info(f"🎵 BGMダッキング・ミキシング完了: {used['file']}（{used['from']}）")
            else:
                logger.warning("BGMミキシングスキップ（FFmpeg失敗）")
                if ctx:
                    ctx.skipped_features.append("BGMミキシング")
        except (ImportError, FileNotFoundError, OSError, ValueError, RuntimeError,
                subprocess.SubprocessError) as e:
            logger.warning(f"BGMミキシングスキップ ({type(e).__name__}): {e}")
            if ctx:
                ctx.skipped_features.append("BGMミキシング")
        finally:
            Path(temp_bgm_mixed).unlink(missing_ok=True)

    def _overlay_logo(self, final_path: str, ctx: PipelineContext = None) -> None:
        """
        動画にブランドロゴを重ねて表示します。

        ロゴの画像パス、不透明度、表示位置、および高さはテンプレート設定から取得します。
        テンプレート設定がない場合はデフォルトロゴ（branding/logos/brand_logo.png）を使用します。

        Args:
            final_path (str): 対象となる動画 of パス。
            ctx (PipelineContext, optional): パイプラインのコンテキスト。
        """
        from logo_policy import logo_enabled
        if not logo_enabled():
            logger.info("🏷️ ロゴなし（backend/config/logo.json）")
            return
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
                # ロゴを重ねると映像をもう一度焼く。書き出しと同じ設定で焼き、そのことを記録に残す（D-47）
                used = getattr(ctx, "render_encode", None) or {}
                logo_args = list(used.get("args") or []) or None
                if used:
                    used["logo"] = {"reencoded": True, "args": logo_args or "既定（medium・crf23）"}
                overlay.apply_logo(
                    input_video=final_path,
                    logo_path=logo_path,
                    output_path=temp_logo_out,
                    position=logo_position,
                    opacity=logo_opacity,
                    target_height=logo_height,
                    video_args=logo_args,
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
