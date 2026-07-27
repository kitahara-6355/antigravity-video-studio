import os
import sys
import shutil
import subprocess
import ctypes
import pytest
from unittest.mock import MagicMock, patch

from backend.services.preflight_validator import (
    PreflightValidator,
    WindowsPreflightHandler,
    AndroidPreflightHandler,
    iOSPreflightHandler,
    BasePreflightHandler
)


# ============================================================
# BasePreflightHandler の未実装確認
# ============================================================
def test_base_preflight_handler_raises_not_implemented():
    handler = BasePreflightHandler()
    with pytest.raises(NotImplementedError):
        handler.check_ffmpeg_dependency()
    with pytest.raises(NotImplementedError):
        handler.check_disk_space(10.0)
    with pytest.raises(NotImplementedError):
        handler.check_workspace_connection(None)
    with pytest.raises(NotImplementedError):
        handler.check_ai_studio_connection()


# ============================================================
# WindowsPreflightHandler テスト
# ============================================================
def test_windows_resolve_ffmpeg_path_meipass():
    handler = WindowsPreflightHandler()
    with patch("sys.platform", "win32"), \
         patch("os.path.exists", return_value=True):
        sys._MEIPASS = "dummy_meipass"
        try:
            path = handler._resolve_ffmpeg_path()
            assert "dummy_meipass" in path
        finally:
            delattr(sys, "_MEIPASS")


def test_windows_resolve_ffmpeg_path_local_bin():
    handler = WindowsPreflightHandler()
    def mock_exists(path):
        return "bin" in path and "ffmpeg.exe" in path
    with patch("os.path.exists", side_effect=mock_exists):
        path = handler._resolve_ffmpeg_path()
        assert "bin" in path


def test_windows_resolve_ffmpeg_path_env_path():
    handler = WindowsPreflightHandler()
    with patch("os.path.exists", return_value=False), \
         patch("shutil.which", return_value="C:\\env_ffmpeg\\ffmpeg.exe"):
        path = handler._resolve_ffmpeg_path()
        assert path == "C:\\env_ffmpeg\\ffmpeg.exe"


def test_windows_resolve_ffmpeg_path_fallback():
    handler = WindowsPreflightHandler()
    with patch("os.path.exists", return_value=False), \
         patch("shutil.which", return_value=None):
        path = handler._resolve_ffmpeg_path()
        assert path == "ffmpeg"


def test_windows_check_ffmpeg_success():
    handler = WindowsPreflightHandler()
    mock_run = MagicMock()
    mock_run.returncode = 0
    with patch("subprocess.run", return_value=mock_run):
        assert handler.check_ffmpeg_dependency() is True


def test_windows_check_ffmpeg_failure():
    handler = WindowsPreflightHandler()
    mock_run = MagicMock()
    mock_run.returncode = 1
    with patch("subprocess.run", return_value=mock_run):
        assert handler.check_ffmpeg_dependency() is False


def test_windows_check_ffmpeg_exception():
    handler = WindowsPreflightHandler()
    with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
        assert handler.check_ffmpeg_dependency() is False


def test_windows_check_ffmpeg_timeout():
    handler = WindowsPreflightHandler()
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["ffmpeg", "-version"], 5)):
        assert handler.check_ffmpeg_dependency() is False


def test_windows_check_ffmpeg_unexpected_exception():
    handler = WindowsPreflightHandler()
    with patch("subprocess.run", side_effect=RuntimeError("unexpected error")):
        assert handler.check_ffmpeg_dependency() is False



def test_windows_check_disk_space_success():
    handler = WindowsPreflightHandler(target_dir="dummy")
    # 20 GB free
    with patch("shutil.disk_usage", return_value=(100 * 1024**3, 80 * 1024**3, 20 * 1024**3)):
        assert handler.check_disk_space(10.0) is True


def test_windows_check_disk_space_insufficient():
    handler = WindowsPreflightHandler(target_dir="dummy")
    # 5 GB free
    with patch("shutil.disk_usage", return_value=(100 * 1024**3, 95 * 1024**3, 5 * 1024**3)):
        assert handler.check_disk_space(10.0) is False


def test_windows_check_disk_space_exception():
    handler = WindowsPreflightHandler(target_dir="dummy")
    with patch("shutil.disk_usage", side_effect=PermissionError("permission denied")):
        assert handler.check_disk_space(10.0) is False


