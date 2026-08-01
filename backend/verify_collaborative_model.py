try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import json
import uuid
from pathlib import Path
from PIL import Image, ImageDraw, UnidentifiedImageError
from branding_manager import branding_manager
import pytest

def _adjust_resolution_and_aspect_ratio(width: int, height: int) -> tuple[int, int]:
    """
    解像度とアスペクト比を16:9（1280x720以上）に自動補正する。
    """
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")
        
    # 1. 解像度の自動補正 (1280x720以上)
    if width < 1280 or height < 720:
        aspect_ratio = width / height
        if aspect_ratio >= 16.0 / 9.0:
            height = 720
            width = int(height * aspect_ratio)
        else:
            width = 1280
            height = int(width / aspect_ratio)

    # 2. アスペクト比の自動補正 (16:9)
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        if aspect_ratio > target_ratio:
            height = int(width * 9 / 16)
        else:
            width = int(height * 16 / 9)
            
    return width, height

def _draw_gradient_background(img: Image.Image, text: str) -> None:
    """
    背景グラデーションによる美しいベースデザインの生成 (NHK/YouTuber基準) とテキストの描画。
    """
    width, height = img.size
    draw = ImageDraw.Draw(img)
    for y in range(height):
        r = int(30 - (20 * y / height))
        g = int(120 - (60 * y / height))
        b = int(80 - (40 * y / height))
        draw.line([(0, y), (width, y)], fill=(r, g, b))
        
    draw.text((100, height // 2 - 20), text, fill=(255, 255, 255))

def _save_and_compress_image(img: Image.Image, temp_path: Path) -> None:
    """
    画像をPNGで保存し、ファイルサイズが4MB以上の場合はJPEG変換やリサイズで自動圧縮する。
    """
    img.save(temp_path, "PNG")
    size_bytes = temp_path.stat().st_size
    
    # 4MB制限の自動圧縮
    if size_bytes >= 4 * 1024 * 1024:
        for quality in [95, 85, 70, 50, 30]:
            img.save(temp_path, "JPEG", quality=quality)
            if temp_path.stat().st_size < 4 * 1024 * 1024:
                break
        else:
            scaled_img = img.resize((1280, 720), Image.Resampling.LANCZOS)
            scaled_img.save(temp_path, "JPEG", quality=30)
            if temp_path.stat().st_size >= 4 * 1024 * 1024:
                raise ValueError("Failed to compress thumbnail under 4MB limit.")

def _verify_image_not_corrupted(temp_path: Path) -> None:
    """
    生成された画像ファイルが破損していないかをロードして自己検証する。
    """
    try:
        with Image.open(temp_path) as verify_img:
            verify_img.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as e:
        raise ValueError(f"Generated thumbnail image is corrupted: {e}")

def generate_collaborative_thumbnail(
    output_path: str,
    width: int = 1280,
    height: int = 720,
    text: str = "Collaborative Model"
) -> Path:
    """
    Pillowを使用して、アトミックに指定の解像度とテキストでサムネイル画像を生成する。
    画像が品質基準（1280x720以上、16:9アスペクト比、4MB未満、非破損）を満たすよう自動補正する。
    """
    width, height = _adjust_resolution_and_aspect_ratio(width, height)
        
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 原子的な書き込み (Atomic Write)
    temp_path = out_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        img = Image.new("RGB", (width, height), color=(30, 120, 80))
        _draw_gradient_background(img, text)
        
        _save_and_compress_image(img, temp_path)
        _verify_image_not_corrupted(temp_path)
            
        # 正常に保存・検証されたらリネーム
        if out_path.exists():
            out_path.unlink()
        temp_path.rename(out_path)
    except (OSError, ValueError, TypeError, UnidentifiedImageError, RuntimeError) as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        if isinstance(e, ValueError):
            raise
        raise RuntimeError(f"Failed to generate collaborative thumbnail atomically: {e}")
        
    return out_path

def validate_thumbnail_quality(file_path: str) -> dict:
    """
    生成されたサムネイル画像の品質要件を検証する。
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    try:
        with Image.open(file_path) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise ValueError(f"Image is corrupted or invalid format (verify): {e}")
        
    try:
        with Image.open(file_path) as img:
            img.load()  # ピクセルデータのロードを強制
            width, height = img.size
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise ValueError(f"Image is corrupted or invalid format (load): {e}")
        
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

async def resolve_collaborative_thumbnail_task(task_id: str) -> str:
    """
    StageBoundAgent から呼び出し可能な非同期タスク処理ハンドラ。
    """
    output_dir = _writable_path("backend/temp_thumbnails")
    output_path = output_dir / f"collaborative_model_{task_id}.png"
    
    # 画像生成
    generate_collaborative_thumbnail(
        str(output_path),
        width=1280,
        height=720,
        text=f"Collaborative Model\nTask: {task_id}"
    )
    
    success = False
    try:
        # 品質検証
        result_info = validate_thumbnail_quality(str(output_path))
        success = True
        return json.dumps(result_info)
    finally:
        if not success and output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass

def verify_collaborative_evolution():
    print("🚀 Testing Collaborative Trinity 2.0 Logic...")
    
    # 1. Check Initial Context
    print("\n[Step 1] Verifying Collaborative Context...")
    context = branding_manager.get_context_block()
    print(context)
    
    # Check if 'Collaborative Profile' exists in context
    if "COLLABORATIVE PROFILE" not in context:
        print("Context missing Collaborative Profile header.")
    else:
        print("✅ Context includes Collaborative Profile header.")

    # Get Initial XP
    u_before = branding_manager.user_model
    initial_admin_xp = u_before.get("profiles", {}).get("admin", {}).get("ranks", {}).get("tech_rank", {}).get("xp", 0)
    initial_owner_xp = u_before.get("profiles", {}).get("owner", {}).get("ranks", {}).get("biz_rank", {}).get("xp", 0)
    
    # 2. Grant Admin XP (Tech)
    print("\n[Step 2] Granting XP to ADMIN (Tech)...")
    branding_manager.update_user_rank("tech_rank", amount=20)
    
    # 3. Grant Owner XP (Biz)
    print("\n[Step 3] Granting XP to OWNER (Biz)...")
    branding_manager.update_user_rank("biz_rank", amount=30)
    
    # 4. Verify Model State
    u_after = branding_manager.user_model
    admin_xp = u_after.get("profiles", {}).get("admin", {}).get("ranks", {}).get("tech_rank", {}).get("xp", 0)
    owner_xp = u_after.get("profiles", {}).get("owner", {}).get("ranks", {}).get("biz_rank", {}).get("xp", 0)
    
    print(f"\nFinal State:")
    print(f"Admin Tech XP: {admin_xp} (was {initial_admin_xp})")
    print(f"Owner Biz XP: {owner_xp} (was {initial_owner_xp})")
    
    if admin_xp != initial_admin_xp + 20 or owner_xp != initial_owner_xp + 30:
        print("FAILURE: XP did not update correctly in nested profiles.")
        return False
        
    print("\n✨ SUCCESS: Collaborative XP Tracking is working flawlessly!")
    return True


def test_adjust_resolution_and_aspect_ratio():
    # 1. 正常な解像度の維持
    w, h = _adjust_resolution_and_aspect_ratio(1280, 720)
    assert w == 1280 and h == 720
    
    # 2. 低解像度の自動補正 (16:9アスペクト比維持)
    w, h = _adjust_resolution_and_aspect_ratio(640, 360)
    assert w >= 1280 and h >= 720
    assert abs((w / h) - (16.0 / 9.0)) < 0.01

    # 3. アスペクト比が16:9でない場合の自動補正
    w, h = _adjust_resolution_and_aspect_ratio(1000, 1000)  # 1:1
    assert abs((w / h) - (16.0 / 9.0)) < 0.01
    
    # 4. エラーケース
    with pytest.raises(ValueError):
        _adjust_resolution_and_aspect_ratio(-100, 100)
    with pytest.raises(ValueError):
        _adjust_resolution_and_aspect_ratio(100, 0)
    with pytest.raises(ValueError):
        _adjust_resolution_and_aspect_ratio("invalid", 100)  # type: ignore


def test_thumbnail_generation_and_validation(tmp_path):
    output_file = tmp_path / "test_thumb.png"
    # 生成
    path = generate_collaborative_thumbnail(str(output_file), width=1280, height=720, text="Test Thumbnail")
    assert path.exists()
    
    # 検証
    info = validate_thumbnail_quality(str(path))
    assert info["width"] == 1280
    assert info["height"] == 720
    assert info["size_bytes"] > 0
    
    # 存在しないファイルに対する検証エラー
    with pytest.raises(FileNotFoundError):
        validate_thumbnail_quality("non_existent_file.png")


@pytest.mark.asyncio
async def test_resolve_collaborative_thumbnail_task():
    task_id = "test_task_123"
    result_json = await resolve_collaborative_thumbnail_task(task_id)
    info = json.loads(result_json)
    
    expected_path = _writable_path("backend/temp_thumbnails") / f"collaborative_model_{task_id}.png"
    assert expected_path.exists()
    assert info["width"] == 1280
    assert info["height"] == 720
    
    # 後処理（クリーンアップ）
    if expected_path.exists():
        expected_path.unlink()
