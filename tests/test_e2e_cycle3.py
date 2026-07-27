import sys
from pathlib import Path

# 2026-07-26: backend/tests/ を package 化したことで、トップレベル名 'tests' が
# backend/tests に解決されるようになった。このファイルが読むのは同ディレクトリの
# _e2e_cycle3.py なので、'tests.' 接頭辞を外して兄弟モジュールとして import する。
# package 化は tests/ と backend/tests/ のモジュール名衝突（94件）を
# ファイルを1つも削除せずに解消するために必要だった。
BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import pytest
import urllib.request
import urllib.error
import json
import time
from unittest.mock import MagicMock, patch

# テスト対象モジュールのインポート
import _e2e_cycle3 as e2e

# -----------------------------------------------------------------------------
# 時間シミュレーター
# -----------------------------------------------------------------------------
class TimeSimulator:
    def __init__(self, start_time=100.0):
        self.current = start_time
    def get_time(self):
        ret = self.current
        self.current += 0.01
        return ret
    def sleep(self, seconds):
        self.current += seconds

# -----------------------------------------------------------------------------
# wait_for_server のテスト
# -----------------------------------------------------------------------------

def test_wait_for_server_success():
    """サーバーが即座に起動している場合の正常系"""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = MagicMock()
        
        result = e2e.wait_for_server(timeout=10)
        
        assert result is True
        mock_urlopen.assert_called_once_with(f"{e2e.API}/api/pipeline/status", timeout=3)

def test_wait_for_server_retry_success():
    """数回失敗した後にサーバー接続が成功する場合"""
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [urllib.error.URLError("Conn err"), urllib.error.URLError("Conn err"), MagicMock()]
        
        result = e2e.wait_for_server(timeout=10)
        
        assert result is True
        assert mock_urlopen.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(2)

def test_wait_for_server_timeout():
    """タイムアウトまでサーバーが起動しない場合"""
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = urllib.error.URLError("Always fail")
        
        result = e2e.wait_for_server(timeout=5)
        
        assert result is False
        assert mock_sleep.call_count == 3

# -----------------------------------------------------------------------------
# start_pipeline のテスト
# -----------------------------------------------------------------------------

def test_start_pipeline_success():
    """パイプラインが正常に起動し、セッション情報を返す場合"""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"session_id": "session_123456"}).encode("utf-8")
    
    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = e2e.start_pipeline()
        
        assert result == {"session_id": "session_123456"}
        mock_urlopen.assert_called_once()
        args, kwargs = mock_urlopen.call_args
        req = args[0]
        assert isinstance(req, urllib.request.Request)
        assert req.full_url == f"{e2e.API}/api/pipeline/start"
        assert req.headers["Content-type"] == "application/json"

# -----------------------------------------------------------------------------
# monitor_pipeline のテスト
# -----------------------------------------------------------------------------

def test_monitor_pipeline_completed():
    """パイプライン監視中に running ステートを経て completed になる場合"""
    mock_response_running = MagicMock()
    mock_response_running.read.return_value = json.dumps({
        "status": "running",
        "stages": [{"name": "Transcribe", "status": "running", "detail": "Processing video..."}]
    }).encode("utf-8")
    
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": [
            {"name": "Transcribe", "status": "completed", "icon": "📝", "detail": "スコア: 95点"},
            {"name": "Render", "status": "completed", "icon": "🎬", "detail": "Completed successfully"}
        ]
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [mock_response_running, mock_response_completed]
        
        result = e2e.monitor_pipeline(timeout=100)
        
        assert result is not None
        assert result["status"] == "completed"
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(10)

def test_monitor_pipeline_error():
    """パイプラインがエラーで終了する場合"""
    mock_response_error = MagicMock()
    mock_response_error.read.return_value = json.dumps({
        "status": "error",
        "error": "GPU Out of Memory",
        "stages": [{"name": "Render", "status": "failed"}]
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_response_error) as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        result = e2e.monitor_pipeline(timeout=100)
        
        assert result is not None
        assert result["status"] == "error"
        assert result["error"] == "GPU Out of Memory"
        assert mock_sleep.call_count == 1

def test_monitor_pipeline_exception_handling():
    """監視中に一時的な例外が発生するが、最終的に completed になる場合"""
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [
            urllib.error.URLError("Connection refused"),
            urllib.error.URLError("urlopen timed out"),
            mock_response_completed
        ]
        
        result = e2e.monitor_pipeline(timeout=100)
        
        assert result is not None
        assert result["status"] == "completed"
        assert mock_sleep.call_count == 3

def test_monitor_pipeline_timeout():
    """監視タイムアウトに達した場合"""
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = urllib.error.URLError("Timed out in urlopen")
        
        result = e2e.monitor_pipeline(timeout=30)
        
        assert result is None
        assert mock_sleep.call_count == 3

# -----------------------------------------------------------------------------
# main のテスト
# -----------------------------------------------------------------------------

def test_main_success_all_pass():
    """すべての品質ゲート・時間制限をクリアする場合の正常系"""
    stages_data = [
        {"name": "Stage A", "status": "completed", "icon": "✅", "detail": "スコア: 95点"},
        {"name": "Stage B", "status": "completed", "icon": "✅", "detail": "No score details"}
    ]
    final_data = {"status": "completed", "stages": stages_data}
    
    sim = TimeSimulator()
    with patch("_e2e_cycle3.wait_for_server", return_value=True) as mock_wait, \
         patch("_e2e_cycle3.start_pipeline", return_value={"session_id": "sess_123"}) as mock_start, \
         patch("_e2e_cycle3.monitor_pipeline", return_value=final_data) as mock_monitor, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        sim.sleep(100)
        
        e2e.main()
        
        mock_wait.assert_called_once()
        mock_start.assert_called_once()
        mock_monitor.assert_called_once()

def test_main_success_speed_fail():
    """品質はOKだが、処理時間が制限（10分）を超える場合"""
    stages_data = [
        {"name": "Stage A", "status": "completed", "icon": "✅", "detail": "スコア: 93点"}
    ]
    final_data = {"status": "completed", "stages": stages_data}
    
    sim = TimeSimulator()
    
    def mock_monitor(*args, **kwargs):
        sim.sleep(700)  # 700秒 (10分超) 進める
        return final_data
        
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", return_value={"session_id": "sess_123"}), \
         patch("_e2e_cycle3.monitor_pipeline", side_effect=mock_monitor), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        assert excinfo.value.code == 1

def test_main_success_quality_fail():
    """処理時間は制限内だが、品質スコアがベースライン未満の場合"""
    stages_data = [
        {"name": "Stage A", "status": "completed", "icon": "✅", "detail": "スコア: 90点"}
    ]
    final_data = {"status": "completed", "stages": stages_data}
    
    sim = TimeSimulator()
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", return_value={"session_id": "sess_123"}), \
         patch("_e2e_cycle3.monitor_pipeline", return_value=final_data), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        sim.sleep(100)
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        assert excinfo.value.code == 1

def test_main_score_parse_error():
    """品質スコアが数値としてパースできない場合、scoreは0になり、品質ゲートがFAILすることを確認"""
    stages_data = [
        {"name": "Stage A", "status": "completed", "icon": "✅", "detail": "スコア: invalid点"}
    ]
    final_data = {"status": "completed", "stages": stages_data}
    
    sim = TimeSimulator()
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", return_value={"session_id": "sess_123"}), \
         patch("_e2e_cycle3.monitor_pipeline", return_value=final_data), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        sim.sleep(100)
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        assert excinfo.value.code == 1

def test_main_server_timeout():
    """サーバー起動待機でタイムアウトした場合（SystemExit(1)）"""
    with patch("_e2e_cycle3.wait_for_server", return_value=False) as mock_wait:
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        
        assert excinfo.value.code == 1
        mock_wait.assert_called_once()

def test_main_pipeline_failed_or_timeout():
    """パイプラインの実行が失敗または監視タイムアウトになった場合（SystemExit(1)）"""
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", return_value={"session_id": "sess_123"}), \
         patch("_e2e_cycle3.monitor_pipeline", return_value=None):
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        
        assert excinfo.value.code == 1

def test_main_pipeline_error_status():
    """パイプラインが "error" ステータスを返した場合（SystemExit(1)）"""
    final_data = {"status": "error", "error": "Something went wrong"}
    
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", return_value={"session_id": "sess_123"}), \
         patch("_e2e_cycle3.monitor_pipeline", return_value=final_data):
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        
        assert excinfo.value.code == 1

# -----------------------------------------------------------------------------
# 追加のテストケース (Phase 33 T-batch_244c04-bug_hunter-004)
# -----------------------------------------------------------------------------

def test_start_pipeline_http_error():
    """start_pipelineでHTTPErrorが発生した場合、そのまま例外が呼び出し元に伝播することを確認"""
    import urllib.error
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.HTTPError(
            f"{e2e.API}/api/pipeline/start", 500, "Internal Server Error", {}, None
        )
        
        with pytest.raises(urllib.error.HTTPError):
            e2e.start_pipeline()


def test_main_start_pipeline_error_handled():
    """start_pipeline() が URLError を投げたときに main() が適切にキャッチして sys.exit(1) することを確認"""
    with patch("_e2e_cycle3.wait_for_server", return_value=True),          patch("_e2e_cycle3.start_pipeline") as mock_start:
        
        mock_start.side_effect = urllib.error.URLError("Connection failed")
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        
        assert excinfo.value.code == 1
        mock_start.assert_called_once()


# -----------------------------------------------------------------------------
# 追加のエラーハンドリング検証テスト (Phase 33 T-batch_244c04-bug_hunter-004)
# -----------------------------------------------------------------------------

def test_wait_for_server_http_exception():
    """wait_for_serverでhttp.client.HTTPExceptionが発生した場合、適切に再試行され、最終的にタイムアウトすることを確認"""
    import http.client
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = http.client.HTTPException("Protocol error")
        
        result = e2e.wait_for_server(timeout=5)
        
        assert result is False
        assert mock_sleep.call_count == 3


def test_main_start_pipeline_non_dict_handled():
    """start_pipeline()の戻り値が辞書でない場合、main()が適切に例外をキャッチしてsys.exit(1)することを確認"""
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", return_value="not a dict") as mock_start:
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        
        assert excinfo.value.code == 1
        mock_start.assert_called_once()


def test_monitor_pipeline_http_exception():
    """monitor_pipeline監視中にhttp.client.HTTPExceptionが発生したが、最終的に成功する場合の検証"""
    import http.client
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [
            http.client.HTTPException("HTTP failure"),
            mock_response_completed
        ]
        
        result = e2e.monitor_pipeline(timeout=100)
        
        assert result is not None
        assert result["status"] == "completed"
        assert mock_sleep.call_count == 2


def test_monitor_pipeline_non_dict_response():
    """monitor_pipeline監視中に非辞書型レスポンスが返ってきた場合、例外がキャッチされループが継続されることを検証"""
    mock_response_invalid = MagicMock()
    mock_response_invalid.read.return_value = json.dumps(["invalid", "list"]).encode("utf-8")
    
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [
            mock_response_invalid,
            mock_response_completed
        ]
        
        result = e2e.monitor_pipeline(timeout=100)
        
        assert result is not None
        assert result["status"] == "completed"
        assert mock_sleep.call_count == 2


def test_monitor_pipeline_invalid_stage_type():
    """stagesに辞書以外（Noneなど）が混入した場合でもAttributeErrorでクラッシュしないことの検証"""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "status": "completed",
        "stages": [None, {"name": "Render", "status": "completed", "icon": "🎬", "detail": "スコア: 95点"}]
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_response), \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        result = e2e.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "completed"


