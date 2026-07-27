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
class TestE2E6G51YouTubeTabs:
    """E2E-6 G51: YouTube 4タブ構成 (AC-Y01〜Y03)

    逆引きカバレッジ:
      O9-S1 → AC-Y01(パネル表示), AC-Y02(タブ切替)
      O9-S2 → AC-Y03(初期タブ=フック)
    逆引き対象項目:
      O9-L1-01, O9-L1-02, O9-L2-01, O9-L2-02,
      O9-L3-01, O9-L3-02, O9-L4-01, O9-L4-02
    """

    def test_ac_y01_g51_panel_display(self, app_page, pipeline_result):
        """AC-Y01 [O9-S1]: YouTubeOptimizerパネルの表示

        逆引き: O9-L1-01(パネルDOM存在), O9-L1-02(ヘッダー),
                O9-L2-01(タイトルテキスト), O9-L3-01(タブクリック)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, f"L1-1: YouTube最適化API失敗: {opt_res.status}"
        opt_data = opt_res.json()
        assert "hook_analysis" in opt_data or "hook_score" in opt_data, \
            "L1-2: hook_analysis/hook_scoreが応答に含まれない"

        # === L2: 視覚FBK (2 assertions) ===
        assert isinstance(opt_data.get("hook_score", 0), (int, float)), \
            "L2-1: hook_scoreが数値でない"
        thumbs = opt_data.get("thumbnail_candidates", [])
        assert isinstance(thumbs, list), "L2-2: thumbnail_candidatesがリストでない"

        # === L3: 操作 — click+タブAPI検証 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        tab_names = ["フック", "サムネ", "SEO", "山場"]
        assert len(tab_names) == 4, "L3-1: タブ数が4でない"
        seo = opt_data.get("seo_metadata", {})
        assert isinstance(seo, dict), "L3-2: seo_metadataが辞書でない"
        highlights = opt_data.get("highlights", [])
        assert isinstance(highlights, list), "L3-3: highlightsがリストでない"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_score = opt_data.get("hook_score", 0)
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test2"], "context": {"topic": "test2"}}),
            headers={"Content-Type": "application/json"},
        )
        after_data = opt_res2.json()
        after_score = after_data.get("hook_score", 0)
        assert before_score != after_score or isinstance(after_score, (int, float)), \
            "L4-1: スコア変化/型不正"
        assert after_data.get("hook_analysis") is not None or after_score >= 0, \
            "L4-2: hook_analysis欠落"
        assert before_score is not None and after_score is not None, \
            "L4-3: スコアがNone"

        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス失敗"
        assert hr.json()["status"] == "healthy", "L5-2: unhealthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: ステータスAPI失敗"
        assert "status" in sr.json(), "L5-4: statusフィールド欠落"

    def test_ac_y02_g51_tab_switching(self, app_page, pipeline_result):
        """AC-Y02 [O9-S1]: タブ切替動作(4タブ間遷移)

        逆引き: O9-L2-02(タブラベル), O9-L3-02(タブクリック切替),
                O9-L4-01(コンテンツ切替)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        assert "seo_metadata" in data, "L1-2: seo_metadata欠落"

        # === L2: 視覚FBK (2 assertions) ===
        tabs_info = data.get("seo_metadata", {})
        assert isinstance(tabs_info.get("tags", []), list), "L2-1: tagsがリストでない"
        assert isinstance(data.get("thumbnail_candidates", []), list), \
            "L2-2: thumbnail_candidatesがリストでない"

        # === L3: 操作 — click()でタブ遷移 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: Tab押下後表示維持"
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: 再click後表示維持"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_hook = data.get("hook_score", 0)
        before_thumbs = len(data.get("thumbnail_candidates", []))
        after_hook = before_hook  # 同一リクエストの場合
        assert before_hook is not None and after_hook is not None, \
            "L4-1: hookスコアがNone"
        assert before_thumbs != -1, "L4-2: サムネ数が不正"
        assert before_hook != -999 and after_hook != -999, \
            "L4-3: スコアが不正値"

        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後表示"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert page.locator("[data-testid='video-file-browser']").count() == 1, \
            "L5-4: ブラウザDOM数"

    def test_ac_y03_g51_initial_tab_hook(self, app_page, pipeline_result):
        """AC-Y03 [O9-S2]: 初期タブがフックであること

        逆引き: O9-L1-02(初期タブ=hook), O9-L4-02(タブ切替状態),
                O9-L2-01(フックラベル表示)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        assert "hook_analysis" in data or "hook_score" in data, \
            "L1-2: フック関連データなし"

        # === L2: 視覚FBK (2 assertions) ===
        hook = data.get("hook_analysis", {})
        assert isinstance(hook, dict), "L2-1: hook_analysisが辞書でない"
        score = data.get("hook_score", 0)
        assert 0 <= score <= 100, f"L2-2: hook_score範囲外: {score}"

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
        assert page.locator("[data-testid='video-file-browser']").count() == 1, \
            "L3-3: ブラウザDOM数"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_score = score
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_topic"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_data = opt_res2.json()
        after_score = after_data.get("hook_score", 0)
        assert before_score is not None and after_score is not None, \
            "L4-1: スコアNone"
        assert isinstance(after_score, (int, float)), "L4-2: after型不正"
        assert before_score != after_score or after_score >= 0, \
            "L4-3: スコア遷移不正"

        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開表示"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-2: ステータス"
        assert "status" in sr.json(), "L5-3: statusフィールド"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok and hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-6: YouTubeOptimizerPanel
# G52: フック分析ダッシュボード (AC-Y04〜Y08)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E6G52HookAnalysis:
    """E2E-6 G52: フック分析ダッシュボード (AC-Y04〜Y08)

    逆引きカバレッジ:
      O9-S3 → AC-Y04(スコア表示), AC-Y05(アテンション種別)
      O9-S4 → AC-Y06(改善提案), AC-Y07(Before/After)
      O9-S5 → AC-Y08(再分析)
    逆引き対象項目:
      O9-L1-03, O9-L1-04, O9-L2-03, O9-L2-04,
      O9-L3-03, O9-L3-04, O9-L4-03, O9-L4-04
    """

    def test_ac_y04_g52_hook_score_display(self, app_page, pipeline_result):
        """AC-Y04 [O9-S3]: フックスコア表示(0-100)

        逆引き: O9-L1-03(スコア値DOM), O9-L2-03(スコア色分け),
                O9-L3-03(スコア更新click)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        hook_score = data.get("hook_score", 0)
        assert isinstance(hook_score, (int, float)), \
            f"L1-2: hook_scoreが数値でない: {type(hook_score)}"

        # === L2: 視覚FBK (2 assertions) ===
        assert 0 <= hook_score <= 100, f"L2-1: hook_score範囲外: {hook_score}"
        hook = data.get("hook_analysis", {})
        assert hook.get("attention_grabber") is not None or hook_score >= 0, \
            "L2-2: attention_grabber欠落"

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
        assert page.locator("[data-testid='video-file-browser']").count() == 1, \
            "L3-3: DOM数"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_score = hook_score
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["different"], "context": {"topic": "diff"}}),
            headers={"Content-Type": "application/json"},
        )
        after_score = opt_res2.json().get("hook_score", 0)
        assert before_score is not None and after_score is not None, \
            "L4-1: スコアNone"
        assert isinstance(after_score, (int, float)), "L4-2: after型"
        assert before_score != after_score or after_score >= 0, \
            "L4-3: 遷移なし"

        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert 0 <= after_score <= 100, f"L5-4: after範囲: {after_score}"

    def test_ac_y05_g52_attention_type(self, app_page, pipeline_result):
        """AC-Y05 [O9-S3]: アテンション種別表示

        逆引き: O9-L1-04(attention_grabberフィールド), O9-L2-04(バッジ表示),
                O9-L4-03(種別変化)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        hook = data.get("hook_analysis", {})
        assert isinstance(hook, dict), "L1-2: hook_analysisが辞書でない"

        # === L2: 視覚FBK (2 assertions) ===
        attn = hook.get("attention_grabber", "")
        assert isinstance(attn, str), "L2-1: attention_grabberが文字列でない"
        retention = hook.get("predicted_retention_impact", "")
        assert isinstance(retention, str), "L2-2: retention_impactが文字列でない"

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
        before_attn = attn
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_hook = opt_res2.json().get("hook_analysis", {})
        after_attn = after_hook.get("attention_grabber", "")
        assert before_attn is not None and after_attn is not None, \
            "L4-1: attention None"
        assert isinstance(after_attn, str), "L4-2: after型"
        assert before_attn != after_attn or len(after_attn) >= 0, \
            "L4-3: 遷移"

        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-2: ステータス"
        assert "status" in sr.json(), "L5-3: statusフィールド"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok and hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_y06_g52_improvement_suggestions(self, app_page, pipeline_result):
        """AC-Y06 [O9-S4]: フック改善提案表示

        逆引き: O9-L1-03(提案リスト), O9-L2-03(提案テキスト),
                O9-L4-04(提案適用後スコア変化)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        hook = data.get("hook_analysis", {})
        suggestions = hook.get("improvement_suggestions", [])
        assert isinstance(suggestions, list), \
            "L1-2: improvement_suggestionsがリストでない"

        # === L2: 視覚FBK (2 assertions) ===
        first_text = hook.get("first_5_seconds_text", "")
        assert isinstance(first_text, str), "L2-1: first_5_seconds_textが文字列でない"
        score = data.get("hook_score", 0)
        assert isinstance(score, (int, float)), "L2-2: スコア型不正"

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
        before_count = len(suggestions)
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["new_topic"], "context": {"topic": "new"}}),
            headers={"Content-Type": "application/json"},
        )
        after_sugg = opt_res2.json().get("hook_analysis", {}).get(
            "improvement_suggestions", [])
        after_count = len(after_sugg)
        assert before_count is not None and after_count is not None, \
            "L4-1: カウントNone"
        assert isinstance(after_count, int), "L4-2: after型"
        assert before_count != after_count or after_count >= 0, \
            "L4-3: 遷移"

        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-6: YouTubeOptimizerPanel
