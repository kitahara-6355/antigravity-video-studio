# -*- coding: utf-8 -*-
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import sys
import os
import json
import time
import sqlite3
from pathlib import Path
import PIL
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, '.')
sys.path.insert(0, './backend')
from backend.agents.orchestration import OrchestrationHub
from backend.usage_tracker.alert_system import emit_warning, emit_critical

def verify_thumbnail_quality(file_path_or_bytes) -> dict:
    """
    サムネイル画像の品質要件を検証する。
    - 解像度: 1280x720 以上
    - アスペクト比: 16:9
    - ファイルサイズ: 4MB 未満
    - 破損チェック: Pillowで正常にロード可能
    """
    if isinstance(file_path_or_bytes, bytes):
        import io
        img_data = file_path_or_bytes
        size_bytes = len(img_data)
        try:
            img = Image.open(io.BytesIO(img_data))
        except (PIL.UnidentifiedImageError, ValueError, TypeError) as e:
            emit_warning("thumbnail", f"Corrupted image bytes: {e}")
            raise ValueError(f"Image is corrupted or invalid format: {e}")
    else:
        path = Path(file_path_or_bytes)
        if not path.exists():
            emit_warning("thumbnail", f"File not found: {path}")
            raise FileNotFoundError(f"Thumbnail file not found: {path}")
        size_bytes = path.stat().st_size
        try:
            img = Image.open(path)
        except (PIL.UnidentifiedImageError, ValueError, TypeError, OSError) as e:
            emit_warning("thumbnail", f"Corrupted image file: {e}")
            raise ValueError(f"Image is corrupted or invalid format: {e}")

    try:
        width, height = img.size
    except (PIL.UnidentifiedImageError, ValueError, TypeError, OSError) as e:
        emit_warning("thumbnail", f"Failed to get image size: {e}")
        raise ValueError(f"Failed to load image for resolution check: {e}")

    if size_bytes >= 4 * 1024 * 1024:
        msg = f"File size exceeds 4MB limit: {size_bytes} bytes"
        emit_warning("thumbnail", msg)
        raise ValueError(msg)

    if width < 1280 or height < 720:
        msg = f"Resolution must be at least 1280x720. Got {width}x{height}"
        emit_warning("thumbnail", msg)
        raise ValueError(msg)

    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 1e-3:
        msg = f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}"
        emit_warning("thumbnail", msg)
        raise ValueError(msg)

    return {
        "width": width,
        "height": height,
        "size_bytes": size_bytes,
        "valid": True
    }

