import subprocess
import shutil
import logging
from pathlib import Path
from datetime import datetime
import uuid

# Progressive Preview System (憲法 9.1 視覚確認プロトコル)
from progressive_preview import ProgressivePreview
from progressive_preview_report import PreviewReportGenerator

logger = logging.getLogger(__name__)

class ColorGrading:
    """
    シネマティック・カラーグレーディングエンジン
    - LUT（Look Up Table）プリセット適用
    - FFmpeg ビルトインフィルタによる色彩補正
    """
    
    # プリセット定義（FFmpeg フィルタベース）
    PRESETS = {
        "cinematic": "eq=contrast=1.2:brightness=0.05:saturation=1.3,curves=r='0/0 0.5/0.58 1/1':g='0/0 0.5/0.5 1/1':b='0/0 0.5/0.42 1/1'",
        "warm": "eq=contrast=1.1:saturation=1.2,colortemperature=temperature=6500",
        "cool": "eq=contrast=1.15:saturation=1.1,colortemperature=temperature=9000",
        "vintage": "curves=vintage,eq=contrast=1.3:brightness=-0.05:saturation=0.8",
        "vibrant": "eq=contrast=1.25:saturation=1.5:gamma=1.1",
        "none": ""  # プリセットなし
    }
    
    def __init__(self):
        # FFmpeg の自動検出
        self.ffmpeg = shutil.which('ffmpeg')
        if not self.ffmpeg:
            local_ffmpeg = Path('./backend/bin/ffmpeg.exe')
            if local_ffmpeg.exists():
                self.ffmpeg = str(local_ffmpeg)
            else:
                self.ffmpeg = None
        
        # LUT ディレクトリ（将来の拡張用）
        self.lut_dir = Path("luts").resolve()
        self.lut_dir.mkdir(exist_ok=True)
        
        # 出力ディレクトリ
        self.output_dir = Path("graded_videos").resolve()
        self.output_dir.mkdir(exist_ok=True)
        
        print(f"✅ ColorGrading initialized. FFmpeg: {self.ffmpeg}")
        print(f"📁 Available presets: {', '.join(self.PRESETS.keys())}")

    def _ensure_ffmpeg(self):
        if not self.ffmpeg:
            raise RuntimeError("FFmpeg not found. Please install FFmpeg.")
    
    def apply_preset(self, video_path: str, preset: str = "cinematic") -> str:
        """
        カラーグレーディング プリセットを適用
        
        Args:
            video_path: 入力動画ファイル
            preset: プリセット名（cinematic, warm, cool, vintage, vibrant, none）
        
        Returns:
            グレーディング適用後の動画ファイルのパス
        """
        self._ensure_ffmpeg()
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        if preset not in self.PRESETS:
            raise ValueError(f"Unknown preset: {preset}. Available: {list(self.PRESETS.keys())}")
        
        output_id = str(uuid.uuid4())
        output = self.output_dir / f"{output_id}_graded_{preset}.mp4"
        
        filter_str = self.PRESETS[preset]
        
        # プリセットが "none" の場合はコピーのみ
        if preset == "none" or not filter_str:
            cmd = [
                self.ffmpeg,
                '-i', video_path,
                '-c', 'copy',
                '-y',
                str(output)
            ]
        else:
            # カラーグレーディング適用
            cmd = [
                self.ffmpeg,
                '-i', video_path,
                '-vf', filter_str,
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-c:a', 'copy',  # 音声はそのままコピー
                '-y',
                str(output)
            ]
        
        try:
            print(f"🎨 Applying color grading preset: {preset}")
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"✅ Color grading applied: {output}")
            
            # === 憲法 9.1: カラーグレーディング後のプレビュー ===
            try:
                session_id = f"color_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                preview = ProgressivePreview(session_id=session_id)
                preview.snapshot_step(
                    step_name=f"color_{preset}",
                    before_video=video_path,
                    after_video=str(output),
                    num_samples=3
                )
                generator = PreviewReportGenerator()
                report_path = generator.generate_from_session_dir(str(preview.output_dir))
                print(f"📸 Preview report: {report_path}")
            except (OSError, RuntimeError, ValueError) as pe:
                logger.warning(f"Preview generation failed (expected exception): {pe}", exc_info=True)
                print(f"   ⚠️ Preview generation failed: {pe}")
            except Exception as pe:
                logger.error(f"Unexpected preview generation error: {pe}", exc_info=True)
                print(f"   ⚠️ Preview generation failed: {pe}")
            
            return str(output)
        except subprocess.CalledProcessError as e:
            stderr_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
            print(f"❌ FFmpeg error: {stderr_msg}")
            raise RuntimeError(f"Color grading failed: {stderr_msg}")
    
    def apply_lut(self, video_path: str, output_path: str, preset: str = "cinematic") -> str:
        """
        指定のプリセットを用いてカラーグレーディング（LUT）を適用し、指定の出力パスに保存する。
        
        Args:
            video_path: 入力動画ファイル
            output_path: 出力動画ファイル
            preset: プリセット名（cinematic, warm, cool, vintage, vibrant, none）
        
        Returns:
            適用後の動画ファイルのパス
        """
        self._ensure_ffmpeg()
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        if preset not in self.PRESETS:
            raise ValueError(f"Unknown preset: {preset}. Available: {list(self.PRESETS.keys())}")
        
        filter_str = self.PRESETS[preset]
        
        # プリセットが "none" の場合はコピーのみ
        if preset == "none" or not filter_str:
            cmd = [
                self.ffmpeg,
                '-i', video_path,
                '-c', 'copy',
                '-y',
                str(output_path)
            ]
        else:
            # カラーグレーディング適用
            cmd = [
                self.ffmpeg,
                '-i', video_path,
                '-vf', filter_str,
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-c:a', 'copy',
                '-y',
                str(output_path)
            ]
        
        try:
            print(f"🎨 Applying color grading (apply_lut): {preset} -> {output_path}")
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"✅ Color grading applied: {output_path}")
            
            # === 憲法 9.1: カラーグレーディング後のプレビュー ===
            try:
                session_id = f"color_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                preview = ProgressivePreview(session_id=session_id)
                preview.snapshot_step(
                    step_name=f"color_{preset}",
                    before_video=video_path,
                    after_video=str(output_path),
                    num_samples=3
                )
                generator = PreviewReportGenerator()
                report_path = generator.generate_from_session_dir(str(preview.output_dir))
                print(f"📸 Preview report: {report_path}")
            except (OSError, RuntimeError, ValueError) as pe:
                logger.warning(f"Preview generation failed during apply_lut (expected exception): {pe}", exc_info=True)
                print(f"   ⚠️ Preview generation failed: {pe}")
            except Exception as pe:
                logger.error(f"Unexpected preview generation error during apply_lut: {pe}", exc_info=True)
                print(f"   ⚠️ Preview generation failed: {pe}")
            
            return str(output_path)
        except subprocess.CalledProcessError as e:
            stderr_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
            print(f"❌ FFmpeg error in apply_lut: {stderr_msg}")
            raise RuntimeError(f"Color grading (apply_lut) failed: {stderr_msg}")

    def apply_custom_lut(self, video_path: str, lut_file: str) -> str:
        """
        カスタム LUT ファイル（.cube）を適用
        
        Args:
            video_path: 入力動画ファイル
            lut_file: LUT ファイルのパス（.cube形式）
        
        Returns:
            LUT 適用後の動画ファイルのパス
        """
        self._ensure_ffmpeg()
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if not Path(lut_file).exists():
            raise FileNotFoundError(f"LUT file not found: {lut_file}")
        
        output_id = str(uuid.uuid4())
        output = self.output_dir / f"{output_id}_lut_applied.mp4"
        
        lut_file_escaped = _escape_filter_path(lut_file)
        lut_filter = f"lut3d={lut_file_escaped}"
        
        cmd = [
            self.ffmpeg,
            '-i', video_path,
            '-vf', lut_filter,
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'copy',
            '-y',
            str(output)
        ]
        
        try:
            print(f"🎨 Applying custom LUT: {lut_file}")
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"✅ LUT applied: {output}")
            
            # === 憲法 9.1: カラーグレーディング後のプレビュー ===
            try:
                session_id = f"color_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                preview = ProgressivePreview(session_id=session_id)
                preview.snapshot_step(
                    step_name="color_custom_lut",
                    before_video=video_path,
                    after_video=str(output),
                    num_samples=3
                )
                generator = PreviewReportGenerator()
                report_path = generator.generate_from_session_dir(str(preview.output_dir))
                print(f"📸 Preview report: {report_path}")
            except (OSError, RuntimeError, ValueError) as pe:
                logger.warning(f"Preview generation failed during apply_custom_lut (expected exception): {pe}", exc_info=True)
                print(f"   ⚠️ Preview generation failed: {pe}")
            except Exception as pe:
                logger.error(f"Unexpected preview generation error during apply_custom_lut: {pe}", exc_info=True)
                print(f"   ⚠️ Preview generation failed: {pe}")
                
            return str(output)
        except subprocess.CalledProcessError as e:
            stderr_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
            print(f"❌ FFmpeg error: {stderr_msg}")
            raise RuntimeError(f"LUT application failed: {stderr_msg}")

def _escape_filter_path(path_str: str) -> str:
    """
    FFmpegのフィルタでパスを指定する際のエスケープ処理
    """
    resolved_path = Path(path_str).resolve().as_posix()
    return resolved_path.replace(":", "\\:")

# グローバルインスタンス
color_grading = ColorGrading()
