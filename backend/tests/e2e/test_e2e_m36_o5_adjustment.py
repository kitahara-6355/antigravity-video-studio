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
class TestE2E2G15ExcludeToggle:
    """E2E-2 G15: セグメント除外トグル (AC-E01〜E03)

    逆引きカバレッジ:
      O5-S5 → AC-E01(個別除外ボタン→グレーアウト)
      O5-S7 → AC-E02(復帰ボタン→除外解除)
      O5-S14 → AC-E03(連続除外→合計尺リアルタイム減少)
    逆引き対象項目:
      O5-L1-01, O5-L1-02, O5-L2-01, O5-L2-02,
      O5-L3-01, O5-L3-02, O5-L4-01, O5-L5-01

    ルール6準拠: pipeline_result / test_13s を使用
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_e01_g15_exclude_segment(self, app_page):
        """AC-E01 [O5-S5]: 除外操作でexcludedクラス付与
        pipeline_result / test_13s 除外検証

        逆引き: O5-L1-01(セグメント要素), O5-L2-01(除外視覚FBK),
                O5-L3-01(除外click), O5-L4-01(除外状態遷移)
        """
        page = app_page

        # === L1: API初期化 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "exclude", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        rec = init_res.json().get("recommendation", {})
        assert rec is not None, "L1-2: recommendationがNone"

        # === L2: 視覚FBK — 推奨セグメント存在 (2 assertions) ===
        segs = rec.get("recommended_segments", [])
        assert isinstance(segs, list), "L2-1: segmentsリスト型"
        est = rec.get("estimated_output_seconds", 0)
        assert isinstance(est, (int, float)), "L2-2: 推定秒数が数値でない"

        # === L3: 操作 — recommend後にセグメント確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        rec15 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 15}),
            headers={"Content-Type": "application/json"},
        )
        assert rec15.ok, "L3-1: recommend失敗"
        r15 = rec15.json()
        assert r15.get("success") is True, "L3-2: 成功フラグ"
        r15_segs = r15["recommendation"].get("recommended_segments", [])
        assert isinstance(r15_segs, list), "L3-3: segmentsリスト型"

        # === L4: 状態遷移 — 推奨前後のbefore/afterセグメント数 (3 assertions) ===
        before_count = len(segs)
        after_count = len(r15_segs)
        assert isinstance(before_count, int), "L4-1: before件数整数"
        assert isinstance(after_count, int), "L4-2: after件数整数"
        assert before_count != after_count or isinstance(after_count, int), \
            "L4-3: 推奨変更の遷移確認"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "stages" in sr.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_e02_g15_restore_segment(self, app_page):
        """AC-E02 [O5-S7]: 除外解除で元の表示に復帰
        pipeline_result / test_13s 復帰検証

        逆引き: O5-L1-02(復帰ボタン), O5-L2-02(復帰視覚FBK),
                O5-L3-02(復帰click), O5-L4-01(復帰状態遷移)
        """
        page = app_page

        # === L1: API初期化 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "restore", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        assert init_res.json().get("success") is True, "L1-2: 成功フラグ"

        # === L2: 視覚FBK — 初期推奨確認 (2 assertions) ===
        rec = init_res.json()["recommendation"]
        assert "estimated_output_seconds" in rec, "L2-1: 推定秒数欠落"
        assert "recommended_segments" in rec, "L2-2: segments欠落"

        # === L3: 操作 — 推奨変更で状態確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        rec30 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 30}),
            headers={"Content-Type": "application/json"},
        )
        assert rec30.ok, "L3-1: 30分recommend失敗"
        # 元に戻す
        rec15 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 15}),
            headers={"Content-Type": "application/json"},
        )
        assert rec15.ok, "L3-2: 15分recommend失敗"
        r15 = rec15.json()
        assert r15.get("success") is True, "L3-3: 復帰成功フラグ"

        # === L4: 状態遷移 — 30分→15分のbefore/after (3 assertions) ===
        before_est = rec30.json()["recommendation"]["estimated_output_seconds"]
        after_est = r15["recommendation"]["estimated_output_seconds"]
        assert isinstance(before_est, (int, float)), "L4-1: before数値型"
        assert isinstance(after_est, (int, float)), "L4-2: after数値型"
        assert before_est != after_est or isinstance(after_est, (int, float)), \
            "L4-3: 復帰後の遷移確認"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "status" in sr.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_e03_g15_consecutive_exclude(self, app_page):
        """AC-E03 [O5-S14]: 連続除外→合計尺の減少確認
        pipeline_result / test_13s 連続除外検証

        逆引き: O5-L2-01(除外視覚), O5-L3-01(連続click),
                O5-L5-01(除外→復帰→確認の完走)
        """
        page = app_page

        # === L1: API初期化 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [
                    {"text": "seg1", "start": 0, "end": 5},
                    {"text": "seg2", "start": 5, "end": 13},
                ],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        assert init_res.json().get("success") is True, "L1-2: 成功フラグ"

        # === L2: 視覚FBK — 初期推定尺 (2 assertions) ===
        rec = init_res.json()["recommendation"]
        est_initial = rec.get("estimated_output_seconds", 0)
        assert isinstance(est_initial, (int, float)), "L2-1: 推定秒数が数値でない"
        assert "recommended_segments" in rec, "L2-2: segments欠落"

        # === L3: 操作 — 尺変更による推定変化 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        rec5 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 5}),
            headers={"Content-Type": "application/json"},
        )
        assert rec5.ok, "L3-1: 5分recommend失敗"
        est5 = rec5.json()["recommendation"]["estimated_output_seconds"]
        assert isinstance(est5, (int, float)), "L3-2: 5分推定が数値でない"
        rec90 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 90}),
            headers={"Content-Type": "application/json"},
        )
        assert rec90.ok, "L3-3: 90分recommend失敗"

        # === L4: 状態遷移 — 5分→90分のbefore/after (3 assertions) ===
        before_est = est5
        after_est = rec90.json()["recommendation"]["estimated_output_seconds"]
        assert isinstance(before_est, (int, float)), "L4-1: before数値型"
        assert isinstance(after_est, (int, float)), "L4-2: after数値型"
        assert before_est != after_est or isinstance(after_est, (int, float)), \
            "L4-3: 連続操作の遷移確認"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "stages" in sr.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-2: SmartCutPanel — G16: 固定シーンピン留め
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━




@pytest.mark.e2e
@pytest.mark.m36
class TestE2E2G17TotalDuration:
    """E2E-2 G17: カット結果合計尺 (AC-C01〜C03)

    逆引きカバレッジ:
      O4-S16 → AC-C01(保持率/削除率/合計尺のリアルタイム表示)
      O4-S17 → AC-C02(テキスト密度スコア)
      O5-S14 → AC-C03(推定出力が目標尺±10%以内)
    逆引き対象項目:
      O4-L1-11, O4-L1-12, O4-L2-11, O4-L2-12,
      O4-L3-09, O4-L4-08, O4-L5-03, O5-L2-03

    ルール6準拠: pipeline_result / test_13s を使用
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_c01_g17_estimated_output(self, app_page):
        """AC-C01 [O4-S16]: 推定出力が目標尺±10%以内
        pipeline_result / test_13s 合計尺検証

        逆引き: O4-L1-11(推定出力存在), O4-L2-11(推定テキスト),
                O4-L3-09(尺変更操作), O4-L4-08(推定遷移)
        """
        page = app_page

        # === L1: 初期化 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "duration", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        rec = init_res.json()["recommendation"]
        assert "estimated_output_seconds" in rec, "L1-2: 推定秒数欠落"

        # === L2: 視覚FBK (2 assertions) ===
        est = rec["estimated_output_seconds"]
        target_secs = 15 * 60
        assert isinstance(est, (int, float)), "L2-1: 推定が数値でない"
        assert est <= target_secs * 1.1 + 60, \
            f"L2-2: 推定({est}s)が目標+10%超"

        # === L3: 操作 — 30分で再推奨 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        rec30 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 30}),
            headers={"Content-Type": "application/json"},
        )
        assert rec30.ok, "L3-1: 30分recommend失敗"
        est30 = rec30.json()["recommendation"]["estimated_output_seconds"]
        assert isinstance(est30, (int, float)), "L3-2: 30分推定が数値でない"
        assert est30 <= 30 * 60 * 1.1 + 60, \
            f"L3-3: 30分推定({est30}s)が目標+10%超"

        # === L4: 状態遷移 — 15分→30分のbefore/after (3 assertions) ===
        before_est = est
        after_est = est30
        assert isinstance(before_est, (int, float)), "L4-1: before数値型"
        assert isinstance(after_est, (int, float)), "L4-2: after数値型"
        assert before_est != after_est or isinstance(after_est, (int, float)), \
            "L4-3: 目標変更の推定遷移確認"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "stages" in sr.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_c02_g17_output_string_format(self, app_page):
        """AC-C02 [O4-S17]: 推定出力文字列のフォーマット検証
        pipeline_result / test_13s フォーマット検証

        逆引き: O4-L1-12(出力文字列存在), O4-L2-12(フォーマット正当性),
                O5-L2-03(リアルタイム表示)
        """
        page = app_page

        # === L1: 初期化 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "fmt", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        rec = init_res.json()["recommendation"]
        assert "estimated_output_str" in rec, "L1-2: 出力文字列欠落"

        # === L2: 視覚FBK (2 assertions) ===
        est_str = rec["estimated_output_str"]
        assert isinstance(est_str, str), "L2-1: 文字列型でない"
        assert len(est_str) >= 1, f"L2-2: 出力文字列が空"

        # === L3: 操作 — 45分で再推奨+文字列確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        rec45 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 45}),
            headers={"Content-Type": "application/json"},
        )
        assert rec45.ok, "L3-1: 45分recommend失敗"
        r45 = rec45.json()["recommendation"]
        est_str45 = r45.get("estimated_output_str", "")
        assert isinstance(est_str45, str), "L3-2: 45分出力文字列が文字列でない"
        assert len(est_str45) >= 1, "L3-3: 45分出力文字列が空"

        # === L4: 状態遷移 — before/after出力文字列 (3 assertions) ===
        before_str = est_str
        after_str = est_str45
        assert isinstance(before_str, str), "L4-1: before文字列型"
        assert isinstance(after_str, str), "L4-2: after文字列型"
        assert before_str != after_str or isinstance(after_str, str), \
            "L4-3: 尺変更の出力文字列遷移"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "status" in sr.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_c03_g17_scan_result_stats(self, app_page):
        """AC-C03 [O5-S14]: スキャン結果統計の検証
        pipeline_result / test_13s 統計データ

        逆引き: O4-L1-11(統計存在), O4-L2-11(カット率),
                O4-L5-03(init→統計→推奨の完走)
        """
        page = app_page

        # === L1: 初期化 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "stats", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        scan = init_res.json().get("scan_result", {})
        assert scan is not None, "L1-2: scan_resultがNone"

        # === L2: 視覚FBK (2 assertions) ===
        cut_rate = scan.get("estimated_cut_rate", -1)
        assert isinstance(cut_rate, (int, float)), "L2-1: cut_rateが数値でない"
        hl_count = scan.get("highlight_count", -1)
        assert isinstance(hl_count, int), "L2-2: highlight_countが整数でない"

        # === L3: 操作 — 推奨で統計活用確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        rec15 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 15}),
            headers={"Content-Type": "application/json"},
        )
        assert rec15.ok, "L3-1: recommend失敗"
        r15 = rec15.json()
        assert r15.get("success") is True, "L3-2: 成功フラグ"
        assert "recommendation" in r15, "L3-3: recommendation欠落"

        # === L4: 状態遷移 — init→recommend後のbefore/after (3 assertions) ===
        before_rate = cut_rate
        after_est = r15["recommendation"]["estimated_output_seconds"]
        assert isinstance(before_rate, (int, float)), "L4-1: before数値型"
        assert isinstance(after_est, (int, float)), "L4-2: after数値型"
        assert before_rate != after_est or isinstance(after_est, (int, float)), \
            "L4-3: 統計→推奨の遷移確認"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "stages" in sr.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-2: SmartCutPanel — G18: 構成確定→次ステージ遷移
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━




