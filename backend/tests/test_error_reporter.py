import os
import sys
import json
import pytest
from pathlib import Path
from unittest import mock
from fastapi.testclient import TestClient
from fastapi import FastAPI

# 適切なパスを追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.error_reporter import (
    ErrorReport,
    FAQEntry,
    ErrorReportManager,
    FAQManager,
    router
)

@pytest.fixture
def temp_report_dir(tmp_path):
    report_dir = tmp_path / "error_reports"
    report_dir.mkdir()
    return report_dir

def test_error_report_dataclass():
    report = ErrorReport(
        id="123",
        error_type="ValueError",
        message="Invalid value"
    )
    assert report.id == "123"
    assert report.error_type == "ValueError"
    assert report.message == "Invalid value"
    assert report.resolved is False

def test_faq_entry_dataclass():
    faq = FAQEntry(
        id="faq_test",
        question="What is this?",
        answer="A test faq.",
        keywords=["test"],
        error_patterns=["test_pattern"]
    )
    assert faq.id == "faq_test"
    assert faq.question == "What is this?"
    assert faq.keywords == ["test"]

def test_error_report_manager_init_empty(temp_report_dir):
    manager = ErrorReportManager(report_dir=str(temp_report_dir))
    assert manager._reports == []

def test_error_report_manager_load_corrupted_json(temp_report_dir):
    report_file = temp_report_dir / "reports.json"
    report_file.write_text("invalid json data", encoding="utf-8")
    
    # 読み込み失敗時に logger.warning が呼ばれ、空で初期化されること
    with mock.patch("backend.error_reporter.logger") as mock_logger:
        manager = ErrorReportManager(report_dir=str(temp_report_dir))
        assert manager._reports == []
        mock_logger.warning.assert_called_once()

def test_error_report_manager_flow(temp_report_dir):
    manager = ErrorReportManager(report_dir=str(temp_report_dir))
    
    # 1. エラー報告
    report_id = manager.report_error(
        error_type="KeyError",
        message="Missing 'db'",
        stack_trace="traceback text",
        context={"api": "/user"}
    )
    assert len(report_id) == 8
    
    unresolved = manager.get_unresolved()
    assert len(unresolved) == 1
    assert unresolved[0].id == report_id
    assert unresolved[0].error_type == "KeyError"
    
    # 2. 保存ファイルの存在確認
    report_file = temp_report_dir / "reports.json"
    assert report_file.exists()
    
    # 3. 解決
    resolved = manager.resolve_error(report_id, "Fixed db config.")
    assert resolved is True
    assert len(manager.get_unresolved()) == 0
    assert manager._reports[0].resolved is True
    assert manager._reports[0].resolution == "Fixed db config."
    
    # 存在しないIDの解決
    assert manager.resolve_error("nonexistent", "no action") is False
    
    # 4. 統計の取得
    stats = manager.get_stats()
    assert stats["total"] == 1
    assert stats["unresolved"] == 0
    assert stats["resolved"] == 1
    assert stats["by_type"] == {"KeyError": 1}

def test_error_report_manager_save_error(temp_report_dir):
    manager = ErrorReportManager(report_dir=str(temp_report_dir))
    manager.report_error("TypeError", "Mock message")
    
    # 書き込みエラーのテスト
    with mock.patch("builtins.open", side_effect=OSError("Write permission denied")),          mock.patch("backend.error_reporter.logger") as mock_logger:
        with pytest.raises(OSError, match="Write permission denied"):
            manager._save_reports()
        mock_logger.error.assert_called_once()

def test_faq_manager_flow():
    manager = FAQManager()
    
    # デフォルトFAQのロード
    assert len(manager._faqs) >= 3
    
    # FAQ追加
    new_faq = FAQEntry(
        id="faq_custom",
        question="Custom Question",
        answer="Custom Answer",
        keywords=["custom_kw"],
        error_patterns=["custom_err"]
    )
    manager.add_faq(new_faq)
    
    # 検索機能のテスト
    # キーワードマッチ
    results = manager.search("My custom_kw query")
    assert len(results) >= 1
    assert results[0].id == "faq_custom"
    
    # エラーパターンマッチ
    results_err = manager.search("error code custom_err occurred")
    assert len(results_err) >= 1
    assert results_err[0].id == "faq_custom"
    
    # find_for_error
    faq = manager.find_for_error("custom_err")
    assert faq is not None
    assert faq.id == "faq_custom"
    
    # マッチしない検索
    assert manager.search("completely unrelated query") == []
    assert manager.find_for_error("completely unrelated query") is None

# FastAPI テストクライアント用の設定
app = FastAPI()
app.include_router(router)
client = TestClient(app)

