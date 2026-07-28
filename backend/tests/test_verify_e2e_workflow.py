import pytest
import sys
import os
from unittest.mock import patch, MagicMock, mock_open
import runpy

from path_resolver import raw_videos_dir
import verify_e2e_workflow

# 1. step_1_upload のテスト
@patch('verify_e2e_workflow.os.path.exists')
def test_step_1_upload_file_not_found(mock_exists):
    mock_exists.return_value = False
    with pytest.raises(SystemExit) as exc_info:
        verify_e2e_workflow.step_1_upload()
    assert exc_info.value.code == 1

@patch('verify_e2e_workflow.os.path.exists')
@patch('verify_e2e_workflow.requests.post')
def test_step_1_upload_success(mock_post, mock_exists):
    mock_exists.return_value = True
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}
    mock_post.return_value = mock_response

    # open をモック
    with patch('builtins.open', mock_open(read_data=b"dummy video data")):
        verify_e2e_workflow.step_1_upload()
    
    mock_post.assert_called_once()
    # timeout引数の検証 (追加テスト)
    _, kwargs = mock_post.call_args
    assert kwargs.get("timeout") == 30

@patch('verify_e2e_workflow.os.path.exists')
@patch('verify_e2e_workflow.requests.post')
def test_step_1_upload_failed_status(mock_post, mock_exists):
    mock_exists.return_value = True
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_post.return_value = mock_response

    with patch('builtins.open', mock_open(read_data=b"dummy video data")):
        with pytest.raises(SystemExit) as exc_info:
            verify_e2e_workflow.step_1_upload()
    assert exc_info.value.code == 1

@patch('verify_e2e_workflow.os.path.exists')
@patch('verify_e2e_workflow.requests.post')
def test_step_1_upload_exception(mock_post, mock_exists):
    mock_exists.return_value = True
    mock_post.side_effect = Exception("Connection refused")

    with patch('builtins.open', mock_open(read_data=b"dummy video data")):
        with pytest.raises(SystemExit) as exc_info:
            verify_e2e_workflow.step_1_upload()
    assert exc_info.value.code == 1


# 2. step_2_transcribe のテスト
@patch('verify_e2e_workflow.requests.post')
def test_step_2_transcribe_success(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "triggered"}
    mock_post.return_value = mock_response

    verify_e2e_workflow.step_2_transcribe()
    mock_post.assert_called_once()
    # timeout引数の検証 (追加テスト)
    _, kwargs = mock_post.call_args
    assert kwargs.get("timeout") == 30

