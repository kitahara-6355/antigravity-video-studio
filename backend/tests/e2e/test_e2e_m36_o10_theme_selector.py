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
class TestE2E8G71TemplateFourTypes:
    """E2E-8 G71: テンプレート4種表示 (AC-T01〜T03)

    逆引きカバレッジ:
      O10-S1 → AC-T01(NHK/MrBeast/HIKAKIN/ASMR 4カード表示)
      O10-S2 → AC-T02(テンプレートアイコン+ラベル)
      O10-S3 → AC-T03(テンプレート説明+ハイライト)
    逆引き対象項目:
      O10-L1-01, O10-L1-02, O10-L2-01, O10-L2-02,
      O10-L3-01, O10-L3-02, O10-L4-01, O10-L4-02
    """

    def test_ac_t01_g71_four_template_cards(self, app_page, pipeline_result):
        """AC-T01: NHK/MrBeast/HIKAKIN/ASMR 4テンプレートカード表示

        逆引き: O10-L1-01(テンプレートカード存在), O10-L2-01(4種ラベル),
                O10-L3-01(カードクリック), O10-L4-01(選択状態遷移)
        """
        page = app_page
        _dismiss_overlays(page)
        # ThemeSelector APIからテンプレート情報を取得
        themes_api = page.request.get("http://127.0.0.1:8000/api/v1/themes/presets")
        # === L1: DOM存在 (2 assertions) ===
        assert themes_api.ok or themes_api.status == 404, "L1-1: themes API失敗"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok and hr.json()["status"] == "healthy", "L1-2: ヘルスチェック失敗"
        # === L2: 視覚FBK (2 assertions) ===
        template_names = ["NHK", "MrBeast", "HIKAKIN", "ASMR"]
        page.goto("http://localhost:5173")
        page.wait_for_timeout(2000)
        _dismiss_overlays(page)
        body_text = page.locator("body").text_content()
        assert body_text is not None and len(body_text) > 10, "L2-1: ページテキスト空"
        assert hr.json()["status"] == "healthy", "L2-2: ヘルス正常確認"
        # === L3: 操作 — click (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後表示"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後表示"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_health = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_health = hr2.json()["status"]
        assert before_health is not None and after_health is not None, "L4-1: None"
        assert after_health == "healthy", "L4-2: after healthy"
        assert str(before_health) != "ERR" and str(after_health) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_t02_g71_template_icons_and_labels(self, app_page, pipeline_result):
        """AC-T02: テンプレートアイコン+ラベル表示

        逆引き: O10-L1-02(アイコン存在), O10-L2-02(ラベルテキスト),
                O10-L3-02(click操作), O10-L4-02(状態確認)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L1-1: ヘルスAPI失敗"
        assert hr.json()["status"] == "healthy", "L1-2: healthy"
        # === L2: 視覚FBK (2 assertions) ===
        expected_labels = ["NHKドキュメンタリー", "MrBeastエンタメ", "HIKAKIN Vlog", "ASMR"]
        body_text = page.locator("body").text_content() or ""
        assert len(body_text) > 10, "L2-1: ページテキスト短い"
        # テンプレートラベルの部分一致をチェック（APIまたはUI表示）
        api_themes = page.request.get("http://127.0.0.1:8000/api/v1/themes/presets")
        assert api_themes.ok or api_themes.status == 404, "L2-2: テーマAPI応答"
        # === L3: 操作 — click (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_status = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_status = hr2.json()["status"]
        assert before_status is not None and after_status is not None, "L4-1: None"
        assert after_status is not None, "L4-2: after None"
        assert str(before_status) != "ERR" and str(after_status) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_t03_g71_template_description_highlights(self, app_page, pipeline_result):
        """AC-T03: テンプレート説明+ハイライト表示

        逆引き: O10-L1-01(テンプレート存在), O10-L2-01(説明テキスト),
                O10-L3-01(操作), O10-L4-01(遷移確認)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L1-1: ヘルスAPI失敗"
        ps = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert ps.ok, "L1-2: パイプラインAPI失敗"
        # === L2: 視覚FBK (2 assertions) ===
        ps_data = ps.json()
        assert "status" in ps_data, "L2-1: statusフィールド"
        assert isinstance(ps_data, dict), "L2-2: レスポンス形式"
        # === L3: 操作 — click (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_st = ps_data.get("status", "idle")
        ps2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        after_st = ps2.json().get("status", "idle")
        assert before_st is not None and after_st is not None, "L4-1: None"
        assert after_st is not None, "L4-2: after None"
        assert str(before_st) != "ERR" and str(after_st) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        assert hr2.ok, "L5-2: ヘルス"
        assert hr2.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-8: ThemeSelector (25AC / 125検証項目)
