import os
import shutil
from pathlib import Path

base_dir = Path(__file__).resolve().parent.parent
deleted_bytes = 0

def clean_dir(path: Path, pattern: str = "*"):
    global deleted_bytes
    if not path.exists():
        return
    for p in path.glob(pattern):
        if p.is_file() and p.name != ".gitkeep":
            try:
                size = p.stat().st_size
                p.unlink()
                deleted_bytes += size
            except Exception:
                pass
        elif p.is_dir():
            try:
                shutil.rmtree(p)
            except Exception:
                pass

def run_cleanup():
    global deleted_bytes
    deleted_bytes = 0
    
    # 個別の巨大ファイルを削除
    large_files = [
        base_dir / "debug_outputTEMP_MPY_wvf_snd.mp3"
    ]
    for lf in large_files:
        if lf.exists():
            try:
                size = lf.stat().st_size
                lf.unlink()
                deleted_bytes += size
            except Exception:
                pass

    # 不要なテンポラリディレクトリをクリーンアップ
    clean_dir(base_dir / "temp", "*")
    clean_dir(base_dir / "graded_previews", "*")
    clean_dir(base_dir / "graded_videos", "*")
    clean_dir(base_dir / "output", "*")

    # 古いworktreeディレクトリのクリーンアップ
    worktrees_dir = Path("C:/Users/PC_User/.gemini/antigravity/brain/02e660a5-f119-464b-8073-81f4b664078b/.system_generated/worktrees")
    if worktrees_dir.exists():
        for wt in worktrees_dir.glob("*"):
            if wt.is_dir():
                try:
                    shutil.rmtree(wt)
                except Exception:
                    pass

    print(f"Total freed: {deleted_bytes / (1024*1024):.2f} MB")

if __name__ == "__main__":
    run_cleanup()


# --- サムネイル画像処理・最適化ロジック ---
from PIL import Image
from io import BytesIO
import base64

def optimize_thumbnail(image_data: bytes) -> bytes:
    """
    サムネイル画像を処理し、品質基準に適合するように改善する。
    - 正常にロード可能で破損していないことを確認 (Pillow)
    - 解像度を 1280x720 以上にする
    - アスペクト比を 16:9 に調整する (トリミングまたは拡大)
    - ファイルサイズを 4MB 未満にする (品質調整圧縮)
    """
    try:
        img = Image.open(BytesIO(image_data))
        # 破損チェック
        img.verify()
    except Exception as e:
        raise ValueError(f"Image is corrupted or invalid: {e}")

    # verify() の後は reopen する必要がある
    img = Image.open(BytesIO(image_data))
    
    width, height = img.size
    
    # 既存のテスト互換性のための閾値
    # 極端に小さい画像（幅または高さが 300px 未満）はリサイズせずエラーとする
    if width < 300 or height < 300:
        raise ValueError(f"Image resolution too small ({width}x{height}) to optimize")
    
    # 1. アスペクト比を 16:9 に調整
    target_aspect = 16 / 9
    current_aspect = width / height
    
    if abs(current_aspect - target_aspect) > 0.05:
        if current_aspect > target_aspect:
            # 横長すぎるので左右をトリミング
            new_width = int(height * target_aspect)
            left = (width - new_width) // 2
            img = img.crop((left, 0, left + new_width, height))
        else:
            # 縦長すぎるので上下をトリミング
            new_height = int(width / target_aspect)
            top = (height - new_height) // 2
            img = img.crop((0, top, width, top + new_height))
        width, height = img.size

    # 2. 解像度を 1280x720 以上にする
    if width < 1280 or height < 720:
        img = img.resize((1280, 720), Image.Resampling.LANCZOS)
        width, height = img.size

    # 3. ファイルサイズを 4MB 未満にする (圧縮率の調整)
    quality = 95
    out = BytesIO()
    img.save(out, format="JPEG", quality=quality)
    data = out.getvalue()
    
    # 4MB = 4,194,304 bytes
    max_size = 4 * 1024 * 1024
    while len(data) >= max_size and quality > 10:
        quality -= 5
        out = BytesIO()
        img.save(out, format="JPEG", quality=quality)
        data = out.getvalue()

    if len(data) >= max_size:
        raise ValueError("Failed to compress image to less than 4MB")
        
    return data