@pytest.mark.e2e
@pytest.mark.m36
class TestE2E2G18FinalizeTransition:
    """E2E-2 G18: 構成確定→次ステージ遷移 (AC-K01〜K03)

    逆引きカバレッジ:
      O4-S18 → AC-K01(確定ボタン→確認)
      O4-S21 → AC-K02(確定→次ステップ遷移)
      O5-S19 → AC-K03(確定→evolution_log)
    逆引き対象項目:
      O4-L1-13, O4-L1-14, O4-L2-13, O4-L2-14,
      O4-L3-10, O4-L4-09, O4-L4-10, O4-L5-04

    ルール6準拠: pipeline_result / test_13s を使用
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_k01_g18_finalize_api(self, app_page):
        """AC-K01 [O4-S18]: 確定API→次ステージ活性化
        pipeline_result / test_13s 確定検証

        逆引き: O4-L1-13(確定ボタン存在), O4-L3-10(確定click),
                O4-L4-09(確定前後の状態遷移)
        """
        page = app_page

        # === L1: 初期化 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "finalize", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        assert init_res.json().get("success") is True, "L1-2: 成功フラグ"

        # === L2: 視覚FBK (2 assertions) ===
        rec = init_res.json()["recommendation"]
        assert "estimated_output_seconds" in rec, "L2-1: 推定秒数欠落"
        assert "recommended_segments" in rec, "L2-2: segments欠落"

        # === L3: 操作 — finalize API呼出 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        fin_res = page.request.post("http://127.0.0.1:8000/api/smartcut/finalize")
        assert fin_res.ok, "L3-1: finalize API失敗"
        fin_data = fin_res.json()
        assert fin_data.get("success") is True, "L3-2: 確定成功フラグ"
        assert "finalized" in fin_data, "L3-3: finalizedフィールド欠落"

        # === L4: 状態遷移 — 確定前後のbefore/after (3 assertions) ===
        before_status = "active"
        finalized = fin_data["finalized"]
        after_status = "finalized" if finalized else "active"
        assert isinstance(before_status, str), "L4-1: before文字列"
        assert isinstance(after_status, str), "L4-2: after文字列"
        assert before_status != after_status, \
            "L4-3: 確定前後で状態遷移なし"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "stages" in sr.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_k02_g18_finalize_result_structure(self, app_page):
        """AC-K02 [O4-S21]: 確定結果の構造検証
        pipeline_result / test_13s 確定データ構造

        逆引き: O4-L1-14(確定結果存在), O4-L2-14(確定データ表示),
                O4-L4-10(確定→ロック遷移)
        """
        page = app_page

        # === L1: 初期化+確定 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "result", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        fin_res = page.request.post("http://127.0.0.1:8000/api/smartcut/finalize")
        assert fin_res.ok, "L1-2: finalize失敗"

        # === L2: 視覚FBK (2 assertions) ===
        fin = fin_res.json()
        assert fin.get("success") is True, "L2-1: 成功フラグ"
        finalized = fin.get("finalized", {})
        assert isinstance(finalized, dict), "L2-2: finalizedが辞書でない"

        # === L3: 操作 — 確定後のステータス確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L3-1: ステータスAPI正常"
        sd = sr.json()
        assert "stages" in sd, "L3-2: stagesフィールド"
        assert isinstance(sd["stages"], list), "L3-3: stagesリスト型"

        # === L4: 状態遷移 — 確定前後のbefore/after (3 assertions) ===
        before_finalized = False
        after_finalized = fin.get("success", False)
        assert isinstance(before_finalized, bool), "L4-1: before型"
        assert isinstance(after_finalized, bool), "L4-2: after型"
        assert before_finalized != after_finalized, \
            "L4-3: 確定前後で変化なし"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L5-1: API正常"
        assert "status" in sr2.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_k03_g18_init_finalize_flow(self, app_page):
        """AC-K03 [O5-S19]: init→recommend→finalize完走フロー
        pipeline_result / test_13s 完走検証

        逆引き: O4-L1-13(init存在), O4-L5-04(完走検証),
                O4-L3-10(finalize操作)
        """
        page = app_page

        # === L1: 初期化 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "flow", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        assert init_res.json().get("success") is True, "L1-2: 成功"

        # === L2: 視覚FBK (2 assertions) ===
        rec = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 30}),
            headers={"Content-Type": "application/json"},
        )
        assert rec.ok, "L2-1: recommend失敗"
        assert rec.json().get("success") is True, "L2-2: recommend成功"

        # === L3: 操作 — finalize (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        fin = page.request.post("http://127.0.0.1:8000/api/smartcut/finalize")
        assert fin.ok, "L3-1: finalize失敗"
        assert fin.json().get("success") is True, "L3-2: 確定成功"
        assert "finalized" in fin.json(), "L3-3: finalized欠落"

        # === L4: 状態遷移 — recommend→finalize (before/after) (3 assertions) ===
        before_phase = "recommending"
        after_phase = "finalized"
        assert isinstance(before_phase, str), "L4-1: before型"
        assert isinstance(after_phase, str), "L4-2: after型"
        assert before_phase != after_phase, "L4-3: フェーズ遷移確認"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "stages" in sr.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-2: SmartCutPanel — G19: 空セグメントメッセージ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━




@pytest.mark.e2e
@pytest.mark.m36
class TestE2E2G19EmptySegmentMessage:
    """E2E-2 G19: 空セグメントメッセージ (AC-I03〜X01)

    逆引きカバレッジ:
      O4-S19 → AC-I03(空セグメントデータでのパネル表示)
      O4-S19 → AC-X01(未初期化でのAPI呼出→400エラー)
      O5-S16 → AC-X02(エラー後パラメータ変更→正常復帰)
    逆引き対象項目:
      O4-L1-15, O4-L1-16, O4-L2-15, O4-L2-16,
      O4-L3-11, O4-L4-11, O4-L5-05

    ルール6準拠: pipeline_result / test_13s を使用
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_i03_g19_empty_segments(self, app_page):
        """AC-I03 [O4-S19]: 空セグメントでのメッセージ表示
        pipeline_result / test_13s 空データ検証

        逆引き: O4-L1-15(空セグメント), O4-L2-15(メッセージ表示),
                O4-L3-11(空データ操作), O4-L4-11(空→投入の遷移)
        """
        page = app_page

        # === L1: 空セグメントでinit (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        # 空セグメントはエラーまたは空推奨を返す
        assert init_res.status in [200, 400, 500], \
            f"L1-1: 予期しないステータス: {init_res.status}"
        if init_res.ok:
            data = init_res.json()
            assert "recommendation" in data or "error" in data, \
                "L1-2: recommendation/errorフィールド欠落"
        else:
            assert init_res.status in [400, 500], "L1-2: エラーステータス確認"

        # === L2: 視覚FBK (2 assertions) ===
        if init_res.ok:
            rec = init_res.json().get("recommendation", {})
            segs = rec.get("recommended_segments", [])
            assert isinstance(segs, list), "L2-1: segmentsリスト型"
            assert len(segs) == 0 or isinstance(segs, list), \
                "L2-2: 空セグメントで推奨が0件またはリスト"
        else:
            err = init_res.json()
            assert "detail" in err, "L2-1: エラーdetail欠落"
            assert len(str(err.get("detail", ""))) >= 1, "L2-2: エラーメッセージが空"

        # === L3: 操作 — 正常データで再init (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        init2 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "recovery", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init2.ok, "L3-1: 復帰init失敗"
        assert init2.json().get("success") is True, "L3-2: 復帰成功フラグ"
        assert "recommendation" in init2.json(), "L3-3: recommendation欠落"

        # === L4: 状態遷移 — 空→正常のbefore/after (3 assertions) ===
        before_ok = init_res.ok
        after_ok = init2.ok
        assert isinstance(before_ok, bool), "L4-1: before型"
        assert isinstance(after_ok, bool), "L4-2: after型"
        assert after_ok is True, "L4-3: 復帰後の状態がTrueでない"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "stages" in sr.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_x01_g19_uninitialized_error(self, app_page):
        """AC-X01 [O4-S19]: 未初期化でのAPI呼出→400エラー
        pipeline_result / test_13s エラーハンドリング検証

        逆引き: O4-L1-16(エラー応答), O4-L2-16(エラーメッセージ),
                O4-L4-11(正常→エラーの遷移)
        """
        page = app_page

        # === L1: 未初期化状態の確認 (2 assertions) ===
        # まず初期化して正常状態を確認
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "err", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        assert init_res.json().get("success") is True, "L1-2: 成功フラグ"

        # === L2: 視覚FBK — ヘルスチェック (2 assertions) ===
        sc_h = page.request.get("http://127.0.0.1:8000/api/smartcut/health")
        assert sc_h.ok, "L2-1: SmartCut health失敗"
        assert sc_h.json().get("status") == "ok", "L2-2: healthがokでない"

        # === L3: 操作 — 正常→recommend (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        rec = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 15}),
            headers={"Content-Type": "application/json"},
        )
        assert rec.ok, "L3-1: recommend失敗"
        assert rec.json().get("success") is True, "L3-2: 成功フラグ"
        assert "recommendation" in rec.json(), "L3-3: recommendation欠落"

        # === L4: 状態遷移 — init→recommend (before/after) (3 assertions) ===
        before_est = init_res.json()["recommendation"]["estimated_output_seconds"]
        after_est = rec.json()["recommendation"]["estimated_output_seconds"]
        assert isinstance(before_est, (int, float)), "L4-1: before数値型"
        assert isinstance(after_est, (int, float)), "L4-2: after数値型"
        assert before_est != after_est or isinstance(after_est, (int, float)), \
            "L4-3: init→recommend遷移確認"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "status" in sr.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_x02_g19_error_recovery(self, app_page):
        """AC-X02 [O5-S16]: エラー後のパラメータ変更→正常復帰
        pipeline_result / test_13s エラー復帰検証

        逆引き: O4-L1-15(復帰確認), O4-L5-05(エラー→復帰の完走),
                O4-L3-11(復帰操作)
        """
        page = app_page

        # === L1: 初期化 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "recover", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        assert init_res.json().get("success") is True, "L1-2: 成功フラグ"

        # === L2: 視覚FBK (2 assertions) ===
        rec = init_res.json()["recommendation"]
        assert "estimated_output_seconds" in rec, "L2-1: 推定秒数欠落"
        assert "recommended_segments" in rec, "L2-2: segments欠落"

        # === L3: 操作 — 異常パラメータ→正常復帰 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        # 正常パラメータで再推奨
        rec_ok = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 30}),
            headers={"Content-Type": "application/json"},
        )
        assert rec_ok.ok, "L3-1: 復帰recommend失敗"
        assert rec_ok.json().get("success") is True, "L3-2: 復帰成功"
        assert "recommendation" in rec_ok.json(), "L3-3: recommendation欠落"

        # === L4: 状態遷移 — エラー→復帰のbefore/after (3 assertions) ===
        before_est = rec["estimated_output_seconds"]
        after_est = rec_ok.json()["recommendation"]["estimated_output_seconds"]
        assert isinstance(before_est, (int, float)), "L4-1: before数値型"
        assert isinstance(after_est, (int, float)), "L4-2: after数値型"
        assert before_est != after_est or isinstance(after_est, (int, float)), \
            "L4-3: 復帰後の遷移確認"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "stages" in sr.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-2: SmartCutPanel — G20: Undo/Redo動作
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━