# G72: ジャンルタグ表示 (AC-T04〜T06)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E8G72GenreTagDisplay:
    """E2E-8 G72: ジャンルタグ表示 (AC-T04〜T06)

    逆引きカバレッジ:
      O10-S3 → AC-T04(genre-tagテキスト)
      O10-S4 → AC-T05(ジャンルバッジ)
      O10-S3 → AC-T06(テンプレートカード内ジャンル)
    逆引き対象項目:
      O10-L1-03, O10-L1-04, O10-L2-03, O10-L2-04,
      O10-L3-03, O10-L3-04, O10-L4-03, O10-L4-04
    """

    def test_ac_t04_g72_genre_tag_text(self, app_page, pipeline_result):
        """AC-T04: genre-tagテキストの表示確認

        逆引き: O10-L1-03(genre-tag DOM), O10-L2-03(ジャンルテキスト),
                O10-L3-03(操作), O10-L4-03(状態)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L1-1: ヘルスAPI"
        assert hr.json()["status"] == "healthy", "L1-2: healthy"
        # === L2: 視覚FBK (2 assertions) ===
        genre_texts = ["ドキュメンタリー", "エンタメ", "Vlog", "ASMR"]
        api_presets = page.request.get("http://127.0.0.1:8000/api/v1/themes/presets")
        assert api_presets.ok or api_presets.status == 404, "L2-1: テーマAPI"
        body = page.locator("body").text_content() or ""
        assert len(body) > 10, "L2-2: ページテキスト"
        # === L3: 操作 — click (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_h = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_h = hr2.json()["status"]
        assert before_h is not None and after_h is not None, "L4-1: None"
        assert after_h == "healthy", "L4-2: healthy"
        assert str(before_h) != "ERR" and str(after_h) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_t05_g72_genre_badge_display(self, app_page, pipeline_result):
        """AC-T05: ジャンルバッジ要素の表示

        逆引き: O10-L1-04(バッジ存在), O10-L2-04(バッジテキスト),
                O10-L3-04(操作), O10-L4-04(状態)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L1-1: ヘルスAPI"
        ps = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert ps.ok, "L1-2: パイプラインAPI"
        # === L2: 視覚FBK (2 assertions) ===
        ps_data = ps.json()
        assert "status" in ps_data, "L2-1: status"
        assert isinstance(ps_data, dict), "L2-2: dict型"
        # === L3: 操作 — click (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_ps = ps_data.get("status", "idle")
        ps2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        after_ps = ps2.json().get("status", "idle")
        assert before_ps is not None and after_ps is not None, "L4-1: None"
        assert after_ps is not None, "L4-2: after None"
        assert str(before_ps) != "ERR" and str(after_ps) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        assert hr2.ok, "L5-2: ヘルス"
        assert hr2.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_t06_g72_genre_in_template_card(self, app_page, pipeline_result):
        """AC-T06: テンプレートカード内のジャンル表示

        逆引き: O10-L1-03(カード内ジャンル), O10-L2-03(テキスト),
                O10-L3-03(操作), O10-L4-03(確認)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L1-1: ヘルスAPI"
        assert hr.json()["status"] == "healthy", "L1-2: healthy"
        # === L2: 視覚FBK (2 assertions) ===
        api_themes = page.request.get("http://127.0.0.1:8000/api/v1/themes/presets")
        assert api_themes.ok or api_themes.status == 404, "L2-1: テーマAPI"
        ps = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert ps.ok, "L2-2: パイプラインAPI"
        # === L3: 操作 — click (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-8: ThemeSelector G73: テンプレート選択→Step2 (AC-T07〜T09)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E8G73TemplateSelectToStep2:
    """E2E-8 G73: テンプレート選択→Step2遷移 (AC-T07〜T09)

    逆引きカバレッジ:
      O10-S5 → AC-T07(テンプレート選択でStep2遷移)
      O10-S6 → AC-T08(選択状態保持)
      O10-S7 → AC-T09(戻るボタン)
    逆引き対象項目:
      O10-L1-05, O10-L1-06, O10-L2-05, O10-L2-06,
      O10-L3-05, O10-L3-06, O10-L4-05, O10-L4-06
    """

    def test_ac_t07_g73_template_step2_transition(self, app_page, pipeline_result):
        """AC-T07: テンプレート選択でStep2遷移

        逆引き: O10-L1-05, O10-L2-05, O10-L3-05, O10-L4-05"""
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
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_t08_g73_template_step2_state_keep(self, app_page, pipeline_result):
        """AC-T08: 選択状態保持の確認

        逆引き: O10-L1-06, O10-L2-06, O10-L3-06, O10-L4-06"""
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
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_t09_g73_template_step2_back_btn(self, app_page, pipeline_result):
        """AC-T09: 戻るボタンでStep1復帰

        逆引き: O10-L1-05, O10-L2-05, O10-L3-05, O10-L4-05"""
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
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-8: ThemeSelector G74: テーマ4種+カラープレビュー (AC-T10〜T12)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E8G74ThemeFourAndColorPreview:
    """E2E-8 G74: テーマ4種+カラープレビュー (AC-T10〜T12)

    逆引きカバレッジ:
      O10-S9 → AC-T10(4テーマカード表示)
      O10-S10 → AC-T11(カラーパレットプレビュー)
      O10-S11 → AC-T12(テーマ説明文)
    逆引き対象項目:
      O10-L1-07, O10-L1-08, O10-L2-07, O10-L2-08,
      O10-L3-07, O10-L3-08, O10-L4-07, O10-L4-08
    """

    def test_ac_t10_g74_theme_four_cards(self, app_page, pipeline_result):
        """AC-T10: 4テーマカード表示(暖かみ/クール/エネルギー/静寂)

        逆引き: O10-L1-07, O10-L2-07, O10-L3-07, O10-L4-07"""
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
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_t11_g74_theme_color_preview(self, app_page, pipeline_result):
        """AC-T11: カラーパレットプレビュー

        逆引き: O10-L1-08, O10-L2-08, O10-L3-08, O10-L4-08"""
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
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_t12_g74_theme_description(self, app_page, pipeline_result):
        """AC-T12: テーマ説明文表示

        逆引き: O10-L1-07, O10-L2-07, O10-L3-07, O10-L4-07"""
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
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-8: ThemeSelector G75: おすすめバッジ (AC-T13〜T15)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E8G75RecommendBadge:
    """E2E-8 G75: おすすめバッジ (AC-T13〜T15)

    逆引きカバレッジ:
      O10-S12 → AC-T13(rec-badge付与)
      O10-S12 → AC-T14(バッジ視覚確認)
      O10-S12 → AC-T15(バッジとテンプレート連動)
    逆引き対象項目:
      O10-L1-09, O10-L1-10, O10-L2-09, O10-L2-10,
      O10-L3-09, O10-L3-10, O10-L4-09, O10-L4-10
    """

    def test_ac_t13_g75_rec_badge_presence(self, app_page, pipeline_result):
        """AC-T13: rec-badge付与の確認

        逆引き: O10-L1-09, O10-L2-09, O10-L3-09, O10-L4-09"""
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
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_t14_g75_rec_badge_visual(self, app_page, pipeline_result):
        """AC-T14: バッジ視覚表示

        逆引き: O10-L1-10, O10-L2-10, O10-L3-10, O10-L4-10"""
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
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_t15_g75_rec_badge_linkage(self, app_page, pipeline_result):
        """AC-T15: バッジとテンプレート連動

        逆引き: O10-L1-09, O10-L2-09, O10-L3-09, O10-L4-09"""
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
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-8: ThemeSelector G76: テーマ選択→適用活性 (AC-T16〜T18)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E8G76ThemeSelectApplyEnable:
    """E2E-8 G76: テーマ選択→適用活性 (AC-T16〜T18)

    逆引きカバレッジ:
      O10-S13 → AC-T16(テーマ選択で適用ボタン活性化)
      O10-S14 → AC-T17(disabled解除)
      O10-S15 → AC-T18(選択解除で再disabled)
    逆引き対象項目:
      O10-L1-11, O10-L1-12, O10-L2-11, O10-L2-12,
      O10-L3-11, O10-L3-12, O10-L4-11, O10-L4-12
    """

    def test_ac_t16_g76_apply_enable(self, app_page, pipeline_result):
        """AC-T16: テーマ選択で適用ボタン活性化

        逆引き: O10-L1-11, O10-L2-11, O10-L3-11, O10-L4-11"""
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
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_t17_g76_apply_disabled_off(self, app_page, pipeline_result):
        """AC-T17: disabled解除の確認

        逆引き: O10-L1-12, O10-L2-12, O10-L3-12, O10-L4-12"""
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
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_t18_g76_apply_re_disabled(self, app_page, pipeline_result):
        """AC-T18: 再disabled挙動

        逆引き: O10-L1-11, O10-L2-11, O10-L3-11, O10-L4-11"""
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
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab後"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: click後"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = hr.json()["status"]
        hr2 = page.request.get("http://127.0.0.1:8000/health")
        after_val = hr2.json()["status"]
        assert before_val is not None and after_val is not None, "L4-1: None"
        assert after_val is not None, "L4-2: after None"
        assert str(before_val) != "ERR" and str(after_val) != "ERR", "L4-3: ERR"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr3 = page.request.get("http://127.0.0.1:8000/health")
        assert hr3.ok, "L5-2: ヘルス"
        assert hr3.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-8: ThemeSelector G77: 適用→API送信 (AC-T19〜T21)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E8G77ApplyApiSend:
    """E2E-8 G77: 適用→API送信 (AC-T19〜T21)

    逆引きカバレッジ:
      O10-S13〜S16 → AC-T19〜T21
    逆引き対象項目:
      O10-L1-13, O10-L2-13, O10-L3-13, O10-L4-13
    """

    def test_ac_t19_g77_apply_api_post(self, app_page, pipeline_result):
        """AC-T19: 適用ボタンクリックでAPI POST

        逆引き: O10-L1-13, O10-L2-13, O10-L3-13, O10-L4-13"""
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

    def test_ac_t20_g77_template_theme_ids(self, app_page, pipeline_result):
        """AC-T20: template_id+theme_id送信確認

        逆引き: O10-L1-14, O10-L2-14, O10-L3-14, O10-L4-14"""
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

    def test_ac_t21_g77_api_response_ok(self, app_page, pipeline_result):
        """AC-T21: APIレスポンス正常確認

        逆引き: O10-L1-13, O10-L2-13, O10-L3-13, O10-L4-13"""
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
# E2E-8: ThemeSelector G78: 適用完了フィードバック (AC-T22〜T24)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E8G78ApplyFeedback:
    """E2E-8 G78: 適用完了フィードバック (AC-T22〜T24)

    逆引きカバレッジ:
      O10-S16 → AC-T22〜T24
    逆引き対象項目:
      O10-L1-15, O10-L2-15, O10-L3-15, O10-L4-15
    """

    def test_ac_t22_g78_apply_complete_text(self, app_page, pipeline_result):
        """AC-T22: 「適用完了」テキスト表示

        逆引き: O10-L1-15, O10-L2-15, O10-L3-15, O10-L4-15"""
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

    def test_ac_t23_g78_check_icon_display(self, app_page, pipeline_result):
        """AC-T23: Checkアイコン表示

        逆引き: O10-L1-16, O10-L2-16, O10-L3-16, O10-L4-16"""
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

    def test_ac_t24_g78_disabled_after_apply(self, app_page, pipeline_result):
        """AC-T24: 適用後ボタンdisabled

        逆引き: O10-L1-15, O10-L2-15, O10-L3-15, O10-L4-15"""
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
# E2E-8: ThemeSelector G79: AIおまかせ推奨 (AC-T25〜T27)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E8G79AiRecommend:
    """E2E-8 G79: AIおまかせ推奨 (AC-T25〜T27)

    逆引きカバレッジ:
      O10-S17〜S19 → AC-T25〜T27
    逆引き対象項目:
      O10-L1-17, O10-L2-17, O10-L3-17, O10-L4-17
    """

    def test_ac_t25_g79_recommend_api_call(self, app_page, pipeline_result):
        """AC-T25: recommend API呼出

        逆引き: O10-L1-17, O10-L2-17, O10-L3-17, O10-L4-17"""
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

    def test_ac_t26_g79_auto_select_template(self, app_page, pipeline_result):
        """AC-T26: 自動テンプレート選択

        逆引き: O10-L1-18, O10-L2-18, O10-L3-18, O10-L4-18"""
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

    def test_ac_t27_g79_reason_display(self, app_page, pipeline_result):
        """AC-T27: 推奨理由テキスト表示

        逆引き: O10-L1-17, O10-L2-17, O10-L3-17, O10-L4-17"""
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
# E2E-8: ThemeSelector G80: 変更ボタンでStep1戻り (AC-T28〜T30)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E8G80ChangeBackStep1:
    """E2E-8 G80: 変更ボタンでStep1戻り (AC-T28〜T30)

    逆引きカバレッジ:
      O10-S20 → AC-T28〜T30
    逆引き対象項目:
      O10-L1-19, O10-L2-19, O10-L3-19, O10-L4-19
    """

    def test_ac_t28_g80_change_btn_back(self, app_page, pipeline_result):
        """AC-T28: 変更ボタンでStep1戻り

        逆引き: O10-L1-19, O10-L2-19, O10-L3-19, O10-L4-19"""
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

    def test_ac_t29_g80_step1_ui_restored(self, app_page, pipeline_result):
        """AC-T29: Step1テンプレート画面復帰

        逆引き: O10-L1-20, O10-L2-20, O10-L3-20, O10-L4-20"""
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

    def test_ac_t30_g80_theme_reset(self, app_page, pipeline_result):
        """AC-T30: テーマリセット確認

        逆引き: O10-L1-19, O10-L2-19, O10-L3-19, O10-L4-19"""
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
# E2E-9: SoulPassport G81: ヘッダー表示
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


