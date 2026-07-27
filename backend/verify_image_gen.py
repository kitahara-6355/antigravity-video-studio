import requests
import time
import sys
import os
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError, ImageFilter
import uuid
import logging

logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"
TIMEOUT_SEC = 10

def _load_font(font_size: int):
    """システム内の利用可能なTrueTypeフォントを探索してロードする。なければデフォルトフォントを返す"""
    font_names = [
        # 日本語フォントを優先探索 (文字化け・豆腐化対策)
        "meiryo.ttc", "msgothic.ttc", "msmincho.ttc", 
        "Hiragino Sans GB.ttc", "NotoSansCJK-Regular.ttc",
        "TakaoGothic.ttf", "ipag.ttf",
        "arial.ttf", "calibri.ttf", "tahoma.ttf", 
        "LiberationSans-Regular.ttf", "DejaVuSans.ttf"
    ]
    
    font_dirs = []
    if sys.platform.startswith("win"):
        win_dir = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Fonts"
        font_dirs.append(win_dir)
    elif sys.platform.startswith("darwin"):
        font_dirs.extend([Path("/Library/Fonts"), Path("/System/Library/Fonts")])
    else:
        font_dirs.extend([Path("/usr/share/fonts"), Path("/usr/local/share/fonts")])

    for font_name in font_names:
        for font_dir in font_dirs:
            if font_dir.exists():
                font_path = font_dir / font_name
                if font_path.exists():
                    try:
                        return ImageFont.truetype(str(font_path), font_size)
                    except (OSError, AttributeError, ValueError, RuntimeError):
                        pass
        try:
            return ImageFont.truetype(font_name, font_size)
        except (OSError, AttributeError, ValueError, RuntimeError):
            pass
            
    return ImageFont.load_default()

def _wrap_text(text: str, font, max_width: int, draw) -> str:
    """テキストを画像の最大幅に合わせて自動的に改行（折り返し）する"""
    words = text.split(" ")
    lines = []
    current_line = []
    
    for word in words:
        subwords = word.split("\n")
        for i, subword in enumerate(subwords):
            if i > 0:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = []
            
            test_line = current_line + [subword] if current_line else [subword]
            test_str = " ".join(test_line)
            
            try:
                # Pillow 10+
                bbox = draw.textbbox((0, 0), test_str, font=font)
                w = bbox[2] - bbox[0]
            except AttributeError:
                # Older Pillow fallback
                w, _ = draw.textsize(test_str, font=font)
                
            if w <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [subword]
                
    if current_line:
        lines.append(" ".join(current_line))
        
    return "\n".join(lines)

