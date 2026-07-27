"""
API-UI整合性チェック (_check_api_ui.py) のユニットテスト
"""
import pytest
from unittest.mock import patch, AsyncMock
import sys
import runpy
from pathlib import Path

# アライメントスクリプトの親ディレクトリをインポートパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

# 依存先である template_config のインポートエラーを回避するためのパッチ
try:
    import template_config
    import template_constants
    if not hasattr(template_config, "PRODUCTION_TEMPLATES"):
        template_config.PRODUCTION_TEMPLATES = template_constants.PRODUCTION_TEMPLATES
    if not hasattr(template_config, "MOOD_THEMES"):
        template_config.MOOD_THEMES = template_constants.MOOD_THEMES
    if not hasattr(template_config, "RECOMMENDED_COMBOS"):
        template_config.RECOMMENDED_COMBOS = template_constants.RECOMMENDED_COMBOS
except Exception:
    pass

import _check_api_ui

@pytest.mark.asyncio
async def test_check_all_ok(capsys):
    """すべての整合性チェックがOKになるケース"""
    premium = _check_api_ui.PREMIUM_MODEL
    standard = _check_api_ui.STANDARD_MODEL
    batch = _check_api_ui.BATCH_MODEL

    mock_response = {
        "tiers": {
            "premium": {"model": premium, "label": "Premium"},
            "standard": {"model": standard, "label": "Standard"},
            "batch": {"model": batch, "label": "Batch"}
        },
        "usage": {
            "models": {
                premium: {"used": 10, "limit": 100, "usage_ratio": 0.1},
                standard: {"used": 20, "limit": 100, "usage_ratio": 0.2},
                batch: {"used": 30, "limit": 100, "usage_ratio": 0.3}
            }
        },
        "fallback_chain": {
            premium: standard,
            standard: batch,
            batch: None
        }
    }
    
    with patch("_check_api_ui.get_governance_status", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        await _check_api_ui.check()
        
    captured = capsys.readouterr()
    assert "RESULT: 16/16 passed" in captured.out


@pytest.mark.asyncio
async def test_check_ng(capsys):
    """一部の整合性チェックがNGになるケース"""
    premium = _check_api_ui.PREMIUM_MODEL
    standard = _check_api_ui.STANDARD_MODEL
    batch = _check_api_ui.BATCH_MODEL

    mock_response = {
        "tiers": {
            "premium": {"model": premium, "label": "Premium"},
        },
        "usage": {
            "models": {
                premium: {"used": 10, "limit": 100, "usage_ratio": 0.1},
            }
        },
        "fallback_chain": {}
    }
    
    with patch("_check_api_ui.get_governance_status", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        await _check_api_ui.check()
        
    captured = capsys.readouterr()
    assert "RESULT: " in captured.out
    assert "16/16 passed" not in captured.out


def test_main_execution(capsys):
    """__main__ブロック実行のテスト"""
    premium = _check_api_ui.PREMIUM_MODEL
    standard = _check_api_ui.STANDARD_MODEL
    batch = _check_api_ui.BATCH_MODEL

    mock_response = {
        "tiers": {
            "premium": {"model": premium, "label": "Premium"},
            "standard": {"model": standard, "label": "Standard"},
            "batch": {"model": batch, "label": "Batch"}
        },
        "usage": {
            "models": {
                premium: {"used": 10, "limit": 100, "usage_ratio": 0.1},
                standard: {"used": 20, "limit": 100, "usage_ratio": 0.2},
                batch: {"used": 30, "limit": 100, "usage_ratio": 0.3}
            }
        },
        "fallback_chain": {
            premium: standard,
            standard: batch,
            batch: None
        }
    }
    
    script_path = Path(__file__).parent / "_check_api_ui.py"
    
    # coroutine 'check' was never awaited 警告を防ぐために close() を呼び出す
    def mock_run_side_effect(coro):
        coro.close()
    
    with patch("_check_api_ui.get_governance_status", new_callable=AsyncMock) as mock_get,          patch("asyncio.run", side_effect=mock_run_side_effect) as mock_run:
        mock_get.return_value = mock_response
        runpy.run_path(str(script_path), run_name="__main__")
        mock_run.assert_called_once()


def test_imported_constants():
    """model_config.json からインポートされた定数が定義されていることの検証"""
    assert hasattr(_check_api_ui, "PREMIUM_MODEL")
    assert hasattr(_check_api_ui, "STANDARD_MODEL")
    assert hasattr(_check_api_ui, "BATCH_MODEL")
    assert _check_api_ui.PREMIUM_MODEL is not None


def test_model_config_fallback():
    '''model_config.json が空、または tiers が定義されていない場合のフォールバック値の検証'''
    import importlib
    from unittest.mock import patch, mock_open
    
    m_open = mock_open(read_data="{}")
    with patch("builtins.open", m_open):
        importlib.reload(_check_api_ui)
        assert _check_api_ui.PREMIUM_MODEL == "gemini-3-flash-preview"
        assert _check_api_ui.STANDARD_MODEL == "gemini-2.5-flash"
        assert _check_api_ui.BATCH_MODEL == "gemini-2.5-flash-lite"
        
    # テスト後に元の状態に逆戻り
    importlib.reload(_check_api_ui)


@pytest.mark.asyncio
async def test_check_exception(capsys):
    """get_governance_status が例外を投げた場合の挙動"""
    with patch("_check_api_ui.get_governance_status", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = RuntimeError("Status fetch failed")
        # 例外は内部でキャッチされ警告が発生することを確認
        with pytest.warns(RuntimeWarning, match="Failed to fetch governance status"):
            success = await _check_api_ui.check()
            assert success is False
        
        captured = capsys.readouterr()
        assert "RESULT: " in captured.out
        assert "16/16 passed" not in captured.out


def test_model_config_invalid_json():
    """model_config.json が不正なJSONの場合にデフォルト値にフォールバックし警告が発生することの検証"""
    import importlib
    from unittest.mock import patch, mock_open
    
    m_open = mock_open(read_data="{invalid json}")
    with patch("builtins.open", m_open):
        with pytest.warns(RuntimeWarning, match="Failed to load model config"):
            importlib.reload(_check_api_ui)
            
        assert _check_api_ui.PREMIUM_MODEL == "gemini-3-flash-preview"
        assert _check_api_ui.STANDARD_MODEL == "gemini-2.5-flash"
        assert _check_api_ui.BATCH_MODEL == "gemini-2.5-flash-lite"
            
    # 元の状態に戻す
    importlib.reload(_check_api_ui)


@pytest.mark.asyncio
async def test_check_invalid_data_structure(capsys):
    """get_governance_status がNoneや想定外の構造を返した場合の挙動"""
    with patch("_check_api_ui.get_governance_status", new_callable=AsyncMock) as mock_get:
        # tiersキーがNoneの場合
        mock_get.return_value = {"tiers": None}
        success = await _check_api_ui.check()
        assert success is False
        
        captured = capsys.readouterr()
        assert "RESULT: " in captured.out
        assert "16/16 passed" not in captured.out


def test_model_config_invalid_structure():
    """model_config.json 内のキー構造が辞書ではない（Noneなど）場合にデフォルト値にフォールバックすることの検証"""
    import importlib
    from unittest.mock import patch, mock_open
    
    m_open = mock_open(read_data='{"text_generation": null}')
    with patch("builtins.open", m_open):
        importlib.reload(_check_api_ui)
        assert _check_api_ui.PREMIUM_MODEL == "gemini-3-flash-preview"
        assert _check_api_ui.STANDARD_MODEL == "gemini-2.5-flash"
        assert _check_api_ui.BATCH_MODEL == "gemini-2.5-flash-lite"
            
    # 元の状態に戻す
    importlib.reload(_check_api_ui)


def test_model_config_file_not_found():
    """model_config.json が存在しない場合にデフォルト値にフォールバックし警告が発生することの検証"""
    import importlib
    from unittest.mock import patch
    
    with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
        with pytest.warns(RuntimeWarning, match="Failed to load model config"):
            importlib.reload(_check_api_ui)
            
        assert _check_api_ui.PREMIUM_MODEL == "gemini-3-flash-preview"
        assert _check_api_ui.STANDARD_MODEL == "gemini-2.5-flash"
        assert _check_api_ui.BATCH_MODEL == "gemini-2.5-flash-lite"
        
    # 元の状態に戻す
    importlib.reload(_check_api_ui)


def test_model_config_permission_error():
    """model_config.json の読み取り権限がない場合にデフォルト値にフォールバックし警告が発生することの検証"""
    import importlib
    from unittest.mock import patch
    
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with pytest.warns(RuntimeWarning, match="Failed to load model config"):
            importlib.reload(_check_api_ui)
            
        assert _check_api_ui.PREMIUM_MODEL == "gemini-3-flash-preview"
        assert _check_api_ui.STANDARD_MODEL == "gemini-2.5-flash"
        assert _check_api_ui.BATCH_MODEL == "gemini-2.5-flash-lite"
        
    # 元の状態に戻す
    importlib.reload(_check_api_ui)


def test_model_config_not_dict():
    """model_config.json の内容が辞書ではない場合（リスト等）にデフォルト値にフォールバックすることの検証"""
    import importlib
    from unittest.mock import patch, mock_open
    
    m_open = mock_open(read_data='[]')
    with patch("builtins.open", m_open):
        importlib.reload(_check_api_ui)
        assert _check_api_ui.PREMIUM_MODEL == "gemini-3-flash-preview"
        assert _check_api_ui.STANDARD_MODEL == "gemini-2.5-flash"
        assert _check_api_ui.BATCH_MODEL == "gemini-2.5-flash-lite"
        
    # 元の状態に戻す
    importlib.reload(_check_api_ui)


def test_model_config_tiers_not_dict():
    """model_config.json 内の tiers が辞書ではない場合（None等）にデフォルト値にフォールバックすることの検証"""
    import importlib
    from unittest.mock import patch, mock_open
    
    m_open = mock_open(read_data='{"text_generation": {"tiers": null}}')
    with patch("builtins.open", m_open):
        importlib.reload(_check_api_ui)
        assert _check_api_ui.PREMIUM_MODEL == "gemini-3-flash-preview"
        assert _check_api_ui.STANDARD_MODEL == "gemini-2.5-flash"
        assert _check_api_ui.BATCH_MODEL == "gemini-2.5-flash-lite"
        
    # 元の状態に戻す
    importlib.reload(_check_api_ui)


@pytest.mark.asyncio
async def test_check_result_not_dict(capsys):
    """get_governance_status が辞書ではない型を返した場合の挙動"""
    with patch("_check_api_ui.get_governance_status", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = "invalid response"
        with pytest.warns(RuntimeWarning, match="Governance status result is not a dict"):
            success = await _check_api_ui.check()
            assert success is False
        
        captured = capsys.readouterr()
        assert "RESULT: " in captured.out
        assert "16/16 passed" not in captured.out


def test_model_config_unexpected_exception():
    """model_config.json 読込時に想定外の例外が発生した場合に警告が発生し、デフォルト値にフォールバックすることの検証"""
    import importlib
    from unittest.mock import patch
    
    with patch("builtins.open", side_effect=RuntimeError("Unexpected OS/Disk error")):
        with pytest.warns(RuntimeWarning, match="Unexpected error loading model config"):
            importlib.reload(_check_api_ui)
            
        assert _check_api_ui.PREMIUM_MODEL == "gemini-3-flash-preview"
        assert _check_api_ui.STANDARD_MODEL == "gemini-2.5-flash"
        assert _check_api_ui.BATCH_MODEL == "gemini-2.5-flash-lite"
        
    # 元の状態に戻す
    importlib.reload(_check_api_ui)


def test_main_execution_exception(capsys):
    """__main__ブロック実行時に例外が発生した場合のハンドリング"""
    script_path = Path(__file__).parent / "_check_api_ui.py"
    
    def mock_run_side_effect(coro):
        coro.close()
        raise RuntimeError("Async run failed")
    
    with patch("asyncio.run", side_effect=mock_run_side_effect), \
         pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(script_path), run_name="__main__")
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Critical error during API-UI check: Async run failed" in captured.err

