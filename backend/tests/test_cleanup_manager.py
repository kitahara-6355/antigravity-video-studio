import os
import sys
import time
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.cleanup_manager import CleanupManager, CleanupRule, cleanup_manager


def test_cleanup_rule_dataclass():
    rule = CleanupRule(
        category="test",
        directory=Path("test_dir"),
        retention_days=5,
        max_count=10,
        protected=True,
        extensions=[".txt"]
    )
    assert rule.category == "test"
    assert rule.directory == Path("test_dir")
    assert rule.retention_days == 5
    assert rule.max_count == 10
    assert rule.protected is True
    assert rule.extensions == [".txt"]


def test_init_directory_creation_error():
    # OSError during mkdir in __init__
    with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
        manager = CleanupManager()
        # Should not raise exception, but log warning
        assert len(manager.rules) > 0


def test_is_protected():
    manager = CleanupManager()
    
    # Path is None
    assert manager.is_protected(None) is False
    
    # Invalid path format (e.g. ValueError or TypeError on Path creation)
    # Since Path accepts strings, we pass something that raises TypeError/ValueError in Path
    with patch("pathlib.Path", side_effect=TypeError("Invalid path")):
        assert manager.is_protected(12345) is False

    # Mock rule directories to verify behavior
    manager.rules = {
        "protected_dir": CleanupRule(
            category="protected_dir",
            directory=Path("/tmp/protected"),
            retention_days=None,
            max_count=None,
            protected=True
        ),
        "unprotected_dir": CleanupRule(
            category="unprotected_dir",
            directory=Path("/tmp/unprotected"),
            retention_days=None,
            max_count=None,
            protected=False
        )
    }

    # Protected path
    assert manager.is_protected("/tmp/protected/file.mp4") is True
    # Unprotected path
    assert manager.is_protected("/tmp/unprotected/file.mp4") is False
    # Unrelated path
    assert manager.is_protected("/tmp/other/file.mp4") is False

    # relative_to raises TypeError/ValueError in checking
    with patch("pathlib.Path.relative_to", side_effect=ValueError("Not in directory")):
        assert manager.is_protected("/tmp/protected/file.mp4") is False


def test_cleanup_argument_validation():
    manager = CleanupManager()
    
    # Category is not a string
    res = manager.cleanup(category=123)
    assert res["deleted"] == []
    
    # Category is unknown
    res = manager.cleanup(category="unknown_category")
    assert res["deleted"] == []


def test_cleanup_protected_category_skipped():
    manager = CleanupManager()
    # Mock a rule to be protected and track if directory exists is called
    protected_rule = CleanupRule(
        category="final",
        directory=Path("/tmp/final"),
        retention_days=None,
        max_count=None,
        protected=True
    )
    manager.rules = {"final": protected_rule}
    
    with patch("pathlib.Path.exists") as mock_exists:
        res = manager.cleanup(category="final")
        assert res["deleted"] == []
        mock_exists.assert_not_called()


def test_cleanup_directory_access_error(tmp_path):
    manager = CleanupManager()
    unprotected_rule = CleanupRule(
        category="temp",
        directory=tmp_path / "temp_dir",
        retention_days=7,
        max_count=10,
        protected=False
    )
    manager.rules = {"temp": unprotected_rule}
    
    # OSError when accessing directory.exists()
    with patch("pathlib.Path.exists", side_effect=OSError("Disk error")):
        res = manager.cleanup()
        assert res["deleted"] == []


def test_cleanup_glob_error(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "glob_test"
    test_dir.mkdir()
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=7,
        max_count=10,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}
    
    # OSError or TypeError during glob
    with patch("pathlib.Path.glob", side_effect=OSError("Glob failed")):
        res = manager.cleanup()
        assert res["deleted"] == []


def test_cleanup_retention_days(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "retention_test"
    test_dir.mkdir()
    
    # Create test files
    old_file = test_dir / "old_file.mp4"
    new_file = test_dir / "new_file.mp4"
    old_file.write_text("old")
    new_file.write_text("new")
    
    # Modify mtime
    now = time.time()
    os.utime(old_file, (now - 10 * 24 * 60 * 60, now - 10 * 24 * 60 * 60))  # 10 days old
    os.utime(new_file, (now - 1 * 24 * 60 * 60, now - 1 * 24 * 60 * 60))    # 1 day old
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=5,
        max_count=None,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}
    
    # Run cleanup
    res = manager.cleanup()
    assert str(old_file) in res["deleted"]
    assert str(new_file) not in res["deleted"]
    assert not old_file.exists()
    assert new_file.exists()


def test_cleanup_retention_days_exceptions(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "retention_ex_test"
    test_dir.mkdir()
    
    file1 = test_dir / "file1.mp4"
    file1.write_text("test")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=5,
        max_count=None,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}

    # Case 1: stat() raises FileNotFoundError or OSError
    with patch("pathlib.Path.stat", side_effect=FileNotFoundError):
        res = manager.cleanup()
        assert res["deleted"] == []

    # Case 2: TypeError/ValueError during retention days calculations
    with patch("time.time", side_effect=TypeError("Invalid time")):
        res = manager.cleanup()
        assert res["deleted"] == []


def test_cleanup_max_count(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "max_count_test"
    test_dir.mkdir()
    
    # Create 5 files
    files = []
    now = time.time()
    for i in range(5):
        f = test_dir / f"file_{i}.mp4"
        f.write_text(f"content {i}")
        # Set mtimes progressively older (file_0 is newest, file_4 is oldest)
        os.utime(f, (now - i * 100, now - i * 100))
        files.append(f)
        
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=None,
        max_count=2,  # Keep newest 2 (file_0 and file_1)
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}
    
    res = manager.cleanup()
    
    # Expected deleted: file_2, file_3, file_4 (older ones)
    assert str(files[0]) not in res["deleted"]
    assert str(files[1]) not in res["deleted"]
    assert str(files[2]) in res["deleted"]
    assert str(files[3]) in res["deleted"]
    assert str(files[4]) in res["deleted"]
    
    assert files[0].exists()
    assert files[1].exists()
    assert not files[2].exists()


