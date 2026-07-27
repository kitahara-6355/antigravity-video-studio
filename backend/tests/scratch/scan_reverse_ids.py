import re
import uuid
import logging
from pathlib import Path
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

def _split_into_class_blocks(content: str) -> list[tuple[str, str]]:
    """コンテンツをクラス名とクラス定義ブロックのタプルリストに分割する"""
    class_blocks = []
    current_class = None
    current_block = []

    for line in content.splitlines():
        class_match = re.match(r"^\s*class\s+(\w+)", line)
        if class_match:
            if current_class:
                class_blocks.append((current_class, "\n".join(current_block)))
            current_class = class_match.group(1)
            current_block = [line]
        elif current_class:
            current_block.append(line)

    if current_class:
        class_blocks.append((current_class, "\n".join(current_block)))
    return class_blocks

def _extract_stories_from_block(block: str) -> tuple[list[str], int]:
    """クラスブロックから逆引きIDパターンを検索し、テーマIDプレフィックス（ユニークリスト）と総出現数を抽出する"""
    # 逆引きID（O2-L1-01やA4-L2-01等）を検索し、テーマID（O2やA4）を抽出
    matched_ids = re.findall(r'\b([OA]\d+)-L\d+-\d+', block)
    unique_story_ids = sorted(set(matched_ids))
    return unique_story_ids, len(matched_ids)

def scan_content_for_reverse_ids(content: str):
    """コンテンツ内のクラスごとに逆引きIDを抽出する"""
    class_blocks = _split_into_class_blocks(content)
    results = []
    for class_name, block in class_blocks:
        unique_story_ids, count = _extract_stories_from_block(block)
        results.append((class_name, unique_story_ids, count))
    return results

def scan_file_for_reverse_ids(file_path: Path):
    """指定されたファイルを読み込み、逆引きIDを抽出する"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return scan_content_for_reverse_ids(content)
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return []

# --- サムネイル生成・品質検証・タスク連携ロジックの追加 ---

def generate_thumbnail(
    output_path,
    width: int = 1280,
    height: int = 720,
    text: str = "Thumbnail"
):
    """Pillowを使用して、指定された解像度とテキストでサムネイル画像を生成する"""
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
        with Image.new("RGB", (width, height), color=(73, 109, 137)) as img:
            d = ImageDraw.Draw(img)
            d.text((10, 10), text, fill=(255, 255, 0))
            img.save(temp_path, "PNG")
        
        # 正常に保存されたらリネーム
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)
    except Exception as e:
        logger.error(f"Failed to generate thumbnail atomically: {e}")
        raise
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        
    return output_path

def validate_thumbnail(file_path) -> dict:
    """
    サムネイル画像の品質要件を検証する
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Target path is not a file: {file_path}")
        
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

async def resolve_thumbnail_task(self, task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理
    """
    import json
    output_dir = Path(getattr(self, "output_dir", None) or "backend/temp_thumbnails")
    output_path = output_dir / f"{task_id}.png"
    
    width = getattr(self, "width", 1280)
    height = getattr(self, "height", 720)
    text = getattr(self, "text", "Thumbnail")
    
    try:
        generate_thumbnail(output_path, width=width, height=height, text=text)
        result_info = validate_thumbnail(output_path)
        return json.dumps(result_info)
    except Exception as e:
        logger.error(f"Failed to resolve thumbnail task {task_id}: {e}", exc_info=True)
        return json.dumps({"error": str(e), "task_id": task_id})

if __name__ == "__main__":
    # スクリプト自身の位置からの相対パスで解析対象ファイルを探索する
    target_path = Path(__file__).parent.parent / "e2e" / "archives" / "test_e2e_browser_m36.py"
    if target_path.exists():
        results = scan_file_for_reverse_ids(target_path)
        print(f"Total classes found: {len(results)}")
        for class_name, unique_story_ids, count in results:
            if unique_story_ids:
                print(f"{class_name:35s}: Stories {unique_story_ids} (ID Count: {count})")
            else:
                print(f"{class_name:35s}: No formal reverse IDs found")
    else:
        print(f"Target path not found: {target_path}")