def test_monitor_pipeline_detail_none():
    """stages内のdetailがNoneの場合にTypeError/AttributeErrorでクラッシュしないことの検証"""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "status": "completed",
        "stages": [{"name": "Render", "status": "completed", "icon": "🎬", "detail": None}]
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_response), \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        result = e2e.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "completed"


def test_main_detail_none_quality_check():
    """mainの品質判定においてdetailがNoneの場合でもTypeErrorでクラッシュせず品質ゲートがFAIL（SysExit(1)）となることの検証"""
    stages_data = [
        {"name": "Stage A", "status": "completed", "icon": "✅", "detail": None}
    ]
    final_data = {"status": "completed", "stages": stages_data}
    
    sim = TimeSimulator()
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", return_value={"session_id": "sess_123"}), \
         patch("_e2e_cycle3.monitor_pipeline", return_value=final_data), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        assert excinfo.value.code == 1

# -----------------------------------------------------------------------------
# E2EPipelineClient のテスト (Phase 33 bug_hunter タスク #5)
# -----------------------------------------------------------------------------

def test_client_wait_for_server_success():
    """E2EPipelineClient.wait_for_server の正常系検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = MagicMock()
        result = client.wait_for_server(timeout=10)
        assert result is True
        mock_urlopen.assert_called_once_with("http://localhost:8000/api/pipeline/status", timeout=3)


def test_client_start_pipeline_success():
    """E2EPipelineClient.start_pipeline の正常系検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"session_id": "sess_client_123"}).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = client.start_pipeline(["path1.mp4"], 20)
        assert result == {"session_id": "sess_client_123"}
        mock_urlopen.assert_called_once()


def test_client_monitor_pipeline_completed():
    """E2EPipelineClient.monitor_pipeline の正常系検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": [{"name": "Stage Client", "status": "completed", "icon": "✅", "detail": "detail"}]
    }).encode("utf-8")
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_response_completed) as mock_urlopen,          patch("time.sleep", side_effect=sim.sleep) as mock_sleep,          patch("time.monotonic", side_effect=sim.get_time):
        result = client.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "completed"
        assert mock_sleep.call_count == 1


# -----------------------------------------------------------------------------
# 例外伝播（エラーハンドリング強化）のテスト (Phase 33 bug_hunter タスク #5)
# -----------------------------------------------------------------------------

def test_wait_for_server_attribute_error_propagates():
    """wait_for_serverでAttributeErrorが発生した場合、握り潰されずにそのまま伝播することを検証"""
    with patch("urllib.request.urlopen", side_effect=AttributeError("Unexpected attribute error")):
        with pytest.raises(AttributeError):
            e2e.wait_for_server(timeout=10)


def test_monitor_pipeline_attribute_error_propagates():
    """monitor_pipelineでAttributeErrorが発生した場合、握り潰されずにそのまま伝播することを検証"""
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=AttributeError("Unexpected attribute error")),          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        with pytest.raises(AttributeError):
            e2e.monitor_pipeline(timeout=100)


def test_main_unexpected_type_error_propagates():
    """main()実行中、start_pipeline()から想定外のTypeErrorが発生した場合、伝播することを検証"""
    with patch("_e2e_cycle3.wait_for_server", return_value=True),          patch("_e2e_cycle3.start_pipeline", side_effect=TypeError("Unexpected type error")):
        with pytest.raises(TypeError):
            e2e.main()



# -----------------------------------------------------------------------------
# HTTPError ログ出力のテスト (Phase 33 bug_hunter タスク #5)
# -----------------------------------------------------------------------------

def test_monitor_pipeline_http_error_logs_properly(capsys):
    """monitor_pipeline監視中にHTTPErrorが発生した際、詳細なステータスコードとボディがログ出力されることを検証"""
    import urllib.error
    # HTTPErrorが発生した後に正常終了レスポンスを返すように設定
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    # HTTPError のモック
    import io
    err_body = io.BytesIO(b"Detailed error message from server")
    http_error = urllib.error.HTTPError(
        f"{e2e.API}/api/pipeline/status", 500, "Internal Server Error", {}, err_body
    )
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [http_error, mock_response_completed]
        
        result = e2e.monitor_pipeline(timeout=100)
        
        assert result is not None
        assert result["status"] == "completed"
        
        captured = capsys.readouterr()
        assert "HTTPError 500: Internal Server Error" in captured.out
        assert "Body: Detailed error message from server" in captured.out


def test_client_monitor_pipeline_http_error_logs_properly(capsys):
    """E2EPipelineClient.monitor_pipeline監視中にHTTPErrorが発生した際、詳細なステータスコードとボディがログ出力されることを検証"""
    import urllib.error
    import io
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    err_body = io.BytesIO(b"Client error message")
    http_error = urllib.error.HTTPError(
        "http://localhost:8000/api/pipeline/status", 400, "Bad Request", {}, err_body
    )
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [http_error, mock_response_completed]
        
        result = client.monitor_pipeline(timeout=100)
        
        assert result is not None
        assert result["status"] == "completed"
        
        captured = capsys.readouterr()
        assert "HTTPError 400: Bad Request" in captured.out
        assert "Body: Client error message" in captured.out

# -----------------------------------------------------------------------------
# 追加の例外ハンドリング検証テスト (OSError, UnicodeDecodeError, etc.)
# -----------------------------------------------------------------------------

def test_monitor_pipeline_http_error_read_oserror(capsys):
    """monitor_pipeline監視中にHTTPErrorが発生し、かつe.read()でOSErrorが発生した際、クラッシュせずにログ出力されることを検証"""
    import urllib.error
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    # read() で OSError を投げる HTTPError のモック
    http_error = urllib.error.HTTPError(
        f"{e2e.API}/api/pipeline/status", 500, "Internal Server Error", {}, None
    )
    http_error.read = MagicMock(side_effect=OSError("Read failure"))
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [http_error, mock_response_completed]
        result = e2e.monitor_pipeline(timeout=100)
        
        assert result is not None
        assert result["status"] == "completed"
        
        captured = capsys.readouterr()
        assert "HTTPError 500: Internal Server Error" in captured.out
        # Bodyは空文字列
        assert "Body: " in captured.out


def test_monitor_pipeline_http_error_decode_error(capsys):
    """monitor_pipeline監視中にHTTPErrorが発生し、かつデコードでUnicodeDecodeErrorが発生した際、クラッシュせずにログ出力されることを検証"""
    import urllib.error
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    # decode で UnicodeDecodeError を投げる HTTPError のモック
    import io
    err_body = io.BytesIO(b"\xff\xfe\xfd")  # 不正なUTF-8バイト
    http_error = urllib.error.HTTPError(
        f"{e2e.API}/api/pipeline/status", 500, "Internal Server Error", {}, err_body
    )
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [http_error, mock_response_completed]
        result = e2e.monitor_pipeline(timeout=100)
        
        assert result is not None
        assert result["status"] == "completed"
        
        captured = capsys.readouterr()
        assert "HTTPError 500: Internal Server Error" in captured.out
        # Bodyは空文字列
        assert "Body: " in captured.out


def test_client_monitor_pipeline_http_error_read_oserror(capsys):
    """E2EPipelineClient.monitor_pipeline監視中にHTTPErrorが発生し、かつe.read()でOSErrorが発生した際、クラッシュせずにログ出力されることを検証"""
    import urllib.error
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    http_error = urllib.error.HTTPError(
        "http://localhost:8000/api/pipeline/status", 400, "Bad Request", {}, None
    )
    http_error.read = MagicMock(side_effect=OSError("Read failure"))
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [http_error, mock_response_completed]
        result = client.monitor_pipeline(timeout=100)
        
        assert result is not None
        assert result["status"] == "completed"
        
        captured = capsys.readouterr()
        assert "HTTPError 400: Bad Request" in captured.out
        assert "Body: " in captured.out


def test_client_monitor_pipeline_http_error_decode_error(capsys):
    """E2EPipelineClient.monitor_pipeline監視中にHTTPErrorが発生し、かつデコードでUnicodeDecodeErrorが発生した際、クラッシュせずにログ出力されることを検証"""
    import urllib.error
    import io
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    err_body = io.BytesIO(b"\xff\xfe\xfd")  # 不正なUTF-8バイト
    http_error = urllib.error.HTTPError(
        "http://localhost:8000/api/pipeline/status", 400, "Bad Request", {}, err_body
    )
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [http_error, mock_response_completed]
        result = client.monitor_pipeline(timeout=100)
        
        assert result is not None
        assert result["status"] == "completed"
        
        captured = capsys.readouterr()
        assert "HTTPError 400: Bad Request" in captured.out
        assert "Body: " in captured.out


def test_client_wait_for_server_timeout():
    """E2EPipelineClient.wait_for_server がタイムアウトまで接続できない場合"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = urllib.error.URLError("Always fail")
        result = client.wait_for_server(timeout=5)
        
        assert result is False
        assert mock_sleep.call_count == 3


