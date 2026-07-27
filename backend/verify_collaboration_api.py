import json
import requests

BASE_URL = "http://localhost:8000/api/collaboration"

def post_journal_entry(author: str, content: str) -> requests.Response:
    """Journal APIに新しいエントリを投稿する"""
    return requests.post(f"{BASE_URL}/journal", json={"author": author, "content": content}, timeout=10)

def get_journal_entries() -> requests.Response:
    """Journal APIから履歴を取得する"""
    return requests.get(f"{BASE_URL}/journal", timeout=10)

def post_feedback(suggestion_id: str, action: str, role: str, comment: str) -> requests.Response:
    """Feedback APIにフィードバックを送信する"""
    return requests.post(f"{BASE_URL}/feedback", json={
        "suggestion_id": suggestion_id,
        "action": action,
        "role": role,
        "comment": comment
    }, timeout=10)

def _print_response(prefix: str, response: requests.Response) -> None:
    """レスポンスのステータスコードとJSON内容を出力するヘルパー関数"""
    print(f"{prefix}: {response.status_code}")
    try:
        print(response.json())
    except (ValueError, json.JSONDecodeError):
        print(f"Non-JSON Response: {response.text}")
    response.raise_for_status()

def verify_journal_api() -> None:
    """Journal APIの動作検証とログ出力を行う"""
    print("Testing Journal API...")
    
    connection_failed = False
    
    # エントリ追加の検証
    try:
        post_response = post_journal_entry("admin", "Verification Test Entry")
        _print_response("POST Journal", post_response)
    except requests.exceptions.Timeout as e:
        print(f"Journal API Timeout Error: {e}")
        connection_failed = True
    except requests.exceptions.HTTPError as e:
        print(f"Journal API HTTP Error: {e}")
    except requests.exceptions.RequestException as e:
        print(f"Journal API Connection Error: {e}")
        connection_failed = True
        
    if not connection_failed:
        # 履歴取得の検証
        try:
            get_response = get_journal_entries()
            _print_response("GET Journal", get_response)
        except requests.exceptions.Timeout as e:
            print(f"Journal API Timeout Error: {e}")
        except requests.exceptions.HTTPError as e:
            print(f"Journal API HTTP Error: {e}")
        except requests.exceptions.RequestException as e:
            print(f"Journal API Connection Error: {e}")

def verify_feedback_api() -> None:
    """Feedback APIの動作検証とログ出力を行う"""
    print("\nTesting Feedback API...")
    try:
        feedback_response = post_feedback(
            suggestion_id="test-id",
            action="approve",
            role="owner",
            comment="Looks great!"
        )
        _print_response("POST Feedback", feedback_response)
    except requests.exceptions.Timeout as e:
        print(f"Feedback API Timeout Error: {e}")
    except requests.exceptions.HTTPError as e:
        print(f"Feedback API HTTP Error: {e}")
    except requests.exceptions.RequestException as e:
        print(f"Feedback API Connection Error: {e}")

def main() -> None:
    """コラボレーションAPI全体の検証を実行する"""
    verify_journal_api()
    verify_feedback_api()

if __name__ == "__main__":  # pragma: no cover
    main()
