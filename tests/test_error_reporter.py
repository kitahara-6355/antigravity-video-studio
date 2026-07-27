import os
import json
import logging
import pytest
from unittest.mock import patch, mock_open, MagicMock
from datetime import datetime
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.error_reporter import (
    ErrorReport,
    FAQEntry,
    ErrorReportManager,
    FAQManager,
    router
)

# 1. データクラスのテスト
def test_error_report_dataclass():
    report = ErrorReport(id="test_id", error_type="ValueError", message="Invalid value")
    assert report.id == "test_id"
    assert report.error_type == "ValueError"
    assert report.message == "Invalid value"
    assert report.stack_trace == ""
    assert report.context == {}
    assert isinstance(report.timestamp, str)
    assert report.resolved is False
    assert report.resolution == ""

def test_faq_entry_dataclass():
    entry = FAQEntry(id="faq_test", question="What?", answer="This.")
    assert entry.id == "faq_test"
    assert entry.question == "What?"
    assert entry.answer == "This."
    assert entry.keywords == []
    assert entry.error_patterns == []

# 2. ErrorReportManagerのテスト
def test_error_report_manager_init(tmp_path):
    report_dir = tmp_path / "reports"
    manager = ErrorReportManager(report_dir=str(report_dir))
    assert manager._reports == []
    manager.report_error("Test", "Msg")
    assert os.path.exists(str(report_dir))

