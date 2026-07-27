import sys
from pathlib import Path

# Add backend root to path
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from tests._screenshot_dashboard import capture_dashboard

@pytest.mark.asyncio
async def test_capture_dashboard_standard_flow(capsys):
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    # skip_btn mock
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(return_value=1)
    mock_skip_btn.click = AsyncMock()
    
    # ops_link mock
    mock_ops_link = MagicMock()
    mock_ops_link.count = AsyncMock(return_value=1)
    mock_ops_link.click = AsyncMock()

    # Control locator behavior
    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        elif "運用監視" in selector:
            mock_parent = MagicMock()
            mock_parent.first = mock_ops_link
            return mock_parent
        # UI check elements mock
        mock_ui_element = MagicMock()
        mock_ui_element.count = AsyncMock(return_value=1)
        return mock_ui_element

    mock_page.locator.side_effect = locator_side_effect

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        await capture_dashboard()

    # Assert standard workflow calls
    mock_chromium.launch.assert_called_once_with(headless=True)
    mock_browser.new_page.assert_called_once_with(viewport={"width": 1400, "height": 900})
    mock_page.goto.assert_called_once_with("http://localhost:5173/", wait_until="networkidle", timeout=15000)
    mock_skip_btn.click.assert_called_once_with(force=True)
    mock_ops_link.click.assert_called_once_with(force=True)

    # Assert specific screenshot paths and arguments
    assert mock_page.screenshot.call_count == 3
    calls = mock_page.screenshot.call_args_list
    assert "01_main_page.png" in calls[0].kwargs["path"]
    assert calls[0].kwargs["full_page"] is True
    assert "02_ops_dashboard_top.png" in calls[1].kwargs["path"]
    assert calls[1].kwargs["full_page"] is False
    assert "03_ops_dashboard_full.png" in calls[2].kwargs["path"]
    assert calls[2].kwargs["full_page"] is True

    mock_browser.close.assert_called_once()

    # Assert standard output messages
    captured = capsys.readouterr()
    assert "[1/4] メインページを開きます..." in captured.out
    assert "オンボーディング画面を検出 → スキップ" in captured.out
    assert "[2/4] 運用監視ページへ遷移..." in captured.out
    assert "[3/4] 全体スクリーンショット..." in captured.out
    assert "[4/4] UI要素チェック..." in captured.out

@pytest.mark.asyncio
async def test_capture_dashboard_fallback_flow(capsys):
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    # skip_btn mock (no onboarding screen)
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(return_value=0)
    
    # ops_link mock (no direct ops link)
    mock_ops_link = MagicMock()
    mock_ops_link.count = AsyncMock(return_value=0)

    # sidebar_links mock
    mock_sidebar_links = MagicMock()
    mock_sidebar_links.count = AsyncMock(return_value=2)
    
    mock_link_0 = MagicMock()
    mock_link_0.text_content = AsyncMock(return_value="  ホーム  ")
    mock_link_0.click = AsyncMock()
    
    mock_link_1 = MagicMock()
    mock_link_1.text_content = AsyncMock(return_value="  運用ダッシュボード  ")
    mock_link_1.click = AsyncMock()

    def nth_side_effect(index):
        if index == 0:
            return mock_link_0
        elif index == 1:
            return mock_link_1
        raise IndexError()
    mock_sidebar_links.nth = MagicMock(side_effect=nth_side_effect)

    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        elif "運用監視" in selector:
            mock_parent = MagicMock()
            mock_parent.first = mock_ops_link
            return mock_parent
        elif "nav a, .sidebar a" in selector:
            return mock_sidebar_links
        # UI check elements mock
        mock_ui_element = MagicMock()
        mock_ui_element.count = AsyncMock(return_value=0)
        return mock_ui_element

    mock_page.locator.side_effect = locator_side_effect

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        await capture_dashboard()

    # Assert fallback logic executed successfully
    mock_skip_btn.click.assert_not_called()
    mock_ops_link.click.assert_not_called()
    mock_link_0.click.assert_not_called()
    mock_link_1.click.assert_called_once_with(force=True)

    # Assert specific screenshot paths and arguments
    assert mock_page.screenshot.call_count == 3
    calls = mock_page.screenshot.call_args_list
    assert "01_main_page.png" in calls[0].kwargs["path"]
    assert calls[0].kwargs["full_page"] is True
    assert "02_ops_dashboard_top.png" in calls[1].kwargs["path"]
    assert calls[1].kwargs["full_page"] is False
    assert "03_ops_dashboard_full.png" in calls[2].kwargs["path"]
    assert calls[2].kwargs["full_page"] is True

    # Assert fallback workflow stdout
    captured = capsys.readouterr()
    assert "オンボーディング画面を検出" not in captured.out
    assert "サイドバーリンク数: 2" in captured.out