def test_client_monitor_pipeline_non_dict_response():
    """E2EPipelineClient.monitor_pipeline監視中に非辞書型レスポンスが返ってきた場合、例外がキャッチされループが継続されることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_response_invalid = MagicMock()
    mock_response_invalid.read.return_value = json.dumps(["invalid", "list"]).encode("utf-8")
    
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [
            mock_response_invalid,
            mock_response_completed
        ]
        
        result = client.monitor_pipeline(timeout=100)
        
        assert result is not None
        assert result["status"] == "completed"
        assert mock_sleep.call_count == 2


def test_client_monitor_pipeline_invalid_stage_type():
    """E2EPipelineClient.monitor_pipeline監視中にstagesに辞書以外（Noneなど）が混入した場合でもAttributeErrorでクラッシュしないことの検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "status": "completed",
        "stages": [None, {"name": "Render", "status": "completed", "icon": "🎬", "detail": "スコア: 95点"}]
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_response), \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        result = client.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "completed"

def test_main_invalid_stage_type_ignored():
    """main()品質判定において、stages内に辞書型以外の要素（Noneなど）が存在する場合に無視されることを検証"""
    stages_data = [
        None,
        {"name": "Stage A", "status": "completed", "icon": "✅", "detail": "スコア: 95点"}
    ]
    final_data = {"status": "completed", "stages": stages_data}
    
    sim = TimeSimulator()
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", return_value={"session_id": "sess_123"}), \
         patch("_e2e_cycle3.monitor_pipeline", return_value=final_data), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        sim.sleep(100)
        e2e.main()  # 正常終了 (品質OK、時間制限内)


def test_client_monitor_pipeline_timeout():
    """E2EPipelineClient.monitor_pipeline で監視タイムアウトに達した場合に None が返ることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = urllib.error.URLError("Timed out in urlopen")
        result = client.monitor_pipeline(timeout=30)
        
        assert result is None
        assert mock_sleep.call_count == 3

def test_client_monitor_pipeline_stages_none_fallback():
    """E2EPipelineClient.monitor_pipeline監視中、レスポンス内のstagesがNone(null)の場合でもTypeErrorでクラッシュせず、空リストとしてフォールバックされることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "status": "completed",
        "stages": None
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_response),          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        result = client.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "completed"

def test_monitor_pipeline_stages_non_list_fallback():
    """モジュール関数 monitor_pipeline 監視中、レスポンス内のstagesが非イテラブル(整数など)の場合でもTypeErrorでクラッシュせず、空リストとしてフォールバックされることを検証"""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "status": "completed",
        "stages": 12345
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_response),          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        result = e2e.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "completed"


# -----------------------------------------------------------------------------
# リソースクローズ検証テスト (Phase 33 リソースリーク対策)
# -----------------------------------------------------------------------------

import io
import urllib.error

class DummyHTTPError(urllib.error.HTTPError):
    def __init__(self):
        fp = io.BytesIO(b"Error")
        super().__init__("http://dummy", 500, "Internal Server Error", {}, fp)
        self.close_called = False
    def close(self):
        self.close_called = True
        super().close()

def test_wait_for_server_http_error_closes_exception():
    """wait_for_server で HTTPError が発生した際に例外オブジェクトが close されることを検証"""
    mock_error = DummyHTTPError()
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=mock_error), \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        e2e.wait_for_server(timeout=1)
        assert mock_error.close_called is True

def test_monitor_pipeline_http_error_closes_exception():
    """monitor_pipeline で HTTPError が発生した際に例外オブジェクトが close されることを検証"""
    mock_error = DummyHTTPError()
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=mock_error), \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        e2e.monitor_pipeline(timeout=1)
        assert mock_error.close_called is True

def test_client_wait_for_server_http_error_closes_exception():
    """E2EPipelineClient.wait_for_server で HTTPError が発生した際に例外オブジェクトが close されることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_error = DummyHTTPError()
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=mock_error), \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        client.wait_for_server(timeout=1)
        assert mock_error.close_called is True

def test_client_monitor_pipeline_http_error_closes_exception():
    """E2EPipelineClient.monitor_pipeline で HTTPError が発生した際に例外オブジェクトが close されることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_error = DummyHTTPError()
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=mock_error), \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        client.monitor_pipeline(timeout=1)
        assert mock_error.close_called is True

def test_start_pipeline_http_error_remains_open():
    """start_pipeline で HTTPError が発生した際、例外オブジェクトがクローズされずに再送出されることを検証"""
    mock_error = DummyHTTPError()
    with patch("urllib.request.urlopen", side_effect=mock_error):
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            e2e.start_pipeline()
        assert excinfo.value.close_called is False

def test_client_start_pipeline_http_error_remains_open():
    """E2EPipelineClient.start_pipeline で HTTPError が発生した際、例外オブジェクトがクローズされずに再送出されることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_error = DummyHTTPError()
    with patch("urllib.request.urlopen", side_effect=mock_error):
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            client.start_pipeline(["path1.mp4"], 20)
        assert excinfo.value.close_called is False


# -----------------------------------------------------------------------------
# 正常系および異常時（パースエラー等）のレスポンスクローズ検証テスト (Phase 33 try-finally効果検証)
# -----------------------------------------------------------------------------

def test_wait_for_server_response_closes_on_success():
    """wait_for_server で接続成功した際、レスポンスがクローズされることを検証"""
    mock_resp = MagicMock()
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = e2e.wait_for_server(timeout=1)
        assert result is True
        mock_resp.close.assert_called_once()

def test_client_wait_for_server_response_closes_on_success():
    """E2EPipelineClient.wait_for_server で接続成功した際、レスポンスがクローズされることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_resp = MagicMock()
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = client.wait_for_server(timeout=1)
        assert result is True
        mock_resp.close.assert_called_once()

def test_start_pipeline_response_closes_on_success():
    """start_pipeline で正常終了した際、レスポンスがクローズされることを検証"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"session_id": "sess_123"}'
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = e2e.start_pipeline()
        assert result == {"session_id": "sess_123"}
        mock_resp.close.assert_called_once()

def test_client_start_pipeline_response_closes_on_success():
    """E2EPipelineClient.start_pipeline で正常終了した際、レスポンスがクローズされることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"session_id": "sess_123"}'
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = client.start_pipeline(["path1.mp4"], 20)
        assert result == {"session_id": "sess_123"}
        mock_resp.close.assert_called_once()

