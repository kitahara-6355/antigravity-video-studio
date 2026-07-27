"""
Sprint 4.3.2: ストレージ自動クリーンアップ テスト

設計書: sprint_43_storage_coverage_design.md §4 Sprint 4.3.2
憲法: §11 ストレージ保護階層, §12.3 上書き禁止

テスト:
- S432-01: パイプライン完了後にcleanup自動呼出
- S432-02: cleanup実行後、raw/finalカテゴリのファイルが削除されていない
- S432-03: cleanup結果(deleted件数/freed_MB)がevolution_logに記録される
- S432-04: GET /api/storage/stats + POST /api/storage/cleanup が正常動作
"""
import json
import time
import inspect
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock


# ============================================================
# S432-01: パイプライン完了後にcleanup自動呼出
# ============================================================
class TestS432_01_PipelineCompletionTriggersCleanup:
    """S432-01: パイプライン完了後にcleanup_manager.auto_cleanup()が自動呼出される"""

    def test_pipeline_router_contains_auto_cleanup_call(self):
        """pipeline_router.py に auto_cleanup() 呼出しが存在するか (構造検証)"""
        source_path = (
            Path(__file__).parent.parent.parent
            / "routers"
            / "pipeline_router.py"
        )
        source = source_path.read_text(encoding="utf-8")

        # auto_cleanup が pipeline_router.py 内に存在すること
        assert "auto_cleanup" in source, \
            "pipeline_router.py に auto_cleanup() 呼出しが必要"

    def test_auto_cleanup_called_after_sync_all(self):
        """auto_cleanup() が sync_all() の後に配置されていることを確認"""
        source_path = (
            Path(__file__).parent.parent.parent
            / "routers"
            / "pipeline_router.py"
        )
        source = source_path.read_text(encoding="utf-8")

        sync_pos = source.find("sync_all()")
        cleanup_pos = source.find("auto_cleanup()")
        assert sync_pos > 0, "sync_all() が存在しない"
        assert cleanup_pos > 0, "auto_cleanup() が存在しない"
        assert cleanup_pos > sync_pos, \
            "auto_cleanup() は sync_all() の後に配置されるべき"

    def test_auto_cleanup_method_exists(self):
        """cleanup_manager に auto_cleanup() メソッドが存在する"""
        from cleanup_manager import CleanupManager
        manager = CleanupManager()
        assert hasattr(manager, "auto_cleanup"), \
            "CleanupManager に auto_cleanup() メソッドが必要"
        assert callable(manager.auto_cleanup)


# ============================================================
# S432-02: cleanup実行後、raw/finalカテゴリのファイルが削除されていない
# ============================================================
class TestS432_02_CleanupProtectsRawAndFinal:
    """S432-02: cleanup実行後、raw/finalカテゴリのファイルが削除されていない"""

    def test_cleanup_skips_protected_categories(self, tmp_path):
        """cleanup実行時にprotected=Trueカテゴリがスキップされる"""
        from cleanup_manager import CleanupManager

        manager = CleanupManager()
        # raw, finalのprotected状態を検証
        raw_rule = manager.rules.get("raw")
        final_rule = manager.rules.get("final")

        assert raw_rule is not None, "raw ルールが未定義"
        assert final_rule is not None, "final ルールが未定義"
        assert raw_rule.protected is True, "raw は protected=True であること"
        assert final_rule.protected is True, "final は protected=True であること"

    def test_cleanup_does_not_delete_protected_files(self, tmp_path):
        """protected=True カテゴリのファイルがdry_runで削除候補に含まれない"""
        from cleanup_manager import CleanupManager

        manager = CleanupManager()

        # dry_run で実行
        result = manager.cleanup(dry_run=True)

        # protected に含まれるファイルは削除対象ではない
        assert result["dry_run"] is True
        # protected カテゴリのファイルが deleted に含まれないことを確認
        for deleted_path in result.get("deleted", []):
            assert not manager.is_protected(deleted_path), \
                f"保護対象ファイルが削除候補に含まれている: {deleted_path}"

    def test_raw_retention_is_permanent(self):
        """raw カテゴリの retention_days が None (永久保持) である"""
        from cleanup_manager import CleanupManager
        manager = CleanupManager()
        assert manager.rules["raw"].retention_days is None

    def test_final_retention_is_permanent(self):
        """final カテゴリの retention_days が None (永久保持) である"""
        from cleanup_manager import CleanupManager
        manager = CleanupManager()
        assert manager.rules["final"].retention_days is None

    def test_retention_days_match_spec(self):
        """§11.3 保持期間: screenshots 7日/drafts 3日/prefinal 1日/video_output 7日"""
        from cleanup_manager import CleanupManager
        manager = CleanupManager()
        assert manager.rules["screenshots"].retention_days == 7
        assert manager.rules["drafts"].retention_days == 3
        assert manager.rules["prefinal"].retention_days == 1
        assert manager.rules["video_output"].retention_days == 7


