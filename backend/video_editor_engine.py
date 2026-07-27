"""
Video Editor Engine
FFmpeg連携による自動編集

機能:
- カット自動化
- マージ/結合
- テロップ焼き込み
- オープニング/エンディング追加
- トランジション適用
"""

import json
import logging
import subprocess
import shutil
import uuid
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

try:
    from safe_io import VAULT_OUTPUTS_DIR
    DEFAULT_OUTPUT_DIR = VAULT_OUTPUTS_DIR / "edited"
except ImportError:
    DEFAULT_OUTPUT_DIR = Path("output/edited")

logger = logging.getLogger(__name__)


class TransitionType(Enum):
    """トランジションタイプ"""
    CUT = "cut"
    FADE = "fade"
    DISSOLVE = "dissolve"
    WIPE = "wipe"


@dataclass
class VideoClip:
    """動画クリップ"""
    path: Path
    start_sec: float = 0
    end_sec: Optional[float] = None
    label: str = ""





class FFmpegEditor:
    """FFmpeg連携エディター（Phase D: GPU/NVENC対応）"""
    
    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or DEFAULT_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_path = self._find_ffmpeg()
        self.temp_dir = self.output_dir / ".temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.use_gpu = self._detect_gpu()
    
    def _resolve_ffprobe_path(self) -> Optional[str]:
        """ffmpegのパスから対応するffprobeのパスを解決"""
        if not self.ffmpeg_path:
            return None
        
        ffmpeg_path_obj = Path(self.ffmpeg_path)
        name = ffmpeg_path_obj.name
        
        if "ffmpeg.EXE" in name:
            new_name = name.replace("ffmpeg.EXE", "ffprobe.EXE")
        elif "ffmpeg.exe" in name:
            new_name = name.replace("ffmpeg.exe", "ffprobe.exe")
        elif "ffmpeg" in name:
            new_name = name.replace("ffmpeg", "ffprobe")
        else:
            new_name = name.replace("FFMPEG", "FFPROBE")
            
        ffprobe_path = ffmpeg_path_obj.with_name(new_name)
        if ffprobe_path.exists():
            return ffprobe_path.as_posix()
        return None

    def _get_drawtext_position(self, position: str) -> str:
        """位置指定からdrawtext用の座標設定文字列を解決"""
        positions = {
            "top": "x=(w-text_w)/2:y=50",
            "center": "x=(w-text_w)/2:y=(h-text_h)/2",
            "bottom": "x=(w-text_w)/2:y=h-text_h-50"
        }
        return positions.get(position, positions["bottom"])

    def _find_ffmpeg(self) -> Optional[str]:
        """FFmpegパスを探索"""
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            logger.info(f"FFmpeg found: {ffmpeg}")
            return ffmpeg
        
        # よくあるパス
        common_paths = [
            "C:/ffmpeg/bin/ffmpeg.exe",
            "C:/Program Files/ffmpeg/bin/ffmpeg.exe",
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg"
        ]
        
        for path in common_paths:
            if Path(path).exists():
                logger.info(f"FFmpeg found: {path}")
                return path
        
        logger.warning("FFmpeg not found in PATH")
        return None
    
    def _detect_gpu(self) -> bool:
        """NVIDIA NVENC 対応を自動検出（Phase D）"""
        if not self.ffmpeg_path:
            return False
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-encoders"],
                capture_output=True, text=True, timeout=10
            )
            has_nvenc = "h264_nvenc" in result.stdout
            if has_nvenc:
                logger.info("✅ GPU (NVENC) detected — hardware encoding enabled")
            else:
                logger.info("⚠️ NVENC not available — falling back to CPU encoding")
            return has_nvenc
        except (subprocess.SubprocessError, OSError, ValueError) as e:
            logger.warning(f"GPU detection failed: {e} — falling back to CPU")
            return False
    
    def _get_encode_args(self, quality: str = "balanced") -> List[str]:
        """
        GPU/CPU に応じたエンコード引数を返す（Phase D）
        
        Args:
            quality: "fast"(プレビュー用) / "balanced"(通常) / "quality"(最終出力)
        """
        presets = {
            "fast":     {"gpu": ["p1", "28"], "cpu": ["ultrafast", "28"]},
            "balanced": {"gpu": ["p4", "23"], "cpu": ["veryfast", "23"]},
            "quality":  {"gpu": ["p7", "18"], "cpu": ["slow", "18"]},
        }
        preset_cfg = presets.get(quality, presets["balanced"])
        
        if self.use_gpu:
            return [
                "-c:v", "h264_nvenc",
                "-preset", preset_cfg["gpu"][0],
                "-cq", preset_cfg["gpu"][1],
                "-c:a", "aac",
            ]
        else:
            return [
                "-c:v", "libx264",
                "-preset", preset_cfg["cpu"][0],
                "-crf", preset_cfg["cpu"][1],
                "-c:a", "aac",
            ]
    
    def _get_hwaccel_input_args(self) -> List[str]:
        """GPU デコードの入力引数を返す（Phase D）"""
        if self.use_gpu:
            return ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        return []
    
    def is_available(self) -> bool:
        """FFmpegが利用可能か"""
        return self.ffmpeg_path is not None
    
    def run_command(self, args: List[str], timeout: int = 600) -> Tuple[bool, str]:
        """FFmpegコマンドを実行"""
        if not self.is_available():
            return False, "FFmpeg not available"
        
        cmd = [self.ffmpeg_path] + args
        logger.info(f"Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr
                
        except subprocess.TimeoutExpired:
            return False, "Timeout"
        except (OSError, ValueError) as e:
            return False, str(e)
    
    def cut_video(self, 
                  input_path: Path, 
                  output_path: Path,
                  start_sec: float, 
                  end_sec: float,
                  reencode: bool = False) -> bool:
        """
        動画をカット
        
        Args:
            input_path: 入力ファイル
            output_path: 出力ファイル
            start_sec: 開始秒
            end_sec: 終了秒
            reencode: 再エンコードするか
        """
        if not Path(input_path).exists():
            raise FileNotFoundError(f"動画ファイルが見つかりません: {input_path}")
        duration = end_sec - start_sec
        
        if reencode:
            args = [
                "-y",
                *self._get_hwaccel_input_args(),
                "-i", str(input_path),
                "-ss", str(start_sec),
                "-t", str(duration),
                *self._get_encode_args(),
                str(output_path)
            ]
        else:
            # ストリームコピー（高速）
            args = [
                "-y",
                "-ss", str(start_sec),
                "-i", str(input_path),
                "-t", str(duration),
                "-c", "copy",
                str(output_path)
            ]
        
        success, _ = self.run_command(args)
        return success
    
    def merge_videos(self,
                     clips: List[VideoClip],
                     output_path: Path,
                     transition: TransitionType = TransitionType.CUT,
                     timeout: int = 1800) -> bool:
        """
        複数動画をマージ
        
        Args:
            clips: クリップリスト
            output_path: 出力ファイル
            transition: トランジションタイプ
        """
        if not clips:
            return False
        for clip in clips:
            if not Path(clip.path).exists():
                raise FileNotFoundError(f"動画ファイルが見つかりません: {clip.path}")
        
        # 一時ファイルリストを作成（並行実行の衝突を防ぐためユニーク名）
        list_file = self.temp_dir / f"concat_list_{uuid.uuid4().hex}.txt"
        
        try:
            with open(list_file, "w", encoding="utf-8") as f:
                for clip in clips:
                    # Windowsパスをエスケープ
                    path_str = str(clip.path).replace("\\", "/")
                    f.write(f"file '{path_str}'\n")
            
            if transition == TransitionType.CUT:
                # シンプル結合
                args = [
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(list_file),
                    "-c", "copy",
                    str(output_path)
                ]
            else:
                # トランジション付き（要再エンコード — GPU対応）
                args = [
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(list_file),
                    *self._get_encode_args(),
                    str(output_path)
                ]
            
            success, output = self.run_command(args, timeout=timeout)
            if not success:
                logger.error(f"merge_videos failed ({len(clips)} clips): {output[:500]}")
            return success
        finally:
            if list_file.exists():
                try:
                    list_file.unlink()
                except OSError as e:
                    logger.warning(f"Failed to delete concat list file {list_file}: {e}")
    
    def add_opening(self,
                    main_video: Path,
                    opening_video: Path,
                    output_path: Path) -> bool:
        """オープニングを追加"""
        clips = [
            VideoClip(path=opening_video, label="opening"),
            VideoClip(path=main_video, label="main")
        ]
        return self.merge_videos(clips, output_path)
    
    def add_ending(self,
                   main_video: Path,
                   ending_video: Path,
                   output_path: Path) -> bool:
        """エンディングを追加"""
        clips = [
            VideoClip(path=main_video, label="main"),
            VideoClip(path=ending_video, label="ending")
        ]
        return self.merge_videos(clips, output_path)
    
    def add_telop(self,
                  input_path: Path,
                  output_path: Path,
                  text: str,
                  position: str = "bottom",
                  start_sec: float = 0,
                  duration_sec: float = 5,
                  font_size: int = 48,
                  font_color: str = "white",
                  bg_color: str = "black@0.5") -> bool:
        """
        テロップを焼き込み
        
        Args:
            input_path: 入力ファイル
            output_path: 出力ファイル
            text: テロップテキスト
            position: 位置 (top, center, bottom)
            start_sec: 表示開始秒
            duration_sec: 表示時間
            font_size: フォントサイズ
            font_color: フォント色
            bg_color: 背景色
        """
        if not Path(input_path).exists():
            raise FileNotFoundError(f"動画ファイルが見つかりません: {input_path}")
        # 位置計算
        pos = self._get_drawtext_position(position)
        
        # drawtext フィルター
        filter_str = (
            f"drawtext=text='{text}':"
            f"fontsize={font_size}:"
            f"fontcolor={font_color}:"
            f"box=1:boxcolor={bg_color}:"
            f"{pos}:"
            f"enable='between(t,{start_sec},{start_sec + duration_sec})'"
        )
        
        args = [
            "-y",
            "-i", str(input_path),
            "-vf", filter_str,
            *self._get_encode_args(),
            str(output_path)
        ]
        
        success, _ = self.run_command(args)
        return success
    
    def apply_batch_telops(self,
                           input_path: Path,
                           output_path: Path,
                           telops: List[Dict]) -> bool:
        """
        複数テロップを一括適用
        
        Args:
            telops: [{"text": str, "start": float, "end": float, "position": str}, ...]
        """
        if not Path(input_path).exists():
            raise FileNotFoundError(f"動画ファイルが見つかりません: {input_path}")
        if not telops:
            # テロップなしの場合はコピー
            shutil.copy(input_path, output_path)
            return True
        
        # 複合フィルターを構築
        filters = []
        
        # テンプレート基準のフォントサイズを取得
        try:
            from template_config import template_config
            font_size = template_config.get_subtitle_rules().get("font_size_min_px", 40)
        except (ImportError, AttributeError):
            font_size = 40
        
        for t in telops:
            text = t.get("text", "").replace("'", "\\'")
            start = t.get("start", 0)
            end = t.get("end", start + 5)
            position = t.get("position", "bottom")
            pos = self._get_drawtext_position(position)
            
            filters.append(
                f"drawtext=text='{text}':"
                f"fontsize={font_size}:fontcolor=white:"
                f"box=1:boxcolor=black@0.5:"
                f"{pos}:"
                f"enable='between(t,{start},{end})'"
            )
        
        filter_str = ",".join(filters)
        
        args = [
            "-y",
            "-i", str(input_path),
            "-vf", filter_str,
            *self._get_encode_args(),
            str(output_path)
        ]
        
        success, _ = self.run_command(args)
        return success
    
    def extract_audio(self, input_path: Path, output_path: Path) -> bool:
        """音声を抽出"""
        if not Path(input_path).exists():
            raise FileNotFoundError(f"動画ファイルが見つかりません: {input_path}")
        args = [
            "-y",
            "-i", str(input_path),
            "-vn",
            "-acodec", "libmp3lame",
            str(output_path)
        ]
        success, _ = self.run_command(args)
        return success
    
    def get_duration(self, input_path: Path) -> Optional[float]:
        """動画の長さを取得"""
        if not Path(input_path).exists():
            raise FileNotFoundError(f"動画ファイルが見つかりません: {input_path}")
        args = [
            "-i", str(input_path),
            "-show_entries", "format=duration",
            "-v", "quiet",
            "-of", "csv=p=0"
        ]
        
        ffprobe = self._resolve_ffprobe_path()
        if not ffprobe:
            return None
        
        try:
            result = subprocess.run(
                [ffprobe] + args,
                capture_output=True,
                text=True,
                timeout=30
            )
            return float(result.stdout.strip())
        except (subprocess.SubprocessError, ValueError, OSError):
            return None

    def get_video_info(self, input_path: Path) -> dict:
        """動画の情報を取得 (幅、高さ、ビデオコーデック、オーディオコーデック、再生時間)"""
        if not Path(input_path).exists():
            raise FileNotFoundError(f"動画ファイルが見つかりません: {input_path}")
        args = [
            "-v", "error",
            "-show_entries", "format=duration:stream=width,height,codec_name,codec_type",
            "-of", "json",
            str(input_path)
        ]
        
        ffprobe = self._resolve_ffprobe_path() or "ffprobe"

        default_info = {
            "width": 0,
            "height": 0,
            "video_codec": "",
            "audio_codec": "",
            "duration": 0.0
        }

        if not ffprobe or not Path(ffprobe).exists():
            return default_info

        try:
            result = subprocess.run(
                [ffprobe] + args,
                capture_output=True,
                text=True,
                timeout=30
            )
            data = json.loads(result.stdout)
            
            info = default_info.copy()
            
            # ストリーム解析
            for stream in data.get("streams", []):
                codec_type = stream.get("codec_type")
                if codec_type == "video":
                    info["width"] = int(stream.get("width", 0))
                    info["height"] = int(stream.get("height", 0))
                    info["video_codec"] = stream.get("codec_name", "")
                elif codec_type == "audio":
                    info["audio_codec"] = stream.get("codec_name", "")
            
            # 再生時間解析
            format_info = data.get("format", {})
            dur_str = format_info.get("duration")
            if dur_str:
                info["duration"] = float(dur_str)
                
            return info
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Failed to get video info: {e}")
            return default_info



class VideoEditorEngine:
    """統合動画編集エンジン"""
    
    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or DEFAULT_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.ffmpeg = FFmpegEditor(self.output_dir)
    
    def is_available(self) -> bool:
        """FFmpegが利用可能か"""
        return self.ffmpeg.is_available()
    
    def create_final_video(self,
                           main_video: Path,
                           opening: Optional[Path] = None,
                           ending: Optional[Path] = None,
                           telops: List[Dict] = None,
                           output_name: str = "final_video.mp4") -> Dict:
        """
        最終動画を生成
        
        Args:
            main_video: メイン動画
            opening: オープニング動画（オプション）
            ending: エンディング動画（オプション）
            telops: テロップリスト
            output_name: 出力ファイル名
        """
        result = {
            "success": False,
            "output_path": None,
            "steps": []
        }
        
        if not self.is_available():
            result["error"] = "FFmpeg not available"
            return result
        
        if not Path(main_video).exists():
            raise FileNotFoundError(f"動画ファイルが見つかりません: {main_video}")
        
        current = main_video
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Step 1: テロップ適用
        if telops:
            telop_output = self.output_dir / f"step1_telops_{timestamp}.mp4"
            if self.ffmpeg.apply_batch_telops(current, telop_output, telops):
                result["steps"].append("telops applied")
                current = telop_output
            else:
                result["steps"].append("telops failed")
        
        # Step 2: オープニング追加
        if opening and opening.exists():
            opening_output = self.output_dir / f"step2_opening_{timestamp}.mp4"
            if self.ffmpeg.add_opening(current, opening, opening_output):
                result["steps"].append("opening added")
                current = opening_output
            else:
                result["steps"].append("opening failed")
        
        # Step 3: エンディング追加
        if ending and ending.exists():
            ending_output = self.output_dir / f"step3_ending_{timestamp}.mp4"
            if self.ffmpeg.add_ending(current, ending, ending_output):
                result["steps"].append("ending added")
                current = ending_output
            else:
                result["steps"].append("ending failed")
        
        # 最終出力
        final_output = self.output_dir / output_name
        if current != main_video:
            shutil.copy(current, final_output)
        else:
            shutil.copy(main_video, final_output)
        
        result["success"] = True
        result["output_path"] = str(final_output)
        
        return result
    
    def _detect_silence_segments(self,
                                 input_path: Path,
                                 threshold_db: float,
                                 min_silence_sec: float) -> Optional[Tuple[List[float], List[float]]]:
        """無音区間を検出して開始・終了時間のリストを返す。検出失敗時はNoneを返す。"""
        import re
        detect_args = [
            "-i", str(input_path),
            "-af", f"silencedetect=n={threshold_db}dB:d={min_silence_sec}",
            "-f", "null",
            "-"
        ]
        
        success, output = self.ffmpeg.run_command(detect_args)
        if not success:
            logger.error("Silence detection failed")
            return None
        
        silence_starts = [float(t) for t in re.findall(r'silence_start: ([\d.]+)', output)]
        silence_ends = [float(t) for t in re.findall(r'silence_end: ([\d.]+)', output)]
        return silence_starts, silence_ends

    def _calculate_keep_ranges(self,
                               silence_starts: List[float],
                               silence_ends: List[float],
                               total_duration: float) -> List[Tuple[float, float]]:
        """無音区間の合間にある保持すべき有音区間のリストを算出"""
        keep_ranges = []
        prev_end = 0.0
        
        for i, s_start in enumerate(silence_starts):
            if s_start > prev_end + 0.1:  # 0.1秒以上の有音区間のみ保持
                keep_ranges.append((prev_end, s_start))
            if i < len(silence_ends):
                prev_end = silence_ends[i]
        
        if prev_end < total_duration - 0.1:
            keep_ranges.append((prev_end, total_duration))
            
        return keep_ranges

    def _cut_and_merge_segments(self,
                                input_path: Path,
                                output_path: Path,
                                keep_ranges: List[Tuple[float, float]]) -> bool:
        """各区間をカットして結合し、一時ファイルをクリーンアップする"""
        temp_parts = []
        try:
            for i, (start, end) in enumerate(keep_ranges):
                temp_path = self.ffmpeg.temp_dir / f"silence_cut_{uuid.uuid4().hex}_{i:04d}.mp4"
                if self.ffmpeg.cut_video(input_path, temp_path, start, end):
                    temp_parts.append(temp_path)
                else:
                    logger.warning(f"Failed to cut segment {i} ({start:.2f}-{end:.2f})")
            
            if not temp_parts:
                return False
            
            clips = [VideoClip(path=p) for p in temp_parts]
            success = self.ffmpeg.merge_videos(clips, output_path)
            return success
        finally:
            for p in temp_parts:
                if p.exists():
                    try:
                        p.unlink()
                    except OSError as e:
                        logger.warning(f"Failed to delete temp file {p}: {e}")

    def auto_cut_silence(self,
                         input_path: Path,
                         output_path: Path,
                         threshold_db: float = -40,
                         min_silence_sec: float = 1.0) -> bool:
        """無音部分を自動カット（Phase D: 完全実装）"""
        if not Path(input_path).exists():
            raise FileNotFoundError(f"動画ファイルが見つかりません: {input_path}")
        # Step 1 & 2: 無音検出とパース
        silence_result = self._detect_silence_segments(
            input_path, threshold_db, min_silence_sec
        )
        if silence_result is None:
            return False
            
        silence_starts, silence_ends = silence_result
        
        if not silence_starts:
            logger.info("No silence detected or detection failed — copying original")
            shutil.copy(input_path, output_path)
            return True
            
        # Step 3: 保持する区間を計算（無音の逆）
        total_duration = self.ffmpeg.get_duration(input_path)
        if total_duration is None:
            logger.error("Could not determine video duration")
            return False
            
        keep_ranges = self._calculate_keep_ranges(
            silence_starts, silence_ends, total_duration
        )
        
        if not keep_ranges:
            logger.warning("No audio segments to keep")
            return False
            
        logger.info(f"Silence cut: {len(silence_starts)} silent ranges detected, "
                    f"keeping {len(keep_ranges)} segments")
                    
        # Step 4 & 5: 各保持区間のカットと結合
        return self._cut_and_merge_segments(input_path, output_path, keep_ranges)


# シングルトンインスタンス
video_editor = VideoEditorEngine()


# 簡易関数
def check_ffmpeg() -> bool:
    """FFmpegが利用可能か確認"""
    return video_editor.is_available()


def create_final_video(main_video: Path, **kwargs) -> Dict:
    """最終動画を生成"""
    return video_editor.create_final_video(main_video, **kwargs)
