"""
Complete Preview Generator with All Elements
ロゴ+字幕+カラーグレーディングの統合プレビュー
"""

import subprocess
from pathlib import Path
import logging
import sys
import uuid
import asyncio
import json
import time
import threading
from PIL import Image, ImageFont, ImageDraw, UnidentifiedImageError, ImageEnhance, ImageFilter, ImageOps
from PIL.Image import DecompressionBombError
import shutil
import os

from path_resolver import raw_videos_dir

# ピクセル数の安全な最大制限値を設定 (デフォルトの89,478,485ピクセルから拡張して DecompressionBombError を極力防止)
try:
    Image.MAX_IMAGE_PIXELS = 256 * 1024 * 1024  # 256MPまで許容
except AttributeError as attr_err:
    # Image.MAX_IMAGE_PIXELS が存在しない場合のためのフォールバック
    pass

# スレッドセーフな画像ロードのためのロック
image_truncated_lock = threading.Lock()

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)


class PreviewGenerationError(ValueError):
    """プレビュー生成処理全般のベース例外クラス"""
    pass


class PreviewImageCorruptedError(PreviewGenerationError):
    """画像ファイル破損またはデコード失敗時の例外クラス"""
    pass


class PreviewImageSizeExceededError(PreviewGenerationError):
    """ファイルサイズ制限超過時の例外クラス"""
    pass


class PreviewResolutionError(PreviewGenerationError):
    """解像度またはアスペクト比の基準未達時の例外クラス"""
    pass


class PreviewImageInvalidAspectRatioError(PreviewResolutionError):
    """アスペクト比の基準未達時の例外クラス"""
    pass


def _parse_srt_subtitle_for_timestamp(srt_path: Path, timestamp: float) -> str:
    """
    指定されたタイムスタンプ（秒）に該当する字幕テキストを SRT ファイルから検索する。
    """
    if not srt_path.exists():
        return ""
    try:
        content = srt_path.read_text(encoding="utf-8")
        blocks = content.strip().split("\n\n")
        for block in blocks:
            try:
                lines = block.strip().split("\n")
                if len(lines) < 3:
                    continue
                time_line = lines[1]
                if "-->" not in time_line:
                    continue
                start_str, end_str = time_line.split("-->")
                
                def parse_time(t_str):
                    t_str = t_str.strip()
                    parts = t_str.split(":")
                    h = int(parts[0])
                    m = int(parts[1])
                    s_ms = parts[2].replace(",", ".")
                    s = float(s_ms)
                    return h * 3600 + m * 60 + s
                
                start_time = parse_time(start_str)
                end_time = parse_time(end_str)
                if start_time <= timestamp <= end_time:
                    return "\n".join(lines[2:])
            except (ValueError, IndexError) as e:
                logger.warning(f"Failed to parse SRT block for timestamp {timestamp}: {e}")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(f"Failed to read SRT file: {e}", exc_info=True)
    return ""