def test_error_report_manager_load_reports(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    
    # 正常なデータ
    reports_data = [
        {
            "id": "err1",
            "error_type": "KeyError",
            "message": "Key missing",
            "stack_trace": "line 1",
            "context": {"user": "test"},
            "timestamp": "2026-05-25T10:00:00",
            "resolved": False,
            "resolution": ""
        }
    ]
    report_file = report_dir / "reports.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(reports_data, f)
        
    manager = ErrorReportManager(report_dir=str(report_dir))
    assert len(manager._reports) == 1
    assert manager._reports[0].id == "err1"
    assert manager._reports[0].error_type == "KeyError"

def test_error_report_manager_load_reports_json_decode_error(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_file = report_dir / "reports.json"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("{invalid_json")
        
    with patch("backend.error_reporter.logger") as mock_logger:
        manager = ErrorReportManager(report_dir=str(report_dir))
        assert manager._reports == []
        mock_logger.warning.assert_called_once()

def test_error_report_manager_load_reports_type_error(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_file = report_dir / "reports.json"
    # リストではなく辞書を保存してTypeErrorを誘発させる
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({"not": "a list"}, f)
        
    with patch("backend.error_reporter.logger") as mock_logger:
        manager = ErrorReportManager(report_dir=str(report_dir))
        assert manager._reports == []
        # 自動復旧が走るため、warningログが記録される
        assert mock_logger.warning.called
        assert manager._loaded is True
        assert os.path.exists(str(report_file) + ".bak")

def test_error_report_manager_load_reports_key_error(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_file = report_dir / "reports.json"
    # 必須キー 'id' が欠けているデータ
    reports_data = [
        {
            "error_type": "KeyError",
            "message": "Key missing",
            "stack_trace": "line 1",
            "context": {},
            "timestamp": "2026-05-25T10:00:00",
            "resolved": False,
            "resolution": ""
        }
    ]
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(reports_data, f)
        
    with patch("backend.error_reporter.logger") as mock_logger:
        manager = ErrorReportManager(report_dir=str(report_dir))
        assert manager._reports == []
        mock_logger.warning.assert_called_once()

def test_error_report_manager_save_reports_os_error(tmp_path):
    report_dir = tmp_path / "reports"
    manager = ErrorReportManager(report_dir=str(report_dir))
    manager.report_error(error_type="TestError", message="Test message")
    
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        with patch("backend.error_reporter.logger") as mock_logger:
            with pytest.raises(OSError, match="Permission denied"):
                manager._save_reports()
            mock_logger.error.assert_called_once()

def test_error_report_manager_report_error(tmp_path):
    report_dir = tmp_path / "reports"
    manager = ErrorReportManager(report_dir=str(report_dir))
    
    report_id = manager.report_error(
        error_type="TypeError",
        message="Type mismatch",
        stack_trace="traceback",
        context={"step": 1}
    )
    assert len(report_id) == 8
    assert len(manager._reports) == 1
    assert manager._reports[0].id == report_id
    assert manager._reports[0].error_type == "TypeError"
    assert manager._reports[0].message == "Type mismatch"
    assert manager._reports[0].stack_trace == "traceback"
    assert manager._reports[0].context == {"step": 1}

def test_error_report_manager_resolve_error(tmp_path):
    report_dir = tmp_path / "reports"
    manager = ErrorReportManager(report_dir=str(report_dir))
    
    report_id = manager.report_error(error_type="Error", message="Message")
    assert manager.get_unresolved()[0].id == report_id
    
    # 存在しないIDでの解決
    success = manager.resolve_error("invalid_id", "Not fixed")
    assert success is False
    assert manager.get_unresolved()[0].id == report_id
    
    # 存在するIDでの解決
    success = manager.resolve_error(report_id, "Fixed it")
    assert success is True
    assert len(manager.get_unresolved()) == 0
    assert manager._reports[0].resolved is True
    assert manager._reports[0].resolution == "Fixed it"

def test_error_report_manager_get_stats(tmp_path):
    report_dir = tmp_path / "reports"
    manager = ErrorReportManager(report_dir=str(report_dir))
    
    manager.report_error(error_type="ValueError", message="Err1")
    manager.report_error(error_type="ValueError", message="Err2")
    err3_id = manager.report_error(error_type="TypeError", message="Err3")
    
    manager.resolve_error(err3_id, "Fixed")
    
    stats = manager.get_stats()
    assert stats["total"] == 3
    assert stats["unresolved"] == 2
    assert stats["resolved"] == 1
    assert stats["by_type"] == {"ValueError": 2, "TypeError": 1}

# 3. FAQManagerのテスト
def test_faq_manager_init():
    manager = FAQManager()
    assert len(manager._faqs) == 3
    assert manager._faqs[0].id == "faq_1"

def test_faq_manager_search():
    manager = FAQManager()
    
    # キーキーワードマッチ (接続 -> faq_1)
    results = manager.search("接続テスト")
    assert len(results) >= 1
    assert results[0].id == "faq_1"
    
    # 質問テキストマッチ ("バックエンドに接続できません" -> faq_1)
    results = manager.search("バックエンドに")
    assert len(results) >= 1
    assert results[0].id == "faq_1"
    
    # エラーパターンマッチ ("CUDA out of memory" -> faq_2)
    results = manager.search("CUDA out of memory error occurred")
    assert len(results) >= 1
    assert results[0].id == "faq_2"
    
    # マッチしない場合
    results = manager.search("全く関係ないクエリ")
    assert len(results) == 0

def test_faq_manager_find_for_error():
    manager = FAQManager()
    
    # 存在するエラーパターン
    faq = manager.find_for_error("Connection refused by host")
    assert faq is not None
    assert faq.id == "faq_1"
    
    # 存在しない
    faq = manager.find_for_error("unknown failure")
    assert faq is None

def test_faq_manager_add_faq():
    manager = FAQManager()
    new_faq = FAQEntry(id="faq_4", question="New Q", answer="New A", keywords=["new"], error_patterns=["new_pattern"])
    manager.add_faq(new_faq)
    assert len(manager._faqs) == 4
    assert manager.find_for_error("new_pattern").id == "faq_4"

# 4. FastAPIルーターのテスト
@pytest.fixture
def client(tmp_path):
    # テストごとに独立したManagerを割り当ててシングルトンをモック化
    test_report_dir = tmp_path / "api_reports"
    test_report_manager = ErrorReportManager(report_dir=str(test_report_dir))
    test_faq_manager = FAQManager()
    
    app = FastAPI()
    app.include_router(router)
    
    with patch("backend.error_reporter.error_report_manager", test_report_manager), \
         patch("backend.error_reporter.faq_manager", test_faq_manager):
        yield TestClient(app)

def test_router_report_error(client):
    response = client.post(
        "/api/support/report",
        params={
            "error_type": "ConnectionError",
            "message": "Connection refused by target",
            "stack_trace": "some traceback"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "report_id" in data
    assert data["related_faq"] is not None
    assert data["related_faq"]["id"] == "faq_1"

def test_router_report_error_no_faq(client):
    response = client.post(
        "/api/support/report",
        params={
            "error_type": "UnknownError",
            "message": "Something totally unexpected happened",
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "report_id" in data
    assert data["related_faq"] is None

def test_router_get_unresolved_errors(client):
    # 初期状態
    response = client.get("/api/support/unresolved")
    assert response.status_code == 200
    assert response.json() == {"errors": []}
    
    # 追加後
    client.post(
        "/api/support/report",
        params={"error_type": "ValueError", "message": "Oops"}
    )
    response = client.get("/api/support/unresolved")
    assert response.status_code == 200
    errors = response.json()["errors"]
    assert len(errors) == 1
    assert errors[0]["message"] == "Oops"

def test_router_resolve_error(client):
    report_response = client.post(
        "/api/support/report",
        params={"error_type": "ValueError", "message": "Oops"}
    )
    report_id = report_response.json()["report_id"]
    
    # 解決
    resolve_response = client.post(
        f"/api/support/resolve/{report_id}",
        params={"resolution": "Fixed by resetting"}
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json() == {"success": True}
    
    # 未解決リストが空になったことを確認
    unresolved_response = client.get("/api/support/unresolved")
    assert len(unresolved_response.json()["errors"]) == 0

def test_router_search_faq(client):
    response = client.get("/api/support/faq", params={"query": "接続できません"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) >= 1
    assert results[0]["id"] == "faq_1"

def test_router_get_error_stats(client):
    client.post(
        "/api/support/report",
        params={"error_type": "ValueError", "message": "Oops1"}
    )
    client.post(
        "/api/support/report",
        params={"error_type": "TypeError", "message": "Oops2"}
    )
    
    response = client.get("/api/support/stats")
    assert response.status_code == 200
    stats = response.json()
    assert stats["total"] == 2
    assert stats["unresolved"] == 2
    assert stats["resolved"] == 0
    assert stats["by_type"] == {"ValueError": 1, "TypeError": 1}

# 5. 堅牢性向上のための追加テスト

def test_error_report_manager_init_empty_path():
    # 空文字や空白文字の場合にデフォルトパスにフォールバックすることの検証
    manager1 = ErrorReportManager(report_dir="")
    assert "error_reports" in manager1.report_dir
    
    manager2 = ErrorReportManager(report_dir="   ")
    assert "error_reports" in manager2.report_dir

def test_error_report_manager_load_reports_invalid_format(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_file = report_dir / "reports.json"
    
    # リストではない JSON データ (辞書)
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({"not": "a list"}, f)
        
    with patch("backend.error_reporter.logger") as mock_logger:
        manager = ErrorReportManager(report_dir=str(report_dir))
        assert manager._reports == []
        assert mock_logger.warning.called
        assert manager._loaded is True

def test_error_report_manager_load_reports_partial_corruption(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_file = report_dir / "reports.json"
    
    # 一部破損（リストの要素が辞書ではない、キーが足りない等）
    reports_data = [
        "not_a_dict",
        {
            "id": "err1",
            "error_type": "KeyError",
            "message": "Key missing",
            "stack_trace": "line 1",
            "context": {"user": "test"},
            "timestamp": "2026-05-25T10:00:00",
            "resolved": False,
            "resolution": ""
        },
        {
            "error_type": "KeyError" # id がない
        }
    ]
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(reports_data, f)
        
    with patch("backend.error_reporter.logger") as mock_logger:
        manager = ErrorReportManager(report_dir=str(report_dir))
        # 正しいもの (err1) だけがロードされているはず
        assert len(manager._reports) == 1
        assert manager._reports[0].id == "err1"
        assert mock_logger.warning.call_count >= 2

def test_error_report_manager_save_non_serializable_context(tmp_path):
    report_dir = tmp_path / "reports"
    manager = ErrorReportManager(report_dir=str(report_dir))
    
    class UnserializableObj:
        def __str__(self):
            return "unserializable"
    
    report = ErrorReport(
        id="test_unserializable",
        error_type="TestError",
        message="Message",
        context={"bad_value": UnserializableObj()}
    )
    manager._reports.append(report)
    
    # 例外を投げずに default=str によって安全にシリアライズされて保存されること
    manager._save_reports()
    
    report_file = os.path.join(str(report_dir), "reports.json")
    with open(report_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        assert len(data) == 1
        assert "unserializable" in str(data[0]["context"]["bad_value"])

def test_error_report_manager_report_error_invalid_inputs(tmp_path):
    report_dir = tmp_path / "reports"
    manager = ErrorReportManager(report_dir=str(report_dir))
    
    # error_type が空
    with pytest.raises(ValueError, match="error_type must be a non-empty string"):
        manager.report_error(error_type="", message="Msg")
    
    # message が空
    with pytest.raises(ValueError, match="message must be a non-empty string"):
        manager.report_error(error_type="Err", message="   ")
        
    # context が辞書ではない
    with pytest.raises(TypeError, match="context must be a dictionary"):
        manager.report_error(error_type="Err", message="Msg", context="not a dict")

def test_error_report_manager_resolve_error_invalid_inputs(tmp_path):
    report_dir = tmp_path / "reports"
    manager = ErrorReportManager(report_dir=str(report_dir))
    
    report_id = manager.report_error(error_type="Err", message="Msg")
    
    # ID が不正
    assert manager.resolve_error("", "Fixed") is False
    assert manager.resolve_error(None, "Fixed") is False
    
    # resolution が不正な場合は default にフォールバック
    assert manager.resolve_error(report_id, "") is True
    assert manager._reports[0].resolved is True
    assert manager._reports[0].resolution == "Resolved"

def test_faq_manager_search_invalid_inputs():
    manager = FAQManager()
    # query が None や空文字列など
    assert manager.search(None) == []
    assert manager.search("") == []
    assert manager.search("   ") == []
    assert manager.search(123) == []

def test_faq_manager_search_corrupted_faq_keywords_and_patterns():
    manager = FAQManager()
    
    # keywords や error_patterns が None な FAQEntry
    corrupted_faq = FAQEntry(
        id="faq_corrupted",
        question="What?",
        answer="This.",
        keywords=None,
        error_patterns=None
    )
    manager.add_faq(corrupted_faq)
    
    # keywords/patterns が None でも例外が発生せず検索が通ること
    assert manager.search("What?") == [corrupted_faq]

def test_faq_manager_find_for_error_invalid_inputs():
    manager = FAQManager()
    assert manager.find_for_error(None) is None
    assert manager.find_for_error("") is None

def test_faq_manager_add_faq_invalid_type():
    manager = FAQManager()
    with pytest.raises(TypeError, match="faq must be an instance of FAQEntry"):
        manager.add_faq("not an FAQEntry")

# ルーター層のバリデーションテスト
def test_router_report_error_empty_inputs(client):
    # error_type が空
    response = client.post(
        "/api/support/report",
        params={
            "error_type": "",
            "message": "Connection refused",
        }
    )
    assert response.status_code == 400
    assert "error_type must be a non-empty string" in response.json()["detail"]
    
    # message が空
    response = client.post(
        "/api/support/report",
        params={
            "error_type": "ValueError",
            "message": "  ",
        }
    )
    assert response.status_code == 400
    assert "message must be a non-empty string" in response.json()["detail"]

def test_router_report_error_validation_exception(client):
    # context が不正な型で送信され、TypeErrorが投げられた時
    response = client.post(
        "/api/support/report",
        params={
            "error_type": "ValueError",
            "message": "Oops",
        },
        json=["invalid_context_type_list"]
    )
    assert response.status_code == 400
    assert "context must be a dictionary" in response.json()["detail"]

def test_router_resolve_error_empty_inputs(client):
    response = client.post(
        "/api/support/resolve/report_id_123",
        params={"resolution": "  "}
    )
    assert response.status_code == 400
    assert "resolution cannot be empty" in response.json()["detail"]
    
    response = client.post(
        "/api/support/resolve/ ",
        params={"resolution": "Fixed"}
    )
    assert response.status_code in (400, 404)

def test_router_search_faq_empty_query(client):
    response = client.get("/api/support/faq", params={"query": "  "})
    assert response.status_code == 400
    assert "query cannot be empty" in response.json()["detail"]


# 6. 新規追加した堅牢性・エラーハンドリング強化のテスト

def test_error_report_manager_corrupted_file_recovery(tmp_path):
    report_dir = tmp_path / "corrupted_reports"
    report_dir.mkdir()
    report_file = report_dir / "reports.json"
    
    # 壊れた JSON データを書き込む
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("{invalid_json_data")
        
    # ロード時に自動復旧が走り、空のリストで初期化されること
    manager = ErrorReportManager(report_dir=str(report_dir))
    assert manager._reports == []
    assert manager._loaded is True
    
    # バックアップファイルが作成されていることを検証
    backup_file = str(report_file) + ".bak"
    assert os.path.exists(backup_file)
    with open(backup_file, "r", encoding="utf-8") as f:
        assert f.read() == "{invalid_json_data"
        
    # エラー報告が正常に行われ、保存ができることを確認
    report_id = manager.report_error(error_type="TestRecovery", message="It works")
    assert len(manager._reports) == 1
    assert manager._reports[0].id == report_id


def test_error_report_manager_empty_file_load(tmp_path):
    report_dir = tmp_path / "empty_reports"
    report_dir.mkdir()
    report_file = report_dir / "reports.json"
    
    # 0 バイトの空ファイルを書き込む
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("")
        
    manager = ErrorReportManager(report_dir=str(report_dir))
    assert manager._reports == []
    assert manager._loaded is True
    
    # 新規エラー報告が正常に機能することを確認
    report_id = manager.report_error(error_type="TestEmpty", message="Works")
    assert len(manager._reports) == 1


def test_faq_manager_add_faq_invalid_fields():
    manager = FAQManager()
    
    # question が None や空文字列
    with pytest.raises(ValueError, match="faq.question must be a non-empty string"):
        manager.add_faq(FAQEntry(id="err_q", question="", answer="Answer"))
        
    # answer が None や空文字列
    with pytest.raises(ValueError, match="faq.answer must be a non-empty string"):
        manager.add_faq(FAQEntry(id="err_a", question="Question", answer="  "))
        
    # keywords がリストではない
    with pytest.raises(TypeError, match="faq.keywords must be a list"):
        manager.add_faq(FAQEntry(id="err_k", question="Question", answer="Answer", keywords="not_a_list")) # type: ignore
        
    # error_patterns がリストではない
    with pytest.raises(TypeError, match="faq.error_patterns must be a list"):
        manager.add_faq(FAQEntry(id="err_p", question="Question", answer="Answer", error_patterns="not_a_list")) # type: ignore


def test_router_report_error_os_error_handling(tmp_path):
    # ErrorReportManager.report_error が OSError を投げた時のルーターハンドリングをテスト
    app = FastAPI()
    app.include_router(router)
    
    test_report_dir = tmp_path / "os_error_reports"
    test_report_manager = ErrorReportManager(report_dir=str(test_report_dir))
    test_faq_manager = FAQManager()
    
    # report_error が OSError を投げるようにモック化
    test_report_manager.report_error = MagicMock(side_effect=OSError("Disk Full"))
    
    with patch("backend.error_reporter.error_report_manager", test_report_manager), \
         patch("backend.error_reporter.faq_manager", test_faq_manager):
        client = TestClient(app)
        response = client.post(
            "/api/support/report",
            params={
                "error_type": "ConnectionError",
                "message": "Connection refused",
            }
        )
        assert response.status_code == 503
        assert "Service temporary unavailable due to storage issue" in response.json()["detail"]


def test_router_resolve_error_os_error_handling(tmp_path):
    # ErrorReportManager.resolve_error が OSError を投げた時
    app = FastAPI()
    app.include_router(router)
    
    test_report_dir = tmp_path / "os_error_reports_resolve"
    test_report_manager = ErrorReportManager(report_dir=str(test_report_dir))
    test_faq_manager = FAQManager()
    
    test_report_manager.resolve_error = MagicMock(side_effect=OSError("Write permission denied"))
    
    with patch("backend.error_reporter.error_report_manager", test_report_manager), \
         patch("backend.error_reporter.faq_manager", test_faq_manager):
        client = TestClient(app)
        response = client.post(
            "/api/support/resolve/err_id_123",
            params={"resolution": "Fixed"}
        )
        assert response.status_code == 503


def test_error_report_manager_load_reports_invalid_format_recovery(tmp_path):
    report_dir = tmp_path / "reports_recovery"
    report_dir.mkdir()
    report_file = report_dir / "reports.json"
    
    # 辞書形式（非リスト）のJSONデータを書き込む
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({"error_id": "dummy", "message": "invalid format"}, f)
        
    # ロード時に自動復旧が走り、_loaded=Trueになり、空で初期化されること
    manager = ErrorReportManager(report_dir=str(report_dir))
    assert manager._reports == []
    assert manager._loaded is True
    
    # バックアップファイルが作成されていることを検証
    backup_file = str(report_file) + ".bak"
    assert os.path.exists(backup_file)
    with open(backup_file, "r", encoding="utf-8") as f:
        backup_data = json.load(f)
        assert backup_data["error_id"] == "dummy"
        
    # 新規エラー報告が正常に機能し、保存ができることを確認
    report_id = manager.report_error(error_type="TestRecovery", message="It works")
    assert len(manager._reports) == 1
    assert manager._reports[0].id == report_id