def test_cleanup_max_count_exceptions(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "max_count_ex_test"
    test_dir.mkdir()
    
    f1 = test_dir / "file1.mp4"
    f1.write_text("test")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=None,
        max_count=1,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}

    # stat() raises FileNotFoundError/OSError inside valid_files loop
    original_stat = Path.stat
    def mock_stat(self, *args, **kwargs):
        if self.name == "file1.mp4":
            raise OSError("Stat error")
        return original_stat(self, *args, **kwargs)

    with patch.object(Path, "stat", mock_stat):
        res = manager.cleanup()
        assert res["deleted"] == []

    # ValueError during sort
    with patch("builtins.sorted", side_effect=ValueError("Sort error")):
        res = manager.cleanup()
        assert res["deleted"] == []


def test_cleanup_unlink_error(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "unlink_error_test"
    test_dir.mkdir()
    
    f1 = test_dir / "file1.mp4"
    f1.write_text("test")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=0,  # Mark all as old
        max_count=None,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}

    # Case 1: OSError during unlink
    with patch("pathlib.Path.unlink", side_effect=OSError("Access denied")):
        res = manager.cleanup()
        assert res["deleted"] == []

    # Case 2: Unexpected exception during unlink
    with patch("pathlib.Path.unlink", side_effect=ValueError("Unexpected unlink failure")):
        res = manager.cleanup()
        assert res["deleted"] == []


def test_cleanup_stat_size_error(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "stat_size_error_test"
    test_dir.mkdir()
    
    f1 = test_dir / "file1.mp4"
    f1.write_text("test")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=0,
        max_count=None,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}

    # stat() raises OSError only when accessed inside size computation in the cleanup loop
    original_stat = Path.stat
    def mock_stat(self, *args, **kwargs):
        res = original_stat(self, *args, **kwargs)
        if self.name == "file1.mp4":
            class BadStatResult:
                def __init__(self, orig):
                    self._orig = orig
                @property
                def st_size(self):
                    raise OSError("Size check failed")
                def __getattr__(self, name):
                    return getattr(self._orig, name)
            return BadStatResult(res)
        return res

    with patch("pathlib.Path.stat", mock_stat):
        res = manager.cleanup()
        assert str(f1) in res["deleted"]
        assert res["freed_bytes"] == 0


def test_cleanup_dry_run(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "dry_run_test"
    test_dir.mkdir()
    
    f1 = test_dir / "file1.mp4"
    f1.write_text("test")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=0,
        max_count=None,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}
    
    res = manager.cleanup(dry_run=True)
    assert str(f1) in res["deleted"]
    assert f1.exists()  # Not deleted in dry run


def test_get_storage_stats(tmp_path):
    manager = CleanupManager()
    
    test_dir = tmp_path / "stats_test"
    test_dir.mkdir()
    
    f1 = test_dir / "file1.mp4"
    # Write 2MB of dummy data to ensure size_mb > 0
    f1.write_text("a" * (2 * 1024 * 1024))
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=5,
        max_count=10,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}
    
    stats = manager.get_storage_stats()
    assert "temp" in stats["categories"]
    assert stats["categories"]["temp"]["count"] == 1
    assert stats["categories"]["temp"]["size_mb"] == 2.0
    assert stats["categories"]["temp"]["protected"] is False
    assert stats["categories"]["temp"]["retention_days"] == 5
    assert stats["categories"]["temp"]["max_count"] == 10
    assert stats["categories"]["temp"]["oldest_file"] is not None
    assert stats["categories"]["temp"]["newest_file"] is not None


def test_get_storage_stats_non_existent_directory():
    manager = CleanupManager()
    rule = CleanupRule(
        category="temp",
        directory=Path("/non_existent_dir_12345"),
        retention_days=5,
        max_count=10,
        protected=False
    )
    manager.rules = {"temp": rule}
    
    stats = manager.get_storage_stats()
    assert stats["categories"]["temp"]["count"] == 0
    assert stats["categories"]["temp"]["size_mb"] == 0


def test_get_storage_stats_exists_os_error():
    manager = CleanupManager()
    rule = CleanupRule(
        category="temp",
        directory=Path("/tmp/test_os_error"),
        retention_days=5,
        max_count=10,
        protected=False
    )
    manager.rules = {"temp": rule}
    
    with patch("pathlib.Path.exists", side_effect=OSError("Disk error")):
        stats = manager.get_storage_stats()
        assert stats["categories"]["temp"]["count"] == 0
        assert stats["categories"]["temp"]["size_mb"] == 0


def test_get_storage_stats_glob_and_stat_errors(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "stats_err_test"
    test_dir.mkdir()
    
    f1 = test_dir / "file1.mp4"
    f1.write_text("test")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=5,
        max_count=10,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}

    # Case 1: TypeError or OSError during glob
    with patch("pathlib.Path.glob", side_effect=TypeError("Invalid pattern")):
        stats = manager.get_storage_stats()
        assert stats["categories"]["temp"]["count"] == 0

    # Case 2: FileNotFoundError or OSError in stat calls
    with patch("pathlib.Path.stat", side_effect=FileNotFoundError):
        stats = manager.get_storage_stats()
        assert stats["categories"]["temp"]["count"] == 0


def test_preview_cleanup(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "preview_test"
    test_dir.mkdir()
    
    f1 = test_dir / "file1.mp4"
    f1.write_text("test")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=0,
        max_count=None,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}
    
    res = manager.preview_cleanup()
    assert str(f1) in res["deleted"]
    assert res["dry_run"] is True
    assert f1.exists()


def test_auto_cleanup_success(tmp_path):
    manager = CleanupManager()
    
    # Mock cleanup and report_to_evolution_log
    mock_cleanup_res = {"deleted": ["file1"], "protected": [], "freed_bytes": 1024 * 1024, "dry_run": False}
    manager.cleanup = MagicMock(return_value=mock_cleanup_res)
    manager.report_to_evolution_log = MagicMock()
    
    # Mock services
    mock_trigger_svc = MagicMock()
    mock_trigger_svc._load_evolution_log = MagicMock(return_value={})
    mock_trigger_svc._trim_trust_history = MagicMock()
    mock_trigger_svc._save_evolution_log = MagicMock()
    
    mock_proposal_svc = MagicMock()
    mock_proposal_svc._trim_pending_proposals = MagicMock()
    
    with patch("services.evolution_trigger_service.EvolutionTriggerService", return_value=mock_trigger_svc), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", return_value=mock_proposal_svc):
        
        res = manager.auto_cleanup()
        
        assert res == mock_cleanup_res
        manager.cleanup.assert_called_once()
        mock_trigger_svc._load_evolution_log.assert_called_once()
        mock_trigger_svc._trim_trust_history.assert_called_once()
        mock_trigger_svc._save_evolution_log.assert_called_once()
        mock_proposal_svc._trim_pending_proposals.assert_called_once()
        manager.report_to_evolution_log.assert_called_once_with(mock_cleanup_res)