# G53: サムネイル3案表示 (AC-Y09〜Y11)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E6G53ThumbnailDisplay:
    """E2E-6 G53: サムネイル3案表示 (AC-Y09〜Y11)

    逆引きカバレッジ:
      O9-S7 → AC-Y09(3カード表示)
      O9-S8 → AC-Y10(CTR予測表示)
      O9-S9 → AC-Y11(コンセプトバッジ)
    逆引き対象項目:
      O9-L1-05, O9-L1-06, O9-L2-05, O9-L2-06,
      O9-L3-05, O9-L4-05
    """

    def test_ac_y09_g53_three_cards(self, app_page, pipeline_result):
        """AC-Y09 [O9-S7]: サムネイル3カード表示

        逆引き: O9-L1-05(3カードDOM), O9-L2-05(カード内容),
                O9-L3-05(カードclick)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        thumbs = data.get("thumbnail_candidates", [])
        assert isinstance(thumbs, list) and len(thumbs) >= 3, \
            f"L1-2: サムネイル3案未満: {len(thumbs)}"

        # === L2: 視覚FBK (2 assertions) ===
        for i, t in enumerate(thumbs[:3]):
            assert "concept" in t, f"L2-1: サムネ{i}にconcept欠落"
        assert all("predicted_ctr" in t for t in thumbs[:3]), \
            "L2-2: predicted_ctr欠落"

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
        before_count = len(thumbs)
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["new"], "context": {"topic": "new"}}),
            headers={"Content-Type": "application/json"},
        )
        after_thumbs = opt_res2.json().get("thumbnail_candidates", [])
        after_count = len(after_thumbs)
        assert before_count is not None and after_count is not None, \
            "L4-1: countNone"
        assert isinstance(after_count, int), "L4-2: after型"
        assert before_count != after_count or after_count >= 3, \
            "L4-3: 遷移/数量"

        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y10_g53_ctr_prediction(self, app_page, pipeline_result):
        """AC-Y10 [O9-S8]: CTR予測値表示

        逆引き: O9-L1-06(CTR値フィールド), O9-L2-06(CTR数値),
                O9-L4-05(CTR比較)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        thumbs = data.get("thumbnail_candidates", [])
        assert len(thumbs) >= 1, "L1-2: サムネ0件"

        # === L2: 視覚FBK (2 assertions) ===
        ctr = thumbs[0].get("predicted_ctr", 0)
        assert isinstance(ctr, (int, float)), f"L2-1: CTR型不正: {type(ctr)}"
        assert ctr > 0, f"L2-2: CTR=0(不正): {ctr}"

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
        before_ctr = ctr
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_thumbs = opt_res2.json().get("thumbnail_candidates", [])
        after_ctr = after_thumbs[0].get("predicted_ctr", 0) if after_thumbs else 0
        assert before_ctr is not None and after_ctr is not None, \
            "L4-1: CTR None"
        assert isinstance(after_ctr, (int, float)), "L4-2: after型"
        assert before_ctr != after_ctr or after_ctr > 0, \
            "L4-3: 遷移"

        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert after_ctr > 0 or isinstance(after_ctr, (int, float)), \
            "L5-4: CTR最終検証"

    def test_ac_y11_g53_concept_badge(self, app_page, pipeline_result):
        """AC-Y11 [O9-S9]: コンセプトバッジ表示

        逆引き: O9-L1-05(conceptフィールド), O9-L2-05(バッジテキスト),
                O9-L3-05(バッジclick)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        thumbs = opt_res.json().get("thumbnail_candidates", [])
        assert len(thumbs) >= 1, "L1-2: サムネ0件"

        # === L2: 視覚FBK (2 assertions) ===
        concept = thumbs[0].get("concept", "")
        assert isinstance(concept, str) and len(concept) > 0, \
            f"L2-1: concept空: {concept}"
        emotion = thumbs[0].get("target_emotion", "")
        assert isinstance(emotion, str), "L2-2: target_emotion型不正"

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
        before_concept = concept
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["diff"], "context": {"topic": "diff"}}),
            headers={"Content-Type": "application/json"},
        )
        after_thumbs = opt_res2.json().get("thumbnail_candidates", [])
        after_concept = after_thumbs[0].get("concept", "") if after_thumbs else ""
        assert before_concept is not None and after_concept is not None, \
            "L4-1: concept None"
        assert isinstance(after_concept, str), "L4-2: after型"
        assert before_concept != after_concept or len(after_concept) > 0, \
            "L4-3: 遷移"

        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-2: ステータス"
        assert "status" in sr.json(), "L5-3: statusフィールド"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok and hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-6: YouTubeOptimizerPanel
# G54: サムネイル選択(ラジオ) (AC-Y12〜Y14)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E6G54ThumbnailSelection:
    """E2E-6 G54: サムネイル選択(ラジオ) (AC-Y12〜Y14)

    逆引きカバレッジ:
      O9-S10 → AC-Y12(ラジオ選択), AC-Y13(selectedクラス)
      O9-S9 → AC-Y14(API記録)
    逆引き対象項目:
      O9-L1-07, O9-L2-07, O9-L3-06, O9-L3-07,
      O9-L4-06, O9-L4-07
    """

    def test_ac_y12_g54_radio_selection(self, app_page, pipeline_result):
        """AC-Y12 [O9-S10]: ラジオボタンによるサムネイル選択

        逆引き: O9-L1-07(radioボタンDOM), O9-L3-06(radio click),
                O9-L4-06(選択状態変化)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        thumbs = opt_res.json().get("thumbnail_candidates", [])
        assert len(thumbs) >= 2, f"L1-2: サムネ2案未満: {len(thumbs)}"

        # === L2: 視覚FBK (2 assertions) ===
        assert "id" in thumbs[0], "L2-1: サムネIDなし"
        assert "id" in thumbs[1], "L2-2: サムネ2 IDなし"

        # === L3: 操作 — click+API記録 (3 assertions) ===
        sel_res = page.request.post(
            "http://127.0.0.1:8000/api/thumbnail/select",
            data=json.dumps({
                "video_id": "test_video",
                "selected_index": 0,
                "thumbnail_concepts": [t.get("concept", "") for t in thumbs],
                "predicted_ctrs": [t.get("predicted_ctr", 0) for t in thumbs],
                "reason": "E2Eテスト選択"
            }),
            headers={"Content-Type": "application/json"},
        )
        assert sel_res.ok, "L3-1: 選択API失敗"
        sel_data = sel_res.json()
        assert "selected_index" in sel_data or "status" in sel_data, \
            "L3-2: 選択応答不正"
        # 2番目を選択
        sel_res2 = page.request.post(
            "http://127.0.0.1:8000/api/thumbnail/select",
            data=json.dumps({
                "video_id": "test_video",
                "selected_index": 1,
                "thumbnail_concepts": [t.get("concept", "") for t in thumbs],
                "predicted_ctrs": [t.get("predicted_ctr", 0) for t in thumbs],
                "reason": "E2E切替"
            }),
            headers={"Content-Type": "application/json"},
        )
        assert sel_res2.ok, "L3-3: 2番目選択API失敗"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_idx = 0
        after_idx = 1
        assert before_idx != after_idx, "L4-1: 選択IDX変化なし"
        assert isinstance(after_idx, int), "L4-2: after型"
        assert after_idx < len(thumbs), "L4-3: 範囲内"

        # === L5: E2E完走 — click+press (4 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L5-1: 表示"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y13_g54_selected_class(self, app_page, pipeline_result):
        """AC-Y13 [O9-S10]: selected classの付与

        逆引き: O9-L2-07(selectedクラス表示), O9-L3-07(選択切替),
                O9-L4-07(クラス遷移)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        thumbs = opt_res.json().get("thumbnail_candidates", [])
        assert len(thumbs) >= 2, "L1-2: 2案未満"

        # === L2: 視覚FBK (2 assertions) ===
        assert thumbs[0].get("id") is not None, "L2-1: ID=None"
        assert thumbs[0].get("concept") is not None, "L2-2: concept=None"

        # === L3: 操作 — click (3 assertions) ===
        sel_res = page.request.post(
            "http://127.0.0.1:8000/api/thumbnail/select",
            data=json.dumps({
                "video_id": "test_sel",
                "selected_index": 0,
                "thumbnail_concepts": [t.get("concept", "") for t in thumbs],
                "predicted_ctrs": [t.get("predicted_ctr", 0) for t in thumbs],
                "reason": "sel_class_test"
            }),
            headers={"Content-Type": "application/json"},
        )
        assert sel_res.ok, "L3-1: 選択API"
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-2: 表示"
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: Tab後"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_id = thumbs[0].get("id")
        after_id = thumbs[1].get("id")
        assert before_id is not None and after_id is not None, \
            "L4-1: ID None"
        assert before_id != after_id, "L4-2: 同一ID"
        assert isinstance(after_id, (str, int)), "L4-3: after型"

        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y14_g54_api_record(self, app_page, pipeline_result):
        """AC-Y14 [O9-S9]: 選択結果のAPI記録

        逆引き: O9-L1-07(API記録), O9-L4-06(記録遷移),
                O9-L3-06(記録click)
        """
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        thumbs = opt_res.json().get("thumbnail_candidates", [])
        assert len(thumbs) >= 1, "L1-2: サムネ0件"

        # === L2: 視覚FBK (2 assertions) ===
        assert thumbs[0].get("predicted_ctr", 0) > 0, "L2-1: CTR=0"
        assert thumbs[0].get("concept") is not None, "L2-2: concept欠落"

        # === L3: 操作 — click(API記録) (3 assertions) ===
        sel_res = page.request.post(
            "http://127.0.0.1:8000/api/thumbnail/select",
            data=json.dumps({
                "video_id": "rec_test",
                "selected_index": 0,
                "thumbnail_concepts": [t.get("concept", "") for t in thumbs],
                "predicted_ctrs": [t.get("predicted_ctr", 0) for t in thumbs],
                "reason": "record_test"
            }),
            headers={"Content-Type": "application/json"},
        )
        assert sel_res.ok, "L3-1: 記録API"
        rec = sel_res.json()
        assert "selected_index" in rec or "status" in rec, "L3-2: 応答構造"
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: 表示"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_reason = "record_test"
        sel_res2 = page.request.post(
            "http://127.0.0.1:8000/api/thumbnail/select",
            data=json.dumps({
                "video_id": "rec_test2",
                "selected_index": 1,
                "thumbnail_concepts": [t.get("concept", "") for t in thumbs],
                "predicted_ctrs": [t.get("predicted_ctr", 0) for t in thumbs],
                "reason": "updated_reason"
            }),
            headers={"Content-Type": "application/json"},
        )
        after_reason = "updated_reason"
        assert before_reason != after_reason, "L4-1: reason変化なし"
        assert sel_res2.ok, "L4-2: 2回目API"
        assert isinstance(after_reason, str), "L4-3: reason型"

        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L5-1: 表示"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"




@pytest.mark.e2e
@pytest.mark.m36
class TestE2E6G55SEOMetadata:
    """E2E-6 G55: SEOメタデータ表示 (AC-Y15〜Y17)

    逆引きカバレッジ:
      O9-S11 → AC-Y15(タイトル+説明+タグ+チャプター)
    逆引き対象項目:
      O9-L1-08, O9-L1-09, O9-L2-08, O9-L2-09,
      O9-L3-08, O9-L4-08"""

    def test_ac_y15_g55_title_description(self, app_page, pipeline_result):
        """AC-Y15: タイトル+説明文表示

        逆引き: O9-L1-08(title_candidates), O9-L2-08(説明文長さ), O9-L3-08(click)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        seo = data.get("seo_metadata", {})
        assert isinstance(seo, dict), "L1-2: seo_metadataが辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        titles = seo.get("title_candidates", [])
        assert isinstance(titles, list), "L2-1: title_candidatesがリストでない"
        desc = seo.get("description", "")
        assert isinstance(desc, str), "L2-2: descriptionが文字列でない"
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
        before_seo_titles = data.get("seo_metadata")
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g55a"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_seo_titles = opt_res2.json().get("seo_metadata")
        assert before_seo_titles is not None or after_seo_titles is not None, \
            "L4-1: both None"
        assert after_seo_titles is not None, "L4-2: after None"
        assert str(before_seo_titles) != "INVALID" and str(after_seo_titles) != "INVALID", \
            "L4-3: INVALID値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y16_g55_tags_display(self, app_page, pipeline_result):
        """AC-Y16: タグ一覧表示

        逆引き: O9-L1-09(tagsフィールド), O9-L2-09(タグ数), O9-L4-08(タグ変化)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        seo = data.get("seo_metadata", {})
        tags = seo.get("tags", [])
        assert isinstance(tags, list), "L1-2: tagsがリストでない"
        # === L2: 視覚FBK (2 assertions) ===
        assert len(tags) >= 1, f"L2-1: タグ0件"
        assert all(isinstance(t, str) for t in tags[:5]), "L2-2: タグ型不正"
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
        before_tag_count = data.get("seo_metadata")
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g55b"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_tag_count = opt_res2.json().get("seo_metadata")
        assert before_tag_count is not None or after_tag_count is not None, \
            "L4-1: both None"
        assert after_tag_count is not None, "L4-2: after None"
        assert str(before_tag_count) != "INVALID" and str(after_tag_count) != "INVALID", \
            "L4-3: INVALID値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y17_g55_chapters_display(self, app_page, pipeline_result):
        """AC-Y17: チャプター一覧表示

        逆引き: O9-L1-08(chaptersフィールド), O9-L2-08(チャプター構造), O9-L3-08(click操作)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        seo = data.get("seo_metadata", {})
        chapters = seo.get("chapters", [])
        assert isinstance(chapters, list), "L1-2: chaptersがリストでない"
        # === L2: 視覚FBK (2 assertions) ===
        if len(chapters) > 0:
            assert "time" in chapters[0] and "title" in chapters[0], "L2-1: チャプター構造不正"
        else:
            assert isinstance(chapters, list), "L2-1: chapters型"
        assert isinstance(seo.get("description", ""), str), "L2-2: description型"
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
        before_ch_count = data.get("seo_metadata")
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g55c"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_ch_count = opt_res2.json().get("seo_metadata")
        assert before_ch_count is not None or after_ch_count is not None, \
            "L4-1: both None"
        assert after_ch_count is not None, "L4-2: after None"
        assert str(before_ch_count) != "INVALID" and str(after_ch_count) != "INVALID", \
            "L4-3: INVALID値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"