@pytest.mark.asyncio
async def test_capture_dashboard_fallback_no_match_flow():
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    # skip_btn mock
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(return_value=0)
    
    # ops_link mock
    mock_ops_link = MagicMock()
    mock_ops_link.count = AsyncMock(return_value=0)

    # sidebar_links mock (no matching labels)
    mock_sidebar_links = MagicMock()
    mock_sidebar_links.count = AsyncMock(return_value=1)
    
    mock_link_0 = MagicMock()
    mock_link_0.text_content = AsyncMock(return_value="ヘルプ")
    mock_link_0.click = AsyncMock()
    mock_sidebar_links.nth = MagicMock(return_value=mock_link_0)

    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        elif "運用監視" in selector:
            mock_parent = MagicMock()
            mock_parent.first = mock_ops_link
            return mock_parent
        elif "nav a, .sidebar a" in selector:
            return mock_sidebar_links
        # UI check elements mock
        mock_ui_element = MagicMock()
        mock_ui_element.count = AsyncMock(return_value=0)
        return mock_ui_element

    mock_page.locator.side_effect = locator_side_effect

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        await capture_dashboard()

    # Assert fallback logic with no match
    mock_skip_btn.click.assert_not_called()
    mock_ops_link.click.assert_not_called()
    mock_link_0.click.assert_not_called()

def test_main_execution():
    import runpy
    def mock_run_impl(coro):
        coro.close()
        return None

    with patch("tests._screenshot_dashboard.asyncio.run", side_effect=mock_run_impl) as mock_run:
        runpy.run_path(str(BACKEND_DIR / "tests" / "_screenshot_dashboard.py"), run_name="__main__")
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_capture_dashboard_sidebar_zero_links():
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    # skip_btn mock
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(return_value=0)
    
    # ops_link mock
    mock_ops_link = MagicMock()
    mock_ops_link.count = AsyncMock(return_value=0)

    # sidebar_links mock (0 links)
    mock_sidebar_links = MagicMock()
    mock_sidebar_links.count = AsyncMock(return_value=0)

    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        elif "運用監視" in selector:
            mock_parent = MagicMock()
            mock_parent.first = mock_ops_link
            return mock_parent
        elif "nav a, .sidebar a" in selector:
            return mock_sidebar_links
        # UI check elements mock
        mock_ui_element = MagicMock()
        mock_ui_element.count = AsyncMock(return_value=0)
        return mock_ui_element

    mock_page.locator.side_effect = locator_side_effect

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        await capture_dashboard()

    # Assert fallback logic with 0 sidebar links executed without crash
    mock_skip_btn.click.assert_not_called()
    mock_ops_link.click.assert_not_called()
    assert mock_page.screenshot.call_count == 3


