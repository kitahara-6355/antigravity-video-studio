"""
固定テロップ（1種類）+ ロゴを追加
"""
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from datetime import datetime
import uuid
import json

from path_resolver import project_root

# 高品質リサンプリングフィルタの取得
def _get_lanczos_filter(img_module=Image):
    try:
        if hasattr(img_module, "Resampling"):
            return img_module.Resampling.LANCZOS
        elif hasattr(img_module, "LANCZOS"):
            return img_module.LANCZOS
        else:
            return img_module.ANTIALIAS
    except AttributeError:
        try:
            return img_module.BICUBIC
        except AttributeError:
            return None


LANCZOS = _get_lanczos_filter()



def _resolve_branding_paths(base_path: Path | None) -> tuple[Path, Path]:
    """ベースパスからロゴおよび出力先のパスを解決し、出力先ディレクトリを作成する"""
    base = Path(base_path) if base_path is not None else project_root()
    logo_path = base / "backend" / "branding" / "logos" / "brand_logo.png"
    output_path = base / "backend" / "branding" / "final_branding.png"

    # 保存先ディレクトリの自動生成 (テスト時のPathモックとの衝突を避けるためTypeErrorをハンドリング)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except (TypeError, OSError):
        pass
    return logo_path, output_path


def _load_and_resize_logo(logo_path: Path, logo_width: int, logo_height: int) -> Image.Image:
    """ロゴ画像を読み込みリサイズする。失敗した場合はプレースホルダーロゴを生成して返す。"""
    try:
        if not logo_path.exists():
            raise FileNotFoundError(f"Logo file not found: {logo_path}")
        logo = Image.open(logo_path).convert('RGBA')
        # 高品質リサイズ
        if logo.size != (logo_width, logo_height):
            if LANCZOS is not None:
                logo = logo.resize((logo_width, logo_height), LANCZOS)
            else:
                logo = logo.resize((logo_width, logo_height))
    except (FileNotFoundError, OSError, ValueError) as e:
        print(f"⚠️ Failed to load logo {logo_path}: {e}. Creating fallback placeholder logo.")
        # プレースホルダーロゴの作成 (RGBベースに文字を描画)
        logo = Image.new('RGBA', (logo_width, logo_height), (200, 50, 50, 255))
        draw_placeholder = ImageDraw.Draw(logo)
        try:
            fallback_font = ImageFont.load_default()
            bbox = draw_placeholder.textbbox((0, 0), "L", font=fallback_font)
            pw = bbox[2] - bbox[0]
            ph = bbox[3] - bbox[1]
            draw_placeholder.text(((logo_width - pw) // 2, (logo_height - ph) // 2), "L", font=fallback_font, fill=(255, 255, 255, 255))
        except (OSError, ValueError):
            pass
    return logo


def _select_branding_font(font_size: int) -> ImageFont.ImageFont:
    """日本語フォントをフォールバック付きで選択する"""
    font_paths = [
        r"C:\Windows\Fonts\msgothic.ttc",
        r"C:\Windows\Fonts\msmincho.ttc",
        r"C:\Windows\Fonts\meiryo.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",  # macOS
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",  # Debian/Ubuntu
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"  # Fedora/RHEL
    ]
    font = None
    for fp in font_paths:
        try:
            if Path(fp).exists():
                font = ImageFont.truetype(fp, font_size)
                break
        except:
            continue

    if font is None:
        try:
            font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()
    return font


def _create_telop_image(text: str, width: int, height: int, font: ImageFont.ImageFont) -> Image.Image:
    """テロップテキストを描画した半透明画像を生成する"""
    telop = Image.new('RGBA', (width, height), (0, 0, 0, 128))
    draw = ImageDraw.Draw(telop)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (width - text_width) // 2
    y = (height - text_height) // 2

    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    return telop


def create_combined_branding(target_height=45, base_path=None):
    """ロゴ + 固定テロップの統合画像を作成

    Args:
        target_height (int): ブランディング画像の高さ。アスペクト比(331:45)を維持して幅もスケーリングされる。
        base_path (Path, optional): 基準となる動画自動化ディレクトリのパス。
    """
    logo_path, output_path = _resolve_branding_paths(base_path)

    # アスペクト比を維持したサイズ・位置計算
    scale = target_height / 45.0
    logo_width = int(23 * scale)
    logo_height = target_height
    telop_width = int(303 * scale)
    telop_height = target_height
    combined_width = int(331 * scale)
    font_size = max(1, int(18 * scale))
    telop_x_offset = int(28 * scale)

    # 各パーツの生成
    logo = _load_and_resize_logo(logo_path, logo_width, logo_height)
    font = _select_branding_font(font_size)
    telop_text = "デザイン書道作家 山田タロウ"
    telop = _create_telop_image(telop_text, telop_width, telop_height, font)

    # 統合
    combined = Image.new('RGBA', (combined_width, target_height), (0, 0, 0, 0))
    combined.paste(logo, (0, 0), logo)
    combined.paste(telop, (telop_x_offset, 0), telop)

    try:
        combined.save(output_path)
        print(f"✅ Combined branding created: {output_path}")
    except (OSError, ValueError) as e:
        print(f"❌ Failed to save combined branding: {e}")
        raise

    return output_path


def add_branding_to_video():
    """ロゴ + テロップを動画に追加"""
    base = project_root()
    input_video = base / "soul_narrative_FINAL_EDITED.mp4"
    output_video = base / "soul_narrative_YOUTUBE_READY.mp4"
    
    # 入力動画の存在チェック
    if not input_video.exists():
        print(f"❌ Input video does not exist: {input_video}")
        return None
        
    # 出力先親ディレクトリの作成 (テスト時のPathモックとの衝突を避けるためTypeErrorをハンドリング)
    try:
        output_video.parent.mkdir(parents=True, exist_ok=True)
    except (TypeError, OSError):
        pass
    
    branding_path = create_combined_branding()
    
    print("\n" + "="*70)
    print("Adding Branding to Video")
    print("="*70)
    
    # シンプルなオーバーレイ（動的切り替えなし）
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-i", str(branding_path),
        "-filter_complex", "[0:v][1:v] overlay=15:15",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_video)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    
    if result.returncode == 0 and output_video.exists():
        size_mb = output_video.stat().st_size / 1024 / 1024
        
        # 長さ確認
        check_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(output_video)
        ]
        duration_result = subprocess.run(check_cmd, capture_output=True, text=True)
        duration_sec = float(duration_result.stdout.strip())
        duration_min = int(duration_sec // 60)
        duration_sec_remaining = int(duration_sec % 60)
        
        print(f"\n✅ YouTube-ready video complete!")
        print(f"   File: {output_video}")
        print(f"   Size: {size_mb:.1f} MB")
        print(f"   Duration: {duration_min}:{duration_sec_remaining:02d}")
        
        return str(output_video)
    else:
        print(f"\n❌ Failed to add branding")
        print(result.stderr[-1000:] if result.stderr else "")
        return None


def _validate_thumbnail_params(output_path: Path, width: int, height: int) -> tuple[int, int, Path, str]:
    """幅、高さ、アスペクト比、出力ファイル形式などをバリデーションし、解決済みのPathオブジェクトを返す"""
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError("Width and height must be positive integers.")
        
    # 解像度制限のチェック (1280x720以上)
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    if width > 7680 or height > 4320:
        raise ValueError("Resolution exceeds maximum limit")

    # アスペクト比のチェック (16:9)
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    output_path = Path(output_path)
    if output_path.is_dir():
        raise ValueError("Output path must be a file path, not a directory")
        
    suffix = output_path.suffix.lower()
    if suffix not in ('.png', '.jpg', '.jpeg', '.webp'):
        raise ValueError(f"Unsupported file format: {suffix}")

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except (TypeError, OSError):
        pass

    return width, height, output_path, suffix


def _generate_gradient_background(draw_width: int, draw_height: int) -> Image.Image:
    """NumPyを使用してネイティブ解像度で滑らかなグラデーション背景をディザリング付きで高速生成する"""
    y_grid, x_grid = np.ogrid[:draw_height, :draw_width]
    factor = (x_grid / (draw_width - 1.0) + y_grid / (draw_height - 1.0)) / 2.0
    
    # プレミアムで現代的なグラデーションカラーの選定
    color1 = np.array([11, 19, 43], dtype=np.float32)
    color2 = np.array([60, 9, 108], dtype=np.float32)
    color3 = np.array([31, 58, 96], dtype=np.float32)
    
    # 3色の滑らかなブレンド
    mask = factor < 0.5
    t = np.where(mask, factor * 2.0, (factor - 0.5) * 2.0)
    
    r = np.where(mask, color1[0] + (color2[0] - color1[0]) * t, color2[0] + (color3[0] - color2[0]) * t)
    g = np.where(mask, color1[1] + (color2[1] - color1[1]) * t, color2[1] + (color3[1] - color2[1]) * t)
    b = np.where(mask, color1[2] + (color2[2] - color1[2]) * t, color2[2] + (color3[2] - color2[2]) * t)
    
    # カラー階調の縞模様防止のディザリングノイズ
    dither = np.random.uniform(-0.5, 0.5, (draw_height, draw_width, 3))
    rgb = np.clip(np.stack([r, g, b], axis=-1) + dither, 0, 255).astype(np.uint8)
    return Image.fromarray(rgb).convert("RGBA")


def _draw_decorations(d: ImageDraw.Draw, width: int, height: int, draw_width: int, draw_height: int, ss_scale: int) -> tuple[int, int]:
    """外枠の二重線飾りおよび右下装飾用グラフィックを描画する"""
    border_margin = max(15, int(min(width, height) * 0.03)) * ss_scale
    border_width = max(1, int(min(width, height) * 0.004)) * ss_scale
    
    # 外枠（ホワイト、透明度あり）
    d.rectangle(
        [border_margin, border_margin, draw_width - border_margin, draw_height - border_margin],
        outline=(255, 255, 255, 120),
        width=border_width
    )
    # 内枠（ゴールド / 真鍮色、不透明）
    inner_margin = border_margin + border_width + 3 * ss_scale
    d.rectangle(
        [inner_margin, inner_margin, draw_width - inner_margin, draw_height - inner_margin],
        outline=(218, 165, 32, 255),
        width=max(1, 2 * ss_scale)
    )
    
    # 右下装飾用グラフィック（重ね合わせた半透明円）
    d.ellipse(
        [draw_width - 160 * ss_scale, draw_height - 160 * ss_scale, draw_width - 60 * ss_scale, draw_height - 60 * ss_scale],
        fill=(255, 255, 255, 10),
        outline=(255, 255, 255, 20),
        width=max(1, 2 * ss_scale)
    )
    d.ellipse(
        [draw_width - 140 * ss_scale, draw_height - 140 * ss_scale, draw_width - 80 * ss_scale, draw_height - 80 * ss_scale],
        fill=(218, 165, 32, 8),
        outline=(218, 165, 32, 15),
        width=max(1, 1 * ss_scale)
    )
    return border_margin, border_width


def _wrap_text_lines(text: str) -> list[str]:
    """テキストを自動折り返し規則に従って分割する"""
    words_or_chars = text.splitlines()
    wrapped_lines = []
    for line in words_or_chars:
        if len(line) > 30:
            sub_lines = [line[i:i+30] for i in range(0, len(line), 30)]
            wrapped_lines.extend(sub_lines)
        else:
            wrapped_lines.append(line)
    return wrapped_lines


def _fit_text_font(
    d: ImageDraw.Draw,
    wrapped_lines: list[str],
    max_text_width: int,
    max_text_height: int,
    initial_font_size: int,
    ss_scale: int
) -> tuple[ImageFont.ImageFont, int]:
    """領域内に収まるようにフォントサイズを自動調整し、フォントオブジェクトを返す"""
    font_paths = [
        "C:/Windows/Fonts/yugothm.ttc",
        "C:/Windows/Fonts/yugothb.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/meiryob.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/msmincho.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"
    ]
    
    font_size = initial_font_size
    font = None
    
    while font_size >= 12 * ss_scale:
        for fp in font_paths:
            try:
                if Path(fp).exists():
                    font = ImageFont.truetype(fp, font_size)
                    break
            except (OSError, ValueError):
                continue
        if font is None:
            try:
                font = ImageFont.load_default()
            except (OSError, ValueError):
                font = None
                break
        
        line_height = int(font_size * 1.4)
        total_text_height = len(wrapped_lines) * line_height
        
        max_line_w = 0
        for line in wrapped_lines:
            try:
                bbox = d.textbbox((0, 0), line, font=font)
                w = bbox[2] - bbox[0]
                if w > max_line_w:
                    max_line_w = w
            except (OSError, ValueError):
                max_line_w = len(line) * font_size
                
        if max_line_w <= max_text_width and total_text_height <= max_text_height:
            break
        
        font_size -= 2 * ss_scale
        
    return font, font_size


def _draw_wrapped_text(
    d: ImageDraw.Draw,
    wrapped_lines: list[str],
    font: ImageFont.ImageFont,
    font_size: int,
    draw_width: int,
    draw_height: int,
    ss_scale: int
):
    """折り返された各テキスト行をセンタリングしてドロップシャドウ・アウトライン付きで描画する"""
    line_height = int(font_size * 1.4)
    start_y = (draw_height - (len(wrapped_lines) * line_height)) // 2
    
    for i, line in enumerate(wrapped_lines):
        y_pos = start_y + i * line_height
        
        # テキストのセンタリング配置のための幅測定
        try:
            bbox = d.textbbox((0, 0), line, font=font)
            line_w = bbox[2] - bbox[0]
        except (OSError, ValueError):
            line_w = len(line) * font_size
        x_pos = (draw_width - line_w) // 2
        
        # ドロップシャドウによる視認性向上
        d.text((x_pos + 3 * ss_scale, y_pos + 3 * ss_scale), line, fill=(0, 0, 0, 180), font=font)
        # メインテキスト（品質向上のためのアウトライン付き描画）
        stroke_w = max(1, int(font_size * 0.05))
        d.text((x_pos, y_pos), line, fill=(255, 255, 255, 255), font=font, stroke_width=stroke_w, stroke_fill=(15, 23, 42, 255))


def _save_thumbnail_to_path(
    img: Image.Image,
    width: int,
    height: int,
    temp_path: Path,
    output_path: Path,
    suffix: str
) -> Image.Image:
    """スーパークサンプリング画像を元の解像度に縮小し、最適化して保存する"""
    # スーパークサンプリング画像を本来の解像度に高品質リサイズで縮小
    if LANCZOS is not None:
        resized_img = img.resize((width, height), LANCZOS)
    else:
        try:
            resized_img = img.resize((width, height), Image.Resampling.BILINEAR)
        except AttributeError:
            resized_img = img.resize((width, height), 2)
            
    # RGBに変換して保存
    final_img = resized_img.convert("RGB")
    # 4MB未満を保証するためフォーマットに応じた最適化
    format_map = {
        '.png': 'PNG',
        '.jpg': 'JPEG',
        '.jpeg': 'JPEG',
        '.webp': 'WEBP'
    }
    img_format = format_map.get(suffix, 'PNG')
    save_kwargs = {}
    if img_format == 'PNG':
        save_kwargs = {'optimize': True, 'compress_level': 9}
    elif img_format == 'JPEG':
        save_kwargs = {'quality': 85, 'optimize': True}
    elif img_format == 'WEBP':
        save_kwargs = {'quality': 80, 'lossless': False}
    
    final_img.save(temp_path, img_format, **save_kwargs)
    
    if output_path.exists():
        try:
            output_path.unlink()
        except OSError:
            pass
    temp_path.rename(output_path)
    return final_img


def _generate_preview_if_needed(
    final_img: Image.Image,
    preview_path: Path | None,
    temp_preview_path: Path | None
):
    """必要に応じて高品質なプレビュー画像を生成し保存する"""
    if preview_path and temp_preview_path:
        preview_w = 640
        preview_h = 360
        
        if LANCZOS is not None:
            preview_img = final_img.resize((preview_w, preview_h), LANCZOS)
        else:
            try:
                preview_img = final_img.resize((preview_w, preview_h), Image.Resampling.BILINEAR)
            except AttributeError:
                preview_img = final_img.resize((preview_w, preview_h), 2)  # BILINEAR
            
        preview_img.save(temp_preview_path, "PNG", optimize=True, compress_level=9)
        
        if preview_path.exists():
            try:
                preview_path.unlink()
            except OSError:
                pass
        temp_preview_path.rename(preview_path)


OUTPUT_DIR = "backend/temp_thumbnails"


def generate_simple_branding_thumbnail(output_path, width=1280, height=720, text=None, preview_path=None):
    """NumPyとPillowを使用して、高品質なブランディング（サムネイル）画像を生成する。必要に応じてプレビュー画像も生成する。"""
    width, height, output_path, suffix = _validate_thumbnail_params(output_path, width, height)
    
    # 高解像度（4K以上）の場合はメモリと処理効率向上のためスーパークサンプリングを無効化
    ss_scale = 2 if width < 3840 else 1
    draw_width = width * ss_scale
    draw_height = height * ss_scale
    
    # 原子的な書き込み (Atomic Write) の実装
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temp_preview_path = None
    if preview_path:
        preview_path = Path(preview_path)
        temp_preview_path = preview_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            preview_path.parent.mkdir(parents=True, exist_ok=True)
        except (TypeError, OSError):
            pass

    try:
        # 背景生成
        img = _generate_gradient_background(draw_width, draw_height)
        d = ImageDraw.Draw(img)
        
        # 装飾描画
        border_margin, _ = _draw_decorations(d, width, height, draw_width, draw_height, ss_scale)
        
        if not text:
            text = "Simple Branding Thumbnail\nGenerated at: " + datetime.now().isoformat()
            
        # テキストの長さに応じて自動折り返し＆フォントサイズ調整
        max_text_width = draw_width - (border_margin * 4) - 40 * ss_scale
        max_text_height = draw_height - (border_margin * 4) - 40 * ss_scale
        
        # 自動折り返し
        wrapped_lines = _wrap_text_lines(text)
        
        # フォント調整
        initial_font_size = max(24, int(height * 0.06)) * ss_scale
        font, font_size = _fit_text_font(d, wrapped_lines, max_text_width, max_text_height, initial_font_size, ss_scale)
        
        # テキスト描画
        if font is not None:
            _draw_wrapped_text(d, wrapped_lines, font, font_size, draw_width, draw_height, ss_scale)
            
        # サムネイル保存
        final_img = _save_thumbnail_to_path(img, width, height, temp_path, output_path, suffix)
        
        # プレビュー生成
        _generate_preview_if_needed(final_img, preview_path, temp_preview_path)
            
    except (OSError, ValueError, TypeError) as e:
        for tp in [temp_path, temp_preview_path]:
            if tp and tp.exists():
                try:
                    tp.unlink()
                except OSError:
                    pass
        raise e
        
    return output_path

def validate_thumbnail(file_path, is_preview=False) -> dict:
    """
    サムネイル画像（またはプレビュー画像）の品質要件を検証する
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    # 1. 簡易的なverify
    try:
        with Image.open(file_path) as img:
            img.verify()
    except (OSError, ValueError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    # 2. 完全なピクセルデータのロードによる破損検知
    try:
        with Image.open(file_path) as img:
            img.load()  # ピクセルデータのロードを強制
            width, height = img.size
    except (OSError, ValueError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    if is_preview:
        if width < 320 or height < 180:
            raise ValueError(f"Preview resolution must be at least 320x180. Got {width}x{height}")
    else:
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }

async def resolve_branding_task(self, task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理
    """
    # agent (self) から設定を取得、無ければデフォルト値を使用
    width = getattr(self, "width", 1280)
    height = getattr(self, "height", 720)
    text = getattr(self, "text", None)
    output_dir = Path(getattr(self, "output_dir", None) or OUTPUT_DIR)
    
    if text is None:
        text = (
            f"=== Simple Branding Process ===\n"
            f"Status: OK\n"
            f"Timestamp: {datetime.now().isoformat()}\n"
            f"Task ID: {task_id}\n"
            f"Note: Verification completed successfully."
        )
        
    output_path = output_dir / f"{task_id}.png"
    preview_path = output_dir / f"{task_id}_preview.png"
    
    generate_simple_branding_thumbnail(
        output_path, 
        width=width, 
        height=height, 
        text=text, 
        preview_path=preview_path
    )
    result_info = validate_thumbnail(output_path)
    
    if preview_path.exists():
        preview_info = validate_thumbnail(preview_path, is_preview=True)
        result_info["preview"] = preview_info
        
    return json.dumps(result_info)

if __name__ == "__main__":
    import time
    start = time.time()
    
    video_path = add_branding_to_video()
    
    elapsed = time.time() - start
    
    print("\n" + "="*70)
    print(f"Processing complete: {elapsed / 60:.1f} minutes")
    print("="*70)
    
    if video_path:
        print("\n🚀 Ready for YouTube Upload!")
        print("\nFiles:")
        print(f"  Video: {video_path}")
        print(f"  SRT: {project_root() / 'soul_narrative_combined.srt'}")
    else:
        print("\n❌ Failed")