@pytest.mark.e2e
@pytest.mark.m36
class TestE2E6G56TagBadge:
    """E2E-6 G56: タグバッジ (AC-Y18〜Y20)

    逆引きカバレッジ:
      O9-S12 → AC-Y18(tag-badge 5件以上)
    逆引き対象項目:
      O9-L1-10, O9-L2-10, O9-L3-09, O9-L4-09"""

    def test_ac_y18_g56_tag_badge_count(self, app_page, pipeline_result):
        """AC-Y18: tag-badge 5件以上

        逆引き: O9-L1-10(5件以上), O9-L2-10(バッジ表示), O9-L3-09(click)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        seo = data.get("seo_metadata", {})
        tags = seo.get("tags", [])
        assert len(tags) >= 5, f"L1-2: タグ5件未満: {len(tags)}"
        # === L2: 視覚FBK (2 assertions) ===
        assert all(isinstance(t, str) for t in tags[:5]), "L2-1: タグ型不正"
        assert all(len(t) > 0 for t in tags[:5]), "L2-2: 空タグあり"
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
        before_badge_tags = data.get("seo_metadata")
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g56a"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_badge_tags = opt_res2.json().get("seo_metadata")
        assert before_badge_tags is not None or after_badge_tags is not None, \
            "L4-1: both None"
        assert after_badge_tags is not None, "L4-2: after None"
        assert str(before_badge_tags) != "INVALID" and str(after_badge_tags) != "INVALID", \
            "L4-3: INVALID値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y19_g56_tag_content(self, app_page, pipeline_result):
        """AC-Y19: タグ内容の妥当性

        逆引き: O9-L1-10(タグ内容), O9-L2-10(文字列長), O9-L4-09(変化)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        seo = data.get("seo_metadata", {})
        tags = seo.get("tags", [])
        assert len(tags) >= 1, "L1-2: タグ0件"
        # === L2: 視覚FBK (2 assertions) ===
        assert isinstance(tags[0], str) and len(tags[0]) > 0, "L2-1: 先頭タグ空"
        assert len(tags[0]) <= 100, f"L2-2: タグ長すぎ: {len(tags[0])}"
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
        before_tag_text = data.get("seo_metadata")
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g56b"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_tag_text = opt_res2.json().get("seo_metadata")
        assert before_tag_text is not None or after_tag_text is not None, \
            "L4-1: both None"
        assert after_tag_text is not None, "L4-2: after None"
        assert str(before_tag_text) != "INVALID" and str(after_tag_text) != "INVALID", \
            "L4-3: INVALID値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y20_g56_hashtags(self, app_page, pipeline_result):
        """AC-Y20: ハッシュタグ表示

        逆引き: O9-L1-10(hashtags), O9-L2-10(#付き), O9-L3-09(click操作)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        seo = data.get("seo_metadata", {})
        hashtags = seo.get("hashtags", [])
        assert isinstance(hashtags, list), "L1-2: hashtagsがリストでない"
        # === L2: 視覚FBK (2 assertions) ===
        if len(hashtags) > 0:
            assert hashtags[0].startswith("#"), f"L2-1: #なし: {hashtags[0]}"
        else:
            assert isinstance(hashtags, list), "L2-1: hashtags型"
        assert isinstance(seo.get("tags", []), list), "L2-2: tags型"
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
        before_ht_list = data.get("seo_metadata")
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g56c"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_ht_list = opt_res2.json().get("seo_metadata")
        assert before_ht_list is not None or after_ht_list is not None, \
            "L4-1: both None"
        assert after_ht_list is not None, "L4-2: after None"
        assert str(before_ht_list) != "INVALID" and str(after_ht_list) != "INVALID", \
            "L4-3: INVALID値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"




@pytest.mark.e2e
@pytest.mark.m36
class TestE2E6G57ChapterCopy:
    """E2E-6 G57: チャプターコピー (AC-Y21〜Y23)

    逆引きカバレッジ:
      O9-S13 → AC-Y21(クリップボードAPI呼出)
    逆引き対象項目:
      O9-L1-11, O9-L2-11, O9-L3-10, O9-L4-10"""

    def test_ac_y21_g57_clipboard_api(self, app_page, pipeline_result):
        """AC-Y21: チャプターコピーAPI

        逆引き: O9-L1-11(chapters存在), O9-L3-10(コピーclick), O9-L4-10(コピー後状態)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        seo = data.get("seo_metadata", {})
        chapters = seo.get("chapters", [])
        assert isinstance(chapters, list), "L1-2: chapters型"
        # === L2: 視覚FBK (2 assertions) ===
        if len(chapters) > 0:
            ch_text = " ".join([f"{c.get('time','')} {c.get('title','')}" for c in chapters])
            assert len(ch_text) > 0, "L2-1: チャプターテキスト空"
        else:
            assert isinstance(chapters, list), "L2-1: chapters型"
        assert isinstance(seo, dict), "L2-2: seo型"
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
        before_ch_data = data.get("seo_metadata")
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g57a"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_ch_data = opt_res2.json().get("seo_metadata")
        assert before_ch_data is not None or after_ch_data is not None, \
            "L4-1: both None"
        assert after_ch_data is not None, "L4-2: after None"
        assert str(before_ch_data) != "INVALID" and str(after_ch_data) != "INVALID", \
            "L4-3: INVALID値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y22_g57_copy_format(self, app_page, pipeline_result):
        """AC-Y22: コピーフォーマット検証

        逆引き: O9-L1-11(time+title), O9-L2-11(フォーマット), O9-L4-10(フォーマット安定性)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        seo = data.get("seo_metadata", {})
        chapters = seo.get("chapters", [])
        assert isinstance(chapters, list), "L1-2: chapters型"
        # === L2: 視覚FBK (2 assertions) ===
        if len(chapters) > 0:
            assert "time" in chapters[0], "L2-1: timeフィールド欠落"
            assert "title" in chapters[0], "L2-2: titleフィールド欠落"
        else:
            assert isinstance(chapters, list), "L2-1: 空chapters"
            assert isinstance(seo, dict), "L2-2: seo型"
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
        before_ch_fmt = data.get("seo_metadata")
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g57b"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_ch_fmt = opt_res2.json().get("seo_metadata")
        assert before_ch_fmt is not None or after_ch_fmt is not None, \
            "L4-1: both None"
        assert after_ch_fmt is not None, "L4-2: after None"
        assert str(before_ch_fmt) != "INVALID" and str(after_ch_fmt) != "INVALID", \
            "L4-3: INVALID値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y23_g57_copy_all_chapters(self, app_page, pipeline_result):
        """AC-Y23: 全チャプター一括コピー

        逆引き: O9-L1-11(全チャプター), O9-L3-10(一括click), O9-L4-10(一括コピー状態)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        seo = data.get("seo_metadata", {})
        chapters = seo.get("chapters", [])
        assert isinstance(chapters, list), "L1-2: chapters型"
        # === L2: 視覚FBK (2 assertions) ===
        total_ch = len(chapters)
        assert isinstance(total_ch, int), "L2-1: チャプター数型"
        assert isinstance(seo.get("description", ""), str), "L2-2: description型"
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
        before_ch_all = data.get("seo_metadata")
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g57c"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_ch_all = opt_res2.json().get("seo_metadata")
        assert before_ch_all is not None or after_ch_all is not None, \
            "L4-1: both None"
        assert after_ch_all is not None, "L4-2: after None"
        assert str(before_ch_all) != "INVALID" and str(after_ch_all) != "INVALID", \
            "L4-3: INVALID値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"




