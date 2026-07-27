"""
API-UI整合性チェック (_check_api_ui_alignment.py) のユニットテスト
"""
import pytest
from unittest.mock import patch, AsyncMock
import sys
import runpy
from pathlib import Path

# アライメントスクリプトとその親ディレクトリをインポートパスに追加
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import _check_api_ui_alignment

@pytest.mark.asyncio
async def test_check_alignment_all_ok(capsys):
    """すべての整合性チェックがOKになるケース"""
    mock_response = {
        "tiers": {
            "premium": {"model": "gemini-3-flash-preview", "label": "Premium"},
            "standard": {"model": "gemini-2.5-flash", "label": "Standard"},
            "batch": {"model": "gemini-2.5-flash-lite", "label": "Batch"}
        },
        "usage": {
            "models": {
                "gemini-3-flash-preview": {"used": 10, "limit": 100, "usage_ratio": 0.1},
                "gemini-2.5-flash": {"used": 20, "limit": 100, "usage_ratio": 0.2},
                "gemini-2.5-flash-lite": {"used": 30, "limit": 100, "usage_ratio": 0.3}
            }
        },
        "fallback_chain": {
            "gemini-3-flash-preview": "gemini-2.5-flash",
            "gemini-2.5-flash": "gemini-2.5-flash-lite",
            "gemini-2.5-flash-lite": None
        }
    }
    
    with patch("_check_api_ui_alignment.get_governance_status", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        await _check_api_ui_alignment.check()
        
    captured = capsys.readouterr()
    assert "RESULT: ALL OK (16/16)" in captured.out


@pytest.mark.asyncio
async def test_check_alignment_ng(capsys):
    """整合性チェックで不整合（NG）が発生するケース"""
    mock_response = {
        "tiers": {
            "premium": {"model": "gemini-3-flash-preview", "label": "Premium"},
            "standard": {"model": "gemini-2.5-flash", "label": "Standard"},
            "batch": {"model": "gemini-2.5-flash-lite", "label": "Batch"}
        },
        "usage": {
            "models": {
                "gemini-3-flash-preview": {"used": 10, "limit": 100, "usage_ratio": 0.1},
                "gemini-2.5-flash": {"used": 20, "limit": 100, "usage_ratio": 0.2},
                "gemini-2.5-flash-lite": {"used": 30, "limit": 100, "usage_ratio": 0.3}
            }
        },
        "fallback_chain": {}  # 欠落
    }
    
    with patch("_check_api_ui_alignment.get_governance_status", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        await _check_api_ui_alignment.check()
        
    captured = capsys.readouterr()
    assert "RESULT: NG" in captured.out


def test_main_execution(capsys):
    """__main__ブロック実行のテスト"""
    mock_response = {
        "tiers": {
            "premium": {"model": "gemini-3-flash-preview", "label": "Premium"},
            "standard": {"model": "gemini-2.5-flash", "label": "Standard"},
            "batch": {"model": "gemini-2.5-flash-lite", "label": "Batch"}
        },
        "usage": {
            "models": {
                "gemini-3-flash-preview": {"used": 10, "limit": 100, "usage_ratio": 0.1},
                "gemini-2.5-flash": {"used": 20, "limit": 100, "usage_ratio": 0.2},
                "gemini-2.5-flash-lite": {"used": 30, "limit": 100, "usage_ratio": 0.3}
            }
        },
        "fallback_chain": {
            "gemini-3-flash-preview": "gemini-2.5-flash",
            "gemini-2.5-flash": "gemini-2.5-flash-lite",
            "gemini-2.5-flash-lite": None
        }
    }
    
    script_path = Path(__file__).parent / "_check_api_ui_alignment.py"
    
    # coroutine 'check' was never awaited 警告を防ぐために close() を呼び出す
    def mock_run_side_effect(coro):
        coro.close()
    
    with patch("_check_api_ui_alignment.get_governance_status", new_callable=AsyncMock) as mock_get, \
         patch("asyncio.run", side_effect=mock_run_side_effect) as mock_run:
        mock_get.return_value = mock_response
        # runpy でスクリプトを __main__ として実行
        runpy.run_path(str(script_path), run_name="__main__")
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_check_alignment_missing_tiers_and_usage(capsys):
    """tiers や usage が欠落している、あるいは空工程の場合のテスト"""
    mock_response = {
        "tiers": {},
        "usage": {},
        "fallback_chain": {}
    }
    
    with patch("_check_api_ui_alignment.get_governance_status", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        await _check_api_ui_alignment.check()
        
    captured = capsys.readouterr()
    assert "RESULT: NG" in captured.out


@pytest.mark.asyncio
async def test_check_alignment_result_not_dict(capsys):
    """get_governance_status が辞書ではない（None）を返す場合のテスト"""
    with patch("_check_api_ui_alignment.get_governance_status", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        await _check_api_ui_alignment.check()
        
    captured = capsys.readouterr()
    assert "RESULT: NG" in captured.out


def test_imported_constants():
    """model_config.json からインポートされた定数が定義されていることの検証"""
    assert hasattr(_check_api_ui_alignment, "PREMIUM_MODEL")
    assert hasattr(_check_api_ui_alignment, "STANDARD_MODEL")
    assert hasattr(_check_api_ui_alignment, "BATCH_MODEL")
    assert _check_api_ui_alignment.PREMIUM_MODEL is not None


def test_load_model_config_exceptions():
    """model_config.json の読込失敗時の例外処理とフォールバックのテスト"""
    import builtins
    import json
    
    # FileNotFoundError を発生させるケース
    with patch("builtins.open", side_effect=FileNotFoundError):
        config = _check_api_ui_alignment.load_model_config()
        assert config == {}
        
    # JSONDecodeError を発生させるケース
    with patch("builtins.open", side_effect=json.JSONDecodeError("mock msg", "mock doc", 0)):
        config = _check_api_ui_alignment.load_model_config()
        assert config == {}
        
    # PermissionError を発生させるケース
    with patch("builtins.open", side_effect=PermissionError):
        config = _check_api_ui_alignment.load_model_config()
        assert config == {}


def test_load_model_config_partial():
    """model_config.json の一部の設定が欠落している場合のフォールバックテスト"""
    import importlib
    import json
    import io
    import _check_api_ui_alignment
    from unittest.mock import patch
    
    partial_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "custom-premium"},
            }
        }
    }
    
    original_open = open
    def mock_open_fn(file, *args, **kwargs):
        if "model_config.json" in str(file):
            return io.StringIO(json.dumps(partial_config))
        return original_open(file, *args, **kwargs)
        
    with patch("builtins.open", side_effect=mock_open_fn):
        # モジュールをリロードして定数を再設定させる
        importlib.reload(_check_api_ui_alignment)
        
        assert _check_api_ui_alignment.PREMIUM_MODEL == "custom-premium"
        assert _check_api_ui_alignment.STANDARD_MODEL == "gemini-2.5-flash"  # デフォルト値
        assert _check_api_ui_alignment.BATCH_MODEL == "gemini-2.5-flash-lite"  # デフォルト値

    # テスト後に元の状態に戻すため、再度リロードしておく
    importlib.reload(_check_api_ui_alignment)


