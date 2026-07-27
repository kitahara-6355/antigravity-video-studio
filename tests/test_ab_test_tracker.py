import sys
from pathlib import Path

# backend/routers を sys.path に追加して、__init__.py の自動ロードを回避する
sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "routers"))
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import json
from unittest.mock import patch, MagicMock

# ab_test_tracker を直接インポート (backend.routers.__init__.py をバイパス)
import ab_test_tracker
from ab_test_tracker import (
    router,
    SelectThumbnailRequest,
    CTRFeedbackRequest,
    _load_json,
    _save_json,
    _analyze_prediction_accuracy,
)

# テスト用のFastAPIアプリ
app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    """SELECTION_HISTORY_PATHとCTR_FEEDBACK_PATHをテスト用の一時パスに変更する"""
    history_file = tmp_path / "selection_history_test.json"
    ctr_file = tmp_path / "ctr_feedback_test.json"
    
    monkeypatch.setattr(ab_test_tracker, "SELECTION_HISTORY_PATH", history_file)
    monkeypatch.setattr(ab_test_tracker, "CTR_FEEDBACK_PATH", ctr_file)
    
    return history_file, ctr_file


def test_load_json_non_existent(tmp_path):
    """存在しないファイルをロードした場合は空リストが返る"""
    non_existent = tmp_path / "not_found.json"
    assert _load_json(non_existent) == []


def test_load_json_corrupted(tmp_path):
    """破損したJSONファイルをロードした場合は空リストが返る"""
    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("invalid json {", encoding="utf-8")
    assert _load_json(corrupt_file) == []


def test_save_and_load_json_success(tmp_path):
    """JSONの保存と読み込みが正常に動作すること"""
    test_file = tmp_path / "nested_dir" / "test.json"
    data = [{"key": "value"}]
    _save_json(test_file, data)
    
    assert test_file.exists()
    loaded = _load_json(test_file)
    assert loaded == data