def test_start_pipeline_response_closes_on_parse_error():
    """start_pipeline でレスポンスのパースエラー（非JSON）が発生した際、レスポンスがクローズされることを検証"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'invalid json'
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        with pytest.raises(json.JSONDecodeError):
            e2e.start_pipeline()
        mock_resp.close.assert_called_once()

def test_client_start_pipeline_response_closes_on_parse_error():
    """E2EPipelineClient.start_pipeline でレスポンスのパースエラー（非JSON）が発生した際、レスポンスがクローズされることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'invalid json'
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        with pytest.raises(json.JSONDecodeError):
            client.start_pipeline(["path1.mp4"], 20)
        mock_resp.close.assert_called_once()

def test_monitor_pipeline_response_closes_on_success():
    """monitor_pipeline で監視が1回で正常終了した際、レスポンスがクローズされることを検証"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"status": "completed", "stages": []}'
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        result = e2e.monitor_pipeline(timeout=100)
        assert result == {"status": "completed", "stages": []}
        mock_resp.close.assert_called_once()

def test_client_monitor_pipeline_response_closes_on_success():
    """E2EPipelineClient.monitor_pipeline で監視が1回で正常終了した際、レスポンスがクローズされることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"status": "completed", "stages": []}'
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        result = client.monitor_pipeline(timeout=100)
        assert result == {"status": "completed", "stages": []}
        mock_resp.close.assert_called_once()

def test_monitor_pipeline_response_closes_on_parse_error():
    """monitor_pipeline でパースエラー（非JSON）が発生した際、ループ内でレスポンスがクローズされつつ、次のループで正常に完了することを検証"""
    mock_resp_invalid = MagicMock()
    mock_resp_invalid.read.return_value = b'invalid json'
    
    mock_resp_completed = MagicMock()
    mock_resp_completed.read.return_value = b'{"status": "completed", "stages": []}'
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        mock_urlopen.side_effect = [mock_resp_invalid, mock_resp_completed]
        result = e2e.monitor_pipeline(timeout=100)
        assert result == {"status": "completed", "stages": []}
        mock_resp_invalid.close.assert_called_once()
        mock_resp_completed.close.assert_called_once()

def test_client_monitor_pipeline_response_closes_on_parse_error():
    """E2EPipelineClient.monitor_pipeline でパースエラー（非JSON）が発生した際、ループ内でレスポンスがクローズされつつ、次のループで正常に完了することを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    
    mock_resp_invalid = MagicMock()
    mock_resp_invalid.read.return_value = b'invalid json'
    
    mock_resp_completed = MagicMock()
    mock_resp_completed.read.return_value = b'{"status": "completed", "stages": []}'
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        mock_urlopen.side_effect = [mock_resp_invalid, mock_resp_completed]
        result = client.monitor_pipeline(timeout=100)
        assert result == {"status": "completed", "stages": []}
        mock_resp_invalid.close.assert_called_once()
        mock_resp_completed.close.assert_called_once()


# -----------------------------------------------------------------------------
# 連続エラーと致命的エラーによる早期終了のテスト (Phase 33 改善)
# -----------------------------------------------------------------------------

def test_monitor_pipeline_consecutive_errors_timeout():
    """monitor_pipelineで一時エラーが5回連続して発生した際、早期終了してNoneを返すことを検証"""
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen,          patch("time.sleep", side_effect=sim.sleep) as mock_sleep,          patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        
        result = e2e.monitor_pipeline(timeout=100)
        
        assert result is None
        # 連続5回エラーで早期終了するため、urlopenの呼び出し回数は5回
        assert mock_urlopen.call_count == 5
        # 5回のループで sleep(10) が5回呼ばれる
        assert mock_sleep.call_count == 5

def test_monitor_pipeline_fatal_json_decode_error():
    """monitor_pipelineでJSONDecodeErrorなどの致命的パースエラーが発生した際、連続5回で早期終了してNoneを返すことを検証"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"<html>Error</html>" # 不正な非JSONデータ
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen,          patch("time.sleep", side_effect=sim.sleep) as mock_sleep,          patch("time.monotonic", side_effect=sim.get_time):
        
        result = e2e.monitor_pipeline(timeout=100)
        
        assert result is None
        # 連続5回でエラー終了するため、urlopenの呼び出しは5回
        assert mock_urlopen.call_count == 5
        assert mock_sleep.call_count == 5

def test_monitor_pipeline_error_recovery():
    """monitor_pipelineでエラーが発生しても、正常な受信によりエラーカウンタがリセットされることを検証"""
    mock_resp_running = MagicMock()
    mock_resp_running.read.return_value = b'{"status": "running", "stages": []}'
    
    mock_resp_completed = MagicMock()
    mock_resp_completed.read.return_value = b'{"status": "completed", "stages": []}'
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen,          patch("time.sleep", side_effect=sim.sleep) as mock_sleep,          patch("time.monotonic", side_effect=sim.get_time):
        
        # エラー3回 -> 正常running -> エラー3回 -> 正常completed
        # 連続エラーが最大3回であるため、閾値5回に達せず最後まで正常に監視が完了するはず
        mock_urlopen.side_effect = [
            urllib.error.URLError("Conn err"),
            urllib.error.URLError("Conn err"),
            urllib.error.URLError("Conn err"),
            mock_resp_running,
            urllib.error.URLError("Conn err"),
            urllib.error.URLError("Conn err"),
            urllib.error.URLError("Conn err"),
            mock_resp_completed
        ]
        
        result = e2e.monitor_pipeline(timeout=100)
        
        assert result == {"status": "completed", "stages": []}
        assert mock_urlopen.call_count == 8
        assert mock_sleep.call_count == 8

def test_client_monitor_pipeline_consecutive_errors_timeout():
    """E2EPipelineClient.monitor_pipelineで一時エラーが5回連続して発生した際、早期終了してNoneを返すことを検証"""
    config = e2e.E2EConfig(monitor_timeout=100)
    client = e2e.E2EPipelineClient(config)
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen,          patch("time.sleep", side_effect=sim.sleep) as mock_sleep,          patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        
        result = client.monitor_pipeline()
        
        assert result is None
        assert mock_urlopen.call_count == 5
        assert mock_sleep.call_count == 5


# -----------------------------------------------------------------------------
# Phase 33 エラーハンドリング強化テスト
# -----------------------------------------------------------------------------

def test_wait_for_server_timeout_none():
    """wait_for_server に timeout=None を渡した場合にデフォルトのタイムアウトで動作することを検証"""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = MagicMock()
        result = e2e.wait_for_server(timeout=None)
        assert result is True
        mock_urlopen.assert_called_once()


def test_start_pipeline_non_dict_response():
    """start_pipeline が辞書以外のレスポンスを受け取った際に ValueError を投げることを検証"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'"not a dict string"'
    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ValueError) as excinfo:
            e2e.start_pipeline()
        assert "Response data is not a dictionary" in str(excinfo.value)


def test_client_start_pipeline_non_dict_response():
    """E2EPipelineClient.start_pipeline が辞書以外のレスポンスを受け取った際に ValueError を投げることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'"not a dict string"'
    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ValueError) as excinfo:
            client.start_pipeline(["path.mp4"], 20)
        assert "Response data is not a dictionary" in str(excinfo.value)


def test_main_start_pipeline_http_exception_handled():
    """main() で start_pipeline() が HTTPException を投げた際に適切にキャッチされ、sys.exit(1) で終了することを検証"""
    import http.client
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", side_effect=http.client.HTTPException("Connection broken")):
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        assert excinfo.value.code == 1


def test_main_final_non_dict_handled():
    """monitor_pipeline から辞書以外の結果が返ってきた場合に、main() が適切に sys.exit(1) で終了することを検証"""
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", return_value={"session_id": "sess_123"}), \
         patch("_e2e_cycle3.monitor_pipeline", return_value="not a dict completed"):
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        assert excinfo.value.code == 1


def test_main_detail_non_str_handled():
    """stages の detail に文字列以外のオブジェクト（例えば辞書）が設定されていた場合でも、main() がクラッシュせず終了することを検証"""
    stages_data = [
        {"name": "Stage A", "status": "completed", "icon": "✅", "detail": {"unexpected": "object"}}
    ]
    final_data = {"status": "completed", "stages": stages_data}
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", return_value={"session_id": "sess_123"}), \
         patch("_e2e_cycle3.monitor_pipeline", return_value=final_data):
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        assert excinfo.value.code == 1

def test_client_monitor_pipeline_fatal_json_decode_error():
    """E2EPipelineClient.monitor_pipelineで致命的パースエラーが発生した際、連続5回で早期終了してNoneを返すことを検証"""
    config = e2e.E2EConfig(monitor_timeout=100)
    client = e2e.E2EPipelineClient(config)
    
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"Not JSON"
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen,          patch("time.sleep", side_effect=sim.sleep) as mock_sleep,          patch("time.monotonic", side_effect=sim.get_time):
        
        result = client.monitor_pipeline()
        
        assert result is None
        assert mock_urlopen.call_count == 5
        assert mock_sleep.call_count == 5