@pytest.mark.asyncio
async def test_check_alignment_get_status_exception(capsys):
    """get_governance_status が例外を投げた場合のエラーハンドリングテスト"""
    with patch("_check_api_ui_alignment.get_governance_status", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = RuntimeError("Simulated API Error")
        await _check_api_ui_alignment.check()
        
    captured = capsys.readouterr()
    assert "Error fetching governance data: Simulated API Error" in captured.err
    assert "RESULT: NG" in captured.out


def test_load_model_config_unexpected_exception(capsys):
    """load_model_config 内で想定外の例外が発生した場合のテスト"""
    with patch("builtins.open", side_effect=RuntimeError("Simulated OS/Disk Crash")):
        config = _check_api_ui_alignment.load_model_config()
        assert config == {}
        
    captured = capsys.readouterr()
    assert "Error: Unexpected error loading model config: Simulated OS/Disk Crash" in captured.err


def test_load_model_config_type_error(capsys):
    """load_model_config 内で TypeError が発生した場合のテスト"""
    with patch("builtins.open", side_effect=TypeError("Simulated Type Error")):
        config = _check_api_ui_alignment.load_model_config()
        assert config == {}
        
    captured = capsys.readouterr()
    assert "Error: Unexpected error loading model config: Simulated Type Error" in captured.err


@pytest.mark.asyncio
async def test_check_alignment_get_status_import_error(capsys):
    """get_governance_status が ImportError を投げた場合のエラーハンドリングテスト"""
    with patch("_check_api_ui_alignment.get_governance_status", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = ImportError("Simulated Import Error")
        await _check_api_ui_alignment.check()
        
    captured = capsys.readouterr()
    assert "Error fetching governance data: Simulated Import Error" in captured.err
    assert "RESULT: NG" in captured.out
