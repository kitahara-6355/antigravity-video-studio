"""
Theme Telop Generator
Phase 30 - Week 3 Implementation

動画のテーマテロップを生成する機能
高級感のあるデザインで、上段に表示
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from typing import Tuple, Optional
import os
import logging

logger = logging.getLogger(__name__)


class ThemeTelopGenerator:
    """テーマテロップ生成クラス"""
    
    def __init__(self, output_dir: str = "backend/temp"):
        """
        Args:
            output_dir: 出力ディレクトリ
        """
        self.output_dir = Path(output_dir)
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create output directory {output_dir}: {e}")
            raise
        
        # デフォルトフォント（Windows, Linux/Docker環境両対応）
        self.font_paths = []
        
        # 環境変数によるフォント指定を最優先
        env_font = os.environ.get("THEME_TELOP_FONT_PATH")
        if env_font:
            self.font_paths.append(env_font)
            
        self.font_paths.extend([
            # Windows
            "C:/Windows/Fonts/NotoSansJP-Regular.ttf",
            "C:/Windows/Fonts/Yu Gothic UI.ttf",
            "C:/Windows/Fonts/msgothic.ttc",
            "C:/Windows/Fonts/arial.ttf",
            # Linux / Docker
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/fonts-japanese-gothic.ttf"
        ])
    
    def _get_font(self, size: int = 24) -> ImageFont.FreeTypeFont:
        """
        フォントを取得
        
        Args:
            size: フォントサイズ
        
        Returns:
            PIL Font object
        """
        # フォントサイズ制限 (リソース制限)
        if not (8 <= size <= 200):
            raise ValueError(f"Invalid font size: {size}. Must be between 8 and 200.")

        for font_path in self.font_paths:
            if Path(font_path).exists():
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception as e:
                    logger.warning(f"Failed to load font file '{font_path}' (invalid format or read error): {e}")
        
        # フォールバック: デフォルトフォント
        logger.warning("Using default font")
        return ImageFont.load_default()
    
    def _validate_telop_params(
        self,
        text: str,
        font_size: int,
        padding: int,
        border_radius: int
    ) -> None:
        """入力パラメータのバリデーション"""
        if not text:
            raise ValueError("Text cannot be empty.")
        if len(text) > 200:
            raise ValueError(f"Text length ({len(text)}) exceeds maximum allowed (200 characters).")
        if not (8 <= font_size <= 200):
            raise ValueError(f"Invalid font_size: {font_size}. Must be between 8 and 200.")
        if not (0 <= padding <= 100):
            raise ValueError(f"Invalid padding: {padding}. Must be between 0 and 100.")
        if not (0 <= border_radius <= 100):
            raise ValueError(f"Invalid border_radius: {border_radius}. Must be between 0 and 100.")

    def _measure_text_size(self, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
        """テキストの描画サイズを計測"""
        dummy_img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
        dummy_draw = ImageDraw.Draw(dummy_img)
        bbox = dummy_draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        return text_width, text_height

    def _create_telop_image(
        self,
        text: str,
        font: ImageFont.FreeTypeFont,
        img_width: int,
        img_height: int,
        text_color: Tuple[int, int, int, int],
        bg_color: Tuple[int, int, int, int],
        padding: int,
        border_radius: int
    ) -> Image.Image:
        """透過テロップ画像を生成して描画"""
        img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # 背景描画
        if border_radius > 0:
            self._draw_rounded_rectangle(
                draw,
                (0, 0, img_width, img_height),
                border_radius,
                fill=bg_color
            )
        else:
            draw.rectangle(
                (0, 0, img_width, img_height),
                fill=bg_color
            )
        
        # テキスト描画（左上のパディング位置から描画）
        draw.text(
            (padding, padding),
            text,
            font=font,
            fill=text_color
        )
        return img

    def _save_image(self, img: Image.Image, output_path: str) -> Path:
        """生成した画像をPNG形式で保存"""
        path_obj = Path(output_path)
        try:
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            img.save(path_obj, 'PNG')
        except OSError as e:
            logger.error(f"Failed to save telop image to {output_path}: {e}")
            raise OSError(f"Could not save generated telop image: {e}") from e
        return path_obj

    def generate_telop(
        self,
        text: str,
        output_path: str,
        font_size: int = 24,
        text_color: Tuple[int, int, int, int] = (255, 255, 255, 255),  # 白
        bg_color: Tuple[int, int, int, int] = (0, 0, 0, 77),  # 半透明黒（30%）
        padding: int = 10,
        border_radius: int = 5
    ) -> str:
        """
        テーマテロップを生成
        
        Args:
            text: テロップテキスト
            output_path: 出力パス
            font_size: フォントサイズ
            text_color: テキスト色 (R, G, B, A)
            bg_color: 背景色 (R, G, B, A)
            padding: パディング（px）
            border_radius: 角丸半径（px）
        
        Returns:
            出力ファイルパス
        """
        self._validate_telop_params(text, font_size, padding, border_radius)

        logger.info(f"Generating theme telop: '{text}'")
        
        font = self._get_font(font_size)
        
        text_width, text_height = self._measure_text_size(text, font)
        img_width = text_width + (padding * 2)
        img_height = text_height + (padding * 2)
        
        max_width, max_height = 3840, 2160
        if img_width > max_width or img_height > max_height:
            raise ValueError(
                f"Generated image dimensions ({img_width}x{img_height}) "
                f"exceed safety limits ({max_width}x{max_height})."
            )
        
        img = self._create_telop_image(
            text=text,
            font=font,
            img_width=img_width,
            img_height=img_height,
            text_color=text_color,
            bg_color=bg_color,
            padding=padding,
            border_radius=border_radius
        )
        
        saved_path = self._save_image(img, output_path)
        
        logger.info(f"Telop generated: {saved_path} ({img_width}x{img_height})")
        return str(saved_path)
    
    def _draw_rounded_rectangle(
        self,
        draw: ImageDraw.Draw,
        rect_coords: Tuple[int, int, int, int],
        corner_radius: int,
        fill: Tuple[int, int, int, int]
    ) -> None:
        """
        角丸矩形を描画
        
        Args:
            draw: ImageDraw object
            rect_coords: (x0, y0, x1, y1)
            corner_radius: 角丸半径
            fill: 塗りつぶし色
        """
        x0, y0, x1, y1 = rect_coords
        
        img_w = x1 - x0
        img_h = y1 - y0
        max_r = min(img_w, img_h) // 2
        corner_radius = max(0, min(corner_radius, max_r))
        
        if corner_radius == 0:
            draw.rectangle(rect_coords, fill=fill)
            return

        draw.rectangle(
            (x0 + corner_radius, y0, x1 - corner_radius, y1),
            fill=fill
        )
        draw.rectangle(
            (x0, y0 + corner_radius, x1, y1 - corner_radius),
            fill=fill
        )
        
        draw.ellipse(
            (x0, y0, x0 + corner_radius * 2, y0 + corner_radius * 2),
            fill=fill
        )
        draw.ellipse(
            (x1 - corner_radius * 2, y0, x1, y0 + corner_radius * 2),
            fill=fill
        )
        draw.ellipse(
            (x0, y1 - corner_radius * 2, x0 + corner_radius * 2, y1),
            fill=fill
        )
        draw.ellipse(
            (x1 - corner_radius * 2, y1 - corner_radius * 2, x1, y1),
            fill=fill
        )
    
    def generate_video_theme_telop(
        self,
        speaker1: str,
        speaker2: str,
        theme: str,
        output_path: Optional[str] = None
    ) -> str:
        """
        動画のテーマテロップを生成
        
        Args:
            speaker1: 話者1（例: "北原美麗"）
            speaker2: 話者2（例: "山田タロウ"）
            theme: テーマ（例: "想いを筆で起こす"）
            output_path: 出力パス（省略時は自動生成）
        
        Returns:
            出力ファイルパス
        """
        # テロップテキスト生成
        telop_text = f"{speaker1} × {speaker2}"
        
        if theme:
            telop_text += f"：{theme}"
        
        # 出力パス決定
        if output_path is None:
            output_path = self.output_dir / "theme_telop.png"
        
        # テロップ生成
        return self.generate_telop(
            text=telop_text,
            output_path=str(output_path),
            font_size=24,
            padding=12,
            border_radius=5
        )


def main():
    generator = ThemeTelopGenerator()
    
    # サンプル生成
    telop_path = generator.generate_video_theme_telop(
        speaker1="北原美麗",
        speaker2="山田タロウ",
        theme="想いを筆で起こす",
        output_path="backend/temp/theme_telop_test.png"
    )
    
    print(f"Generated telop: {telop_path}")


if __name__ == "__main__":
    # テスト
    logging.basicConfig(level=logging.INFO)
    main()