# -----------------------------------------------------------------------------
# with 構文導入による read 途中例外時の自動クローズテスト (Phase 33 強化)
# -----------------------------------------------------------------------------

def test_start_pipeline_response_closes_on_read_failure():
    """start_pipeline で resp.read() 中に OSError が発生した場合でも、resp がクローズされることを検証"""
    mock_resp = MagicMock()
    mock_resp.read.side_effect = OSError("Read timeout or connection reset")
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        with pytest.raises(OSError):
            e2e.start_pipeline()
        mock_resp.close.assert_called_once()

def test_client_start_pipeline_response_closes_on_read_failure():
    """E2EPipelineClient.start_pipeline で resp.read() 中に OSError が発生した場合でも、resp がクローズされることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_resp = MagicMock()
    mock_resp.read.side_effect = OSError("Read timeout or connection reset")
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        with pytest.raises(OSError):
            client.start_pipeline(["path.mp4"], 20)
        mock_resp.close.assert_called_once()


# -----------------------------------------------------------------------------
# 追加のテスト (Phase 33 エラーハンドリング強化・ログ詳細化)
# -----------------------------------------------------------------------------

def test_monitor_pipeline_consecutive_http_errors_timeout():
    """monitor_pipelineでHTTPErrorが5回連続して発生した際、早期終了してNoneを返すことを検証"""
    import io
    def http_error_factory(*args, **kwargs):
        err_body = io.BytesIO(b"Error body")
        return urllib.error.HTTPError(
            f"{e2e.API}/api/pipeline/status", 500, "Internal Server Error", {}, err_body
        )
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen,          patch("time.sleep", side_effect=sim.sleep) as mock_sleep,          patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = http_error_factory
        result = e2e.monitor_pipeline(timeout=100)
        
        assert result is None
        assert mock_urlopen.call_count == 5

def test_client_monitor_pipeline_consecutive_http_errors_timeout():
    """E2EPipelineClient.monitor_pipelineでHTTPErrorが5回連続して発生した際、早期終了してNoneを返すことを検証"""
    import io
    config = e2e.E2EConfig(monitor_timeout=100)
    client = e2e.E2EPipelineClient(config)
    def http_error_factory(*args, **kwargs):
        err_body = io.BytesIO(b"Error body")
        return urllib.error.HTTPError(
            "http://localhost:8000/api/pipeline/status", 500, "Internal Server Error", {}, err_body
        )
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen,          patch("time.sleep", side_effect=sim.sleep) as mock_sleep,          patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = http_error_factory
        result = client.monitor_pipeline()
        
        assert result is None
        assert mock_urlopen.call_count == 5

def test_wait_for_server_http_error_logging(capsys):
    """wait_for_serverでHTTPErrorが発生した際に適切にログが出力されることを検証"""
    import io
    err_body = io.BytesIO(b"Error")
    http_error = urllib.error.HTTPError(
        f"{e2e.API}/api/pipeline/status", 503, "Service Unavailable", {}, err_body
    )
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=http_error),          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        e2e.wait_for_server(timeout=3)
        captured = capsys.readouterr()
        assert "Server returned HTTPError: 503 Service Unavailable" in captured.out

def test_wait_for_server_connection_failed_logging(capsys):
    """wait_for_serverでURLErrorが発生した際に適切に接続失敗ログが出力されることを検証"""
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network down")),          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        e2e.wait_for_server(timeout=3)
        captured = capsys.readouterr()
        assert "Server connection failed: <urlopen error Network down>" in captured.out

def test_client_wait_for_server_logging(capsys):
    """E2EPipelineClient.wait_for_serverで例外発生時にログが出力されることを検証"""
    config = e2e.E2EConfig(wait_timeout=3)
    client = e2e.E2EPipelineClient(config)
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network down")),          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        client.wait_for_server()
        captured = capsys.readouterr()
        assert "Server connection failed: <urlopen error Network down>" in captured.out

def test_monitor_pipeline_connection_timeout_logging(capsys):
    """monitor_pipelineでタイムアウト例外が発生した際にConnection timed outがログ出力されることを検証"""
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = b'{"status": "completed", "stages": []}'
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen,          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [urllib.error.URLError("timed out"), mock_response_completed]
        e2e.monitor_pipeline(timeout=100)
        captured = capsys.readouterr()
        assert "Connection timed out" in captured.out

def test_client_monitor_pipeline_connection_timeout_logging(capsys):
    """E2EPipelineClient.monitor_pipelineでタイムアウト例外が発生した際にConnection timed outがログ出力されることを検証"""
    config = e2e.E2EConfig(monitor_timeout=100)
    client = e2e.E2EPipelineClient(config)
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = b'{"status": "completed", "stages": []}'
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen,          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [urllib.error.URLError("timed out"), mock_response_completed]
        client.monitor_pipeline()
        captured = capsys.readouterr()
        assert "Connection timed out" in captured.out

def test_monitor_pipeline_read_failure_snippet(capsys):
    """monitor_pipelineでHTTPErrorのread()に失敗した際、snippetに失敗理由が設定されることを検証"""
    import urllib.error
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = b'{"status": "completed", "stages": []}'
    
    http_error = urllib.error.HTTPError(
        f"{e2e.API}/api/pipeline/status", 500, "Internal Server Error", {}, None
    )
    http_error.read = MagicMock(side_effect=OSError("Read timeout"))
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen,          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [http_error, mock_response_completed]
        e2e.monitor_pipeline(timeout=100)
        captured = capsys.readouterr()
        assert "Body: (failed to read body: Read timeout)" in captured.out

def test_client_monitor_pipeline_read_failure_snippet(capsys):
    """E2EPipelineClient.monitor_pipelineでHTTPError of read()に失敗した際、snippetに失敗理由が設定されることを検証"""
    config = e2e.E2EConfig(monitor_timeout=100)
    client = e2e.E2EPipelineClient(config)
    
    http_error = urllib.error.HTTPError(
        "http://localhost:8000/api/pipeline/status", 500, "Internal Server Error", {}, None
    )
    http_error.read = MagicMock(side_effect=OSError("Read timeout"))
    
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = b'{"status": "completed", "stages": []}'
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen,          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [http_error, mock_response_completed]
        client.monitor_pipeline()
        captured = capsys.readouterr()
        assert "Body: (failed to read body: Read timeout)" in captured.out

# -----------------------------------------------------------------------------
# 新規追加されたエラーハンドリング（HTTPErrorのBodyログ、ValueErrorによる早期離脱）のテスト
# -----------------------------------------------------------------------------

def test_start_pipeline_http_error_body_logging(capsys):
    """start_pipelineでHTTPErrorが発生した際、エラーボディがロギングされて例外が再送出されることを検証"""
    mock_err_fp = MagicMock()
    mock_err_fp.read.return_value = b"Custom error details from server"
    
    # HTTPErrorの引数: url, code, msg, hdrs, fp
    mock_err = urllib.error.HTTPError("http://test/start", 400, "Bad Request", {}, mock_err_fp)
    
    with patch("urllib.request.urlopen", side_effect=mock_err):
        with pytest.raises(urllib.error.HTTPError):
            e2e.start_pipeline()
            
    captured = capsys.readouterr()
    assert "Server returned HTTPError 400: Bad Request" in captured.out
    assert "Custom error details from server" in captured.out

def test_client_start_pipeline_http_error_body_logging(capsys):
    """E2EPipelineClient.start_pipelineでHTTPErrorが発生した際、エラーボディがロギングされて例外が再送出されることを検証"""
    config = e2e.E2EConfig()
    client = e2e.E2EPipelineClient(config)
    
    mock_err_fp = MagicMock()
    mock_err_fp.read.return_value = b"Client error details"
    mock_err = urllib.error.HTTPError("http://test/start", 401, "Unauthorized", {}, mock_err_fp)
    
    with patch("urllib.request.urlopen", side_effect=mock_err):
        with pytest.raises(urllib.error.HTTPError):
            client.start_pipeline(["video.mp4"], 10)
            
    captured = capsys.readouterr()
    assert "Server returned HTTPError 401: Unauthorized" in captured.out
    assert "Client error details" in captured.out

def test_wait_for_server_http_error_body_logging(capsys):
    """wait_for_serverでHTTPErrorが発生した際、エラーボディがロギングされてタイムアウトまでリトライされることを検証"""
    mock_err_fp = MagicMock()
    mock_err_fp.read.return_value = b"Database connection failed"
    mock_err = urllib.error.HTTPError("http://test/status", 500, "Internal Server Error", {}, mock_err_fp)
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=mock_err),          patch("time.sleep", side_effect=sim.sleep) as mock_sleep,          patch("time.monotonic", side_effect=sim.get_time):
        
        result = e2e.wait_for_server(timeout=5)
        
        assert result is False
        assert mock_sleep.call_count == 3
        
    captured = capsys.readouterr()
    assert "Server returned HTTPError: 500 Internal Server Error" in captured.out
    assert "Database connection failed" in captured.out

def test_client_wait_for_server_http_error_body_logging(capsys):
    """E2EPipelineClient.wait_for_serverでHTTPErrorが発生した際、エラーボディがロギングされてタイムアウトまでリトライされることを検証"""
    config = e2e.E2EConfig(wait_timeout=5)
    client = e2e.E2EPipelineClient(config)
    
    mock_err_fp = MagicMock()
    mock_err_fp.read.return_value = b"Gateway Timeout"
    mock_err = urllib.error.HTTPError("http://test/status", 504, "Gateway Timeout", {}, mock_err_fp)
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=mock_err),          patch("time.sleep", side_effect=sim.sleep) as mock_sleep,          patch("time.monotonic", side_effect=sim.get_time):
        
        result = client.wait_for_server()
        
        assert result is False
        assert mock_sleep.call_count == 3
        
    captured = capsys.readouterr()
    assert "Server returned HTTPError: 504 Gateway Timeout" in captured.out
    assert "Gateway Timeout" in captured.out

def test_wait_for_server_value_error_returns_false(capsys):
    """wait_for_serverでValueErrorが発生した際、即座にFalseを返すことを検証"""
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=ValueError("unknown url type")),          patch("time.sleep", side_effect=sim.sleep) as mock_sleep,          patch("time.monotonic", side_effect=sim.get_time):
        
        result = e2e.wait_for_server(timeout=10)
        
        assert result is False
        # リトライループに入らず即座にリターンするため、sleepは0回
        assert mock_sleep.call_count == 0
        
    captured = capsys.readouterr()
    assert "Invalid URL or configuration error: unknown url type" in captured.out

def test_client_wait_for_server_value_error_returns_false(capsys):
    """E2EPipelineClient.wait_for_serverでValueErrorが発生した際、即座にFalseを返すことを検証"""
    config = e2e.E2EConfig(wait_timeout=10)
    client = e2e.E2EPipelineClient(config)
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=ValueError("unknown url type")),          patch("time.sleep", side_effect=sim.sleep) as mock_sleep,          patch("time.monotonic", side_effect=sim.get_time):
        
        result = client.wait_for_server()
        
        assert result is False
        assert mock_sleep.call_count == 0
        
    captured = capsys.readouterr()
    assert "Invalid URL or configuration error: unknown url type" in captured.out


def test_monitor_pipeline_detail_non_str_dict():
    """monitor_pipeline監視中、stages内のdetailが辞書型の場合にTypeErrorでクラッシュせず、正常に処理されることを検証"""
    mock_response_running = MagicMock()
    mock_response_running.read.return_value = json.dumps({
        "status": "running",
        "stages": [{"name": "Render", "status": "running", "icon": "🎬", "detail": {"error_code": 500, "message": "Failed"}}]
    }).encode("utf-8")
    
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [mock_response_running, mock_response_completed]
        result = e2e.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "completed"


def test_client_monitor_pipeline_detail_non_str_dict():
    """E2EPipelineClient.monitor_pipeline監視中、stages内のdetailが辞書型の場合にTypeErrorでクラッシュせず、正常に処理されることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    mock_response_running = MagicMock()
    mock_response_running.read.return_value = json.dumps({
        "status": "running",
        "stages": [{"name": "Render", "status": "running", "icon": "🎬", "detail": {"error_code": 500, "message": "Failed"}}]
    }).encode("utf-8")
    
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [mock_response_running, mock_response_completed]
        result = client.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "completed"


