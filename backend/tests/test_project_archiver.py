# 出力先は実装と同じ経路で解決する。直書きすると、実装を writable_path へ
# 寄せた後もテストだけがリポジトリ内を見に行き、本番ディレクトリを掴む。
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _wp
except ImportError:
    from path_resolver import writable_path as _wp

import os
import json
import shutil
import time
import pytest
import runpy
from unittest.mock import patch

# project_archiver モジュールのインポート
import backend.project_archiver as pa
from backend.project_archiver import ProjectArchiver, _is_safe_name

def test_is_safe_name_func():
    assert _is_safe_name("valid_name-123") is True
    assert _is_safe_name("") is False
    assert _is_safe_name(None) is False
    assert _is_safe_name(123) is False
    assert _is_safe_name("invalid/name") is False
    assert _is_safe_name("invalid.name") is False

@pytest.fixture
def temp_archive_env(tmp_path):
    # テスト用の一時フォルダ構成を作成
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    archive_dir = tmp_path / "archives"
    archive_dir.mkdir()
    
    # 元ファイルを準備
    scenes_file = src_dir / "scenes_data.json"
    scenes_file.write_text(json.dumps({"scenes": []}), encoding="utf-8")
    
    segments_file = src_dir / "segments_a_plus_plus.json"
    segments_file.write_text(json.dumps({"segments": []}), encoding="utf-8")
    
    # テスト対象モジュールのグローバル定数を差し替える
    orig_src_dir = pa.SRC_DIR
    orig_archive_dir = pa.ARCHIVE_DIR
    orig_backup_dict = pa.FILES_TO_BACKUP
    
    pa.SRC_DIR = str(src_dir)
    pa.ARCHIVE_DIR = str(archive_dir)
    pa.FILES_TO_BACKUP = {
        "scenes": str(scenes_file),
        "segments": str(segments_file)
    }
    
    yield tmp_path, src_dir, archive_dir, scenes_file, segments_file
    
    # 元に戻す
    pa.SRC_DIR = orig_src_dir
    pa.ARCHIVE_DIR = orig_archive_dir
    pa.FILES_TO_BACKUP = orig_backup_dict

def test_project_archiver_init(temp_archive_env):
    _, _, archive_dir, _, _ = temp_archive_env
    # __init__ で ARCHIVE_DIR が作成されることを確認
    shutil.rmtree(archive_dir)
    archiver = ProjectArchiver()
    assert os.path.exists(archive_dir)

def test_validate_snapshot_path(temp_archive_env):
    _, _, archive_dir, _, _ = temp_archive_env
    archiver = ProjectArchiver()
    
    # 正常系
    path = archiver._validate_snapshot_path("valid_id")
    assert path == os.path.join(archive_dir, "valid_id")
    
    # 異常系: 不正文字
    with pytest.raises(ValueError, match="Invalid characters in snapshot_id"):
        archiver._validate_snapshot_path("invalid/id")
        
    # 異常系: パストラバーサル (1. 通常のガードで弾かれるケース)
    with pytest.raises(ValueError, match="Invalid characters in snapshot_id"):
        archiver._validate_snapshot_path("../invalid_id")
        
    # 異常系: パストラバーサル (2. _is_safe_nameをバイパスして、dirname != archive_dir ガードを通すケース)
    with patch("backend.project_archiver._is_safe_name", return_value=True):
        with pytest.raises(ValueError, match="Path traversal attempt detected"):
            archiver._validate_snapshot_path("../invalid_id")

def test_save_snapshot_validation(temp_archive_env):
    archiver = ProjectArchiver()
    
    with pytest.raises(ValueError, match="Invalid characters in project_name"):
        archiver.save_snapshot(project_name="invalid/name")
        
    with pytest.raises(ValueError, match="Invalid characters in label"):
        archiver.save_snapshot(label="invalid/label")

