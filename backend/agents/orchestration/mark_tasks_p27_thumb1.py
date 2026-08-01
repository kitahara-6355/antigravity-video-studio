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
import numpy as np

sys.path.insert(0, '.')
sys.path.insert(0, './backend')
from backend.agents.orchestration import OrchestrationHub
from backend.agents.stage_bound_agent import StageBoundAgent
from backend.usage_tracker.alert_system import emit_warning, emit_critical

def verify_thumbnail_quality(file_path_or_bytes) -> dict:
    """
    サムネイル画像の品質要件を検証する。
    - 解像度: 1280x720 以上
    - アスペクト比: 16:9
    - ファイルサイズ: 4MB 未満
    - 破損チェック: Pillowで正常にロード可能
    """
    if not isinstance(file_path_or_bytes, (bytes, str, Path)):
        msg = f"Invalid argument type: {type(file_path_or_bytes)}. Expected bytes, str, or Path."
        emit_warning("thumbnail", msg)
        raise TypeError(msg)

    if isinstance(file_path_or_bytes, bytes):
        import io
        img_data = file_path_or_bytes
        size_bytes = len(img_data)
        try:
            with Image.open(io.BytesIO(img_data)) as img:
                img.load()
                width, height = img.size
        except (PIL.UnidentifiedImageError, ValueError, TypeError, OSError) as e:
            emit_warning("thumbnail", f"Corrupted image bytes: {e}")
            raise ValueError(f"Image is corrupted or invalid format: {e}")
    else:
        try:
            path = Path(file_path_or_bytes)
        except (TypeError, ValueError) as e:
            msg = f"Invalid file path structure: {e}"
            emit_warning("thumbnail", msg)
            raise TypeError(msg)
            
        if not path.exists():
            emit_warning("thumbnail", f"File not found: {path}")
            raise FileNotFoundError(f"Thumbnail file not found: {path}")
        size_bytes = path.stat().st_size
        try:
            with Image.open(path) as img:
                img.load()
                width, height = img.size
        except (PIL.UnidentifiedImageError, ValueError, TypeError, OSError) as e:
            emit_warning("thumbnail", f"Corrupted image file: {e}")
            raise ValueError(f"Image is corrupted or invalid format: {e}")

    if size_bytes >= 4 * 1024 * 1024:
        msg = f"File size exceeds 4MB limit: {size_bytes} bytes"
        emit_warning("thumbnail", msg)
        raise ValueError(msg)

    if height <= 0:
        msg = f"Invalid image height: {height}"
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
    対角線上の3色線形グラデーションや、幾何学的オーバーレイによるプレミアム品質画像を生成する。
    """
    try:
        output_dir = _writable_path("temp_thumbnails")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{task_id}.png"
        
        width, height = 1280, 720
        img = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img)
        
        # 1. 对角線上の3色グラデーション背景 (ディープブルー -> ネオンパープル -> マゼンタ)
        color1 = (10, 20, 50)     # ディープブルー
        color2 = (90, 20, 150)    # ネオンパープル
        color3 = (180, 20, 120)   # マゼンタ
        
        # 対角線上の3色グラデーション背景を numpy で高速生成
        xv, yv = np.meshgrid(np.linspace(0.0, 1.0, width), np.linspace(0.0, 1.0, height))
        t = (xv + yv) / 2.0
        
        r_arr = np.zeros((height, width), dtype=np.uint8)
        g_arr = np.zeros((height, width), dtype=np.uint8)
        b_arr = np.zeros((height, width), dtype=np.uint8)
        
        mask1 = t < 0.5
        mask2 = ~mask1
        
        lt1 = t * 2.0
        r_arr[mask1] = (color1[0] * (1.0 - lt1[mask1]) + color2[0] * lt1[mask1]).astype(np.uint8)
        g_arr[mask1] = (color1[1] * (1.0 - lt1[mask1]) + color2[1] * lt1[mask1]).astype(np.uint8)
        b_arr[mask1] = (color1[2] * (1.0 - lt1[mask1]) + color2[2] * lt1[mask1]).astype(np.uint8)
        
        lt2 = (t - 0.5) * 2.0
        r_arr[mask2] = (color2[0] * (1.0 - lt2[mask2]) + color3[0] * lt2[mask2]).astype(np.uint8)
        g_arr[mask2] = (color2[1] * (1.0 - lt2[mask2]) + color3[1] * lt2[mask2]).astype(np.uint8)
        b_arr[mask2] = (color2[2] * (1.0 - lt2[mask2]) + color3[2] * lt2[mask2]).astype(np.uint8)
        
        img_array = np.stack([r_arr, g_arr, b_arr], axis=-1)
        img = Image.fromarray(img_array, mode="RGB")
                
        # 2. 幾何学的グリッドパターンのオーバーレイ
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        
        # 斜め格子グリッド
        grid_spacing = 80
        for offset in range(-height, width + height, grid_spacing):
            overlay_draw.line([(offset, 0), (offset + height, height)], fill=(255, 255, 255, 12), width=1)
            overlay_draw.line([(offset, height), (offset + height, 0)], fill=(255, 255, 255, 12), width=1)
            
        # 3. フォントの読み込みとテキスト配置
        font = None
        font_paths = [
            "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\msgothic.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc"
        ]
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    font = ImageFont.truetype(fp, 44)
                    break
                except (OSError, RuntimeError):
                    pass
        if font is None:
            font = ImageFont.load_default()
            
        text = f"P27 THUMBNAIL: {task_id}"
        
        # テキストサイズ取得 (Pillow 8.0.0 以降の標準 API textbbox を使用)
        bbox = overlay_draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
            
        x = (width - text_width) // 2
        y = (height - text_height) // 2
        
        # 4. ネオングラスモルフィズム风カードの描画
        rect_padding_w = 70
        rect_padding_h = 45
        rect_x1 = x - rect_padding_w
        rect_y1 = y - rect_padding_h
        rect_x2 = x + text_width + rect_padding_w
        rect_y2 = y + text_height + rect_padding_h
        
        # 白い半透明 of 角丸長方形 (ガラス背景)
        overlay_draw.rounded_rectangle(
            [rect_x1, rect_y1, rect_x2, rect_y2],
            radius=25,
            fill=(255, 255, 255, 22),
            outline=(255, 255, 255, 90),
            width=3
        )
        
        # 外側のソフトなハイライト枠
        overlay_draw.rounded_rectangle(
            [rect_x1 - 3, rect_y1 - 3, rect_x2 + 3, rect_y2 + 3],
            radius=28,
            fill=None,
            outline=(255, 255, 255, 35),
            width=1
        )
        
        # テキストのドロップシャドウ
        overlay_draw.text((x + 3, y + 3), text, fill=(0, 0, 0, 160), font=font)
        # メインテキスト (ゴールド)
        overlay_draw.text((x, y), text, fill=(255, 215, 0, 255), font=font)
        
        # グラデーション背景画像とオーバーレイを合成
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        
        # PNG保存 (ファイルサイズ最適化)
        img.save(output_path, "PNG", optimize=True)

        # 品質要件の検証
        result_info = verify_thumbnail_quality(output_path)
        
        # DBマイグレーションと結果保存
        conn = None
        try:
            conn = sqlite3.connect(db_path)
            with conn:
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
        except sqlite3.Error:
            raise
        finally:
            if conn is not None:
                conn.close()

        return json.dumps(result_info)
    except (ValueError, TypeError, FileNotFoundError, OSError, sqlite3.Error) as e:
        emit_critical("thumbnail", f"Thumbnail task failed for task {task_id}: {e}")
        raise

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("a9736a64-a242-485f-942e-bf8476d21fa6")
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # thumbnail-001 完了マーク
    hub.mark_task_done("T-batch_214e16-thumbnail-001", "pass", {
        "message": "harness/evaluator_optimizer.py のサムネイル処理改善と品質検証・テスト追加。",
        "changed_files": [
            "backend/harness/evaluator_optimizer.py",
            "tests/test_evaluator_optimizer.py"
        ]
    })
    
    print("TASK_MARKED_DONE")

    # 最新ステータス表示
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

if __name__ == "__main__":
    main()