def test_api_report_error(temp_report_dir):
    # ErrorReportManagerとFAQManagerを一時的にモック化
    mock_manager = ErrorReportManager(report_dir=str(temp_report_dir))
    
    with mock.patch("backend.error_reporter.error_report_manager", mock_manager):
        # 1. 報告API
        res = client.post("/api/support/report", params={
            "error_type": "ConnectionError",
            "message": "Connection refused by host",
            "stack_trace": "some stack trace"
        })
        assert res.status_code == 200
        data = res.json()
        assert "report_id" in data
        assert data["related_faq"] is not None  # "Connection refused" がデフォルトFAQのfaq_1にヒットするはず
        assert data["related_faq"]["id"] == "faq_1"
        
        report_id = data["report_id"]
        
        # 2. 未解決エラー取得API
        res_unresolved = client.get("/api/support/unresolved")
        assert res_unresolved.status_code == 200
        unresolved_data = res_unresolved.json()
        assert len(unresolved_data["errors"]) == 1
        assert unresolved_data["errors"][0]["id"] == report_id
        
        # 3. 解決API
        res_resolve = client.post(f"/api/support/resolve/{report_id}", params={
            "resolution": "Checked host config."
        })
        assert res_resolve.status_code == 200
        assert res_resolve.json() == {"success": True}
        
        # 4. 統計API
        res_stats = client.get("/api/support/stats")
        assert res_stats.status_code == 200
        stats_data = res_stats.json()
        assert stats_data["total"] == 1
        assert stats_data["resolved"] == 1
        assert stats_data["unresolved"] == 0
        
        # 5. FAQ検索API
        res_faq = client.get("/api/support/faq", params={"query": "接続できません"})
        assert res_faq.status_code == 200
        faq_data = res_faq.json()
        assert len(faq_data["results"]) >= 1
        assert faq_data["results"][0]["id"] == "faq_1"


def test_error_report_manager_load_failed_prevents_save(temp_report_dir):
    report_file = temp_report_dir / "reports.json"
    report_file.write_text("invalid json structure that causes error", encoding="utf-8")
    
    # 破損ファイル検出後のバックアップ処理（os.rename）が失敗するようにモック化することで、
    # 自動復旧が機能せず _loaded が False のままになる状態を作り出す
    with mock.patch("os.rename", side_effect=OSError("Rename failed")):
        manager = ErrorReportManager(report_dir=str(temp_report_dir))
        assert manager._loaded is False
        
        # ロード失敗状態での保存は RuntimeError を引き起こすこと
        with pytest.raises(RuntimeError, match="Cannot save reports because the initial load failed"):
            manager.report_error("TypeError", "Should fail to save")


def test_error_report_manager_save_failed_propagates(temp_report_dir):
    manager = ErrorReportManager(report_dir=str(temp_report_dir))
    
    # 保存エラーが伝播することの確認
    with mock.patch("builtins.open", side_effect=OSError("Write permission denied")):
        with pytest.raises(OSError, match="Write permission denied"):
            manager.report_error("TypeError", "Propagated error")


def test_router_unexpected_error_returns_500(temp_report_dir):
    # ErrorReportManagerを一時的にモック化
    mock_manager = ErrorReportManager(report_dir=str(temp_report_dir))
    # ロード失敗状態にして保存でRuntimeErrorが発生するようにする
    mock_manager._loaded = False
    
    app = FastAPI()
    app.include_router(router)
    test_client = TestClient(app)
    
    with mock.patch("backend.error_reporter.error_report_manager", mock_manager):
        # 報告APIが500エラーを返すこと
        res = test_client.post("/api/support/report", params={
            "error_type": "ConnectionError",
            "message": "Connection refused by host"
        })
        assert res.status_code == 500
        assert "Internal server error" in res.json()["detail"]


def test_error_report_manager_lazy_initialization(tmp_path):
    report_dir = tmp_path / "lazy_reports"
    assert not report_dir.exists()
    
    manager = ErrorReportManager(report_dir=str(report_dir))
    assert not report_dir.exists()
    
    unresolved = manager.get_unresolved()
    assert unresolved == []
    assert not report_dir.exists()
    
    manager.report_error("Test", "msg")
    assert report_dir.exists()


def test_api_resolve_error_default_resolution(temp_report_dir):
    mock_manager = ErrorReportManager(report_dir=str(temp_report_dir))
    
    with mock.patch("backend.error_reporter.error_report_manager", mock_manager):
        res = client.post("/api/support/report", params={
            "error_type": "ConnectionError",
            "message": "Connection refused by host",
        })
        assert res.status_code == 200
        report_id = res.json()["report_id"]
        
        res_resolve = client.post(f"/api/support/resolve/{report_id}")
        assert res_resolve.status_code == 200
        assert res_resolve.json() == {"success": True}
        
        assert mock_manager._reports[0].resolved is True
        assert mock_manager._reports[0].resolution == "Resolved"


def test_error_report_manager_auto_recover_failure_raises_runtime_error(temp_report_dir):
    report_file = temp_report_dir / "reports.json"
    report_file.write_text("invalid json structure that causes error", encoding="utf-8")

    # 自動復旧中のバックアップ移動(os.rename)で OSError が発生した場合
    # ロード成否フラグ(_loaded)が False になり、以降の report_error で RuntimeError が発生することを検証する
    with mock.patch("os.rename", side_effect=OSError("Disk write protected")):
        manager = ErrorReportManager(report_dir=str(temp_report_dir))
        assert manager._loaded is False

        with pytest.raises(RuntimeError, match="Cannot save reports because the initial load failed"):
            manager.report_error("TypeError", "Should prevent save when auto-recover fails")
