try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import json
import os
import time
import logging
import struct
import io
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional

# Paths
# 相対パスなのでプロセスの起動ディレクトリ基準になっていた。リポジトリ直下から
# 動かすと Git 追跡下の archives/analytics/history.jsonl に追記される
# （`archives/` は過去版のスナップショット置き場で、触ってはいけない領域）。
# 実行のたびに追記されるログなので writable_path 経由にする。
HISTORY_FILE = _writable_path("archives/analytics/history.jsonl")

logger = logging.getLogger(__name__)

class EventType(Enum):
    STATUS_CHANGE = "STATUS_CHANGE"
    TASK_COMPLETION = "TASK_COMPLETION"
    CHAT_INTERACTION = "CHAT_INTERACTION"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    USER_INTERACTION = "USER_INTERACTION"
    CONTENT_EXPORT = "CONTENT_EXPORT"


class StatusHistoryManager:
    """
    Manages the persistent history of the User-AI evolution.
    Uses JSON Lines (.jsonl) for append-only, scalable storage.
    """
    def __init__(self, history_file: Path = None):
        self.history_file = history_file or HISTORY_FILE

    def _ensure_storage(self):
        """Creates the directory and file if not exists."""
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            if not self.history_file.exists():
                self.history_file.touch()
        except (OSError, IOError) as e:
            logger.error(f"Failed to ensure storage directory or file: {e}")

    def log_event(self, event_type: EventType, data: dict):
        """
        Logs a standardized event to the history.
        """
        self._ensure_storage()
        entry = {
            "timestamp": time.time(),
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": event_type.value,
            "data": data
        }
        
        try:
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.error(f"Failed to log history (OS/IO error): {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error when logging history: {e}", exc_info=True)

    def get_history(self, limit=100):
        """Retrieves the last N records."""
        records = []
        try:
            if not self.history_file.exists():
                return []
            with open(self.history_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except (json.JSONDecodeError, TypeError) as pe:
                        logger.warning(f"Skipping corrupted history line: {pe}")
            return records[-limit:]
        except OSError as e:
            logger.error(f"Failed to read history (OS/IO error): {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Unexpected error when reading history: {e}", exc_info=True)
            return []

    def get_recent_events(self, event_type: EventType, limit=100):
        """Retrieves the last N records filtering by event type."""
        all_records = self.get_history(limit=limit * 10)
        filtered = [r for r in all_records if r.get("type") == event_type.value]
        return filtered[-limit:]


# Singleton instance
history_manager = StatusHistoryManager()


class ImageValidationError(ValueError):
    """画像検証でエラーが発生した場合のカスタム例外"""
    pass


class ThumbnailValidator:
    """
    サムネイル画像の解像度、アスペクト比、ファイルサイズ、カラー品質を検証するクラス
    """
    @staticmethod
    def _get_image_dimensions_and_mode(image_bytes: bytes) -> tuple[tuple[int, int], Optional[str]]:
        """
        画像バイナリから ((width, height), mode) を取得する。
        Pillow が利用できる場合はそれを使用し、利用できない場合は JPEG/PNG のバイナリヘッダーを解析する。
        """
        # 1. Pillowを使用する試み
        try:
            from PIL import Image
            try:
                # 破損をより確実に検出するためにBytesIOで読み込み、verifyおよびloadを実行
                with Image.open(io.BytesIO(image_bytes)) as img:
                    img.verify()
                with Image.open(io.BytesIO(image_bytes)) as img:
                    img.load()  # 実際にピクセルデータをロードして破損チェックを行う
                    # 転置処理（FLIP）を実行してデコーダと内部のピクセルデータの完全性を徹底検証
                    img.transpose(Image.FLIP_LEFT_RIGHT)
                    return img.size, img.mode
            except Exception as e:
                # Pillowがあるのにデコードに失敗した場合は、フォールバックせず破損とみなす
                logger.error(f"Pillow failed to decode image bytes: {e}")
                raise ImageValidationError(f"Image quality check failed: Image is corrupted or invalid format: {e}") from e
        except ImportError:
            logger.info("Pillow is not available, falling back to binary parsing.")

        # 2. 自前バイナリ解析（フォールバック）
        try:
            # PNG 判定
            if image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
                if len(image_bytes) < 24:
                    raise ImageValidationError("Image quality check failed: invalid PNG format (missing header data)")
                # PNGの末尾にIENDが含まれているか確認（簡易破損チェック）
                if b'IEND' not in image_bytes[-12:]:
                    raise ImageValidationError("Image quality check failed: PNG image is corrupted (missing IEND chunk at end)")
                w, h = struct.unpack('>II', image_bytes[16:24])
                return (w, h), None

            # JPEG 判定
            if image_bytes.startswith(b'\xff\xd8'):
                if len(image_bytes) < 10:
                    raise ImageValidationError("Image quality check failed: JPEG image is too short")
                # JPEGの末尾にEOIマーカー（\xff\xd9）が含まれているか確認（簡易破損チェック）
                if not image_bytes.endswith(b'\xff\xd9') and b'\xff\xd9' not in image_bytes[-4:]:
                    raise ImageValidationError("Image quality check failed: JPEG image is corrupted (missing EOI marker at end)")
                idx = 2
                while idx < len(image_bytes):
                    if image_bytes[idx] != 0xff:
                        idx += 1
                        continue
                    
                    while idx < len(image_bytes) and image_bytes[idx] == 0xff:
                        idx += 1
                    if idx >= len(image_bytes):
                        break
                    
                    marker = image_bytes[idx]
                    idx += 1
                    
                    if marker in (0xd0, 0xd1, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0x01, 0x00):
                        continue
                    
                    if idx + 2 > len(image_bytes):
                        break
                    length = struct.unpack('>H', image_bytes[idx:idx+2])[0]
                    
                    if length < 2:
                        raise ImageValidationError("Image quality check failed: invalid JPEG format (marker segment length is too small)")
                    
                    if 0xc0 <= marker <= 0xcf and marker not in (0xc4, 0xc8, 0xcc):
                        if idx + 2 + 5 <= len(image_bytes):
                            h, w = struct.unpack('>HH', image_bytes[idx+3:idx+7])
                            return (w, h), None
                        break
                    if idx + length > len(image_bytes):
                        raise ImageValidationError("Image quality check failed: invalid JPEG format (segment extends beyond bytes)")
                    idx += length
                raise ImageValidationError("Image quality check failed: invalid JPEG format or SOF marker not found")
            
            raise ImageValidationError("Image quality check failed: Unsupported image format (only JPEG and PNG are supported)")
        except (IndexError, struct.error) as se:
            logger.error(f"Binary parsing of image failed: {se}", exc_info=True)
            raise ImageValidationError(f"Image quality check failed: Failed to parse image binary structure: {se}") from se

    @staticmethod
    def validate_image(
        image_bytes: bytes, 
        min_width: int = 1280, 
        min_height: int = 720, 
        aspect_ratio: str = "16:9", 
        max_size_bytes: int = 4 * 1024 * 1024,
        allowed_modes: Optional[List[str]] = None
    ) -> bool:
        """
        画像の品質とフォーマットを検証する。
        - ファイルサイズ制限 (default: 4MB)
        - 最小解像度 (default: 1280x720)
        - アスペクト比 (default: 16:9 = 1.777...)
        - カラー品質/カラーモード検証 (Pillowが利用可能な場合のみ検証、例: L/1などの白黒のグレースケールを排除)
        """
        if not image_bytes:
            raise ImageValidationError("Image quality check failed: Image data is empty")
        if len(image_bytes) < 24:
            raise ImageValidationError("Image quality check failed: Image data is too small to be valid")
        
        # 1. ファイルサイズ検証
        size = len(image_bytes)
        if size >= max_size_bytes:
            raise ImageValidationError(f"Image quality check failed: File size {size} bytes exceeds limit of {max_size_bytes} bytes")
        
        # 2. 解像度 & モード検証
        (width, height), mode = ThumbnailValidator._get_image_dimensions_and_mode(image_bytes)
        if width <= 0 or height <= 0:
            raise ImageValidationError(f"Image quality check failed: Invalid image dimensions {width}x{height}")
        if width < min_width or height < min_height:
            raise ImageValidationError(f"Image quality check failed: Resolution {width}x{height} is below minimum requirement of {min_width}x{min_height}")
        
        # 3. アスペクト比検証
        if aspect_ratio == "16:9":
            target_ratio = 16.0 / 9.0  # 1.777...
            actual_ratio = float(width) / float(height)
            if abs(actual_ratio - target_ratio) > 0.05:
                raise ImageValidationError(f"Image quality check failed: Aspect ratio {width}:{height} ({actual_ratio:.2f}) does not match expected 16:9")
        elif aspect_ratio == "1:1":
            target_ratio = 1.0
            actual_ratio = float(width) / float(height)
            if abs(actual_ratio - target_ratio) > 0.05:
                raise ImageValidationError(f"Image quality check failed: Aspect ratio {width}:{height} ({actual_ratio:.2f}) does not match expected 1:1")
        
        # 4. カラーモード検証
        if allowed_modes and mode and mode not in allowed_modes:
            raise ImageValidationError(f"Image quality check failed: color mode {mode} is not allowed")
            
        return True


class PremiumThumbnailGenerator:
    """
    高品質なプレミアムサムネイル画像を生成するクラス
    """
    @staticmethod
    def generate(
        output_path,
        width: int = 1280,
        height: int = 720,
        text: str = "Premium Thumbnail",
        draw_arrow: bool = False,
        draw_circle: bool = False,
        use_banner: bool = True
    ) -> Path:
        import os
        import uuid
        from PIL import Image, ImageDraw, ImageFont
        from pathlib import Path
        
        try:
            width = int(width)
            height = int(height)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Width and height must be integers: {e}")
            
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
            
        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        if abs(aspect_ratio - target_ratio) > 0.05:
            raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
            
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # スーパーサンプリングスケール設定（巨大な解像度でのメモリ爆発とハングを防ぐため、1080pを超える場合は1に制限）
        scale = 2
        if width > 1920 or height > 1080:
            scale = 1
        w_draw = width * scale
        h_draw = height * scale
        
        # 原子的な書き込み (Atomic Write) の実装
        temp_path = None
        try:
            temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            # 1. 3色グラデーション背景
            color1 = (11, 19, 43)      # リッチディープネイビー
            color2 = (44, 19, 84)      # ディープバイオレット
            color3 = (158, 20, 100)    # ネオンマゼンタ
            
            try:
                import numpy as np
                y_grid, x_grid = np.ogrid[:h_draw, :w_draw]
                factor = (x_grid / (w_draw - 1.0) + y_grid / (h_draw - 1.0)) / 2.0
                c1 = np.array(color1, dtype=np.float32)
                c2 = np.array(color2, dtype=np.float32)
                c3 = np.array(color3, dtype=np.float32)
                
                mask = factor < 0.5
                t = np.where(mask, factor * 2.0, (factor - 0.5) * 2.0)
                
                # Smoothstep (Hermite interpolation) for smoother gradient transitions
                t_smooth = t * t * (3.0 - 2.0 * t)
                
                r = np.where(mask, c1[0] + (c2[0] - c1[0]) * t_smooth, c2[0] + (c3[0] - c2[0]) * t_smooth)
                g = np.where(mask, c1[1] + (c2[1] - c1[1]) * t_smooth, c2[1] + (c3[1] - c2[1]) * t_smooth)
                b = np.where(mask, c1[2] + (c2[2] - c1[2]) * t_smooth, c2[2] + (c3[2] - c2[2]) * t_smooth)
                
                # 高品質なディザーノイズでカラーバンディング（階調の縞）を徹底排除
                dither = np.random.uniform(-0.8, 0.8, (h_draw, w_draw, 3))
                rgb = np.clip(np.stack([r, g, b], axis=-1) + dither, 0, 255).astype(np.uint8)
                img = Image.fromarray(rgb)
            except ImportError:
                import random
                # NumPyがない場合のフォールバック: Smoothstepによる滑らかなグラデーション
                grad_size = 1024
                grad_line = Image.new("RGB", (grad_size, 1))
                half_size = grad_size // 2
                for x in range(half_size):
                    t = x / (half_size - 1)
                    t_smooth = t * t * (3.0 - 2.0 * t)
                    r = int(color1[0] * (1 - t_smooth) + color2[0] * t_smooth)
                    g = int(color1[1] * (1 - t_smooth) + color2[1] * t_smooth)
                    b = int(color1[2] * (1 - t_smooth) + color2[2] * t_smooth)
                    grad_line.putpixel((x, 0), (r, g, b))
                for x in range(half_size):
                    t = x / (half_size - 1)
                    t_smooth = t * t * (3.0 - 2.0 * t)
                    r = int(color2[0] * (1 - t_smooth) + color3[0] * t_smooth)
                    g = int(color2[1] * (1 - t_smooth) + color3[1] * t_smooth)
                    b = int(color2[2] * (1 - t_smooth) + color3[2] * t_smooth)
                    grad_line.putpixel((half_size + x, 0), (r, g, b))
                
                grad_2d = Image.new("RGB", (grad_size, grad_size))
                for y in range(grad_size):
                    for x in range(grad_size):
                        factor = (x + y) / (2 * grad_size - 2)
                        idx = int(factor * (grad_size - 1))
                        r, g, b = grad_line.getpixel((idx, 0))
                        dither = random.uniform(-0.8, 0.8)
                        rn = min(255, max(0, int(r + dither)))
                        gn = min(255, max(0, int(g + dither)))
                        bn = min(255, max(0, int(b + dither)))
                        grad_2d.putpixel((x, y), (rn, gn, bn))
                img = grad_2d.resize((w_draw, h_draw), Image.Resampling.LANCZOS)
            
            # 2. 幾何学的格子パターンの半透明オーバーレイ
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            
            grid_spacing = 80 * scale
            for offset in range(-h_draw, w_draw + h_draw, grid_spacing):
                overlay_draw.line([(offset, 0), (offset + h_draw, h_draw)], fill=(255, 255, 255, 12), width=1 * scale)
                overlay_draw.line([(offset, h_draw), (offset + h_draw, 0)], fill=(255, 255, 255, 12), width=1 * scale)
                
            # 3. フォントの動的選択とオートスケール
            font = None
            font_paths = [
                r"C:\Windows\Fonts\segoeui.ttf",
                r"C:\Windows\Fonts\meiryo.ttc",
                r"C:\Windows\Fonts\msgothic.ttc",
                r"C:\Windows\Fonts\yugothm.ttc",
                r"C:\Windows\Fonts\msmincho.ttc",
                r"C:\Windows\Fonts\BIZ-UDGothicR.ttc",
                r"C:\Windows\Fonts\BIZ-UDMinchoR.ttc",
                r"C:\Windows\Fonts\arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/ヒラギノ角ゴ ProN W3.ttc",
                "/Library/Fonts/Arial.ttf"
            ]
            
            # 最大文字幅制限 (画像幅の80%) と最大高さ制限 (画像高の65%)
            max_allowed_width = int(w_draw * 0.8)
            max_allowed_height = int(h_draw * 0.65)
            font_size = 48 * scale  # 初期フォントサイズをやや高めて品質とインパクトを優先
            
            selected_font_path = None
            for fp in font_paths:
                if os.path.exists(fp):
                    try:
                        ImageFont.truetype(fp, font_size)
                        selected_font_path = fp
                        break
                    except Exception as e:
                        logger.warning(f"Found font file {fp} but failed to load: {e}")
            
            # 日本語/英語対応の自動折り返し関数
            def wrap_text(text_to_wrap, current_font, max_w):
                lines = []
                for paragraph in text_to_wrap.split('\n'):
                    if not paragraph:
                        lines.append("")
                        continue
                    current_line = ""
                    for char in paragraph:
                        test_line = current_line + char
                        try:
                            bbox = overlay_draw.textbbox((0, 0), test_line, font=current_font)
                            w = bbox[2] - bbox[0]
                        except AttributeError:
                            if hasattr(current_font, "getsize"):
                                w, _ = current_font.getsize(test_line)
                            else:
                                w = len(test_line) * (font_size * 0.6)
                        if w <= max_w:
                            current_line = test_line
                        else:
                            if current_line:
                                lines.append(current_line)
                            current_line = char
                    if current_line:
                        lines.append(current_line)
                return lines

            wrapped_lines = []
            text_width = 0
            text_height = 0
            line_gap = 0
            
            while font_size >= 14 * scale:
                if selected_font_path:
                    try:
                        font = ImageFont.truetype(selected_font_path, font_size)
                    except (OSError, RuntimeError):
                        font = None
                
                if font is None:
                    try:
                        font = ImageFont.load_default(size=font_size)
                    except TypeError:
                        font = ImageFont.load_default()
                
                wrapped_lines = wrap_text(text, font, max_allowed_width)
                
                max_w = 0
                total_h = 0
                for line in wrapped_lines:
                    try:
                        bbox = overlay_draw.textbbox((0, 0), line, font=font)
                        w = bbox[2] - bbox[0]
                        h = bbox[3] - bbox[1]
                    except AttributeError:
                        if hasattr(font, "getsize"):
                             w, h = font.getsize(line)
                        else:
                             w, h = len(line) * (font_size * 0.6), font_size
                    max_w = max(max_w, w)
                    total_h += h
                
                line_gap = int(font_size * 0.3)
                total_h += line_gap * (len(wrapped_lines) - 1)
                
                if max_w <= max_allowed_width and total_h <= max_allowed_height:
                    text_width = max_w
                    text_height = total_h
                    break
                
                if selected_font_path is None:
                    text_width = max_w
                    text_height = total_h
                    break
                font_size -= 2 * scale
            
            y_cursor = (h_draw - text_height) // 2
            
            # 4. ネオングラスモルフィズム風カード背景の描画
            if use_banner and text:
                rect_padding_w = 60 * scale
                rect_padding_h = 35 * scale
                rect_x1 = max(10 * scale, (w_draw - text_width) // 2 - rect_padding_w)
                rect_y1 = max(10 * scale, y_cursor - rect_padding_h)
                rect_x2 = min(w_draw - 10 * scale, (w_draw - text_width) // 2 + text_width + rect_padding_w)
                rect_y2 = min(h_draw - 10 * scale, y_cursor + text_height + rect_padding_h)
                
                # 半透明白背景
                overlay_draw.rounded_rectangle(
                    [rect_x1, rect_y1, rect_x2, rect_y2],
                    radius=20 * scale,
                    fill=(255, 255, 255, 20),
                    outline=(255, 255, 255, 100),
                    width=2 * scale
                )
                
                # ハイライト線
                overlay_draw.rounded_rectangle(
                    [rect_x1 - 2 * scale, rect_y1 - 2 * scale, rect_x2 + 2 * scale, rect_y2 + 2 * scale],
                    radius=22 * scale,
                    fill=None,
                    outline=(255, 255, 255, 40),
                    width=1 * scale
                )

            # 5. 注目を集める矢印の描画
            if draw_arrow:
                arrow_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                arrow_draw = ImageDraw.Draw(arrow_overlay)
                # 鋭くダイナミックなプレミアム矢印の頂点定義
                pts = [
                    (int(w_draw * 0.65), int(h_draw * 0.35)),  # 先端
                    (int(w_draw * 0.74), int(h_draw * 0.26)),  # 鏃の上翼
                    (int(w_draw * 0.72), int(h_draw * 0.28)),  # インサイド上
                    (int(w_draw * 0.82), int(h_draw * 0.18)),  # 軸の根元上
                    (int(w_draw * 0.84), int(h_draw * 0.20)),  # 軸の根元下
                    (int(w_draw * 0.74), int(h_draw * 0.30)),  # インサイド下
                    (int(w_draw * 0.76), int(h_draw * 0.38)),  # 鏃の下翼
                ]
                arrow_draw.polygon(pts, fill=(230, 30, 30, 230), outline=(255, 215, 0, 255), width=3 * scale)
                overlay = Image.alpha_composite(overlay, arrow_overlay)
                overlay_draw = ImageDraw.Draw(overlay)

            # 6. 強調サークルの描画
            if draw_circle:
                circle_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                circle_draw = ImageDraw.Draw(circle_overlay)
                cx = int(w_draw * 0.25)
                cy = int(h_draw * 0.5)
                rx = int(w_draw * 0.12)
                ry = int(h_draw * 0.22)
                circle_draw.ellipse(
                    [cx - rx, cy - ry, cx + rx, cy + ry],
                    outline=(255, 215, 0, 200),
                    width=max(4, int(min(w_draw, h_draw) * 0.008))
                )
                overlay = Image.alpha_composite(overlay, circle_overlay)
                overlay_draw = ImageDraw.Draw(overlay)
            
            # 7. テキスト描画 (シャドウ + メインゴールド)
            for line in wrapped_lines:
                try:
                    bbox = overlay_draw.textbbox((0, 0), line, font=font)
                    w = bbox[2] - bbox[0]
                    h = bbox[3] - bbox[1]
                except AttributeError:
                    if hasattr(font, "getsize"):
                        w, h = font.getsize(line)
                    else:
                        w, h = len(line) * (font_size * 0.6), font_size
                
                x_line = (w_draw - w) // 2
                
                # ドロップシャドウ
                overlay_draw.text((x_line + 2 * scale, y_cursor + 2 * scale), line, fill=(0, 0, 0, 180), font=font)
                # ゴールドカラー
                overlay_draw.text((x_line, y_cursor), line, fill=(255, 215, 0, 255), font=font)
                
                y_cursor += h + line_gap
            
            # 合成
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
            
            # スーパーサンプリング縮小処理
            try:
                resample_filter = Image.Resampling.LANCZOS
            except AttributeError:
                try:
                    resample_filter = Image.LANCZOS
                except AttributeError:
                    resample_filter = Image.ANTIALIAS
            img = img.resize((width, height), resample_filter)
            
            # ファイルサイズ4MB未満を保証する堅牢な保存ループ (自動圧縮/減色/JPEGフォールバック)
            max_size = 4 * 1024 * 1024
            ext = output_path.suffix.lower()
            
            if ext in [".jpg", ".jpeg"]:
                # JPEG保存 (限界まで高精細にするため quality=95 から 5刻みで 30 まで下げる)
                quality = 95
                while quality >= 30:
                    if temp_path and temp_path.exists():
                        temp_path.unlink()
                    img.save(temp_path, "JPEG", optimize=True, quality=quality, subsampling=0)
                    if temp_path.stat().st_size < max_size:
                        break
                    quality -= 5
                else:
                    raise ImageValidationError("Failed to compress JPEG below 4MB even at quality 30")
            else:
                # PNG保存
                img.save(temp_path, "PNG", optimize=True, compress_level=9)
                if temp_path.stat().st_size >= max_size:
                    # 4MBを超えた場合、256色に減色して再試行
                    logger.warning("PNG size exceeds 4MB. Retrying with quantization...")
                    if temp_path and temp_path.exists():
                        temp_path.unlink()
                    quantized = img.quantize(colors=256)
                    try:
                        quantized_rgb = quantized.convert("RGB")
                        quantized_rgb.save(temp_path, "PNG", optimize=True)
                    except Exception:
                        quantized.save(temp_path, "PNG", optimize=True)
                    
                    if temp_path.stat().st_size >= max_size:
                        # 減色しても4MBを超える場合は、緊急避難的にJPEG形式で保存 (品質向上のため subsampling=0)
                        logger.warning("Quantized PNG still exceeds 4MB. Falling back to JPEG format...")
                        if temp_path and temp_path.exists():
                            temp_path.unlink()
                        img.save(temp_path, "JPEG", optimize=True, quality=80, subsampling=0)
            
            # 正常に保存されたらリネーム（リトライおよび shutil.move へのフォールバックを伴う堅牢なアトミック書き込み）
            import shutil
            success = False
            for attempt in range(5):
                try:
                    if output_path.exists():
                        output_path.unlink()
                    temp_path.rename(output_path)
                    success = True
                    break
                except OSError as e:
                    logger.warning(f"Rename attempt {attempt + 1} failed ({e}). Retrying with shutil.move...")
                    try:
                        shutil.move(str(temp_path), str(output_path))
                        success = True
                        break
                    except Exception as ex:
                        logger.error(f"shutil.move fallback failed: {ex}")
                    time.sleep(0.1)
            if not success:
                raise IOError(f"Failed to move temporary file {temp_path} to final destination {output_path}")
            
        except Exception as e:
            logger.error(f"Failed to generate premium thumbnail (size={width}x{height}, text='{text}'): {e}", exc_info=True)
            raise ImageValidationError(f"Failed to generate premium thumbnail (size={width}x{height}, text='{text}'): {e}") from e
        finally:
            if temp_path and hasattr(temp_path, "exists") and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            
        return output_path


async def resolve_thumbnail_task(agent_or_id, task_id: str = None, db_path: str = None, output_dir=None) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスクハンドラ。
    agent_or_id が StageBoundAgent インスタンスの場合と、単なる文字列 (task_id) の場合の両方に対応する。
    """
    import sqlite3
    import time
    import json
    from pathlib import Path
    
    # StageBoundAgentインスタンスかどうかの判定
    # クラス名と属性を用いて多重インポート問題（backend.agents vs agents）を回避する
    is_agent = False
    if type(agent_or_id).__name__ == "StageBoundAgent" or hasattr(agent_or_id, "stage_name"):
        is_agent = True
        
    if is_agent:
        agent = agent_or_id
        actual_task_id = task_id or getattr(agent, "current_task_id", "task_unknown")
        actual_db_path = agent.db_path
        actual_output_dir = output_dir or getattr(agent, "output_dir", None)
        width = getattr(agent, "width", 1280)
        height = getattr(agent, "height", 720)
        text = getattr(agent, "text", f"P27 THUMBNAIL: {actual_task_id}")
    else:
        actual_task_id = agent_or_id
        actual_db_path = db_path or ":memory:"
        actual_output_dir = output_dir
        width = 1280
        height = 720
        text = f"P27 THUMBNAIL: {actual_task_id}"
        
    # 出力パスの決定
    if actual_output_dir is None:
        actual_output_dir = _writable_path("temp_thumbnails")
    else:
        actual_output_dir = Path(actual_output_dir)
        
    actual_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = actual_output_dir / f"{actual_task_id}.png"
    
    try:
        # プレミアムサムネイルを生成
        PremiumThumbnailGenerator.generate(output_path, width=width, height=height, text=text)
        
        # 保存されたファイルを読み込んで検証
        with open(output_path, "rb") as f:
            img_bytes = f.read()
            
        # 品質要件の検証
        ThumbnailValidator.validate_image(img_bytes)
        
        # ロードしてサイズと容量を取得
        from PIL import Image
        with Image.open(output_path) as img:
            w_out, h_out = img.size
            size_bytes = len(img_bytes)
            
        # DBマイグレーション & 結果の保存 (接続タイムアウトを延長し、ロック競合に対して最大5回リトライを行う)
        db_retries = 5
        import asyncio
        for attempt in range(db_retries):
            try:
                conn = sqlite3.connect(actual_db_path, timeout=30.0)
                try:
                    # WALモードを有効化して同時実行安全性を高める
                    conn.execute("PRAGMA journal_mode=WAL")
                    
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS thumbnail_results (
                            task_id TEXT PRIMARY KEY,
                            path TEXT,
                            width INTEGER,
                            height INTEGER,
                            size_bytes INTEGER,
                            verified_at REAL
                        )
                    """)
                    conn.execute(
                        "INSERT OR REPLACE INTO thumbnail_results VALUES (?, ?, ?, ?, ?, ?)",
                        (actual_task_id, str(output_path), w_out, h_out, size_bytes, time.time())
                    )
                    conn.commit()
                    break
                except sqlite3.Error as de:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    raise de
                finally:
                    conn.close()
            except sqlite3.OperationalError as oe:
                if "locked" in str(oe).lower() and attempt < db_retries - 1:
                    import random
                    # 指数バックオフ + ジッター
                    sleep_time = (2 ** attempt) * 0.5 + random.random()
                    logger.warning(
                        f"Database locked in resolve_thumbnail_task (Attempt {attempt + 1}/{db_retries}). "
                        f"Retrying in {sleep_time:.2f} seconds (jittered)..."
                    )
                    await asyncio.sleep(sleep_time)
                else:
                    logger.error(f"Database operation failed in resolve_thumbnail_task for task {actual_task_id}: {oe}", exc_info=True)
                    raise
            
        result_info = {
            "task_id": actual_task_id,
            "path": str(output_path),
            "width": w_out,
            "height": h_out,
            "size_bytes": size_bytes,
            "valid": True
        }
        return json.dumps(result_info)
        
    except ImageValidationError as ve:
        logger.error(f"Image validation failed in resolve_thumbnail_task for task {actual_task_id}: {ve}", exc_info=True)
        raise
    except sqlite3.Error as de:
        logger.error(f"Database error in resolve_thumbnail_task for task {actual_task_id}: {de}", exc_info=True)
        raise
    except OSError as oe:
        logger.error(f"OS/IO error in resolve_thumbnail_task for task {actual_task_id}: {oe}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected error in resolve_thumbnail_task for task {actual_task_id}: {e}", exc_info=True)
        raise
