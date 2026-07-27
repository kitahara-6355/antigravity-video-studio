"""
Harness テスト — pytest 設定

pytest-asyncio の自動モードを有効化し、
async def test_xxx() を自動的に非同期テストとして認識させる。
"""
import pytest


def pytest_collection_modifyitems(items):
    """
    async def test_xxx() 関数に自動で asyncio マークを付与。

    これにより @pytest.mark.asyncio デコレータなしでも
    async テストが正常に実行される。
    """
    import asyncio

    for item in items:
        if asyncio.iscoroutinefunction(item.function):
            item.add_marker(pytest.mark.asyncio)