def test_windows_check_workspace_connection_none_store():
    handler = WindowsPreflightHandler()
    assert handler.check_workspace_connection(None) is False


def test_windows_check_workspace_connection_success():
    handler = WindowsPreflightHandler()
    mock_store = MagicMock()
    mock_store.list_input_raw_videos.return_value = ["video1.mp4"]
    assert handler.check_workspace_connection(mock_store) is True


def test_windows_check_workspace_connection_exception():
    handler = WindowsPreflightHandler()
    mock_store = MagicMock()
    mock_store.list_input_raw_videos.side_effect = ConnectionError("timeout")
    assert handler.check_workspace_connection(mock_store) is False


def test_windows_check_ai_studio_connection_success():
    handler = WindowsPreflightHandler()
    mock_conn = MagicMock()
    mock_conn.getcode.return_value = 200
    mock_conn.__enter__.return_value = mock_conn
    with patch("urllib.request.urlopen", return_value=mock_conn):
        assert handler.check_ai_studio_connection() is True


def test_windows_check_ai_studio_connection_403_404():
    handler = WindowsPreflightHandler()
    mock_conn = MagicMock()
    mock_conn.getcode.return_value = 403
    mock_conn.__enter__.return_value = mock_conn
    with patch("urllib.request.urlopen", return_value=mock_conn):
        assert handler.check_ai_studio_connection() is True


def test_windows_check_ai_studio_connection_exception():
    handler = WindowsPreflightHandler()
    with patch("urllib.request.urlopen", side_effect=TimeoutError("timeout")):
        assert handler.check_ai_studio_connection() is False


# ============================================================
# AndroidPreflightHandler テスト
# ============================================================
def test_android_resolve_ffmpeg_path_exists():
    handler = AndroidPreflightHandler(files_dir="dummy_dir")
    def mock_exists(path):
        return "dummy_dir" in path and "ffmpeg" in path
    with patch("os.path.exists", side_effect=mock_exists):
        path = handler._resolve_ffmpeg_path()
        assert path == os.path.join("dummy_dir", "ffmpeg")


def test_android_resolve_ffmpeg_path_fallback_which():
    handler = AndroidPreflightHandler(files_dir="dummy_dir")
    with patch("os.path.exists", return_value=False), \
         patch("shutil.which", return_value="/system/bin/ffmpeg"):
        path = handler._resolve_ffmpeg_path()
        assert path == "/system/bin/ffmpeg"


def test_android_resolve_ffmpeg_path_fallback_default():
    handler = AndroidPreflightHandler(files_dir="dummy_dir")
    with patch("os.path.exists", return_value=False), \
         patch("shutil.which", return_value=None):
        path = handler._resolve_ffmpeg_path()
        assert path == "ffmpeg"


def test_android_check_ffmpeg_success():
    handler = AndroidPreflightHandler()
    mock_run = MagicMock()
    mock_run.returncode = 0
    with patch("subprocess.run", return_value=mock_run):
        assert handler.check_ffmpeg_dependency() is True


def test_android_check_ffmpeg_exception():
    handler = AndroidPreflightHandler()
    with patch("subprocess.run", side_effect=Exception("error")):
        assert handler.check_ffmpeg_dependency() is False


def test_android_check_disk_space_success():
    handler = AndroidPreflightHandler(files_dir="dummy_dir")
    with patch("os.makedirs") as mock_makedirs, \
         patch("shutil.disk_usage", return_value=(10 * 1024**3, 5 * 1024**3, 5 * 1024**3)):
        assert handler.check_disk_space(1.0) is True
        mock_makedirs.assert_called_once()


def test_android_check_disk_space_exception():
    handler = AndroidPreflightHandler(files_dir="dummy_dir")
    with patch("os.makedirs"), \
         patch("shutil.disk_usage", side_effect=Exception("error")):
        assert handler.check_disk_space(1.0) is False


def test_android_check_workspace_connection():
    handler = AndroidPreflightHandler()
    assert handler.check_workspace_connection(None) is False
    mock_store = MagicMock()
    mock_store.list_input_raw_videos.return_value = []
    assert handler.check_workspace_connection(mock_store) is True
    mock_store.list_input_raw_videos.side_effect = Exception("error")
    assert handler.check_workspace_connection(mock_store) is False


def test_android_check_ai_studio_connection():
    handler = AndroidPreflightHandler()
    mock_conn = MagicMock()
    mock_conn.getcode.return_value = 200
    mock_conn.__enter__.return_value = mock_conn
    with patch("urllib.request.urlopen", return_value=mock_conn):
        assert handler.check_ai_studio_connection() is True
    with patch("urllib.request.urlopen", side_effect=Exception("error")):
        assert handler.check_ai_studio_connection() is False


