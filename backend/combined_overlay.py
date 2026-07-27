"""
Combined Logo and Telop Overlay
Phase 30 - Week 3 Implementation

ロゴとテーマテロップを同時にオーバーレイ
"""

import subprocess
from pathlib import Path
from datetime import datetime
import uuid
from typing import Tuple, Optional
import logging
import os

from logo_manager import LogoManager
from theme_telop import ThemeTelopGenerator

# Progressive Preview System (憲法 9.1 視覚確認プロトコル)
from progressive_preview import ProgressivePreview
from services.preview_report_generator import PreviewReportGenerator

logger = logging.getLogger(__name__)


class CombinedOverlay:
    """ロゴ+テロップ統合オーバーレイクラス"""
    
    def __init__(self):
        """初期化"""
        self.logo_manager = LogoManager()
        self.telop_generator = ThemeTelopGenerator()
        self.ffmpeg_path = "ffmpeg"
        
    def _run_ffmpeg(self, cmd: list, description: str) -> subprocess.CompletedProcess:
        """FFmpegコマンドを実行する共通ヘルパー"""
        debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
        if debug_mode:
            logger.info(f"FFmpeg command ({description}): {' '.join(cmd)}")
        try:
            return subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg error ({description}): {e.stderr}")
            raise
            
    def _has_audio(self, video_path: str) -> bool:
        """動画ファイルに音声ストリームが含まれているか確認する"""
        ffprobe_path = os.getenv("FFPROBE_PATH", "ffprobe")
        cmd = [
            ffprobe_path,
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            video_path
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            stdout = res.stdout or ""
            return "audio" in stdout
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            logger.warning(f"Failed to check audio stream with ffprobe: {e}")
            # エラー時はフォールバックとしてTrueを返す (既存の挙動を維持)
            return True

    
    def apply_brand_overlay(
        self,
        input_video: str,
        output_path: str,
        speaker1: str = "北原美麗",
        speaker2: str = "山田タロウ",
        theme: str = "想いを筆で起こす",
        logo_position: Tuple[int, int] = (10, 10),
        logo_height: int = 60,
        logo_opacity: float = 0.8,
        telop_position: Optional[Tuple[int, int]] = None,
        telop_opacity: float = 0.85,
        telop_duration: float = 10.0
    ) -> str:
        """
        ブランドロゴ+テーマテロップを統合オーバーレイ
        
        Args:
            input_video: 入力動画パス
            output_path: 出力動画パス
            speaker1: 話者1
            speaker2: 話者2
            theme: テーマ
            logo_position: ロゴ位置 (x, y)
            logo_height: ロゴ高さ（px）
            logo_opacity: ロゴ不透明度
            telop_position: テロップ位置（省略時は自動計算）
            telop_opacity: テロップ不透明度
            telop_duration: テロップ表示時間（秒）
        
        Returns:
            出力動画パス
        """
        logger.info("Applying combined brand overlay")
        
        # ロゴパス取得
        logo_path = self.logo_manager.get_logo_path("brand_logo.png")
        if not logo_path:
            logger.error("Logo not found")
            raise FileNotFoundError("Brand logo not found")
            
        # テロップ用の一時出力先（並行競合を避けるため一意のファイル名にする）
        temp_dir = Path("backend/temp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        unique_id = uuid.uuid4().hex
        telop_path = temp_dir / f"theme_telop_{unique_id}.png"
        
        try:
            # テロップ生成
            generated_telop = self.telop_generator.generate_video_theme_telop(
                speaker1=speaker1,
                speaker2=speaker2,
                theme=theme,
                output_path=str(telop_path)
            )
            
            # テロップ位置計算（ロゴの右側）
            if telop_position is None:
                logo_size = self.logo_manager.get_logo_size(logo_path)
                target_logo_size = self.logo_manager.calculate_target_size(logo_size, logo_height)
                telop_x = logo_position[0] + target_logo_size[0] + 20  # ロゴの右に20pxマージン
                telop_y = logo_position[1] + 5  # ロゴとほぼ同じ高さ
                telop_position = (telop_x, telop_y)
            
            logger.info(f"  Logo: {logo_path} at {logo_position}")
            logger.info(f"  Telop: {generated_telop} at {telop_position}")
            logger.info(f"  Telop duration: {telop_duration}s")
            
            telop_x, telop_y = telop_position
            logo_x, logo_y = logo_position
            fade_out_start = telop_duration - 2.0  # 最後の2秒でフェードアウト
            
            filter_complex = (
                # ロゴ処理
                f"[1:v]scale=-1:{logo_height}[logo_resized];"
                f"[logo_resized]format=rgba,colorchannelmixer=aa={logo_opacity}[logo];"
                
                # テロップ処理（フェードアウト付き）
                f"[2:v]format=rgba,colorchannelmixer=aa={telop_opacity}[telop_opacity];"
                f"[telop_opacity]fade=out:st={fade_out_start}:d=2:alpha=1[telop];"
                
                # オーバーレイ（ロゴ→テロップの順）
                f"[0:v][logo]overlay={logo_x}:{logo_y}:format=auto[v_with_logo];"
                f"[v_with_logo][telop]overlay={telop_x}:{telop_y}:enable='lte(t,{telop_duration})':format=auto[v]"
            )
            
            # FFmpegコマンド
            cmd = [
                self.ffmpeg_path,
                "-i", input_video,
                "-i", str(logo_path),
                "-i", str(generated_telop),
                "-filter_complex", filter_complex,
                "-map", "[v]",
            ]
            
            if self._has_audio(input_video):
                cmd.extend([
                    "-map", "0:a",
                    "-c:a", "copy",
                ])
            else:
                logger.info("No audio stream detected. Disabling audio mapping.")
                
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-y",
                output_path
            ])
            
            self._run_ffmpeg(cmd, "apply_brand_overlay")
            logger.info(f"Combined overlay completed: {output_path}")
            return output_path
            
        finally:
            # 生成した一時的なテロップ画像を削除
            if telop_path.exists():
                try:
                    telop_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete temp telop file {telop_path}: {e}")
    
    def generate_preview(
        self,
        input_video: str,
        output_path: str,
        preview_duration: float = 10.0,
        **overlay_kwargs
    ) -> str:
        """
        プレビュー動画を生成（最初のN秒を抽出してオーバーレイ）
        
        Args:
            input_video: 入力動画パス
            output_path: 出力動画パス
            preview_duration: プレビュー時間（秒）
            **overlay_kwargs: apply_brand_overlayの引数
        
        Returns:
            プレビュー動画パス
        """
        logger.info(f"Generating preview ({preview_duration}s)")
        
        # 一時ファイル（最初のN秒を抽出）
        temp_dir = Path("backend/temp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        unique_id = uuid.uuid4().hex
        temp_video = temp_dir / f"preview_temp_{unique_id}.mp4"
        
        # 最初のN秒を抽出
        extract_cmd = [
            self.ffmpeg_path,
            "-i", input_video,
            "-t", str(preview_duration),
            "-c", "copy",
            "-y",
            str(temp_video)
        ]
        
        try:
            self._run_ffmpeg(extract_cmd, "generate_preview_extract")
            logger.info(f"Extracted {preview_duration}s preview")
            
            # オーバーレイ適用
            result = self.apply_brand_overlay(
                input_video=str(temp_video),
                output_path=output_path,
                **overlay_kwargs
            )
            
            # === 憲法 9.1: オーバーレイ後のプレビュー ===
            try:
                session_id = f"overlay_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                preview = ProgressivePreview(session_id=session_id)
                preview.snapshot_step(
                    step_name="brand_overlay",
                    before_video=input_video,
                    after_video=result,
                    num_samples=3
                )
                generator = PreviewReportGenerator()
                report_path = generator.generate_from_session_dir(str(preview.output_dir))
                logger.info(f"Preview report: {report_path}")
            except Exception as pe:
                logger.warning(f"Preview generation failed: {pe}")
            
            return result
            
        finally:
            # 一時ファイルの確実なクリーンアップ
            if temp_video.exists():
                try:
                    temp_video.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete temp video file {temp_video}: {e}")

    def generate_thumbnail(
        self,
        output_path,
        width: int = 1280,
        height: int = 720,
        text: str = "Thumbnail"
    ):
        from agents.stage_bound_agent import generate_thumbnail
        return generate_thumbnail(output_path, width=width, height=height, text=text)

    def validate_thumbnail(self, file_path) -> dict:
        from agents.stage_bound_agent import validate_thumbnail
        return validate_thumbnail(file_path)

    async def resolve_thumbnail_task(self, task_id: str) -> str:
        from agents.stage_bound_agent import resolve_thumbnail_task
        return await resolve_thumbnail_task(self, task_id)


if __name__ == "__main__":
    # テスト
    logging.basicConfig(level=logging.INFO)
    
    overlay = CombinedOverlay()
    
    # シーン04でプレビューテスト
    input_video = r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画\シーン04_後編02.mp4"
    output_preview = "backend/temp/preview_with_brand.mp4"
    
    if Path(input_video).exists():
        try:
            overlay.generate_preview(
                input_video=input_video,
                output_path=output_preview,
                preview_duration=10.0,
                speaker1="北原美麗",
                speaker2="山田タロウ",
                theme="想いを筆で起こす"
            )
            print(f"\n✅ プレビュー生成完了: {output_preview}")
        except Exception as e:
            print(f"\n❌ エラー: {e}")
    else:
        print(f"❌ 動画ファイルが見つかりません: {input_video}")