def test_auto_cleanup_service_exceptions():
    manager = CleanupManager()
    manager.cleanup = MagicMock(return_value={})
    manager.report_to_evolution_log = MagicMock()
    
    # Trigger exception in EvolutionTriggerService
    with patch("services.evolution_trigger_service.EvolutionTriggerService", side_effect=ImportError("Import failed")), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", side_effect=ImportError("Import failed")):
        # Should not raise exception
        res = manager.auto_cleanup()
        assert res == {}


def test_report_to_evolution_log_validation():
    manager = CleanupManager()
    
    # Non-dictionary cleanup result
    with patch("logging.Logger.error") as mock_log_err:
        manager.report_to_evolution_log("invalid_result")
        # Should log error and return
        mock_log_err.assert_called()

    # Invalid evolution_log_path format
    with patch("pathlib.Path", side_effect=TypeError("Invalid type")):
        manager.report_to_evolution_log({}, evolution_log_path=12345)


def test_report_to_evolution_log_write(tmp_path):
    manager = CleanupManager()
    
    log_file = tmp_path / "evolution_log.json"
    cleanup_res = {
        "deleted": ["/tmp/file1.mp4", "/tmp/file2.mp4"],
        "protected": ["/tmp/protected.mp4"],
        "freed_bytes": 2 * 1024 * 1024,
        "dry_run": False
    }
    
    # Mock safe_load_json and safe_save_json
    mock_log_data = {"entries": []}
    
    with patch("utils.json_safe_io.safe_load_json", return_value=mock_log_data) as mock_load, \
         patch("utils.json_safe_io.safe_save_json") as mock_save:
        
        manager.report_to_evolution_log(cleanup_res, evolution_log_path=log_file)
        
        mock_load.assert_called_once_with(Path(log_file))
        mock_save.assert_called_once()
        
        # Verify saved data structure
        saved_data = mock_save.call_args[0][1]
        assert len(saved_data["entries"]) == 1
        entry = saved_data["entries"][0]
        assert entry["type"] == "storage_cleanup"
        assert entry["deleted_count"] == 2
        assert entry["freed_mb"] == 2.0
        assert entry["protected_count"] == 1
        assert entry["dry_run"] is False
        assert "Auto cleanup: 2 files" in entry["summary"]


def test_report_to_evolution_log_exceptions(tmp_path):
    manager = CleanupManager()
    log_file = tmp_path / "evolution_log.json"
    
    # Exception during loading/saving
    with patch("utils.json_safe_io.safe_load_json", side_effect=OSError("Read error")):
        # Should not raise exception
        manager.report_to_evolution_log({}, evolution_log_path=log_file)


def test_singleton_instance():
    assert isinstance(cleanup_manager, CleanupManager)


# --- 未カバー行の完全網羅テスト ---

def test_is_protected_type_error():
    manager = CleanupManager()
    manager.rules = {
        "protected_dir": CleanupRule(
            category="protected_dir",
            directory=Path("/tmp/protected"),
            retention_days=None,
            max_count=None,
            protected=True
        )
    }
    # TypeError during relative_to verification inside is_protected
    with patch("pathlib.Path.relative_to", side_effect=TypeError("Type error")):
        assert manager.is_protected("/tmp/protected/file.mp4") is False


def test_cleanup_non_existent_directory_skipped():
    manager = CleanupManager()
    rule = CleanupRule(
        category="temp",
        directory=Path("/non_existent_dir_12345"),
        retention_days=5,
        max_count=10,
        protected=False
    )
    manager.rules = {"temp": rule}
    res = manager.cleanup()
    assert res["deleted"] == []


def test_cleanup_empty_directory_skipped(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "empty_dir"
    test_dir.mkdir()
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=5,
        max_count=10,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}
    res = manager.cleanup()
    assert res["deleted"] == []


def test_cleanup_retention_stat_error(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "retention_stat_err_test"
    test_dir.mkdir()
    
    f1 = test_dir / "file1.mp4"
    f1.write_text("test")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=5,
        max_count=None,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}

    # f.stat() raises FileNotFoundError inside retention days check loop
    original_stat = Path.stat
    def mock_stat(self, *args, **kwargs):
        if self.name == "file1.mp4":
            raise FileNotFoundError("Mock file not found")
        return original_stat(self, *args, **kwargs)

    with patch("pathlib.Path.stat", mock_stat):
        res = manager.cleanup()
        assert res["deleted"] == []


