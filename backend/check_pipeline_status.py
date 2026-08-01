"""Pipeline status checker."""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import urllib.request
import json
import sys

def fetch_pipeline_status_data() -> dict:
    """APIからパイプラインのステータスデータを取得して辞書として返す"""
    try:
        response = urllib.request.urlopen('http://127.0.0.1:8000/api/pipeline/status', timeout=5)
        response_bytes = response.read()
    except urllib.error.URLError as e:
        print(f"Error: Failed to connect to pipeline server: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        # TDR-CRITICAL: Unexpected connection error safety net
        print(f"Unexpected error during connection: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(response_bytes.decode('utf-8'))
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON response from server: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        # TDR-CRITICAL: Unexpected JSON parse error safety net
        print(f"Unexpected error during parsing: {e}", file=sys.stderr)
        sys.exit(1)
        
    return data


def _print_stages(stages: list) -> None:
    """各ステージのステータスを出力する"""
    for stage in stages:
        icon = {"completed": "✅", "running": "🔄", "pending": "⏳", "failed": "❌"}.get(stage.get('status', ''), "?")
        idx = stage.get('index', stage.get('stage_index', '?'))
        name = stage.get('name', stage.get('stage_name', '?'))
        detail = stage.get('detail', stage.get('message', ''))
        print(f"  {icon} [{idx}] {name}: {stage.get('status', '?')} {detail}")


def _print_feedback(feedback: list) -> None:
    """クオリティフィードバックを出力する"""
    if feedback:
        print(f"\nQuality Feedback:")
        for f in feedback:
            print(f"  - {f}")


def _print_result(result: dict) -> None:
    """パイプラインの実行結果を出力する"""
    if not result:
        return
    print(f"\nDuration: {result.get('duration_seconds', 0):.1f}s")
    final = result.get('final_path', 'N/A')
    print(f"Final:    {final}")
    quality = result.get('quality_score', 0)
    print(f"Quality:  {quality}")
    for stage_result in result.get('stage_results', []):
        icon = "✅" if stage_result.get('success') else "❌"
        print(f"  {icon} {stage_result.get('name')}: {stage_result.get('duration', 0):.1f}s")
    
    _print_feedback(result.get('quality_feedback', []))


def print_pipeline_status(data: dict) -> None:
    """パイプラインのステータスデータを標準出力にフォーマットして出力する"""
    print(f"Status:  {data.get('status')}")
    print(f"Stage:   {data.get('current_stage')}")
    
    _print_stages(data.get('stages', []))
    _print_result(data.get('result'))


def check() -> None:
    """パイプラインステータスをチェックし、結果を出力するメイン処理"""
    data = fetch_pipeline_status_data()
    print_pipeline_status(data)


if __name__ == "__main__":
    check()


# --- サムネイル画像生成・品質検証・StageBoundAgent連携ロジックの追加 ---
from PIL import Image, ImageDraw
import uuid
from pathlib import Path
from datetime import datetime
import asyncio

OUTPUT_DIR = str(_writable_path("backend/temp_thumbnails"))

def generate_pipeline_status_thumbnail(output_path, width=1280, height=720, text=None):
    """Pillowを使用して、パイプラインステータスのサムネイル画像を生成する"""
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
        # 落ち着いた紫色の背景
        img = Image.new("RGB", (width, height), color=(45, 30, 45))
        d = ImageDraw.Draw(img)
        
        if not text:
            text = f"Pipeline Status Report\nGenerated at: {datetime.now().isoformat()}"
            
        d.text((40, 40), text, fill=(255, 255, 255))
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

def validate_pipeline_status_thumbnail(file_path) -> dict:
    """
    サムネイル画像の品質要件を検証する
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    # Pillowによる破損検証
    try:
        with Image.open(file_path) as img:
            img.verify()
    except Exception as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    # ピクセルロードによる完全検証
    try:
        with Image.open(file_path) as img:
            img.load()
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

async def resolve_pipeline_status_thumbnail_task(task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理
    """
    
    status_text = "Pipeline Status: Unknown (offline)"
    try:
        def _get_status():
            try:
                # タイムアウトを短く設定し、テスト等のハングを防止する
                r = urllib.request.urlopen('http://127.0.0.1:8000/api/pipeline/status', timeout=2)
                return json.loads(r.read().decode('utf-8'))
            except Exception:
                return None
                
        data = await asyncio.to_thread(_get_status)
        if data:
            status_text = (
                f"=== Pipeline Status ===\n"
                f"Status: {data.get('status')}\n"
                f"Stage: {data.get('current_stage')}\n"
                f"Checked at: {datetime.now().isoformat()}"
            )
    except Exception as e:
        status_text = f"Pipeline Connection Error: {e}"
        
    output_dir_path = Path(OUTPUT_DIR)
    output_path = output_dir_path / f"{task_id}.png"
    
    generate_pipeline_status_thumbnail(output_path, text=status_text)
    result_info = validate_pipeline_status_thumbnail(output_path)
    
    return json.dumps(result_info)

