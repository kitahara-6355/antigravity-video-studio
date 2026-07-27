import os
import json
import shutil
import pytest
import runpy
import sys
from unittest.mock import patch

# project_archiver をインポートして、定数を一時ディレクトリに差し替えるためのフィクスチャ
@pytest.fixture
def mock_archiver(tmp_path, monkeypatch):
    import project_archiver
    
    tmp_archive = tmp_path / "archives"
    tmp_src = tmp_path / "src"
    tmp_src.mkdir(exist_ok=True)
    
    # 定数を差し替え
    monkeypatch.setattr(project_archiver, "ARCHIVE_DIR", str(tmp_archive))
    monkeypatch.setattr(project_archiver, "FILES_TO_BACKUP", {
        "scenes": str(tmp_src / "scenes_data.json"),
        "segments": str(tmp_src / "segments_a_plus_plus.json")
    })
    
    # グローバルインスタンスの属性も更新
    # ProjectArchiverのコンストラクタが再び走るようにし、新しいARCHIVE_DIRを作成させる
    archiver = project_archiver.ProjectArchiver()
    monkeypatch.setattr(project_archiver, "project_archiver", archiver)
    
    return archiver, tmp_src, tmp_archive

def test_project_archiver_init(tmp_path, monkeypatch):
    import project_archiver
    tmp_archive = tmp_path / "new_archives"
    
    monkeypatch.setattr(project_archiver, "ARCHIVE_DIR", str(tmp_archive))
    assert not tmp_archive.exists()
    
    # インスタンス化によりディレクトリが作成されることを確認
    archiver = project_archiver.ProjectArchiver()
    assert tmp_archive.exists()