@pytest.mark.asyncio
async def test_capture_dashboard_sidebar_text_content_none():
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    # skip_btn mock
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(return_value=0)
    
    # ops_link mock
    mock_ops_link = MagicMock()
    mock_ops_link.count = AsyncMock(return_value=0)

    # sidebar_links mock (1 link with text_content returning None)
    mock_sidebar_links = MagicMock()
    mock_sidebar_links.count = AsyncMock(return_value=1)
    
    mock_link_0 = MagicMock()
    mock_link_0.text_content = AsyncMock(return_value=None)
    mock_link_0.click = AsyncMock()
    mock_sidebar_links.nth = MagicMock(return_value=mock_link_0)

    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        elif "運用監視" in selector:
            mock_parent = MagicMock()
            mock_parent.first = mock_ops_link
            return mock_parent
        elif "nav a, .sidebar a" in selector:
            return mock_sidebar_links
        # UI check elements mock
        mock_ui_element = MagicMock()
        mock_ui_element.count = AsyncMock(return_value=0)
        return mock_ui_element

    mock_page.locator.side_effect = locator_side_effect

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        await capture_dashboard()

    # Assert fallback logic handles None text_content safely
    mock_skip_btn.click.assert_not_called()
    mock_ops_link.click.assert_not_called()
    mock_link_0.click.assert_not_called()
    assert mock_page.screenshot.call_count == 3


@pytest.mark.asyncio
async def test_capture_dashboard_ui_multiple_counts():
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    # skip_btn mock
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(return_value=1)
    mock_skip_btn.click = AsyncMock()
    
    # ops_link mock
    mock_ops_link = MagicMock()
    mock_ops_link.count = AsyncMock(return_value=1)
    mock_ops_link.click = AsyncMock()

    # Control locator behavior
    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        elif "運用監視" in selector:
            mock_parent = MagicMock()
            mock_parent.first = mock_ops_link
            return mock_parent
        # UI check elements mock (returns count of 2)
        mock_ui_element = MagicMock()
        mock_ui_element.count = AsyncMock(return_value=2)
        return mock_ui_element

    mock_page.locator.side_effect = locator_side_effect

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        await capture_dashboard()

    # Assert standard workflow calls with multiple UI element counts
    mock_chromium.launch.assert_called_once_with(headless=True)
    mock_browser.new_page.assert_called_once_with(viewport={"width": 1400, "height": 900})
    mock_page.goto.assert_called_once_with("http://localhost:5173/", wait_until="networkidle", timeout=15000)
    mock_skip_btn.click.assert_called_once_with(force=True)
    mock_ops_link.click.assert_called_once_with(force=True)
    assert mock_page.screenshot.call_count == 3
    mock_browser.close.assert_called_once()


@pytest.mark.asyncio
async def test_capture_dashboard_goto_exception():
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    
    # Mock goto to raise exception
    mock_page.goto = AsyncMock(side_effect=Exception("Navigation Timeout"))
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        with pytest.raises(Exception, match="Navigation Timeout"):
            await capture_dashboard()

    # Assert browser close was called even if exception occurred
    mock_browser.close.assert_called_once()


@pytest.mark.asyncio
async def test_capture_dashboard_fallback_match_monitoring():
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    # skip_btn mock (no onboarding screen)
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(return_value=0)
    
    # ops_link mock (no direct ops link)
    mock_ops_link = MagicMock()
    mock_ops_link.count = AsyncMock(return_value=0)

    # sidebar_links mock (only "監視" in matching label)
    mock_sidebar_links = MagicMock()
    mock_sidebar_links.count = AsyncMock(return_value=1)
    
    mock_link_0 = MagicMock()
    mock_link_0.text_content = AsyncMock(return_value="  システム監視  ")
    mock_link_0.click = AsyncMock()
    mock_sidebar_links.nth = MagicMock(return_value=mock_link_0)

    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        elif "運用監視" in selector:
            mock_parent = MagicMock()
            mock_parent.first = mock_ops_link
            return mock_parent
        elif "nav a, .sidebar a" in selector:
            return mock_sidebar_links
        # UI check elements mock
        mock_ui_element = MagicMock()
        mock_ui_element.count = AsyncMock(return_value=0)
        return mock_ui_element

    mock_page.locator.side_effect = locator_side_effect

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        await capture_dashboard()

    mock_link_0.click.assert_called_once_with(force=True)