# ============================================================
# iOSPreflightHandler テスト
# ============================================================
def test_ios_check_ffmpeg_success():
    handler = iOSPreflightHandler()
    # libavcodec.dylib などのロードが成功したとシミュレート
    with patch("ctypes.CDLL", return_value=MagicMock()):
        assert handler.check_ffmpeg_dependency() is True


def test_ios_check_ffmpeg_all_failed():
    handler = iOSPreflightHandler()
    with patch("ctypes.CDLL", side_effect=OSError("not found")):
        assert handler.check_ffmpeg_dependency() is False


def test_ios_check_disk_space_success():
    handler = iOSPreflightHandler(doc_dir="dummy_doc")
    with patch("os.makedirs"), \
         patch("shutil.disk_usage", return_value=(10 * 1024**3, 9 * 1024**3, 1 * 1024**3)):
        assert handler.check_disk_space(0.5) is True


def test_ios_check_disk_space_exception():
    handler = iOSPreflightHandler(doc_dir="dummy_doc")
    with patch("os.makedirs"), \
         patch("shutil.disk_usage", side_effect=Exception("error")):
        assert handler.check_disk_space(0.5) is False


def test_ios_check_workspace_connection():
    handler = iOSPreflightHandler()
    assert handler.check_workspace_connection(None) is False
    mock_store = MagicMock()
    mock_store.list_input_raw_videos.return_value = []
    assert handler.check_workspace_connection(mock_store) is True
    mock_store.list_input_raw_videos.side_effect = Exception("error")
    assert handler.check_workspace_connection(mock_store) is False


def test_ios_check_ai_studio_connection():
    handler = iOSPreflightHandler()
    mock_conn = MagicMock()
    mock_conn.getcode.return_value = 200
    mock_conn.__enter__.return_value = mock_conn
    with patch("urllib.request.urlopen", return_value=mock_conn):
        assert handler.check_ai_studio_connection() is True
    with patch("urllib.request.urlopen", side_effect=Exception("error")):
        assert handler.check_ai_studio_connection() is False


# ============================================================
# PreflightValidator テスト
# ============================================================
def test_preflight_validator_handler_selection_windows():
    with patch("sys.platform", "win32"):
        validator = PreflightValidator()
        assert isinstance(validator.handler, WindowsPreflightHandler)


def test_preflight_validator_handler_selection_android():
    with patch("sys.platform", "linux"), \
         patch.dict(os.environ, {"ANDROID_ARGUMENT": "dummy"}):
        validator = PreflightValidator()
        assert isinstance(validator.handler, AndroidPreflightHandler)


def test_preflight_validator_handler_selection_ios():
    with patch("sys.platform", "darwin"):
        validator = PreflightValidator(platform_name="darwin")
        assert isinstance(validator.handler, iOSPreflightHandler)
        
        validator2 = PreflightValidator(platform_name="ios_simulator")
        assert isinstance(validator2.handler, iOSPreflightHandler)


def test_preflight_validator_handler_selection_fallback():
    # darwinやwin32やandroid以外の未知のOS
    with patch("sys.platform", "unknown_os"):
        validator = PreflightValidator()
        assert isinstance(validator.handler, WindowsPreflightHandler)


def test_validate_all_all_passed():
    # すべて合格する場合
    validator = PreflightValidator(platform_name="win32")
    with patch.object(validator.handler, "check_ffmpeg_dependency", return_value=True), \
         patch.object(validator.handler, "check_disk_space", return_value=True), \
         patch.object(validator.handler, "check_workspace_connection", return_value=True), \
         patch.object(validator.handler, "check_ai_studio_connection", return_value=True):
        res = validator.validate_all()
        assert all(res.values())