def test_cleanup_protected_file_in_delete_list(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "protected_test"
    test_dir.mkdir()
    
    f1 = test_dir / "protected_file.mp4"
    f1.write_text("test")
    
    # Force mock_stat to return very old mtime to trigger deletion logic
    now = time.time()
    os.utime(f1, (now - 10 * 24 * 60 * 60, now - 10 * 24 * 60 * 60))
    
    # Set rule: category 'temp' is not protected, but rule 'final' protects test_dir/protected_file.mp4
    manager.rules = {
        "temp": CleanupRule(
            category="temp",
            directory=test_dir,
            retention_days=5,
            max_count=None,
            protected=False,
            extensions=[".mp4"]
        ),
        "final": CleanupRule(
            category="final",
            directory=test_dir,  # Protect the same directory
            retention_days=None,
            max_count=None,
            protected=True,
            extensions=[".mp4"]
        )
    }
    
    res = manager.cleanup()
    # Should not delete protected_file.mp4 because it falls under the protected rule 'final'
    assert str(f1) not in res["deleted"]
    assert str(f1) in res["protected"]
    assert f1.exists()


def test_get_storage_stats_stat_error_skipped(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "stats_skipped_test"
    test_dir.mkdir()
    
    f1 = test_dir / "file1.mp4"
    f1.write_text("test")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=5,
        max_count=10,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}

    # stat() raises FileNotFoundError inside get_storage_stats stats collector loop
    original_stat = Path.stat
    def mock_stat(self, *args, **kwargs):
        if self.name == "file1.mp4" and "is_file" not in str(sys._getframe(1).f_code.co_names):
            raise FileNotFoundError("Mock file not found")
        return original_stat(self, *args, **kwargs)

    with patch("pathlib.Path.stat", mock_stat):
        stats = manager.get_storage_stats()
        # Count should be 0 because stat() failed
        assert stats["categories"]["temp"]["count"] == 0


def test_get_storage_stats_protected_size(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "stats_protected_test"
    test_dir.mkdir()
    
    f1 = test_dir / "file1.mp4"
    f1.write_text("a" * (2 * 1024 * 1024))  # 2MB
    
    rule = CleanupRule(
        category="final",
        directory=test_dir,
        retention_days=None,
        max_count=None,
        protected=True,
        extensions=[".mp4"]
    )
    manager.rules = {"final": rule}
    
    stats = manager.get_storage_stats()
    assert stats["protected_size_mb"] == 2.0
    assert stats["deletable_size_mb"] == 0.0


def test_report_to_evolution_log_default_path():
    manager = CleanupManager()
    
    cleanup_res = {
        "deleted": ["/tmp/file1.mp4"],
        "protected": [],
        "freed_bytes": 1024 * 1024,
        "dry_run": False
    }
    
    mock_log_data = {"entries": []}
    
    with patch("utils.json_safe_io.safe_load_json", return_value=mock_log_data) as mock_load, \
         patch("utils.json_safe_io.safe_save_json") as mock_save:
        
        manager.report_to_evolution_log(cleanup_res, evolution_log_path=None)

        # 既定パスは writable_path で解決される。__file__ 起点で直接
        # 組み立てると本番の evolution_log.json を指してしまい、テストが
        # Git 追跡下のファイルを書き換える。
        from path_resolver import writable_path
        expected_path = writable_path("backend/branding/evolution_log.json")
        mock_load.assert_called_once_with(expected_path)
        mock_save.assert_called_once()


def test_is_protected_relative_and_case_mixing():
    manager = CleanupManager()
    
    # 実際にある親ディレクトリを元に、保護ルールを追加する
    # ドライブレターやスラッシュの表記を変えたパスを用意
    base_path_str = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "temp", "drafts", "final"))
    resolved_base = Path(base_path_str)
    
    # ドライブレターが大文字の場合と小文字の場合などをシミュレート
    # ドライブレターを小文字化、または大文字化
    drive, tail = os.path.splitdrive(base_path_str)
    if drive:
        lower_drive_path = drive.lower() + tail
        upper_drive_path = drive.upper() + tail
    else:
        lower_drive_path = base_path_str
        upper_drive_path = base_path_str

    manager.rules = {
        "final": CleanupRule(
            category="final",
            directory=resolved_base,
            retention_days=None,
            max_count=None,
            protected=True,
            extensions=[".mp4"]
        )
    }

    # テスト1: 相対パスでの呼び出し
    # カレントディレクトリからの相対パスで表現
    rel_file = os.path.relpath(os.path.join(base_path_str, "protected_file.mp4"))
    assert manager.is_protected(rel_file) is True

    # テスト2: ドライブレターの大文字小文字違い (Windows依存)
    if os.name == 'nt':
        assert manager.is_protected(os.path.join(lower_drive_path, "protected_file.mp4")) is True
        assert manager.is_protected(os.path.join(upper_drive_path, "protected_file.mp4")) is True


def test_auto_cleanup_exception_logging():
    manager = CleanupManager()
    manager.cleanup = MagicMock(return_value={})
    manager.report_to_evolution_log = MagicMock()

    # Exception inside auto_cleanup trigger_svc or proposal_svc
    # detailed log with exception stack trace should be outputted
    with patch("services.evolution_trigger_service.EvolutionTriggerService", side_effect=OSError("Database connection failure")), \
         patch("logging.Logger.warning") as mock_warn:
        manager.auto_cleanup()
        # warning should log with traceback info
        assert mock_warn.called
        # Check if traceback / exception info was passed
        args, kwargs = mock_warn.call_args
        assert any("database connection failure" in str(arg).lower() for arg in args) or any("database connection failure" in str(val).lower() for val in kwargs.values()) or kwargs.get('exc_info') is True



def test_cleanup_non_recursive_glob(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "glob_non_recursive"
    test_dir.mkdir()
    
    f_direct = test_dir / "file_direct.mp4"
    f_direct.write_text("direct")
    
    sub_dir = test_dir / "subdir"
    sub_dir.mkdir()
    f_subdir = sub_dir / "file_subdir.mp4"
    f_subdir.write_text("subdir")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=0,
        max_count=None,
        protected=False,
        extensions=["*"]
    )
    manager.rules = {"temp": rule}
    
    res = manager.cleanup()
    
    assert str(f_direct) in res["deleted"]
    assert str(f_subdir) not in res["deleted"]
    assert not f_direct.exists()
    assert f_subdir.exists()


def test_cleanup_glob_type_error(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "glob_type_error"
    test_dir.mkdir()
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=7,
        max_count=10,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}
    
    with patch("pathlib.Path.glob", side_effect=TypeError("Mock TypeError")):
        res = manager.cleanup()
        assert res["deleted"] == []


def test_cleanup_glob_value_error(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "glob_value_error"
    test_dir.mkdir()
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=7,
        max_count=10,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}
    
    with patch("pathlib.Path.glob", side_effect=ValueError("Mock ValueError")):
        res = manager.cleanup()
        assert res["deleted"] == []


def test_get_storage_stats_glob_type_error(tmp_path):
    manager = CleanupManager()
    test_dir = tmp_path / "stats_type_error"
    test_dir.mkdir()
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=5,
        max_count=10,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}
    
    with patch("pathlib.Path.glob", side_effect=TypeError("Mock TypeError")):
        stats = manager.get_storage_stats()
        assert stats["categories"]["temp"]["count"] == 0


# --- Phase 30 追加テストケース (大文字小文字対応および遅延ディレクトリ作成の検証) ---

