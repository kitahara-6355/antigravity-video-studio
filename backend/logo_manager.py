"""
Logo Manager Module
Phase 30 - Week 3 Implementation

ブランドロゴの管理・検証・読み込み機能
"""

from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, UnidentifiedImageError
import logging

logger = logging.getLogger(__name__)


class LogoManager:
    """ブランドロゴ管理クラス"""
    
    def __init__(self, logo_dir: str = "backend/branding/logos"):
        """
        Args:
            logo_dir: ロゴディレクトリパス
        """
        path = Path(logo_dir)
        if logo_dir == "backend/branding/logos":
            logo_file = path / "brand_logo.png"
            if not path.exists() or not logo_file.exists():
                alt_path = Path("branding/logos")
                if alt_path.exists() and (alt_path / "brand_logo.png").exists():
                    path = alt_path
                
        self.logo_dir = path
        self.logo_dir.mkdir(parents=True, exist_ok=True)
        
        # フォールバックロゴパス
        self.fallback_logo = self.logo_dir / "fallback_logo.png"
    
    def get_logo_path(self, logo_name: str = "brand_logo.png") -> Optional[Path]:
        """
        ロゴファイルパスを取得
        
        Args:
            logo_name: ロゴファイル名
        
        Returns:
            ロゴファイルパス（存在しない場合はNone）
        """
        logo_path = self.logo_dir / logo_name
        
        if logo_path.exists():
            logger.info(f"Logo found: {logo_path}")
            return logo_path
        
        # フォールバック
        if self.fallback_logo.exists():
            logger.warning(f"Logo not found, using fallback: {self.fallback_logo}")
            return self.fallback_logo
        
        logger.error(f"No logo found: {logo_name}")
        return None
    
    def validate_logo(self, logo_path: Path) -> bool:
        """
        ロゴファイルを検証
        
        Args:
            logo_path: ロゴファイルパス
        
        Returns:
            検証結果（True: 有効, False: 無効）
        """
        if not logo_path.exists():
            logger.error(f"Logo file does not exist: {logo_path}")
            return False
        
        try:
            with Image.open(logo_path) as img:
                # 画像形式確認
                if img.format not in ["PNG", "JPEG", "JPG"]:
                    logger.error(f"Unsupported format: {img.format}")
                    return False
                
                # サイズ確認（最小サイズ）
                if img.width < 50 or img.height < 50:
                    logger.error(f"Logo too small: {img.width}x{img.height}")
                    return False
                
                # 最大サイズ確認
                if img.width > 2000 or img.height > 2000:
                    logger.warning(f"Logo very large: {img.width}x{img.height}")
                
                logger.info(f"Logo validated: {img.width}x{img.height}, {img.format}")
                return True
                
        except (UnidentifiedImageError, OSError, ValueError) as e:
            logger.error(f"Logo validation error (expected image issue): {e}", exc_info=True)
            return False
        except (AttributeError, TypeError) as e:
            logger.error(f"Logo validation error (unexpected error): {e}", exc_info=True)
            return False
    
    def get_logo_size(self, logo_path: Path) -> Tuple[int, int]:
        """
        ロゴサイズを取得
        
        Args:
            logo_path: ロゴファイルパス
        
        Returns:
            (width, height)
        """
        try:
            with Image.open(logo_path) as img:
                return (img.width, img.height)
        except (UnidentifiedImageError, OSError, ValueError) as e:
            logger.error(f"Failed to get logo size (expected image issue): {e}", exc_info=True)
            return (0, 0)
        except (AttributeError, TypeError) as e:
            logger.error(f"Failed to get logo size (unexpected error): {e}", exc_info=True)
            return (0, 0)
    
    def calculate_target_size(
        self, 
        original_size: Tuple[int, int], 
        target_height: int = 60
    ) -> Tuple[int, int]:
        """
        アスペクト比を維持したサイズを計算
        
        Args:
            original_size: (width, height)
            target_height: 目標高さ
        
        Returns:
            (new_width, new_height)
        """
        width, height = original_size
        
        if height == 0:
            return (0, 0)
        
        aspect_ratio = width / height
        new_height = target_height
        new_width = int(new_height * aspect_ratio)
        
        logger.info(f"Logo resize: {width}x{height} -> {new_width}x{new_height}")
        return (new_width, new_height)
    
    def save_uploaded_logo(self, uploaded_file_path: str, logo_name: str = "brand_logo.png") -> Path:
        """
        アップロードされたロゴを保存
        
        Args:
            uploaded_file_path: アップロードファイルパス
            logo_name: 保存するロゴ名
        
        Returns:
            保存先パス
        """
        source = Path(uploaded_file_path)
        destination = self.logo_dir / logo_name
        
        try:
            # 画像を開いて再保存（最適化）
            with Image.open(source) as img:
                # PNG形式で保存（透過対応）
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')
                
                img.save(destination, 'PNG', optimize=True)
                logger.info(f"Logo saved: {destination}")
                
            return destination
            
        except (OSError, ValueError) as e:
            logger.error(f"Failed to save logo (I/O or value error): {e}", exc_info=True)
            raise
        except (AttributeError, TypeError, KeyError) as e:
            logger.error(f"Failed to save logo (unexpected error): {e}", exc_info=True)
            raise


if __name__ == "__main__":
    # テスト
    logging.basicConfig(level=logging.INFO)
    
    manager = LogoManager()
    logo = manager.get_logo_path()
    
    if logo:
        if manager.validate_logo(logo):
            size = manager.get_logo_size(logo)
            target_size = manager.calculate_target_size(size, target_height=60)
            print(f"Original: {size}")
            print(f"Target: {target_size}")
