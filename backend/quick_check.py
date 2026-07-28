import subprocess
import os
from pathlib import Path

from path_resolver import brain_dir, project_root

BASE_DIR = project_root()
RAW_DIR = BASE_DIR / "raw_videos" / "AI Studio アップロード用動画"
# 出力先は特定の会話 UUID 配下。UUID 自体は当時の会話のもので他マシンには無いが、
# 親（brain/）を解決に通しておけば ANTIGRAVITY_APP_DATA_DIR で丸ごと差し替えられる。
OUT_DIR = brain_dir() / "638e528a-ad1b-4885-ad73-5d9f60dc2799"
TELOP_DIR = BASE_DIR / "backend" / "temp" / "final_build"

# Windows用のパスエスケープ関数
def fPath(p):
    return str(p).replace("\\", "/").replace(":", "\\\\:")

def run_segment(name, input_file, start, duration, crop, srt=None, telop_idx=0):
    output = TELOP_DIR / f"check_{name}.mp4"
    sub_filter = f",subtitles='{fPath(srt)}'" if srt else ""
    telop_path = TELOP_DIR / f"brand_telop_{telop_idx}.png"
    
    # 1280x720に統一し、字幕とロゴを入れる
    vf = f"crop={crop},scale=1280:720,format=yuv420p{sub_filter},movie='{fPath(telop_path)}'[logo];[in][logo]overlay=15:15"
    
    cmd = [
        "ffmpeg", "-y", "-ss", str(start), "-t", str(duration),
        "-i", str(input_file),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-c:a", "copy",
        str(output)
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    TELOP_DIR.mkdir(parents=True, exist_ok=True)
    # 01: 30分, 02: 54s, 03: 7分, 04: 5.5分
    procs = [
        run_segment("scene01", RAW_DIR / "シーン01_前編.mp4", 0, 10, "1152:720:26:0", RAW_DIR / "シーン01_前編_whisper_semantic.srt", 0),
        run_segment("scene02", RAW_DIR / "シーン02_ゲスト書道.mp4", 0, 10, "1920:960:0:60", None, 3),
        run_segment("scene03", RAW_DIR / "シーン03_後編01.mp4", 0, 10, "1136:640:28:40", RAW_DIR / "シーン03_後編01_whisper_semantic.srt", 4),
        run_segment("scene04", RAW_DIR / "シーン04_後編02.mp4", 0, 10, "1136:640:26:40", RAW_DIR / "シーン04_後編02_whisper_semantic.srt", 6)
    ]
    for p in procs: p.wait()
    print("DONE_CHECKPOINTS")

if __name__ == "__main__":
    main()


# ============================================================
# サムネイル生成・品質検証ロジック
# ============================================================

def generate_quick_check_thumbnail(
    output_path,
    width: int = 1280,
    height: int = 720,
    text: str = "Quick Check"
):
    """Pillowを使用して、指定された解像度とテキストでサムネイル画像を生成する"""
    from PIL import Image, ImageDraw
    import uuid
    from pathlib import Path
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")
        
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 原子的な書き込み (Atomic Write) の実装
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        img = Image.new("RGB", (width, height), color=(50, 150, 50))
        d = ImageDraw.Draw(img)
        d.text((10, 10), text, fill=(255, 255, 255))
        img.save(temp_path, "PNG")
        
        # 正常に保存されたらリネーム
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)
    except Exception as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise e
    return output_path

def validate_quick_check_thumbnail(file_path) -> dict:
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
    except Exception as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    # 2. 完全なピクセルデータのロードによる破損検知
    try:
        with Image.open(file_path) as img:
            img.load()  # ピクセルデータのロードを強制
            width, height = img.size
    except Exception as e:
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

async def resolve_quick_check_thumbnail_task(task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理
    """
    import json
    from pathlib import Path
    output_dir = BASE_DIR / "backend" / "temp_thumbnails"
    output_path = output_dir / f"{task_id}.png"
    
    generate_quick_check_thumbnail(output_path, width=1280, height=720, text="Quick Check")
    result_info = validate_quick_check_thumbnail(output_path)
    return json.dumps(result_info)
