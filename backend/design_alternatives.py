"""
Design Alternatives Generator
デザイン改善案を複数生成
"""

import subprocess
import sys
import traceback
from pathlib import Path
import logging
from combined_overlay import CombinedOverlay
from logo_overlay import LogoOverlay
from logo_manager import LogoManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DesignAlternativesError(Exception):
    """Design Alternatives Generator におけるエラー"""
    pass


def _validate_and_prepare_dir(input_video: str, output_dir: str) -> tuple[Path, Path]:
    """入力のバリデーションと出力ディレクトリの作成"""
    if not input_video:
        raise ValueError("input_video cannot be empty or None")
    
    input_path = Path(input_video)
    if not input_path.exists() or not input_path.is_file():
        raise FileNotFoundError(f"input_video does not exist: {input_video}")
        
    if not output_dir:
        raise ValueError("output_dir cannot be empty or None")
        
    output_path = Path(output_dir)
    try:
        output_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create output directory: {e}")
        raise DesignAlternativesError(f"Failed to create output directory: {e}") from e
        
    return input_path, output_path


def _extract_base_video(input_path: Path, temp_video_path: Path) -> None:
    """最初の10秒を抽出"""
    logger.info("Extracting base video...")
    extract_cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-t", "10",
        "-c:v", "libx264",
        "-c:a", "copy",
        "-y",
        str(temp_video_path)
    ]
    try:
        subprocess.run(extract_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg extraction failed: {e.stderr}")
        raise DesignAlternativesError(f"FFmpeg extraction failed: {e.stderr}") from e
    except FileNotFoundError as e:
        logger.error(f"ffmpeg command not found: {e}")
        raise DesignAlternativesError("ffmpeg command not found") from e


def _apply_brand_overlay_with_handling(
    overlay: CombinedOverlay,
    input_video: Path,
    output_path: Path,
    alternative_name: str,
    **kwargs
) -> Path:
    """共通のブランドオーバーレイ適用と例外ハンドリングを行うヘルパー関数"""
    logger.info(f"\n=== {alternative_name} ===")
    try:
        overlay.apply_brand_overlay(
            input_video=str(input_video),
            output_path=str(output_path),
            speaker1="北原美麗",
            speaker2="山田タロウ",
            theme="想いを筆で起こす",
            telop_duration=10.0,
            **kwargs
        )
        logger.info(f"✅ {alternative_name}: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"Failed to apply {alternative_name} overlay: {e}")
        raise DesignAlternativesError(f"Failed to apply {alternative_name} overlay: {e}") from e


def _generate_current_design_alternative(overlay: CombinedOverlay, temp_video: Path, output_dir: Path) -> Path:
    """A案: 現在のデザイン（ロゴ60px + テロップ24px）"""
    output_a = output_dir / "A_current_logo60_telop24.mp4"
    return _apply_brand_overlay_with_handling(
        overlay, temp_video, output_a, "A案", logo_height=60
    )


def _generate_moderate_design_alternative(overlay: CombinedOverlay, temp_video: Path, output_dir: Path) -> Path:
    """B案: 控えめサイズ（ロゴ45px + テロップ18px）"""
    output_b = output_dir / "B_moderate_logo45.mp4"
    return _apply_brand_overlay_with_handling(
        overlay, temp_video, output_b, "B案", logo_height=45
    )


def _generate_minimal_design_alternative(overlay: CombinedOverlay, temp_video: Path, output_dir: Path) -> Path:
    """C案: ミニマル（ロゴ35px + テロップ16px + 不透明度0.6）"""
    output_c = output_dir / "C_minimal_logo35.mp4"
    return _apply_brand_overlay_with_handling(
        overlay, temp_video, output_c, "C案", logo_height=35, logo_opacity=0.6
    )


def _generate_logo_only_design_alternative(temp_video: Path, output_dir: Path) -> Path:
    """D案: ロゴのみ（テロップなし）"""
    logger.info("\n=== D案: ロゴのみ ===")
    try:
        logo_overlay = LogoOverlay()
        logo_manager = LogoManager()
        logo_path = logo_manager.get_logo_path("brand_logo.png")
    except Exception as e:
        logger.error(f"Failed to initialize logo manager/overlay: {e}")
        raise DesignAlternativesError(f"Failed to initialize logo manager/overlay: {e}") from e
        
    output_d = output_dir / "D_logo_only.mp4"
    try:
        logo_overlay.apply_logo_with_fade(
            input_video=str(temp_video),
            logo_path=str(logo_path),
            output_path=str(output_d),
            position=(10, 10),
            opacity=0.7,
            target_height=50
        )
        logger.info(f"✅ D案: {output_d}")
        return output_d
    except Exception as e:
        logger.error(f"Failed to apply D案 logo overlay: {e}")
        raise DesignAlternativesError(f"Failed to apply D案 logo overlay: {e}") from e



def _extract_line_number_from_traceback(tb) -> int:
    """tracebackからdesign_alternatives.pyの最後の実行行番号を取得"""
    line_no = 227  # fallback
    if tb is not None:
        for frame, lineno in traceback.walk_tb(tb):
            co_filename = frame.f_code.co_filename
            if "design_alternatives.py" in co_filename:
                line_no = lineno
    return line_no


def _register_unexpected_debt(exc: Exception, line_number: int) -> None:
    """想定外の例外発生時に技術負債を登録"""
    try:
        from backend.agents.memory.technical_debt import TechnicalDebtStore
        store = TechnicalDebtStore()
        store.register_debt(
            category="MINOR_INFRA",
            file_path="backend/design_alternatives.py",
            line_number=line_number,
            pattern="except Exception as e:",
            cause_pattern="DP-01",
            fix_pattern="具体的な例外の個別キャッチ",
            registered_by="thumbnail_robustification",
            notes="一時ファイル削除のための最終防壁catch"
        )
    except Exception as debt_err:
        logger.error(f"Failed to register technical debt: {debt_err}")


def _cleanup_temp_files(paths: list[Path]) -> None:
    """一時ファイルの削除クリーンアップ"""
    for path in paths:
        try:
            if path.exists():
                path.unlink()
                logger.info(f"Cleaned up temporary file: {path}")
        except Exception as e:
            logger.warning(f"Failed to delete temporary file {path}: {e}")


def generate_design_alternatives(
    input_video: str,
    output_dir: str = "backend/temp/design_alternatives"
):
    """
    複数のデザイン案を生成
    
    A案: 現在のデザイン（ロゴ60px + テロップ24px）
    B案: 控えめサイズ（ロゴ45px + テロップ18px）
    C案: ミニマル（ロゴ40px + テロップ16px）
    D案: テロップなしロゴのみ
    """
    input_path, output_path = _validate_and_prepare_dir(input_video, output_dir)
    temp_video = output_path / "base_10s.mp4"
    
    try:
        _extract_base_video(input_path, temp_video)
        
        try:
            combined_overlay = CombinedOverlay()
        except Exception as e:
            logger.error(f"Failed to initialize CombinedOverlay: {e}")
            raise DesignAlternativesError(f"Failed to initialize CombinedOverlay: {e}") from e
            
        alternatives = []
        
        # A案
        output_a = _generate_current_design_alternative(combined_overlay, temp_video, output_path)
        alternatives.append(("A案（現在）", str(output_a)))
        
        # B案
        output_b = _generate_moderate_design_alternative(combined_overlay, temp_video, output_path)
        alternatives.append(("B案（控えめ）", str(output_b)))
        
        # C案
        output_c = _generate_minimal_design_alternative(combined_overlay, temp_video, output_path)
        alternatives.append(("C案（ミニマル）", str(output_c)))
        
        # D案
        output_d = _generate_logo_only_design_alternative(temp_video, output_path)
        alternatives.append(("D案（ロゴのみ）", str(output_d)))
        
        logger.info(f"\n✅ 全{len(alternatives)}案生成完了")
        return alternatives
        
    except Exception as e:
        logger.error(f"Error during generate_design_alternatives: {e}")
        if not isinstance(e, (ValueError, FileNotFoundError, DesignAlternativesError)):
            tb = sys.exc_info()[2]
            line_no = _extract_line_number_from_traceback(tb)
            _register_unexpected_debt(e, line_no)
            raise DesignAlternativesError(f"Design alternatives generation failed: {e}") from e
        raise
    finally:
        _cleanup_temp_files([temp_video])


if __name__ == "__main__":  # pragma: no cover
    input_video = r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画\シーン04_後編02.mp4"
    
    if Path(input_video).exists():
        alternatives = generate_design_alternatives(input_video)
        
        print("\n" + "="*60)
        print("デザイン案一覧")
        print("="*60)
        for name, path in alternatives:
            print(f"{name}: {Path(path).name}")
    else:
        print(f"❌ Video not found: {input_video}")
