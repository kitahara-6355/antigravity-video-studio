import sys
import os
from pathlib import Path

# プロジェクトルートのbackendをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
os.environ["GOOGLE_API_KEY"] = "dummy_for_stub"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.youtube_optimizer import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)

def test_api_endpoints():
    print("=== [テスト 1] POST /api/youtube/assets/build-index ===")
    response = client.post("/api/youtube/assets/build-index")
    print(f"Status Code: {response.status_code}")
    print(f"Response JSON: {response.json()}")
    assert response.status_code == 200, "ビルドインデックスが失敗しました"
    
    print("\n=== [テスト 2] GET /api/youtube/assets/search ===")
    query = "人物写真"
    response = client.get(f"/api/youtube/assets/search?q={query}&top_k=2")
    print(f"Status Code: {response.status_code}")
    
    data = response.json()
    print("Response JSON:")
    for key, val in data.items():
         if key != 'results':
             print(f"  {key}: {val}")
    
    print("検索結果:")
    for idx, r in enumerate(data.get("results", [])):
         print(f"  {idx+1}. [{r.get('id', '未知')}] スコア: {r.get('search_score')} / カテゴリ: {r.get('category')} / ラベル: {r.get('labels')}")
         
    assert response.status_code == 200, "検索リクエストが失敗しました"
    assert data.get("success") is True, "successフラグがTrueではありません"
    assert "results" in data, "resultsキーがありません"
    
    print("\n[OK] API Endpoints Test Passed.")
    
if __name__ == "__main__":
    test_api_endpoints()