def test_select_thumbnail_success(temp_paths):
    """サムネイル選択が正常に記録されること"""
    history_file, _ = temp_paths
    
    payload = {
        "video_id": "video_01",
        "selected_index": 1,
        "thumbnail_concepts": ["concept_A", "concept_B", "concept_C"],
        "predicted_ctrs": [5.5, 7.2, 4.8],
        "reason": "Test selection reason"
    }
    
    response = client.post("/api/thumbnail/select", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["success"] is True
    assert data["record"]["video_id"] == "video_01"
    assert data["record"]["selected_concept"] == "concept_B"
    assert data["record"]["predicted_ctr"] == 7.2
    assert data["record"]["reason"] == "Test selection reason"
    
    # ファイルに書き込まれているか確認
    saved = _load_json(history_file)
    assert len(saved) == 1
    assert saved[0]["video_id"] == "video_01"


def test_select_thumbnail_out_of_bounds(temp_paths):
    """インデックスが範囲外のときの選択記録の境界値テスト"""
    # selected_indexが範囲外
    payload = {
        "video_id": "video_02",
        "selected_index": 5,
        "thumbnail_concepts": ["concept_A", "concept_B"],
        "predicted_ctrs": [5.5, 7.2],
        "reason": "Out of bounds index test"
    }
    
    response = client.post("/api/thumbnail/select", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["record"]["selected_concept"] == ""
    assert data["record"]["predicted_ctr"] == 0.0


def test_select_thumbnail_http_exception(temp_paths, monkeypatch):
    """select_thumbnail内でHTTPExceptionが発生した場合、そのまま透過すること"""
    def mock_load_raise(*args, **kwargs):
        raise HTTPException(status_code=400, detail="Mocked HTTP error")
        
    monkeypatch.setattr(ab_test_tracker, "_load_json", mock_load_raise)
    
    payload = {
        "video_id": "video_01",
        "selected_index": 0,
        "thumbnail_concepts": ["concept_A"],
        "predicted_ctrs": [5.0],
        "reason": ""
    }
    response = client.post("/api/thumbnail/select", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Mocked HTTP error"


def test_select_thumbnail_general_exception(temp_paths, monkeypatch):
    """select_thumbnail内で一般例外が発生した場合、500エラーになること"""
    def mock_load_raise(*args, **kwargs):
        raise ValueError("Database crash")
        
    monkeypatch.setattr(ab_test_tracker, "_load_json", mock_load_raise)
    
    payload = {
        "video_id": "video_01",
        "selected_index": 0,
        "thumbnail_concepts": ["concept_A"],
        "predicted_ctrs": [5.0],
        "reason": ""
    }
    response = client.post("/api/thumbnail/select", json=payload)
    assert response.status_code == 500
    assert "Database crash" in response.json()["detail"]


def test_record_ctr_feedback_success(temp_paths):
    """実CTRフィードバックが正常に記録されること"""
    history_file, _ = temp_paths
    
    # 選択履歴を事前準備
    history_data = [
        {
            "video_id": "video_01",
            "selected_index": 1,
            "selected_concept": "concept_B",
            "predicted_ctr": 7.0,
            "all_predicted_ctrs": [5.0, 7.0, 4.0],
            "reason": "Test",
            "actual_ctr": None
        }
    ]
    _save_json(history_file, history_data)
    
    payload = {
        "video_id": "video_01",
        "actual_ctr": 8.5,
        "impressions": 1000,
        "clicks": 85
    }
    
    response = client.post("/api/thumbnail/feedback", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "prediction_accuracy" in data
    
    # 保存データを確認
    saved = _load_json(history_file)
    assert saved[0]["actual_ctr"] == 8.5
    assert saved[0]["impressions"] == 1000
    assert saved[0]["clicks"] == 85
    assert saved[0]["prediction_error"] == abs(8.5 - 7.0)


def test_record_ctr_feedback_not_found(temp_paths):
    """存在しないビデオIDに対するフィードバックは失敗すること"""
    payload = {
        "video_id": "non_existent_video",
        "actual_ctr": 5.0,
        "impressions": 100,
        "clicks": 5
    }
    response = client.post("/api/thumbnail/feedback", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["message"] == "該当する動画が見つかりませんでした"


def test_record_ctr_feedback_http_exception(temp_paths, monkeypatch):
    """record_ctr_feedback内でHTTPExceptionが発生した場合、そのまま透過すること"""
    def mock_load_raise(*args, **kwargs):
        raise HTTPException(status_code=403, detail="Forbidden action")
        
    monkeypatch.setattr(ab_test_tracker, "_load_json", mock_load_raise)
    
    payload = {
        "video_id": "video_01",
        "actual_ctr": 8.5,
        "impressions": 1000,
        "clicks": 85
    }
    response = client.post("/api/thumbnail/feedback", json=payload)
    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden action"


def test_record_ctr_feedback_general_exception(temp_paths, monkeypatch):
    """record_ctr_feedback内で一般例外が発生した場合、500エラーになること"""
    def mock_load_raise(*args, **kwargs):
        raise RuntimeError("Disk full")
        
    monkeypatch.setattr(ab_test_tracker, "_load_json", mock_load_raise)
    
    payload = {
        "video_id": "video_01",
        "actual_ctr": 8.5,
        "impressions": 1000,
        "clicks": 85
    }
    response = client.post("/api/thumbnail/feedback", json=payload)
    assert response.status_code == 500
    assert "Disk full" in response.json()["detail"]


def test_get_selection_history_success(temp_paths):
    """履歴取得が正常に動作し、limitが適用されること"""
    history_file, _ = temp_paths
    
    # ダミーデータを複数件作成
    history_data = [
        {"video_id": f"video_{i}", "selected_at": f"2026-05-26T12:00:{i:02d}"}
        for i in range(1, 6)
    ]
    _save_json(history_file, history_data)
    
    # 全件取得（limit指定なし、デフォルトは20だがデータ数が5）
    response = client.get("/api/thumbnail/history")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["total"] == 5
    assert len(data["history"]) == 5
    # ソート順の確認（最新が先頭）
    assert data["history"][0]["video_id"] == "video_5"
    
    # limit制限テスト
    response = client.get("/api/thumbnail/history?limit=3")
    data = response.json()
    assert len(data["history"]) == 3
    assert data["history"][0]["video_id"] == "video_5"
    assert data["history"][2]["video_id"] == "video_3"


def test_get_selection_history_http_exception(temp_paths, monkeypatch):
    """get_selection_historyでHTTPExceptionが発生した場合、そのまま透過すること"""
    def mock_load_raise(*args, **kwargs):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    monkeypatch.setattr(ab_test_tracker, "_load_json", mock_load_raise)
    
    response = client.get("/api/thumbnail/history")
    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_get_selection_history_general_exception(temp_paths, monkeypatch):
    """get_selection_historyで一般例外が発生した場合、500エラーになること"""
    def mock_load_raise(*args, **kwargs):
        raise ValueError("Unknown format")
        
    monkeypatch.setattr(ab_test_tracker, "_load_json", mock_load_raise)
    
    response = client.get("/api/thumbnail/history")
    assert response.status_code == 500
    assert "Unknown format" in response.json()["detail"]


def test_get_prediction_accuracy_success(temp_paths):
    """予測精度取得が正常に動作すること"""
    history_file, _ = temp_paths
    
    # フィードバック済みのダミーデータを用意
    history_data = [
        {
            "video_id": "video_01",
            "selected_index": 1,
            "predicted_ctr": 7.0,
            "all_predicted_ctrs": [5.0, 7.0, 4.0],
            "actual_ctr": 8.0
        },
        {
            "video_id": "video_02",
            "selected_index": 0,
            "predicted_ctr": 6.0,
            "all_predicted_ctrs": [6.0, 5.0, 4.0],
            "actual_ctr": 5.0
        }
    ]
    _save_json(history_file, history_data)
    
    response = client.get("/api/thumbnail/accuracy")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["accuracy"]["sample_size"] == 2
    assert data["accuracy"]["average_error"] == 1.0  # abs(8-7)=1, abs(5-6)=1. Avg=1.0
    assert data["accuracy"]["correct_prediction_rate"] == 100.0  # 両方とも最大CTRコンセプトが選ばれている


def test_get_prediction_accuracy_http_exception(temp_paths, monkeypatch):
    """get_prediction_accuracyでHTTPExceptionが発生した場合、そのまま透過すること"""
    def mock_load_raise(*args, **kwargs):
        raise HTTPException(status_code=402, detail="Payment required")
        
    monkeypatch.setattr(ab_test_tracker, "_load_json", mock_load_raise)
    
    response = client.get("/api/thumbnail/accuracy")
    assert response.status_code == 402
    assert response.json()["detail"] == "Payment required"


def test_get_prediction_accuracy_general_exception(temp_paths, monkeypatch):
    """get_prediction_accuracyで一般例外が発生した場合、500エラーになること"""
    def mock_load_raise(*args, **kwargs):
        raise OSError("Permission denied")
        
    monkeypatch.setattr(ab_test_tracker, "_load_json", mock_load_raise)
    
    response = client.get("/api/thumbnail/accuracy")
    assert response.status_code == 500
    assert "Permission" in response.json()["detail"]


def test_analyze_prediction_accuracy_no_feedback():
    """フィードバックデータが全くない場合の分析"""
    history = [
        {"video_id": "video_01", "actual_ctr": None}
    ]
    res = _analyze_prediction_accuracy(history)
    assert res["sample_size"] == 0
    assert res["message"] == "フィードバックデータがまだありません"


def test_analyze_prediction_accuracy_no_predicted_ctr():
    """フィードバックはあるが、予測CTR（predicted_ctr）がない場合"""
    history = [
        {"video_id": "video_01", "actual_ctr": 8.0}  # predicted_ctr なし
    ]
    res = _analyze_prediction_accuracy(history)
    assert res["sample_size"] == 1
    assert res["message"] == "予測CTRデータがありません"


def test_analyze_prediction_accuracy_all_predicted_ctrs_empty():
    """all_predicted_ctrsが空または存在しない場合の分岐カバー"""
    history = [
        {
            "video_id": "video_01",
            "selected_index": 0,
            "predicted_ctr": 5.0,
            "actual_ctr": 6.0
            # all_predicted_ctrs なし
        }
    ]
    res = _analyze_prediction_accuracy(history)
    assert res["sample_size"] == 1
    assert res["correct_prediction_rate"] == 0.0


def test_health_check():
    """ヘルスチェックエンドポイントの検証"""
    response = client.get("/api/thumbnail/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ab_test_tracker"}
