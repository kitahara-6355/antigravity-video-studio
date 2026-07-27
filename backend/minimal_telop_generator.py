"""
Minimal Theme Telop Generator
最小情報量のテーマテロップ生成
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from typing import Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MinimalTelopGenerator:
    """最小情報量のテーマテロップ生成"""
    
    def __init__(self, output_dir: str = "backend/temp/minimal_telops"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # フォントパス
        self.font_paths = [
            "C:/Windows/Fonts/NotoSansJP-Regular.ttf",
            "C:/Windows/Fonts/Yu Gothic UI.ttf",
            "C:/Windows/Fonts/msgothic.ttc"
        ]
    
    def _get_font(self, size: int = 16):
        """フォント取得"""
        for font_path in self.font_paths:
            if Path(font_path).exists():
                try:
                    return ImageFont.truetype(font_path, size)
                except:
                    pass
        return ImageFont.load_default()
    
    def generate_minimal_telop(
        self,
        theme_text: str,
        output_path: str,
        font_size: int = 16,
        padding: int = 8
    ) -> str:
        """
        最小情報量のテロップ生成
        
        Args:
            theme_text: テーマテキスト（短く）
            output_path: 出力パス
            font_size: フォントサイズ（小さめ）
            padding: パディング（小さめ）
        """
        logger.info(f"Generating minimal telop: '{theme_text}'")
        
        if not theme_text:
            raise ValueError("theme_text cannot be empty.")
        if font_size <= 0 or font_size > 200:
            raise ValueError("Invalid font_size.")
        if padding < 0 or padding > 100:
            raise ValueError("Invalid padding.")
            
        font = self._get_font(font_size)
        
        # テキストサイズ計測（頑健なフォールバック付き）
        try:
            if hasattr(font, "getbbox"):
                bbox = font.getbbox(theme_text)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            elif hasattr(font, "getsize"):
                text_width, text_height = font.getsize(theme_text)
            else:
                text_width = len(theme_text) * (font_size // 2)
                text_height = font_size
        except (AttributeError, TypeError, ValueError, OSError):
            text_width = len(theme_text) * (font_size // 2)
            text_height = font_size
        
        # 画像サイズ（コンパクト）
        img_width = text_width + (padding * 2)
        img_height = text_height + (padding * 2)
        
        # 画像作成
        img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # 角丸背景（ごく控えめ）
        bg_color = (0, 0, 0, 51)  # 20%透明度（より控えめ）
        self._draw_rounded_rectangle(
            draw,
            (0, 0, img_width, img_height),
            3,  # 角丸小さめ
            fill=bg_color
        )
        
        # テキスト描画
        text_color = (255, 255, 255, 217)  # 85%透明度
        draw.text(
            (padding, padding),
            theme_text,
            font=font,
            fill=text_color
        )
        
        # PNG保存
        img.save(output_path, 'PNG')
        logger.info(f"Minimal telop: {output_path} ({img_width}x{img_height})")
        
        return output_path
    
    def _draw_rounded_rectangle(self, draw, xy, corner_radius, fill):
        """角丸矩形描画"""
        if hasattr(draw, "rounded_rectangle"):
            # Pillow 8.2.0 以降の標準メソッドを使用（安全かつ最適化されている）
            draw.rounded_rectangle(xy, radius=corner_radius, fill=fill)
            return
            
        x0, y0, x1, y1 = xy
        
        # corner_radius のクリッピング安全策
        max_radius = min((x1 - x0) // 2, (y1 - y0) // 2)
        corner_radius = max(0, min(corner_radius, max_radius))
        
        if corner_radius == 0:
            draw.rectangle(xy, fill=fill)
            return
            
        # 中央矩形
        draw.rectangle((x0 + corner_radius, y0, x1 - corner_radius, y1), fill=fill)
        draw.rectangle((x0, y0 + corner_radius, x1, y1 - corner_radius), fill=fill)
        
        # 4つの角
        draw.ellipse((x0, y0, x0 + corner_radius * 2, y0 + corner_radius * 2), fill=fill)
        draw.ellipse((x1 - corner_radius * 2, y0, x1, y0 + corner_radius * 2), fill=fill)
        draw.ellipse((x0, y1 - corner_radius * 2, x0 + corner_radius * 2, y1), fill=fill)
        draw.ellipse((x1 - corner_radius * 2, y1 - corner_radius * 2, x1, y1), fill=fill)


# テーマ一覧生成
def generate_all_theme_telops():
    """全テーマテロップを生成"""
    
    themes = {
        "scene01_theme1": "対談：手書き文字の価値",
        "scene01_theme2": "伝統工芸の未来",
        "scene01_theme3": "想いを筆で起こす",
        "scene03_theme1": "書道家の使命",
        "scene03_theme2": "文字文化の継承",
        "scene04_theme1": "筆の話",
        "scene04_theme2": "書道の未来",
    }
    
    generator = MinimalTelopGenerator()
    generated = {}
    
    for key, theme in themes.items():
        output_path = generator.output_dir / f"{key}.png"
        generator.generate_minimal_telop(theme, str(output_path))
        generated[theme] = str(output_path)
    
    return generated


if __name__ == "__main__":
    telops = generate_all_theme_telops()
    
    print("\n" + "="*60)
    print("生成されたテーマテロップ一覧")
    print("="*60)
    for theme, path in telops.items():
        print(f"・{theme}")
        print(f"  → {Path(path).name}")
