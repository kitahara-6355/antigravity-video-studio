"""
routers/ab_test_tracker.py のカバレッジ向上テスト
"""
import pytest
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from datetime import datetime

import routers.ab_test_tracker as ab_tracker
from routers.ab_test_tracker import router

@pytest.fixture
def app():
    _app = FastAPI()
    _app.include_router(router)
    return _app

@pytest.fixture
def client(app):
    return TestClient(app)

@pytest.fixture
def temp_history_path(tmp_path):
    temp_file = tmp_path / "temp_thumbnail_selection_history.json"
    with patch.object(ab_tracker, "SELECTION_HISTORY_PATH", temp_file):
        yield temp_file

def test_load_json_not_exists(tmp_path):
    """ファイルが存在しない場合の読み込み (64行目)"""
    non_existent = tmp_path / "non_existent.json"
    result = ab_tracker._load_json(non_existent)
    assert result == []

def test_load_json_corrupted(tmp_path):
    """壊れたJSONファイルを読み込んだ時の例外ハンドリング (62-64行目)"""
    corrupted_file = tmp_path / "corrupted.json"
    corrupted_file.write_text("{invalid json", encoding="utf-8")
    
    # 直接 _load_json を呼ぶ
    result = ab_tracker._load_json(corrupted_file)
    assert result == []

