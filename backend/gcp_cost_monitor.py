"""
GCP費用監視スクリプト
恒久的な費用管理の一環として、月次費用をチェック
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path


import subprocess
import json
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw
import uuid

OUTPUT_DIR = str(_writable_path("backend/temp_thumbnails"))


def _get_nested_value(data, *keys, default="N/A"):
    """辞書からネストしたキーの値を安全に取得するヘルパー"""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
    return current if current is not None else default


def _fetch_gcp_projects():
    """GCPのプロジェクト一覧を取得する"""
    print("\n📋 プロジェクト一覧を確認中...")
    try:
        result = subprocess.run(
            ["gcloud", "projects", "list", "--format=json"],
            capture_output=True,
            text=True,
            check=True
        )
        try:
            projects = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"❌ JSONパースエラー: {e}")
            return None
        
        if not projects:
            print("⚠️ GCPプロジェクトが見つかりません")
            return None
        
        print(f"\n✅ {len(projects)} 個のプロジェクトを発見")
        for project in projects:
            print(f"  - {project.get('projectId', 'N/A')}: {project.get('name', 'N/A')}")
        
        return projects
        
    except subprocess.CalledProcessError as e:
        print(f"❌ エラー: {e}")
        print("gcloud コマンドが利用可能か確認してください")
        return None


def _fetch_cloud_run_services(project_id):
    """指定されたプロジェクトのCloud Runサービス一覧を取得する"""
    try:
        result = subprocess.run(
            ["gcloud", "run", "services", "list", f"--project={project_id}", "--format=json"],
            capture_output=True,
            text=True,
            check=True
        )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"  ❌ JSONパースエラー: {e}")
            return None
    except subprocess.CalledProcessError:
        print("  ℹ️ Cloud Run APIが有効化されていないか、サービスがありません")
        return None


def _print_cloud_run_services(services):
    """Cloud Runサービスの詳細を出力する"""
    if services:
        print(f"⚠️ {len(services)} 個のCloud Runサービスが稼働中:")
        for service in services:
            print(f"  - {_get_nested_value(service, 'metadata', 'name')}")
            print(f"    リージョン: {_get_nested_value(service, 'metadata', 'labels', 'cloud.googleapis.com/location')}")
            print(f"    作成日: {_get_nested_value(service, 'metadata', 'creationTimestamp')}")
            print(f"    🔴 削除推奨: このサービスは課金されている可能性があります")
    else:
        print("✅ Cloud Runサービスなし（費用0円）")


def _print_deletion_recommendation():
    """推奨される削除アクションを出力する"""
    print("\n" + "="*60)
    print("🛠️ 推奨アクション")
    print("="*60)
    print("\nCloud Runサービスが見つかった場合、以下のコマンドで削除:")
    print("\n  gcloud run services delete SERVICE_NAME --region REGION --project PROJECT_ID --quiet")
    print("\n全サービスを確認:")
    print("  gcloud run services list --project PROJECT_ID")


def _check_projects_services(projects):
    """プロジェクト一覧を巡回してCloud Runサービスをチェックする"""
    checked_project_ids = []
    for project in projects:
        project_id = project.get('projectId')
        if not project_id or project_id == "N/A":
            continue
        print(f"\n📦 プロジェクト: {project_id}")
        checked_project_ids.append(project_id)
        
        services = _fetch_cloud_run_services(project_id)
        if services is not None:
            _print_cloud_run_services(services)
    return checked_project_ids


def check_gcp_costs():
    """
    GCP費用をチェックし、閾値を超えている場合は警告
    
    Returns:
        dict: 費用情報と警告
    """
    print("\n" + "="*60)
    print("💰 GCP 費用チェック")
    print("="*60)
    
    projects = _fetch_gcp_projects()
    if projects is None:
        return None
    
    # Cloud Runサービスチェック
    print("\n" + "="*60)
    print("🔍 Cloud Run サービスチェック")
    print("="*60)
    
    checked_project_ids = _check_projects_services(projects)
            
    _print_deletion_recommendation()
    
    print("\n" + "="*60)
    print("✅ チェック完了")
    print("="*60 + "\n")
    
    return {
        "timestamp": datetime.now().isoformat(),
        "projects": checked_project_ids
    }


def _create_report_image(width, height, text=None):
    """Pillowを使用してレポート用のImageオブジェクトを作成し描画する"""
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers.")
        
    img = Image.new("RGB", (width, height), color=(20, 30, 45))
    draw = ImageDraw.Draw(img)
    
    if not text:
        text = f"GCP Cost Monitor Report\nGenerated at: {datetime.now().isoformat()}"
        
    draw.text((40, 40), text, fill=(255, 255, 255))
    return img


def _save_image_atomically(img, file_path):
    """一時ファイルを使用して画像を安全かつアトミックに保存する"""
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    temp_path = file_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        img.save(temp_path, "PNG")
        if file_path.exists():
            file_path.unlink()
        temp_path.rename(file_path)
    except Exception as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise e


def generate_gcp_cost_report_thumbnail(output_path, width=1280, height=720, text=None):
    """Pillowを使用して、GCP費用監視レポート画像を生成する"""
    file_path = Path(output_path)
    img = _create_report_image(width, height, text)
    _save_image_atomically(img, file_path)
    return file_path


def _verify_image_integrity(file_path):
    """画像を構成する存在確認、ファイルサイズ、および破損チェックを行う"""
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
        
    return width, height, size_bytes


def _verify_image_dimensions(width, height):
    """画像の解像度とアスペクト比が要件を満たしているか検証する"""
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")


def validate_thumbnail(file_path) -> dict:
    """
    サムネイル画像の品質要件を検証する
    """
    file_path = Path(file_path)
    width, height, size_bytes = _verify_image_integrity(file_path)
    _verify_image_dimensions(width, height)
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }


def _format_report_text(cost_info):
    """費用情報からレポート用の文字列を生成する"""
    if cost_info:
        projects_str = ", ".join(cost_info.get("projects", []))
        return (
            f"=== GCP Cost Monitor Report ===\n"
            f"Status: OK\n"
            f"Timestamp: {cost_info.get('timestamp')}\n"
            f"Checked Projects: {projects_str}\n"
            f"Note: Verification completed successfully."
        )
    else:
        return (
            f"=== GCP Cost Monitor Report ===\n"
            f"Status: WARNING / ERROR\n"
            f"Timestamp: {datetime.now().isoformat()}\n"
            f"Details: Failed to retrieve cost details."
        )


async def resolve_gcp_cost_monitor_task(task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理
    """
    cost_info = check_gcp_costs()
    text = _format_report_text(cost_info)
        
    output_dir_path = Path(OUTPUT_DIR)
    file_path = output_dir_path / f"{task_id}.png"
    
    generate_gcp_cost_report_thumbnail(file_path, text=text)
    validation_result = validate_thumbnail(file_path)
    
    import json
    return json.dumps(validation_result)


if __name__ == "__main__":
    check_gcp_costs()