def test_cleanup_case_insensitive_glob(tmp_path):
    """大文字拡張子（.MP4, .PNG）のファイルが正しく削除対象になることを検証 (Python 3.13 挙動検証)"""
    manager = CleanupManager()
    test_dir = tmp_path / "case_insensitive_glob_test"
    test_dir.mkdir(parents=True, exist_ok=True)

    # 大文字・小文字の混在する拡張子を持つファイルを作成
    file_lower = test_dir / "test_video.mp4"
    file_upper = test_dir / "test_video_upper.MP4"
    file_mixed = test_dir / "test_video_mixed.Mp4"
    
    file_lower.write_text("lower")
    file_upper.write_text("upper")
    file_mixed.write_text("mixed")

    # 10日前の一時ファイルとするために mtime を変更
    now = time.time()
    cutoff = now - 10 * 24 * 60 * 60
    os.utime(file_lower, (cutoff, cutoff))
    os.utime(file_upper, (cutoff, cutoff))
    os.utime(file_mixed, (cutoff, cutoff))

    # カテゴリのルールを設定
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=5,
        max_count=None,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}

    # クリーンアップ実行
    res = manager.cleanup(category="temp")

    # 大文字・小文字・混在のすべてが削除されていることを確認
    assert str(file_lower) in res["deleted"]
    assert str(file_upper) in res["deleted"]
    assert str(file_mixed) in res["deleted"]
    assert not file_lower.exists()
    assert not file_upper.exists()
    assert not file_mixed.exists()


def test_is_protected_case_insensitive_path():
    """Linux 環境等を想定し、保護ディレクトリと判定対象パスの大文字小文字に差があっても正しく保護されることを検証"""
    manager = CleanupManager()
    
    # 大文字小文字の差を混ぜたパスを設定
    # final ディレクトリのルールを定義
    rule = CleanupRule(
        category="final",
        directory=Path("/var/Temp/Drafts/Final"),
        retention_days=None,
        max_count=None,
        protected=True
    )
    manager.rules = {"final": rule}

    # 異なるケース（すべて小文字）のファイルパスで判定
    test_path_lower = "/var/temp/drafts/final/output_video.mp4"
    assert manager.is_protected(test_path_lower) is True

    # 異なるケース（大文字混ざり）のファイルパスで判定
    test_path_mixed = "/VAR/TEMP/DRAFTS/FINAL/OUTPUT_VIDEO.MP4"
    assert manager.is_protected(test_path_mixed) is True


def test_lazy_directory_creation_on_import():
    """CleanupManagerのインスタンス化（インポート）の時点では実ディレクトリが作成されず、
    実際の操作（cleanup, get_storage_stats）のタイミングで初めてディレクトリが作成されることを検証"""
    # 一時的なルール構成を設定
    test_rule_dir = Path("./temp_lazy_test_dir_not_exist")
    if test_rule_dir.exists():
        try:
            test_rule_dir.rmdir()
        except OSError:
            pass

    # cleanup_manager がインポートされた状態を模した、新規インスタンス生成時の挙動を確認
    with patch("pathlib.Path.mkdir") as mock_mkdir:
        # インスタンス生成
        manager = CleanupManager()
        # rules を上書き
        manager.rules = {
            "lazy_test": CleanupRule(
                category="lazy_test",
                directory=test_rule_dir,
                retention_days=7,
                max_count=5,
                protected=False,
                extensions=[".mp4"]
            )
        }
        # インスタンス化のタイミングでは mkdir は一切呼ばれないことを検証
        mock_mkdir.assert_not_called()

        # cleanup または get_storage_stats を呼ぶと初めて mkdir が実行されることを検証
        with patch("pathlib.Path.exists", return_value=True):
            manager.get_storage_stats()
            assert mock_mkdir.call_count >= 1


# --- Phase 30 新規追加：エラーハンドリング強化とロバストソートの検証 ---

def test_cleanup_max_count_robust_against_missing_file_during_sort(tmp_path):
    """ソート中にファイルが削除されたり、アクセス不可になっても、
    事前に取得した mtime に基づき安全にソート及びクリーンアップが継続されることを検証"""
    import builtins
    manager = CleanupManager()
    test_dir = tmp_path / "robust_sort_test"
    test_dir.mkdir()
    
    # 3つのファイルを作成
    files = []
    now = time.time()
    for i in range(3):
        f = test_dir / f"file_{i}.mp4"
        f.write_text(f"content {i}")
        os.utime(f, (now - i * 100, now - i * 100))
        files.append(f)

    # 1つだけ保護されていない状態で、max_count を 1 に設定して古いものを消す設定にする
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=None,
        max_count=1,  # 最新の1つだけ残す (file_0 が最新, file_1, file_2 を消す)
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}

    original_sorted = builtins.sorted
    in_sorted = False

    def mock_sorted(*args, **kwargs):
        nonlocal in_sorted
        in_sorted = True
        try:
            return original_sorted(*args, **kwargs)
        finally:
            in_sorted = False

    original_stat = Path.stat
    def mock_stat(self, *args, **kwargs):
        if in_sorted:
            # sorted() の実行中に Path.stat が呼ばれたらエラーを投げる
            raise RuntimeError("Path.stat() was called during sorted()!")
        return original_stat(self, *args, **kwargs)

    with patch("builtins.sorted", mock_sorted), \
         patch.object(Path, "stat", mock_stat):
        res = manager.cleanup()
        # file_0 は残り、file_1, file_2 は削除対象（dry_runではないので削除される）
        assert str(files[0]) not in res["deleted"]
        assert str(files[1]) in res["deleted"]
        assert str(files[2]) in res["deleted"]