def test_validate_all_insufficient_disk_defaults():
    # ディスク閾値のプラットフォーム別デフォルトチェック
    # windows -> 10.0 GB
    validator_win = PreflightValidator(platform_name="win32")
    mock_disk_win = MagicMock(return_value=True)
    with patch.object(validator_win.handler, "check_ffmpeg_dependency", return_value=True), \
         patch.object(validator_win.handler, "check_disk_space", mock_disk_win) as mock_win, \
         patch.object(validator_win.handler, "check_workspace_connection", return_value=True), \
         patch.object(validator_win.handler, "check_ai_studio_connection", return_value=True):
        validator_win.validate_all()
        mock_win.assert_called_once_with(10.0)

    # android -> 0.5 GB
    validator_android = PreflightValidator(platform_name="android")
    mock_disk_android = MagicMock(return_value=True)
    with patch.object(validator_android.handler, "check_ffmpeg_dependency", return_value=True), \
         patch.object(validator_android.handler, "check_disk_space", mock_disk_android) as mock_and, \
         patch.object(validator_android.handler, "check_workspace_connection", return_value=True), \
         patch.object(validator_android.handler, "check_ai_studio_connection", return_value=True):
        validator_android.validate_all()
        mock_and.assert_called_once_with(0.5)


def test_validate_all_register_tdr():
    # 不適合があり、TDRに自動登録されるテスト
    # HAS_TDR = True を前提に、TechnicalDebtStoreのモック化を確認
    validator = PreflightValidator(platform_name="win32")
    mock_store_instance = MagicMock()
    
    with patch.object(validator.handler, "check_ffmpeg_dependency", return_value=False), \
         patch.object(validator.handler, "check_disk_space", return_value=True), \
         patch.object(validator.handler, "check_workspace_connection", return_value=True), \
         patch.object(validator.handler, "check_ai_studio_connection", return_value=True), \
         patch("backend.services.preflight_validator.HAS_TDR", True), \
         patch("backend.services.preflight_validator.TechnicalDebtStore", return_value=mock_store_instance):
        
        res = validator.validate_all()
        assert res["ffmpeg"] is False
        mock_store_instance.register_debt.assert_called_once()
        args, kwargs = mock_store_instance.register_debt.call_args
        assert kwargs["category"] == "IMPORTANT_SERVICE"
        assert "ffmpeg" in kwargs["notes"]


def test_validate_all_register_tdr_exception():
    # TDR登録時に例外が発生した場合のセーフハンドリング
    validator = PreflightValidator(platform_name="win32")
    mock_store_instance = MagicMock()
    mock_store_instance.register_debt.side_effect = Exception("db write error")
    
    with patch.object(validator.handler, "check_ffmpeg_dependency", return_value=False), \
         patch.object(validator.handler, "check_disk_space", return_value=True), \
         patch.object(validator.handler, "check_workspace_connection", return_value=True), \
         patch.object(validator.handler, "check_ai_studio_connection", return_value=True), \
         patch("backend.services.preflight_validator.HAS_TDR", True), \
         patch("backend.services.preflight_validator.TechnicalDebtStore", return_value=mock_store_instance):
        
        res = validator.validate_all()
        assert res["ffmpeg"] is False
        # 例外がログ出力され、上位へ伝播しないことを検証


def test_preflight_validator_no_tdr_import():
    # TechnicalDebtStore がインポートできない場合の挙動をテスト
    # sys.modules から一時的に削除してモジュールをリロードする
    import importlib
    import sys
    
    # 元の状態を退避
    orig_modules = sys.modules.copy()
    
    # 依存を削除
    if "backend.agents.memory.technical_debt" in sys.modules:
        del sys.modules["backend.agents.memory.technical_debt"]
    
    # sys.modules に None を設定することで ImportError を誘発させます。
    sys.modules["backend.agents.memory.technical_debt"] = None
    
    try:
        # モジュールを再ロードして HAS_TDR が False になることを確認
        import backend.services.preflight_validator
        importlib.reload(backend.services.preflight_validator)
        assert backend.services.preflight_validator.HAS_TDR is False
        
        # 実際に validate_all を実行して TDR 登録処理がスキップされてもクラッシュしないか検証
        validator = backend.services.preflight_validator.PreflightValidator(platform_name="win32")
        with patch.object(validator.handler, "check_ffmpeg_dependency", return_value=False), \
             patch.object(validator.handler, "check_disk_space", return_value=True), \
             patch.object(validator.handler, "check_workspace_connection", return_value=True), \
             patch.object(validator.handler, "check_ai_studio_connection", return_value=True):
            res = validator.validate_all()
            assert res["ffmpeg"] is False # TDR が無いがエラーにならず終了する
            
    finally:
        # sys.modules を復元し、モジュールを再度リロードして正常な状態に戻す
        sys.modules.clear()
        sys.modules.update(orig_modules)
        import backend.services.preflight_validator
        importlib.reload(backend.services.preflight_validator)