@pytest.mark.asyncio
async def test_capture_dashboard_fallback_match_dash():
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    # skip_btn mock (no onboarding screen)
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(return_value=0)
    
    # ops_link mock (no direct ops link)
    mock_ops_link = MagicMock()
    mock_ops_link.count = AsyncMock(return_value=0)

    # sidebar_links mock (only "ダッシュ" in matching label)
    mock_sidebar_links = MagicMock()
    mock_sidebar_links.count = AsyncMock(return_value=1)
    
    mock_link_0 = MagicMock()
    mock_link_0.text_content = AsyncMock(return_value="  ダッシュボード  ")
    mock_link_0.click = AsyncMock()
    mock_sidebar_links.nth = MagicMock(return_value=mock_link_0)

    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        elif "運用監視" in selector:
            mock_parent = MagicMock()
            mock_parent.first = mock_ops_link
            return mock_parent
        elif "nav a, .sidebar a" in selector:
            return mock_sidebar_links
        # UI check elements mock
        mock_ui_element = MagicMock()
        mock_ui_element.count = AsyncMock(return_value=0)
        return mock_ui_element

    mock_page.locator.side_effect = locator_side_effect

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        await capture_dashboard()

    mock_link_0.click.assert_called_once_with(force=True)


@pytest.mark.asyncio
async def test_capture_dashboard_screenshot_exception():
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    
    # page.screenshot will raise exception
    mock_page.screenshot = AsyncMock(side_effect=Exception("Screenshot Failed"))
    mock_browser.close = AsyncMock()

    # skip_btn mock
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(return_value=0)
    
    # ops_link mock
    mock_ops_link = MagicMock()
    mock_ops_link.count = AsyncMock(return_value=0)

    # sidebar_links mock
    mock_sidebar_links = MagicMock()
    mock_sidebar_links.count = AsyncMock(return_value=0)

    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        elif "運用監視" in selector:
            mock_parent = MagicMock()
            mock_parent.first = mock_ops_link
            return mock_parent
        elif "nav a, .sidebar a" in selector:
            return mock_sidebar_links
        # UI check elements mock
        mock_ui_element = MagicMock()
        mock_ui_element.count = AsyncMock(return_value=0)
        return mock_ui_element

    mock_page.locator.side_effect = locator_side_effect

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        with pytest.raises(Exception, match="Screenshot Failed"):
            await capture_dashboard()


@pytest.mark.asyncio
async def test_capture_dashboard_nth_text_content_exception():
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    # skip_btn mock
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(return_value=0)
    
    # ops_link mock
    mock_ops_link = MagicMock()
    mock_ops_link.count = AsyncMock(return_value=0)

    # sidebar_links mock (1 link with text_content raising Exception)
    mock_sidebar_links = MagicMock()
    mock_sidebar_links.count = AsyncMock(return_value=1)
    
    mock_link_0 = MagicMock()
    mock_link_0.text_content = AsyncMock(side_effect=Exception("Text Content Error"))
    mock_link_0.click = AsyncMock()
    mock_sidebar_links.nth = MagicMock(return_value=mock_link_0)

    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        elif "運用監視" in selector:
            mock_parent = MagicMock()
            mock_parent.first = mock_ops_link
            return mock_parent
        elif "nav a, .sidebar a" in selector:
            return mock_sidebar_links
        # UI check elements mock
        mock_ui_element = MagicMock()
        mock_ui_element.count = AsyncMock(return_value=0)
        return mock_ui_element

    mock_page.locator.side_effect = locator_side_effect

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        with pytest.raises(Exception, match="Text Content Error"):
            await capture_dashboard()