def _draw_subtitle_on_image(image_path: str, subtitle_text: str, _test_callback=None) -> None:
    """
    Pillow を用いて画像下部に美しい字幕（半透明背景座布団と輪郭線付き）を描画する。
    自動折り返しとフォントサイズ自動縮小ロジックを搭載し、画面外へのはみ出しを防ぐ。
    """
    if not subtitle_text:
        return
    
    temp_path = None
    try:
        with Image.open(image_path) as img:
            img.load()
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            w, h = img.size
            max_text_width = w - 80  # 左右マージン40pxずつ
            max_total_height = int(h * 0.25)  # 字幕描画エリアの最大高さ
            
            # フォントサイズ決定ループ
            font_size = int(h * 0.05)
            font = None
            font_paths = [
                "C:\\Windows\\Fonts\\yugothib.ttf",  # 游ゴシック Bold (優先)
                "C:\\Windows\\Fonts\\meiryob.ttc",   # メイリオ Bold (優先)
                "C:\\Windows\\Fonts\\yugothic.ttc",
                "C:\\Windows\\Fonts\\meiryo.ttc",
                "C:\\Windows\\Fonts\\msgothic.ttc",
                "C:\\Windows\\Fonts\\msmincho.ttc",
                "C:\\Windows\\Fonts\\BIZ-UDGothicB.ttc", # BIZ UDゴシック Bold (優先)
                "C:\\Windows\\Fonts\\BIZ-UDGothic.ttc",
                "C:\\Windows\\Fonts\\arial.ttf",
                # macOSフォント
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
                "/System/Library/Fonts/STHeiti Light.ttc",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                # Linuxフォント
                "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
                "/usr/share/fonts/fonts-japanese-gothic.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            ]
            
            temp_draw = ImageDraw.Draw(img)
            
            def load_font(size):
                # 1. 既定の優先フォントパスを走査
                for fp in font_paths:
                    if Path(fp).exists():
                        try:
                            return ImageFont.truetype(fp, size)
                        except OSError as font_err:
                            logger.debug(f"Failed to load font from {fp}: {font_err}")
                
                # 2. 動的にシステムフォントディレクトリから日本語・アジア系フォントを探索するフォールバック
                search_dirs = []
                if sys.platform == "win32":
                    search_dirs.append(Path("C:\\Windows\\Fonts"))
                elif sys.platform == "darwin":
                    search_dirs.extend([Path("/System/Library/Fonts"), Path("/Library/Fonts")])
                else:
                    search_dirs.extend([Path("/usr/share/fonts"), Path("/usr/local/share/fonts")])
                
                for s_dir in search_dirs:
                    if s_dir.exists():
                        for ext in ["*.ttc", "*.ttf"]:
                            try:
                                for fp in s_dir.rglob(ext):
                                    fp_str = str(fp)
                                    fp_lower = fp.name.lower()
                                    # 日本語やCJK系のフォントとして知られるキーワードを優先的にマッチング
                                    if any(k in fp_lower for k in ["goth", "min", "meiryo", "yugoth", "msjh", "msyh", "cjk", "sazanami", "kochi", "takao"]):
                                        try:
                                            return ImageFont.truetype(fp_str, size)
                                        except OSError:
                                            continue
                            except OSError as glob_err:
                                logger.debug(f"Error globbing font directory {s_dir}: {glob_err}")

                # 3. 最終手段としてデフォルトフォント
                return ImageFont.load_default()
            
            font = load_font(font_size)
            
            # 自動折り返しとフォントサイズ自動縮小のループ (最小フォントサイズは 12)
            # 一流YouTuber・放送局基準の禁則処理を考慮した美しいレイアウト設計
            kinsoku_chars = {"、", "。", "！", "？", "」", "』", "）", "]", "}", "・", "ー"}
            loop_count = 0
            while font_size >= 12 and loop_count < 50:
                loop_count += 1
                text_lines = []
                for orig_line in subtitle_text.split("\n"):
                    current_line = ""
                    for char in orig_line:
                        test_line = current_line + char
                        try:
                            if hasattr(temp_draw, "textbbox"):
                                bbox = temp_draw.textbbox((0, 0), test_line, font=font)
                                line_w = bbox[2] - bbox[0]
                            else:
                                line_w, _ = temp_draw.textsize(test_line, font=font)
                        except (OSError, AttributeError, TypeError, ValueError) as text_err:
                            logger.debug(f"Failed to measure text width, falling back to approximation: {text_err}")
                            line_w = len(test_line) * font_size * 0.6
                        
                        if line_w > max_text_width and current_line:
                            # 簡易行頭禁則処理: 次の文字が禁則文字の場合は、現在行の末尾に引っ張り、改行位置を調整
                            if char in kinsoku_chars:
                                current_line = current_line + char
                                text_lines.append(current_line)
                                current_line = ""
                            else:
                                text_lines.append(current_line)
                                current_line = char
                        else:
                            current_line = test_line
                    if current_line:
                        text_lines.append(current_line)
                
                line_datas = []
                line_spacing = max(6, int(font_size * 0.2))
                total_height = 0
                
                for line in text_lines:
                    try:
                        if hasattr(temp_draw, "textbbox"):
                            bbox = temp_draw.textbbox((0, 0), line, font=font)
                            text_w = bbox[2] - bbox[0]
                            text_h = bbox[3] - bbox[1]
                        else:
                            text_w, text_h = temp_draw.textsize(line, font=font)
                    except (OSError, AttributeError, TypeError, ValueError) as text_err:
                        logger.debug(f"Failed to measure line height, falling back to approximation: {text_err}")
                        text_w, text_h = len(line) * font_size * 0.6, font_size
                    
                    line_datas.append((line, text_w, text_h))
                    total_height += text_h + line_spacing
                
                if line_datas:
                    total_height -= line_spacing
                
                if total_height > max_total_height and font_size > 12:
                    font_size = max(12, int(font_size * 0.85))
                    font = load_font(font_size)
                else:
                    break
            
            current_y = h - int(h * 0.05) - total_height
            
            final_line_datas = []
            line_widths = []
            for line, text_w, text_h in line_datas:
                x = (w - text_w) // 2
                y = current_y
                final_line_datas.append((line, x, y, text_w, text_h))
                line_widths.append(text_w)
                current_y += text_h + line_spacing
            
            if _test_callback:
                _test_callback({
                    "final_font_size": font_size,
                    "line_widths": line_widths,
                    "line_count": len(text_lines)
                })
            
            # 1. 半透明の背景座布団を描画
            if final_line_datas:
                # 描画位置の下部領域の背景の平均輝度を計算して透明度を動的に決定
                # John Carmack 流のシンプルさと計算効率のため、ImageStat を使用して C レイヤーで高速算出
                try:
                    from PIL import ImageStat
                    ymin = min(y for _, _, y, _, _ in final_line_datas)
                    crop_area = (0, max(0, ymin - 10), w, h)
                    with img.crop(crop_area) as crop_img:
                        stat_crop = crop_img.convert("L")
                        avg_bg_brightness = ImageStat.Stat(stat_crop).mean[0]
                except (ValueError, TypeError, OSError, AttributeError, IndexError) as stat_err:
                    logger.debug(f"Failed to calculate background brightness, using default (128): {stat_err}")
                    avg_bg_brightness = 128  # デフォルト値
 
                # 明るい背景には不透明度を高く (160), 暗い背景には不透明度を低く (110)
                opacity_val = 160 if avg_bg_brightness > 150 else (110 if avg_bg_brightness < 70 else 135)
 
                overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                overlay_draw = ImageDraw.Draw(overlay)
                
                box_padding_x = 15
                box_padding_y = 6
                
                for _, x, y, text_w, text_h in final_line_datas:
                    box_x0 = max(0, x - box_padding_x)
                    box_y0 = max(0, y - box_padding_y)
                    box_x1 = min(w, x + text_w + box_padding_x)
                    box_y1 = min(h, y + text_h + box_padding_y)
                    
                    try:
                        # プレミアム仕様の角丸座布団（微細な白の輪郭線を追加して視認性アップ）
                        overlay_draw.rounded_rectangle(
                            [box_x0, box_y0, box_x1, box_y1],
                            radius=8,
                            fill=(0, 0, 0, opacity_val),
                            outline=(255, 255, 255, 45),
                            width=1
                        )
                    except AttributeError:
                        overlay_draw.rectangle(
                            [box_x0, box_y0, box_x1, box_y1],
                            fill=(0, 0, 0, opacity_val)
                        )
                
                img.paste(overlay, (0, 0), mask=overlay)
            
            # 2. テキスト本体と高品質な輪郭線およびドロップシャドウを描画
            draw = ImageDraw.Draw(img)
            border_color = (0, 0, 0)
            text_color = (255, 255, 255)
            # フォントサイズが小さい場合は輪郭線で潰れるのを防ぐため、フォントサイズに連動した調整を行う
            border_width = max(1, min(int(font_size * 0.12), int(h * 0.004)))
            shadow_offset = max(1, int(font_size * 0.06))
            
            # プレミアム多重ドロップシャドウ（ソフトぼかし影の効果を再現するためにオフセットと不透明度を段階的に描画）
            shadow_offsets = [
                (shadow_offset, shadow_offset, 140),
                (shadow_offset + 1, shadow_offset + 1, 100),
                (shadow_offset + 2, shadow_offset + 2, 60),
                (shadow_offset - 1, shadow_offset + 1, 50),
                (shadow_offset + 1, shadow_offset - 1, 50)
            ]
            
            for line, x, y, text_w, text_h in final_line_datas:
                for sx, sy, opacity in shadow_offsets:
                    try:
                        draw.text(
                            (x + sx, y + sy), 
                            line, 
                            fill=(0, 0, 0, opacity), 
                            font=font, 
                            stroke_width=border_width, 
                            stroke_fill=(0, 0, 0, opacity)
                        )
                    except TypeError:
                        draw.text((x + sx, y + sy), line, fill=(0, 0, 0), font=font)
            
            # その上に本体と輪郭線を描画
            for line, x, y, text_w, text_h in final_line_datas:
                try:
                    draw.text((x, y), line, fill=text_color, font=font, stroke_width=border_width, stroke_fill=border_color)
                except TypeError:
                    for dx in range(-border_width, border_width + 1):
                        for dy in range(-border_width, border_width + 1):
                            if dx != 0 or dy != 0:
                                # 円形になるように距離を制限 (dx*dx + dy*dy <= border_width*border_width)
                                if dx * dx + dy * dy <= border_width * border_width:
                                    draw.text((x + dx, y + dy), line, fill=border_color, font=font)
                    draw.text((x, y), line, fill=text_color, font=font)
            
            temp_path = Path(image_path).with_suffix(f".{uuid.uuid4().hex}.tmp")
            
            # 保存処理の堅牢化 (I/Oエラーリトライ)
            save_success = False
            for save_attempt in range(1, 4):
                try:
                    img.save(temp_path, format="PNG" if Path(image_path).suffix.lower() == ".png" else "JPEG")
                    save_success = True
                    break
                except (IOError, OSError) as save_err:
                    if save_attempt == 3:
                        raise save_err
                    time.sleep(0.1 * save_attempt)
            
            # 原子的な置き換えとWindows向け堅牢化
            max_attempts = 5
            for attempt in range(1, max_attempts + 1):
                try:
                    if Path(image_path).exists():
                        try:
                            Path(image_path).unlink()
                        except OSError:
                            pass
                    os.replace(str(temp_path), image_path)
                    break
                except OSError as e:
                    if attempt == max_attempts:
                        try:
                            shutil.copy(str(temp_path), image_path)
                            temp_path.unlink()
                        except OSError as fallback_err:
                            raise RuntimeError(f"Failed to finalize image: {fallback_err}") from fallback_err
                    time.sleep(0.15 * attempt)
    except (ValueError, TypeError, OSError, AttributeError, IndexError, KeyError, RuntimeError) as e:
        logger.error(f"Failed to draw subtitle on {image_path}: {e}", exc_info=True)
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise PreviewGenerationError(f"Failed to draw subtitle on image: {e}") from e



def validate_preview_image(image_path: str) -> dict:
    """
    プレビュー画像（スクリーンショット）の品質要件を検証する。
    Windows環境等での一時的なファイルロック競合に耐えるようにリトライ機構を搭載。
    """
    path = Path(image_path)
    
    # ロックによる一時的な読み込み失敗を避けるためのリトライ機構
    size_bytes = 0
    for attempt in range(1, 6):
        try:
            if not path.exists():
                if attempt < 5:
                    time.sleep(0.05 * attempt)
                    continue
                raise FileNotFoundError(f"Preview image file not found: {image_path}")
            size_bytes = path.stat().st_size
            break
        except (OSError, PermissionError) as e:
            if attempt == 5:
                raise
            time.sleep(0.05 * attempt)
    if size_bytes == 0:
        raise PreviewImageCorruptedError("Image is corrupted or invalid format: Image file is empty (0 bytes)")
        
    if size_bytes >= 4 * 1024 * 1024:
        raise PreviewImageSizeExceededError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    # 1. 簡易的な verify による破損チェック
    try:
        with Image.open(path) as img:
            img.verify()
    except DecompressionBombError as e:
        raise PreviewImageCorruptedError(f"Image size exceeds safety limits or is corrupted: {e}")
    except (UnidentifiedImageError, IOError, OSError, ValueError, SyntaxError, IndexError) as e:
        raise PreviewImageCorruptedError(f"Image is corrupted or invalid format (verify failed): {e}")
        
    # 2. 完全なピクセルデータロードによる破損チェック & 解像度取得
    # truncatedな破損画像を厳密に検知するため、LOAD_TRUNCATED_IMAGES を一時的に False にする（ロックで保護）
    with image_truncated_lock:
        from PIL import ImageFile
        orig_load_truncated = ImageFile.LOAD_TRUNCATED_IMAGES
        ImageFile.LOAD_TRUNCATED_IMAGES = False
        
        try:
            with Image.open(path) as img:
                img.load()
                # 内部デコーダ検証のための転置処理
                img.transpose(Image.FLIP_LEFT_RIGHT)
                
                # ICCカラープロファイルの破損チェック
                icc = img.info.get("icc_profile")
                if icc:
                    from PIL import ImageCms
                    import io
                    try:
                        ImageCms.getProfileName(io.BytesIO(icc))
                    except (ValueError, TypeError, OSError, ImageCms.PyCMSError) as e:
                        raise PreviewImageCorruptedError(f"Corrupted ICC profile: {e}")
                
                width, height = img.size
                
                # 単一色（ソリッドカラー）のチェック
                extrema = img.getextrema()
                if extrema:
                    if isinstance(extrema[0], tuple):
                        is_solid = all(min_val == max_val for min_val, max_val in extrema)
                    else:
                        is_solid = extrema[0] == extrema[1]
                    if is_solid:
                        raise PreviewImageCorruptedError("Image is a single solid color")
        except DecompressionBombError as e:
            raise PreviewImageCorruptedError(f"Image size exceeds safety limits or is corrupted: {e}")
        except MemoryError as e:
            logger.critical(f"Memory limit exceeded during image validation: {e}")
            import gc
            gc.collect()
            raise PreviewImageCorruptedError(f"Out of memory during image validation: {e}")
        except (UnidentifiedImageError, IOError, OSError, ValueError, SyntaxError, IndexError, TypeError, AttributeError) as e:
            if isinstance(e, PreviewImageCorruptedError):
                raise e
            raise PreviewImageCorruptedError(f"Image is corrupted or invalid format (load failed): {e}")
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = orig_load_truncated
        
    if width < 1280 or height < 720:
        raise PreviewResolutionError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise PreviewImageInvalidAspectRatioError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    return {
        "path": str(path),
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "size_bytes": size_bytes
    }


def ensure_preview_image_quality(image_path: str, padding_mode: str = "black", force_enhance: bool = False) -> str:
    """
    Pillowを用いて画像を 1280x720 (アスペクト比16:9) に自動的に補正する。
    アスペクト比が異なる場合は、アスペクト比を維持しつつリサイズし、黒帯を追加（パディング）するか、背景をブラー処理（ぼかしパディング）する。
    また、ファイルサイズが 4MB 未満になるように自動で段階的圧縮を行う。
    """
    path = Path(image_path)
    
    # 1. 無効な文字のチェック (Windows での無効な文字)
    invalid_chars = '<>:"|?*'
    if any(c in path.name for c in invalid_chars):
        raise OSError("Invalid characters in path")
        
    # 2. ディスク空き容量 of チェック (10MB 未満はエラー)
    try:
        parent_dir = path.parent if path.parent.exists() else Path(".")
        total, used, free = shutil.disk_usage(str(parent_dir))
        if free < 10 * 1024 * 1024:
            # ディスクGC: 古い一時ファイルをクリーンアップして空きを作る
            logger.info("Insufficient disk space detected. Running disk GC for temp files...")
            cleaned_any = False
            for tmp_file in parent_dir.glob("*.tmp"):
                try:
                    tmp_file.unlink()
                    cleaned_any = True
                except OSError as unlink_err:
                    logger.warning(f"Failed to clean up old temp file {tmp_file}: {unlink_err}")
            
            if cleaned_any:
                total, used, free = shutil.disk_usage(str(parent_dir))
            
            if free < 10 * 1024 * 1024:
                raise OSError("Insufficient disk space")
    except OSError as e:
        if "Insufficient disk space" in str(e):
            raise
        logger.warning(f"Failed to check disk space: {e}")

    # 3. サポートする拡張子のチェック
    ext = path.suffix.lower()
    if ext not in ('.png', '.jpg', '.jpeg'):
        raise PreviewGenerationError(f"Unsupported file format: {ext}")

    if not path.exists():
        raise FileNotFoundError(f"Image file to ensure quality not found: {image_path}")
        
    try:
        with Image.open(path) as img:
            img.load()
            orig_w, orig_h = img.size
            # 画像モードを RGB に変換（RGBA やパレット、グレースケール等からの変換に対応）
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            # ICCカラープロファイルを維持
            icc_profile = img.info.get("icc_profile")
            
            target_w, target_h = 1280, 720
            target_ratio = target_w / target_h
            orig_ratio = orig_w / orig_h
            
            # すでに1280x720で、ファイルサイズも4MB未満で、かつ強制画質補正が不要な場合はそのまま戻す
            if orig_w == target_w and orig_h == target_h and not force_enhance:
                try:
                    if path.stat().st_size < 4 * 1024 * 1024:
                        return str(path)
                except OSError as stat_err:
                    logger.warning(f"Failed to check file size of {path}: {stat_err}")
                
            # アスペクト比を維持したリサイズスケールを計算
            scale_w = target_w / orig_w
            scale_h = target_h / orig_h
            scale = min(scale_w, scale_h)
            
            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)
            
            # 品質向上: アップスケールまたは大幅なダウンスケール時の補間フィルター選択
            try:
                resample_filter = Image.Resampling.LANCZOS
            except AttributeError:
                resample_filter = getattr(Image, "LANCZOS", Image.BICUBIC)
            resized_img = img.resize((new_w, new_h), resample_filter)

            try:
                resample_bilinear = Image.Resampling.BILINEAR
            except AttributeError:
                resample_bilinear = getattr(Image, "BILINEAR", Image.BILINEAR)
            
            # 背景キャンバスの作成
            if padding_mode == "blur":
                # ブラーパディング用の背景を作成
                bg_scale = max(target_w / orig_w, target_h / orig_h)
                bg_w = int(orig_w * bg_scale)
                bg_h = int(orig_h * bg_scale)
                bg_resized = img.resize((bg_w, bg_h), resample_bilinear)
                
                # キャンバスの中央に配置して切り抜く
                bg_canvas = Image.new("RGB", (target_w, target_h))
                bg_x = (target_w - bg_w) // 2
                bg_y = (target_h - bg_h) // 2
                bg_canvas.paste(bg_resized, (bg_x, bg_y))
                
                # ガウシアンブラーをかけてぼかし背景を作る
                canvas = bg_canvas.filter(ImageFilter.GaussianBlur(radius=30))
                # 品質向上: ぼかし背景の輝度をさらに下げて、中央のコンテンツを視覚的に大きく引き立てる
                try:
                    bg_enhancer = ImageEnhance.Brightness(canvas)
                    canvas = bg_enhancer.enhance(0.55)
                except (AttributeError, ValueError, OSError) as bg_enh_err:
                    logger.warning(f"Failed to lower brightness of blur background: {bg_enh_err}")
            elif padding_mode == "black":
                # 黒背景キャンバスの作成
                canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
            else:
                raise PreviewGenerationError(f"Unsupported padding_mode: {padding_mode}")
            
            # 品質向上: リサイズ後のコンテンツ画像に対して、ぼやけを防ぐためにシャープネスやコントラストなどの各種自動補正を適用する
            try:
                # アップスケール比率に応じた動的なシャープネス調整とアンシャープマスクの適用
                if scale > 3.0:
                    sharpness_factor = 1.95
                elif scale > 2.0:
                    sharpness_factor = 1.65
                elif scale > 1.5:
                    sharpness_factor = 1.45
                elif scale > 1.1:
                    sharpness_factor = 1.25
                else:
                    sharpness_factor = 1.12
                enhancer = ImageEnhance.Sharpness(resized_img)
                resized_img = enhancer.enhance(sharpness_factor)
                
                # アンシャープマスクを適用してエッジを補正（ディテール復元、倍率に応じて調整）
                if scale > 3.0:
                    unsharp_percent = 185
                elif scale > 1.5:
                    unsharp_percent = 145
                else:
                    unsharp_percent = 125
                resized_img = resized_img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=unsharp_percent, threshold=1))
                
                # 適応的な彩度（色彩）の自動補正
                stat_img = resized_img.convert("L")
                try:
                    r, g, b = resized_img.split()[:3]
                    from PIL import ImageChops, ImageStat
                    diff_img = ImageChops.difference(r, g)
                    mean_color_variance = ImageStat.Stat(diff_img).mean[0]
                    color_factor = 1.25 if mean_color_variance < 15.0 else 1.15
                except (ValueError, TypeError, AttributeError, OSError, ZeroDivisionError) as e:
                    logger.debug(f"Failed to calculate color variance, using default: {e}")
                    color_factor = 1.15
                color_enhancer = ImageEnhance.Color(resized_img)
                resized_img = color_enhancer.enhance(color_factor)

                # 暗い/明るい画像の自動明度補正（適応的制御）
                stat_img = resized_img.convert("L")
                try:
                    from PIL import ImageStat
                    mean_brightness = ImageStat.Stat(stat_img).mean[0]
                except (ValueError, TypeError, AttributeError, OSError, ZeroDivisionError) as e:
                    logger.debug(f"Failed to calculate mean brightness, using approximation: {e}")
                    mean_brightness = 128
                if mean_brightness < 50:
                    brightness_factor = 1.3
                    brightness_enhancer = ImageEnhance.Brightness(resized_img)
                    resized_img = brightness_enhancer.enhance(brightness_factor)
                elif mean_brightness < 85:
                    brightness_factor = 1.18
                    brightness_enhancer = ImageEnhance.Brightness(resized_img)
                    resized_img = brightness_enhancer.enhance(brightness_factor)
                elif mean_brightness >= 200:
                    brightness_factor = 0.88
                    brightness_enhancer = ImageEnhance.Brightness(resized_img)
                    resized_img = brightness_enhancer.enhance(brightness_factor)

                # 適応的コントラスト調整（平坦な画像には強い補正）
                extrema = stat_img.getextrema()
                if extrema:
                    min_val, max_val = extrema
                    brightness_range = max_val - min_val
                    print(f"DEBUG: brightness_range={brightness_range}, min={min_val}, max={max_val}, img_size={stat_img.size}", flush=True)
                    if brightness_range < 50:
                        # 非常にコントラストが低い（平坦な）画像の場合、ヒストグラム平坦化を施し、かつ元画像と適度にブレンドして色の破綻を抑えつつ画質を劇的に向上させる
                        try:
                            equalized = ImageOps.equalize(resized_img)
                            resized_img = Image.blend(resized_img, equalized, 0.45)
                        except (ValueError, OSError) as eq_err:
                            logger.warning(f"Failed to apply ImageOps.equalize: {eq_err}")
                        contrast_factor = 1.25
                    elif brightness_range < 100:
                        contrast_factor = 1.2
                    elif brightness_range < 150:
                        contrast_factor = 1.1
                    else:
                        contrast_factor = 1.05
                else:
                    contrast_factor = 1.05
                contrast_enhancer = ImageEnhance.Contrast(resized_img)
                resized_img = contrast_enhancer.enhance(contrast_factor)
                
                # 自動ホワイトバランス（カラーバランス・コントラスト調整）
                try:
                    # コントラスト度合いに応じて cutoff を動的に制御
                    if 'brightness_range' in locals() and brightness_range > 180:
                        dynamic_cutoff = 0.2
                    elif 'brightness_range' in locals() and brightness_range < 80:
                        dynamic_cutoff = 2.0
                    else:
                        dynamic_cutoff = 1.0
                    resized_img = ImageOps.autocontrast(resized_img, cutoff=dynamic_cutoff)
                except (ValueError, OSError) as ops_err:
                    logger.warning(f"Failed to apply ImageOps.autocontrast: {ops_err}")
            except AssertionError:
                raise
            except (ValueError, TypeError, OSError, AttributeError) as enh_err:
                logger.error(f"Failed to apply premium enhancements to image: {enh_err}", exc_info=True)
                
            paste_x = (target_w - new_w) // 2
            paste_y = (target_h - new_h) // 2
            canvas.paste(resized_img, (paste_x, paste_y))

            # 境界の視覚的強調（うっすらとしたダークボーダーの描画）
            if paste_x > 0 or paste_y > 0:
                try:
                    draw = ImageDraw.Draw(canvas)
                    draw.rectangle(
                        [paste_x, paste_y, paste_x + new_w - 1, paste_y + new_h - 1],
                        outline=(30, 30, 30),
                        width=2
                    )
                except (ValueError, TypeError, OSError) as border_err:
                    logger.warning(f"Failed to draw premium border: {border_err}")
            
    except DecompressionBombError as e:
        logger.error(f"Decompression bomb detected for image {image_path}: {e}")
        raise PreviewImageCorruptedError(f"Image size exceeds safety limits or is corrupted: {e}")
    except MemoryError as e:
        logger.critical(f"Memory limit exceeded during image processing: {e}")
        import gc
        gc.collect()
        raise PreviewImageCorruptedError(f"Out of memory during image processing: {e}")
    except (UnidentifiedImageError, IOError, OSError, ValueError, SyntaxError, IndexError, TypeError, AttributeError) as e:
        logger.error(f"Image processing failed for {image_path}: {e}")
        raise PreviewImageCorruptedError(f"Failed to process image for quality adjustment: {e}")
        
    ext = path.suffix.lower()
    
    # 段階的な圧縮フォーマットと設定の定義（4MB未満を死守するため）
    # ディザリングを明示的に有効にする（FLOYDSTEINBERG 定数を使用）
    dither_val = getattr(Image, "FLOYDSTEINBERG", 1)
    if ext in ('.jpg', '.jpeg'):
        formats_to_try = [
            ('JPEG', {'quality': 95, 'optimize': True, 'subsampling': 0}),
            ('JPEG', {'quality': 85, 'optimize': True, 'subsampling': 0}),
            ('JPEG', {'quality': 70, 'optimize': True, 'subsampling': 0}),
            ('JPEG', {'quality': 50, 'optimize': True}),
            ('JPEG', {'quality': 30, 'optimize': True}),
        ]
    else:
        formats_to_try = [
            ('PNG', {'optimize': True, 'compress_level': 9}),
            ('PNG', {'optimize': True, 'compress_level': 9, 'quantize': True, 'dither': dither_val}),
            # 4MBを超えた場合にノイズ低減フィルター（Smooth）を適用してさらなる圧縮を図る
            ('PNG', {'optimize': True, 'compress_level': 9, 'quantize': True, 'dither': dither_val, 'smooth': True}),
            ('JPEG', {'quality': 85, 'optimize': True, 'subsampling': 0}),
            ('JPEG', {'quality': 65, 'optimize': True}),
            ('JPEG', {'quality': 40, 'optimize': True}),
        ]

    temp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    success = False
    
    try:
        # 圧縮パラメータを順に試行して4MB未満のファイルを生成する
        for fmt, kwargs in formats_to_try:
            try:
                save_img = canvas
                save_kwargs = kwargs.copy()
                if icc_profile:
                    save_kwargs["icc_profile"] = icc_profile
                
                # 'smooth' フラグがある場合はノイズ低減フィルタを適用して圧縮率を劇的に向上させる
                if save_kwargs.pop('smooth', False):
                    save_img = save_img.filter(ImageFilter.SMOOTH)
                
                if save_kwargs.pop('quantize', False):
                    # 減色処理 (PNG-8) とディザリング適用
                    dither_mode = save_kwargs.pop('dither', dither_val)
                    save_img = save_img.quantize(colors=256, dither=dither_mode)
                    
                # 一時ファイルへの保存時にI/Oエラー（ロックなど）を考慮したリトライループを追加
                save_success = False
                for save_attempt in range(1, 4):
                    try:
                        save_img.save(temp_path, fmt, **save_kwargs)
                        save_success = True
                        break
                    except (IOError, OSError, ValueError, TypeError) as save_io_err:
                        # ICCプロファイル破損などが疑われる場合、ICCプロファイルを削除してリトライ
                        if "icc_profile" in save_kwargs:
                            logger.warning(f"Saving with ICC profile failed, retrying without it: {save_io_err}")
                            save_kwargs.pop("icc_profile", None)
                            continue
                        if save_attempt == 3:
                            raise save_io_err
                        logger.warning(f"Save attempt {save_attempt}/3 failed with I/O error: {save_io_err}. Retrying...")
                        time.sleep(0.1 * save_attempt)

                if not save_success:
                    continue
                
                # 一時ファイルのサイズをチェック
                size_bytes = temp_path.stat().st_size
                if size_bytes < 4 * 1024 * 1024:
                    success = True
                    break
                else:
                    logger.warning(f"Saved temp image size {size_bytes} exceeds 4MB limit under format {fmt}. Trying next fallback...")
                    if temp_path.exists():
                        temp_path.unlink()
            except (OSError, ValueError, TypeError) as save_err:
                logger.warning(f"Failed to save temp image in format {fmt}: {save_err}")
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
 
        if not success:
            # 最終防御ライン: 圧縮しても4MBを超える場合、解像度を段階的に下げて再試行する
            logger.warning("Applying extreme fallback: downsizing image resolution to fit 4MB limit.")
            for downscale_factor in [0.75, 0.5]:
                try:
                    temp_w = int(target_w * downscale_factor)
                    temp_h = int(target_h * downscale_factor)
                    downscaled_canvas = canvas.resize((temp_w, temp_h), resample_filter)
                    
                    # 16:9のアスペクト比を維持したまま、解像度を下げて再試行
                    for fmt, kwargs in [('JPEG', {'quality': 60, 'optimize': True}), ('JPEG', {'quality': 40, 'optimize': True})]:
                        try:
                            downscaled_canvas.save(temp_path, fmt, **kwargs)
                            size_bytes = temp_path.stat().st_size
                            if size_bytes < 4 * 1024 * 1024:
                                # 1280x720 以上の解像度要件を満たすため、1280x720 にアップスケールし直して、より高い圧縮率で保存する
                                re_canvas = downscaled_canvas.resize((target_w, target_h), resample_filter)
                                re_canvas.save(temp_path, 'JPEG', quality=45, optimize=True)
                                if temp_path.stat().st_size < 4 * 1024 * 1024:
                                    success = True
                                    break
                        except (OSError, ValueError) as fallback_err:
                            logger.warning(f"Extreme fallback attempt failed: {fallback_err}")
                    if success:
                        break
                except (ValueError, OSError, MemoryError) as downscale_err:
                    logger.error(f"Failed downscaling during extreme fallback: {downscale_err}")

        if not success:
            logger.error(f"Failed to compress preview image {image_path} below 4MB limit.")
            raise PreviewImageSizeExceededError("Could not reduce image file size below 4MB even after compression/quantization attempts.")
 
        # 原子的な書き込み (Atomic Write) と Windows 向けリトライ処理
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            try:
                if path.exists():
                    try:
                        os.remove(str(path))
                    except (PermissionError, OSError) as unlink_err:
                        logger.warning(f"Could not unlink existing path {path} on attempt {attempt}: {unlink_err}")
                os.replace(str(temp_path), str(path))
                break
            except (IOError, OSError, ValueError) as e:
                logger.warning(f"Attempt {attempt}/{max_attempts} failed to rename tmp file: {e}")
                if attempt == max_attempts:
                    # renameが全て失敗した場合、shutil.copy と unlink による代替処理（フォールバック）を試みる
                    try:
                        logger.info("Attempting fallback copy & delete due to rename failure...")
                        shutil.copy(str(temp_path), str(path))
                        try:
                            os.remove(str(temp_path))
                        except OSError:
                            pass
                        break
                    except (IOError, OSError) as fallback_err:
                        logger.error(f"Failed to finalize adjusted image via fallback: {fallback_err}")
                        raise RuntimeError(f"Failed to save adjusted image: {fallback_err}")
                time.sleep(0.15 * attempt)  # 指数バックオフで待機
    finally:
        # 堅牢な一時ファイルクリーンアップ
        if temp_path.exists():
            for cleanup_attempt in range(1, 4):
                try:
                    os.remove(str(temp_path))
                    break
                except OSError as cleanup_err:
                    logger.warning(f"Failed to clean up temp file {temp_path} (attempt {cleanup_attempt}/3): {cleanup_err}")
                    time.sleep(0.1 * cleanup_attempt)
                
    return str(path)