def test_save_snapshot_success(mock_archiver):
    archiver, tmp_src, tmp_archive = mock_archiver
    
    # テスト用元ファイルを作成
    scenes_data = {"scenes": []}
    segments_data = {"segments": []}
    
    import project_archiver
    scenes_path = project_archiver.FILES_TO_BACKUP["scenes"]
    segments_path = project_archiver.FILES_TO_BACKUP["segments"]
    
    with open(scenes_path, "w", encoding="utf-8") as f:
        json.dump(scenes_data, f)
    with open(segments_path, "w", encoding="utf-8") as f:
        json.dump(segments_data, f)
        
    # 保存実行
    snapshot_id = archiver.save_snapshot(project_name="test_proj", label="test_label")
    
    assert snapshot_id is not None
    assert "test_proj_test_label_" in snapshot_id
    
    # スナップショット先フォルダの存在確認
    dest_dir = os.path.join(tmp_archive, snapshot_id)
    assert os.path.exists(dest_dir)
    assert os.path.exists(os.path.join(dest_dir, "scenes.json"))
    assert os.path.exists(os.path.join(dest_dir, "segments.json"))
    assert os.path.exists(os.path.join(dest_dir, "metadata.json"))
    
    # メタデータの内容確認
    with open(os.path.join(dest_dir, "metadata.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)
        assert meta["snapshot_id"] == snapshot_id
        assert meta["project_name"] == "test_proj"
        assert meta["label"] == "test_label"
        assert "scenes" in meta["files"]
        assert "segments" in meta["files"]

def test_save_snapshot_no_files(mock_archiver):
    archiver, tmp_src, tmp_archive = mock_archiver
    
    # 元ファイルを作成せずに実行
    snapshot_id = archiver.save_snapshot(project_name="empty_proj", label="empty_label")
    
    dest_dir = os.path.join(tmp_archive, snapshot_id)
    assert os.path.exists(dest_dir)
    # ファイルはコピーされていないはず
    assert not os.path.exists(os.path.join(dest_dir, "scenes.json"))
    assert not os.path.exists(os.path.join(dest_dir, "segments.json"))
    
    # メタデータは作成され、filesは空のはず
    with open(os.path.join(dest_dir, "metadata.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)
        assert meta["files"] == []

def test_list_snapshots(mock_archiver):
    archiver, tmp_src, tmp_archive = mock_archiver
    
    # snapshotフォルダとメタデータを手動でいくつか作成してテスト
    snap1_path = os.path.join(tmp_archive, "projA_label_20260521_100000")
    os.makedirs(snap1_path, exist_ok=True)
    meta1 = {
        "snapshot_id": "projA_label_20260521_100000",
        "project_name": "projA",
        "label": "label",
        "timestamp": "20260521_100000",
        "files": []
    }
    with open(os.path.join(snap1_path, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta1, f)
        
    snap2_path = os.path.join(tmp_archive, "projB_label_20260521_110000")
    os.makedirs(snap2_path, exist_ok=True)
    meta2 = {
        "snapshot_id": "projB_label_20260521_110000",
        "project_name": "projB",
        "label": "label",
        "timestamp": "20260521_110000",
        "files": []
    }
    with open(os.path.join(snap2_path, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta2, f)
        
    # リスト取得 (全体、ソート順の確認。最新の20260521_110000が最初に来るはず)
    snapshots = archiver.list_snapshots()
    assert len(snapshots) == 2
    assert snapshots[0]["snapshot_id"] == "projB_label_20260521_110000"
    assert snapshots[1]["snapshot_id"] == "projA_label_20260521_100000"
    
    # フィルタリング
    proj_a_snaps = archiver.list_snapshots(project_name="projA")
    assert len(proj_a_snaps) == 1
    assert proj_a_snaps[0]["snapshot_id"] == "projA_label_20260521_100000"
    
    # 空のディレクトリチェックのため、ARCHIVE_DIR が存在しないケースをシミュレート
    import project_archiver
    original_archive_dir = project_archiver.ARCHIVE_DIR
    try:
        shutil.rmtree(tmp_archive)
        assert archiver.list_snapshots() == []
    finally:
        os.makedirs(original_archive_dir, exist_ok=True)

def test_restore_snapshot_success(mock_archiver):
    archiver, tmp_src, tmp_archive = mock_archiver
    
    import project_archiver
    scenes_path = project_archiver.FILES_TO_BACKUP["scenes"]
    
    # スナップショットデータを用意
    snap_id = "test_restore_123"
    snap_path = os.path.join(tmp_archive, snap_id)
    os.makedirs(snap_path, exist_ok=True)
    
    snap_scenes_path = os.path.join(snap_path, "scenes.json")
    snap_data = {"restored": True}
    with open(snap_scenes_path, "w", encoding="utf-8") as f:
        json.dump(snap_data, f)
        
    # 現在のシーンファイルも作成しておく（auto_before_restoreに保存されるため）
    current_data = {"current": True}
    with open(scenes_path, "w", encoding="utf-8") as f:
        json.dump(current_data, f)
        
    # 復元実行
    result = archiver.restore_snapshot(snap_id)
    assert result is True
    
    # 復元されたファイルの確認
    with open(scenes_path, "r", encoding="utf-8") as f:
        restored = json.load(f)
        assert restored == snap_data
        
    # auto_before_restore スナップショットが作成されていることを確認
    snaps = archiver.list_snapshots()
    auto_snaps = [s for s in snaps if s["label"] == "auto_before_restore"]
    assert len(auto_snaps) == 1
    auto_snap_dir = os.path.join(tmp_archive, auto_snaps[0]["snapshot_id"])
    with open(os.path.join(auto_snap_dir, "scenes.json"), "r", encoding="utf-8") as f:
        saved_before = json.load(f)
        assert saved_before == current_data

def test_restore_snapshot_not_found(mock_archiver):
    archiver, tmp_src, tmp_archive = mock_archiver
    
    with pytest.raises(FileNotFoundError):
        archiver.restore_snapshot("nonexistent_snapshot_id")

# 再帰を防ぐためのグローバルフラグ
_in_mock_join = False
_in_mock_abs = False

def test_main_block(tmp_path, monkeypatch):
    # sys.modulesから一度削除して、再ロードさせる
    sys.modules.pop("project_archiver", None)
    
    tmp_archive = tmp_path / "archives"
    tmp_src = tmp_path / "src"
    tmp_src.mkdir(parents=True, exist_ok=True)
    tmp_archive.mkdir(parents=True, exist_ok=True)
    
    # 元ファイルを作成しておく
    scenes_path = tmp_src / "scenes_data.json"
    with open(scenes_path, "w", encoding="utf-8") as f:
        json.dump({"test": "main"}, f)
        
    # os.path.abspath と os.path.join を差し替えるための関数
    original_abspath = os.path.abspath
    original_join = os.path.join
    
    def mock_abspath(path):
        global _in_mock_abs
        if _in_mock_abs:
            return original_abspath(path)
        _in_mock_abs = True
        try:
            if "project_archiver.py" in path:
                return str(tmp_path / "backend" / "project_archiver.py")
            return original_abspath(path)
        finally:
            _in_mock_abs = False
        
    def mock_join(*args):
        global _in_mock_join
        if _in_mock_join:
            return original_join(*args)
        _in_mock_join = True
        try:
            if any(isinstance(a, str) and "scenes_data.json" in a for a in args):
                return str(tmp_src / "scenes_data.json")
            if any(isinstance(a, str) and "segments_a_plus_plus.json" in a for a in args):
                return str(tmp_src / "segments_a_plus_plus.json")
            if any(isinstance(a, str) and "projects" in a for a in args):
                return str(tmp_archive)
            return original_join(*args)
        finally:
            _in_mock_join = False
        
    monkeypatch.setattr(sys, "argv", ["project_archiver.py"])
    
    # runpy.run_module を実行
    with patch("os.path.abspath", side_effect=mock_abspath), \
         patch("os.path.join", side_effect=mock_join):
        mod_globals = runpy.run_module("project_archiver", run_name="__main__")
        
    # 実行後、スナップショットが作られていることを確認
    assert mod_globals["ARCHIVE_DIR"] == str(tmp_archive)
    
    # スナップショットの一覧を取得
    archiver = mod_globals["project_archiver"]
    snaps = archiver.list_snapshots()
    test_snaps = [s for s in snaps if s["label"] == "test"]
    assert len(test_snaps) >= 1


def test_save_snapshot_validation_errors(mock_archiver):
    archiver, tmp_src, tmp_archive = mock_archiver
    
    # 不正なプロジェクト名で ValueError が発生することを確認
    with pytest.raises(ValueError, match="Invalid characters in project_name"):
        archiver.save_snapshot(project_name="invalid/name", label="manual")
        
    with pytest.raises(ValueError, match="Invalid characters in project_name"):
        archiver.save_snapshot(project_name="../invalid", label="manual")

    with pytest.raises(ValueError, match="Invalid characters in project_name"):
        archiver.save_snapshot(project_name="invalid;name", label="manual")

    # 不正なラベル名で ValueError が発生することを確認
    with pytest.raises(ValueError, match="Invalid characters in label"):
        archiver.save_snapshot(project_name="default", label="invalid/label")

    with pytest.raises(ValueError, match="Invalid characters in label"):
        archiver.save_snapshot(project_name="default", label="..")

def test_restore_snapshot_validation_errors(mock_archiver):
    archiver, tmp_src, tmp_archive = mock_archiver
    
    # 不正な snapshot_id (トラバーサルや不正文字) で ValueError が発生することを確認
    with pytest.raises(ValueError, match="Invalid characters in snapshot_id"):
        archiver.restore_snapshot("invalid/id")
        
    with pytest.raises(ValueError, match="Invalid characters in snapshot_id"):
        archiver.restore_snapshot("../parent_dir")

    with pytest.raises(ValueError, match="Invalid characters in snapshot_id"):
        archiver.restore_snapshot("")

def test_list_snapshots_with_broken_metadata(mock_archiver):
    archiver, tmp_src, tmp_archive = mock_archiver
    
    # 正常なスナップショット
    snap_normal_path = os.path.join(tmp_archive, "normal_snap_20260521_120000")
    os.makedirs(snap_normal_path, exist_ok=True)
    meta_normal = {
        "snapshot_id": "normal_snap_20260521_120000",
        "project_name": "normal",
        "label": "manual",
        "timestamp": "20260521_120000",
        "files": []
    }
    with open(os.path.join(snap_normal_path, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta_normal, f)
        
    # 壊れた metadata.json (JSON 構文エラー)
    snap_broken_path = os.path.join(tmp_archive, "broken_snap_20260521_130000")
    os.makedirs(snap_broken_path, exist_ok=True)
    with open(os.path.join(snap_broken_path, "metadata.json"), "w", encoding="utf-8") as f:
        f.write("{invalid json...")
        
    # 正常なスナップショットが取得でき、壊れたスナップショットは安全にスキップされることを確認
    snapshots = archiver.list_snapshots()
    assert len(snapshots) == 1
    assert snapshots[0]["snapshot_id"] == "normal_snap_20260521_120000"

    # 安全な project_name 以外の指定で ValueError が発生することを確認
    with pytest.raises(ValueError, match="Invalid characters in project_name"):
        archiver.list_snapshots(project_name="invalid/name")

def test_validate_snapshot_path_path_traversal(mock_archiver):
    archiver, tmp_src, tmp_archive = mock_archiver
    
    # L42 をカバーするため、_is_safe_name を一時的にモックして True にし、
    # _validate_snapshot_path 内でトラバーサル条件(os.path.dirname(abs_snapshot) != abs_archive)をトリガーさせる
    import project_archiver
    with patch("project_archiver._is_safe_name", return_value=True):
        with pytest.raises(ValueError, match="Path traversal attempt detected"):
            archiver._validate_snapshot_path("../traversal_test")

def test_list_snapshots_skips_unsafe_directories(mock_archiver):
    archiver, tmp_src, tmp_archive = mock_archiver
    
    # 正常なスナップショット
    snap_normal_path = os.path.join(tmp_archive, "normal_snap_20260521_120000")
    os.makedirs(snap_normal_path, exist_ok=True)
    meta_normal = {
        "snapshot_id": "normal_snap_20260521_120000",
        "project_name": "normal",
        "label": "manual",
        "timestamp": "20260521_120000",
        "files": []
    }
    with open(os.path.join(snap_normal_path, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta_normal, f)
        
    # 安全でない名前のディレクトリ（L95 で _is_safe_name によりスキップされる）
    unsafe_dir_path = os.path.join(tmp_archive, "unsafe@dir")
    os.makedirs(unsafe_dir_path, exist_ok=True)
    meta_unsafe = {
        "snapshot_id": "unsafe@dir",
        "project_name": "unsafe",
        "label": "manual",
        "timestamp": "20260521_120000",
        "files": []
    }
    with open(os.path.join(unsafe_dir_path, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta_unsafe, f)
        
    # 正常なスナップショットのみが取得され、安全でないディレクトリはスキップされることを確認
    snapshots = archiver.list_snapshots()
    assert len(snapshots) == 1
    assert snapshots[0]["snapshot_id"] == "normal_snap_20260521_120000"


def test_list_snapshots_with_os_error_metadata(mock_archiver):
    import builtins
    archiver, tmp_src, tmp_archive = mock_archiver
    
    # 正常なスナップショット
    snap_normal_path = os.path.join(tmp_archive, "normal_snap_20260521_120000")
    os.makedirs(snap_normal_path, exist_ok=True)
    meta_normal = {
        "snapshot_id": "normal_snap_20260521_120000",
        "project_name": "normal",
        "label": "manual",
        "timestamp": "20260521_120000",
        "files": []
    }
    with open(os.path.join(snap_normal_path, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta_normal, f)
        
    # OSErrorを模擬するスナップショット
    snap_error_path = os.path.join(tmp_archive, "error_snap_20260521_130000")
    os.makedirs(snap_error_path, exist_ok=True)
    meta_error_path = os.path.join(snap_error_path, "metadata.json")
    with open(meta_error_path, "w", encoding="utf-8") as f:
        json.dump(meta_normal, f)
        
    original_open = builtins.open
    
    def mock_open(file, *args, **kwargs):
        normalized_file = os.path.abspath(str(file))
        normalized_target = os.path.abspath(meta_error_path)
        if normalized_file == normalized_target:
            raise OSError("Simulated permission or disk error")
        return original_open(file, *args, **kwargs)
        
    with patch("builtins.open", mock_open):
        snapshots = archiver.list_snapshots()
        
    # エラーになったスナップショットはスキップされ、正常なものだけ取得できることを確認
    assert len(snapshots) == 1
    assert snapshots[0]["snapshot_id"] == "normal_snap_20260521_120000"


def test_restore_snapshot_copy_failure(mock_archiver):
    archiver, tmp_src, tmp_archive = mock_archiver
    
    # スナップショットデータを用意
    snap_id = "test_restore_fail"
    snap_path = os.path.join(tmp_archive, snap_id)
    os.makedirs(snap_path, exist_ok=True)
    
    snap_scenes_path = os.path.join(snap_path, "scenes.json")
    with open(snap_scenes_path, "w", encoding="utf-8") as f:
        json.dump({"restored": True}, f)
        
    # 現在のシーンファイルも作成しておく（バックアップが走るため）
    import project_archiver
    scenes_path = project_archiver.FILES_TO_BACKUP["scenes"]
    with open(scenes_path, "w", encoding="utf-8") as f:
        json.dump({"current": True}, f)
        
    original_copy2 = shutil.copy2
    
    def mock_copy2(src, dst, *args, **kwargs):
        if "test_restore_fail" in str(src) and "scenes_data.json" in str(dst):
            raise OSError("Copy failed due to disk space or permission")
        return original_copy2(src, dst, *args, **kwargs)
        
    with patch("shutil.copy2", side_effect=mock_copy2):
        with pytest.raises(OSError, match="Copy failed due to disk space or permission"):
            archiver.restore_snapshot(snap_id)


def test_validation_errors_with_non_string_types(mock_archiver):
    archiver, tmp_src, tmp_archive = mock_archiver
    
    # project_name が None や int の場合、ValueError になることを確認
    with pytest.raises(ValueError, match="Invalid characters in project_name"):
        archiver.save_snapshot(project_name=None, label="manual")
        
    with pytest.raises(ValueError, match="Invalid characters in project_name"):
        archiver.save_snapshot(project_name=123, label="manual")

    with pytest.raises(ValueError, match="Invalid characters in label"):
        archiver.save_snapshot(project_name="default", label=None)

    # restore_snapshot に None や int を渡した場合
    with pytest.raises(ValueError, match="Invalid characters in snapshot_id"):
        archiver.restore_snapshot(None)

    with pytest.raises(ValueError, match="Invalid characters in snapshot_id"):
        archiver.restore_snapshot(456)
