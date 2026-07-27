"""
ingest_service.py — S1: 素材取込ステージ

動画・音声ファイルの入力検証、フォーマット正規化を行うパイプラインステージ。
FFmpeg呼び出しは _run_ffmpeg() メソッドに分離し、テスト時にモック可能な設計。

subprocess.Popenモック安全規約:
  - poll() は return_value=0 で即座に終了コードを返すこと
  - readline() は空文字列 "" を返すこと
  - conftest.py の safe_popen_mock fixture を使用すること
"""

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# サポート対象の拡張子
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3"}
SUPPORTED_EXTENSIONS = SUPPORTED_VIDEO_EXTENSIONS | SUPPORTED_AUDIO_EXTENSIONS


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データクラス定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class NormalizedMedia:
    """正規化済みメディアの情報。

    Attributes:
        path: 正規化後のファイルパス
        codec: 映像コーデック (例: libx264)
        resolution: 解像度 (例: "1920x1080")
        fps: フレームレート
        audio_codec: 音声コーデック (例: aac)
        audio_channels: 音声チャンネル数
    """

    path: str = ""
    codec: str = ""
    resolution: str = ""
    fps: float = 0.0
    audio_codec: str = ""
    audio_channels: int = 0


@dataclass
class IngestResult:
    """素材取込結果。

    Attributes:
        success: 取込成功フラグ
        original_path: 元ファイルパス
        normalized_path: 正規化後ファイルパス
        format_info: フォーマット情報の辞書
        duration_seconds: メディア長（秒）
        file_size_bytes: ファイルサイズ（バイト）
        error: エラーメッセージ（失敗時のみ）
    """

    success: bool = False
    original_path: str = ""
    normalized_path: str = ""
    format_info: dict = field(default_factory=dict)
    duration_seconds: float = 0.0
    file_size_bytes: int = 0
    error: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# IngestService クラス
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class IngestService:
    """S1: 素材取込ステージ。

    動画・音声ファイルの入力検証とフォーマット正規化を行う。
    FFmpeg呼び出しは _run_ffmpeg() メソッドに分離し、
    テスト時に safe_popen_mock でモック可能。

    Args:
        input_dir: 入力ディレクトリパス（省略時はカレントディレクトリ）
        output_dir: 出力ディレクトリパス（省略時はカレントディレクトリ）
    """

    def __init__(self, input_dir: Optional[str] = None, output_dir: Optional[str] = None) -> None:
        """IngestServiceを初期化する。

        Args:
            input_dir: 入力ディレクトリパス
            output_dir: 出力ディレクトリパス
        """
        self.input_dir: str = input_dir or os.getcwd()
        self.output_dir: str = output_dir or os.getcwd()
        # 出力ディレクトリが存在しない場合は作成
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def validate_input(self, file_path: str) -> IngestResult:
        """入力ファイルの存在確認と拡張子チェックを行う。

        Args:
            file_path: 検証対象のファイルパス

        Returns:
            IngestResult: 検証結果。successフラグとエラー情報を含む
        """
        path = Path(file_path)

        # ファイル存在確認
        if not path.exists():
            logger.error("ファイルが存在しません: %s", file_path)
            return IngestResult(
                success=False,
                original_path=file_path,
                error=f"ファイルが存在しません: {file_path}",
            )

        # 拡張子チェック
        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            logger.error("サポートされていない拡張子です: %s (対応: %s)", ext, SUPPORTED_EXTENSIONS)
            return IngestResult(
                success=False,
                original_path=file_path,
                error=f"サポートされていない拡張子: {ext}",
            )

        # ファイルサイズ取得
        file_size = path.stat().st_size

        # 境界値: 0バイトファイル
        if file_size == 0:
            logger.error("ファイルサイズが0バイトです: %s", file_path)
            return IngestResult(
                success=False,
                original_path=file_path,
                file_size_bytes=file_size,
                error="ファイルサイズが0バイトです",
            )

        logger.info("入力ファイル検証OK: %s (%d bytes)", file_path, file_size)
        return IngestResult(
            success=True,
            original_path=file_path,
            file_size_bytes=file_size,
            format_info={"extension": ext},
        )

    def normalize_format(self, file_path: str) -> NormalizedMedia:
        """ファイルをH.264/AACフォーマットに正規化する。

        FFmpegを使用して入力ファイルを標準フォーマット（H.264映像 + AAC音声）に
        変換する。変換後のファイルは output_dir に出力される。

        Args:
            file_path: 正規化対象のファイルパス

        Returns:
            NormalizedMedia: 正規化後のメディア情報
        """
        input_path = Path(file_path)
        output_path = Path(self.output_dir) / f"{input_path.stem}_normalized.mp4"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-ac", "2",
            str(output_path),
        ]

        logger.info("フォーマット正規化開始: %s -> %s", file_path, output_path)

        try:
            self._run_ffmpeg(cmd)
        except Exception as e:
            # TDR登録済み: ACCEPTED_SAFETY / DP-02
            logger.error("FFmpegによる正規化に失敗しました: %s", e)
            return NormalizedMedia(path="", codec="", resolution="")

        return NormalizedMedia(
            path=str(output_path),
            codec="libx264",
            resolution="1920x1080",
            fps=30.0,
            audio_codec="aac",
            audio_channels=2,
        )

    def ingest(self, file_path: str) -> IngestResult:
        """素材取込のメインエントリポイント。

        入力検証 → フォーマット正規化 の順に処理を行い、
        最終的な IngestResult を返す。

        Args:
            file_path: 取込対象のファイルパス

        Returns:
            IngestResult: 取込結果
        """
        # 入力検証
        validation = self.validate_input(file_path)
        if not validation.success:
            return validation

        # フォーマット正規化
        normalized = self.normalize_format(file_path)
        if not normalized.path:
            return IngestResult(
                success=False,
                original_path=file_path,
                error="フォーマット正規化に失敗しました",
            )

        return IngestResult(
            success=True,
            original_path=file_path,
            normalized_path=normalized.path,
            format_info={
                "codec": normalized.codec,
                "resolution": normalized.resolution,
                "fps": normalized.fps,
                "audio_codec": normalized.audio_codec,
                "audio_channels": normalized.audio_channels,
            },
            duration_seconds=validation.duration_seconds,
            file_size_bytes=validation.file_size_bytes,
        )

    def _run_ffmpeg(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """FFmpegコマンドを実行する。

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
            subprocess.CalledProcessError: FFmpegが非ゼロ終了した場合
        """
        logger.info("FFmpegコマンド実行: %s", " ".join(cmd))
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        
        try:
            stdout, stderr = process.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            raise subprocess.SubprocessError("FFmpeg execution timed out")
            
        returncode = process.poll()
        if returncode is None:
            returncode = process.returncode or 0
            
        if returncode != 0:
            raise subprocess.CalledProcessError(
                returncode=returncode,
                cmd=cmd,
                output=stdout,
                stderr=stderr,
            )
            
        logger.info("FFmpegコマンド完了 (returncode=%d)", returncode)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )


if __name__ == "__main__":
    # 動作確認用のサンプルコード
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("使用方法: python ingest_service.py <入力ファイルパス>")
        sys.exit(1)

    service = IngestService(output_dir="./output")
    result = service.ingest(sys.argv[1])
    print(f"取込結果: success={result.success}, path={result.normalized_path}")
    if result.error:
        print(f"エラー: {result.error}")
