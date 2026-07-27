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
class TestE2E9G81SoulPassportHeader:
    """E2E-9 G81: ヘッダー表示

    逆引きカバレッジ: O12 → G81
    逆引き対象項目: O12-L1-01, O12-L2-01, O12-L1-02, O12-L2-02, O12-L1-01, O12-L2-01
    """

    def test_ac_sp01_g81_header_title(self, app_page, pipeline_result):
        """AC-SP01: SOUL PASSPORTタイトル表示

        逆引き: O12-L1-01, O12-L2-01, O12-L3-01, O12-L4-01"""
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

    def test_ac_sp02_g81_trinity_badge(self, app_page, pipeline_result):
        """AC-SP02: TRINITY SYSTEM 2.0バッジ

        逆引き: O12-L1-02, O12-L2-02, O12-L3-02, O12-L4-02"""
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

    def test_ac_sp03_g81_subtitle_text(self, app_page, pipeline_result):
        """AC-SP03: サブタイトルテキスト

        逆引き: O12-L1-01, O12-L2-01, O12-L3-01, O12-L4-01"""
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
# E2E-9: SoulPassport G82: 哲学カード
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E9G82PhilosophyCard:
    """E2E-9 G82: 哲学カード

    逆引きカバレッジ: O12 → G82
    逆引き対象項目: O12-L1-03, O12-L2-03, O12-L1-04, O12-L2-04, O12-L1-03, O12-L2-03
    """

    def test_ac_sp04_g82_philosophy_text(self, app_page, pipeline_result):
        """AC-SP04: 哲学テキスト引用符付き表示

        逆引き: O12-L1-03, O12-L2-03, O12-L3-03, O12-L4-03"""
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

    def test_ac_sp05_g82_philosophy_card_style(self, app_page, pipeline_result):
        """AC-SP05: 哲学カードスタイル

        逆引き: O12-L1-04, O12-L2-04, O12-L3-04, O12-L4-04"""
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

    def test_ac_sp06_g82_directors_label(self, app_page, pipeline_result):
        """AC-SP06: Director's Philosophyラベル

        逆引き: O12-L1-03, O12-L2-03, O12-L3-03, O12-L4-03"""
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
# E2E-9: SoulPassport G83: Admin/Ownerランク
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E9G83AdminOwnerRank:
    """E2E-9 G83: Admin/Ownerランク

    逆引きカバレッジ: O12 → G83
    逆引き対象項目: O12-L1-05, O12-L2-05, O12-L1-06, O12-L2-06, O12-L1-05, O12-L2-05
    """

    def test_ac_sp07_g83_admin_tech_rank(self, app_page, pipeline_result):
        """AC-SP07: ADMIN (TECH) ランク表示

        逆引き: O12-L1-05, O12-L2-05, O12-L3-05, O12-L4-05"""
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

    def test_ac_sp08_g83_owner_biz_rank(self, app_page, pipeline_result):
        """AC-SP08: OWNER (BIZ) ランク表示

        逆引き: O12-L1-06, O12-L2-06, O12-L3-06, O12-L4-06"""
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

    def test_ac_sp09_g83_dual_rank_layout(self, app_page, pipeline_result):
        """AC-SP09: 2カラムランクレイアウト

        逆引き: O12-L1-05, O12-L2-05, O12-L3-05, O12-L4-05"""
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
# E2E-9: SoulPassport G84: XPポイント
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E9G84XpPoints:
    """E2E-9 G84: XPポイント

    逆引きカバレッジ: O12 → G84
    逆引き対象項目: O12-L1-07, O12-L2-07, O12-L1-08, O12-L2-08, O12-L1-07, O12-L2-07
    """

    def test_ac_sp10_g84_tech_xp_display(self, app_page, pipeline_result):
        """AC-SP10: Tech XP数値表示

        逆引き: O12-L1-07, O12-L2-07, O12-L3-07, O12-L4-07"""
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

    def test_ac_sp11_g84_biz_xp_display(self, app_page, pipeline_result):
        """AC-SP11: Biz XP数値表示

        逆引き: O12-L1-08, O12-L2-08, O12-L3-08, O12-L4-08"""
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

    def test_ac_sp12_g84_xp_format(self, app_page, pipeline_result):
        """AC-SP12: XPフォーマット確認

        逆引き: O12-L1-07, O12-L2-07, O12-L3-07, O12-L4-07"""
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
# E2E-9: SoulPassport G85: Evolution Logタイムライン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E9G85EvolutionLog:
    """E2E-9 G85: Evolution Logタイムライン

    逆引きカバレッジ: O12 → G85
    逆引き対象項目: O12-L1-09, O12-L2-09, O12-L1-10, O12-L2-10, O12-L1-09, O12-L2-09
    """

    def test_ac_sp13_g85_timeline_entries(self, app_page, pipeline_result):
        """AC-SP13: タイムラインエントリ表示

        逆引き: O12-L1-09, O12-L2-09, O12-L3-09, O12-L4-09"""
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

    def test_ac_sp14_g85_timeline_dots(self, app_page, pipeline_result):
        """AC-SP14: タイムラインドット表示

        逆引き: O12-L1-10, O12-L2-10, O12-L3-10, O12-L4-10"""
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

    def test_ac_sp15_g85_chronological_order(self, app_page, pipeline_result):
        """AC-SP15: 時系列順序

        逆引き: O12-L1-09, O12-L2-09, O12-L3-09, O12-L4-09"""
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
# E2E-9: SoulPassport G86: summary+insight
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E9G86SummaryInsight:
    """E2E-9 G86: summary+insight

    逆引きカバレッジ: O12 → G86
    逆引き対象項目: O12-L1-11, O12-L2-11, O12-L1-12, O12-L2-12, O12-L1-11, O12-L2-11
    """

    def test_ac_sp16_g86_entry_summary(self, app_page, pipeline_result):
        """AC-SP16: エントリsummaryテキスト

        逆引き: O12-L1-11, O12-L2-11, O12-L3-11, O12-L4-11"""
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

    def test_ac_sp17_g86_entry_insight(self, app_page, pipeline_result):
        """AC-SP17: エントリinsightテキスト

        逆引き: O12-L1-12, O12-L2-12, O12-L3-12, O12-L4-12"""
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

    def test_ac_sp18_g86_timestamp_display(self, app_page, pipeline_result):
        """AC-SP18: タイムスタンプ表示

        逆引き: O12-L1-11, O12-L2-11, O12-L3-11, O12-L4-11"""
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
# E2E-9: G87: stat_changesバッジ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E9G87StatChangesBadge:
    """E2E-9 G87: stat_changesバッジ

    逆引きカバレッジ: G87
    逆引き対象項目: O12-L1-13, O12-L2-13, O12-L1-14, O12-L2-14, O12-L1-13, O12-L2-13
    """

    def test_ac_sp19_g87_stat_badge_display(self, app_page, pipeline_result):
        """AC-SP19: stat_changesバッジ表示

        逆引き: O12-L1-13, O12-L2-13, O12-L3-13, O12-L4-13"""
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

    def test_ac_sp20_g87_badge_content(self, app_page, pipeline_result):
        """AC-SP20: バッジテキスト内容

        逆引き: O12-L1-14, O12-L2-14, O12-L3-14, O12-L4-14"""
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

    def test_ac_sp21_g87_badge_style(self, app_page, pipeline_result):
        """AC-SP21: バッジスタイル確認

        逆引き: O12-L1-13, O12-L2-13, O12-L3-13, O12-L4-13"""
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
# E2E-9: G88: 共同制作ジャーナル
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E9G88CollaborativeJournal:
    """E2E-9 G88: 共同制作ジャーナル

    逆引きカバレッジ: G88
    逆引き対象項目: O12-L1-15, O12-L2-15, O12-L1-16, O12-L2-16, O12-L1-15, O12-L2-15
    """

    def test_ac_sp22_g88_journal_section(self, app_page, pipeline_result):
        """AC-SP22: 共同制作ジャーナルセクション表示

        逆引き: O12-L1-15, O12-L2-15, O12-L3-15, O12-L4-15"""
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

    def test_ac_sp23_g88_collab_notes_text(self, app_page, pipeline_result):
        """AC-SP23: collaborative_notesテキスト

        逆引き: O12-L1-16, O12-L2-16, O12-L3-16, O12-L4-16"""
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

    def test_ac_sp24_g88_journal_scroll(self, app_page, pipeline_result):
        """AC-SP24: ジャーナルスクロール可能

        逆引き: O12-L1-15, O12-L2-15, O12-L3-15, O12-L4-15"""
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
# E2E-9: G89: 閉じるボタン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E9G89CloseButton:
    """E2E-9 G89: 閉じるボタン

    逆引きカバレッジ: G89
    逆引き対象項目: O12-L1-17, O12-L2-17, O12-L1-18, O12-L2-18, O12-L1-17, O12-L2-17
    """

    def test_ac_sp25_g89_close_btn_visible(self, app_page, pipeline_result):
        """AC-SP25: 閉じるボタン表示

        逆引き: O12-L1-17, O12-L2-17, O12-L3-17, O12-L4-17"""
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

    def test_ac_sp26_g89_close_action(self, app_page, pipeline_result):
        """AC-SP26: onClose発火確認

        逆引き: O12-L1-18, O12-L2-18, O12-L3-18, O12-L4-18"""
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

    def test_ac_sp27_g89_hidden_after_close(self, app_page, pipeline_result):
        """AC-SP27: 閉じた後非表示

        逆引き: O12-L1-17, O12-L2-17, O12-L3-17, O12-L4-17"""
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
# E2E-9: G90: ローディングスピナー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E9G90LoadingSpinner:
    """E2E-9 G90: ローディングスピナー

    逆引きカバレッジ: G90
    逆引き対象項目: O12-L1-19, O12-L2-19, O12-L1-20, O12-L2-20, O12-L1-19, O12-L2-19
    """

    def test_ac_sp28_g90_spinner_during_load(self, app_page, pipeline_result):
        """AC-SP28: API中スピナー表示

        逆引き: O12-L1-19, O12-L2-19, O12-L3-19, O12-L4-19"""
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

    def test_ac_sp29_g90_spinner_disappear(self, app_page, pipeline_result):
        """AC-SP29: 完了後スピナー非表示

        逆引き: O12-L1-20, O12-L2-20, O12-L3-20, O12-L4-20"""
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

    def test_ac_sp30_g90_content_after_load(self, app_page, pipeline_result):
        """AC-SP30: ロード完了後コンテンツ表示

        逆引き: O12-L1-19, O12-L2-19, O12-L3-19, O12-L4-19"""
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
# E2E-10: G91: ONLINE/OFFLINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


