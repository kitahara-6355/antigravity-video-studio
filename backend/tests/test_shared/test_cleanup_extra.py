import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from cleanup_manager import CleanupManager, CleanupRule

class TestCleanupExtra:
    """cleanup_manager.py の追加堅牢化・カバレッジ 100% 達成テスト"""

    def _make_manager(self, tmp_path):
        mgr = CleanupManager.__new__(CleanupManager)
        mgr.rules = {
            "screenshots": CleanupRule(
                category="screenshots",
                directory=tmp_path / "screenshots",
                retention_days=1,
                max_count=3,
                protected=False,
                extensions=[".png"],
            ),
            "raw": CleanupRule(
                category="raw",
                directory=tmp_path / "raw",
                retention_days=None,
                max_count=None,
                protected=True,
                extensions=[".mp4"],
            ),
        }
        for rule in mgr.rules.values():
            rule.directory.mkdir(parents=True, exist_ok=True)
        return mgr

    def test_init_mkdir_oserror(self):
        """__init__ での mkdir 時の OSError ハンドリングを検証"""
        with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
            mgr = CleanupManager()
            assert len(mgr.rules) > 0

    def test_is_protected_type_errors(self, tmp_path):
        """is_protected の型異常・None ガード検証"""
        mgr = self._make_manager(tmp_path)
        assert mgr.is_protected(None) is False
        assert mgr.is_protected(12345) is False

    def test_is_protected_relative_to_type_error(self, tmp_path):
        """is_protected の relative_to で TypeError が発生した場合のハンドリング"""
        mgr = self._make_manager(tmp_path)
        with patch("pathlib.Path.relative_to", side_effect=TypeError("relative_to TypeError")):
            assert mgr.is_protected("some_path.png") is False

    def test_cleanup_invalid_category_type(self, tmp_path):
        """cleanup の category に無効な型または未定義値が渡された場合"""
        mgr = self._make_manager(tmp_path)
        res1 = mgr.cleanup(category=123)
        assert res1["deleted"] == []
        res2 = mgr.cleanup(category="unknown")
        assert res2["deleted"] == []

    def test_cleanup_directory_not_exists(self, tmp_path):
        """cleanup 実行時にディレクトリが存在しない場合 (Line 147 相当)"""
        mgr = self._make_manager(tmp_path)
        ss_dir = mgr.rules["screenshots"].directory
        if ss_dir.exists():
            ss_dir.rmdir()
        
        res = mgr.cleanup(category="screenshots")
        assert res["deleted"] == []

    def test_cleanup_directory_exists_oserror(self, tmp_path):
        """cleanup 実行時に directory.exists() で OSError が発生した場合のハンドリング"""
        mgr = self._make_manager(tmp_path)
        with patch("pathlib.Path.exists", side_effect=OSError("Disk error")):
            res = mgr.cleanup(category="screenshots")
            assert res["deleted"] == []

    def test_cleanup_glob_exception(self, tmp_path):
        """cleanup 実行時に directory.glob() で OSError/TypeError/ValueError が発生した場合のハンドリング"""
        mgr = self._make_manager(tmp_path)
        with patch("pathlib.Path.glob", side_effect=ValueError("Invalid pattern")):
            res = mgr.cleanup(category="screenshots")
            assert res["deleted"] == []

    def test_cleanup_retention_calculation_exception(self, tmp_path):
        """cleanup 内の retention_days 計算で TypeError/ValueError が発生した場合のハンドリング"""
        mgr = self._make_manager(tmp_path)
        mgr.rules["screenshots"].retention_days = "invalid_days"
        
        ss_dir = mgr.rules["screenshots"].directory
        f = ss_dir / "test.png"
        f.write_bytes(b"x")
        
        res = mgr.cleanup(category="screenshots")
        assert f.exists()

    def test_cleanup_retention_stat_oserror(self, tmp_path):
        """cleanup 内の retention チェックでの f.stat() 時の OSError/FileNotFoundError のハンドリング"""
        mgr = self._make_manager(tmp_path)
        mgr.rules["screenshots"].retention_days = 1
        
        mock_f = MagicMock(spec=Path)
        mock_f.name = "test.png"
        mock_f.exists.return_value = True
        mock_f.is_file.return_value = True
        mock_f.stat.side_effect = FileNotFoundError("file not found")
        mock_f.relative_to.return_value = Path("screenshots/test.png")
        
        with patch("pathlib.Path.glob", return_value=[mock_f]):
            res = mgr.cleanup(category="screenshots")
            assert mock_f.name not in [Path(p).name for p in res["deleted"]]

    def test_cleanup_max_count_stat_oserror(self, tmp_path):
        """cleanup 内の max_count チェックでの f.stat() 時の FileNotFoundError/OSError のハンドリング"""
        mgr = self._make_manager(tmp_path)
        mgr.rules["screenshots"].max_count = 1
        
        mock_f1 = MagicMock(spec=Path)
        mock_f1.name = "test1.png"
        mock_f1.stat.side_effect = FileNotFoundError("Mock file not found")
        mock_f1.relative_to.return_value = Path("screenshots/test1.png")
        
        mock_f2 = MagicMock(spec=Path)
        mock_f2.name = "test2.png"
        
        class GoodStat:
            st_mtime = 100
            st_size = 0
            
        mock_f2.stat.return_value = GoodStat()
        mock_f2.relative_to.return_value = Path("screenshots/test2.png")
        
        with patch("pathlib.Path.glob", return_value=[mock_f1, mock_f2]):
            res = mgr.cleanup(category="screenshots")
            assert res is not None

    def test_cleanup_sorting_oserror(self, tmp_path):
        """cleanup 内の max_count ソート時の OSError ハンドリング"""
        mgr = self._make_manager(tmp_path)
        mgr.rules["screenshots"].max_count = 1
        
        mock_f1 = MagicMock(spec=Path)
        mock_f1.name = "test1.png"
        mock_f1.relative_to.return_value = Path("screenshots/test1.png")
        
        class BadStat:
            @property
            def st_mtime(self):
                raise OSError("Stat error on sort")
            st_size = 100

        mock_f1.stat.return_value = BadStat()
        
        with patch("pathlib.Path.glob", return_value=[mock_f1]):
            res = mgr.cleanup(category="screenshots")
            assert res is not None

    def test_cleanup_unlink_size_stat_oserror(self, tmp_path):
        """cleanup の unlink 処理直前の size 取得時の OSError ハンドリング"""
        mgr = self._make_manager(tmp_path)
        mgr.rules["screenshots"].retention_days = 1
        
        mock_f = MagicMock(spec=Path)
        mock_f.name = "test_size_err.png"
        mock_f.__str__.return_value = "screenshots/test_size_err.png"
        mock_f.relative_to.return_value = Path("screenshots/test_size_err.png")
        
        class BadSizeStat:
            def __init__(self):
                self.st_mtime = 0
            @property
            def st_size(self):
                raise FileNotFoundError("Mock error")

        mock_f.stat.return_value = BadSizeStat()
        
        with patch("pathlib.Path.glob", return_value=[mock_f]):
            res = mgr.cleanup(category="screenshots")
            assert "test_size_err.png" in [Path(p).name for p in res["deleted"]]
            assert res["freed_bytes"] == 0

    def test_cleanup_with_protected_file_in_deletion_list(self, tmp_path):
        """cleanup 中に is_protected() が True になるファイルが含まれる場合 (Lines 180-181 相当)"""
        mgr = self._make_manager(tmp_path)
        ss_dir = mgr.rules["screenshots"].directory
        
        import time as _time
        import os
        f = ss_dir / "old_protected.png"
        f.write_bytes(b"x")
        old_time = _time.time() - 2 * 86400
        os.utime(f, (old_time, old_time))
        
        with patch.object(mgr, "is_protected", return_value=True):
            res = mgr.cleanup(category="screenshots")
            assert f.name not in [Path(p).name for p in res["deleted"]]
            assert str(f) in res["protected"]
            assert f.exists()

    def test_cleanup_unlink_exception(self, tmp_path):
        """unlink 実行時に OSError が発生した場合 (Lines 191-192 相当)"""
        mgr = self._make_manager(tmp_path)
        ss_dir = mgr.rules["screenshots"].directory
        
        import time as _time
        import os
        f = ss_dir / "old_err.png"
        f.write_bytes(b"x")
        old_time = _time.time() - 2 * 86400
        os.utime(f, (old_time, old_time))
        
        with patch("pathlib.Path.unlink", side_effect=OSError("Permission denied")):
            res = mgr.cleanup(category="screenshots")
            assert res["deleted"] == []
            assert f.exists()

    def test_cleanup_unlink_unexpected_exception(self, tmp_path):
        """cleanup の unlink 処理時の一般例外（TypeError等）ハンドリング"""
        mgr = self._make_manager(tmp_path)
        mgr.rules["screenshots"].retention_days = 1
        ss_dir = mgr.rules["screenshots"].directory
        f = ss_dir / "test_unexp.png"
        f.write_bytes(b"x")
        import time as _time
        import os
        old_time = _time.time() - 2 * 86400
        os.utime(f, (old_time, old_time))
        
        with patch("pathlib.Path.unlink", side_effect=TypeError("Unexpected error")):
            res = mgr.cleanup(category="screenshots")
            assert res is not None

    def test_get_storage_stats_dir_not_exists(self, tmp_path):
        """stats 取得時にディレクトリが存在しない場合 (Lines 217-224 相当)"""
        mgr = self._make_manager(tmp_path)
        ss_dir = mgr.rules["screenshots"].directory
        if ss_dir.exists():
            ss_dir.rmdir()
            
        stats = mgr.get_storage_stats()
        assert stats["categories"]["screenshots"]["count"] == 0
        assert stats["categories"]["screenshots"]["size_mb"] == 0

    def test_get_storage_stats_exists_oserror(self, tmp_path):
        """get_storage_stats 内の exists() で OSError が発生した場合のハンドリング"""
        mgr = self._make_manager(tmp_path)
        with patch("pathlib.Path.exists", side_effect=OSError("Disk error")):
            stats = mgr.get_storage_stats()
            assert "screenshots" in stats["categories"]
            assert stats["categories"]["screenshots"]["count"] == 0

    def test_get_storage_stats_glob_exception(self, tmp_path):
        """get_storage_stats 内の glob() で OSError/TypeError が発生した場合のハンドリング"""
        mgr = self._make_manager(tmp_path)
        with patch("pathlib.Path.glob", side_effect=TypeError("Invalid glob type")):
            stats = mgr.get_storage_stats()
            assert "screenshots" in stats["categories"]
            assert stats["categories"]["screenshots"]["count"] == 0

    def test_get_storage_stats_stat_exception(self, tmp_path):
        """get_storage_stats 内の stat() で OSError/FileNotFoundError が発生した場合のハンドリング"""
        mgr = self._make_manager(tmp_path)
        
        mock_f = MagicMock(spec=Path)
        mock_f.name = "stat_err.png"
        mock_f.is_file.return_value = True
        mock_f.stat.side_effect = OSError("Stat failed")
        
        with patch("pathlib.Path.glob", return_value=[mock_f]):
            stats = mgr.get_storage_stats()
            assert stats["categories"]["screenshots"]["count"] == 0

    def test_preview_cleanup(self, tmp_path):
        """preview_cleanup が dry_run=True で cleanup() を呼ぶこと (Line 260 相当)"""
        mgr = self._make_manager(tmp_path)
        with patch.object(mgr, "cleanup", return_value={"preview": True}) as mock_cleanup:
            res = mgr.preview_cleanup()
            mock_cleanup.assert_called_once_with(dry_run=True)
            assert res == {"preview": True}

    def test_auto_cleanup_normal_flow(self, tmp_path):
        """auto_cleanup の正常系フロー (EvolutionTriggerService/PhilosophyProposalService の呼び出し) (Lines 287-289, 297 相当)"""
        mgr = self._make_manager(tmp_path)
        
        mock_trigger_svc = MagicMock()
        mock_trigger_svc._load_evolution_log.return_value = {"rejection_count": 0, "trust_history": []}
        
        mock_proposal_svc = MagicMock()
        
        with patch("services.evolution_trigger_service.EvolutionTriggerService", return_value=mock_trigger_svc), \
             patch("services.philosophy_proposal_service.PhilosophyProposalService", return_value=mock_proposal_svc), \
             patch.object(mgr, "report_to_evolution_log") as mock_report:
            
            res = mgr.auto_cleanup()
            
            mock_trigger_svc._load_evolution_log.assert_called_once()
            mock_trigger_svc._trim_trust_history.assert_called_once()
            mock_trigger_svc._save_evolution_log.assert_called_once()
            mock_proposal_svc._trim_pending_proposals.assert_called_once()
            mock_report.assert_called_once()

    def test_report_to_evolution_log_type_errors(self, tmp_path):
        """report_to_evolution_log に渡された cleanup_result や path の型異常"""
        mgr = self._make_manager(tmp_path)
        
        with patch("logging.Logger.error") as mock_log:
            mgr.report_to_evolution_log("not a dict")
            mock_log.assert_called_once()
            
        with patch("logging.Logger.error") as mock_log:
            mgr.report_to_evolution_log({}, evolution_log_path=12345)
            mock_log.assert_called_once()

    def test_report_to_evolution_log_no_existing_log(self, tmp_path):
        """evolution_log が存在しない（新規作成される）場合の動作 (Lines 326-348 相当)"""
        mgr = self._make_manager(tmp_path)
        evo_path = tmp_path / "new_evo_log.json"
        
        cleanup_result = {
            "deleted": ["file1.png", "file2.png"],
            "freed_bytes": 2048 * 1024,
            "protected": ["raw.mp4"],
            "dry_run": False
        }
        
        mgr.report_to_evolution_log(cleanup_result, evolution_log_path=evo_path)
        
        assert evo_path.exists()
        import json
        with open(evo_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["entries"]) == 1
        entry = data["entries"][0]
        assert entry["type"] == "storage_cleanup"
        assert entry["deleted_count"] == 2
        assert entry["freed_mb"] == 2.0
        assert entry["protected_count"] == 1
        assert entry["dry_run"] is False

    def test_report_to_evolution_log_default_path(self, tmp_path):
        """evolution_log_path が None の場合（デフォルトパス）の動作とカバレッジ"""
        mgr = self._make_manager(tmp_path)
        cleanup_result = {
            "deleted": ["file.png"],
            "freed_bytes": 1024,
            "protected": [],
            "dry_run": False
        }
        
        with patch("utils.json_safe_io.safe_load_json", return_value={}) as mock_load, \
             patch("utils.json_safe_io.safe_save_json") as mock_save:
            mgr.report_to_evolution_log(cleanup_result, evolution_log_path=None)
            
            mock_load.assert_called_once()
            called_path = mock_load.call_args[0][0]
            assert called_path.name == "evolution_log.json"
            assert called_path.parent.name == "branding"
            mock_save.assert_called_once()

    def test_report_to_evolution_log_load_save_exceptions(self, tmp_path):
        """report_to_evolution_log の読み込み・保存時の例外キャッチ"""
        mgr = self._make_manager(tmp_path)
        evo_path = tmp_path / "evo_log_err.json"
        evo_path.write_text("{}", encoding="utf-8")
        
        with patch("utils.json_safe_io.safe_load_json", side_effect=Exception("Load error")), \
             patch("logging.Logger.warning") as mock_warning:
            mgr.report_to_evolution_log({}, evolution_log_path=evo_path)
            assert any("evolution_log記録失敗" in call[0][0] for call in mock_warning.call_args_list)

    def test_singleton_instance_default_rules(self):
        """シングルトンインスタンスのデフォルトルール構成アサーション"""
        from cleanup_manager import cleanup_manager
        assert cleanup_manager is not None
        categories = ["screenshots", "drafts", "prefinal", "final", "raw", "video_output"]
        for cat in categories:
            assert cat in cleanup_manager.rules
            rule = cleanup_manager.rules[cat]
            assert rule.category == cat
            assert rule.directory is not None

    def test_is_protected_extreme_values(self, tmp_path):
        """is_protected の極端な異常値入力（空文字列や不正な値）に対する堅牢性検証"""
        mgr = self._make_manager(tmp_path)
        assert mgr.is_protected("") is False
        assert mgr.is_protected("\x00") is False
        assert mgr.is_protected("A" * 1000) is False

    def test_auto_cleanup_partial_error_isolation(self, tmp_path):
        """auto_cleanup で EvolutionTriggerService が失敗しても PhilosophyProposalService が実行されること"""
        mgr = self._make_manager(tmp_path)
        
        # EvolutionTriggerServiceのインスタンス作成時ではなく、メソッド実行時で例外を発生させる
        mock_trigger_svc = MagicMock()
        mock_trigger_svc._load_evolution_log.side_effect = Exception("Evolution load failed")
        
        mock_proposal_svc = MagicMock()
        
        with patch("services.evolution_trigger_service.EvolutionTriggerService", return_value=mock_trigger_svc), \
             patch("services.philosophy_proposal_service.PhilosophyProposalService", return_value=mock_proposal_svc), \
             patch.object(mgr, "report_to_evolution_log") as mock_report:
            
            res = mgr.auto_cleanup()
            
            # EvolutionTriggerService は途中で失敗するが、PhilosophyProposalService のトリミングと report_to_evolution_log は実行されること
            mock_proposal_svc._trim_pending_proposals.assert_called_once()
            mock_report.assert_called_once()
            assert res is not None