# ============================================================
# S432-03: cleanup結果がevolution_logに記録される
# ============================================================
class TestS432_03_CleanupReportInEvolutionLog:
    """S432-03: cleanup結果(deleted件数/freed_MB)がevolution_logに記録される"""

    def test_report_to_evolution_log_method_exists(self):
        """cleanup_manager に report_to_evolution_log() メソッドが存在する"""
        from cleanup_manager import CleanupManager
        manager = CleanupManager()
        assert hasattr(manager, "report_to_evolution_log"), \
            "CleanupManager に report_to_evolution_log() メソッドが必要"

    def test_report_appends_to_evolution_log(self, tmp_path):
        """cleanup結果がevolution_logのentriesに追記される (§12.3 appendのみ)"""
        from cleanup_manager import CleanupManager

        # テスト用evolution_log
        evo_log_path = tmp_path / "branding" / "evolution_log.json"
        evo_log_path.parent.mkdir(parents=True, exist_ok=True)
        initial_data = {"entries": [{"type": "existing", "data": "keep"}]}
        evo_log_path.write_text(
            json.dumps(initial_data, ensure_ascii=False), encoding="utf-8"
        )

        manager = CleanupManager()

        cleanup_result = {
            "deleted": ["file1.mp4", "file2.png"],
            "protected": [],
            "freed_bytes": 1024 * 1024 * 50,  # 50MB
            "dry_run": False,
        }

        manager.report_to_evolution_log(cleanup_result, evo_log_path)

        # evolution_log を読み込み検証
        data = json.loads(evo_log_path.read_text(encoding="utf-8"))
        entries = data.get("entries", [])

        # 既存エントリが保持されている (§12.3: 上書き禁止)
        assert entries[0]["type"] == "existing"

        # cleanup レポートエントリが追記されている
        cleanup_entries = [e for e in entries if e.get("type") == "storage_cleanup"]
        assert len(cleanup_entries) >= 1, \
            "cleanup結果エントリが追加されていない"

        report = cleanup_entries[-1]
        assert report["deleted_count"] == 2
        assert report["freed_mb"] == pytest.approx(50.0, rel=0.1)

    def test_auto_cleanup_calls_report(self, tmp_path):
        """auto_cleanup() が report_to_evolution_log() を呼出す"""
        from cleanup_manager import CleanupManager

        manager = CleanupManager()

        with patch.object(manager, "cleanup", return_value={
            "deleted": [], "protected": [], "freed_bytes": 0, "dry_run": False,
        }) as mock_cleanup, \
             patch.object(manager, "report_to_evolution_log") as mock_report:
            manager.auto_cleanup()
            mock_cleanup.assert_called_once()
            mock_report.assert_called_once()