async def resolve_comprehensive_preview_task(self, task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理。
    包括的プレビューの生成と、その画像の品質検証を行う。
    """
    try:
        input_video = getattr(self, "input_video", None)
        if not input_video:
            raise ValueError("input_video not configured on agent")
            
        output_dir = getattr(self, "output_dir", None) or "backend/temp/comprehensive_preview"
        timestamps = getattr(self, "timestamps", None) or [0.5, 3.0, 7.0]
        
        # スレッドでプレビュー生成プロセスを走らせる
        result = await asyncio.to_thread(
            create_comprehensive_preview,
            input_video,
            output_dir=output_dir,
            timestamps=timestamps
        )
        
        # 生成されたすべての comprehensive スクリーンショットを検証
        validation_results = []
        screenshots = result.get("screenshots", {})
        comp_screenshots = screenshots.get("comprehensive", [])
        
        if not comp_screenshots:
            raise ValueError("No comprehensive screenshots were generated")
            
        for img_path in comp_screenshots:
            corrected_path = ensure_preview_image_quality(img_path)
            val_res = validate_preview_image(corrected_path)
            validation_results.append(val_res)
            
        result_info = {
            "task_id": task_id,
            "preview_result": result,
            "validation": validation_results
        }
        
        return json.dumps(result_info, ensure_ascii=False)
    except (ValueError, TypeError, OSError, AttributeError, IndexError, KeyError, RuntimeError, PreviewGenerationError) as e:
        logger.error(f"Error occurred during comprehensive preview task execution ({task_id}): {e}", exc_info=True)
        raise PreviewGenerationError(f"Task execution failed: {e}") from e



def create_comprehensive_preview(
    input_video: str,
    output_dir: str = "backend/temp/comprehensive_preview",
    timestamps: list[float] = None
):
    """
    包括的なプレビューを生成
    
    1. ロゴ+テロップのみ
    2. 字幕のみ
    3. カラーグレーディングのみ
    4. 全要素統合
    """
    # 1. 引数のガード処理
    if not input_video or not isinstance(input_video, (str, Path)):
        raise ValueError("input_video must be a non-empty string or Path object")
    if not output_dir or not isinstance(output_dir, (str, Path)):
        raise ValueError("output_dir must be a non-empty string or Path object")
    if timestamps is not None:
        if not isinstance(timestamps, list) or not all(isinstance(t, (int, float)) for t in timestamps):
            raise ValueError("timestamps must be a list of numbers")

    input_path = Path(input_video)
    if not input_path.exists():
        raise FileNotFoundError(f"Input video file not found: {input_video}")

    try:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to create output directory {output_dir}: {e}")
        raise

    # 最初の10秒を抽出
    temp_video = output_dir / "base_10s.mp4"
    logger.info("Extracting first 10 seconds...")
    
    extract_cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-t", "10",
        "-c:v", "libx264",
        "-c:a", "copy",
        "-y",
        str(temp_video)
    ]
    
    created_files = [temp_video]
    
    try:
        ffmpeg_success = False
        ffmpeg_error = None
        for attempt in range(1, 4):
            try:
                subprocess.run(extract_cmd, check=True, capture_output=True, timeout=60)
                ffmpeg_success = True
                break
            except subprocess.TimeoutExpired as e:
                logger.warning(f"ffmpeg extraction timed out (attempt {attempt}/3): {e}")
                ffmpeg_error = PreviewGenerationError(f"ffmpeg extraction timed out: {e}")
            except OSError as e:
                logger.warning(f"ffmpeg execution failed (attempt {attempt}/3): {e}")
                ffmpeg_error = PreviewGenerationError(f"ffmpeg execution failed: {e}")
            except subprocess.CalledProcessError as e:
                stderr_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
                logger.warning(f"ffmpeg extraction failed (attempt {attempt}/3): {stderr_msg}")
                ffmpeg_error = PreviewGenerationError(f"ffmpeg extraction failed: {stderr_msg}")
            
            if attempt < 3:
                time.sleep(0.5 * attempt)
        
        if not ffmpeg_success:
            if ffmpeg_error:
                raise ffmpeg_error
            raise PreviewGenerationError("ffmpeg extraction failed after 3 attempts")

        logger.info(f"✅ Base video extracted: {temp_video}")
        
        # 1. ロゴ+テロップ
        logger.info("\n=== 1. Logo + Telop ===")
        from combined_overlay import CombinedOverlay
        
        overlay = CombinedOverlay()
        logo_output = output_dir / "01_logo_telop.mp4"
        created_files.append(logo_output)
        
        overlay.apply_brand_overlay(
            input_video=str(temp_video),
            output_path=str(logo_output),
            speaker1="北原美麗",
            speaker2="山田タロウ",
            theme="想いを筆で起こす"
        )
        logger.info(f"✅ Logo+Telop: {logo_output}")
        
        # 2. 字幕のみ（簡易版・焼き込みなし）
        logger.info("\n=== 2. Subtitle Info ===")
        subtitle_file = input_path.parent / f"{input_path.stem}_whisper_semantic.srt"
        
        subtitle_loaded = False
        if subtitle_file.exists():
            logger.info(f"✅ Subtitle file found: {subtitle_file.name}")
            try:
                # 最初の5行を読み込んで表示
                with open(subtitle_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[:20]
                    logger.info("Subtitle sample:")
                    for line in lines:
                        logger.info(f"  {line.rstrip()}")
                subtitle_loaded = True
            except (OSError, UnicodeDecodeError) as e:
                logger.warning(f"⚠️ Failed to read subtitle file {subtitle_file}: {e}")
        else:
            logger.warning(f"⚠️ Subtitle file not found: {subtitle_file}")
        
        # 3. カラーグレーディング
        logger.info("\n=== 3. Color Grading ===")
        from color_grading import ColorGrading
        
        grading = ColorGrading()
        color_output = output_dir / "03_color_graded.mp4"
        created_files.append(color_output)
        
        grading.apply_lut(
            str(temp_video),
            str(color_output),
            "cinematic"
        )
        logger.info(f"✅ Color graded: {color_output}")
        
        # 4. 全要素統合
        logger.info("\n=== 4. Comprehensive ===")
        comprehensive_output = output_dir / "04_comprehensive.mp4"
        created_files.append(comprehensive_output)
        
        overlay.apply_brand_overlay(
            input_video=str(color_output),
            output_path=str(comprehensive_output),
            speaker1="北原美麗",
            speaker2="山田タロウ",
            theme="想いを筆で起こす"
        )
        logger.info(f"✅ Comprehensive preview: {comprehensive_output}")
        
        # スクリーンショット生成
        logger.info("\n=== Generating Screenshots ===")
        from screenshot_generator import generate_multiple_screenshots
        
        actual_timestamps = timestamps if timestamps is not None else [0.5, 3.0, 7.0]
        
        # ロゴ+テロップのスクリーンショット
        logo_screenshots = generate_multiple_screenshots(
            str(logo_output),
            actual_timestamps,
            str(output_dir / "screenshots"),
            "01_logo_telop"
        )
        for i, path in enumerate(logo_screenshots):
            p = Path(path)
            created_files.append(p)
            if p.exists():
                if subtitle_loaded and subtitle_file.exists():
                    sub_text = _parse_srt_subtitle_for_timestamp(subtitle_file, actual_timestamps[i])
                    if sub_text:
                        _draw_subtitle_on_image(path, sub_text)
                logo_screenshots[i] = ensure_preview_image_quality(path)
                validate_preview_image(logo_screenshots[i])
        logger.info(f"✅ Logo screenshots: {len(logo_screenshots)}")
        
        # カラーグレーディングのスクリーンショット  
        color_screenshots = generate_multiple_screenshots(
            str(color_output),
            actual_timestamps,
            str(output_dir / "screenshots"),
            "03_color_graded"
        )
        for i, path in enumerate(color_screenshots):
            p = Path(path)
            created_files.append(p)
            if p.exists():
                color_screenshots[i] = ensure_preview_image_quality(path)
                validate_preview_image(color_screenshots[i])
        logger.info(f"✅ Color screenshots: {len(color_screenshots)}")
        
        # 統合プレビューのスクリーンショット
        comprehensive_screenshots = generate_multiple_screenshots(
            str(comprehensive_output),
            actual_timestamps,
            str(output_dir / "screenshots"),
            "04_comprehensive"
        )
        for i, path in enumerate(comprehensive_screenshots):
            p = Path(path)
            created_files.append(p)
            if p.exists():
                if subtitle_loaded and subtitle_file.exists():
                    sub_text = _parse_srt_subtitle_for_timestamp(subtitle_file, actual_timestamps[i])
                    if sub_text:
                        _draw_subtitle_on_image(path, sub_text)
                comprehensive_screenshots[i] = ensure_preview_image_quality(path)
                validate_preview_image(comprehensive_screenshots[i])
        logger.info(f"✅ Comprehensive screenshots: {len(comprehensive_screenshots)}")
        
        logger.info("\n" + "="*60)
        logger.info("🎉 Comprehensive preview generation complete!")
        logger.info("="*60)
        logger.info(f"\nOutput directory: {output_dir}")
        logger.info(f"  1. Logo+Telop: {logo_output.name}")
        logger.info(f"  2. Subtitle file: {subtitle_file.name if subtitle_loaded else 'Not found'}")
        logger.info(f"  3. Color graded: {color_output.name}")
        logger.info(f"  4. Comprehensive: {comprehensive_output.name}")
        logger.info(f"  Screenshots: {output_dir / 'screenshots'}")
        
        return {
            "base": str(temp_video),
            "logo_telop": str(logo_output),
            "subtitle_file": str(subtitle_file) if subtitle_loaded else None,
            "color_graded": str(color_output),
            "comprehensive": str(comprehensive_output),
            "screenshots": {
                "logo": logo_screenshots,
                "color": color_screenshots,
                "comprehensive": comprehensive_screenshots
            }
        }
    except (ValueError, TypeError, OSError, AttributeError, IndexError, KeyError, RuntimeError, PreviewGenerationError) as e:
        logger.error(f"Error occurred during comprehensive preview generation: {e}", exc_info=True)
        # 例外が発生した場合は、生成途中の中間ファイルをクリーンアップする
        for f in created_files:
            if not f.exists():
                continue
            for cleanup_attempt in range(1, 5):
                try:
                    if f.is_dir():
                        shutil.rmtree(f)
                    else:
                        f.unlink()
                    logger.info(f"Cleaned up temporary file/dir: {f.name}")
                    break
                except OSError as unlink_err:
                    logger.warning(f"Failed to cleanup {f} (attempt {cleanup_attempt}/4): {unlink_err}")
                    if cleanup_attempt == 4:
                        logger.error(f"Failed to cleanup file {f} after 4 attempts.")
                    else:
                        time.sleep(0.15 * cleanup_attempt)
        raise


if __name__ == "__main__":  # pragma: no cover
    # シーン04でテスト
    input_video = str(raw_videos_dir() / "AI Studio アップロード用動画" / "シーン04_後編02.mp4")
    
    if not Path(input_video).exists():
        print(f"❌ Video not found: {input_video}")
        sys.exit(1)
    
    result = create_comprehensive_preview(input_video)
    
    print("\n" + "="*60)
    print("📊 Preview Summary")
    print("="*60)
    for key, value in result.items():
        print(f"{key}: {value}")