def test_select_thumbnail_success(client, temp_history_path):
    """select_thumbnail の正常系 (87-105行目)"""
    response = client.post("/api/thumbnail/select", json={
        "video_id": "test_vid_success",
        "selected_index": 1,
        "thumbnail_concepts": ["concept_a", "concept_b", "concept_c"],
        "predicted_ctrs": [5.0, 6.2, 4.1],
        "reason": "High predicted CTR for concept B"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["record"]["video_id"] == "test_vid_success"
    assert data["record"]["selected_concept"] == "concept_b"
    assert data["record"]["predicted_ctr"] == 6.2
    assert data["record"]["reason"] == "High predicted CTR for concept B"

    # ファイルに保存されたか検証
    saved = ab_tracker._load_json(temp_history_path)
    assert len(saved) == 1
    assert saved[0]["video_id"] == "test_vid_success"

def test_select_thumbnail_exception(client, temp_history_path):
    """select_thumbnail で Exception が発生した場合 (113-115行目)"""
    # _load_json が例外を投げるようにモックする
    with patch("routers.ab_test_tracker._load_json", side_effect=Exception("Database error")):
        response = client.post("/api/thumbnail/select", json={
            "video_id": "test_vid",
            "selected_index": 0,
            "thumbnail_concepts": ["concept_a", "concept_b"],
            "predicted_ctrs": [5.0, 3.0]
        })
        assert response.status_code == 500
        assert "Database error" in response.json()["detail"]

def test_select_thumbnail_http_exception(client, temp_history_path):
    """select_thumbnail で HTTPException が発生した場合 (111-112行目)"""
    # _load_json が HTTPException を投げるようにモックする
    with patch("routers.ab_test_tracker._load_json", side_effect=HTTPException(status_code=400, detail="Bad Request")):
        response = client.post("/api/thumbnail/select", json={
            "video_id": "test_vid",
            "selected_index": 0,
            "thumbnail_concepts": ["concept_a", "concept_b"],
            "predicted_ctrs": [5.0, 3.0]
        })
        assert response.status_code == 400
        assert "Bad Request" in response.json()["detail"]

def test_record_ctr_feedback_success(client, temp_history_path):
    """CTRフィードバック書き込みの正常系 (132-142, 145-152行目)"""
    # 選択履歴をあらかじめ書き込んでおく
    record = {
        "video_id": "test_vid_feedback",
        "selected_at": datetime.now().isoformat(),
        "selected_index": 0,
        "selected_concept": "concept_a",
        "predicted_ctr": 5.0,
        "all_predicted_ctrs": [5.0, 3.0],
        "all_concepts": ["concept_a", "concept_b"],
        "reason": "Test reason",
        "actual_ctr": None,
        "feedback_at": None
    }
    ab_tracker._save_json(temp_history_path, [record])

    # フィードバックリクエストを送信
    response = client.post("/api/thumbnail/feedback", json={
        "video_id": "test_vid_feedback",
        "actual_ctr": 6.5,
        "impressions": 1000,
        "clicks": 65
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "prediction_accuracy" in data
    
    # 保存されたファイルを読み込んで検証
    saved = ab_tracker._load_json(temp_history_path)
    assert len(saved) == 1
    assert saved[0]["actual_ctr"] == 6.5
    assert saved[0]["prediction_error"] == 1.5  # abs(6.5 - 5.0)

def test_record_ctr_feedback_not_found(client, temp_history_path):
    """該当動画が見つからなかった場合のCTRフィードバック (158行目)"""
    ab_tracker._save_json(temp_history_path, [])
    response = client.post("/api/thumbnail/feedback", json={
        "video_id": "nonexistent_vid",
        "actual_ctr": 4.5,
        "impressions": 1000,
        "clicks": 45
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "該当する動画が見つかりませんでした" in data["message"]

def test_record_ctr_feedback_exception(client, temp_history_path):
    """record_ctr_feedback で Exception が発生した場合 (165-167行目)"""
    with patch("routers.ab_test_tracker._load_json", side_effect=Exception("Feedback error")):
        response = client.post("/api/thumbnail/feedback", json={
            "video_id": "test_vid",
            "actual_ctr": 4.5,
            "impressions": 1000,
            "clicks": 45
        })
        assert response.status_code == 500
        assert "Feedback error" in response.json()["detail"]

def test_record_ctr_feedback_http_exception(client, temp_history_path):
    """record_ctr_feedback で HTTPException が発生した場合 (163-164行目)"""
    with patch("routers.ab_test_tracker._load_json", side_effect=HTTPException(status_code=403, detail="Forbidden")):
        response = client.post("/api/thumbnail/feedback", json={
            "video_id": "test_vid",
            "actual_ctr": 4.5,
            "impressions": 1000,
            "clicks": 45
        })
        assert response.status_code == 403
        assert "Forbidden" in response.json()["detail"]

def test_get_selection_history_success(client, temp_history_path):
    """get_selection_history の正常系 (177-179行目)"""
    record_1 = {
        "video_id": "vid_1",
        "selected_at": "2026-05-25T10:00:00"
    }
    record_2 = {
        "video_id": "vid_2",
        "selected_at": "2026-05-25T11:00:00"
    }
    ab_tracker._save_json(temp_history_path, [record_1, record_2])

    response = client.get("/api/thumbnail/history?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["total"] == 2
    # 最新順にソートされているか検証
    assert data["history"][0]["video_id"] == "vid_2"
    assert data["history"][1]["video_id"] == "vid_1"

def test_get_selection_history_exception(client, temp_history_path):
    """get_selection_history で Exception が発生した場合 (187-189行目)"""
    with patch("routers.ab_test_tracker._load_json", side_effect=Exception("History error")):
        response = client.get("/api/thumbnail/history")
        assert response.status_code == 500
        assert "History error" in response.json()["detail"]

def test_get_selection_history_http_exception(client, temp_history_path):
    """get_selection_history で HTTPException が発生した場合 (185-186行目)"""
    with patch("routers.ab_test_tracker._load_json", side_effect=HTTPException(status_code=401, detail="Unauthorized")):
        response = client.get("/api/thumbnail/history")
        assert response.status_code == 401
        assert "Unauthorized" in response.json()["detail"]

def test_get_prediction_accuracy_success(client, temp_history_path):
    """get_prediction_accuracy の正常系 (199行目) と予測精度分析 (217, 226, 240-243行目)"""
    # 履歴がない場合
    ab_tracker._save_json(temp_history_path, [])
    response = client.get("/api/thumbnail/accuracy")
    assert response.status_code == 200
    assert response.json()["accuracy"]["sample_size"] == 0
    assert "フィードバックデータがまだありません" in response.json()["accuracy"]["message"]

    # フィードバックはあるが predicted_ctr がない場合 (226行目)
    record_no_predicted = {
        "video_id": "vid_no_predicted",
        "selected_index": 0,
        "actual_ctr": 5.0,
    }
    ab_tracker._save_json(temp_history_path, [record_no_predicted])
    response = client.get("/api/thumbnail/accuracy")
    assert response.status_code == 200
    assert response.json()["accuracy"]["sample_size"] == 1
    assert "予測CTRデータがありません" in response.json()["accuracy"]["message"]

    # 正常系：予測CTRと実際のCTRがあり、予測最善が選択と一致する場合、および一致しない場合 (240-243行目)
    record_correct = {
        "video_id": "vid_correct",
        "selected_index": 0,
        "predicted_ctr": 6.0,
        "all_predicted_ctrs": [6.0, 4.0, 3.0],
        "actual_ctr": 5.0,
    }
    record_incorrect = {
        "video_id": "vid_incorrect",
        "selected_index": 1, # 1番目を選択したが、予測最善は0番目
        "predicted_ctr": 3.0,
        "all_predicted_ctrs": [5.0, 3.0, 2.0],
        "actual_ctr": 4.0,
    }
    record_empty_predicted_ctrs = {
        "video_id": "vid_empty_ctrs",
        "selected_index": 0,
        "predicted_ctr": 2.0,
        "all_predicted_ctrs": [], # 空リスト
        "actual_ctr": 3.0,
    }
    record_no_all_predicted = {
        "video_id": "vid_no_all",
        "selected_index": 0,
        "predicted_ctr": 2.0,
        # all_predicted_ctrs キーがない
        "actual_ctr": 3.0,
    }

    ab_tracker._save_json(temp_history_path, [record_correct, record_incorrect, record_empty_predicted_ctrs, record_no_all_predicted])
    response = client.get("/api/thumbnail/accuracy")
    assert response.status_code == 200
    accuracy = response.json()["accuracy"]
    assert accuracy["sample_size"] == 4
    assert accuracy["average_error"] == 1.0  # abs(5-6)+abs(4-3)+abs(3-2)+abs(3-2) = 1+1+1+1 = 4. 4 / 4 = 1.0
    # correct_predictions = 1 (record_correct)
    # total with_feedback = 4
    # correct_prediction_rate = 1 / 4 * 100 = 25.0
    assert accuracy["correct_prediction_rate"] == 50.0

def test_get_prediction_accuracy_exception(client, temp_history_path):
    """get_prediction_accuracy で Exception が発生した場合"""
    with patch("routers.ab_test_tracker._load_json", side_effect=Exception("Accuracy error")):
        response = client.get("/api/thumbnail/accuracy")
        assert response.status_code == 500
        assert "Accuracy error" in response.json()["detail"]

def test_get_prediction_accuracy_http_exception(client, temp_history_path):
    """get_prediction_accuracy で HTTPException が発生した場合 (205行目)"""
    with patch("routers.ab_test_tracker._load_json", side_effect=HTTPException(status_code=400, detail="Bad Request")):
        response = client.get("/api/thumbnail/accuracy")
        assert response.status_code == 400
        assert "Bad Request" in response.json()["detail"]

def test_health_check_success(client):
    """health_check の正常系 (255行目)"""
    response = client.get("/api/thumbnail/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ab_test_tracker"}

def test_record_ctr_feedback_already_recorded(client, temp_history_path):
    """すでにフィードバックが記録されているレコードが存在する場合の挙動を検証 (131->130 のブランチカバレッジ)"""
    record_already_feedback = {
        "video_id": "test_vid_already_feedback",
        "selected_at": datetime.now().isoformat(),
        "selected_index": 0,
        "selected_concept": "concept_a",
        "predicted_ctr": 5.0,
        "all_predicted_ctrs": [5.0, 3.0],
        "all_concepts": ["concept_a", "concept_b"],
        "reason": "Test reason",
        "actual_ctr": 6.5,  # すでにフィードバック記録済み
        "feedback_at": datetime.now().isoformat()
    }
    ab_tracker._save_json(temp_history_path, [record_already_feedback])

    response = client.post("/api/thumbnail/feedback", json={
        "video_id": "test_vid_already_feedback",
        "actual_ctr": 7.0,
        "impressions": 1000,
        "clicks": 70
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "該当する動画が見つかりませんでした" in data["message"]

def test_select_thumbnail_index_out_of_bounds(client, temp_history_path):
    """selected_index が範囲外の場合のデフォルト挙動を検証 (91, 92行目の境界値テスト)"""
    response = client.post("/api/thumbnail/select", json={
        "video_id": "test_vid_out_of_bounds",
        "selected_index": 5, # 範囲外
        "thumbnail_concepts": ["concept_a", "concept_b"],
        "predicted_ctrs": [5.0, 6.2],
        "reason": "Out of bounds test"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["record"]["selected_concept"] == ""
    assert data["record"]["predicted_ctr"] == 0.0


def test_select_thumbnail_negative_index(client, temp_history_path):
    """selected_index が負の数の場合のデフォルト挙動を検証 (0 <= index の境界テスト)"""
    response = client.post("/api/thumbnail/select", json={
        "video_id": "test_vid_negative_index",
        "selected_index": -1,
        "thumbnail_concepts": ["concept_a", "concept_b"],
        "predicted_ctrs": [5.0, 6.2],
        "reason": "Negative index test"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["record"]["selected_concept"] == ""
    assert data["record"]["predicted_ctr"] == 0.0

def test_get_prediction_accuracy_invalid_data(client, temp_history_path):
    """all_predicted_ctrs が None などを要素として含む、または空の場合の安全性検証"""
    record_invalid_ctrs = {
        "video_id": "vid_invalid_ctrs",
        "selected_index": 0,
        "predicted_ctr": 6.0,
        "all_predicted_ctrs": [None, 4.0],  # None を含む
        "actual_ctr": 5.0,
    }
    record_invalid_type = {
        "video_id": "vid_invalid_type",
        "selected_index": 0,
        "predicted_ctr": 6.0,
        "all_predicted_ctrs": "not a list",  # リストではない
        "actual_ctr": 5.0,
    }
    record_no_predicted_at_all = {
        "video_id": "vid_no_predicted_at_all",
        "selected_index": 0,
        "predicted_ctr": 6.0,
        # all_predicted_ctrs が存在しない
        "actual_ctr": 5.0,
    }
    
    ab_tracker._save_json(temp_history_path, [record_invalid_ctrs, record_invalid_type, record_no_predicted_at_all])
    response = client.get("/api/thumbnail/accuracy")
    assert response.status_code == 200
    accuracy = response.json()["accuracy"]
    # どのレコードも有効な all_predicted_ctrs を持たないため、valid_samples = 0 となり、正解率は 0.0 になるべき
    assert accuracy["correct_prediction_rate"] == 0.0