def test_auto_cleanup_specific_exception_types():
    """auto_cleanup で発生したインポートエラーとその他の例外が
    適切なログレベルと個別の try-except 階層でハンドリングされることを検証"""
    import builtins
    manager = CleanupManager()
    manager.cleanup = MagicMock(return_value={})
    manager.report_to_evolution_log = MagicMock()

    # Case 1: ImportError / ModuleNotFoundError
    # ログには INFO レベルで「unavailable」が記録され、初期化に失敗しないこと
    original_import = builtins.__import__
    def mock_import(name, globals=None, locals=None, fromlist=(), level=0):
        if "evolution_trigger_service" in name or "philosophy_proposal_service" in name:
            raise ImportError("Mock import failure")
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", mock_import), \
         patch("logging.Logger.info") as mock_info, \
         patch("logging.Logger.warning") as mock_warn:
         
        res = manager.auto_cleanup()
        assert res == {}
        # インポートエラーは警告ではなく INFO として出力される
        assert any("is unavailable" in args[0] for args, _ in mock_info.call_args_list)
        # warning は出力されない
        assert not any("trim失敗" in args[0] for args, _ in mock_warn.call_args_list)

    # Case 2: OSError (I/O エラー)
    # _load_evolution_log 等で発生した OSError が個別にキャッチされ、警告が出力されること
    mock_trigger_svc = MagicMock()
    mock_trigger_svc._load_evolution_log.side_effect = OSError("Read failed")
    
    with patch("services.evolution_trigger_service.EvolutionTriggerService", return_value=mock_trigger_svc), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", side_effect=ImportError("Mock import failure")), \
         patch("logging.Logger.warning") as mock_warn:
         
        manager.auto_cleanup()
        # evolution log の読み込み失敗による警告が出力されること
        assert any("Failed to read/write evolution log file" in args[0] for args, _ in mock_warn.call_args_list)


# --- Phase 30 新規追加：カバレッジ網羅テスト ---

def test_cleanup_directory_not_exists_mock(tmp_path):
    manager = CleanupManager()
    rule = CleanupRule(
        category="temp",
        directory=tmp_path / "mock_non_existent",
        retention_days=5,
        max_count=10,
        protected=False
    )
    manager.rules = {"temp": rule}
    with patch.object(Path, "exists", return_value=False), \
         patch.object(Path, "mkdir"):
        res = manager.cleanup()
        assert res["deleted"] == []


def test_get_storage_stats_directory_not_exists_mock(tmp_path):
    manager = CleanupManager()
    rule = CleanupRule(
        category="temp",
        directory=tmp_path / "mock_non_existent",
        retention_days=5,
        max_count=10,
        protected=False
    )
    manager.rules = {"temp": rule}
    with patch.object(Path, "exists", return_value=False), \
         patch.object(Path, "mkdir"):
        stats = manager.get_storage_stats()
        assert stats["categories"]["temp"]["count"] == 0
        assert stats["categories"]["temp"]["size_mb"] == 0


def test_auto_cleanup_trust_history_trim_non_fatal_error():
    manager = CleanupManager()
    manager.cleanup = MagicMock(return_value={})
    manager.report_to_evolution_log = MagicMock()
    
    mock_trigger_svc = MagicMock()
    mock_trigger_svc._load_evolution_log.side_effect = ValueError("Trim parse error")
    
    with patch("services.evolution_trigger_service.EvolutionTriggerService", return_value=mock_trigger_svc), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", side_effect=ImportError), \
         patch("logging.Logger.warning") as mock_warn:
        
        manager.auto_cleanup()
        assert any("trust_history structure error" in args[0] for args, _ in mock_warn.call_args_list)


def test_auto_cleanup_proposal_service_init_error():
    manager = CleanupManager()
    manager.cleanup = MagicMock(return_value={})
    manager.report_to_evolution_log = MagicMock()
    
    with patch("services.evolution_trigger_service.EvolutionTriggerService", side_effect=ImportError), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", side_effect=ValueError("Init error")), \
         patch("logging.Logger.warning") as mock_warn:
         
        manager.auto_cleanup()
        assert any("PhilosophyProposalService initialization failed" in args[0] for args, _ in mock_warn.call_args_list)


def test_auto_cleanup_proposal_trim_errors():
    manager = CleanupManager()
    manager.cleanup = MagicMock(return_value={})
    manager.report_to_evolution_log = MagicMock()
    
    mock_proposal_svc = MagicMock()
    
    # Case 1: OSError
    mock_proposal_svc._trim_pending_proposals.side_effect = OSError("Trim OS error")
    with patch("services.evolution_trigger_service.EvolutionTriggerService", side_effect=ImportError), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", return_value=mock_proposal_svc), \
         patch("logging.Logger.warning") as mock_warn:
        
        manager.auto_cleanup()
        assert any("Failed to trim pending proposals file" in args[0] for args, _ in mock_warn.call_args_list)

    # Case 2: ValueError
    mock_proposal_svc._trim_pending_proposals.side_effect = ValueError("Trim value error")
    with patch("services.evolution_trigger_service.EvolutionTriggerService", side_effect=ImportError), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", return_value=mock_proposal_svc), \
         patch("logging.Logger.warning") as mock_warn:
        
        manager.auto_cleanup()
        assert any("pending_proposals structure error" in args[0] for args, _ in mock_warn.call_args_list)


def test_report_to_evolution_log_non_fatal_error(tmp_path):
    manager = CleanupManager()
    log_file = tmp_path / "evolution_log.json"
    
    with patch("utils.json_safe_io.safe_load_json", side_effect=ValueError("Format error")), \
         patch("logging.Logger.warning") as mock_warn:
        manager.report_to_evolution_log({}, evolution_log_path=log_file)
        assert any("evolution_logのデータ構造または形式が無効です" in args[0] for args, _ in mock_warn.call_args_list)



def test_ensure_directories_exist_invalid_type():
    """rule.directory が Path オブジェクトでなく mkdir が存在しない型（Noneなど）の場合に、
    _ensure_directories_exist がクラッシュせず警告ログを出力することを検証"""
    manager = CleanupManager()
    manager.rules = {
        "invalid_dir": CleanupRule(
            category="invalid_dir",
            directory=None,
            retention_days=None,
            max_count=None,
            protected=False
        )
    }
    with patch("logging.Logger.warning") as mock_warn:
        manager._ensure_directories_exist()
        assert mock_warn.called


def test_report_to_evolution_log_import_error():
    """json_safe_ioモジュールのインポートで ImportError/ModuleNotFoundError が発生した場合に、
    report_to_evolution_log がクラッシュせず警告ログを出力して処理を中断することを検証"""
    import builtins
    manager = CleanupManager()
    
    original_import = builtins.__import__
    def mock_import(name, globals=None, locals=None, fromlist=(), level=0):
        if "json_safe_io" in name:
            raise ImportError("Mock import failure for json_safe_io")
        return original_import(name, globals, locals, fromlist, level)
        
    with patch("builtins.__import__", mock_import),          patch("logging.Logger.warning") as mock_warn:
        manager.report_to_evolution_log({}, evolution_log_path=None)
        assert any("インポートに失敗しました" in args[0] for args, _ in mock_warn.call_args_list)


