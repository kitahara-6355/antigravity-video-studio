"""
E2E スモークテスト — Playwright 基盤動作確認

Phase 3 A-4: 最小限のテストで Playwright + pytest-playwright 統合を検証
"""

import pytest


@pytest.mark.e2e
class TestE2ESmoke:
    """Playwright 基盤の最小動作確認"""

    def test_playwright_import(self):
        """Playwright のインポートが成功すること"""
        from playwright.sync_api import sync_playwright
        assert sync_playwright is not None

    def test_browser_launch(self, browser):
        """pytest-playwright の browser fixture が動作すること"""
        assert browser is not None
        # ブラウザタイプを確認
        assert browser.browser_type.name == "chromium"

    def test_page_creation(self, page):
        """page fixture で新しいページが作成されること"""
        assert page is not None

    def test_page_navigation(self, page):
        """ローカルページへのナビゲーションが動作すること"""
        # data: URL でテスト（サーバー不要）
        page.goto("data:text/html,<h1>Playwright E2E Ready</h1>")
        heading = page.locator("h1")
        assert heading.text_content() == "Playwright E2E Ready"
