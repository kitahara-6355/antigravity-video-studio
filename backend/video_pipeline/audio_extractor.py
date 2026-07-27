"""
audio_extractor.py — S2: 音声抽出ステージ

動画ファイルから音声トラックを抽出し、WAV形式で出力するパイプラインステージ。
FFmpeg呼び出しは _run_ffmpeg() メソッドに分離し、テスト時にモック可能な設計。

subprocess.Popenモック安全規約:
  - poll() は return_value=0 で即座に終了コードを返すこと
  - readline() は空文字列 "" を返すこと
  - conftest.py の safe_popen_mock fixture を使用すること
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データクラス定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class AudioResult:
    """音声抽出結果。

    Attributes:
        success: 抽出成功フラグ
        audio_path: 出力された音声ファイルのパス
        format: 音声フォーマット (例: "wav", "mp3")
        sample_rate: サンプリングレート (Hz)
        channels: チャンネル数
        duration_seconds: 音声の長さ（秒）
        error: エラーメッセージ（失敗時のみ）
    """

    success: bool = False
    audio_path: str = ""
    format: str = ""
    sample_rate: int = 0
    channels: int = 0
    duration_seconds: float = 0.0
    error: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AudioExtractor クラス
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AudioExtractor:
    """S2: 音声抽出ステージ。

    動画ファイルから音声トラックを抽出し、PCM WAV形式（16bit, 44100Hz）で
    出力する。チャンネル分離機能も提供。

    FFmpeg呼び出しは _run_ffmpeg() メソッドに分離し、
    テスト時に safe_popen_mock でモック可能。

    Args:
        output_dir: 音声ファイルの出力先ディレクトリ（省略時はカレントディレクトリ）
    """

    def __init__(self, output_dir: Optional[str] = None) -> None:
        """AudioExtractorを初期化する。

        Args:
            output_dir: 音声ファイルの出力先ディレクトリ
        """
        self.output_dir: str = output_dir or os.getcwd()
        # 出力ディレクトリが存在しない場合は作成
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def extract(self, video_path: str) -> AudioResult:
        """動画ファイルから音声を抽出する。

        FFmpegを使用して動画から音声トラックを抽出し、
        PCM WAV形式（16bit, 44100Hz）で出力する。

        Args:
            video_path: 音声を抽出する動画ファイルのパス

        Returns:
            AudioResult: 抽出結果
        """
        input_path = Path(video_path)

        # 入力ファイル存在確認
        if not input_path.exists():
            logger.error("入力ファイルが存在しません: %s", video_path)
            return AudioResult(
                success=False,
                error=f"入力ファイルが存在しません: {video_path}",
            )

        # 音声ストリーム情報の取得
        audio_info = self._get_audio_stream_info(str(input_path))
        if not audio_info:
            logger.error("音声ストリームが含まれていないか、取得に失敗しました: %s", video_path)
            return AudioResult(
                success=False,
                error=f"音声ストリームが含まれていないか、取得に失敗しました: {video_path}",
            )

        output_path = Path(self.output_dir) / f"{input_path.stem}_audio.wav"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            str(output_path),
        ]

        logger.info("音声抽出開始: %s -> %s", video_path, output_path)

        try:
            self._run_ffmpeg(cmd)
        except Exception as e:
            # TDR登録済み: ACCEPTED_SAFETY / DP-02
            logger.error("FFmpegによる音声抽出に失敗しました: %s", e)
            return AudioResult(
                success=False,
                error=f"音声抽出に失敗しました: {e}",
            )

        duration = 0.0
        try:
            duration = float(audio_info.get("duration", 0.0))
        except (ValueError, TypeError):
            pass

        return AudioResult(
            success=True,
            audio_path=str(output_path),
            format="wav",
            sample_rate=44100,
            channels=2,
            duration_seconds=duration,
        )

    def split_channels(self, audio_path: str) -> list[str]:
        """音声ファイルを個別チャンネルに分離する。

        ステレオ音声をL/Rチャンネルに分離し、それぞれ別ファイルとして出力する。

        Args:
            audio_path: チャンネル分離対象 of 音声ファイルパス

        Returns:
            list[str]: 分離された各チャンネルの音声ファイルパスのリスト
        """
        input_path = Path(audio_path)

        if not input_path.exists():
            logger.error("音声ファイルが存在しません: %s", audio_path)
            return []

        channel_paths: list[str] = []

        # Lチャンネル抽出
        left_path = Path(self.output_dir) / f"{input_path.stem}_ch_left.wav"
        cmd_left = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-filter_complex", "channelsplit=channel_layout=stereo:channels=FL[left]",
            "-map", "[left]",
            str(left_path),
        ]

        # Rチャンネル抽出
        right_path = Path(self.output_dir) / f"{input_path.stem}_ch_right.wav"
        cmd_right = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-filter_complex", "channelsplit=channel_layout=stereo:channels=FR[right]",
            "-map", "[right]",
            str(right_path),
        ]

        try:
            self._run_ffmpeg(cmd_left)
            channel_paths.append(str(left_path))
            logger.info("Lチャンネル抽出完了: %s", left_path)

            self._run_ffmpeg(cmd_right)
            channel_paths.append(str(right_path))
            logger.info("Rチャンネル抽出完了: %s", right_path)
        except Exception as e:
            # TDR登録済み: ACCEPTED_SAFETY / DP-02
            logger.error("チャンネル分離に失敗しました: %s", e)
            return channel_paths

        return channel_paths

    def _run_ffmpeg(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """FFmpegコマンドを実行する。

        テスト時は safe_popen_mock でこのメソッドをモックすることで、
        実際のFFmpeg実行を回避できる。

        Args:
            cmd: 実行するコマンドのリスト

        Returns:
            subprocess.CompletedProcess: 実行結果

        Raises:
            subprocess.CalledProcessError: FFmpegが非ゼロ終了した場合
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

    def _run_ffprobe(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """ffprobeコマンドを実行する。

        テスト時は safe_popen_mock や Patch でこのメソッドをモック可能。

        Args:
            cmd: 実行するコマンドのリスト

        Returns:
            subprocess.CompletedProcess: 実行結果
        """
        logger.info("ffprobeコマンド実行: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("ffprobeコマンド完了 (returncode=%d)", result.returncode)
        return result

    def _get_audio_stream_info(self, file_path: str) -> Optional[dict]:
        """ファイルから音声ストリームの情報を取得する。

        Args:
            file_path: 解析対象ファイルパス

        Returns:
            Optional[dict]: 音声ストリーム情報。存在しないか失敗時は None。
        """
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type,duration,sample_rate,channels",
            "-of", "json",
            str(file_path)
        ]
        try:
            res = self._run_ffprobe(cmd)
            import json
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            if not streams:
                return None
            return streams[0]
        except Exception as e:
            # TDR登録対象: ACCEPTED_SAFETY / DP-02
            logger.warning("ffprobeの実行または解析に失敗しました: %s", e)
            return None


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("使用方法: python audio_extractor.py <動画ファイルパス>")
        sys.exit(1)

    extractor = AudioExtractor(output_dir="./output")
    result = extractor.extract(sys.argv[1])
    print(f"抽出結果: success={result.success}, path={result.audio_path}")
    if result.error:
        print(f"エラー: {result.error}")
