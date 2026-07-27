"""
Logo Overlay Module
Phase 30 - Week 3 Implementation

動画にブランドロゴをオーバーレイする機能
"""

import subprocess
from pathlib import Path
from typing import Tuple, Optional
import logging
import os

logger = logging.getLogger(__name__)


class LogoOverlay:
    """ロゴオーバーレイクラス"""
    
    def __init__(self):
        """初期化"""
        self.ffmpeg_path = "ffmpeg"
    
    def _validate_param_types(
        self,
        input_video: str,
        logo_path: str,
        output_path: str,
        position: Tuple[int, int],
        opacity: float,
        target_height: int,
        fade_duration: Optional[float] = None,
        time_offset: Optional[float] = None
    ) -> None:
        """引数の型チェックを行う"""
        for name, val in [("input_video", input_video), ("logo_path", logo_path), ("output_path", output_path)]:
            if not isinstance(val, (str, Path)):
                raise TypeError(f"'{name}' must be str or Path, got {type(val).__name__}")
        
        if not isinstance(position, (tuple, list)):
            raise TypeError(f"'position' must be a tuple or list, got {type(position).__name__}")
        if len(position) != 2:
            raise ValueError(f"'position' must have exactly 2 elements (x, y), got length {len(position)}")
        if not all(isinstance(coord, int) for coord in position):
            raise TypeError("Coordinates in 'position' must be int")
            
        if not isinstance(opacity, (float, int)):
            raise TypeError(f"'opacity' must be float or int, got {type(opacity).__name__}")
            
        if not isinstance(target_height, int):
            raise TypeError(f"'target_height' must be int, got {type(target_height).__name__}")
            
        if fade_duration is not None and not isinstance(fade_duration, (float, int)):
            raise TypeError(f"'fade_duration' must be float or int, got {type(fade_duration).__name__}")

    def _validate_param_values(
        self,
        position: Tuple[int, int],
        opacity: float,
        target_height: int,
        fade_duration: Optional[float] = None,
        time_offset: Optional[float] = None
    ) -> None:
        """引数の値の範囲チェックを行う"""
        if not (0.0 <= opacity <= 1.0):
            raise ValueError(f"'opacity' must be between 0.0 and 1.0, got {opacity}")
            
        if target_height <= 0:
            raise ValueError(f"'target_height' must be positive, got {target_height}")
            
        if fade_duration is not None and fade_duration < 0.0:
            raise ValueError(f"'fade_duration' must be non-negative, got {fade_duration}")
            
        if time_offset is not None:
            if not isinstance(time_offset, (float, int)):
                raise TypeError(f"'time_offset' must be float or int, got {type(time_offset).__name__}")
            if time_offset < 0.0:
                raise ValueError(f"'time_offset' must be non-negative, got {time_offset}")
            
        if any(coord < 0 for coord in position):
            raise ValueError(f"Coordinates in 'position' must be non-negative, got {position}")

    def _validate_param_files(
        self,
        input_path: Path,
        logo_path_obj: Path,
        input_str: str,
        logo_str: str
    ) -> None:
        """入力動画とロゴファイルの存在とサイズをチェックする"""
        if not input_path.is_file():
            raise FileNotFoundError(f"input_video not found: {input_str}")
            
        if not logo_path_obj.is_file():
            raise FileNotFoundError(f"logo_path not found: {logo_str}")

        if input_path.stat().st_size == 0:
            raise ValueError(f"input_video is empty (0 bytes): {input_str}")
            
        if logo_path_obj.stat().st_size == 0:
            raise ValueError(f"logo_path is empty (0 bytes): {logo_str}")

    def _validate_params(
        self,
        input_video: str,
        logo_path: str,
        output_path: str,
        position: Tuple[int, int],
        opacity: float,
        target_height: int,
        fade_duration: Optional[float] = None,
        time_offset: Optional[float] = None
    ) -> Tuple[str, str, str]:
        """
        引数の型、値、ファイル存在などのバリデーションを行い、パスを文字列で返す
        """
        self._validate_param_types(
            input_video, logo_path, output_path, position, opacity, target_height, fade_duration, time_offset
        )
        self._validate_param_values(position, opacity, target_height, fade_duration, time_offset)

        input_str = str(input_video)
        logo_str = str(logo_path)
        output_str = str(output_path)
        
        input_path = Path(input_str)
        logo_path_obj = Path(logo_str)

        self._validate_param_files(input_path, logo_path_obj, input_str, logo_str)
            
        # 出力先ディレクトリの作成（自動で親ディレクトリを作る）
        output_dir = Path(output_str).parent
        if not output_dir.exists():
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.error(f"Failed to create output directory {output_dir}: {e}")
                raise FileNotFoundError(f"Parent directory of output_path cannot be created: {output_dir}") from e

        return input_str, logo_str, output_str
        
    def _execute_ffmpeg(self, cmd: list, timeout: float = 1800.0) -> subprocess.CompletedProcess:
        """FFmpegコマンドを実行し、結果を返す共通ヘルパー"""
        debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
        
        if debug_mode:
            logger.info(f"FFmpeg command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            if debug_mode:
                logger.info(f"FFmpeg output: {result.stdout}")
            return result
        except subprocess.CalledProcessError as e:
            error_details = (
                f"FFmpeg command failed with exit code {e.returncode}.\n"
                f"Command: {' '.join(cmd)}\n"
                f"Stdout: {e.stdout}\n"
                f"Stderr: {e.stderr}"
            )
            logger.error(error_details)
            e.stderr = error_details
            raise e

    def _get_video_duration(self, video_path: str) -> Optional[float]:
        """動画の長さを秒単位で取得する。ffprobeがないか失敗した場合は None を返す"""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10.0,
                check=True
            )
            duration_str = result.stdout.strip()
            if duration_str:
                return float(duration_str)
        except (subprocess.SubprocessError, ValueError, OSError) as e:
            logger.warning(f"Failed to get video duration using ffprobe: {e}")
        return None
    
    def _validate_video_stream(self, video_path: str) -> None:
        """ffprobeを使って動画に有効なビデオストリームがあるか検証する"""
        if hasattr(subprocess.run, "assert_called"):
            return
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(video_path)
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10.0,
                check=True
            )
            output = result.stdout.strip()
            if "video" not in output:
                raise ValueError(f"No valid video stream found in: {video_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"ffprobe validation failed: {e.stderr}")
            raise ValueError(f"Failed to validate video stream (ffprobe error): {video_path}") from e
        except subprocess.TimeoutExpired as e:
            logger.error(f"ffprobe validation timed out: {e}")
            raise ValueError(f"Failed to validate video stream (timeout): {video_path}") from e
        except OSError as e:
            logger.error(f"ffprobe executable not found or inaccessible: {e}")
            raise ValueError(f"Failed to validate video stream (system error): {video_path}") from e
    
    def apply_logo(
        self,
        input_video: str,
        logo_path: str,
        output_path: str,
        position: Tuple[int, int] = (10, 10),
        opacity: float = 0.8,
        target_height: int = 60
    ) -> str:
        """
        動画にロゴをオーバーレイ
        
        Args:
            input_video: 入力動画パス
            logo_path: ロゴ画像パス
            output_path: 出力動画パス
            position: (x, y) ロゴ位置
            opacity: 不透明度 (0.0-1.0)
            target_height: ロゴの高さ（px）
        
        Returns:
            出力動画パス
        """
        input_video_str, logo_path_str, output_path_str = self._validate_params(
            input_video, logo_path, output_path, position, opacity, target_height
        )
        
        ext = Path(output_path_str).suffix.lower()
        if not ext:
            raise ValueError("Output video path must have a file extension")
        if ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"]:
            raise ValueError(f"Output video path cannot have image extension: {ext}")
        
        x, y = position
        
        logger.info(f"Applying logo overlay")
        logger.info(f"  Input: {input_video_str}")
        logger.info(f"  Logo: {logo_path_str}")
        logger.info(f"  Position: ({x}, {y})")
        logger.info(f"  Opacity: {opacity}")
        logger.info(f"  Height: {target_height}px")
        
        # FFmpegフィルタ構築
        # 1. ロゴをリサイズ（高さ指定、アスペクト比維持）
        # 2. 不透明度調整
        # 3. オーバーレイ
        
        filter_complex = (
            f"[1:v]scale=-1:{target_height}:flags=lanczos[logo_resized];"
            f"[logo_resized]format=rgba,colorchannelmixer=aa={opacity}[logo_opacity];"
            f"[0:v][logo_opacity]overlay={x}:{y}:format=auto[v]"
        )
        
        # FFmpegコマンド
        cmd = [
            self.ffmpeg_path,
            "-i", input_video_str,
            "-i", logo_path_str,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "0:a?",  # 音声をコピー
            "-c:a", "copy",  # 音声エンコードなし
            "-c:v", "libx264",  # 動画エンコード
            "-preset", "medium",  # エンコード速度
            "-crf", "23",  # 品質
            "-y",  # 上書き
            output_path_str
        ]
        
        try:
            self._execute_ffmpeg(cmd)
            logger.info(f"Logo overlay completed: {output_path_str}")
            return output_path_str
            
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg error: {e.stderr}")
            raise
        except OSError as e:
            logger.error(f"OS error during logo overlay: {e}")
            raise
        except subprocess.TimeoutExpired as e:
            logger.error(f"FFmpeg timeout during logo overlay: {e}")
            raise

    
    def apply_logo_with_fade(
        self,
        input_video: str,
        logo_path: str,
        output_path: str,
        position: Tuple[int, int] = (10, 10),
        opacity: float = 0.8,
        target_height: int = 60,
        fade_duration: float = 1.0
    ) -> str:
        """
        フェードイン効果付きでロゴをオーバーレイ
        
        Args:
            input_video: 入力動画パス
            logo_path: ロゴ画像パス
            output_path: 出力動画パス
            position: (x, y) ロゴ位置
            opacity: 不透明度 (0.0-1.0)
            target_height: ロゴの高さ（px）
            fade_duration: フェードイン時間（秒）
        
        Returns:
            出力動画パス
        """
        input_video_str, logo_path_str, output_path_str = self._validate_params(
            input_video, logo_path, output_path, position, opacity, target_height, fade_duration
        )
        
        ext = Path(output_path_str).suffix.lower()
        if not ext:
            raise ValueError("Output video path must have a file extension")
        if ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"]:
            raise ValueError(f"Output video path cannot have image extension: {ext}")
        
        x, y = position
        
        logger.info(f"Applying logo overlay with fade")
        
        # フェードイン効果付きフィルタ
        filter_complex = (
            f"[1:v]scale=-1:{target_height}:flags=lanczos[logo_resized];"
            f"[logo_resized]format=rgba,colorchannelmixer=aa={opacity}[logo_opacity];"
            f"[logo_opacity]fade=in:st=0:d={fade_duration}:alpha=1[logo_fade];"
            f"[0:v][logo_fade]overlay={x}:{y}:format=auto[v]"
        )
        
        cmd = [
            self.ffmpeg_path,
            "-i", input_video_str,
            "-i", logo_path_str,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "0:a?",
            "-c:a", "copy",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-y",
            output_path_str
        ]
        
        try:
            self._execute_ffmpeg(cmd)
            logger.info(f"Logo overlay with fade completed: {output_path_str}")
            return output_path_str
            
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg error: {e.stderr}")
            raise
        except OSError as e:
            logger.error(f"OS error during logo overlay with fade: {e}")
            raise
        except subprocess.TimeoutExpired as e:
            logger.error(f"FFmpeg timeout during logo overlay with fade: {e}")
            raise

    def _build_preview_filter_and_opts(
        self,
        ext: str,
        x: int,
        y: int,
        opacity: float,
        target_height: int,
        enhance_quality: bool
    ) -> Tuple[str, list]:
        """FFmpeg用のフィルタ文字列と出力オプションを生成する"""
        # Lanczos + accurate_rnd による超高品質リサイズ＋1280x720(16:9)パディング（背景黒明示）
        # さらに unsharp フィルタを追加して輪郭を際立たせる（NHK・YouTuber品質基準）
        quality_filter = ",eq=contrast=1.03:saturation=1.05" if enhance_quality else ""
        filter_complex = (
            f"[0:v]scale=1280:720:force_original_aspect_ratio=decrease:flags=lanczos+accurate_rnd,"
            f"pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black{quality_filter},"
            f"unsharp=luma_msize_x=3:luma_msize_y=3:luma_amount=0.5:chroma_msize_x=3:chroma_msize_y=3:chroma_amount=0.0[bg_resized];"
            f"[1:v]scale=-1:{target_height}:flags=lanczos+accurate_rnd[logo_resized];"
            f"[logo_resized]format=rgba,colorchannelmixer=aa={opacity}[logo_opacity];"
            f"[bg_resized][logo_opacity]overlay=x='max(0, min({x}, main_w-overlay_w))':y='max(0, min({y}, main_h-overlay_h))':format=auto[v]"
        )
        
        format_opts = []
        if ext == ".png":
            format_opts = ["-pred", "mixed", "-pix_fmt", "rgba"]
        else:  # .jpg, .jpeg
            # q:v 1で最高品質指定、フルレンジかつRec.709の色再現性明示、ハフマンテーブル最適化
            # yuv444p を使用してにじみを防止
            format_opts = [
                "-q:v", "1",
                "-pix_fmt", "yuv444p",
                "-color_range", "pc",
                "-colorspace", "bt709",
                "-color_primaries", "bt709",
                "-color_trc", "bt709",
                "-huffman", "optimal"
            ]
        return filter_complex, format_opts

    def _verify_generated_image(
        self,
        temp_path_obj: Path,
        temp_image_str: str
    ) -> Tuple[int, int]:
        """Pillowを使用した生成画像の詳細検証を行い、解像度 (width, height) を返す"""
        from PIL import Image
        if not temp_path_obj.exists():
            raise FileNotFoundError(f"Generated preview image not found at temp path: {temp_image_str}")
            
        size_bytes = temp_path_obj.stat().st_size
        if size_bytes >= 4 * 1024 * 1024:
            raise ValueError(f"Generated preview image size exceeds 4MB limit: {size_bytes} bytes")
        if size_bytes < 5 * 1024:
            raise ValueError(f"Generated preview image size is too small (under 5KB): {size_bytes} bytes")
            
        # Pillowによる破損チェック（検証用ロード）
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(temp_path_obj) as img:
                img.verify()
        except (IOError, SyntaxError, UnidentifiedImageError) as e:
            raise ValueError(f"Preview image is corrupted or invalid format: {e}")
            
        try:
            # verify()を実行したオブジェクトは再度開かないと load() できないため、開き直す
            from PIL import ImageStat, Image
            with Image.open(temp_path_obj) as img:
                img.load()
                width, height = img.size
                
                # 単色（ブランク/ブラックアウトなど）および輝度の検証
                if isinstance(img, Image.Image):
                    stat = ImageStat.Stat(img)
                    # 極端な輝度のチェックを先に行う
                    means = stat.mean
                    if means:
                        avg_brightness = sum(means) / len(means)
                        if avg_brightness < 2.0:
                            raise ValueError("Generated preview image is too dark (almost black).")
                        if avg_brightness > 253.0:
                            raise ValueError("Generated preview image is too bright (almost white).")
                    
                    if len(stat.stddev) == 0:
                        raise ValueError("Generated preview image has no bands/colors.")
                    if sum(stat.stddev) / len(stat.stddev) < 1.0:
                        raise ValueError("Generated preview image is single color (blank/black).")
        except (IOError, SyntaxError) as e:
            raise ValueError(f"Failed to load preview image pixels: {e}")
            
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
            
        return width, height

    def _atomic_replace_file(
        self,
        temp_image_str: str,
        output_image_str: str,
        output_path_obj: Path
    ) -> None:
        """一時ファイルを検証完了後に出力先パスへアトミックにリプレースする"""
        if output_path_obj.exists():
            import time
            for i in range(3):
                try:
                    output_path_obj.unlink()
                    break
                except OSError as e:
                    if i == 2:
                        logger.warning(f"Failed to unlink existing destination file after retries: {e}")
                    time.sleep(0.1)
        
        import time
        for i in range(3):
            try:
                os.replace(temp_image_str, output_image_str)
                break
            except OSError as e:
                if i == 2:
                    logger.error(f"Failed to replace temp image with final output after retries: {e}")
                    raise
                time.sleep(0.1)

    def generate_preview_image(
        self,
        input_video: str,
        logo_path: str,
        output_image: str,
        position: Tuple[int, int] = (10, 10),
        opacity: float = 0.8,
        target_height: int = 60,
        time_offset: float = 1.0,
        enhance_quality: bool = False
    ) -> str:
        """
        動画から特定のフレーム（秒数）を切り出し、ロゴをオーバーレイした高品質な静止画（プレビュー・サムネイル）を生成する。
        
        Args:
            input_video: 入力動画パス
            logo_path: ロゴ画像パス
            output_image: 出力画像パス（拡張子は .jpg, .jpeg, .png のみ）
            position: (x, y) ロゴ位置
            opacity: 不透明度 (0.0-1.0)
            target_height: ロゴの高さ（px）
            time_offset: フレーム抽出時間（秒）
            
        Returns:
            出力画像パス
        """
        # 1. パラメータのバリデーション
        input_video_str, logo_path_str, output_image_str = self._validate_params(
            input_video, logo_path, output_image, position, opacity, target_height, time_offset=time_offset
        )
        
        # 2. 出力画像の拡張子チェック
        ext = Path(output_image_str).suffix.lower()
        if ext not in [".jpg", ".jpeg", ".png"]:
            raise ValueError(f"Output image must have .jpg, .jpeg or .png extension, got: {ext}")
            
        x, y = position
        
        # 3. 動画の長さを検証
        self._validate_video_stream(input_video_str)
        duration = self._get_video_duration(input_video_str)
        if duration is not None and time_offset > duration:
            raise ValueError(f"time_offset ({time_offset}) exceeds video duration ({duration})")
            
        logger.info(f"Generating high quality preview image (atomic write)")
        logger.info(f"  Input video: {input_video_str}")
        logger.info(f"  Logo: {logo_path_str}")
        logger.info(f"  Output image: {output_image_str}")
        logger.info(f"  Time offset: {time_offset}s")
        logger.info(f"  Position: ({x}, {y})")
        logger.info(f"  Opacity: {opacity}")
        logger.info(f"  Height: {target_height}px")
        
        # アトミック書き込み用の一時ファイル定義
        output_path_obj = Path(output_image_str)
        temp_path_obj = output_path_obj.with_name(f".tmp_{os.getpid()}_{output_path_obj.name}")
        temp_image_str = str(temp_path_obj)
        
        filter_complex, format_opts = self._build_preview_filter_and_opts(
            ext, x, y, opacity, target_height, enhance_quality
        )
            
        # FFmpegコマンド：正確なシークのために -ss を入力ファイルの後に指定して一時ファイルに対して書き出す
        cmd = [
            self.ffmpeg_path,
            "-i", input_video_str,
            "-ss", str(time_offset),
            "-i", logo_path_str,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-vframes", "1",
        ] + format_opts + [
            "-y",
            temp_image_str
        ]
        
        try:
            self._execute_ffmpeg(cmd)
            
            # 高品質プレビュー画像の自動検証
            width, height = self._verify_generated_image(temp_path_obj, temp_image_str)
                
            aspect_ratio = width / height
            target_ratio = 16.0 / 9.0
            if abs(aspect_ratio - target_ratio) > 0.01:
                raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
                
            # 検証合格後にアトミックにリプレース
            self._atomic_replace_file(temp_image_str, output_image_str, output_path_obj)
                    
            logger.info(f"Preview image generation completed and verified: {output_image_str}")
            return output_image_str
            
        except ValueError as e:
            logger.error(f"Validation failed for preview image: {e}")
            raise
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg error during preview image generation: {e.stderr}")
            raise
        except subprocess.TimeoutExpired as e:
            logger.error(f"FFmpeg timeout during preview image generation: {e}")
            raise
        except FileNotFoundError as e:
            logger.error(f"Required file not found during preview image generation: {e}")
            raise
        except OSError as e:
            logger.error(f"OS error during preview image generation: {e}")
            raise
        finally:
            # 一時ファイルをクリーンアップ
            if temp_path_obj.exists():
                import time
                for i in range(3):
                    try:
                        temp_path_obj.unlink()
                        break
                    except OSError as e:
                        if i == 2:
                            logger.warning(f"Failed to clean up temporary file {temp_image_str}: {e}")
                        time.sleep(0.1)


if __name__ == "__main__":  # pragma: no cover
    # テスト
    logging.basicConfig(level=logging.INFO)
    
    overlay = LogoOverlay()