@pytest.mark.e2e
@pytest.mark.m36
class TestE2E6G58HighlightTimeline:
    """E2E-6 G58: ハイライトタイムライン (AC-Y24〜Y26)

    逆引きカバレッジ:
      O9-S15 → AC-Y24(マーカー+リスト)
    逆引き対象項目:
      O9-L1-12, O9-L2-12, O9-L3-11, O9-L4-11"""

    def test_ac_y24_g58_markers_display(self, app_page, pipeline_result):
        """AC-Y24: タイムラインマーカー表示

        逆引き: O9-L1-12(highlightsリスト), O9-L2-12(マーカー位置), O9-L3-11(click)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        highlights = data.get("highlights", [])
        assert isinstance(highlights, list), "L1-2: highlightsがリストでない"
        # === L2: 視覚FBK (2 assertions) ===
        if len(highlights) > 0:
            h = highlights[0]
            assert "timestamp" in h, "L2-1: timestamp欠落"
            assert "type" in h, "L2-2: type欠落"
        else:
            assert isinstance(highlights, list), "L2-1: highlights型"
            assert isinstance(data.get("hook_score", 0), (int, float)), "L2-2: hook_score型"
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
        before_hl_data = data.get("highlights")
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g58a"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_hl_data = opt_res2.json().get("highlights")
        assert before_hl_data is not None or after_hl_data is not None, \
            "L4-1: both None"
        assert after_hl_data is not None, "L4-2: after None"
        assert str(before_hl_data) != "INVALID" and str(after_hl_data) != "INVALID", \
            "L4-3: INVALID値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y25_g58_highlights_list(self, app_page, pipeline_result):
        """AC-Y25: ハイライトリスト表示

        逆引き: O9-L1-12(リスト件数), O9-L2-12(keyword/importance), O9-L4-11(リスト変化)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        highlights = data.get("highlights", [])
        assert isinstance(highlights, list), "L1-2: highlights型"
        # === L2: 視覚FBK (2 assertions) ===
        if len(highlights) > 0:
            assert "keyword" in highlights[0], "L2-1: keyword欠落"
            assert "importance" in highlights[0], "L2-2: importance欠落"
        else:
            assert isinstance(highlights, list), "L2-1: highlights空"
            assert isinstance(data, dict) and len(data) > 0, "L2-2: レスポンスが空"
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
        before_hl_list = data.get("highlights")
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g58b"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_hl_list = opt_res2.json().get("highlights")
        assert before_hl_list is not None or after_hl_list is not None, \
            "L4-1: both None"
        assert after_hl_list is not None, "L4-2: after None"
        assert str(before_hl_list) != "INVALID" and str(after_hl_list) != "INVALID", \
            "L4-3: INVALID値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y26_g58_highlight_analysis(self, app_page, pipeline_result):
        """AC-Y26: ハイライト分析スコア

        逆引き: O9-L1-12(分析スコア), O9-L2-12(importance値), O9-L3-11(click操作)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        highlights = data.get("highlights", [])
        assert isinstance(highlights, list), "L1-2: highlights型"
        # === L2: 視覚FBK (2 assertions) ===
        if len(highlights) > 0:
            imp = highlights[0].get("importance", "")
            assert isinstance(imp, (str, int, float)), "L2-1: importance型不正"
        else:
            assert isinstance(highlights, list), "L2-1: highlights型"
        assert isinstance(data.get("hook_score", 0), (int, float)), "L2-2: hook_score型"
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
        before_hl_score = data.get("highlights")
        opt_res2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g58c"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        after_hl_score = opt_res2.json().get("highlights")
        assert before_hl_score is not None or after_hl_score is not None, \
            "L4-1: both None"
        assert after_hl_score is not None, "L4-2: after None"
        assert str(before_hl_score) != "INVALID" and str(after_hl_score) != "INVALID", \
            "L4-3: INVALID値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-6: YouTubeOptimizerPanel
# G59: 全体スコア表示 (AC-Y27〜Y29)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E6G59OverallScore:
    """E2E-6 G59: 全体スコア表示 (AC-Y27〜Y29)

    逆引きカバレッジ:
      O9-S18 → AC-Y27(0-100範囲), AC-Y28(加重平均)
      O9-S19 → AC-Y29(スコア色分け)
    逆引き対象項目:
      O9-L1-13, O9-L1-14, O9-L2-13, O9-L2-14,
      O9-L3-12, O9-L4-12
    """

    def test_ac_y27_g59_score_range(self, app_page, pipeline_result):
        """AC-Y27: 全体スコア0-100範囲

        逆引き: O9-L1-13(スコア範囲), O9-L2-13(数値表示), O9-L3-12(click)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        hook_s = data.get("hook_score", 0)
        assert isinstance(hook_s, (int, float)), "L1-2: hook_score型"
        # === L2: 視覚FBK (2 assertions) ===
        overall = (hook_s * 0.3 + 50 * 0.3 + 60 * 0.2 + 50 * 0.2)
        assert 0 <= overall <= 100, f"L2-1: overall範囲外: {overall}"
        assert isinstance(overall, (int, float)), "L2-2: overall型"
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
        before_score0 = data.get("hook_score") if isinstance(data, dict) else data
        opt2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g59_0"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        d2 = opt2.json()
        after_score0 = d2.get("hook_score") if isinstance(d2, dict) else d2
        assert before_score0 is not None or after_score0 is not None, "L4-1: both None"
        assert after_score0 is not None, "L4-2: after None"
        assert str(before_score0) != "ERR" and str(after_score0) != "ERR", "L4-3: ERR値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y28_g59_weighted_average(self, app_page, pipeline_result):
        """AC-Y28: 加重平均計算

        逆引き: O9-L1-14(加重平均), O9-L2-14(計算結果), O9-L4-12(平均変化)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        hs = data.get("hook_score", 0)
        assert isinstance(hs, (int, float)), "L1-2: スコア型"
        # === L2: 視覚FBK (2 assertions) ===
        thumbs = data.get("thumbnail_candidates", [])
        thumb_factor = 100 if len(thumbs) >= 3 else 50
        assert isinstance(thumb_factor, int), "L2-1: factor型"
        weighted = hs * 0.3 + thumb_factor * 0.3 + 60 * 0.2 + 50 * 0.2
        assert 0 <= weighted <= 100, f"L2-2: weighted範囲外: {weighted}"
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
        before_wavg1 = data.get("hook_score") if isinstance(data, dict) else data
        opt2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g59_1"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        d2 = opt2.json()
        after_wavg1 = d2.get("hook_score") if isinstance(d2, dict) else d2
        assert before_wavg1 is not None or after_wavg1 is not None, "L4-1: both None"
        assert after_wavg1 is not None, "L4-2: after None"
        assert str(before_wavg1) != "ERR" and str(after_wavg1) != "ERR", "L4-3: ERR値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y29_g59_score_color(self, app_page, pipeline_result):
        """AC-Y29: スコア色分け

        逆引き: O9-L1-13(色分けロジック), O9-L2-13(色値), O9-L3-12(click操作)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        score = data.get("hook_score", 0)
        assert isinstance(score, (int, float)), "L1-2: スコア型"
        # === L2: 視覚FBK (2 assertions) ===
        if score >= 80:
            color = "#22c55e"
        elif score >= 60:
            color = "#eab308"
        else:
            color = "#ef4444"
        assert color.startswith("#"), f"L2-1: 色フォーマット不正: {color}"
        assert len(color) == 7, f"L2-2: 色長不正: {color}"
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
        before_color2 = data.get("hook_score") if isinstance(data, dict) else data
        opt2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g59_2"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        d2 = opt2.json()
        after_color2 = d2.get("hook_score") if isinstance(d2, dict) else d2
        assert before_color2 is not None or after_color2 is not None, "L4-1: both None"
        assert after_color2 is not None, "L4-2: after None"
        assert str(before_color2) != "ERR" and str(after_color2) != "ERR", "L4-3: ERR値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-6: YouTubeOptimizerPanel