@patch('verify_e2e_workflow.requests.post')
def test_step_2_transcribe_failed_status(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"
    mock_post.return_value = mock_response

    with pytest.raises(SystemExit) as exc_info:
        verify_e2e_workflow.step_2_transcribe()
    assert exc_info.value.code == 1

@patch('verify_e2e_workflow.requests.post')
def test_step_2_transcribe_exception(mock_post):
    mock_post.side_effect = Exception("Timeout")

    with pytest.raises(SystemExit) as exc_info:
        verify_e2e_workflow.step_2_transcribe()
    assert exc_info.value.code == 1


# 3. step_3_poll のテスト
@patch('verify_e2e_workflow.requests.get')
@patch('verify_e2e_workflow.time.sleep')
def test_step_3_poll_completed_immediately(mock_sleep, mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "completed",
        "message": "Done",
        "progress": 100
    }
    mock_get.return_value = mock_response

    verify_e2e_workflow.step_3_poll()
    mock_get.assert_called_once()
    # timeout引数の検証 (追加テスト)
    _, kwargs = mock_get.call_args
    assert kwargs.get("timeout") == 10
    mock_sleep.assert_not_called()

@patch('verify_e2e_workflow.requests.get')
@patch('verify_e2e_workflow.time.sleep')
def test_step_3_poll_failed(mock_sleep, mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "failed",
        "message": "Error occurred",
        "progress": 50
    }
    mock_get.return_value = mock_response

    with pytest.raises(SystemExit) as exc_info:
        verify_e2e_workflow.step_3_poll()
    assert exc_info.value.code == 1

@patch('verify_e2e_workflow.requests.get')
@patch('verify_e2e_workflow.time.sleep')
def test_step_3_poll_loop_and_completed(mock_sleep, mock_get):
    # 1回目: status="running", 2回目: status="completed"
    res1 = MagicMock()
    res1.status_code = 200
    res1.json.return_value = {"status": "running", "message": "In progress", "progress": 20}

    res2 = MagicMock()
    res2.status_code = 200
    res2.json.return_value = {"status": "completed", "message": "Done", "progress": 100}

    mock_get.side_effect = [res1, res2]

    verify_e2e_workflow.step_3_poll()
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(5)

@patch('verify_e2e_workflow.requests.get')
@patch('verify_e2e_workflow.time.sleep')
def test_step_3_poll_non_200_then_completed(mock_sleep, mock_get):
    # 1回目: status_code=500, 2回目: status_code=200 & completed
    res1 = MagicMock()
    res1.status_code = 500

    res2 = MagicMock()
    res2.status_code = 200
    res2.json.return_value = {"status": "completed", "message": "Done", "progress": 100}

    mock_get.side_effect = [res1, res2]

    verify_e2e_workflow.step_3_poll()
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(5)

@patch('verify_e2e_workflow.requests.get')
@patch('verify_e2e_workflow.time.sleep')
def test_step_3_poll_exception_then_completed(mock_sleep, mock_get):
    # 1回目: Exception, 2回目: status_code=200 & completed
    res2 = MagicMock()
    res2.status_code = 200
    res2.json.return_value = {"status": "completed", "message": "Done", "progress": 100}

    mock_get.side_effect = [Exception("Network failure"), res2]

    verify_e2e_workflow.step_3_poll()
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(5)


# 4. __main__ 実行パスのテスト
@patch('requests.post')
@patch('requests.get')
@patch('os.path.exists')
@patch('time.sleep')
def test_main_execution_flow(mock_sleep, mock_exists, mock_get, mock_post):
    mock_exists.return_value = True

    # step_1_upload 用の response
    res1 = MagicMock()
    res1.status_code = 200
    res1.json.return_value = {"status": "uploaded"}

    # step_2_transcribe 用の response
    res2 = MagicMock()
    res2.status_code = 200
    res2.json.return_value = {"status": "triggered"}

    mock_post.side_effect = [res1, res2]

    # step_3_poll 用の response
    res3 = MagicMock()
    res3.status_code = 200
    res3.json.return_value = {"status": "completed", "message": "Done", "progress": 100}
    mock_get.return_value = res3

    # sys.modules から 'verify_e2e_workflow' を削除して、run_module が新しく実行されるようにする
    if 'verify_e2e_workflow' in sys.modules:
        del sys.modules['verify_e2e_workflow']

    with patch('builtins.open', mock_open(read_data=b"dummy video data")):
        with patch.object(sys, 'argv', ['verify_e2e_workflow.py']):
            runpy.run_module('verify_e2e_workflow', run_name='__main__')

    assert mock_post.call_count == 2
    mock_get.assert_called_once()


# 5. 追加の堅牢性テスト (タイムアウト、JSONパースエラー、環境変数)
@patch('verify_e2e_workflow.requests.get')
@patch('verify_e2e_workflow.time.sleep')
def test_step_3_poll_timeout(mock_sleep, mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "running",
        "message": "Still running",
        "progress": 50
    }
    mock_get.return_value = mock_response

    with pytest.raises(SystemExit) as exc_info:
        verify_e2e_workflow.step_3_poll()
    assert exc_info.value.code == 1
    # get() 自体は MAX_POLL_ATTEMPTS 回だけ呼ばれて終了する
    assert mock_get.call_count == verify_e2e_workflow.MAX_POLL_ATTEMPTS

@patch('verify_e2e_workflow.os.path.exists')
@patch('verify_e2e_workflow.requests.post')
def test_step_1_upload_json_parse_error(mock_post, mock_exists):
    mock_exists.return_value = True
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("No JSON object could be decoded")
    mock_response.text = "Plain text response"
    mock_post.return_value = mock_response

    with patch('builtins.open', mock_open(read_data=b"dummy video data")):
        verify_e2e_workflow.step_1_upload()
    mock_post.assert_called_once()

@patch('verify_e2e_workflow.requests.post')
def test_step_2_transcribe_json_parse_error(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("No JSON object could be decoded")
    mock_response.text = "Plain text response"
    mock_post.return_value = mock_response

    verify_e2e_workflow.step_2_transcribe()
    mock_post.assert_called_once()

@patch('verify_e2e_workflow.requests.get')
@patch('verify_e2e_workflow.time.sleep')
def test_step_3_poll_json_parse_error_then_completed(mock_sleep, mock_get):
    res1 = MagicMock()
    res1.status_code = 200
    res1.json.side_effect = ValueError("No JSON")
    res1.text = "Raw string"

    res2 = MagicMock()
    res2.status_code = 200
    res2.json.return_value = {"status": "completed", "message": "Done", "progress": 100}

    mock_get.side_effect = [res1, res2]

    verify_e2e_workflow.step_3_poll()
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(5)

def test_environment_variables_override():
    orig_base_url = os.environ.get("BASE_URL")
    orig_video_path = os.environ.get("VIDEO_PATH")
    try:
        os.environ["BASE_URL"] = "http://test-server:9999"
        os.environ["VIDEO_PATH"] = "dummy_path.mp4"
        assert verify_e2e_workflow.get_base_url() == "http://test-server:9999"
        assert verify_e2e_workflow.get_video_path() == "dummy_path.mp4"
    finally:
        if orig_base_url is not None:
            os.environ["BASE_URL"] = orig_base_url
        elif "BASE_URL" in os.environ:
            del os.environ["BASE_URL"]
        if orig_video_path is not None:
            os.environ["VIDEO_PATH"] = orig_video_path
        elif "VIDEO_PATH" in os.environ:
            del os.environ["VIDEO_PATH"]
            
    assert verify_e2e_workflow.get_base_url() == (orig_base_url if orig_base_url is not None else "http://localhost:8000")
    # 既定値は raw_videos_dir() から導出される。
    # 以前は解決結果を絶対パスで書き写していたため、リポジトリを作り直した時点で
    # 期待値のほうが実在しない場所を指していた。
    expected_default = str(
        raw_videos_dir() / "AI Studio アップロード用動画" / "シーン01_前編.mp4"
    )
    assert verify_e2e_workflow.get_video_path() == (
        orig_video_path if orig_video_path is not None else expected_default
    )
