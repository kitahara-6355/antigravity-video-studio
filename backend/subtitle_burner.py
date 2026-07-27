"""
Subtitle Burn-in Tool
字幕を動画に焼き込む（シンプル版）
"""

import subprocess
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _validate_inputs(input_video: str, srt_file: str) -> None:
    """入力ファイルが存在するか検証する"""
    if not Path(input_video).exists():
        logger.error(f"Input video file not found: {input_video}")
        raise FileNotFoundError(f"Input video file not found: {input_video}")
    if not Path(srt_file).exists():
        logger.error(f"SRT subtitle file not found: {srt_file}")
        raise FileNotFoundError(f"SRT subtitle file not found: {srt_file}")


def _get_subtitle_style() -> str:
    """テンプレート構成から字幕スタイルを取得する。取得できない場合はデフォルトスタイルを返す"""
    try:
        from template_config import template_config
        return template_config.get_subtitle_style()
    except (ImportError, AttributeError):
        return "FontSize=40,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,FontName=Yu Gothic UI,MarginV=72"


def _escape_srt_path(srt_file: str) -> str:
    """Windows環境などに対応するため、SRTファイルパスのエスケープ処理を行う"""
    escaped = srt_file.replace("\\", "/").replace(":", "\\:")
    return escaped.replace("'", "'\\\\''")


def _build_ffmpeg_command(input_video: str, srt_escaped: str, subtitle_style: str, output_video: str) -> list[str]:
    """FFmpegの実行コマンドリストを構築する"""
    return [
        "ffmpeg",
        "-i", input_video,
        "-vf", f"subtitles='{srt_escaped}':force_style='{subtitle_style}'",
        "-c:a", "copy",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-y",
        output_video
    ]


def _run_ffmpeg(cmd: list[str], output_video: str) -> str:
    """FFmpegコマンドを実行し、完了通知や例外ハンドリングを行う"""
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=300
        )
        logger.info(f"✅ Subtitle burned: {output_video}")
        return output_video
    except subprocess.TimeoutExpired:
        logger.error("Timeout: 字幕焼き込みが5分以内に完了しませんでした")
        raise
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr[:500]}")
        raise
    except FileNotFoundError as e:
        logger.error(f"FFmpeg command not found. Please ensure FFmpeg is installed and added to PATH. Details: {e}")
        raise
    except OSError as e:
        logger.error(f"OS error occurred while running FFmpeg: {e}")
        raise


def burn_subtitle_simple(
    input_video: str,
    srt_file: str,
    output_video: str
) -> str:
    """
    字幕を動画に焼き込む（シンプル版）
    
    Args:
        input_video: 入力動画のパス
        srt_file: SRT字幕ファイルのパス
        output_video: 出力動画のパス
    """
    logger.info("Burning subtitles...")
    logger.info(f"  Video: {input_video}")
    logger.info(f"  SRT: {srt_file}")
    
    _validate_inputs(input_video, srt_file)
    subtitle_style = _get_subtitle_style()
    srt_escaped = _escape_srt_path(srt_file)
    cmd = _build_ffmpeg_command(input_video, srt_escaped, subtitle_style, output_video)
    return _run_ffmpeg(cmd, output_video)


if __name__ == "__main__":
    import sys
    
    # デフォルトのダミーパス（引数なし時のフォールバック）
    default_input = "input.mp4"
    default_srt = "subtitles.srt"
    default_output = "output.mp4"
    
    input_path = sys.argv[1] if len(sys.argv) > 1 else default_input
    srt_path = sys.argv[2] if len(sys.argv) > 2 else default_srt
    output_path = sys.argv[3] if len(sys.argv) > 3 else default_output
    
    if Path(input_path).exists() and Path(srt_path).exists():
        burn_subtitle_simple(input_path, srt_path, output_path)
        print(f"✅ Process complete: {output_path}")
    else:
        print("❌ Required input files not found. Usage: python subtitle_burner.py [<input_video> <srt_file> <output_video>]")

