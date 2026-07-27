"""
philosophy_router.py カバレッジ100%達成のためのユニットテスト
"""

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from unittest.mock import patch, MagicMock
import sys
import os

# パス設定
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from branding_manager import branding_manager

client = TestClient(app)

def test_list_philosophies_non_dict():
    """list_philosophiesでdict以外のデータが含まれる場合の検証"""
    mock_log = {
        "philosophies": [
            {"content": "テスト哲学1", "extracted_at": "2026-01-01", "session": 1},
            "文字列だけの古い哲学データ"
        ]
    }
    with patch.object(branding_manager, 'get_evolution_log', return_value=mock_log):
        response = client.get("/api/philosophy/list")
        assert response.status_code == 200
        data = response.json()
        philosophies = data["philosophies"]
        assert len(philosophies) == 2
        assert philosophies[0]["content"] == "テスト哲学1"
        assert philosophies[1]["content"] == "文字列だけの古い哲学データ"
        assert philosophies[1]["extractedAt"] == "不明"

def test_list_philosophies_http_exception():
    """list_philosophiesでHTTPExceptionが発生した際の挙動検証"""
    with patch.object(branding_manager, 'get_evolution_log', side_effect=HTTPException(status_code=400, detail="Bad Request")):
        response = client.get("/api/philosophy/list")
        assert response.status_code == 400
        assert response.json()["error"] == "Bad Request"

def test_list_philosophies_general_exception():
    """list_philosophiesで一般例外が発生した際の挙動検証"""
    with patch.object(branding_manager, 'get_evolution_log', side_effect=RuntimeError("DB Error")):
        response = client.get("/api/philosophy/list")
        # routers/philosophy_router.py では一般例外の時 200 でエラー辞書を返す実装になっている
        assert response.status_code == 200
        data = response.json()
        assert data["philosophies"] == []
        assert "error" in data
        assert "DB Error" in data["error"]

def test_add_philosophy_no_philosophies_key():
    """add_philosophyでevolution_logにphilosophiesキーが存在しない場合の検証"""
    mock_log = {}
    with patch.object(branding_manager, 'get_evolution_log', return_value=mock_log), \
         patch.object(branding_manager, 'save_evolution_log') as mock_save:
        response = client.post("/api/philosophy/add", json={
            "content": "新規追加テスト",
            "source": "user"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "added"
        assert data["philosophy"]["content"] == "新規追加テスト"
        
        # save_evolution_logが呼ばれ、その中にphilosophiesが含まれていること
        mock_save.assert_called_once()
        saved_log = mock_save.call_args[0][0]
        assert "philosophies" in saved_log
        assert len(saved_log["philosophies"]) == 1
        assert saved_log["philosophies"][0]["content"] == "新規追加テスト"

def test_add_philosophy_http_exception():
    """add_philosophyでHTTPExceptionが発生した際の挙動検証"""
    with patch.object(branding_manager, 'get_evolution_log', side_effect=HTTPException(status_code=403, detail="Forbidden")):
        response = client.post("/api/philosophy/add", json={
            "content": "テスト哲学",
            "source": "user"
        })
        assert response.status_code == 403
        assert response.json()["error"] == "Forbidden"

def test_add_philosophy_general_exception():
    """add_philosophyで一般例外が発生した際の挙動検証"""
    with patch.object(branding_manager, 'get_evolution_log', side_effect=RuntimeError("Write Error")):
        response = client.post("/api/philosophy/add", json={
            "content": "テスト哲学",
            "source": "user"
        })
        assert response.status_code == 500
        assert "Write Error" in response.json()["error"]

def test_get_philosophy_summary_normal():
    """get_philosophy_summaryの正常系検証"""
    mock_log = {
        "philosophies": [
            {"content": "テスト哲学1", "extracted_at": "2026-01-01", "session": 1}
        ]
    }
    with patch.object(branding_manager, 'get_evolution_log', return_value=mock_log):
        response = client.get("/api/philosophy/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 1
        assert data["latest"]["content"] == "テスト哲学1"
        assert "1件" in data["summary"]

def test_get_philosophy_summary_empty():
    """get_philosophy_summaryの空データ時の検証"""
    mock_log = {"philosophies": []}
    with patch.object(branding_manager, 'get_evolution_log', return_value=mock_log):
        response = client.get("/api/philosophy/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 0
        assert data["latest"] is None

def test_get_philosophy_summary_http_exception():
    """get_philosophy_summaryでHTTPExceptionが発生した際の挙動検証"""
    with patch.object(branding_manager, 'get_evolution_log', side_effect=HTTPException(status_code=401, detail="Unauthorized")):
        response = client.get("/api/philosophy/summary")
        assert response.status_code == 401
        assert response.json()["error"] == "Unauthorized"

def test_get_philosophy_summary_general_exception():
    """get_philosophy_summaryで一般例外が発生した際の挙動検証"""
    with patch.object(branding_manager, 'get_evolution_log', side_effect=RuntimeError("Summary Error")):
        response = client.get("/api/philosophy/summary")
        assert response.status_code == 200
        assert "error" in response.json()
        assert "Summary Error" in response.json()["error"]


def test_list_philosophies_normal():
    """list_philosophiesの正常系検証"""
    mock_log = {
        "philosophies": [
            {"content": "哲学1", "extracted_at": "2026-05-28T00:00:00", "session": 1},
            {"content": "哲学2", "extracted_at": "2026-05-28T01:00:00", "session": 2}
        ]
    }
    with patch.object(branding_manager, 'get_evolution_log', return_value=mock_log):
        response = client.get("/api/philosophy/list")
        assert response.status_code == 200
        data = response.json()
        philosophies = data["philosophies"]
        assert len(philosophies) == 2
        assert philosophies[0]["id"] == "phil_0"
        assert philosophies[0]["content"] == "哲学1"
        assert philosophies[0]["extractedAt"] == "2026-05-28T00:00:00"
        assert philosophies[0]["session"] == 1
        assert philosophies[1]["id"] == "phil_1"
        assert philosophies[1]["content"] == "哲学2"
        assert philosophies[1]["extractedAt"] == "2026-05-28T01:00:00"
        assert philosophies[1]["session"] == 2

def test_add_philosophy_normal():
    """add_philosophyの正常系検証（既にphilosophiesキーが存在する場合）"""
    mock_log = {
        "philosophies": [
            {"content": "既存の哲学", "source": "user", "extracted_at": "2026-05-28T00:00:00"}
        ]
    }
    with patch.object(branding_manager, 'get_evolution_log', return_value=mock_log),          patch.object(branding_manager, 'save_evolution_log') as mock_save:
        response = client.post("/api/philosophy/add", json={
            "content": "追加の哲学",
            "source": "api"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "added"
        assert data["philosophy"]["content"] == "追加の哲学"
        assert data["philosophy"]["source"] == "api"
        
        # save_evolution_logが呼ばれ、既存データに追記されていること
        mock_save.assert_called_once()
        saved_log = mock_save.call_args[0][0]
        assert len(saved_log["philosophies"]) == 2
        assert saved_log["philosophies"][0]["content"] == "既存の哲学"
        assert saved_log["philosophies"][1]["content"] == "追加の哲学"