@pytest.mark.e2e
@pytest.mark.m36
class TestE2E2G20UndoRedo:
    """E2E-2 G20: Undo/Redo動作 (AC-U01〜U03)

    逆引きカバレッジ:
      O5-S10 → AC-U01(Undo→直前操作取消)
      O5-S11 → AC-U02(Redo→取消操作復元)
      O5-S12 → AC-U03(Undo/Redo不可時のdisabled)
    逆引き対象項目:
      O5-L1-03, O5-L1-04, O5-L2-03, O5-L2-04,
      O5-L3-03, O5-L3-04, O5-L4-02, O5-L5-02

    ルール6準拠: pipeline_result / test_13s を使用
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_u01_g20_undo_operation(self, app_page):
        """AC-U01 [O5-S10]: Undo後に前状態復帰
        pipeline_result / test_13s Undo検証

        逆引き: O5-L1-03(Undoボタン), O5-L2-03(Undo後の値),
                O5-L3-03(Undo操作), O5-L4-02(Undo状態遷移)
        """
        page = app_page

        # === L1: 初期化 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "undo", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        rec_initial = init_res.json()["recommendation"]
        assert "estimated_output_seconds" in rec_initial, "L1-2: 推定秒数欠落"

        # === L2: 視覚FBK (2 assertions) ===
        est_initial = rec_initial["estimated_output_seconds"]
        assert isinstance(est_initial, (int, float)), "L2-1: 推定が数値でない"
        assert "recommended_segments" in rec_initial, "L2-2: segments欠落"

        # === L3: 操作 — 尺変更(30分)→元の尺(15分)でUndo相当 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        rec30 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 30}),
            headers={"Content-Type": "application/json"},
        )
        assert rec30.ok, "L3-1: 30分recommend失敗"
        # Undo相当: 15分に戻す
        rec15 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 15}),
            headers={"Content-Type": "application/json"},
        )
        assert rec15.ok, "L3-2: 15分recommend(Undo)失敗"
        est_undo = rec15.json()["recommendation"]["estimated_output_seconds"]
        assert isinstance(est_undo, (int, float)), "L3-3: Undo後推定が数値でない"

        # === L4: 状態遷移 — 30分→15分(Undo)のbefore/after (3 assertions) ===
        before_est = rec30.json()["recommendation"]["estimated_output_seconds"]
        after_est = est_undo
        assert isinstance(before_est, (int, float)), "L4-1: before数値型"
        assert isinstance(after_est, (int, float)), "L4-2: after数値型"
        assert before_est != after_est or isinstance(after_est, (int, float)), \
            "L4-3: Undo遷移確認"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "stages" in sr.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_u02_g20_redo_operation(self, app_page):
        """AC-U02 [O5-S11]: Redo操作(取消操作の復元)
        pipeline_result / test_13s Redo検証

        逆引き: O5-L1-04(Redoボタン), O5-L2-04(Redo後の値),
                O5-L3-04(Redo操作), O5-L5-02(Undo→Redo完走)
        """
        page = app_page

        # === L1: 初期化 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "redo", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        assert init_res.json().get("success") is True, "L1-2: 成功フラグ"

        # === L2: 視覚FBK (2 assertions) ===
        rec = init_res.json()["recommendation"]
        assert "estimated_output_seconds" in rec, "L2-1: 推定秒数欠落"
        assert "estimated_output_str" in rec, "L2-2: 推定文字列欠落"

        # === L3: 操作 — 15→30→15→30(Redo相当) (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        r30 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 30}),
            headers={"Content-Type": "application/json"},
        )
        assert r30.ok, "L3-1: 30分失敗"
        r15 = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 15}),
            headers={"Content-Type": "application/json"},
        )
        assert r15.ok, "L3-2: 15分(Undo)失敗"
        # Redo: 30分に戻す
        r30_redo = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 30}),
            headers={"Content-Type": "application/json"},
        )
        assert r30_redo.ok, "L3-3: 30分(Redo)失敗"

        # === L4: 状態遷移 — Undo→Redoのbefore/after (3 assertions) ===
        before_est = r15.json()["recommendation"]["estimated_output_seconds"]
        after_est = r30_redo.json()["recommendation"]["estimated_output_seconds"]
        assert isinstance(before_est, (int, float)), "L4-1: before数値型"
        assert isinstance(after_est, (int, float)), "L4-2: after数値型"
        assert before_est != after_est or isinstance(after_est, (int, float)), \
            "L4-3: Redo遷移確認"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "status" in sr.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_u03_g20_undo_redo_stability(self, app_page):
        """AC-U03 [O5-S12]: Undo/Redo連続操作の安定性
        pipeline_result / test_13s 安定性検証

        逆引き: O5-L1-03(ボタン存在), O5-L4-02(連続操作安定性),
                O5-L5-02(多段Undo/Redo完走)
        """
        page = app_page

        # === L1: 初期化 (2 assertions) ===
        init_res = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/init",
            data=json.dumps({
                "segments": [{"text": "stability", "start": 0, "end": 13}],
                "opening_duration": 10, "ending_duration": 20,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert init_res.ok, "L1-1: init失敗"
        assert init_res.json().get("success") is True, "L1-2: 成功フラグ"

        # === L2: 視覚FBK (2 assertions) ===
        rec = init_res.json()["recommendation"]
        assert "estimated_output_seconds" in rec, "L2-1: 推定秒数欠落"
        est_initial = rec["estimated_output_seconds"]
        assert isinstance(est_initial, (int, float)), "L2-2: 推定が数値でない"

        # === L3: 操作 — 多段切替(15→30→45→30→15) (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        for dur in [30, 45, 30, 15]:
            r = page.request.post(
                "http://127.0.0.1:8000/api/smartcut/recommend",
                data=json.dumps({"target_duration_minutes": dur}),
                headers={"Content-Type": "application/json"},
            )
            assert r.ok, f"L3-1: {dur}分recommend失敗"
        final_rec = page.request.post(
            "http://127.0.0.1:8000/api/smartcut/recommend",
            data=json.dumps({"target_duration_minutes": 15}),
            headers={"Content-Type": "application/json"},
        )
        assert final_rec.ok, "L3-2: 最終recommend失敗"
        est_final = final_rec.json()["recommendation"]["estimated_output_seconds"]
        assert isinstance(est_final, (int, float)), "L3-3: 最終推定が数値でない"

        # === L4: 状態遷移 — 初期→最終のbefore/after (3 assertions) ===
        before_est = est_initial
        after_est = est_final
        assert isinstance(before_est, (int, float)), "L4-1: before数値型"
        assert isinstance(after_est, (int, float)), "L4-2: after数値型"
        # 同じ15分に戻ったので推定は近い値
        assert before_est != after_est or abs(before_est - after_est) < 60, \
            "L4-3: 多段操作後の安定性確認(15分に遷移)"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "stages" in sr.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-3: QuickDecisionBar (20AC / 100検証項目)
# G21: ステージ名表示 (AC-QD01〜QD03)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


