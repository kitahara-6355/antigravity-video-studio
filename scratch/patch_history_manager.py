import re

def main():
    file_path = "backend/branding/history_manager.py"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. ThumbnailValidatorのバイナリ解析部分の置換
    target_validator = """        # 2. 自前バイナリ解析（フォールバック）
        try:
            # PNG 判定
            if image_bytes.startswith(b'\\x89PNG\\r\\n\\x1a\\n'):
                if len(image_bytes) >= 24:
                    w, h = struct.unpack('>II', image_bytes[16:24])
                    return (w, h), None
                raise ImageValidationError("Image quality check failed: invalid PNG format (missing header data)")

            # JPEG 判定
            if image_bytes.startswith(b'\\xff\\xd8'):
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
            
            raise ImageValidationError("Image quality check failed: Unsupported image format (only JPEG and PNG are supported)")"""

    replacement_validator = """        # 2. 自前バイナリ解析（フォールバック）
        try:
            # PNG 判定
            if image_bytes.startswith(b'\\x89PNG\\r\\n\\x1a\\n'):
                if len(image_bytes) < 24:
                    raise ImageValidationError("Image quality check failed: invalid PNG format (missing header data)")
                # PNGの末尾にIENDが含まれているか確認（簡易破損チェック）
                if b'IEND' not in image_bytes[-12:]:
                    raise ImageValidationError("Image quality check failed: PNG image is corrupted (missing IEND chunk at end)")
                w, h = struct.unpack('>II', image_bytes[16:24])
                return (w, h), None

            # JPEG 判定
            if image_bytes.startswith(b'\\xff\\xd8'):
                if len(image_bytes) < 10:
                    raise ImageValidationError("Image quality check failed: JPEG image is too short")
                # JPEGの末尾にEOIマーカー（\\xff\\xd9）が含まれているか確認（簡易破損チェック）
                if not image_bytes.endswith(b'\\xff\\xd9') and b'\\xff\\xd9' not in image_bytes[-4:]:
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
            
            raise ImageValidationError("Image quality check failed: Unsupported image format (only JPEG and PNG are supported)")"""

    # 2. PremiumThumbnailGeneratorのグラデーションの置換
    target_gradient = """            # 1. 3色グラデーション背景
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
                r = np.where(mask, c1[0] + (c2[0] - c1[0]) * t, c2[0] + (c3[0] - c2[0]) * t)
                g = np.where(mask, c1[1] + (c2[1] - c1[1]) * t, c2[1] + (c3[1] - c2[1]) * t)
                b = np.where(mask, c1[2] + (c2[2] - c1[2]) * t, c2[2] + (c3[2] - c2[2]) * t)
                
                # ディザーノイズでバンディング対策
                dither = np.random.uniform(-0.5, 0.5, (h_draw, w_draw, 3))
                rgb = np.clip(np.stack([r, g, b], axis=-1) + dither, 0, 255).astype(np.uint8)
                img = Image.fromarray(rgb)
            except ImportError:
                import random
                # NumPyがない場合のフォールバック: 1024x1024のサイズで高精細なグラデーションを作成し、LANCZOSで拡大して画質を最大化
                grad_size = 1024
                grad_line = Image.new("RGB", (grad_size, 1))
                half_size = grad_size // 2
                for x in range(half_size):
                    t = x / (half_size - 1)
                    r = int(color1[0] * (1 - t) + color2[0] * t)
                    g = int(color1[1] * (1 - t) + color2[1] * t)
                    b = int(color1[2] * (1 - t) + color2[2] * t)
                    grad_line.putpixel((x, 0), (r, g, b))
                for x in range(half_size):
                    t = x / (half_size - 1)
                    r = int(color2[0] * (1 - t) + color3[0] * t)
                    g = int(color2[1] * (1 - t) + color3[2] * t)
                    grad_line.putpixel((half_size + x, 0), (r, g, b))
                
                grad_2d = Image.new("RGB", (grad_size, grad_size))
                for y in range(grad_size):
                    for x in range(grad_size):
                        idx = int((x + y) / (2 * grad_size - 2) * (grad_size - 1))
                        r, g, b = grad_line.getpixel((idx, 0))
                        dither = random.randint(-1, 1)
                        rn = min(255, max(0, r + dither))
                        gn = min(255, max(0, g + dither))
                        bn = min(255, max(0, b + dither))
                        grad_2d.putpixel((x, y), (rn, gn, bn))
                img = grad_2d.resize((w_draw, h_draw), Image.Resampling.LANCZOS)"""

    replacement_gradient = """            # 1. 3色グラデーション背景
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
                img = grad_2d.resize((w_draw, h_draw), Image.Resampling.LANCZOS)"""

    # 3. PremiumThumbnailGeneratorのフォントサイズ＆高さ制限
    target_font_limit = """            # 最大文字幅制限 (画像幅の80%)
            max_allowed_width = int(w_draw * 0.8)
            font_size = 46 * scale  # 初期フォントサイズ"""

    replacement_font_limit = """            # 最大文字幅制限 (画像幅の80%) と最大高さ制限 (画像高の65%)
            max_allowed_width = int(w_draw * 0.8)
            max_allowed_height = int(h_draw * 0.65)
            font_size = 48 * scale  # 初期フォントサイズをやや高めて品質とインパクトを優先"""

    target_break_cond = """                if max_w <= max_allowed_width and total_h <= int(h_draw * 0.7):
                    text_width = max_w
                    text_height = total_h
                    break"""

    replacement_break_cond = """                if max_w <= max_allowed_width and total_h <= max_allowed_height:
                    text_width = max_w
                    text_height = total_h
                    break"""

    # 4. resolve_thumbnail_taskのDBリトライ
    target_db_retry = """        # DBマイグレーション & 結果の保存 (接続タイムアウトを延長し、ロック競合に対して最大3回リトライを行う)
        db_retries = 3
        import asyncio
        for attempt in range(db_retries):
            try:
                conn = sqlite3.connect(actual_db_path, timeout=30.0)
                try:
                    # WALモードを有効化して同時実行安全性を高める
                    conn.execute("PRAGMA journal_mode=WAL")
                    
                    conn.execute(\"\"\"
                        CREATE TABLE IF NOT EXISTS thumbnail_results (
                            task_id TEXT PRIMARY KEY,
                            path TEXT,
                            width INTEGER,
                            height INTEGER,
                            size_bytes INTEGER,
                            verified_at REAL
                        )
                    \"\"\")
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
                    sleep_time = 0.5 + random.random()
                    logger.warning(
                        f"Database locked in resolve_thumbnail_task (Attempt {attempt + 1}/{db_retries}). "
                        f"Retrying in {sleep_time:.2f} seconds (jittered)..."
                    )
                    await asyncio.sleep(sleep_time)
                else:
                    logger.error(f"Database operation failed in resolve_thumbnail_task for task {actual_task_id}: {oe}", exc_info=True)
                    raise"""

    replacement_db_retry = """        # DBマイグレーション & 結果の保存 (接続タイムアウトを延長し、ロック競合に対して最大5回リトライを行う)
        db_retries = 5
        import asyncio
        for attempt in range(db_retries):
            try:
                conn = sqlite3.connect(actual_db_path, timeout=30.0)
                try:
                    # WALモードを有効化して同時実行安全性を高める
                    conn.execute("PRAGMA journal_mode=WAL")
                    
                    conn.execute(\"\"\"
                        CREATE TABLE IF NOT EXISTS thumbnail_results (
                            task_id TEXT PRIMARY KEY,
                            path TEXT,
                            width INTEGER,
                            height INTEGER,
                            size_bytes INTEGER,
                            verified_at REAL
                        )
                    \"\"\")
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
                    raise"""

    # 各パートの置換
    if target_validator in content:
        content = content.replace(target_validator, replacement_validator)
        print("Replaced: Validator")
    else:
        print("Warning: target_validator not found")

    if target_gradient in content:
        content = content.replace(target_gradient, replacement_gradient)
        print("Replaced: Gradient")
    else:
        print("Warning: target_gradient not found")

    if target_font_limit in content:
        content = content.replace(target_font_limit, replacement_font_limit)
        print("Replaced: Font Limit")
    else:
        print("Warning: target_font_limit not found")

    if target_break_cond in content:
        content = content.replace(target_break_cond, replacement_break_cond)
        print("Replaced: Break Condition")
    else:
        print("Warning: target_break_cond not found")

    if target_db_retry in content:
        content = content.replace(target_db_retry, replacement_db_retry)
        print("Replaced: DB Retry")
    else:
        print("Warning: target_db_retry not found")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == '__main__':
    main()
