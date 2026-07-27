"""
backend/harness/conftest.py のテスト
"""
import pytest
import asyncio
from unittest.mock import MagicMock
from backend.harness.conftest import pytest_collection_modifyitems


def test_pytest_collection_modifyitems_async():
    """
    async def のテスト関数に対して pytest.mark.asyncio マークが自動で付与されることを検証
    """
    # 非同期モック関数の作成
    async def mock_async_func():
        pass

    # pytest Item のモックを作成し、function属性に非同期関数を設定
    mock_item = MagicMock()
    mock_item.function = mock_async_func

    # テスト対象関数の呼び出し
    pytest_collection_modifyitems([mock_item])

    # add_marker が pytest.mark.asyncio を引数に呼び出されたか検証
    mock_item.add_marker.assert_called_once_with(pytest.mark.asyncio)


def test_pytest_collection_modifyitems_sync():
    """
    通常の同期型テスト関数に対してはマークが付与されないことを検証
    """
    # 同期モック関数の作成
    def mock_sync_func():
        pass

    # pytest Item のモックを作成し、function属性に同期関数を設定
    mock_item = MagicMock()
    mock_item.function = mock_sync_func

    # テスト対象関数の呼び出し
    pytest_collection_modifyitems([mock_item])

    # add_marker が呼び出されていないことを検証
    mock_item.add_marker.assert_not_called()