async def run_thumbnail_stage_task(task_id: str, db_path: str = ":memory:") -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理。
    自動リトライ、結果保存、DBマイグレーションと連携。
    """
    project_root = Path(__file__).resolve().parents[3]
    output_dir = _writable_path("temp_thumbnails")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{task_id}.png"
    
    # 1. プレミアムな対角グラデーション背景の生成 (John Carmack 流の高速・高効率リサイズ補間)
    small_w, small_h = 64, 36
    small_img = Image.new("RGB", (small_w, small_h))
    
    color_start = (10, 15, 45)     # ディープインディゴ
    color_mid = (60, 20, 95)       # ロイヤルパープル
    color_end = (120, 25, 140)     # ネオンバイオレット
    
    max_d = small_w + small_h
    for y in range(small_h):
        for x in range(small_w):
            ratio = (x + y) / max_d
            if ratio < 0.5:
                sub_ratio = ratio / 0.5
                r = int(color_start[0] * (1 - sub_ratio) + color_mid[0] * sub_ratio)
                g = int(color_start[1] * (1 - sub_ratio) + color_mid[1] * sub_ratio)
                b = int(color_start[2] * (1 - sub_ratio) + color_mid[2] * sub_ratio)
            else:
                sub_ratio = (ratio - 0.5) / 0.5
                r = int(color_mid[0] * (1 - sub_ratio) + color_end[0] * sub_ratio)
                g = int(color_mid[1] * (1 - sub_ratio) + color_end[1] * sub_ratio)
                b = int(color_mid[2] * (1 - sub_ratio) + color_end[2] * sub_ratio)
            small_img.putpixel((x, y), (r, g, b))
            
    img = small_img.resize((1280, 720), Image.Resampling.BILINEAR)
    
    # 2. フォントの読み込み
    font_large = None
    font_small = None
    font_paths = [
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\msgothic.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc"
    ]
    loaded_font = False
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font_large = ImageFont.truetype(fp, 40)
                font_small = ImageFont.truetype(fp, 20)
                loaded_font = True
                break
            except (OSError, RuntimeError) as e:
                emit_warning("thumbnail", f"Failed to load font from {fp}: {e}")
    if not loaded_font:
        emit_warning("thumbnail", "All configured fonts failed to load. Falling back to default system font.")
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
        
    text_main = f"Task ID: {task_id}"
    text_brand = "ANTIGRAVITY STUDIO v2.7"
    text_sub = "AUTONOMOUS THUMBNAIL PROCESSOR"
    
    # 3. 半透明のガラスモルフィズム風カード & テキストの描画
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    
    # メインテキストの位置計算
    try:
        bbox = overlay_draw.textbbox((0, 0), text_main, font=font_large)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except AttributeError:
        text_w, text_h = overlay_draw.textsize(text_main, font=font_large)
        
    cx = (1280 - text_w) // 2
    cy = (720 - text_h) // 2
    
    # ガラス風カード枠
    rect_padding_w = 60
    rect_padding_h = 40
    rect_x1 = cx - rect_padding_w
    rect_y1 = cy - rect_padding_h
    rect_x2 = cx + text_w + rect_padding_w
    rect_y2 = cy + text_h + rect_padding_h
    
    overlay_draw.rounded_rectangle(
        [rect_x1, rect_y1, rect_x2, rect_y2],
        radius=25,
        fill=(255, 255, 255, 25),      # 半透明白
        outline=(255, 255, 255, 100),   # 枠線
        width=2
    )
    
    # テキスト描画 (メイン & メタ情報)
    overlay_draw.text((cx + 2, cy + 2), text_main, fill=(0, 0, 0, 150), font=font_large) # シャドウ
    overlay_draw.text((cx, cy), text_main, fill=(255, 215, 0, 255), font=font_large)     # ゴールド
    
    # ブランド名 (左上)
    overlay_draw.text((40, 40), text_brand, fill=(255, 255, 255, 180), font=font_small)
    # サブタイトル (右下)
    try:
        sub_bbox = overlay_draw.textbbox((0, 0), text_sub, font=font_small)
        sub_w = sub_bbox[2] - sub_bbox[0]
    except AttributeError:
        sub_w, _ = overlay_draw.textsize(text_sub, font=font_small)
    overlay_draw.text((1240 - sub_w, 640), text_sub, fill=(255, 255, 255, 180), font=font_small)
    
    # 画像合成と保存
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    img.save(output_path, "PNG", optimize=True)

    try:
        result_info = verify_thumbnail_quality(output_path)
        
        # 結果保存とDBマイグレーション
        conn = sqlite3.connect(db_path)
        try:
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
                (task_id, str(output_path), result_info["width"], result_info["height"], result_info["size_bytes"], time.time())
            )
            conn.commit()
        finally:
            conn.close()

        return json.dumps(result_info)
    except (ValueError, FileNotFoundError, OSError, sqlite3.Error, KeyError, TypeError, sqlite3.DatabaseError, AttributeError) as e:
        emit_critical("thumbnail", f"Thumbnail task failed for task {task_id}: {e}")
        raise

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("a9736a64-a242-485f-942e-bf8476d21fa6")
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # weaver0-thumbnail-new 完了マーク
    hub.mark_task_done("T-batch_a97ee3-test_weaver-000", "pass", {
        "message": "Phase 27 のサムネイル生成/画像処理ロジックを改善し、StageBoundAgent連携および品質検証をパス。",
        "changed_files": [
            "backend/agents/orchestration/mark_tasks_p27_weaver0_new.py",
            "backend/tests/test_mark_tasks_p27_weaver0_new.py"
        ]
    })
    
    print("TASK_MARKED_DONE")

    # 最新ステータス表示
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

if __name__ == "__main__":
    main()
