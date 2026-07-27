import requests_mock
import pytest
from verify_collaboration_api import (
    main,
    post_journal_entry,
    get_journal_entries,
    post_feedback
)

def test_verify_collaboration_api_main(capsys):
    with requests_mock.Mocker() as m:
        # Mocking endpoints for journal
        m.post("http://localhost:8000/api/collaboration/journal", json={"status": "success", "entry": {"author": "admin", "content": "Verification Test Entry"}}, status_code=200)
        m.get("http://localhost:8000/api/collaboration/journal", json=[{"author": "admin", "content": "Verification Test Entry"}], status_code=200)
        
        # Mocking endpoints for feedback
        m.post("http://localhost:8000/api/collaboration/feedback", json={"status": "success"}, status_code=200)
        
        # Execute the main function directly
        main()
        
    captured = capsys.readouterr()
    assert "Testing Journal API..." in captured.out
    assert "Testing Feedback API..." in captured.out

def test_api_functions_individually():
    with requests_mock.Mocker() as m:
        m.post("http://localhost:8000/api/collaboration/journal", json={"status": "success"}, status_code=200)
        res = post_journal_entry("admin", "content")
        assert res.status_code == 200
        assert res.json() == {"status": "success"}

        m.get("http://localhost:8000/api/collaboration/journal", json=[], status_code=200)
        res = get_journal_entries()
        assert res.status_code == 200
        assert res.json() == []

        m.post("http://localhost:8000/api/collaboration/feedback", json={"status": "success"}, status_code=200)
        res = post_feedback("test-id", "approve", "owner", "comment")
        assert res.status_code == 200
        assert res.json() == {"status": "success"}

def test_verify_collaboration_api_connection_error(capsys):
    import requests.exceptions
    with requests_mock.Mocker() as m:
        # シミュレートされた接続エラー
        m.post("http://localhost:8000/api/collaboration/journal", exc=requests.exceptions.ConnectionError("Connection refused"))
        m.post("http://localhost:8000/api/collaboration/feedback", exc=requests.exceptions.ConnectionError("Connection refused"))
        
        main()
        
    captured = capsys.readouterr()
    assert "Testing Journal API..." in captured.out
    assert "Journal API Connection Error: Connection refused" in captured.out
    assert "Testing Feedback API..." in captured.out
    assert "Feedback API Connection Error: Connection refused" in captured.out

def test_verify_collaboration_api_non_json_response(capsys):
    with requests_mock.Mocker() as m:
        # 非JSONレスポンスをモック
        m.post("http://localhost:8000/api/collaboration/journal", text="Internal Server Error HTML", status_code=500)
        m.get("http://localhost:8000/api/collaboration/journal", text="Gateway Timeout", status_code=504)
        m.post("http://localhost:8000/api/collaboration/feedback", text="Not Found", status_code=404)
        
        main()
        
    captured = capsys.readouterr()
    assert "Testing Journal API..." in captured.out
    assert "POST Journal: 500" in captured.out
    assert "Non-JSON Response: Internal Server Error HTML" in captured.out
    assert "GET Journal: 504" in captured.out
    assert "Non-JSON Response: Gateway Timeout" in captured.out
    assert "Testing Feedback API..." in captured.out
    assert "POST Feedback: 404" in captured.out
    assert "Non-JSON Response: Not Found" in captured.out

def test_verify_collaboration_api_partial_connection_error(capsys):
    import requests.exceptions
    with requests_mock.Mocker() as m:
        # POST Journal は成功、GET Journal は接続エラー
        m.post("http://localhost:8000/api/collaboration/journal", json={"status": "success"}, status_code=200)
        m.get("http://localhost:8000/api/collaboration/journal", exc=requests.exceptions.ConnectionError("Connection timed out"))
        
        # POST Feedback は成功
        m.post("http://localhost:8000/api/collaboration/feedback", json={"status": "success"}, status_code=200)
        
        main()
        
    captured = capsys.readouterr()
    assert "Testing Journal API..." in captured.out
    assert "POST Journal: 200" in captured.out
    assert "Journal API Connection Error: Connection timed out" in captured.out
    assert "Testing Feedback API..." in captured.out
    assert "POST Feedback: 200" in captured.out

def test_verify_collaboration_api_timeout_error(capsys):
    import requests.exceptions
    with requests_mock.Mocker() as m:
        # シミュレートされたタイムアウトエラー
        m.post("http://localhost:8000/api/collaboration/journal", exc=requests.exceptions.ConnectTimeout("Connection timed out"))
        m.post("http://localhost:8000/api/collaboration/feedback", exc=requests.exceptions.ConnectTimeout("Connection timed out"))
        
        main()
        
    captured = capsys.readouterr()
    assert "Testing Journal API..." in captured.out
    assert "Journal API Timeout Error: Connection timed out" in captured.out
    assert "Testing Feedback API..." in captured.out
    assert "Feedback API Timeout Error: Connection timed out" in captured.out


def test_verify_collaboration_api_http_error(capsys):
    import requests.exceptions
    with requests_mock.Mocker() as m:
        # HTTPError を発生させるために、モックしたレスポンスの raise_for_status() が HTTPError を投げるように status_code を 400 と 500 に設定
        m.post("http://localhost:8000/api/collaboration/journal", text="Bad Request", status_code=400)
        m.get("http://localhost:8000/api/collaboration/journal", text="Internal Server Error", status_code=500)
        m.post("http://localhost:8000/api/collaboration/feedback", text="Internal Server Error", status_code=500)
        
        main()
        
    captured = capsys.readouterr()
    assert "Testing Journal API..." in captured.out
    assert "Journal API HTTP Error: 400 Client Error" in captured.out
    assert "Journal API HTTP Error: 500 Server Error" in captured.out
    assert "Testing Feedback API..." in captured.out
    assert "Feedback API HTTP Error: 500 Server Error" in captured.out
