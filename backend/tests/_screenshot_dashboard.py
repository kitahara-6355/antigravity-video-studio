"""
ブラウザエージェント代替: Playwrightでスクリーンショット取得
ブラウザエージェントが503エラー時のフォールバック手段
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, Page, Browser, Error as PlaywrightError
from PIL import Image, UnidentifiedImageError

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)


def _calculate_target_dimensions(width: int, height: int) -> tuple[int, int]:
    """16:9比率を達成するために必要な目標サイズを計算する (解像度 1280x720 以上を保証)。"""
    target_width = max(width, 1280)
    target_height = int(target_width * 9 / 16)
    
    if target_height < max(height, 720):
        target_height = max(height, 720)
        target_width = int(target_height * 16 / 9)
        
    return target_width, target_height


def _resize_and_composite_image(img: Image.Image, target_width: int, target_height: int) -> Image.Image:
    """アスペクト比を維持して画像を拡大・縮小し、黒背景の新規キャンバスに合成する。"""
    canvas_image = Image.new("RGB", (target_width, target_height), (0, 0, 0))
    
    width, height = img.size
    aspect = width / height
    target_aspect = target_width / target_height
    
    if aspect > target_aspect:
        new_height = int(target_width / aspect)
        resized_image = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
        paste_position = (0, (target_height - new_height) // 2)
    else:
        new_width = int(target_height * aspect)
        resized_image = img.resize((new_width, target_height), Image.Resampling.LANCZOS)
        paste_position = ((target_width - new_width) // 2, 0)
        
    canvas_image.paste(resized_image, paste_position)
    return canvas_image


def adjust_aspect_ratio_to_16_9(image_path: str) -> None:
    """スクリーンショット画像のアスペクト比を16:9（黒背景）に補正し、4MB未満にするためにPNGで圧縮保存する。"""
    path_obj = Path(image_path)
    if not path_obj.exists():
        print(f"  [補正スキップ] ファイルが存在しません: {image_path}")
        return
    try:
        with Image.open(path_obj) as img:
            width, height = img.size
            target_width, target_height = _calculate_target_dimensions(width, height)
            canvas_image = _resize_and_composite_image(img, target_width, target_height)
            
            canvas_image.save(path_obj, "PNG", optimize=True)
            print(f"  [補正完了] {path_obj.name} (サイズ: {target_width}x{target_height})")
    except (UnidentifiedImageError, OSError, ValueError, RuntimeError, AttributeError) as e:
        print(f"  [補正エラー] {path_obj.name}: {e}")


async def _setup_browser_and_page(p) -> tuple[Browser, Page]:
    """Playwrightのブラウザとページを設定して起動する。"""
    browser = await p.chromium.launch(headless=True)
    try:
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        return browser, page
    except (PlaywrightError, OSError, ValueError, RuntimeError, asyncio.TimeoutError) as e:
        print(f"  [ページ設定エラー] ブラウザ新規ページの作成に失敗しました: {e}")
        await browser.close()
        raise


async def _skip_onboarding_if_visible(page: Page) -> None:
    """オンボーディング画面が表示されている場合はスキップする。"""
    skip_btn = page.locator("text=スキップして始める")
    if await skip_btn.count() > 0:
        print("  オンボーディング画面を検出 → スキップ")
        await skip_btn.click(force=True)
        await page.wait_for_timeout(2000)


async def _navigate_to_ops_page(page: Page) -> None:
    """運用監視ページへ遷移する（フォールバックあり）。"""
    ops_link = page.locator("text=運用監視").first
    if await ops_link.count() > 0:
        await ops_link.click(force=True)
        await page.wait_for_timeout(3000)
    else:
        sidebar_links = page.locator("nav a, .sidebar a, [class*=sidebar] a, [class*=nav] a, button")
        count = await sidebar_links.count()
        print(f"  サイドバーリンク数: {count}")
        for i in range(count):
            link_text = (await sidebar_links.nth(i).text_content() or "").strip()
            if "監視" in link_text or "運用" in link_text or "ダッシュ" in link_text:
                await sidebar_links.nth(i).click(force=True)
                await page.wait_for_timeout(3000)
                break


async def _capture_and_process_screenshot(page: Page, file_name: str, full_page: bool = False) -> None:
    """スクリーンショットを撮影し、アスペクト比を16:9に補正して保存する。"""
    shot_path = str(SCREENSHOT_DIR / file_name)
    await page.screenshot(path=shot_path, full_page=full_page)
    adjust_aspect_ratio_to_16_9(shot_path)
    print(f"  => {shot_path}")


async def _verify_dashboard_ui_elements(page: Page) -> None:
    """ダッシュボード内の主要なUI要素が存在するか検証する。"""
    checks = {
        "アクティブモデル見出し": "text=現在のアクティブモデル",
        "降格チェーン": "text=降格チェーン",
        "モデル別API使用量": "text=モデル別API使用量",
        "Premiumラベル": "text=Premium",
        "Standardラベル": "text=Standard",
        "Batchラベル": "text=Batch",
    }
    for label, selector in checks.items():
        found = await page.locator(selector).count()
        icon = "OK" if found > 0 else "NG"
        print(f"  [{icon}] {label} (count={found})")


async def capture_dashboard() -> None:
    """Playwrightで運用監視ダッシュボードのスクリーンショットを撮影・検証する。"""
    async with async_playwright() as p:
        try:
            browser, page = await _setup_browser_and_page(p)
        except (PlaywrightError, OSError, ValueError, RuntimeError, asyncio.TimeoutError) as e:
            print(f"[エラー] ブラウザ起動またはページ設定に失敗しました: {e}")
            raise
        
        try:
            # 1. メインページ
            print("[1/4] メインページを開きます...")
            await page.goto("http://localhost:5173/", wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(2000)

            await _skip_onboarding_if_visible(page)
            await _capture_and_process_screenshot(page, "01_main_page.png", full_page=True)

            # 2. 運用監視をクリック
            print("[2/4] 運用監視ページへ遷移...")
            await _navigate_to_ops_page(page)
            await _capture_and_process_screenshot(page, "02_ops_dashboard_top.png", full_page=False)

            # 3. スクロールして全体を撮影
            print("[3/4] 全体スクリーンショット...")
            await _capture_and_process_screenshot(page, "03_ops_dashboard_full.png", full_page=True)

            # 4. UI要素の存在チェック
            print("[4/4] UI要素チェック...")
            await _verify_dashboard_ui_elements(page)
        except (PlaywrightError, OSError, ValueError, RuntimeError, asyncio.TimeoutError) as e:
            print(f"[エラー] スクリーンショット処理実行中にエラーが発生しました: {e}")
            raise
        finally:
            await browser.close()
            print(f"\nスクリーンショット保存先: {SCREENSHOT_DIR}")


if __name__ == "__main__":
    asyncio.run(capture_dashboard())