def generate_image(
    output_path,
    width: int = 1280,
    height: int = 720,
    text: str = "Generated Image",
    is_preview: bool = False,
    strict_quality: bool = True
):
    """Pillowを使用して、高品質グラデーションとインナー枠線、中央揃えテキストを持つ高品質な画像を生成する (Atomic Writeサポート、プレビュー装飾対応)"""
    if output_path is None:
        raise ValueError("output_path must not be None")
        
    if not isinstance(output_path, (str, Path)):
        raise TypeError("output_path must be a string or Path object")
        
    if str(output_path).strip() == "":
        raise ValueError("output_path must not be empty")

    if text is None:
        text = ""
    else:
        text = str(text)
        
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")
        
    # 安全のための解像度上限チェック
    if width > 16384 or height > 16384:
        raise ValueError(f"Image dimensions exceed maximum safe limit (16384x16384). Got {width}x{height}")
        
    # 早期品質基準チェック
    if strict_quality:
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
            
        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        if abs(aspect_ratio - target_ratio) > 0.01:
            raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f} (dimensions: {width}x{height})")
        
    if not isinstance(is_preview, bool):
        is_preview = bool(is_preview)
        
    output_path = Path(output_path)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise IOError(f"Failed to create output directory: {output_path.parent}. Error: {e}")
    
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        # より高品質な4x4グラデーション（グラデーションステップを増やし、色数を増やしてプレミアム感を向上）
        grad = Image.new("RGB", (4, 4))
        # 1行目: ディープバイオレット -> ロイヤルブルー -> ネオンシアン -> ティール
        grad.putpixel((0, 0), (20, 10, 35))
        grad.putpixel((1, 0), (15, 30, 60))
        grad.putpixel((2, 0), (10, 50, 75))
        grad.putpixel((3, 0), (5, 65, 80))
        # 2行目: マゼンタ層 -> コバルトブルー -> ライトブルー -> エメラルド
        grad.putpixel((0, 1), (30, 20, 50))
        grad.putpixel((1, 1), (40, 50, 90))
        grad.putpixel((2, 1), (30, 80, 105))
        grad.putpixel((3, 1), (20, 95, 110))
        # 3行目: ディープピンク -> 明るいロイヤルブルー -> スカイブルー -> ネオンシアン
        grad.putpixel((0, 2), (45, 25, 60))
        grad.putpixel((1, 2), (50, 65, 110))
        grad.putpixel((2, 2), (60, 100, 140))
        grad.putpixel((3, 2), (40, 115, 150))
        # 4行目: ダークローズ -> ディープパープル -> ロイヤルブルー -> ダークスペース
        grad.putpixel((0, 3), (35, 15, 45))
        grad.putpixel((1, 3), (25, 40, 75))
        grad.putpixel((2, 3), (45, 80, 120))
        grad.putpixel((3, 3), (15, 20, 45))
        
        # BILINEAR から BICUBIC に変更してグラデーション変化をより滑らかに
        img = grad.resize((width, height), resample=Image.Resampling.BICUBIC)
        
        # プレミアムノイズ（グレイン効果）を付与してカラーバンディングを軽減し、質感を向上
        try:
            import numpy as np
            img_array = np.array(img, dtype=np.float32)
            # 平均0, 標準偏差1.2 of ノイズを付与してディザリング効果を狙う
            noise = np.random.normal(0, 1.2, img_array.shape)
            img_array = np.clip(img_array + noise, 0, 255).astype(np.uint8)
            img = Image.fromarray(img_array)
        except (ImportError, ModuleNotFoundError, AttributeError, ValueError, TypeError, RuntimeError):
            try:
                # 高品質な標準ライブラリ/Pillowフォールバック
                # effect_noise で生成したモノクロノイズをわずかに重ねる
                noise = Image.effect_noise((width, height), 10)
                noise_rgba = noise.convert("L").point(lambda x: int((x - 128) * 0.05 + 128))
                img = Image.blend(img, noise_rgba.convert("RGB"), 0.03)
            except (AttributeError, ValueError, OSError):
                pass  # numpyがない、またはエラー時は最終フォールバック
            
        # 描画コンテキスト
        d = ImageDraw.Draw(img)
        
        # デザイン要素: シネマティックなオーバーレイ（輝度向上と中央グロー効果）
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for r in range(0, max(width, height) // 2, 20):
            alpha = int(max(0, 40 - (r * 40) / (max(width, height) // 2)))
            if alpha > 0:
                od.ellipse(
                    [width // 2 - r, height // 2 - r, width // 2 + r, height // 2 + r],
                    fill=(255, 255, 255, alpha)
                )
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        d = ImageDraw.Draw(img)
        
        # デザイン要素: インナーボーダー（プレミアムな角丸二重枠線）の追加
        border_margin = min(20, width // 10, height // 10)
        if border_margin > 0:
            radius = min(15, border_margin)
            # 外側のメイン白枠
            d.rounded_rectangle(
                [border_margin, border_margin, width - border_margin, height - border_margin],
                radius=radius,
                outline=(255, 255, 255),
                width=2
            )
            # 内側のサブブルー枠（デザインアクセント）
            d.rounded_rectangle(
                [border_margin + 4, border_margin + 4, width - border_margin - 4, height - border_margin - 4],
                radius=max(0, radius - 4),
                outline=(150, 180, 200),
                width=1
            )
            
        # プレビュー表示ロジックの改善 (is_preview=True の場合)
        if is_preview:
            # プレビュー用オーバーレイレイヤーを作成 (RGBA)
            preview_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            pwd = ImageDraw.Draw(preview_overlay)
            
            # (1) 「PREVIEW」ウォーターマークテキストを格子状に散布
            p_font_size = max(24, height // 10)
            p_font = _load_font(p_font_size)
            watermark_text = "PREVIEW"
            
            # 格子状に非常に薄く配置
            for i in range(1, 4):
                for j in range(1, 4):
                    wx = (width * i) // 4
                    wy = (height * j) // 4
                    pwd.text(
                        (wx, wy),
                        watermark_text,
                        fill=(255, 255, 255, 20),  # 非常に薄い白色
                        font=p_font,
                        anchor="mm"
                    )
            
            # (2) カメラのファインダーレティクル（プレビュー枠）装飾
            pad = min(30, width // 20, height // 20)
            line_len = pad
            if pad > 0:
                # 左上
                pwd.line([(pad, pad), (pad + line_len, pad)], fill=(255, 255, 255, 80), width=2)
                pwd.line([(pad, pad), (pad, pad + line_len)], fill=(255, 255, 255, 80), width=2)
                # 右上
                pwd.line([(width - pad, pad), (width - pad - line_len, pad)], fill=(255, 255, 255, 80), width=2)
                pwd.line([(width - pad, pad), (width - pad, pad + line_len)], fill=(255, 255, 255, 80), width=2)
                # 左下
                pwd.line([(pad, height - pad), (pad + line_len, height - pad)], fill=(255, 255, 255, 80), width=2)
                pwd.line([(pad, height - pad), (pad, height - pad - line_len)], fill=(255, 255, 255, 80), width=2)
                # 右下
                pwd.line([(width - pad, height - pad), (width - pad - line_len, height - pad)], fill=(255, 255, 255, 80), width=2)
                pwd.line([(width - pad, height - pad), (width - pad, height - pad - line_len)], fill=(255, 255, 255, 80), width=2)
                
                # (3) メタデータテキスト（右上に表示）
                meta_font = _load_font(max(10, height // 50))
                meta_text = f"PREVIEW MODE | {width}x{height} (16:9)"
                pwd.text(
                    (width - pad - 10, pad + 10),
                    meta_text,
                    fill=(255, 255, 255, 120),
                    font=meta_font,
                    anchor="rt"
                )
                
            # 合成
            img = Image.alpha_composite(img.convert("RGBA"), preview_overlay).convert("RGB")
            d = ImageDraw.Draw(img)
            
        # フォントのロードと動的スケーリング（はみ出し防止）
        font_size = max(16, height // 15)
        max_text_width = width - (border_margin * 4)
        if max_text_width < 50:
            raise ValueError(f"Image width {width} is too small for margins")
            
        max_text_height = height - (border_margin * 4)
        
        font = _load_font(font_size)
        wrapped_text = _wrap_text(text, font, max_text_width, d)
        
        # 枠内にテキストが完全に収まるよう、フォントサイズを動的に縮小する
        while font_size > 12:
            try:
                bbox = d.textbbox((0, 0), wrapped_text, font=font)
                text_h = bbox[3] - bbox[1]
            except AttributeError:
                _, text_h = d.textsize(wrapped_text, font=font)
                
            if text_h <= max_text_height:
                break
            font_size = int(font_size * 0.9)
            font = _load_font(font_size)
            wrapped_text = _wrap_text(text, font, max_text_width, d)
        
        # テキスト位置と背景パネル (Glassmorphism)
        text_pos = (width // 2, height // 2)
        
        if text:
            # テキスト背景の半透明ガラス風パネルを描画 (RGBAブレンド + GaussianBlurによるすりガラス効果)
            try:
                bbox = d.textbbox((0, 0), wrapped_text, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
            except AttributeError:
                text_w, text_h = d.textsize(wrapped_text, font=font)
            
            # テキスト周囲のマージン
            padding_x = max(20, text_w // 10)
            padding_y = max(15, text_h // 10)
            panel_w = text_w + padding_x * 2
            panel_h = text_h + padding_y * 2
            
            # パネルが画像からはみ出さないようにガード
            panel_w = min(panel_w, width - border_margin * 2 - 10)
            panel_h = min(panel_h, height - border_margin * 2 - 10)
            
            panel_x0 = (width - panel_w) // 2
            panel_y0 = (height - panel_h) // 2
            panel_x1 = panel_x0 + panel_w
            panel_y1 = panel_y0 + panel_h
            
            # 1. 元画像からパネル領域を切り出す (すりガラスの背景用)
            crop_area = (panel_x0, panel_y0, panel_x1, panel_y1)
            cropped_bg = img.crop(crop_area)
            
            # 2. 切り出した背景にガウシアンブラーを適用 (radius=12)
            # すりガラスらしい程よいボケ味を表現
            blurred_bg = cropped_bg.filter(ImageFilter.GaussianBlur(radius=12))
            
            # 3. 半透明のダークブルー・ダークスペースカラーとブレンド
            tint = Image.new("RGBA", cropped_bg.size, (10, 10, 25, 120))
            glass_patch = Image.alpha_composite(blurred_bg.convert("RGBA"), tint)
            
            # 4. 角丸マスクを作成して、元の画像に合成 (アンチエイリアシングのためのスーパーサンプリング)
            # 4倍サイズでマスクを描画し、BILINEARでリサイズすることでエッジを滑らかにする
            mask_scale = 4
            mask_large = Image.new("L", (panel_w * mask_scale, panel_h * mask_scale), 0)
            mask_draw = ImageDraw.Draw(mask_large)
            mask_draw.rounded_rectangle(
                [0, 0, panel_w * mask_scale, panel_h * mask_scale],
                radius=10 * mask_scale,
                fill=255
            )
            mask = mask_large.resize((panel_w, panel_h), resample=Image.Resampling.BILINEAR)
            
            img.paste(glass_patch.convert("RGB"), (panel_x0, panel_y0), mask=mask)
            
            # 5. 二重の境界線装飾 (Glassmorphism を際立たせる白と水色の極細枠線)
            # アルファチャンネル上で綺麗にブレンドして重ねる
            panel_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            pd = ImageDraw.Draw(panel_overlay)
            
            # 外側の極薄白枠
            pd.rounded_rectangle(
                [panel_x0, panel_y0, panel_x1, panel_y1],
                radius=10,
                outline=(255, 255, 255, 60),
                width=1
            )
            # 内側の極薄水色枠
            pd.rounded_rectangle(
                [panel_x0 + 1, panel_y0 + 1, panel_x1 - 1, panel_y1 - 1],
                radius=9,
                outline=(150, 180, 220, 30),
                width=1
            )
            
            img = Image.alpha_composite(img.convert("RGBA"), panel_overlay).convert("RGB")
            d = ImageDraw.Draw(img)
        
        # テキストのドロップシャドウ
        shadow_offset = max(2, height // 240)
        shadow_pos = (text_pos[0] + shadow_offset, text_pos[1] + shadow_offset)
        
        try:
            d.text(
                shadow_pos,
                wrapped_text,
                fill=(0, 0, 0),
                font=font,
                anchor="mm",
                align="center",
                spacing=font_size // 4
            )
        except TypeError:
            pass
        
        # メインテキストの描画
        try:
            d.text(
                text_pos,
                wrapped_text,
                fill=(255, 255, 255),
                font=font,
                anchor="mm",
                stroke_width=2,
                stroke_fill=(0, 0, 0),
                align="center",
                spacing=font_size // 4
            )
        except TypeError:
            d.text(
                text_pos,
                wrapped_text,
                fill=(255, 255, 255),
                font=font,
                anchor="mm",
                align="center",
                spacing=font_size // 4
            )
        
        ext = output_path.suffix.lower()
        if ext in (".jpg", ".jpeg"):
            img.save(temp_path, "JPEG", quality=90)
        elif ext == ".webp":
            img.save(temp_path, "WEBP", quality=90)
        else:
            img.save(temp_path, "PNG", compress_level=9)
        
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)
        # 正常にリネームできたため、finallyでの一時ファイル削除を避けるためNoneに設定
        temp_path = None
    except OSError as oe:
        logger.error(f"Failed to generate image atomically (OS error): {oe}")
        raise IOError(f"Failed to save image due to OS error: {oe}") from oe
    except RuntimeError as re:
        logger.error(f"Runtime error during image generation: {re}")
        raise
    except (ValueError, TypeError) as te:
        logger.error(f"Value/Type error during image generation: {te}")
        raise
    finally:
        if 'temp_path' in locals() and temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except (OSError, RuntimeError):
                pass
        
    return output_path

def validate_generated_image(file_path) -> dict:
    """
    生成された画像の品質要件を検証する。
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    """
    if file_path is None:
        raise ValueError("file_path must not be None")
        
    if not isinstance(file_path, (str, Path)):
        raise TypeError("file_path must be a string or Path object")
        
    if str(file_path).strip() == "":
        raise ValueError("file_path must not be empty")
        
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Image file not found: {file_path}")
        
    try:
        size_bytes = file_path.stat().st_size
    except OSError as e:
        raise ValueError(f"Failed to retrieve file statistics: {e}") from e

    if size_bytes <= 10:
        raise ValueError(f"File is empty or too small to be a valid image: {size_bytes} bytes")
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    try:
        with Image.open(file_path) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ValueError(f"Image verification failed (corrupted or too large): {e}") from e
        
    try:
        with Image.open(file_path) as img:
            img.load()
            width, height = img.size
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise ValueError(f"Image load failed (corrupted): {e}") from e
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid image dimensions: {width}x{height}")
        
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f} (dimensions: {width}x{height})")
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }

async def resolve_image_generation_task(task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理
    """
    output_dir = Path("backend/temp_thumbnails")
    output_path = output_dir / f"{task_id}.png"
    
    width = 1280
    height = 720
    text = "StageBoundAgent Image"
    
    is_preview = task_id.startswith("preview_") if task_id else False
    
    generate_image(output_path, width=width, height=height, text=text, is_preview=is_preview)
    result_info = validate_generated_image(output_path)
    return json.dumps(result_info)

def run_image_generation_e2e():
    print("--- Starting Image Generation E2E Test ---")
    
    # 1. Trigger Generation
    prompt = "A futuristic city skyline, cyberpunk style, high quality"
    print(f"Sending prompt: '{prompt}'")
    
    try:
        res = requests.post(f"{BASE_URL}/api/director/generate-image-async", json={"prompt": prompt}, timeout=TIMEOUT_SEC)
        if res.status_code != 200:
            print(f"Error triggering generation: {res.text}")
            sys.exit(1)
            
        try:
            data = res.json()
        except (ValueError, json.JSONDecodeError) as je:
            print(f"Failed to decode JSON from generation trigger response: {je}")
            sys.exit(1)
            
        task_id = data.get("task_id")
        if not task_id:
            print("Error: task_id is missing in response.")
            sys.exit(1)
        print(f"Task Started. ID: {task_id}")
        
    except requests.exceptions.Timeout as te:
        print(f"Timeout triggering generation: {te}")
        sys.exit(1)
    except requests.exceptions.RequestException as re:
        print(f"RequestException triggering generation: {re}")
        sys.exit(1)
        
    # 2. Poll Status
    start_time = time.time()
    while True:
        if time.time() - start_time > 60: # 60s timeout
            print("Timeout waiting for image generation.")
            sys.exit(1)
            
        try:
            res = requests.get(f"{BASE_URL}/api/director/tasks/{task_id}", timeout=TIMEOUT_SEC)
            if res.status_code != 200:
                print(f"Error polling task: {res.text}")
                time.sleep(3)
                continue
                
            try:
                task = res.json()
            except (ValueError, json.JSONDecodeError) as je:
                print(f"Failed to decode JSON from poll response: {je}")
                time.sleep(3)
                continue
                
            status = task.get("status")
            print(f"Status: {status}")
            
            if status == "completed":
                print("--- Generation SUCCESS ---")
                images = task.get("result", [])
                print(f"Generated {len(images)} images.")
                break
                
            elif status == "failed":
                print(f"--- Generation FAILED ---")
                print(f"Error: {task.get('error')}")
                sys.exit(1)
                
            elif status is None:
                print("Warning: Task status is missing in response.")
                
        except requests.exceptions.Timeout as te:
            print(f"Polling Timeout Exception: {te}")
        except requests.exceptions.RequestException as re:
            print(f"Polling RequestException: {re}")
            
        time.sleep(3)

if __name__ == "__main__":
    run_image_generation_e2e()
