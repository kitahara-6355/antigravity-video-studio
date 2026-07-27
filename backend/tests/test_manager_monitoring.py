import asyncio
import pytest
from datetime import datetime, timezone
from manager_monitoring import owner_status_store

@pytest.fixture(autouse=True)
def reset_owner_status():
    owner_status_store["last_login"] = None
    owner_status_store["session_count"] = 0
    owner_status_store["interaction_count"] = 0
    owner_status_store["last_interaction_tone"] = "neutral"
    owner_status_store["fatigue_score"] = 0

def test_get_owner_status_initial(client):
    response = client.get("/api/manager/status")
    assert response.status_code == 200
    data = response.json()
    assert data["last_login"] is None
    assert data["session_count"] == 0
    assert data["interaction_count"] == 0
    assert data["last_interaction_tone"] == "neutral"
    assert data["fatigue_score"] == 0
    assert data["alert_message"] is None

def test_update_owner_status_valid_tones(client):
    # neutralの更新
    response = client.post("/api/manager/update?tone=neutral")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"
    assert data["current_fatigue"] == 5

    # statusの確認
    status_response = client.get("/api/manager/status")
    status_data = status_response.json()
    assert status_data["interaction_count"] == 1
    assert status_data["last_interaction_tone"] == "neutral"
    assert status_data["fatigue_score"] == 5
    assert status_data["last_login"] is not None

    # tiredの更新
    response = client.post("/api/manager/update?tone=tired")
    assert response.status_code == 200
    assert response.json()["current_fatigue"] == 20  # 5 + 15 = 20

    # positiveの更新
    response = client.post("/api/manager/update?tone=positive")
    assert response.status_code == 200
    assert response.json()["current_fatigue"] == 10  # 20 - 10 = 10

def test_update_owner_status_invalid_tone(client):
    response = client.post("/api/manager/update?tone=invalid_value")
    assert response.status_code == 400
    assert "Invalid tone value" in response.json()["error"]

def test_fatigue_score_boundaries(client):
    # 疲労度 50 (アラートなし)
    owner_status_store["fatigue_score"] = 50
    response = client.get("/api/manager/status")
    assert response.json()["alert_message"] is None

    # 疲労度 51 (集中力低下)
    owner_status_store["fatigue_score"] = 51
    response = client.get("/api/manager/status")
    assert "集中力が低下しています" in response.json()["alert_message"]

    # 疲労度 70 (集中力低下)
    owner_status_store["fatigue_score"] = 70
    response = client.get("/api/manager/status")
    assert "集中力が低下しています" in response.json()["alert_message"]

    # 疲労度 71 (休憩を促す)
    owner_status_store["fatigue_score"] = 71
    response = client.get("/api/manager/status")
    assert "休憩を促してください" in response.json()["alert_message"]

def test_fatigue_score_cap_and_floor(client):
    # 下限ガードテスト
    owner_status_store["fatigue_score"] = 5
    response = client.post("/api/manager/update?tone=positive")
    assert response.json()["current_fatigue"] == 0  # 5 - 10 = -5 -> guard to 0

    # 上限ガードテスト
    owner_status_store["fatigue_score"] = 95
    response = client.post("/api/manager/update?tone=tired")
    assert response.json()["current_fatigue"] == 100  # 95 + 15 = 110 -> guard to 100

@pytest.mark.anyio
async def test_concurrent_updates(async_client):
    # 20並行更新をテスト
    tasks = [async_client.post("/api/manager/update?tone=neutral") for _ in range(20)]
    responses = await asyncio.gather(*tasks)

    for r in responses:
        assert r.status_code == 200

    # API経由で最終ステータスを取得して検証
    status_response = await async_client.get("/api/manager/status")
    assert status_response.status_code == 200
    status_data = status_response.json()

    # interaction_count は 20 に増えているべき
    assert status_data["interaction_count"] == 20
    # 疲労度は 5 * 20 = 100 に制限されているはず
    assert status_data["fatigue_score"] == 100



def test_update_owner_status_without_increment(client):
    # increment_interaction=False で更新
    response = client.post("/api/manager/update", params={"tone": "neutral", "increment_interaction": "false"})
    assert response.status_code == 200
    
    # statusの確認
    status_response = client.get("/api/manager/status")
    status_data = status_response.json()
    assert status_data["interaction_count"] == 0  # インクリメントされないはず
    assert status_data["last_interaction_tone"] == "neutral"
    assert status_data["fatigue_score"] == 5
    assert status_data["last_login"] is not None


def test_get_status_store_missing_key(client):
    # キーを削除して整合性エラーをシミュレート
    original_fatigue = owner_status_store.pop("fatigue_score")
    try:
        response = client.get("/api/manager/status")
        assert response.status_code == 500
        assert "Store integrity error: missing key" in response.json()["error"]
    finally:
        owner_status_store["fatigue_score"] = original_fatigue


def test_get_status_store_invalid_type(client):
    # 無効な型を設定してTypeErrorをシミュレート
    original_fatigue = owner_status_store["fatigue_score"]
    owner_status_store["fatigue_score"] = "invalid_string_type"
    try:
        response = client.get("/api/manager/status")
        assert response.status_code == 500
        assert "Store type error" in response.json()["error"]
    finally:
        owner_status_store["fatigue_score"] = original_fatigue


def test_update_status_store_missing_key(client):
    # キーを削除して更新時の整合性エラーをシミュレート
    original_fatigue = owner_status_store.pop("fatigue_score")
    try:
        response = client.post("/api/manager/update?tone=neutral")
        assert response.status_code == 500
        assert "Store integrity error: missing key" in response.json()["error"]
    finally:
        owner_status_store["fatigue_score"] = original_fatigue


def test_update_status_store_invalid_type(client):
    # 無効な型を設定して更新時のTypeErrorをシミュレート
    original_fatigue = owner_status_store["fatigue_score"]
    owner_status_store["fatigue_score"] = "invalid_string_type"
    try:
        response = client.post("/api/manager/update?tone=neutral")
        assert response.status_code == 500
        assert "Store type error" in response.json()["error"]
    finally:
        owner_status_store["fatigue_score"] = original_fatigue



def test_update_status_store_bool_type(client):
    # bool値を設定して更新時のTypeErrorをシミュレート
    original_fatigue = owner_status_store["fatigue_score"]
    owner_status_store["fatigue_score"] = True
    try:
        response = client.post("/api/manager/update?tone=neutral")
        assert response.status_code == 500
        assert "Store type error" in response.json()["error"]
    finally:
        owner_status_store["fatigue_score"] = original_fatigue

def test_update_status_store_out_of_bounds(client):
    # 範囲外の値を設定して更新時のValueErrorをシミュレート
    original_fatigue = owner_status_store["fatigue_score"]
    
    # 下限未満のテスト
    owner_status_store["fatigue_score"] = -1
    try:
        response = client.post("/api/manager/update?tone=neutral")
        assert response.status_code == 400
        assert "Invalid value error: current_fatigue must be between" in response.json()["error"]
    finally:
        owner_status_store["fatigue_score"] = original_fatigue

    # 上限超のテスト
    owner_status_store["fatigue_score"] = 101
    try:
        response = client.post("/api/manager/update?tone=neutral")
        assert response.status_code == 400
        assert "Invalid value error: current_fatigue must be between" in response.json()["error"]
    finally:
        owner_status_store["fatigue_score"] = original_fatigue
