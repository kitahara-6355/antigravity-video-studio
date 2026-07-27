import pytest
from unittest.mock import patch, MagicMock
import sys
import os
import requests

# パス追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tests import phase3_diverse

# テストで time.sleep が走ると遅くなるので mock する
@pytest.fixture(autouse=True)
def mock_sleep():
    with patch('tests.phase3_diverse.time.sleep', return_value=None) as m:
        yield m

def test_generate_test_videos(tmp_path):
    orig_test_dir = phase3_diverse.TEST_DIR
    phase3_diverse.TEST_DIR = tmp_path
    try:
        # 全て正常終了かつファイルが存在する場合
        with patch('tests.phase3_diverse.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            # ファイルの疑似生成
            for name in ["30sec", "5min", "silent", "mono", "480p"]:
                (tmp_path / f"test_{name}.mp4").touch()
                
            videos = phase3_diverse.generate_test_videos()
            assert len(videos) == 5
            assert "30sec" in videos

        # subprocessが失敗する場合
        with patch('tests.phase3_diverse.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="FFmpeg error")
            # ファイル削除
            for name in ["30sec", "5min", "silent", "mono", "480p"]:
                p = tmp_path / f"test_{name}.mp4"
                if p.exists():
                    p.unlink()
            videos = phase3_diverse.generate_test_videos()
            assert len(videos) == 0
    finally:
        phase3_diverse.TEST_DIR = orig_test_dir


def test_run_pipeline_success(tmp_path):
    # ダミー動画ファイルの作成 (2.1MB)
    dummy_preview = tmp_path / "preview.mp4"
    dummy_final = tmp_path / "final.mp4"
    with open(dummy_preview, "wb") as f:
        f.write(b"0" * (2 * 1024 * 1024 + 100))
    with open(dummy_final, "wb") as f:
        f.write(b"0" * (2 * 1024 * 1024 + 100))

    # 正常系: idle待機 -> 起動成功 -> 完了待機 -> 7項目チェックPASS
    mock_status_responses = [
        # idle待機の get: idle
        MagicMock(status_code=200),
        # 完了待機の get: running, completed
        MagicMock(status_code=200),
        MagicMock(status_code=200),
    ]
    # statusのjson戻り値を設定
    mock_status_responses[0].json.return_value = {"status": "idle"}
    mock_status_responses[1].json.return_value = {"status": "running"}
    mock_status_responses[2].json.return_value = {
        "status": "completed",
        "result": {
            "session_id": "test_sess_12345",
            "quality_score": 90,
            "duration_seconds": 45.2,
            "segments_count": 10,
            "preview_path": str(dummy_preview),
            "final_path": str(dummy_final),
            "stage_results": [
                {"name": "文字起こし", "success": True},
                {"name": "AI校閲", "success": True},
                {"name": "SmartCut", "success": True},
            ],
            "quality_details": {
                "score": 90,
                "category_report": [
                    {"category": "core"},
                    {"category": "template"},
                    {"category": "broadcast"},
                    {"category": "youtube"},
                ]
            },
            "metadata": {
                "titles": ["title1"],
                "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
                "chapters": ["chapter1"]
            }
        }
    }
    
    mock_post_response = MagicMock(status_code=200)
    mock_post_response.json.return_value = {"session_id": "test_sess_12345"}

    with patch('tests.phase3_diverse.requests.get') as mock_get, \
         patch('tests.phase3_diverse.requests.post') as mock_post, \
         patch('tests.phase2_validator.check_ffprobe', return_value=("h264", "aac")):
         
        mock_get.side_effect = mock_status_responses
        mock_post.return_value = mock_post_response

        passed, detail = phase3_diverse.run_pipeline("test_30sec.mp4", "30秒動画", is_special=False)
        assert passed is True
        assert "score=90" in detail


def test_run_pipeline_idle_exception_and_timeout():
    # idle待機で例外が発生し続け、起動（post）でも例外が発生して即座に終了する
    with patch('tests.phase3_diverse.requests.get') as mock_get, \
         patch('tests.phase3_diverse.requests.post') as mock_post:
         
        mock_get.side_effect = requests.RequestException("Connection Refused")
        mock_post.side_effect = requests.RequestException("Start failed")
        
        passed, detail = phase3_diverse.run_pipeline("test_30sec.mp4", "30秒動画")
        assert passed is False
        assert "Start failed" in detail


def test_run_pipeline_start_failed():
    # 起動（post）が例外を投げるケース
    mock_status_response = MagicMock(status_code=200)
    mock_status_response.json.return_value = {"status": "idle"}
    
    with patch('tests.phase3_diverse.requests.get', return_value=mock_status_response), \
         patch('tests.phase3_diverse.requests.post', side_effect=requests.RequestException("Post Timeout")):
        passed, detail = phase3_diverse.run_pipeline("test_30sec.mp4", "30秒動画")
        assert passed is False
        assert "Post Timeout" in detail


def test_run_pipeline_polling_timeout():
    # 完了待機ループでのタイムアウトケース
    mock_status_idle = MagicMock(status_code=200)
    mock_status_idle.json.return_value = {"status": "idle"}
    
    mock_status_running = MagicMock(status_code=200)
    mock_status_running.json.return_value = {"status": "running"}

    mock_post_response = MagicMock(status_code=200)
    mock_post_response.json.return_value = {"session_id": "test_sess_12345"}

    # time.time を mock してタイムアウトをシミュレート
    with patch('tests.phase3_diverse.requests.get') as mock_get, \
         patch('tests.phase3_diverse.requests.post', return_value=mock_post_response), \
         patch('tests.phase3_diverse.time.time') as mock_time:
         
        # idle 1回、その後ポーリングで running が続く
        mock_get.side_effect = [mock_status_idle] + [mock_status_running] * 10
        # time.time() の呼び出しで時間経過を表現
        mock_time.side_effect = [100.0, 100.0, 105.0, 500.0]
        
        passed, detail = phase3_diverse.run_pipeline("test_30sec.mp4", "30秒動画")
        assert passed is False
        assert "タイムアウト" in detail


def test_run_pipeline_status_error_special():
    # is_special=True で status="error" になった場合（正常動作扱い）
    mock_status_idle = MagicMock(status_code=200)
    mock_status_idle.json.return_value = {"status": "idle"}
    
    mock_status_error = MagicMock(status_code=200)
    mock_status_error.json.return_value = {"status": "error", "error": "Audio Presence Check failed"}

    mock_post_response = MagicMock(status_code=200)
    mock_post_response.json.return_value = {"session_id": "test_sess_12345"}

    with patch('tests.phase3_diverse.requests.get') as mock_get, \
         patch('tests.phase3_diverse.requests.post', return_value=mock_post_response):
         
        mock_get.side_effect = [mock_status_idle, mock_status_error]
        
        passed, detail = phase3_diverse.run_pipeline("test_silent.mp4", "無音動画", is_special=True)
        assert passed is True
        assert "エラー検出(正常)" in detail


def test_run_pipeline_status_error_normal():
    # is_special=False で status="error" になった場合（失敗扱い）
    mock_status_idle = MagicMock(status_code=200)
    mock_status_idle.json.return_value = {"status": "idle"}
    
    mock_status_error = MagicMock(status_code=200)
    mock_status_error.json.return_value = {"status": "error", "error": "Fatal codec crash"}

    mock_post_response = MagicMock(status_code=200)
    mock_post_response.json.return_value = {"session_id": "test_sess_12345"}

    with patch('tests.phase3_diverse.requests.get') as mock_get, \
         patch('tests.phase3_diverse.requests.post', return_value=mock_post_response):
         
        mock_get.side_effect = [mock_status_idle, mock_status_error]
        
        passed, detail = phase3_diverse.run_pipeline("test_normal.mp4", "普通動画", is_special=False)
        assert passed is False
        assert "Fatal codec crash" in detail


def test_run_pipeline_polling_exception_recovery(tmp_path):
    # ダミー動画ファイルの作成 (2.1MB)
    dummy_preview = tmp_path / "preview.mp4"
    dummy_final = tmp_path / "final.mp4"
    with open(dummy_preview, "wb") as f:
        f.write(b"0" * (2 * 1024 * 1024 + 100))
    with open(dummy_final, "wb") as f:
        f.write(b"0" * (2 * 1024 * 1024 + 100))

    # ポーリング中に一度例外が発生しても、次のループでcompletedが取れるケース
    mock_status_idle = MagicMock(status_code=200)
    mock_status_idle.json.return_value = {"status": "idle"}
    
    mock_status_completed = MagicMock(status_code=200)
    mock_status_completed.json.return_value = {
        "status": "completed",
        "result": {
            "session_id": "test_sess_12345",
            "quality_score": 95,
            "duration_seconds": 12.3,
            "segments_count": 10,
            "preview_path": str(dummy_preview),
            "final_path": str(dummy_final),
            "stage_results": [
                {"name": "文字起こし", "success": True},
                {"name": "AI校閲", "success": True},
                {"name": "SmartCut", "success": True},
            ],
            "quality_details": {
                "score": 95,
                "category_report": [
                    {"category": "core"},
                    {"category": "template"},
                    {"category": "broadcast"},
                    {"category": "youtube"},
                ]
            },
            "metadata": {
                "titles": ["title1"],
                "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
                "chapters": ["chapter1"]
            }
        }
    }

    mock_post_response = MagicMock(status_code=200)
    mock_post_response.json.return_value = {"session_id": "test_sess_12345"}

    with patch('tests.phase3_diverse.requests.get') as mock_get, \
         patch('tests.phase3_diverse.requests.post', return_value=mock_post_response), \
         patch('tests.phase2_validator.check_ffprobe', return_value=("h264", "aac")):
         
        # 1回目 idle
        # 2回目 ポーリングで例外スロー
        # 3回目 ポーリングで completed
        mock_get.side_effect = [mock_status_idle, requests.RequestException("Network temporary drop"), mock_status_completed]

        passed, detail = phase3_diverse.run_pipeline("test_30sec.mp4", "30秒動画")
        assert passed is True
        assert "score=95" in detail


def test_run_pipeline_special_completed_fallback():
    # is_special=True で status="completed" になり、7項目チェックの一部が失敗しても
    # 完走しているため合格とするルート
    mock_status_idle = MagicMock(status_code=200)
    mock_status_idle.json.return_value = {"status": "idle"}
    
    mock_status_completed = MagicMock(status_code=200)
    mock_status_completed.json.return_value = {
        "status": "completed",
        "result": {
            "session_id": "test_sess_12345",
            "quality_score": 50,  # 低スコア
            "duration_seconds": 10.0,
            "stage_results": [],
            "quality_details": {},
            "metadata": {}
        }
    }

    mock_post_response = MagicMock(status_code=200)
    mock_post_response.json.return_value = {"session_id": "test_sess_12345"}

    with patch('tests.phase3_diverse.requests.get') as mock_get, \
         patch('tests.phase3_diverse.requests.post', return_value=mock_post_response), \
         patch('tests.phase2_validator.check_ffprobe', return_value=("unknown", "unknown")), \
         patch('pathlib.Path.exists', return_value=False):
         
        mock_get.side_effect = [mock_status_idle, mock_status_completed]

        passed, detail = phase3_diverse.run_pipeline("test_silent.mp4", "無音動画", is_special=True)
        assert passed is True
        assert "特殊入力:完走" in detail


def test_main_all_success():
    # videosが全5種存在し、全て合格するケース
    videos_mock = {
        "30sec": "path/test_30sec.mp4",
        "5min": "path/test_5min.mp4",
        "silent": "path/test_silent.mp4",
        "mono": "path/test_mono.mp4",
        "480p": "path/test_480p.mp4",
    }
    with patch('tests.phase3_diverse.generate_test_videos', return_value=videos_mock), \
         patch('tests.phase3_diverse.run_pipeline', return_value=(True, "score=90")):
        
        success = phase3_diverse.main()
        assert success is True


def test_main_some_failed_or_missing():
    # 一部動画が足りない ＆ run_pipelineが失敗するケース
    videos_mock = {
        "30sec": "path/test_30sec.mp4",
        # 5min が欠けている
        "silent": "path/test_silent.mp4",
        "mono": "path/test_mono.mp4",
        "480p": "path/test_480p.mp4",
    }
    with patch('tests.phase3_diverse.generate_test_videos', return_value=videos_mock), \
         patch('tests.phase3_diverse.run_pipeline') as mock_run_pipe:
         
        # 存在する4回について (True, False, True, True) のような結果を返す
        mock_run_pipe.side_effect = [
            (True, "ok"),
            (False, "error detail"),
            (True, "ok"),
            (True, "ok"),
        ]
        
        success = phase3_diverse.main()
        assert success is False


def test_run_pipeline_json_decode_error_recovery(tmp_path):
    # JSONデコードエラー (ValueError) がポーリング中に発生してもリカバリーして成功するケース
    dummy_preview = tmp_path / "preview.mp4"
    dummy_final = tmp_path / "final.mp4"
    with open(dummy_preview, "wb") as f:
        f.write(b"0" * (2 * 1024 * 1024 + 100))
    with open(dummy_final, "wb") as f:
        f.write(b"0" * (2 * 1024 * 1024 + 100))

    mock_status_idle = MagicMock(status_code=200)
    mock_status_idle.json.return_value = {"status": "idle"}
    
    # JSONデコードエラーを起こすモックレスポンス
    mock_invalid_json = MagicMock(status_code=200)
    mock_invalid_json.json.side_effect = ValueError("No JSON object could be decoded")

    mock_status_completed = MagicMock(status_code=200)
    mock_status_completed.json.return_value = {
        "status": "completed",
        "result": {
            "session_id": "test_sess_12345",
            "quality_score": 88,
            "duration_seconds": 15.0,
            "segments_count": 10,
            "preview_path": str(dummy_preview),
            "final_path": str(dummy_final),
            "stage_results": [
                {"name": "文字起こし", "success": True},
                {"name": "AI校閲", "success": True},
                {"name": "SmartCut", "success": True},
            ],
            "quality_details": {
                "score": 88,
                "category_report": [
                    {"category": "core"},
                    {"category": "template"},
                    {"category": "broadcast"},
                    {"category": "youtube"},
                ]
            },
            "metadata": {
                "titles": ["title1"],
                "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
                "chapters": ["chapter1"]
            }
        }
    }

    mock_post_response = MagicMock(status_code=200)
    mock_post_response.json.return_value = {"session_id": "test_sess_12345"}

    with patch('tests.phase3_diverse.requests.get') as mock_get, \
         patch('tests.phase3_diverse.requests.post', return_value=mock_post_response), \
         patch('tests.phase2_validator.check_ffprobe', return_value=("h264", "aac")):
         
        # 1回目: idle
        # 2回目: json() で ValueError
        # 3回目: completed
        mock_get.side_effect = [mock_status_idle, mock_invalid_json, mock_status_completed]

        passed, detail = phase3_diverse.run_pipeline("test_30sec.mp4", "30秒動画")
        assert passed is True
        assert "score=88" in detail



def test_check_pipeline_abnormal_status_none_error_msg():
    # error_msg が None かつ allow_expected_errors が False の場合は正常に False, None を返す
    res = phase3_diverse._check_pipeline_abnormal_status("error", None, allow_expected_errors=False)
    assert res == (False, None)

    # error_msg が None かつ allow_expected_errors が True の場合は TypeError が発生する
    with pytest.raises(TypeError):
        phase3_diverse._check_pipeline_abnormal_status("error", None, allow_expected_errors=True)

    # status が "timeout" の場合は (False, "タイムアウト") を返す
    res_timeout = phase3_diverse._check_pipeline_abnormal_status("timeout", "timeout error", allow_expected_errors=True)
    assert res_timeout == (False, "タイムアウト")

    # status がそれ以外の未知のステータスの場合は None を返す
    res_other = phase3_diverse._check_pipeline_abnormal_status("unknown", "unknown error", allow_expected_errors=True)
    assert res_other is None


def test_verify_pipeline_quality_metrics_malformed_data():
    from unittest.mock import patch
    # pipeline_data の "result" が None の場合は AttributeError が発生する
    with pytest.raises(AttributeError):
        phase3_diverse._verify_pipeline_quality_metrics({"result": None})

    # pipeline_data に "result" キーがない場合は、run_checks の戻り値が空だったりエラーになったりする可能性を検証
    with patch('tests.phase3_diverse.run_checks', return_value=[]):
        passed, score, duration = phase3_diverse._verify_pipeline_quality_metrics({})
        assert passed is True
        assert score == 0
        assert duration == 0


def test_execute_test_suite_empty_videos():
    # videos が空の辞書の場合、結果は5つのスキップエントリになる
    results = phase3_diverse._execute_test_suite({})
    assert len(results) == 5
    for name, label, passed, detail in results:
        assert passed is False
        assert detail == "動画生成失敗"


def test_print_final_summary_empty():
    # results が空リストの場合、合格 0/0 で結果は True (完了) になる
    success = phase3_diverse._print_final_summary([])
    assert success is True


def test_generate_test_video_file_timeout():
    import subprocess
    from unittest.mock import patch
    # subprocess.run が TimeoutExpired を投げるエッジケース
    with patch('tests.phase3_diverse.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=120)):
        with pytest.raises(subprocess.TimeoutExpired):
            phase3_diverse._generate_test_video_file("timeout_test", "-i dummy.mp4", "Timeout Test")


def test_evaluate_pipeline_result_invalid_types():
    with pytest.raises(AttributeError):
        phase3_diverse._evaluate_pipeline_result(None, allow_expected_errors=False)
    with pytest.raises(AttributeError):
        phase3_diverse._evaluate_pipeline_result([], allow_expected_errors=False)
