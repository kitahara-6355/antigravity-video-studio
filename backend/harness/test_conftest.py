"""backend/harness/conftest.py のユニットテスト"""
import pytest
from unittest.mock import MagicMock
import asyncio

from harness.conftest import pytest_collection_modifyitems

async def test_pytest_collection_modifyitems():
    # 非同期関数と同期関数のテスト用ダミーを作成
    async def dummy_async_func():
        pass

    def dummy_sync_func():
        pass

    # カバレッジのためにダミー関数を実行
    await dummy_async_func()
    dummy_sync_func()

    # ダミーの pytest Item オブジェクトを作成
    async_item = MagicMock()
    async_item.function = dummy_async_func

    sync_item = MagicMock()
    sync_item.function = dummy_sync_func

    # フックを実行
    items = [async_item, sync_item]
    pytest_collection_modifyitems(items)

    # 非同期テストに関数マーカーが追加されたか確認
    # item.add_marker(pytest.mark.asyncio) が呼び出されたか
    async_item.add_marker.assert_called_once_with(pytest.mark.asyncio)

    # 同期テストには追加されないことを確認
    sync_item.add_marker.assert_not_called()


async def test_pytest_collection_modifyitems_edge_cases():
    # 1. 空のアイテムリスト
    empty_items = []
    pytest_collection_modifyitems(empty_items)  # 例外が発生しないことを確認

    # 2. 複数の非同期・同期関数の混在
    async def async_1():
        pass

    async def async_2():
        pass

    def sync_1():
        pass

    def sync_2():
        pass

    await async_1()
    await async_2()
    sync_1()
    sync_2()

    item_async1 = MagicMock()
    item_async1.function = async_1
    item_async2 = MagicMock()
    item_async2.function = async_2
    item_sync1 = MagicMock()
    item_sync1.function = sync_1
    item_sync2 = MagicMock()
    item_sync2.function = sync_2

    mixed_items = [item_async1, item_sync1, item_async2, item_sync2]
    pytest_collection_modifyitems(mixed_items)

    item_async1.add_marker.assert_called_once_with(pytest.mark.asyncio)
    item_async2.add_marker.assert_called_once_with(pytest.mark.asyncio)
    item_sync1.add_marker.assert_not_called()
    item_sync2.add_marker.assert_not_called()

    # 3. 特殊な function 属性（None, 関数以外のオブジェクト, 非同期ジェネレータなど）
    async def async_gen():
        yield 1

    # カバレッジのために実行
    async for _ in async_gen():
        pass

    item_none = MagicMock()
    item_none.function = None

    item_not_callable = MagicMock()
    item_not_callable.function = "not_callable"

    item_async_gen = MagicMock()
    item_async_gen.function = async_gen

    edge_items = [item_none, item_not_callable, item_async_gen]

    # 例外がスローされず、かつ iscoroutinefunction が False であるため add_marker が呼ばれないこと
    pytest_collection_modifyitems(edge_items)

    item_none.add_marker.assert_not_called()
    item_not_callable.add_marker.assert_not_called()
    item_async_gen.add_marker.assert_not_called()