def test_cleanup_negative_retention_days_guard(tmp_path):
    """rule.retention_days に負の数（-5など）が設定された場合、
    全削除を防ぐために安全ガードが働き、retention_days を 0 として処理し、
    現在作成された新規ファイルが削除されないことを検証"""
    manager = CleanupManager()
    test_dir = tmp_path / "neg_retention"
    test_dir.mkdir()
    
    new_file = test_dir / "new.mp4"
    new_file.write_text("new")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=-5,
        max_count=None,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}
    
    with patch("logging.Logger.warning") as mock_warn:
        res = manager.cleanup()
        assert new_file.exists()
        assert str(new_file) not in res["deleted"]
        assert any("Negative retention_days detected" in args[0] for args, _ in mock_warn.call_args_list)


def test_cleanup_negative_max_count_guard(tmp_path):
    """rule.max_count に負の数（-5など）が設定された場合、
    全削除を防ぐために安全ガードが働き、ログを出力し、かつ
    max_count による制限（古いものの削除）を行わずにファイルを維持することを検証"""
    manager = CleanupManager()
    test_dir = tmp_path / "neg_max_count"
    test_dir.mkdir()
    
    f1 = test_dir / "file1.mp4"
    f2 = test_dir / "file2.mp4"
    f1.write_text("1")
    f2.write_text("2")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=None,
        max_count=-5,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}
    
    with patch("logging.Logger.warning") as mock_warn:
        res = manager.cleanup()
        assert f1.exists()
        assert f2.exists()
        assert str(f1) not in res["deleted"]
        assert str(f2) not in res["deleted"]
        assert any("Negative max_count detected" in args[0] for args, _ in mock_warn.call_args_list)


def test_cleanup_directory_attribute_error_handling():
    """existsメソッドを持たないなど、rule.directoryに異常な型（None等）が設定された場合に
    cleanup() が AttributeError を安全に捕捉してスキップすることを検証"""
    manager = CleanupManager()
    manager.rules = {
        "invalid_dir": CleanupRule(
            category="invalid_dir",
            directory=None,
            retention_days=None,
            max_count=None,
            protected=False
        )
    }
    with patch("logging.Logger.error") as mock_err:
        res = manager.cleanup()
        assert res["deleted"] == []
        assert any("Error accessing directory" in args[0] for args, _ in mock_err.call_args_list)


def test_get_storage_stats_directory_attribute_error_handling():
    """existsメソッドを持たないなど、rule.directoryに異常な型（None等）が設定された場合に
    get_storage_stats() が AttributeError を安全に捕捉してスキップすることを検証"""
    manager = CleanupManager()
    manager.rules = {
        "invalid_dir": CleanupRule(
            category="invalid_dir",
            directory=None,
            retention_days=None,
            max_count=None,
            protected=False
        )
    }
    with patch("logging.Logger.error") as mock_err:
        stats = manager.get_storage_stats()
        assert "invalid_dir" in stats["categories"]
        assert stats["categories"]["invalid_dir"]["count"] == 0
        assert any("Error checking directory existence" in args[0] for args, _ in mock_err.call_args_list)


def test_is_protected_invalid_type_guard():
    """is_protected に無効な型（辞書やリスト）が渡された場合、
    TypeErrorを発生させずに安全にガードし、Falseを返すことを検証"""
    manager = CleanupManager()
    with patch("logging.Logger.error") as mock_err:
        assert manager.is_protected({"invalid_key": "val"}) is False
        assert mock_err.called


def test_is_protected_type_error_warning_logged():
    """is_protected 内で TypeError が発生した際、警告ログ（exc_info=True）が出力されることを検証"""
    manager = CleanupManager()
    manager.rules = {
        "protected_dir": CleanupRule(
            category="protected_dir",
            directory=Path("/tmp/protected"),
            retention_days=None,
            max_count=None,
            protected=True
        )
    }
    # TypeError during relative_to verification inside is_protected
    with patch("pathlib.Path.relative_to", side_effect=TypeError("Type error simulation")), \
         patch("logging.Logger.warning") as mock_warn:
        assert manager.is_protected("/tmp/protected/file.mp4") is False
        assert mock_warn.called
        # Check if traceback / exception info (exc_info=True) was passed
        _, kwargs = mock_warn.call_args
        assert kwargs.get('exc_info') is True


def test_cleanup_unlink_os_error_info_logged(tmp_path):
    """cleanup の unlink 時に OSError が発生した際、エラーログ（exc_info=True）が出力されることを検証"""
    manager = CleanupManager()
    test_dir = tmp_path / "unlink_os_error_test"
    test_dir.mkdir()
    
    f1 = test_dir / "file1.mp4"
    f1.write_text("test")
    
    rule = CleanupRule(
        category="temp",
        directory=test_dir,
        retention_days=0,  # Mark all as old
        max_count=None,
        protected=False,
        extensions=[".mp4"]
    )
    manager.rules = {"temp": rule}

    # OSError during unlink
    with patch("pathlib.Path.unlink", side_effect=OSError("Permission denied")), \
         patch("logging.Logger.error") as mock_err:
        res = manager.cleanup()
        assert res["deleted"] == []
        assert mock_err.called
        # Check if exc_info=True was passed in the logging
        _, kwargs = mock_err.call_args
        assert kwargs.get('exc_info') is True

