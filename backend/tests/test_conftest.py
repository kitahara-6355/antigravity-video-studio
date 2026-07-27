import sys
import os
import pytest
import importlib
from unittest.mock import MagicMock, patch

# sys.path に backend ディレクトリを追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.tests.conftest

def test_conftest_reload():
    """
    conftest.py のトップレベル初期化コード（Windows IOCP対策など）のカバレッジをカバーするために、
    カバレッジ測定中に明示的に reload するテスト。
    """
    # Windowsプラットフォームのモック化による分岐網羅
    with patch("sys.platform", "win32"), \
         patch("asyncio.set_event_loop_policy") as mock_set_policy:
        importlib.reload(backend.tests.conftest)
        mock_set_policy.assert_called_once()

    with patch("sys.platform", "linux"), \
         patch("asyncio.set_event_loop_policy") as mock_set_policy:
        importlib.reload(backend.tests.conftest)
        mock_set_policy.assert_not_called()


def test_app_fixture(app):
    """app フィクスチャのテスト"""
    from fastapi import FastAPI
    assert isinstance(app, FastAPI)


def test_client_fixture(client):
    """client フィクスチャのテスト"""
    from fastapi.testclient import TestClient
    assert isinstance(client, TestClient)


@pytest.mark.anyio
async def test_async_client_fixture(async_client):
    """async_client フィクスチャのテスト"""
    from httpx import AsyncClient
    assert isinstance(async_client, AsyncClient)


def test_mock_gemini_fixture(mock_gemini):
    """mock_gemini フィクスチャのテスト"""
    # google.genai.Client がパッチされ、mock_gemini が返されることを確認
    from google.genai import Client
    client_instance = Client()
    assert client_instance == mock_gemini
    
    # generate_content の動作テスト
    res = client_instance.models.generate_content("test query")
    assert res.text == "モックレスポンス"


def test_temp_cache_fixture(temp_cache):
    """temp_cache フィクスチャのテスト"""
    from cache_manager import MemoryCache
    assert isinstance(temp_cache, MemoryCache)
    assert temp_cache.max_size == 100
    assert temp_cache.default_ttl == 60


def test_temp_token_manager_fixture(temp_token_manager):
    """temp_token_manager フィクスチャのテスト"""
    from websocket_handler import TokenManager
    assert isinstance(temp_token_manager, TokenManager)


def test_sample_philosophy_fixture(sample_philosophy):
    """sample_philosophy フィクスチャのテスト"""
    assert isinstance(sample_philosophy, dict)
    assert "content" in sample_philosophy
    assert sample_philosophy["source"] == "test"


def test_sample_approval_request_fixture(sample_approval_request):
    """sample_approval_request フィクスチャのテスト"""
    assert isinstance(sample_approval_request, dict)
    assert sample_approval_request["approved"] is True


def test_sample_error_report_fixture(sample_error_report):
    """sample_error_report フィクスチャのテスト"""
    assert isinstance(sample_error_report, dict)
    assert sample_error_report["error_type"] == "test_error"


def test_reset_singletons_fixture():
    """reset_singletons フィクスチャの動作テスト"""
    from cache_manager import dispatch_cache, api_cache
    
    # ダミーデータをセット
    dispatch_cache.set("key1", "val1")
    api_cache.set("key2", "val2")
    
    # ジェネレータフィクスチャを直接実行してクリーンアップを確認 (__wrapped__ を経由)
    gen = backend.tests.conftest.reset_singletons.__wrapped__()
    next(gen)  # yield まで実行
    try:
        next(gen)  # yield 降のクリーンアップ実行
    except StopIteration:
        pass
        
    assert dispatch_cache.get("key1") is None
    assert api_cache.get("key2") is None


def test_pytest_configure():
    """pytest_configure のテスト"""
    mock_config = MagicMock()
    backend.tests.conftest.pytest_configure(mock_config)
    
    # markersが登録されたことを検証
    assert mock_config.addinivalue_line.call_count >= 8
    calls = [call[0][1] for call in mock_config.addinivalue_line.call_args_list]
    assert any("slow" in c for c in calls)
    assert any("integration" in c for c in calls)
    assert any("fv" in c for c in calls)


def test_pytest_collection_modifyitems():
    """pytest_collection_modifyitems のテスト"""
    # 1. runslow = False の場合 (slowマークがついたテストがスキップされる)
    mock_config = MagicMock()
    mock_config.getoption.return_value = False
    
    mock_item_slow = MagicMock()
    mock_item_slow.keywords = {"slow": True}
    
    mock_item_normal = MagicMock()
    mock_item_normal.keywords = {}
    
    items = [mock_item_slow, mock_item_normal]
    backend.tests.conftest.pytest_collection_modifyitems(mock_config, items)
    
    # slowマークのアイテムにadd_markerが呼ばれたか確認
    mock_item_slow.add_marker.assert_called_once()
    mock_item_normal.add_marker.assert_not_called()

    # 2. runslow = True の場合 (slowマークがついていてもスキップされないが、add_markerは条件Falseで呼ばれる)
    mock_config_runslow = MagicMock()
    mock_config_runslow.getoption.return_value = True
    
    mock_item_slow_run = MagicMock()
    mock_item_slow_run.keywords = {"slow": True}
    
    items_run = [mock_item_slow_run]
    backend.tests.conftest.pytest_collection_modifyitems(mock_config_runslow, items_run)
    mock_item_slow_run.add_marker.assert_called_once()
    called_args = mock_item_slow_run.add_marker.call_args[0][0]
    assert called_args.mark.args[0] is False  # skipif の第1引数が False であること


def test_mock_contexts(
    mock_ctx, mock_ctx_empty, mock_ctx_minimal, mock_ctx_large,
    mock_ctx_corrupt, mock_ctx_type_error, mock_ctx_long
):
    """mock_ctx 関連のフィクスチャのテスト"""
    assert len(mock_ctx.segments) == 10
    assert len(mock_ctx_empty.segments) == 0
    assert len(mock_ctx_minimal.segments) == 1
    assert len(mock_ctx_large.segments) == 50
    assert len(mock_ctx_long.segments) == 100
    
    # 破損・型エラーの検証
    assert mock_ctx_corrupt is not None
    assert mock_ctx_type_error is not None


def test_tv01_path_fixture_not_exists():
    """tv01_path フィクスチャのテスト (ファイルが存在しない場合)"""
    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(pytest.skip.Exception):
            backend.tests.conftest.tv01_path.__wrapped__()


def test_tv01_path_fixture_exists():
    """tv01_path フィクスチャのテスト (ファイルが存在する場合)"""
    with patch("pathlib.Path.exists", return_value=True):
        res = backend.tests.conftest.tv01_path.__wrapped__()
        assert isinstance(res, str)
        assert "tv01_real_clip.mp4" in res


def test_safe_popen_mock_fixture(safe_popen_mock):
    """safe_popen_mock フィクスチャのテスト"""
    proc = safe_popen_mock(returncode=0, stderr_text="no error", stdout_text="output")
    assert proc.poll() == 0
    assert proc.returncode == 0
    assert proc.wait() is None
    assert proc.stderr.readline() == "no error"
    assert proc.stderr.read() == "no error"
    assert proc.stdout.readline() == "output"
    assert proc.stdout.read() == "output"
    assert proc.kill() is None
    assert proc.terminate() is None
