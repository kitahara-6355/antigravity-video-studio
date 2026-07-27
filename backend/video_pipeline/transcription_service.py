"""
transcription_service.py — S3: 音声文字起こし

音声ファイルからテキストを文字起こしするパイプラインステージ。
faster-whisperが利用可能な場合はそれを使用し、利用不可の場合は
ffprobeで音声長を取得してダミーセグメントを生成するフォールバック設計。

FFmpeg呼び出しは _run_ffmpeg() メソッドに分離し、テスト時にモック可能な設計。

subprocess.Popenモック安全規約:
  - poll() は return_value=0 で即座に終了コードを返すこと
  - readline() は空文字列 "" を返すこと
  - conftest.py の safe_popen_mock fixture を使用すること
"""

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データクラス定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class TranscriptSegment:
    """文字起こしの1セグメント。

    Attributes:
        start: セグメント開始時刻（秒）
        end: セグメント終了時刻（秒）
        text: 文字起こしテキスト
        confidence: 信頼度スコア (0.0〜1.0)
    """

    start: float = 0.0
    end: float = 0.0
    text: str = ""
    confidence: float = 0.0


@dataclass
class TranscriptResult:
    """文字起こし結果。

    Attributes:
        success: 文字起こし成功フラグ
        segments: 文字起こしセグメントのリスト
        language: 検出された言語コード
        model_used: 使用されたモデル名
        duration_seconds: 処理にかかった時間（秒）
    """

    success: bool = False
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str = ""
    model_used: str = ""
    duration_seconds: float = 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TranscriptionService クラス
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TranscriptionService:
    """S3: 音声文字起こしステージ。

    faster-whisperモデルで音声を文字起こしする。
    faster-whisper未インストール時は、ffprobeで音声長を取得し
    10秒ごとのダミーセグメントを生成するフォールバックを行う。

    FFmpeg呼び出しは _run_ffmpeg() メソッドに分離し、
    テスト時に safe_popen_mock でモック可能。

    Args:
        model_name: Whisperモデル名 (例: "base", "small", "medium")
        language: 言語コード (例: "ja")
    """

    def __init__(
        self,
        model_name: str = "base",
        language: str = "ja",
        refine_enabled: bool = True,
    ) -> None:
        """TranscriptionServiceを初期化する。

        Args:
            model_name: 使用するWhisperモデル名
            language: 文字起こし対象の言語コード
            refine_enabled: stable-ts によるタイムスタンプ精密化を行うか否か
        """
        self.model_name: str = model_name
        self.language: str = language
        self.refine_enabled: bool = refine_enabled

    def transcribe(self, audio_path: str) -> TranscriptResult:
        """音声ファイルを文字起こしする。

        faster-whisperが利用可能な場合はそれを使用し、
        利用不可の場合はフォールバック（ダミーセグメント生成）を行う。
        refine_enabled=True かつ stable-ts 利用可能な場合、タイムスタンプを精密化する。

        Args:
            audio_path: 音声ファイルのパス

        Returns:
            TranscriptResult: 文字起こし結果
        """
        start_time = time.time()
        logger.info("文字起こし開始: %s (model=%s, lang=%s, refine=%s)",
                     audio_path, self.model_name, self.language, self.refine_enabled)

        try:
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"Audio file not found: {audio_path}")

            if self._is_stable_ts_available():
                segments = self._transcribe_with_stable_ts(audio_path)
                model_used = f"stable-ts/{self.model_name}"
            elif self._is_whisper_available():
                segments = self._transcribe_with_whisper(audio_path)
                model_used = f"faster-whisper/{self.model_name}"
            else:
                logger.warning(
                    "stable-tsおよびfaster-whisperが利用不可のためフォールバックモードで実行"
                )
                segments = self._generate_fallback_transcript(audio_path)
                model_used = "fallback/dummy"

            if self.refine_enabled and self._is_stable_ts_available():
                try:
                    from backend.video_pipeline.stable_ts_wrapper import StableTsWrapper
                    wrapper = StableTsWrapper(model_name=self.model_name, language=self.language)
                    refined = wrapper.refine_timestamps(audio_path, segments)
                    if refined:
                        segments = refined
                        model_used = f"{model_used}+refined"
                except Exception as e:
                    logger.warning("stable-ts refine 処理中に例外が発生したためオリジナルのセグメントを使用します: %s", e)

            elapsed = time.time() - start_time
            logger.info(
                "文字起こし完了: %d セグメント (%.1f秒, model=%s)",
                len(segments), elapsed, model_used,
            )

            return TranscriptResult(
                success=True,
                segments=segments,
                language=self.language,
                model_used=model_used,
                duration_seconds=elapsed,
            )

        except FileNotFoundError:
            elapsed = time.time() - start_time
            logger.error("音声ファイルが見つかりません: %s", audio_path)
            return TranscriptResult(
                success=False,
                language=self.language,
                model_used="",
                duration_seconds=elapsed,
            )
        except Exception:  # TDR登録済み: DP-02
            elapsed = time.time() - start_time
            logger.exception("文字起こし中に予期しないエラーが発生")
            return TranscriptResult(
                success=False,
                language=self.language,
                model_used="",
                duration_seconds=elapsed,
            )

    def _transcribe_with_whisper(
        self, audio_path: str
    ) -> list[TranscriptSegment]:
        """faster-whisperで音声を文字起こしする。

        Args:
            audio_path: 音声ファイルのパス

        Returns:
            文字起こしセグメントのリスト
        """
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]

        model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        raw_segments, _info = model.transcribe(
            audio_path, language=self.language
        )

        segments: list[TranscriptSegment] = []
        for seg in raw_segments:
            segments.append(
                TranscriptSegment(
                    start=seg.start,
                    end=seg.end,
                    text=seg.text.strip(),
                    confidence=getattr(seg, "avg_logprob", 0.0),
                )
            )

        return segments

    def _generate_fallback_transcript(
        self, audio_path: str
    ) -> list[TranscriptSegment]:
        """フォールバック: ffprobeで音声長を取得しダミーセグメントを生成する。

        10秒ごとに「[文字起こし未実行]」セグメントを生成する。

        Args:
            audio_path: 音声ファイルのパス

        Returns:
            ダミーの文字起こしセグメントのリスト
        """
        duration = self._get_audio_duration(audio_path)
        if duration <= 0:
            logger.warning("音声長が取得できません: %s", audio_path)
            return []

        segment_length = 10.0
        segments: list[TranscriptSegment] = []
        current = 0.0

        while current < duration:
            end = min(current + segment_length, duration)
            segments.append(
                TranscriptSegment(
                    start=current,
                    end=end,
                    text="[文字起こし未実行]",
                    confidence=0.0,
                )
            )
            current = end

        logger.info(
            "フォールバックセグメント生成: %d 個 (duration=%.1f秒)",
            len(segments), duration,
        )
        return segments

    def _get_audio_duration(self, audio_path: str) -> float:
        """ffprobeで音声ファイルの長さ（秒）を取得する。

        Args:
            audio_path: 音声ファイルのパス

        Returns:
            音声の長さ（秒）。取得失敗時は 0.0
        """
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "json",
            audio_path,
        ]
        try:
            result = self._run_ffmpeg(cmd)
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0.0))
        except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError):
            logger.warning("ffprobeによる音声長取得に失敗: %s", audio_path)
            return 0.0

    def _is_stable_ts_available(self) -> bool:
        """stable-tsが利用可能かどうかを動的にチェックする。

        Returns:
            stable-tsがインポート可能かつ利用可能であれば True
        """
        try:
            from backend.video_pipeline.stable_ts_wrapper import StableTsWrapper
            return StableTsWrapper.is_available()
        except ImportError:
            return False

    def _transcribe_with_stable_ts(
        self, audio_path: str
    ) -> list[TranscriptSegment]:
        """stable-tsで音声を文字起こしする。

        Args:
            audio_path: 音声ファイルのパス

        Returns:
            文字起こしセグメントのリスト
        """
        from backend.video_pipeline.stable_ts_wrapper import StableTsWrapper

        wrapper = StableTsWrapper(model_name=self.model_name, language=self.language)
        return wrapper.transcribe(audio_path)

    def _is_whisper_available(self) -> bool:
        """faster-whisperが利用可能かどうかを動的にチェックする。

        Returns:
            faster-whisperがインポート可能であれば True
        """
        try:
            import faster_whisper  # type: ignore[import-untyped] # noqa: F401
            return True
        except ImportError:
            return False

    def _run_ffmpeg(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """FFmpeg/ffprobeコマンドを実行する。

        テスト時は safe_popen_mock でこのメソッドをモックすることで、
        実際のFFmpeg実行を回避できる。

        subprocess.Popenモック安全規約:
          - poll() は return_value=0 で即座に終了コードを返すこと
          - readline() は空文字列 "" を返すこと

        Args:
            cmd: 実行するコマンドのリスト

        Returns:
            subprocess.CompletedProcess: 実行結果

        Raises:
            subprocess.CalledProcessError: コマンドが非ゼロ終了した場合
        """
        logger.info("FFmpegコマンド実行: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("FFmpegコマンド完了 (returncode=%d)", result.returncode)
        return result


if __name__ == "__main__":
    # 動作確認用のサンプルコード
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("使用方法: python transcription_service.py <音声ファイルパス>")
        sys.exit(1)

    service = TranscriptionService()
    result = service.transcribe(sys.argv[1])
    print(f"文字起こし結果: success={result.success}, "
          f"segments={len(result.segments)}, model={result.model_used}")
    for seg in result.segments[:5]:
        print(f"  [{seg.start:.1f}-{seg.end:.1f}] {seg.text}")