def test_auto_cleanup_unexpected_exceptions_safety():
    """auto_cleanup メソッドおよび report_to_evolution_log 内で、
    ValueError や RuntimeError といった想定内の例外が発生した際に、
    安全にキャッチされてクラッシュしないことを検証する"""
    manager = CleanupManager()
    manager.cleanup = MagicMock(return_value={})
    
    # EvolutionTriggerServiceの初期化時に ValueError が発生する場合
    with patch("services.evolution_trigger_service.EvolutionTriggerService", side_effect=ValueError("Mock ValueError")), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", side_effect=ImportError), \
         patch("logging.Logger.warning") as mock_warn:
         
        # クラッシュせずに正常終了すること
        res = manager.auto_cleanup()
        assert res == {}
        # 警告ログに expected error に起因するメッセージが含まれること
        assert any("EvolutionTriggerService initialization failed" in args[0] for args, _ in mock_warn.call_args_list)

    # PhilosophyProposalServiceの初期化時に RuntimeError が発生する場合
    with patch("services.evolution_trigger_service.EvolutionTriggerService", side_effect=ImportError), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", side_effect=RuntimeError("Mock RuntimeError")), \
         patch("logging.Logger.error") as mock_err:
         
        res = manager.auto_cleanup()
        assert res == {}
        assert any("PhilosophyProposalService initialization failed" in args[0] for args, _ in mock_err.call_args_list)

    # trust_historyトリミング処理中に ValueError が発生する場合
    mock_trigger_svc = MagicMock()
    mock_trigger_svc._load_evolution_log.side_effect = ValueError("Mock ValueError during trim")
    with patch("services.evolution_trigger_service.EvolutionTriggerService", return_value=mock_trigger_svc), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", side_effect=ImportError), \
         patch("logging.Logger.warning") as mock_warn:
          
        res = manager.auto_cleanup()
        assert res == {}
        assert any("trust_history structure error" in args[0] for args, _ in mock_warn.call_args_list)

    # pending_proposalsトリミング処理中に AttributeError が発生する場合
    mock_proposal_svc = MagicMock()
    mock_proposal_svc._trim_pending_proposals.side_effect = AttributeError("Mock AttributeError during trim")
    with patch("services.evolution_trigger_service.EvolutionTriggerService", side_effect=ImportError), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", return_value=mock_proposal_svc), \
         patch("logging.Logger.error") as mock_err:
          
        res = manager.auto_cleanup()
        assert res == {}
        assert any("pending_proposals trim失敗 (unexpected error)" in args[0] for args, _ in mock_err.call_args_list)

    # report_to_evolution_log 実行中に RuntimeError が発生する場合
    with patch("utils.json_safe_io.safe_load_json", side_effect=RuntimeError("Mock RuntimeError during JSON load")), \
         patch("logging.Logger.error") as mock_err:
          
        manager.report_to_evolution_log({}, evolution_log_path=Path("dummy_path"))
        assert any("evolution_log記録失敗 (unexpected)" in args[0] for args, _ in mock_err.call_args_list)


def test_is_protected_attribute_error_guard():
    """is_protected 内で rule.directory が AttributeError を投げるオブジェクトの場合に、
    安全に AttributeError がキャッチされ、プログラムがクラッシュせずに保護判定が継続されることを検証"""
    manager = CleanupManager()
    
    # 属性アクセスや文字列化の段階で AttributeError を投げるようなダミーオブジェクトを directory に設定
    class BadDirectory:
        def __str__(self):
            raise AttributeError("Mock AttributeError on str()")
        def __fspath__(self):
            raise AttributeError("Mock AttributeError on fspath()")

    manager.rules = {
        "final": CleanupRule(
            category="final",
            directory=BadDirectory(),
            retention_days=None,
            max_count=None,
            protected=True
        )
    }

    with patch("logging.Logger.warning") as mock_warn:
        # AttributeError が発生してもキャッチされて False を返すこと
        assert manager.is_protected("/tmp/some_file.mp4") is False
        assert any("TypeError/AttributeError in is_protected checking rule" in args[0] for args, _ in mock_warn.call_args_list)


def test_report_to_evolution_log_timeout_error(tmp_path):
    """report_to_evolution_log 実行中に filelock.Timeout エラーが発生した際、
    安全に Timeout エラーがキャッチされて処理がクラッシュしないことを検証"""
    from filelock import Timeout
    manager = CleanupManager()
    log_file = tmp_path / "evolution_log.json"
    
    # safe_save_json 呼び出し時に Timeout エラーを発生させる
    with patch("utils.json_safe_io.safe_load_json", return_value={"entries": []}), \
         patch("utils.json_safe_io.safe_save_json", side_effect=Timeout("Lock timeout simulated")), \
         patch("logging.Logger.warning") as mock_warn:
         
        manager.report_to_evolution_log({"deleted": []}, evolution_log_path=log_file)
        # Timeout が safety net で安全に処理されたことを示す警告ログを確認
        assert any("evolution_log記録失敗 (Timeout)" in args[0] for args, _ in mock_warn.call_args_list)


def test_is_protected_type_value_error_in_path_conversion():
    """is_protected 内での os.path.abspath もしくは Path() 変換時における
    TypeError や ValueError の発生と、それが安全にキャッチされて False が返されることを検証"""
    manager = CleanupManager()
    
    # ヌルバイトを含む文字列を渡し、ValueError を発生させる
    assert manager.is_protected("dummy\x00path") is False
    
    # 明示的に os.path.abspath が TypeError を投げるようにモックする
    with patch("os.path.abspath", side_effect=TypeError("Mock TypeError")):
        assert manager.is_protected("dummy_path") is False


def test_auto_cleanup_generic_exception_safety_net():
    """auto_cleanup において、各種サービスや内部処理から generic な Exception が発生した場合でも、
    すべて safety net でキャッチされ、クラッシュせずに正常終了することを検証"""
    manager = CleanupManager()
    manager.cleanup = MagicMock(return_value={})
    manager.report_to_evolution_log = MagicMock()

    # Case 1: EvolutionTriggerService() 自体が Exception を投げる場合
    with patch("services.evolution_trigger_service.EvolutionTriggerService", side_effect=Exception("Generic Evolution Trigger Error")), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", side_effect=ImportError), \
         patch("logging.Logger.error") as mock_err:
         
        res = manager.auto_cleanup()
        assert res == {}
        assert any("EvolutionTriggerService initialization failed (unexpected error)" in args[0] for args, _ in mock_err.call_args_list)

    # Case 2: PhilosophyProposalService() 自体が Exception を投げる場合
    with patch("services.evolution_trigger_service.EvolutionTriggerService", side_effect=ImportError), \
         patch("services.philosophy_proposal_service.PhilosophyProposalService", side_effect=Exception("Generic Philosophy Proposal Error")), \
         patch("logging.Logger.error") as mock_err:
         
        res = manager.auto_cleanup()
        assert res == {}
        assert any("PhilosophyProposalService initialization failed (unexpected error)" in args[0] for args, _ in mock_err.call_args_list)

