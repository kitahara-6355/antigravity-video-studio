import os
import sys
import requests
import json

# 親ディレクトリをシステムパスに追加して backend モジュールをインポート可能にする
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_URL = "http://localhost:8000/api/director"

def test_quality_gate():
    print("Testing Quality Gate API...")
    payload = {
        "full_text": "こんにちは。今日は最高の動画編集ツールを紹介します。非常にエモい仕上がりになる予定です。",
        "scenes": [
            {"name": "オープニング", "source_type": "AI"},
            {"name": "メイン解説", "source_type": "USER_ASSET"}
        ],
        "segments": [
            {"text": "こんにちは。"},
            {"text": "今日は最高の動画編集ツールを紹介します。"},
            {"text": "非常にエモい仕上がりになる予定です。"}
        ]
    }

    # pytestなどのテスト環境下であるかを判定
    is_pytest = "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST") is not None

    if is_pytest:
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        res = client.post("/api/director/verify-quality", json=payload)
        print(f"Status (TestClient): {res.status_code}")
        assert res.status_code == 200
        res_json = res.json()
        assert isinstance(res_json, dict)
        print(json.dumps(res_json, indent=2, ensure_ascii=False))
    else:
        try:
            res = requests.post(f"{BASE_URL}/verify-quality", json=payload)
            print(f"Status: {res.status_code}")
            try:
                print(json.dumps(res.json(), indent=2, ensure_ascii=False))
            except (json.JSONDecodeError, ValueError):
                print(f"Failed to decode JSON. Response text: {res.text}")
        except requests.exceptions.ConnectionError as e:
            print(f"Connection Error: {e}")
            print(f"Please ensure the local server is running at {BASE_URL}")
        except requests.exceptions.RequestException as e:
            print(f"Request Error: {e}")

if __name__ == "__main__":
    test_quality_gate()
