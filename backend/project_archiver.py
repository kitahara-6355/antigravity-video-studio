import os
import json
import shutil
import time
import re
from pathlib import Path

# 構成ファイルのパス定義
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
ARCHIVE_DIR = os.path.join(BASE_DIR, "backend", "archives", "projects")

# 対象ファイル
FILES_TO_BACKUP = {
    "scenes": os.path.join(SRC_DIR, "scenes_data.json"),
    "segments": os.path.join(SRC_DIR, "segments_a_plus_plus.json")
}

def _is_safe_name(name):
    """
    英数字、ハイフン、アンダースコアのみを許容する安全な名前チェック。
    """
    if not isinstance(name, str):
        return False
    if not name:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', name))

class ProjectArchiver:
    def __init__(self):
        os.makedirs(ARCHIVE_DIR, exist_ok=True)

    def _validate_snapshot_path(self, snapshot_id):
        """
        snapshot_id を検証し、安全なスナップショットディレクトリの絶対パスを返す。
        ディレクトリトラバーサルを防止する。
        """
        if not snapshot_id or not _is_safe_name(snapshot_id):
            raise ValueError(f"Invalid characters in snapshot_id: {snapshot_id}")
            
        snapshot_path = os.path.join(ARCHIVE_DIR, snapshot_id)
        abs_archive = os.path.abspath(ARCHIVE_DIR)
        abs_snapshot = os.path.abspath(snapshot_path)
        
        # スナップショットディレクトリの親ディレクトリが ARCHIVE_DIR と完全に一致することを確認
        if os.path.dirname(abs_snapshot) != abs_archive:
            raise ValueError(f"Path traversal attempt detected: {snapshot_id}")
            
        return snapshot_path

    def save_snapshot(self, project_name="default", label="manual"):
        """
        現在の構成ファイルをスナップショットとして保存する。
        """
        if not _is_safe_name(project_name):
            raise ValueError(f"Invalid characters in project_name: {project_name}")
        if not _is_safe_name(label):
            raise ValueError(f"Invalid characters in label: {label}")

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        snapshot_id = f"{project_name}_{label}_{timestamp}"
        
        snapshot_path = self._validate_snapshot_path(snapshot_id)
        os.makedirs(snapshot_path, exist_ok=True)
        
        saved_files = []
        try:
            for key, src_path in FILES_TO_BACKUP.items():
                if os.path.exists(src_path):
                    dest_path = os.path.join(snapshot_path, f"{key}.json")
                    shutil.copy2(src_path, dest_path)
                    saved_files.append(key)
            
            # メタデータの作成
            meta = {
                "snapshot_id": snapshot_id,
                "project_name": project_name,
                "label": label,
                "timestamp": timestamp,
                "files": saved_files
            }
            with open(os.path.join(snapshot_path, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
        except OSError as e:
            # 途中で失敗した場合は作成途中のディレクトリを削除する
            if os.path.exists(snapshot_path):
                shutil.rmtree(snapshot_path, ignore_errors=True)
            raise OSError(f"Failed to create snapshot due to I/O error: {e}") from e
            
        print(f"📦 Snapshot created: {snapshot_id}")
        return snapshot_id

    def list_snapshots(self, project_name=None):
        """
        保存されているスナップショットの一覧を取得する。
        """
        if project_name is not None and not _is_safe_name(project_name):
            raise ValueError(f"Invalid characters in project_name: {project_name}")

        snapshots = []
        if not os.path.exists(ARCHIVE_DIR):
            return []
            
        for d in os.listdir(ARCHIVE_DIR):
            if not _is_safe_name(d):
                continue
                
            path = os.path.join(ARCHIVE_DIR, d)
            meta_path = os.path.join(path, "metadata.json")
            if os.path.isdir(path) and os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        if not isinstance(meta, dict):
                            print(f"⚠️ Metadata for snapshot {d} is not a JSON object")
                            continue
                        if project_name is None or meta.get("project_name") == project_name:
                            snapshots.append(meta)
                except (json.JSONDecodeError, OSError) as e:
                    print(f"⚠️ Failed to load metadata for snapshot {d}: {e}")
                    continue
        
        return sorted(snapshots, key=lambda x: x.get('timestamp', ''), reverse=True)

    def restore_snapshot(self, snapshot_id):
        """
        指定されたスナップショットを現在の作業領域に復元する。
        """
        snapshot_path = self._validate_snapshot_path(snapshot_id)
        if not os.path.exists(snapshot_path):
            raise FileNotFoundError(f"Snapshot {snapshot_id} not found.")
            
        # 復元前に現在の状態をバックアップする。
        # 復元対象のスナップショットのメタデータから project_name を取得して、バックアップ名に反映する。
        meta_path = os.path.join(snapshot_path, "metadata.json")
        project_name = "default"
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    if isinstance(meta, dict):
                        project_name = meta.get("project_name", "default")
            except (json.JSONDecodeError, OSError):
                # メタデータ読み込みに失敗した場合は "default" を使用する
                pass

        # 復元前に現在の状態を 'auto_before_restore' としてバックアップ（念のため）
        self.save_snapshot(project_name=project_name, label="auto_before_restore")
        
        for key, target_path in FILES_TO_BACKUP.items():
            target_dir = os.path.dirname(target_path)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
                
            src_snapshot_path = os.path.join(snapshot_path, f"{key}.json")
            if os.path.exists(src_snapshot_path):
                shutil.copy2(src_snapshot_path, target_path)
                print(f"✅ Restored: {key}")
        
        return True

    def generate_thumbnail(
        self,
        output_path,
        width: int = 1280,
        height: int = 720,
        text: str = "Project Thumbnail"
    ):
        """Pillowを使用して、指定された解像度とテキストでサムネイル画像を生成する"""
        from PIL import Image, ImageDraw
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (width, height), color=(73, 109, 137))
        d = ImageDraw.Draw(img)
        d.text((10, 10), text, fill=(255, 255, 0))
        img.save(output_path, "PNG")
        return output_path

    def validate_thumbnail(self, file_path) -> dict:
        """
        サムネイル画像の品質要件を検証する
        """
        from PIL import Image, UnidentifiedImageError
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
            raise ValueError(f"Image is corrupted or invalid format: {e}")
            
        try:
            with Image.open(file_path) as img:
                width, height = img.size
        except (UnidentifiedImageError, OSError, ValueError, RuntimeError) as e:
            raise ValueError(f"Failed to load image for resolution check: {e}")
            
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
            
        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        if abs(aspect_ratio - target_ratio) > 0.05:
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
        output_dir = Path(getattr(self, "output_dir", None) or "backend/temp_thumbnails")
        output_path = output_dir / f"{task_id}.png"
        self.generate_thumbnail(output_path)
        result_info = self.validate_thumbnail(output_path)
        return json.dumps(result_info)

project_archiver = ProjectArchiver()

if __name__ == "__main__":
    # Test
    sid = project_archiver.save_snapshot(label="test")
    print("Listing snapshots:", project_archiver.list_snapshots())