def test_main_score_parse_error_warning_logged(capsys):
    """品質スコアがパースできない際に、適切に警告ログが出力されることを検証"""
    stages_data = [
        {"name": "Stage A", "status": "completed", "icon": "✅", "detail": "スコア: invalid点"}
    ]
    final_data = {"status": "completed", "stages": stages_data}
    
    sim = TimeSimulator()
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", return_value={"session_id": "sess_123"}), \
         patch("_e2e_cycle3.monitor_pipeline", return_value=final_data), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        sim.sleep(100)
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        assert excinfo.value.code == 1
        
    captured = capsys.readouterr()
    assert "Warning: スコアのパースに失敗しました" in captured.out


# -----------------------------------------------------------------------------
# AttributeError & TypeError ハンドリング検証テスト (Phase 33 強化)
# -----------------------------------------------------------------------------

def test_monitor_pipeline_http_error_read_attribute_error_propagates(capsys):
    """monitor_pipeline監視中にHTTPErrorが発生し、かつe.read()でAttributeErrorが発生した際、クラッシュせずにログ出力されることを検証"""
    import urllib.error
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    http_error = urllib.error.HTTPError(
        f"{e2e.API}/api/pipeline/status", 500, "Internal Server Error", {}, None
    )
    http_error.read = MagicMock(side_effect=AttributeError("Mocked attribute error"))
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [http_error, mock_response_completed]
        result = e2e.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "completed"
        captured = capsys.readouterr()
        assert "HTTPError 500: Internal Server Error" in captured.out
        assert "Body: (failed to read body: Mocked attribute error)" in captured.out


def test_monitor_pipeline_http_error_read_type_error_propagates(capsys):
    """monitor_pipeline監視中にHTTPErrorが発生し、かつe.read()でTypeErrorが発生した際、クラッシュせずにログ出力されることを検証"""
    import urllib.error
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    http_error = urllib.error.HTTPError(
        f"{e2e.API}/api/pipeline/status", 500, "Internal Server Error", {}, None
    )
    http_error.read = MagicMock(side_effect=TypeError("Mocked type error"))
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [http_error, mock_response_completed]
        result = e2e.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "completed"
        captured = capsys.readouterr()
        assert "HTTPError 500: Internal Server Error" in captured.out
        assert "Body: (failed to read body: Mocked type error)" in captured.out


def test_client_monitor_pipeline_http_error_read_attribute_error_propagates(capsys):
    """E2EPipelineClient.monitor_pipeline監視中にHTTPErrorが発生し、かつe.read()でAttributeErrorが発生した際、クラッシュせずにログ出力されることを検証"""
    import urllib.error
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    http_error = urllib.error.HTTPError(
        "http://localhost:8000/api/pipeline/status", 400, "Bad Request", {}, None
    )
    http_error.read = MagicMock(side_effect=AttributeError("Mocked attribute error"))
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [http_error, mock_response_completed]
        result = client.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "completed"
        captured = capsys.readouterr()
        assert "HTTPError 400: Bad Request" in captured.out
        assert "Body: (failed to read body: Mocked attribute error)" in captured.out


def test_client_monitor_pipeline_http_error_read_type_error_propagates(capsys):
    """E2EPipelineClient.monitor_pipeline監視中にHTTPErrorが発生し、かつe.read()でTypeErrorが発生した際、クラッシュせずにログ出力されることを検証"""
    import urllib.error
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    
    mock_response_completed = MagicMock()
    mock_response_completed.read.return_value = json.dumps({
        "status": "completed",
        "stages": []
    }).encode("utf-8")
    
    http_error = urllib.error.HTTPError(
        "http://localhost:8000/api/pipeline/status", 400, "Bad Request", {}, None
    )
    http_error.read = MagicMock(side_effect=TypeError("Mocked type error"))
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        mock_urlopen.side_effect = [http_error, mock_response_completed]
        result = client.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "completed"
        captured = capsys.readouterr()
        assert "HTTPError 400: Bad Request" in captured.out
        assert "Body: (failed to read body: Mocked type error)" in captured.out


# -----------------------------------------------------------------------------
# エラーハンドリングおよびリソースクローズ強化の追加テスト (Phase 33 修正検証)
# -----------------------------------------------------------------------------

def test_main_http_error_closes_exception():
    """main() で start_pipeline() が HTTPError を投げた際に、例外オブジェクトが適切にクローズされることを検証"""
    mock_error = DummyHTTPError()
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", side_effect=mock_error):
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        assert excinfo.value.code == 1
        assert mock_error.close_called is True


# -----------------------------------------------------------------------------
# AttributeError & TypeError 安全キャッチ検証新規テスト (Phase 33 改善)
# -----------------------------------------------------------------------------

def test_wait_for_server_http_error_read_attribute_error_logged(capsys):
    """wait_for_serverでHTTPErrorが発生し、かつe.read()でAttributeErrorが発生した際、クラッシュせずにログ出力されることを検証"""
    import urllib.error
    http_error = urllib.error.HTTPError(
        f"{e2e.API}/api/pipeline/status", 500, "Internal Server Error", {}, None
    )
    http_error.read = MagicMock(side_effect=AttributeError("WaitServer AttributeError"))
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=http_error), \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        result = e2e.wait_for_server(timeout=3)
        assert result is False
        
        captured = capsys.readouterr()
        assert "Server returned HTTPError: 500 Internal Server Error" in captured.out
        assert "Body: (failed to read body: WaitServer AttributeError)" in captured.out


