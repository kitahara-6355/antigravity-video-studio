import re
import os
import sys

# 2026-07-26: 以前は別ワークツリーを指す Windows 絶対パスが直書きされていた:
#   r"c:\Users\PC_User\Desktop\script\video-automation\backend\tests\e2e\..."
# Linux(CI) では存在せず os.path.exists が False を返して [] で早期リターンし、
# test_find_classes.py の7件が失敗していた（Windows では実在するため通っていた）。
# リポジトリ相対で解決する。
_REPO_ROOT = os.path.dirname(  # <repo>/
    os.path.dirname(           # <repo>/backend/
        os.path.dirname(       # <repo>/backend/tests/
            os.path.dirname(os.path.abspath(__file__))  # <repo>/backend/tests/scratch/
        )
    )
)
DEFAULT_PATH = os.path.join(
    _REPO_ROOT, "backend", "tests", "e2e", "archives", "test_e2e_browser_m36.py"
)

def find_classes_in_file(file_path: str) -> list[tuple[int, str]]:
    if not os.path.exists(file_path):
        return []
        
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    classes = []
    for i, line in enumerate(lines):
        m = re.match(r"^class\s+(\w+)", line)
        if m:
            class_name = m.group(1)
            classes.append((i + 1, class_name))
    return classes

def main():
    path = DEFAULT_PATH
    if len(sys.argv) > 1:
        path = sys.argv[1]
        
    print(f"Scanning: {path}")
    classes = find_classes_in_file(path)
    if not classes:
        print("No classes found or file does not exist.")
        return 1
        
    for line_num, name in classes:
        print(f"Line {line_num:5d}: {name}")
    return 0

if __name__ == "__main__":
    sys.exit(main())

# --- サムネイル画像生成・品質検証・StageBoundAgent連携ロジックの追加 (ローカルインポート版) ---
OUTPUT_DIR = "backend/temp_thumbnails"

def generate_find_classes_thumbnail(output_path, width=1280, height=720, text=None):
    """Pillowを使用して、クラス検出結果のサムネイル画像を生成する"""
    from PIL import Image, ImageDraw
    import uuid
    from datetime import datetime
    from pathlib import Path

    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers.")
        
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 原子的な書き込み (Atomic Write) の実装
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        img = Image.new("RGB", (width, height), color=(30, 45, 60))
        d = ImageDraw.Draw(img)
        
        if not text:
            text = f"Find Classes Report\nGenerated at: {datetime.now().isoformat()}"
            
        d.text((40, 40), text, fill=(255, 255, 255))
        img.save(temp_path, "PNG")
        
        # 正常に保存されたらリネーム
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)
    except (OSError, ValueError) as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise e
        
    return output_path

def validate_thumbnail(file_path) -> dict:
    """
    サムネイル画像の品質要件を検証する
    """
    from PIL import Image
    from pathlib import Path

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
    except (OSError, SyntaxError, IndexError, TypeError, ValueError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    # 2. 完全なピクセルデータのロードによる破損検知
    try:
        with Image.open(file_path) as img:
            img.load()  # ピクセルデータのロードを強制
            width, height = img.size
    except (OSError, SyntaxError, IndexError, TypeError, ValueError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
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

async def resolve_find_classes_task(task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理
    """
    import json
    from datetime import datetime
    from pathlib import Path

    # 規定のファイルをスキャンする
    classes = find_classes_in_file(DEFAULT_PATH)
    
    classes_str = ", ".join([name for _, name in classes])
    
    text = (
        f"=== Find Classes Report ===\n"
        f"Target File: {DEFAULT_PATH}\n"
        f"Detected Classes: {classes_str if classes_str else 'None'}\n"
        f"Timestamp: {datetime.now().isoformat()}\n"
    )
        
    output_dir_path = Path(OUTPUT_DIR)
    output_path = output_dir_path / f"{task_id}.png"
    
    generate_find_classes_thumbnail(output_path, text=text)
    result_info = validate_thumbnail(output_path)
    
    return json.dumps(result_info)