# ============================================================
# S432-04: Storage API エンドポイント
# ============================================================
class TestS432_04_StorageApiEndpoints:
    """S432-04: GET /api/storage/stats + POST /api/storage/cleanup が正常動作"""

    @pytest.fixture
    def client(self):
        """テスト用FastAPIクライアント"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from routers.admin_setup_router import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_get_storage_stats(self, client):
        """GET /api/storage/stats → カテゴリ別使用量を返す"""
        with patch(
            "routers.admin_setup_router.cleanup_manager"
        ) as mock_cm:
            mock_cm.get_storage_stats.return_value = {
                "categories": {
                    "screenshots": {"count": 10, "size_mb": 5.0, "protected": False},
                    "raw": {"count": 3, "size_mb": 500.0, "protected": True},
                },
                "total_size_mb": 505.0,
                "protected_size_mb": 500.0,
                "deletable_size_mb": 5.0,
            }
            response = client.get("/api/admin/setup/storage/stats")
            assert response.status_code == 200
            data = response.json()
            assert "categories" in data
            assert "total_size_mb" in data

    def test_post_storage_cleanup_dry_run(self, client):
        """POST /api/storage/cleanup?dry_run=true → dry_run結果を返す"""
        with patch(
            "routers.admin_setup_router.cleanup_manager"
        ) as mock_cm:
            mock_cm.cleanup.return_value = {
                "deleted": ["file1.mp4"],
                "protected": [],
                "freed_bytes": 1048576,
                "dry_run": True,
            }
            response = client.post(
                "/api/admin/setup/storage/cleanup",
                json={"dry_run": True},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["dry_run"] is True

    def test_post_storage_cleanup_execute(self, client):
        """POST /api/storage/cleanup → 実際のクリーンアップ実行"""
        with patch(
            "routers.admin_setup_router.cleanup_manager"
        ) as mock_cm:
            mock_cm.cleanup.return_value = {
                "deleted": ["file1.mp4", "file2.png"],
                "protected": [],
                "freed_bytes": 2097152,
                "dry_run": False,
            }
            mock_cm.report_to_evolution_log = MagicMock()
            response = client.post(
                "/api/admin/setup/storage/cleanup",
                json={"dry_run": False},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["dry_run"] is False
            assert len(data["deleted"]) == 2

    def test_storage_stats_endpoint_exists(self):
        """admin_setup_router.py に /storage/stats エンドポイントが存在する"""
        source_path = (
            Path(__file__).parent.parent.parent
            / "routers"
            / "admin_setup_router.py"
        )
        source = source_path.read_text(encoding="utf-8")
        assert "/storage/stats" in source, \
            "admin_setup_router.py に /storage/stats が必要"

    def test_storage_cleanup_endpoint_exists(self):
        """admin_setup_router.py に /storage/cleanup エンドポイントが存在する"""
        source_path = (
            Path(__file__).parent.parent.parent
            / "routers"
            / "admin_setup_router.py"
        )
        source = source_path.read_text(encoding="utf-8")
        assert "/storage/cleanup" in source, \
            "admin_setup_router.py に /storage/cleanup が必要"


# ============================================================
# カバレッジ向上用のテスト
# ============================================================
class TestCleanupManagerCoverage:
    """cleanup_manager.py の未カバーコードをカバーするための追加テスト"""

    def test_is_protected_various_paths(self):
        """is_protected() の各種パス判定を検証"""
        from cleanup_manager import CleanupManager
        manager = CleanupManager()
        
        # 1. 保護ディレクトリ内のパス (True)
        raw_dir = manager.rules["raw"].directory
        protected_file = raw_dir / "protected_video.mp4"
        assert manager.is_protected(str(protected_file)) is True
        
        # 2. 非保護ディレクトリ内のパス (False)
        screenshots_dir = manager.rules["screenshots"].directory
        unprotected_file = screenshots_dir / "temp_screenshot.png"
        assert manager.is_protected(str(unprotected_file)) is False

    def test_cleanup_non_existent_directory(self):
        """ルールに指定されたディレクトリが存在しない場合の挙動を検証"""
        from cleanup_manager import CleanupManager, CleanupRule
        manager = CleanupManager()
        
        # 存在しないディレクトリを指定したダミールールを追加
        non_existent_dir = Path("non_existent_directory_for_test_12345")
        manager.rules["dummy_missing"] = CleanupRule(
            category="dummy_missing",
            directory=non_existent_dir,
            retention_days=1,
            max_count=1,
            protected=False,
            extensions=[".tmp"]
        )
        
        # クリーンアップを実行してもエラーにならずスキップされること
        result = manager.cleanup(category="dummy_missing")
        assert "dummy_missing" not in result.get("deleted", [])

    def test_cleanup_execution_with_real_files(self, tmp_path):
        """実際のファイル削除と保持ルール判定の挙動を検証"""
        import os
        import time
        from cleanup_manager import CleanupManager, CleanupRule
        manager = CleanupManager()
        
        # テスト用の一時ディレクトリとファイルを作成
        test_dir = tmp_path / "test_cleanup_run"
        test_dir.mkdir(parents=True, exist_ok=True)
        
        # 古いファイル (保持期間超過)
        old_file = test_dir / "old_file.mp4"
        old_file.write_text("old", encoding="utf-8")
        # st_mtime を10日前（retention_days=7より前）に設定
        past_time = time.time() - (10 * 24 * 60 * 60)
        os.utime(old_file, (past_time, past_time))
        
        # 新しいファイル (上限件数オーバー用)
        new_files = []
        for i in range(5):
            f = test_dir / f"new_file_{i}.mp4"
            f.write_text(f"new_{i}", encoding="utf-8")
            new_files.append(f)
            # 少し時間をずらす
            file_time = time.time() - (i * 100)
            os.utime(f, (file_time, file_time))
            
        # テスト用ルール
        manager.rules["test_run"] = CleanupRule(
            category="test_run",
            directory=test_dir,
            retention_days=7, # 7日
            max_count=3,      # 最大3件
            protected=False,
            extensions=[".mp4"]
        )
        
        # dry_run=True でのプレビュー実行
        preview_res = manager.preview_cleanup()
        assert len(preview_res["deleted"]) > 0
        
        # dry_run=False での実行
        result = manager.cleanup(category="test_run", dry_run=False)
        
        # 古いファイルと、件数超過したファイルが削除されていることを検証
        assert str(old_file) in result["deleted"]
        assert not old_file.exists()
        
        # 生き残ったファイル（最大3件なので、新しい順に3件のみ生存）
        assert not (test_dir / "new_file_3.mp4").exists()
        assert not (test_dir / "new_file_4.mp4").exists()
        assert (test_dir / "new_file_0.mp4").exists()
        
    def test_cleanup_unlink_exception(self, tmp_path):
        """unlink時に例外が発生した場合のログ出力を検証"""
        import os
        import time
        from cleanup_manager import CleanupManager, CleanupRule
        manager = CleanupManager()
        
        test_dir = tmp_path / "test_unlink_err"
        test_dir.mkdir(parents=True, exist_ok=True)
        
        target_file = test_dir / "err_file.mp4"
        target_file.write_text("dummy", encoding="utf-8")
        past_time = time.time() - (10 * 24 * 60 * 60)
        os.utime(target_file, (past_time, past_time))
        
        manager.rules["test_err"] = CleanupRule(
            category="test_err",
            directory=test_dir,
            retention_days=7,
            max_count=None,
            protected=False,
            extensions=[".mp4"]
        )
        
        # Path.unlink が例外を投げるようにモックする
        with patch.object(Path, "unlink", side_effect=PermissionError("Permission denied")):
            result = manager.cleanup(category="test_err", dry_run=False)
            # 例外が発生したため、deletedには含まれないはず
            assert str(target_file) not in result["deleted"]

    def test_get_storage_stats_real(self, tmp_path):
        """get_storage_stats() の実際のストレージ統計取得を検証"""
        from cleanup_manager import CleanupManager, CleanupRule
        manager = CleanupManager()
        
        test_dir = tmp_path / "test_stats"
        test_dir.mkdir(parents=True, exist_ok=True)
        
        f1 = test_dir / "file1.mp4"
        f1.write_text("a" * 1024 * 1024, encoding="utf-8") # 1MB
        
        manager.rules["test_stats"] = CleanupRule(
            category="test_stats",
            directory=test_dir,
            retention_days=7,
            max_count=10,
            protected=False,
            extensions=[".mp4"]
        )
        
        stats = manager.get_storage_stats()
        category_stats = stats["categories"].get("test_stats")
        assert category_stats is not None
        assert category_stats["count"] == 1
        assert category_stats["size_mb"] == pytest.approx(1.0, rel=0.1)
        assert category_stats["oldest_file"] is not None
        assert category_stats["newest_file"] is not None

    def test_auto_cleanup_exception_handling(self):
        """auto_cleanup() 内の各サービス連携時例外ハンドリングを検証"""
        from cleanup_manager import CleanupManager
        manager = CleanupManager()
        
        # EvolutionTriggerServiceのインポートまたはメソッド実行で例外を発生させる
        with patch("services.evolution_trigger_service.EvolutionTriggerService", side_effect=Exception("Evolution error")),              patch("services.philosophy_proposal_service.PhilosophyProposalService", side_effect=Exception("Philosophy error")),              patch.object(manager, "cleanup", return_value={"deleted": [], "protected": [], "freed_bytes": 0, "dry_run": False}),              patch.object(manager, "report_to_evolution_log") as mock_report:
            
            # 例外が内部でキャッチされて正常終了することを確認
            result = manager.auto_cleanup()
            assert result is not None
            mock_report.assert_called_once()

    def test_report_to_evolution_log_exception_handling(self):
        """report_to_evolution_log() のファイルI/O例外ハンドリングを検証"""
        from cleanup_manager import CleanupManager
        manager = CleanupManager()
        
        # safe_load_json が例外を投げるようにモックする
        with patch("utils.json_safe_io.safe_load_json", side_effect=Exception("JSON error")):
            # 例外が内部でキャッチされて警告ログが出るのみで、呼び出し自体は正常終了すること
            manager.report_to_evolution_log({"deleted": []})

    def test_cleanup_with_protected_file_inside_deletable_category(self, tmp_path):
        """cleanup実行時に、削除対象カテゴリ内に保護対象判定されるファイルが混在する場合を検証"""
        import os
        import time
        from cleanup_manager import CleanupManager, CleanupRule
        manager = CleanupManager()
        
        test_dir = tmp_path / "test_cleanup_protected"
        test_dir.mkdir(parents=True, exist_ok=True)
        
        f1 = test_dir / "file1.mp4"
        f1.write_text("dummy", encoding="utf-8")
        past_time = time.time() - (10 * 24 * 60 * 60)
        os.utime(f1, (past_time, past_time))
        
        manager.rules["test_protected_mix"] = CleanupRule(
            category="test_protected_mix",
            directory=test_dir,
            retention_days=7,
            max_count=None,
            protected=False,
            extensions=[".mp4"]
        )
        
        # is_protected が True を返すようにモック
        with patch.object(manager, "is_protected", return_value=True):
            result = manager.cleanup(category="test_protected_mix", dry_run=False)
            # 削除対象から保護対象として除外されたことを検証
            assert str(f1) in result["protected"]
            assert str(f1) not in result["deleted"]
            assert f1.exists()

    def test_get_storage_stats_with_missing_directory(self):
        """get_storage_stats() 実行時にルールに指定されたディレクトリが存在しない場合を検証"""
        from cleanup_manager import CleanupManager, CleanupRule
        manager = CleanupManager()
        
        # 存在しないディレクトリを指定したダミールールを追加
        non_existent_dir = Path("non_existent_directory_for_stats_12345")
        manager.rules["dummy_missing_dir"] = CleanupRule(
            category="dummy_missing_dir",
            directory=non_existent_dir,
            retention_days=7,
            max_count=10,
            protected=False,
            extensions=[".mp4"]
        )
        
        # 存在しない状態でstats取得
        stats = manager.get_storage_stats()
        cat_stats = stats["categories"].get("dummy_missing_dir")
        assert cat_stats is not None
        assert cat_stats["count"] == 0
        assert cat_stats["size_mb"] == 0