def test_start_pipeline_http_error_read_attribute_error_logged(capsys):
    """start_pipelineでHTTPErrorが発生し、かつe.read()でAttributeErrorが発生した際、クラッシュせずにログ出力されて例外が再送出されることを検証"""
    import urllib.error
    http_error = urllib.error.HTTPError(
        f"{e2e.API}/api/pipeline/start", 400, "Bad Request", {}, None
    )
    http_error.read = MagicMock(side_effect=AttributeError("StartPipeline AttributeError"))
    
    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(urllib.error.HTTPError):
            e2e.start_pipeline()
            
        captured = capsys.readouterr()
        assert "Server returned HTTPError 400: Bad Request" in captured.out
        assert "Body: (failed to read body: StartPipeline AttributeError)" in captured.out


# -----------------------------------------------------------------------------
# 新規追加: TimeoutError, JSONDecodeError, ValueError 強化テスト
# -----------------------------------------------------------------------------

def test_wait_for_server_timeout_error_logged(capsys):
    """wait_for_serverでTimeoutErrorが発生した際に適切にタイムアウトログが出力されることを検証"""
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")),          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        result = e2e.wait_for_server(timeout=3)
        assert result is False
        
        captured = capsys.readouterr()
        assert "Server connection timed out: Connection timed out" in captured.out


def test_client_wait_for_server_timeout_error_logged(capsys):
    """E2EPipelineClient.wait_for_serverでTimeoutErrorが発生した際に適切にタイムアウトログが出力されることを検証"""
    config = e2e.E2EConfig(wait_timeout=3)
    client = e2e.E2EPipelineClient(config)
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")),          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        result = client.wait_for_server()
        assert result is False
        
        captured = capsys.readouterr()
        assert "Server connection timed out: Connection timed out" in captured.out


