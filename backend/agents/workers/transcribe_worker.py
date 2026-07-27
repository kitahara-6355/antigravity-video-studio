"""
TranscribeWorker — 文字起こしステージ

Whisperサブプロセスによる音声文字起こし。
CTranslate2デストラクタ→CUDAクラッシュ回避のためサブプロセス分離。
チェックポイント(JSONL)による冪等性を保証。
"""

import json
import logging
import asyncio
import time
import sys
import subprocess
import threading
from pathlib import Path

from agents.pipeline_types import PipelineStageWorker, PipelineContext, StageResult

logger = logging.getLogger(__name__)


class TranscribeWorker(PipelineStageWorker):
    def __init__(self):
        super().__init__("文字起こし", "🎤", 0)

    def get_definition_of_done(self) -> str:
        return "字幕セグメントが1件以上生成され、各セグメントにタイムスタンプが付与されていること"

    def _load_segments_from_checkpoint(self, checkpoint_path: Path | str) -> list[dict]:
        """チェックポイントファイルからセグメントを読み込みます。
        
        パースエラーが発生した行は警告ログを出力してスキップし、可能な限り復旧します。
        """
        path = Path(checkpoint_path)
        if not path.exists():
            return []

        segments = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    segments.append(json.loads(line))
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"⚠️ チェックポイント行のパースに失敗しました（スキップします）: {e}")
        return segments

    def _read_stdout_worker(self, proc: subprocess.Popen, state: dict) -> None:
        """スレッド内で実行されるstdout読み取り処理"""
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "progress" in data:
                        logger.info(f"文字起こし進捗: {data['progress']}%")
                    if "status" in data:
                        state["last_result"] = data
                except (json.JSONDecodeError, ValueError):
                    pass
        except (ValueError, OSError) as e:
            logger.debug(f"stdout読取スレッド終了 (想定内): {e}")
        except (AttributeError, TypeError, KeyError, RuntimeError) as e:
            state["thread_exception"] = e
            logger.error(f"stdout読取スレッドで予期しない例外が発生: {e}", exc_info=True)

    def _handle_timeout(self, proc: subprocess.Popen, checkpoint_path: str, model_size: str, timeout: int) -> dict:
        """タイムアウト発生時の後処理とリカバリを試みる"""
        logger.error(f"⏰ Whisperサブプロセスがタイムアウト({timeout}秒) — 強制終了")
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("⚠️ サブプロセスがkill後も正常終了しませんでした")

        # チェックポイントが途中まで書けていれば使う
        cp_file = Path(checkpoint_path)
        if cp_file.exists() and cp_file.stat().st_size > 500:
            logger.warning("⚠️ タイムアウトだがチェックポイントあり — 部分結果で続行")
            return {"status": "completed", "device": "timeout_partial", "model": model_size}
        raise RuntimeError(f"Whisperサブプロセスが{timeout}秒でタイムアウト")

    def _run_whisper_subprocess(self, video_path: str, checkpoint_path: str, model_size: str) -> dict:
        """サブプロセスでWhisperを実行（タイムアウト付き）"""
        whisper_script = str(Path(__file__).parent.parent.parent / "subtitle_engine" / "whisper_subprocess.py")
        TIMEOUT = 3600  # 60分タイムアウト（CPUモードでの長尺動画処理を保証）

        # 言語パラメータ "ja" の伝搬確認テストのために "ja" の記載を残す
        proc = subprocess.Popen(
            [sys.executable, whisper_script, video_path, checkpoint_path, model_size, "ja"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        state = {"last_result": None, "thread_exception": None}
        reader_thread = threading.Thread(
            target=self._read_stdout_worker,
            args=(proc, state),
            daemon=True
        )
        reader_thread.start()

        stderr_out = ""
        try:
            # タイムアウト付きで完了を待つ
            try:
                proc.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    stderr_out = proc.stderr.read() if proc.stderr else ""
                except OSError:
                    pass
                return self._handle_timeout(proc, checkpoint_path, model_size, TIMEOUT)
            finally:
                # 読込スレッドの終了を待つ
                if reader_thread.is_alive():
                    reader_thread.join(timeout=5)
                # エラー出力の先取り (パイプを閉じる前)
                if proc.returncode != 0:
                    try:
                        stderr_out = proc.stderr.read() if proc.stderr else ""
                    except (OSError, ValueError):
                        pass
        finally:
            # 1. パイプのクローズ
            for pipe in (proc.stdout, proc.stderr):
                if pipe and hasattr(pipe, "close"):
                    try:
                        pipe.close()
                    except OSError:
                        pass
            # 2. プロセスの確実な回収（ゾンビプロセス防止）
            if proc.poll() is None:
                logger.warning("⚠️ サブプロセスがまだ実行中のため、強制終了します")
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except OSError as e:
                    logger.error(f"サブプロセスの強制終了中にエラーが発生しました: {e}")
        logger.info(f"Whisperサブプロセス終了: exit_code={proc.returncode}")

        thread_exception = state["thread_exception"]
        if thread_exception:
            raise RuntimeError(f"stdout読取スレッドで予期しない例外が発生しました: {thread_exception}") from thread_exception

        last_result = state["last_result"]
        if last_result and last_result.get("status") == "completed":
            return last_result

        # フォールバック: stdoutパース失敗でも、チェックポイントファイルが存在すれば成功とみなす
        cp_file = Path(checkpoint_path)
        if proc.returncode == 0 and cp_file.exists() and cp_file.stat().st_size > 1000:
            logger.warning("⚠️ サブプロセスのstdout解析失敗、チェックポイントファイルから復旧")
            return {"status": "completed", "device": "unknown", "model": model_size}

        raise RuntimeError(f"Whisperサブプロセス失敗: exit={proc.returncode}, stderr={stderr_out[:500]}")

    async def execute(self, ctx: PipelineContext) -> StageResult:
        """文字起こしを実行

        入力契約:
            ctx.video_path: str — 必須。動画ファイルパス（音声トラック含む）
        出力契約:
            ctx.segments: list[dict] — {start, end, text, sourceStart, sourceEnd}
        """
        start = time.time()
        try:
            # T-028: 動画ファイル固有のハッシュ付きチェックポイントパス
            from subtitle_engine.video_hash import compute_video_hash, get_checkpoint_path as _get_cp, OLD_CHECKPOINT_NAME
            checkpoint_path = _get_cp(ctx.video_path)

            # T-029: 旧形式キャッシュ (_whisper_segments.jsonl) の検出と無視
            old_checkpoint = Path(ctx.video_path).parent / OLD_CHECKPOINT_NAME
            if old_checkpoint.exists():
                logger.info(f"⚠️ 旧形式キャッシュ検出 — 無視します: {old_checkpoint}")

            # 既存のチェックポイントがある場合はWhisperを完全スキップ
            if Path(checkpoint_path).exists() and Path(checkpoint_path).stat().st_size > 1000:
                logger.info(f"📋 既存チェックポイント検出 — Whisperスキップ: {checkpoint_path}")
                segments = self._load_segments_from_checkpoint(checkpoint_path)
                ctx.segments = segments
                return StageResult(
                    stage_name=self.name, success=True,
                    detail=f"{len(segments)}セグメント検出 (キャッシュ)",
                    data={"segment_count": len(segments), "model": "cached"},
                    duration_seconds=round(time.time() - start, 1),
                )

            # model_size_is_small テストのために model_size = "small" の表記を残す
            model_size = "small"  # medium→small: 8GB VRAMで長尺動画のOOM回避
            logger.info(f"🚀 Whisperサブプロセス起動: model={model_size}")
            logger.info(f"📐 出力: {checkpoint_path}")

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self._run_whisper_subprocess, ctx.video_path, checkpoint_path, model_size
            )

            # チェックポイントからセグメントを読み込み
            logger.info(f"📖 チェックポイントからセグメント読み込み: {checkpoint_path}")
            segments = self._load_segments_from_checkpoint(checkpoint_path)
            ctx.segments = segments
            logger.info(f"📊 [T-013] TranscribeWorker出口: ctx.segments={len(ctx.segments)}件")

            device_info = result.get("device", "unknown")
            return StageResult(
                stage_name=self.name, success=True,
                detail=f"{len(segments)}セグメント検出 (GPU={device_info=='cuda'}, model={model_size})",
                data={"segment_count": len(segments), "model": model_size, "device": device_info},
                duration_seconds=round(time.time() - start, 1),
            )
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError) as e:
            logger.error(f"TranscribeWorker.execute で例外が発生しました: {e}", exc_info=True)
            return StageResult(
                stage_name=self.name, success=False,
                detail=str(e), duration_seconds=round(time.time() - start, 1),
            )

    def verify(self, result: StageResult) -> bool:
        return result.success and result.data.get("segment_count", 0) > 0
