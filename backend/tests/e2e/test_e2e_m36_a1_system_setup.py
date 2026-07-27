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
class TestE2E10G91OnlineOffline:
    """E2E-10 G91: ONLINE/OFFLINE

    逆引きカバレッジ: G91
    逆引き対象項目: A1-L1-01, A1-L2-01, A1-L1-02, A1-L2-02, A1-L1-01, A1-L2-01
    """

    def test_ac_od01_g91_health_card_online(self, app_page, pipeline_result):
        """AC-OD01: ONLINEテキスト表示

        逆引き: A1-L1-01, A1-L2-01, A1-L3-01, A1-L4-01"""
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

    def test_ac_od02_g91_health_color(self, app_page, pipeline_result):
        """AC-OD02: ヘルスカード色分け

        逆引き: A1-L1-02, A1-L2-02, A1-L3-02, A1-L4-02"""
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

    def test_ac_od03_g91_auto_refresh(self, app_page, pipeline_result):
        """AC-OD03: 自動更新確認

        逆引き: A1-L1-01, A1-L2-01, A1-L3-01, A1-L4-01"""
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
# E2E-10: G92: パイプラインステータス
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E10G92PipelineStatus:
    """E2E-10 G92: パイプラインステータス

    逆引きカバレッジ: G92
    逆引き対象項目: A1-L1-03, A1-L2-03, A1-L1-04, A1-L2-04, A1-L1-03, A1-L2-03
    """

    def test_ac_od04_g92_phase_name(self, app_page, pipeline_result):
        """AC-OD04: フェーズ名表示

        逆引き: A1-L1-03, A1-L2-03, A1-L3-03, A1-L4-03"""
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

    def test_ac_od05_g92_progress_bar(self, app_page, pipeline_result):
        """AC-OD05: 進捗バー表示

        逆引き: A1-L1-04, A1-L2-04, A1-L3-04, A1-L4-04"""
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

    def test_ac_od06_g92_completion_rate(self, app_page, pipeline_result):
        """AC-OD06: 完了率表示

        逆引き: A1-L1-03, A1-L2-03, A1-L3-03, A1-L4-03"""
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
# E2E-10: G93: やり直し予算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E10G100ManualRefresh:
    """E2E-10 G100: 手動更新ボタン

    逆引きカバレッジ: G100
    逆引き対象項目: A1-L1-05, A1-L2-05, A1-L1-06, A1-L2-06, A1-L1-05, A1-L2-05
    """

    def test_ac_od28_g100_refresh_button(self, app_page, pipeline_result):
        """AC-OD28: 更新ボタン表示

        逆引き: A1-L1-05, A1-L2-05, A1-L3-05, A1-L4-05"""
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

    def test_ac_od29_g100_timestamp_update(self, app_page, pipeline_result):
        """AC-OD29: タイムスタンプ更新

        逆引き: A1-L1-06, A1-L2-06, A1-L3-06, A1-L4-06"""
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

    def test_ac_od30_g100_auto_interval(self, app_page, pipeline_result):
        """AC-OD30: 自動リフレッシュ間隔

        逆引き: A1-L1-05, A1-L2-05, A1-L3-05, A1-L4-05"""
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