def test_save_snapshot_success(temp_archive_env):
    _, _, archive_dir, scenes_file, segments_file = temp_archive_env
    archiver = ProjectArchiver()
    
    snapshot_id = archiver.save_snapshot(project_name="test_proj", label="test_label")
    assert snapshot_id.startswith("test_proj_test_label_")
    
    snapshot_path = os.path.join(archive_dir, snapshot_id)
    assert os.path.exists(snapshot_path)
    assert os.path.exists(os.path.join(snapshot_path, "scenes.json"))
    assert os.path.exists(os.path.join(snapshot_path, "segments.json"))
    assert os.path.exists(os.path.join(snapshot_path, "metadata.json"))
    
    # メタデータの中身を確認
    with open(os.path.join(snapshot_path, "metadata.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)
        assert meta["project_name"] == "test_proj"
        assert meta["label"] == "test_label"
        assert meta["files"] == ["scenes", "segments"]

def test_save_snapshot_missing_src_files(temp_archive_env):
    _, _, archive_dir, scenes_file, segments_file = temp_archive_env
    archiver = ProjectArchiver()
    
    # 片方のファイルを消す
    os.remove(scenes_file)
    
    snapshot_id = archiver.save_snapshot(project_name="test_proj", label="test_label")
    snapshot_path = os.path.join(archive_dir, snapshot_id)
    
    assert not os.path.exists(os.path.join(snapshot_path, "scenes.json"))
    assert os.path.exists(os.path.join(snapshot_path, "segments.json"))
    
    with open(os.path.join(snapshot_path, "metadata.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)
        assert meta["files"] == ["segments"]

def test_save_snapshot_io_error(temp_archive_env):
    _, _, archive_dir, _, _ = temp_archive_env
    archiver = ProjectArchiver()
    
    # shutil.copy2 で OSError を発生させる
    with patch("shutil.copy2", side_effect=OSError("Disk Full")):
        with pytest.raises(OSError, match="Failed to create snapshot due to I/O error"):
            archiver.save_snapshot()
            
    # 作成されかけたディレクトリがクリーンアップされていることを確認
    # (ARCHIVE_DIR 自体は空のはず)
    assert len(os.listdir(archive_dir)) == 0

def test_list_snapshots(temp_archive_env):
    _, _, archive_dir, _, _ = temp_archive_env
    archiver = ProjectArchiver()
    
    # 最初は空
    assert archiver.list_snapshots() == []
    
    # 複数スナップショットを作成
    sid1 = archiver.save_snapshot(project_name="projA", label="manual")
    time.sleep(1.1)  # 1秒待つ
    sid2 = archiver.save_snapshot(project_name="projB", label="manual")
    time.sleep(1.1)
    sid3 = archiver.save_snapshot(project_name="projA", label="auto")
    
    # 全件取得
    snaps = archiver.list_snapshots()
    assert len(snaps) == 3
    # 降順ソート確認 (最新が先頭)
    assert snaps[0]["snapshot_id"] == sid3
    assert snaps[1]["snapshot_id"] == sid2
    assert snaps[2]["snapshot_id"] == sid1
    
    # プロジェクトフィルタ
    snaps_a = archiver.list_snapshots(project_name="projA")
    assert len(snaps_a) == 2
    assert snaps_a[0]["snapshot_id"] == sid3
    assert snaps_a[1]["snapshot_id"] == sid1
    
    # 不正プロジェクト名フィルタ
    with pytest.raises(ValueError, match="Invalid characters in project_name"):
        archiver.list_snapshots(project_name="invalid/name")

def test_list_snapshots_no_archive_dir(temp_archive_env):
    _, _, archive_dir, _, _ = temp_archive_env
    archiver = ProjectArchiver()
    shutil.rmtree(archive_dir)
    assert archiver.list_snapshots() == []

def test_list_snapshots_unsafe_dir_name(temp_archive_env):
    _, _, archive_dir, _, _ = temp_archive_env
    archiver = ProjectArchiver()
    # 安全でないディレクトリ名を作成
    unsafe_dir = os.path.join(archive_dir, "unsafe.dir-name")
    os.makedirs(unsafe_dir, exist_ok=True)
    assert archiver.list_snapshots() == []

def test_list_snapshots_corrupt_metadata(temp_archive_env):
    _, _, archive_dir, _, _ = temp_archive_env
    archiver = ProjectArchiver()
    
    # 正常スナップショット
    archiver.save_snapshot(project_name="projA")
    
    # メタデータ破損用のスナップショットディレクトリを作成
    corrupt_dir = os.path.join(archive_dir, "projA_manual_corrupt")
    os.makedirs(corrupt_dir, exist_ok=True)
    
    # 1. metadata.json が存在しない
    assert len(archiver.list_snapshots()) == 1
    
    # 2. metadata.json がJSONとして不正
    meta_path = os.path.join(corrupt_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("{invalid json")
    assert len(archiver.list_snapshots()) == 1
    
    # 3. metadata.json が辞書ではない (例: リスト)
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(["not", "dict"]))
    assert len(archiver.list_snapshots()) == 1
    
    # 4. metadata.json は正しいが timestamp が欠損している
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"snapshot_id": "projA_manual_corrupt", "project_name": "projA"}, f)
    # エラーにならずにソートされて取得できること
    snaps = archiver.list_snapshots()
    assert len(snaps) == 2

def test_restore_snapshot_not_found(temp_archive_env):
    archiver = ProjectArchiver()
    with pytest.raises(FileNotFoundError, match="Snapshot non_existent not found"):
        archiver.restore_snapshot("non_existent")

def test_restore_snapshot_success(temp_archive_env):
    _, src_dir, archive_dir, scenes_file, segments_file = temp_archive_env
    archiver = ProjectArchiver()
    
    # 状態1を保存
    scenes_file.write_text(json.dumps({"state": 1}), encoding="utf-8")
    segments_file.write_text(json.dumps({"state": 1}), encoding="utf-8")
    sid1 = archiver.save_snapshot(project_name="projX", label="state1")
    
    # 状態2にする
    scenes_file.write_text(json.dumps({"state": 2}), encoding="utf-8")
    segments_file.write_text(json.dumps({"state": 2}), encoding="utf-8")
    
    # 復元実行
    res = archiver.restore_snapshot(sid1)
    assert res is True
    
    # 復元されたか確認
    with open(scenes_file, "r", encoding="utf-8") as f:
        assert json.load(f) == {"state": 1}
    with open(segments_file, "r", encoding="utf-8") as f:
        assert json.load(f) == {"state": 1}
        
    # 自動バックアップが作成されていることを確認
    snaps = archiver.list_snapshots(project_name="projX")
    assert len(snaps) >= 2
    auto_backups = [s for s in snaps if s["label"] == "auto_before_restore"]
    assert len(auto_backups) == 1
    assert auto_backups[0]["project_name"] == "projX"

def test_restore_snapshot_missing_metadata(temp_archive_env):
    _, src_dir, archive_dir, scenes_file, segments_file = temp_archive_env
    archiver = ProjectArchiver()
    
    # スナップショットを保存
    sid = archiver.save_snapshot(project_name="projY", label="state1")
    
    # 保存フォルダ内のメタデータファイルを消して破損状態にする
    snapshot_path = os.path.join(archive_dir, sid)
    os.remove(os.path.join(snapshot_path, "metadata.json"))
    
    # メタデータが無くても復元が実行でき、バックアップの project_name は default にフォールバックされること
    res = archiver.restore_snapshot(sid)
    assert res is True
    
    # default の自動バックアップが作成されたか確認
    snaps_default = archiver.list_snapshots(project_name="default")
    assert len(snaps_default) >= 1
    assert snaps_default[0]["label"] == "auto_before_restore"

def test_restore_snapshot_corrupt_metadata_json_decode_error(temp_archive_env):
    _, _, archive_dir, scenes_file, segments_file = temp_archive_env
    archiver = ProjectArchiver()
    sid = archiver.save_snapshot(project_name="proj_corrupt", label="state")
    
    # メタデータの中身を壊す
    meta_path = os.path.join(archive_dir, sid, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("{invalid json")
        
    # デコードエラーが起きるが、問題なく復元され、デフォルト名でバックアップされること
    res = archiver.restore_snapshot(sid)
    assert res is True

def test_restore_snapshot_destination_missing(temp_archive_env):
    _, src_dir, archive_dir, scenes_file, segments_file = temp_archive_env
    archiver = ProjectArchiver()
    
    sid = archiver.save_snapshot(project_name="projZ", label="state1")
    
    # 復元先ディレクトリ(SRC_DIR)を丸ごと削除する
    shutil.rmtree(src_dir)
    assert not os.path.exists(src_dir)
    
    # 復元を実行すると、ディレクトリが再作成されて復元されること
    res = archiver.restore_snapshot(sid)
    assert res is True
    assert os.path.exists(src_dir)
    assert os.path.exists(scenes_file)

def test_main_execution(temp_archive_env):
    # __main__ ブロックを実行する
    # モックはせず、temp_archive_env の下で安全に最後まで処理を実行する
    runpy.run_path("backend/project_archiver.py", run_name="__main__")


from pathlib import Path
from PIL import Image

def test_generate_thumbnail(tmp_path):
    archiver = ProjectArchiver()
    output_path = tmp_path / "test_thumb.png"
    res = archiver.generate_thumbnail(output_path, text="Custom Gen")
    assert res == output_path
    assert output_path.exists()
    
    with Image.open(output_path) as img:
        assert img.size == (1280, 720)

def test_validate_thumbnail_success(tmp_path):
    archiver = ProjectArchiver()
    output_path = tmp_path / "test_valid.png"
    archiver.generate_thumbnail(output_path, text="Valid 16:9")
    
    res = archiver.validate_thumbnail(output_path)
    assert res["path"] == str(output_path)
    assert res["width"] == 1280
    assert res["height"] == 720
    assert res["size_bytes"] > 0

def test_validate_thumbnail_file_not_found():
    archiver = ProjectArchiver()
    with pytest.raises(FileNotFoundError, match="Thumbnail file not found"):
        archiver.validate_thumbnail("non_existent_file.png")

def test_validate_thumbnail_size_limit(tmp_path):
    archiver = ProjectArchiver()
    output_path = tmp_path / "large_file.png"
    with open(output_path, "wb") as f:
        f.write(b"\x00" * (4 * 1024 * 1024 + 1024))
        
    with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
        archiver.validate_thumbnail(output_path)

def test_validate_thumbnail_invalid_format(tmp_path):
    archiver = ProjectArchiver()
    output_path = tmp_path / "corrupt.png"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("not an image")
        
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        archiver.validate_thumbnail(output_path)

def test_validate_thumbnail_failed_to_load_size(tmp_path):
    archiver = ProjectArchiver()
    output_path = tmp_path / "valid.png"
    archiver.generate_thumbnail(output_path)
    
    original_open = Image.open
    call_count = 0
    
    def mock_open(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("Simulated size load error")
        return original_open(*args, **kwargs)
        
    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError, match="Failed to load image for resolution check"):
            archiver.validate_thumbnail(output_path)

def test_validate_thumbnail_resolution_too_low(tmp_path):
    archiver = ProjectArchiver()
    output_path = tmp_path / "low_res.png"
    archiver.generate_thumbnail(output_path, width=1000, height=500)
    
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        archiver.validate_thumbnail(output_path)

def test_validate_thumbnail_aspect_ratio_invalid(tmp_path):
    archiver = ProjectArchiver()
    output_path = tmp_path / "square.png"
    archiver.generate_thumbnail(output_path, width=1280, height=1280)
    
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        archiver.validate_thumbnail(output_path)

@pytest.mark.asyncio
async def test_resolve_thumbnail_task(tmp_path):
    archiver = ProjectArchiver()
    archiver.output_dir = tmp_path
    
    task_id = "async_task_123"
    result_str = await archiver.resolve_thumbnail_task(task_id)
    
    result_info = json.loads(result_str)
    expected_path = tmp_path / f"{task_id}.png"
    assert result_info["path"] == str(expected_path)
    assert result_info["width"] == 1280
    assert result_info["height"] == 720
    assert expected_path.exists()

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_default_dir(tmp_path):
    archiver = ProjectArchiver()
    task_id = "default_async_task"
    expected_path = _wp("backend/temp_thumbnails") / f"{task_id}.png"
    
    if expected_path.exists():
        expected_path.unlink()
        
    try:
        result_str = await archiver.resolve_thumbnail_task(task_id)
        result_info = json.loads(result_str)
        assert result_info["path"] == str(expected_path)
        assert expected_path.exists()
    finally:
        if expected_path.exists():
            expected_path.unlink()
        try:
            expected_path.parent.rmdir()
        except OSError:
            pass


def test_is_safe_name_extra_edge_cases():
    # 制御文字や空白、非ASCII文字、非常に長い文字列などの詳細検証
    assert _is_safe_name(" ") is False
    assert _is_safe_name("a b") is False
    assert _is_safe_name("a\nb") is False
    assert _is_safe_name("プロジェクト") is False
    assert _is_safe_name("a" * 1000) is True  # 許容文字のみで長い文字列はTrue
    assert _is_safe_name("a" * 1000 + "/") is False


def test_validate_thumbnail_aspect_ratio_boundary(tmp_path):
    archiver = ProjectArchiver()
    output_path = tmp_path / "boundary_ratio.png"
    # アスペクト比が 16:9 (1.7777...) から許容範囲 0.05 ぎりぎりズレる場合
    archiver.generate_thumbnail(output_path, width=1317, height=720, text="Boundary ratio")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        archiver.validate_thumbnail(output_path)


def test_validate_thumbnail_permission_error(tmp_path):
    archiver = ProjectArchiver()
    output_path = tmp_path / "no_permission.png"
    archiver.generate_thumbnail(output_path)
    
    # PermissionErrorを模擬する
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            archiver.validate_thumbnail(output_path)


def test_validate_thumbnail_unknown_exception(tmp_path):
    archiver = ProjectArchiver()
    output_path = tmp_path / "unknown_error.png"
    archiver.generate_thumbnail(output_path)
    
    original_open = Image.open
    call_count = 0
    def mock_open(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("Arbitrary internal error")
        return original_open(*args, **kwargs)
        
    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError, match="Failed to load image for resolution check"):
            archiver.validate_thumbnail(output_path)


@pytest.mark.asyncio
async def test_resolve_thumbnail_task_invalid_task_id(tmp_path):
    archiver = ProjectArchiver()
    archiver.output_dir = tmp_path
    task_id = "invalid_id_with/slash"
    result_str = await archiver.resolve_thumbnail_task(task_id)
    result_info = json.loads(result_str)
    expected_path = tmp_path / "invalid_id_with" / "slash.png"
    assert result_info["path"] == str(expected_path)
    assert expected_path.exists()

def test_runpy_warning_resolved(temp_archive_env):
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        runpy.run_path("backend/project_archiver.py", run_name="__main__")
        
        runtime_warnings = [
            warn for warn in w 
            if issubclass(warn.category, RuntimeWarning) 
            and "found in sys.modules" in str(warn.message)
        ]
        assert len(runtime_warnings) == 0, f"RuntimeWarning detected: {runtime_warnings}"
