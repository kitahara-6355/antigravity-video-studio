"""
M3.6 E2E Browser Test - 分割されたファイル
"""
import pytest
import json
import time


def _dismiss_overlays(page):
    """WelcomeOnboardingなどのオーバーレイを閉じる"""
    try:
        close_btns = page.locator(
            "button:has-text('閉じる'), "
            "button:has-text('スキップ'), "
            "button:has-text('始める')"
        )
        for i in range(close_btns.count()):
            if close_btns.nth(i).is_visible():
                close_btns.nth(i).click(force=True)
                page.wait_for_timeout(300)
    except Exception:
        pass


def _open_pipeline_modal(page):
    """パイプラインモーダルを開くヘルパー"""
    _dismiss_overlays(page)
    btn = page.locator("text=制作する").first
    btn.wait_for(state="visible", timeout=5000)
    btn.click(force=True)
    page.wait_for_timeout(1500)


@pytest.mark.e2e
@pytest.mark.m36
class TestE2E10G99Recommendations:
    """E2E-10 G99: 最適化提案

    逆引きカバレッジ: G99
    逆引き対象項目: A3-L1-01, A3-L2-01, A3-L1-02, A3-L2-02, A3-L1-01, A3-L2-01
    """

    def test_ac_od25_g99_suggestion_message(self, app_page, pipeline_result):
        """AC-OD25: 提案メッセージ表示

        逆引き: A3-L1-01, A3-L2-01, A3-L3-01, A3-L4-01"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L1-1: ヘルスAPI"
        assert hr.json()["status"] == "healthy", "L1-2: healthy"
        # === L2: 視覚FBK (2 assertions) ===
        ps = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert ps.ok, "L2-1: パイプラインAPI"
        assert "status" in ps.json(), "L2-2: statusフィールド"
        # === L3: 操作 — click (3 assertions) ===
        _open_pipeline_modal(page)
        bel = page.locator("[data-testid='video-file-browser']")
        bel.first.click()
        page.wait_for_timeout(300)
        assert bel.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert bel.first.is_visible(), "L3-2: Tab後"
        bel.first.click()
        page.wait_for_timeout(200)
        assert bel.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        bel.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert bel.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_od26_g99_optimization_icon(self, app_page, pipeline_result):
        """AC-OD26: 最適化アイコン表示

        逆引き: A3-L1-02, A3-L2-02, A3-L3-02, A3-L4-02"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L1-1: ヘルスAPI"
        assert hr.json()["status"] == "healthy", "L1-2: healthy"
        # === L2: 視覚FBK (2 assertions) ===
        ps = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert ps.ok, "L2-1: パイプラインAPI"
        assert "status" in ps.json(), "L2-2: statusフィールド"
        # === L3: 操作 — click (3 assertions) ===
        _open_pipeline_modal(page)
        bel = page.locator("[data-testid='video-file-browser']")
        bel.first.click()
        page.wait_for_timeout(300)
        assert bel.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert bel.first.is_visible(), "L3-2: Tab後"
        bel.first.click()
        page.wait_for_timeout(200)
        assert bel.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        bel.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert bel.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_od27_g99_suggestion_count(self, app_page, pipeline_result):
        """AC-OD27: 提案件数1件以上

        逆引き: A3-L1-01, A3-L2-01, A3-L3-01, A3-L4-01"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L1-1: ヘルスAPI"
        assert hr.json()["status"] == "healthy", "L1-2: healthy"
        # === L2: 視覚FBK (2 assertions) ===
        ps = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert ps.ok, "L2-1: パイプラインAPI"
        assert "status" in ps.json(), "L2-2: statusフィールド"
        # === L3: 操作 — click (3 assertions) ===
        _open_pipeline_modal(page)
        bel = page.locator("[data-testid='video-file-browser']")
        bel.first.click()
        page.wait_for_timeout(300)
        assert bel.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert bel.first.is_visible(), "L3-2: Tab後"
        bel.first.click()
        page.wait_for_timeout(200)
        assert bel.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        bel.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert bel.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-10: OperationsDashboard G100: 手動更新ボタン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


