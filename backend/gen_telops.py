"""動画用テロップ画像を自動生成するモジュール。

Pillowライブラリを使用して、ブランドロゴと背景画像、指定されたテーマテキストを
組み合わせたRGBA形式のテロップ画像（PNG）を生成します。
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from path_resolver import project_root

# 環境変数（VIDEO_AUTOMATION_BASE_DIR / ANTIGRAVITY_BASE_DIR）があればそちら、
# なければスクリプトの位置から算出する。
# 以前はここに絶対パスの最終フォールバックがあったが、
# 「backend/ が見つからない」ときに特定マシンのパスを指しても直らないため外した。
DEFAULT_BASE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = project_root()

TEMP_DIR = BASE_DIR / "backend" / "temp" / "final_build"
LOGO_PATH = BASE_DIR / "backend" / "branding" / "logos" / "brand_logo.png"

# OSごとのデフォルトフォントパス（Windows, macOS, Linux）の候補
DEFAULT_FONTS = [
    r"C:\Windows\Fonts\msgothic.ttc",
    r"C:\Windows\Fonts\msmincho.ttc",
    "/System/Library/Fonts/JPN/Hiragino Mincho ProN.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.otf"
]

FONT_PATH = None
for fp in DEFAULT_FONTS:
    if Path(fp).exists():
        FONT_PATH = fp
        break

# 出力先ディレクトリの確保
TEMP_DIR.mkdir(parents=True, exist_ok=True)

THEMES = [
    "デザイン書道作家 山田タロウ",
    "伝統の筆づくり 存続の危機",
    "企業ロゴを筆で書く デザイン書道",
    "山田氏のゲスト書道パフォーマンス",
    "山田流：有名ブランドの書を手がける",
    "ユニクロ×書道 未来を繋ぐ挑戦",
    "鬼滅の刃×書道 山田の筆技",
    "有名人も注目！山田の書道教室"
]

def _load_font(font_path: str | None, size: int = 18) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """指定されたパスからTrueTypeフォントを読み込みます。

    フォントの読み込みに失敗した場合、またはフォントパスが指定されていない場合は、
    Pillowのデフォルトフォントにフォールバックします。

    Args:
        font_path (str | None): 読み込むフォントファイルの絶対パスまたは相対パス。
        size (int, optional): フォントサイズ。デフォルトは 18。

    Returns:
        ImageFont.ImageFont | ImageFont.FreeTypeFont: 読み込まれたフォントオブジェクト。
    """
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except OSError as e:
            print(f"⚠️ フォントファイルの読み込みに失敗しました ({e})。デフォルトフォントを使用します。")
    else:
        print("⚠️ 指定されたフォントが見つからなかったため、デフォルトフォントを使用します。")
    return ImageFont.load_default()

def _load_logo(logo_path: Path) -> Image.Image:
    """指定されたパスからブランドロゴ画像を読み込みます。

    Args:
        logo_path (Path): ロゴ画像のファイルパス。

    Returns:
        Image.Image: 読み込まれたロゴ画像のPILオブジェクト。

    Raises:
        FileNotFoundError: 指定されたファイルが見つからない場合。
        OSError: 画像ファイルを開く際にエラーが発生した場合。
    """
    try:
        return Image.open(logo_path)
    except FileNotFoundError:
        print(f"❌ ロゴファイルが見つかりません: {logo_path}")
        raise
    except OSError as e:
        print(f"❌ ロゴファイルのオープンに失敗しました ({e}): {logo_path}")
        raise

def _create_telop_image(text: str, font: ImageFont.ImageFont | ImageFont.FreeTypeFont) -> Image.Image:
    """指定されたテキストとフォントを使用して、黒い半透明背景のテロップ画像を生成します。

    Args:
        text (str): テロップに表示する文字列。
        font (ImageFont.ImageFont | ImageFont.FreeTypeFont): 描画に使用するフォント。

    Returns:
        Image.Image: 生成されたRGBA形式のテロップ画像（サイズ: 400x45）。
    """
    img = Image.new('RGBA', (400, 45), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 400, 45), fill=(0, 0, 0, 128))
    draw.text((12, 12), text, font=font, fill=(255, 255, 255, 255))
    return img

def _resize_logo(logo: Image.Image, size: tuple[int, int] = (23, 45)) -> Image.Image:
    """ブランドロゴ画像を合成用のサイズにリサイズします。

    リサイズ時のフィルタには Image.Resampling.LANCZOS を使用します。

    Args:
        logo (Image.Image): リサイズ元のPIL画像。
        size (tuple[int, int], optional): リサイズ後の幅と高さ。デフォルトは (23, 45)。

    Returns:
        Image.Image: リサイズされたRGBA形式（または元の形式）の画像。

    Raises:
        ValueError: リサイズサイズが不正な場合。
        OSError: 画像処理中にエラーが発生した場合。
    """
    try:
        return logo.resize(size, Image.Resampling.LANCZOS)
    except (ValueError, OSError) as e:
        print(f"❌ ロゴ画像のリサイズに失敗しました: {e}")
        raise

def _composite_telop(logo_resized: Image.Image, telop_img: Image.Image) -> Image.Image:
    """リサイズされたロゴ画像とテロップ背景画像を水平に連結して合成します。

    合成後の画像サイズは 430x45 で、ロゴ（左側）とテロップ（右側、x=28）を配置します。

    Args:
        logo_resized (Image.Image): リサイズ済みのロゴ画像。
        telop_img (Image.Image): テキスト描画済みのテロップ画像。

    Returns:
        Image.Image: 合成されたRGBA形式の最終画像。
    """
    combined = Image.new('RGBA', (430, 45), (0, 0, 0, 0))
    combined.paste(logo_resized, (0, 0), logo_resized if logo_resized.mode == 'RGBA' else None)
    combined.paste(telop_img, (28, 0), telop_img)
    return combined

def _save_telop(image: Image.Image, save_path: Path) -> None:
    """生成されたテロップ画像をファイルに保存します。

    Args:
        image (Image.Image): 保存する画像。
        save_path (Path): 保存先のファイルパス。

    Raises:
        OSError: 画像の保存処理に失敗した場合（ディスクフル、書き込み権限不足など）。
    """
    try:
        image.save(save_path)
    except OSError as e:
        print(f"❌ 画像の保存に失敗しました: {save_path} ({e})")
        raise

def generate_telops() -> None:
    """指定されたテーマのテロップ画像を生成し、一時ディレクトリに保存します。

    ロゴ画像と背景、テキストを重ね合わせたRGBA形式の画像を生成します。
    フォントやロゴファイルの読み込みエラー、画像の保存エラーに対して堅牢なハンドリングを行います。

    Raises:
        FileNotFoundError: ロゴファイルが存在しない場合。
        OSError: フォントの読み込みや画像の保存に失敗した場合。
        ValueError: ロゴ画像のリサイズなどに失敗した場合。
    """
    font = _load_font(FONT_PATH)
    logo = _load_logo(LOGO_PATH)

    try:
        for i, text in enumerate(THEMES):
            if not isinstance(text, str):
                print(f"⚠️ インデックス {i} のテーマは文字列ではないためスキップします: {text}")
                continue

            telop_img = _create_telop_image(text, font)
            logo_resized = _resize_logo(logo)
            combined = _composite_telop(logo_resized, telop_img)

            save_path = TEMP_DIR / f"brand_telop_{i}.png"
            _save_telop(combined, save_path)
    finally:
        logo.close()

    print("✅ テロップ生成完了")

if __name__ == "__main__":
    generate_telops()