def test_monitor_pipeline_json_decode_error_logged(capsys):
    """monitor_pipelineでJSONDecodeErrorが発生した際、「JSONパース失敗」がログ出力されることを検証"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"Not a JSON string"
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_resp),          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        result = e2e.monitor_pipeline(timeout=100)
        assert result is None
        
        captured = capsys.readouterr()
        assert "JSONパース失敗" in captured.out


def test_client_monitor_pipeline_json_decode_error_logged(capsys):
    """E2EPipelineClient.monitor_pipelineでJSONDecodeErrorが発生した際、「JSONパース失敗」がログ出力されることを検証"""
    config = e2e.E2EConfig(monitor_timeout=100)
    client = e2e.E2EPipelineClient(config)
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"Not a JSON string"
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_resp),          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        result = client.monitor_pipeline()
        assert result is None
        
        captured = capsys.readouterr()
        assert "JSONパース失敗" in captured.out


def test_monitor_pipeline_value_error_logged(capsys):
    """monitor_pipelineでValueErrorが発生した際、「レスポンスデータ検証失敗」がログ出力されることを検証"""
    mock_resp = MagicMock()
    # 辞書でないJSON
    mock_resp.read.return_value = b'"Just a string"'
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_resp),          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        result = e2e.monitor_pipeline(timeout=100)
        assert result is None
        
        captured = capsys.readouterr()
        assert "レスポンスデータ検証失敗" in captured.out


def test_client_monitor_pipeline_value_error_logged(capsys):
    """E2EPipelineClient.monitor_pipelineでValueErrorが発生した際、「レスポンスデータ検証失敗」がログ出力されることを検証"""
    config = e2e.E2EConfig(monitor_timeout=100)
    client = e2e.E2EPipelineClient(config)
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'"Just a string"'
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_resp),          patch("time.sleep", side_effect=sim.sleep),          patch("time.monotonic", side_effect=sim.get_time):
        
        result = client.monitor_pipeline()
        assert result is None
        
        captured = capsys.readouterr()
        assert "レスポンスデータ検証失敗" in captured.out


# -----------------------------------------------------------------------------
# timeout=None に対する安全なデフォルト値適用のテスト (Phase 33 bug_hunter タスク #3)
# -----------------------------------------------------------------------------

def test_client_wait_for_server_timeout_none_config():
    """E2EPipelineClient.wait_for_server において、config.wait_timeout と引数 timeout が共に None の場合、デフォルトの 60 秒が適用されて動作することを検証"""
    config = e2e.E2EConfig(wait_timeout=None)
    client = e2e.E2EPipelineClient(config)
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Always fail")), \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        result = client.wait_for_server(timeout=None)
        assert result is False
        # 60秒間で 2秒スリープを繰り返すので、約30回 sleep が呼ばれるはず
        assert mock_sleep.call_count >= 29


def test_client_monitor_pipeline_timeout_none_config():
    """E2EPipelineClient.monitor_pipeline において、config.monitor_timeout と引数 timeout が共に None の場合、デフォルトの 1800 秒が適用されて動作することを検証"""
    config = e2e.E2EConfig(monitor_timeout=None)
    client = e2e.E2EPipelineClient(config)
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Always fail")), \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        # 連続エラー数が5に達すると終了するので、実際には 5回 sleep するだけで終わるが、
        # ループ自体の時間制限 (1800秒) で TypeError にならないことを保証する
        result = client.monitor_pipeline(timeout=None)
        assert result is None
        assert mock_sleep.call_count == 5


# -----------------------------------------------------------------------------
# 追加の個別例外ハンドリング検証テスト (Phase 33 強化)
# -----------------------------------------------------------------------------

def test_main_start_pipeline_url_error_handled_detail(capsys):
    """start_pipeline() が URLError を投げたときに main() が適切なエラーメッセージを出力して終了することを検証"""
    import urllib.error
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", side_effect=urllib.error.URLError("Connection failed")):
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "FAIL: パイプラインの起動に失敗しました (通信エラー: Connection failed)" in captured.out


def test_main_start_pipeline_http_exception_handled_detail(capsys):
    """start_pipeline() が HTTPException を投げたときに main() が適切なエラーメッセージを出力して終了することを検証"""
    import http.client
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", side_effect=http.client.HTTPException("Protocol error")):
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "FAIL: パイプラインの起動に失敗しました (HTTP例外: Protocol error)" in captured.out


def test_main_start_pipeline_json_decode_error_handled(capsys):
    """start_pipeline() が JSONDecodeError を投げたときに main() が適切なエラーメッセージを出力して終了することを検証"""
    import json
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", side_effect=json.JSONDecodeError("Expecting value", "", 0)):
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "FAIL: レスポンスのJSONパースに失敗しました" in captured.out


def test_main_start_pipeline_os_error_handled(capsys):
    """start_pipeline() が OSError を投げたときに main() が適切なエラーメッセージを出力して終了することを検証"""
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", side_effect=OSError("Disk full")):
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "FAIL: OSエラーが発生しました: Disk full" in captured.out


# -----------------------------------------------------------------------------
# 今回追加した例外ハンドリングとロギングの検証テスト (Phase 33 強化)
# -----------------------------------------------------------------------------

def test_main_start_pipeline_timeout_handled(capsys):
    """start_pipeline() が TimeoutError を投げたときに main() が適切なエラーメッセージを出力して終了することを検証"""
    with patch("_e2e_cycle3.wait_for_server", return_value=True),          patch("_e2e_cycle3.start_pipeline", side_effect=TimeoutError("Request timed out")):
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "FAIL: パイプラインの起動に失敗しました (接続タイムアウト: Request timed out)" in captured.out


def test_client_start_pipeline_url_error_logged(capsys):
    """E2EPipelineClient.start_pipeline 内で URLError が発生した際に、ログに出力され、例外が再スローされることを検証"""
    config = e2e.E2EConfig()
    client = e2e.E2EPipelineClient(config)
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Host not found")):
        with pytest.raises(urllib.error.URLError):
            client.start_pipeline(["dummy.mp4"], 20)
        captured = capsys.readouterr()
        assert "Connection URLError during start_pipeline: Host not found" in captured.out


def test_client_start_pipeline_timeout_logged(capsys):
    """E2EPipelineClient.start_pipeline 内で TimeoutError が発生した際に、ログに出力され、例外が再スローされることを検証"""
    config = e2e.E2EConfig()
    client = e2e.E2EPipelineClient(config)
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timeout")):
        with pytest.raises(TimeoutError):
            client.start_pipeline(["dummy.mp4"], 20)
        captured = capsys.readouterr()
        assert "Connection timeout during start_pipeline: Connection timeout" in captured.out


def test_client_start_pipeline_http_exception_logged(capsys):
    """E2EPipelineClient.start_pipeline 内で HTTPException が発生した際に、ログに出力され、例外が再スローされることを検証"""
    import http.client
    config = e2e.E2EConfig()
    client = e2e.E2EPipelineClient(config)
    with patch("urllib.request.urlopen", side_effect=http.client.HTTPException("Protocol violation")):
        with pytest.raises(http.client.HTTPException):
            client.start_pipeline(["dummy.mp4"], 20)
        captured = capsys.readouterr()
        assert "HTTPException during start_pipeline: Protocol violation" in captured.out


def test_client_start_pipeline_json_decode_error_logged(capsys):
    """E2EPipelineClient.start_pipeline 内で JSONDecodeError が発生した際に、ログに出力され、例外が再スローされることを検証"""
    config = e2e.E2EConfig()
    client = e2e.E2EPipelineClient(config)
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"invalid json"
    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(json.JSONDecodeError):
            client.start_pipeline(["dummy.mp4"], 20)
        captured = capsys.readouterr()
        assert "JSONDecodeError during start_pipeline:" in captured.out


def test_client_start_pipeline_value_error_logged(capsys):
    """E2EPipelineClient.start_pipeline 内で ValueError (辞書型でない等) が発生した際に、ログに出力され、例外が再スローされることを検証"""
    config = e2e.E2EConfig()
    client = e2e.E2EPipelineClient(config)
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'["not a dict"]'
    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ValueError):
            client.start_pipeline(["dummy.mp4"], 20)
        captured = capsys.readouterr()
        assert "ValueError during start_pipeline:" in captured.out


def test_client_start_pipeline_os_error_logged(capsys):
    """E2EPipelineClient.start_pipeline 内で OSError が発生した際に、ログに出力され、例外が再スローされることを検証"""
    config = e2e.E2EConfig()
    client = e2e.E2EPipelineClient(config)
    with patch("urllib.request.urlopen", side_effect=OSError("Read-only file system")):
        with pytest.raises(OSError):
            client.start_pipeline(["dummy.mp4"], 20)
        captured = capsys.readouterr()
        assert "OSError during start_pipeline: Read-only file system" in captured.out


def test_client_monitor_pipeline_error_status_logs_detailed_error(capsys):
    """E2EPipelineClient.monitor_pipeline監視中に status == "error" になった際、ログに error の詳細メッセージが出力されることを検証"""
    config = e2e.E2EConfig(api_url="http://localhost:8000")
    client = e2e.E2EPipelineClient(config)
    
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "status": "error",
        "error": "GPU Memory Allocation Failed",
        "stages": [{"name": "Render", "status": "failed", "detail": "Out of memory"}]
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_response), \
         patch("time.sleep", side_effect=sim.sleep), \
         patch("time.monotonic", side_effect=sim.get_time):
        
        result = client.monitor_pipeline(timeout=100)
        assert result is not None
        assert result["status"] == "error"
        assert result["error"] == "GPU Memory Allocation Failed"
        
        captured = capsys.readouterr()
        assert "GPU Memory Allocation Failed" in captured.out


def test_main_monitor_pipeline_exception_handled():
    """main()実行中、monitor_pipeline() から URLError 例外が発生した場合、適切にキャッチされ sys.exit(1) することを確認"""
    with patch("_e2e_cycle3.wait_for_server", return_value=True), \
         patch("_e2e_cycle3.start_pipeline", return_value={"session_id": "sess_123"}), \
         patch("_e2e_cycle3.monitor_pipeline", side_effect=urllib.error.URLError("Connection reset")):
        
        with pytest.raises(SystemExit) as excinfo:
            e2e.main()
        assert excinfo.value.code == 1


# -----------------------------------------------------------------------------
# 負のタイムアウトに対するエラーハンドリングテスト (Phase 33 強化)
# -----------------------------------------------------------------------------

def test_wait_for_server_negative_timeout():
    """wait_for_server に負のタイムアウトを渡した場合に ValueError が発生することを確認"""
    with pytest.raises(ValueError) as excinfo:
        e2e.wait_for_server(timeout=-5)
    assert "Timeout must be non-negative" in str(excinfo.value)

def test_client_wait_for_server_negative_timeout():
    """E2EPipelineClient.wait_for_server に負のタイムアウトを渡した場合に ValueError が発生することを確認"""
    config = e2e.E2EConfig(wait_timeout=-10)
    client = e2e.E2EPipelineClient(config)
    with pytest.raises(ValueError) as excinfo:
        client.wait_for_server()
    assert "Timeout must be non-negative" in str(excinfo.value)

def test_monitor_pipeline_negative_timeout():
    """monitor_pipeline に負のタイムアウトを渡した場合に ValueError が発生することを確認"""
    with pytest.raises(ValueError) as excinfo:
        e2e.monitor_pipeline(timeout=-1)
    assert "Timeout must be non-negative" in str(excinfo.value)

def test_client_monitor_pipeline_negative_timeout():
    """E2EPipelineClient.monitor_pipeline に負のタイムアウトを渡した場合に ValueError が発生することを確認"""
    config = e2e.E2EConfig(monitor_timeout=-100)
    client = e2e.E2EPipelineClient(config)
    with pytest.raises(ValueError) as excinfo:
        client.monitor_pipeline()
    assert "Timeout must be non-negative" in str(excinfo.value)


# -----------------------------------------------------------------------------
# time.monotonic() 移行の検証テスト (Phase 33 bug_hunter 脆弱性修正検証)
# -----------------------------------------------------------------------------

def test_no_time_time_calls():
    """_e2e_cycle3.py の wait_for_server および monitor_pipeline 内で time.time が呼び出されていないことを検証"""
    with patch("time.time") as mock_time, \
         patch("time.sleep") as mock_sleep, \
         patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.URLError("Always fail")
        
        # wait_for_server の実行
        e2e.wait_for_server(timeout=1)
        mock_time.assert_not_called()

    with patch("time.time") as mock_time, \
         patch("time.sleep") as mock_sleep, \
         patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.URLError("Always fail")
        
        # monitor_pipeline の実行
        e2e.monitor_pipeline(timeout=1)
        mock_time.assert_not_called()


def test_time_monotonic_timeout_resilience():
    """time.monotonic が単調増加することで、タイムアウト時間経過後にループが確実に終了することを検証"""
    # モックの monotonic 戻り値を設定し、時間が進むことをシミュレート
    monotonic_values = [100.0, 101.0, 102.0, 200.0]  # 4回目でタイムアウト閾値(60)を超える
    
    with patch("time.monotonic", side_effect=monotonic_values), \
         patch("time.sleep") as mock_sleep, \
         patch("urllib.request.urlopen") as mock_urlopen:
        
        mock_urlopen.side_effect = urllib.error.URLError("Always fail")
        
        # wait_for_server は timeout=60 の場合、
        # 100.0 (開始) -> 101.0 (経過1) -> 102.0 (経過2) -> 200.0 (経過100 -> タイムアウト) となり、ループを抜けるはず
        result = e2e.wait_for_server(timeout=60)
        assert result is False

def test_default_video_paths_exist():
    """_e2e_cycle3.py の DEFAULT_VIDEO_PATHS に定義されている動画ファイルが実在することを検証 (プロジェクトルートが存在する場合のみ)"""
    import os
    import pytest
    for path in e2e.DEFAULT_VIDEO_PATHS:
        if not os.path.exists(path):
            pytest.skip(f"Video file not found in this environment: {path}")
        assert os.path.exists(path)


def test_default_video_paths_dynamic_resolution():
    """DEFAULT_VIDEO_PATHS が環境変数 PROJECT_ROOT や os.path.exists に従って動的に解決されることを検証"""
    import os
    import importlib
    from unittest.mock import patch
    
    test_root = r"C:\Temp\dummy-project-root-for-test"
    with patch.dict(os.environ, {"PROJECT_ROOT": test_root}):
        import _e2e_cycle3 as e2e_module
        importlib.reload(e2e_module)
        
        expected_path = os.path.join(test_root, "vault-assets", "raw_videos", "本番RAW01 対談_山田", "シーン01_前編.mp4")
        assert e2e_module.DEFAULT_VIDEO_PATHS[0] == expected_path
        
    # 元の状態に戻すために reload する
    importlib.reload(e2e_module)


def test_monitor_pipeline_immediate_first_check_and_timeout():
    """monitor_pipeline が最初のチェックを即座に行い、タイムアウト判定の後に sleep することを確認"""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "status": "running",
        "stages": []
    }).encode("utf-8")
    
    sim = TimeSimulator()
    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen, \
         patch("time.sleep", side_effect=sim.sleep) as mock_sleep, \
         patch("time.monotonic", side_effect=sim.get_time):
        
        result = e2e.monitor_pipeline(timeout=5)
        
        assert result is None
        assert mock_urlopen.call_count >= 1


def test_e2e_cycle3_module_location():
    """_e2e_cycle3.py が直下の tests ディレクトリに正しく配置されインポートされていることを検証"""
    import _e2e_cycle3 as e2e_module
    import os
    expected_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "_e2e_cycle3.py"))
    actual_path = os.path.abspath(e2e_module.__file__)
    assert actual_path == expected_path