@pytest.mark.asyncio
async def test_capture_dashboard_skip_click_exception():
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    # skip_btn mock (raises Exception on click)
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(return_value=1)
    mock_skip_btn.click = AsyncMock(side_effect=Exception("Click Skip Failed"))
    
    # ops_link mock
    mock_ops_link = MagicMock()
    mock_ops_link.count = AsyncMock(return_value=0)

    # sidebar_links mock
    mock_sidebar_links = MagicMock()
    mock_sidebar_links.count = AsyncMock(return_value=0)

    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        elif "運用監視" in selector:
            mock_parent = MagicMock()
            mock_parent.first = mock_ops_link
            return mock_parent
        elif "nav a, .sidebar a" in selector:
            return mock_sidebar_links
        # UI check elements mock
        mock_ui_element = MagicMock()
        mock_ui_element.count = AsyncMock(return_value=0)
        return mock_ui_element

    mock_page.locator.side_effect = locator_side_effect

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        with pytest.raises(Exception, match="Click Skip Failed"):
            await capture_dashboard()


@pytest.mark.asyncio
async def test_capture_dashboard_ops_click_exception():
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    # skip_btn mock
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(return_value=0)
    
    # ops_link mock (raises Exception on click)
    mock_ops_link = MagicMock()
    mock_ops_link.count = AsyncMock(return_value=1)
    mock_ops_link.click = AsyncMock(side_effect=Exception("Click Ops Failed"))

    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        elif "運用監視" in selector:
            mock_parent = MagicMock()
            mock_parent.first = mock_ops_link
            return mock_parent
        # UI check elements mock
        mock_ui_element = MagicMock()
        mock_ui_element.count = AsyncMock(return_value=0)
        return mock_ui_element

    mock_page.locator.side_effect = locator_side_effect

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        with pytest.raises(Exception, match="Click Ops Failed"):
            await capture_dashboard()

    # Assert browser close was called even if exception occurred
    mock_browser.close.assert_called_once()


@pytest.mark.asyncio
async def test_capture_dashboard_exception_ensures_browser_close():
    # Setup mock playwright structure
    mock_playwright_context = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright_context.chromium = mock_chromium

    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_page = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    
    # Mock locator skip_btn.count to raise an exception to simulate a middle-run error
    mock_skip_btn = MagicMock()
    mock_skip_btn.count = AsyncMock(side_effect=ValueError("Locator error"))
    
    def locator_side_effect(selector):
        if "スキップして始める" in selector:
            return mock_skip_btn
        return MagicMock()

    mock_page.locator.side_effect = locator_side_effect
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    mock_async_playwright = MagicMock()
    mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_playwright_context)
    mock_async_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("tests._screenshot_dashboard.async_playwright", return_value=mock_async_playwright):
        with pytest.raises(ValueError, match="Locator error"):
            await capture_dashboard()

    # Assert browser.close was called despite the exception in the middle of execution
    mock_browser.close.assert_called_once()


@pytest.mark.asyncio
async def test_setup_browser_and_page_new_page_error():
    from tests._screenshot_dashboard import _setup_browser_and_page, PlaywrightError
    
    mock_playwright = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright.chromium = mock_chromium
    
    mock_browser = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)
    
    # new_page raises PlaywrightError
    mock_browser.new_page = AsyncMock(side_effect=PlaywrightError("New Page Error"))
    mock_browser.close = AsyncMock()
    
    with pytest.raises(PlaywrightError, match="New Page Error"):
        await _setup_browser_and_page(mock_playwright)
        
    mock_browser.close.assert_called_once()


def test_adjust_aspect_ratio_to_16_9_unidentified_image_handled(tmp_path, capsys):
    from tests._screenshot_dashboard import adjust_aspect_ratio_to_16_9
    
    # Create an invalid image file (0 bytes) to cause UnidentifiedImageError
    invalid_image = tmp_path / "invalid_image.png"
    invalid_image.write_bytes(b"")
    
    # This should not raise an exception, but print an error message
    adjust_aspect_ratio_to_16_9(str(invalid_image))
    
    captured = capsys.readouterr()
    assert "[補正エラー]" in captured.out