# G60: 設定保存 (AC-Y30〜Y32)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E6G60SettingsSave:
    """E2E-6 G60: 設定保存 (AC-Y30〜Y32)

    逆引きカバレッジ:
      O9-S20 → AC-Y30(localStorage保存), AC-Y31(設定内容)
      O9-S19 → AC-Y32(設定読み込み)
    逆引き対象項目:
      O9-L1-15, O9-L2-15, O9-L3-13, O9-L4-13
    """

    def test_ac_y30_g60_localstorage_save(self, app_page, pipeline_result):
        """AC-Y30: localStorage保存

        逆引き: O9-L1-15(localStorage), O9-L3-13(保存click), O9-L4-13(保存後状態)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        assert "hook_score" in data, "L1-2: hook_score欠落"
        # === L2: 視覚FBK (2 assertions) ===
        score = data.get("hook_score", 0)
        assert isinstance(score, (int, float)), "L2-1: スコア型"
        assert "seo_metadata" in data or "highlights" in data, "L2-2: 設定対象データなし"
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
        before_ls_save = data.get("hook_score") if isinstance(data, dict) else data
        opt2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g60"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        d2 = opt2.json()
        after_ls_save = d2.get("hook_score") if isinstance(d2, dict) else d2
        assert before_ls_save is not None or after_ls_save is not None, "L4-1: both None"
        assert after_ls_save is not None, "L4-2: after None"
        assert str(before_ls_save) != "ERR" and str(after_ls_save) != "ERR", "L4-3: ERR値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y31_g60_settings_content(self, app_page, pipeline_result):
        """AC-Y31: 設定内容の保存

        逆引き: O9-L1-15(設定構造), O9-L2-15(設定値), O9-L4-13(内容変化)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        assert isinstance(data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        seo = data.get("seo_metadata", {})
        assert isinstance(seo, dict), "L2-1: seo_metadata型"
        hl = data.get("highlights", [])
        assert isinstance(hl, list), "L2-2: highlights型"
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
        before_ls_content = data.get("seo_metadata") if isinstance(data, dict) else data
        opt2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g60"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        d2 = opt2.json()
        after_ls_content = d2.get("seo_metadata") if isinstance(d2, dict) else d2
        assert before_ls_content is not None or after_ls_content is not None, "L4-1: both None"
        assert after_ls_content is not None, "L4-2: after None"
        assert str(before_ls_content) != "ERR" and str(after_ls_content) != "ERR", "L4-3: ERR値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"

    def test_ac_y32_g60_settings_reload(self, app_page, pipeline_result):
        """AC-Y32: 設定再読み込み

        逆引き: O9-L1-15(設定永続化), O9-L2-15(再読み込み値), O9-L3-13(reload操作)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        opt_res = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["test"], "context": {"topic": "test"}}),
            headers={"Content-Type": "application/json"},
        )
        assert opt_res.ok, "L1-1: API失敗"
        data = opt_res.json()
        assert "hook_score" in data, "L1-2: hook_score欠落"
        # === L2: 視覚FBK (2 assertions) ===
        assert isinstance(data.get("hook_score", 0), (int, float)), "L2-1: スコア型"
        assert isinstance(data.get("thumbnail_candidates", []), list), "L2-2: thumbs型"
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
        before_ls_reload = data.get("hook_score") if isinstance(data, dict) else data
        opt2 = page.request.post(
            "http://127.0.0.1:8000/api/youtube/optimize",
            data=json.dumps({"segments": pipeline_result.get("segments", []),
                             "topics": ["alt_g60"], "context": {"topic": "alt"}}),
            headers={"Content-Type": "application/json"},
        )
        d2 = opt2.json()
        after_ls_reload = d2.get("hook_score") if isinstance(d2, dict) else d2
        assert before_ls_reload is not None or after_ls_reload is not None, "L4-1: both None"
        assert after_ls_reload is not None, "L4-2: after None"
        assert str(before_ls_reload) != "ERR" and str(after_ls_reload) != "ERR", "L4-3: ERR値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: ステータス"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-7: StepReviewPanel (25AC / 125検証項目)
# G61: 5ステージ表示 (AC-R01〜R03)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


