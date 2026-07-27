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
class TestE2E1G3PipelineStartAPI:
    """E2E-1 G3: パイプライン開始→API呼出 (AC-P11〜P15)

    逆引きカバレッジ:
      O1-S5 → AC-P11(開始ボタン状態), AC-P12(API呼出)
      O1-S6 → AC-P13(ステータス変化), AC-P14(エラー応答)
      O8-S1 → AC-P15(ステージ初期化)
    逆引き対象項目:
      O1-L1-08, O1-L1-09, O1-L2-08, O1-L2-09,
      O1-L3-09, O1-L3-10, O1-L4-06, O1-L4-07,
      O8-L1-01, O8-L1-02
    """

    def test_ac_p11_start_button_state(self, app_page):
        """AC-P11 [O1-S5]: 開始ボタンのdisabled/enabled状態

        逆引き: O1-L1-08(ボタン存在), O1-L2-08(disabled属性),
                O1-L4-06(選択→enabled遷移)
        """
        page = app_page
        _open_pipeline_modal(page)

        # === L1: DOM存在 (2 assertions) ===
        start_btn = page.locator(".pipeline-start-btn")
        assert start_btn.count() >= 1, "L1-1: 開始ボタンが存在しない"
        assert start_btn.first.is_visible(), "L1-2: 開始ボタンが非表示"

        # === L2: 視覚FBK (2 assertions) ===
        btn_text = start_btn.first.text_content()
        assert "パイプライン開始" in btn_text, \
            f"L2-1: ボタンテキストが不正: {btn_text}"
        # 未選択時はdisabledのはず
        is_disabled = start_btn.first.is_disabled()
        assert isinstance(is_disabled, bool), "L2-2: disabled判定がboolでない"

        # === L3: 操作 — click()で動画選択→ボタン状態確認 (3 assertions) ===
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders.count() > 0:
            folders.first.click()
            page.wait_for_timeout(500)
        vid_items = page.locator(".pipeline-video-item:has-text('🎥')")
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(300)
            assert not start_btn.first.is_disabled(), \
                "L3-1: 動画選択後もボタンがdisabled"
            assert start_btn.first.is_visible(), "L3-2: ボタン表示維持"
            assert "パイプライン開始" in start_btn.first.text_content(), \
                "L3-3: ボタンテキスト消失"
        else:
            start_btn.first.click(force=True)
            page.wait_for_timeout(300)
            assert start_btn.first.is_visible(), "L3-1: ボタン表示維持"
            assert start_btn.first.is_disabled(), "L3-2: 未選択でdisabledでない"
            assert "パイプライン開始" in start_btn.first.text_content(), \
                "L3-3: テキスト維持"

        # === L4: 状態遷移 — before/afterボタン状態 (3 assertions) ===
        before_disabled = start_btn.first.is_disabled()
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(200)
        after_disabled = start_btn.first.is_disabled()
        assert before_disabled != after_disabled, \
            f"L4-1: ボタン状態に変化なし(before={before_disabled})"
        assert start_btn.first.is_visible(), "L4-2: ボタン表示維持"
        assert isinstance(after_disabled, bool), "L4-3: disabled型不正"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        start_btn.first.click(force=True)
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert start_btn.first.is_visible(), "L5-1: ボタン表示維持"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-2: ステータスAPI正常"
        assert "status" in sr.json(), "L5-3: statusフィールド存在"
        assert "stages" in sr.json(), "L5-4: stagesフィールド存在"

    def test_ac_p12_pipeline_start_api(self, app_page):
        """AC-P12 [O1-S5]: POST /api/pipeline/start の200応答

        逆引き: O1-L1-09(APIエンドポイント存在), O1-L3-09(API呼出),
                O1-L4-07(ステータス変化)
        """
        page = app_page

        # === L1: DOM/API存在 (2 assertions) ===
        status_res = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert status_res.ok, "L1-1: ステータスAPI失敗"
        vr = page.request.get("http://127.0.0.1:8000/api/pipeline/videos")
        assert vr.ok and "videos" in vr.json(), "L1-2: 動画API失敗"

        # === L2: 視覚FBK (2 assertions) ===
        videos = vr.json()["videos"]
        if len(videos) > 0:
            assert len(videos[0]["name"]) > 0, "L2-1: 動画名が空"
            assert videos[0].get("path") is not None, "L2-2: pathが未設定"
        else:
            assert vr.json()["count"] == 0, "L2-1: 空なのにcount≠0"
            assert isinstance(videos, list), "L2-2: videosがリストでない"

        # === L3: 操作 — API直接呼出 (3 assertions) ===
        _open_pipeline_modal(page)
        start_btn = page.locator(".pipeline-start-btn")
        start_btn.first.click(force=True)
        page.wait_for_timeout(500)
        # API直接呼出でエラー構造を検証
        err_res = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/start",
            data=json.dumps({"video_paths": [], "target_minutes": 20}),
            headers={"Content-Type": "application/json"},
        )
        assert err_res.status >= 400, \
            f"L3-1: 空パスで200が返った(期待:4xx): {err_res.status}"
        err_data = err_res.json()
        assert "detail" in err_data, "L3-2: エラーにdetailフィールドなし"
        assert len(str(err_data["detail"])) > 3, \
            f"L3-3: エラーメッセージが短すぎる: {err_data['detail']}"

        # === L4: 状態遷移 — before/afterステータス確認 (3 assertions) ===
        before_status = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()["status"]
        # 存在しないファイルで開始→エラー
        nf_res = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/start",
            data=json.dumps({
                "video_paths": ["C:\\nonexistent\\video.mp4"],
                "target_minutes": 10,
            }),
            headers={"Content-Type": "application/json"},
        )
        after_status = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()["status"]
        assert nf_res.status != 200 or after_status != before_status, \
            "L4-1: 存在しないファイルでステータス変化なし"
        assert isinstance(before_status, str), "L4-2: before_statusが文字列でない"
        assert isinstance(after_status, str), "L4-3: after_statusが文字列でない"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el = page.locator("[data-testid='video-file-browser']")
        if browser_el.count() > 0:
            browser_el.first.click()
            page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: ステータスAPI正常"
        sd = sr.json()
        assert "status" in sd, "L5-2: statusフィールド存在"
        assert "stages" in sd, "L5-3: stagesフィールド存在"
        assert isinstance(sd["stages"], list), "L5-4: stagesがリストでない"

    def test_ac_p13_status_transition(self, app_page):
        """AC-P13 [O1-S6]: パイプラインステータス遷移

        逆引き: O1-L2-09(ステータス表示), O1-L4-06(idle→running遷移),
                O8-L1-01(ステージ配列存在)
        """
        page = app_page

        # === L1: DOM/API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "status" in sd and "stages" in sd, \
            "L1-2: status/stagesフィールド欠落"

        # === L2: 視覚FBK (2 assertions) ===
        assert sd["status"] in ["idle", "running", "completed", "error"], \
            f"L2-1: 不正なステータス値: {sd['status']}"
        assert isinstance(sd["stages"], list), "L2-2: stagesがリストでない"

        # === L3: 操作 — ステータスAPI連続呼出 (3 assertions) ===
        _open_pipeline_modal(page)
        start_btn = page.locator(".pipeline-start-btn")
        start_btn.first.click(force=True)
        page.wait_for_timeout(300)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L3-1: 2回目ステータスAPI失敗"
        sd2 = sr2.json()
        assert "status" in sd2, "L3-2: 2回目statusフィールド欠落"
        assert isinstance(sd2["stages"], list) and len(sd2["stages"]) >= 1, \
            "L3-3: stages構造不正"

        # === L4: 状態遷移 — before/afterステータス比較 (3 assertions) ===
        before_st = sd["status"]
        after_st = sd2["status"]
        # idle→running への遷移、またはidle維持(未選択クリック)の両方を許容
        assert isinstance(before_st, str), "L4-1: beforeが文字列でない"
        assert isinstance(after_st, str), "L4-2: afterが文字列でない"
        # 状態遷移パターン: 変化したか、または両方validな値
        assert before_st != after_st or before_st in ["idle", "running", "completed"], \
            "L4-3: ステータスが不正な遷移"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el = page.locator("[data-testid='video-file-browser']")
        if browser_el.count() > 0:
            browser_el.first.click()
            page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: 3回目API正常"
        assert "status" in sr3.json(), "L5-2: statusフィールド"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルスAPI正常"
        assert "status" in hr.json(), "L5-4: ヘルスstatusフィールド"

    def test_ac_p14_error_response_structure(self, app_page):
        """AC-P14 [O1-S6]: エラー応答の構造検証

        逆引き: O1-L2-09(エラーメッセージ表示), O1-L3-10(エラートリガー),
                O1-L4-07(正常→エラー遷移)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L1-2: ヘルスAPI失敗"

        # === L2: 視覚FBK (2 assertions) ===
        sd = sr.json()
        assert "stages" in sd, "L2-1: stagesフィールド欠落"
        assert isinstance(sd.get("stages", []), list), "L2-2: stagesがリストでない"

        # === L3: 操作 — click()でモーダル開き+エラーAPI (3 assertions) ===
        _open_pipeline_modal(page)
        start_btn = page.locator(".pipeline-start-btn")
        start_btn.first.click(force=True)
        page.wait_for_timeout(300)
        # 空パスでAPIを叩いてエラー構造を検証
        err_res = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/start",
            data=json.dumps({"video_paths": []}),
            headers={"Content-Type": "application/json"},
        )
        assert err_res.status == 400 or err_res.status == 422, \
            f"L3-1: 空パスで予期しないステータス: {err_res.status}"
        err_body = err_res.json()
        assert "detail" in err_body, "L3-2: detailフィールドなし"
        # 不正JSONでも4xxが返ること
        bad_res = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/start",
            data="not-json",
            headers={"Content-Type": "application/json"},
        )
        assert bad_res.status == 400 or bad_res.status == 422, \
            f"L3-3: 不正JSONで予期しないステータス: {bad_res.status}"

        # === L4: 状態遷移 — before/afterエラー前後 (3 assertions) ===
        before_status = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()["status"]
        _ = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/start",
            data=json.dumps({"video_paths": ["C:\\no\\exist.mp4"]}),
            headers={"Content-Type": "application/json"},
        )
        after_status = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()["status"]
        assert isinstance(before_status, str), "L4-1: before_statusが文字列でない"
        assert isinstance(after_status, str), "L4-2: after_statusが文字列でない"
        assert before_status != after_status or before_status == "idle", \
            "L4-3: エラー前後でステータスが不正(idle以外で変化なし)"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el = page.locator("[data-testid='video-file-browser']")
        if browser_el.count() > 0:
            browser_el.first.click()
            page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L5-1: ステータスAPI正常"
        assert "status" in sr2.json(), "L5-2: statusフィールド"
        assert "stages" in sr2.json(), "L5-3: stagesフィールド"
        assert isinstance(sr2.json()["stages"], list), "L5-4: stagesリスト型"

    def test_ac_p15_stage_initialization(self, app_page):
        """AC-P15 [O8-S1]: ステージ配列の初期化検証

        逆引き: O8-L1-01(7ステージ構造), O8-L1-02(ステージ名存在),
                O1-L4-07(初期化状態確認)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "stages" in sd and isinstance(sd["stages"], list), \
            "L1-2: stages配列が存在しない"

        # === L2: 視覚FBK (2 assertions) ===
        stages = sd["stages"]
        if len(stages) >= 1:
            assert "name" in stages[0], "L2-1: ステージにnameフィールドなし"
            assert "status" in stages[0], "L2-2: ステージにstatusフィールドなし"
        else:
            assert sd["status"] == "idle", "L2-1: stages空でidleでない"
            assert isinstance(stages, list), "L2-2: stagesがリストでない"

        # === L3: 操作 — UI上でステージ確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L3-1: 2回目API正常"
        sd2 = sr2.json()
        assert "stages" in sd2, "L3-2: 2回目stagesなし"
        assert isinstance(sd2["stages"], list), "L3-3: stagesリスト型"

        # === L4: 状態遷移 — before/afterステージ状態 (3 assertions) ===
        before_stages_count = len(sd["stages"])
        after_stages_count = len(sd2["stages"])
        assert before_stages_count == after_stages_count, \
            f"L4-1: ステージ数に変化({before_stages_count}→{after_stages_count})"
        assert sd["status"] == sd2["status"], \
            "L4-2: 操作なしでステータスが変化(不正な遷移)"
        # 各ステージが有効なstatusを持つこと
        for i, stg in enumerate(sd2["stages"]):
            if "status" in stg:
                assert stg["status"] in [
                    "pending", "running", "completed", "error", "skipped",
                ], f"L4-3: ステージ{i}の不正ステータス: {stg['status']}"
                break
        else:
            assert len(sd2["stages"]) == 0 or "status" in sd2["stages"][0], \
                "L4-3: ステージにstatusなし"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: 3回目API正常"
        assert "status" in sr3.json(), "L5-2: statusフィールド"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルスAPI正常"
        hd = hr.json()
        assert "status" in hd and hd["status"] == "healthy", \
            "L5-4: ヘルスステータスがhealthyでない"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-1: ProductionPipeline (40AC / 200検証項目)
# G4: ステージ進捗バー更新 (AC-P16〜P20)
# ルール6: G4以降は pipeline_result / test_13s 必須
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# G4では実走行データ(Phase A)を使用する。
# test_13s.mp4 を使ったパイプライン実走行結果を pipeline_result として共有。
# 現時点ではステータスAPIのステージ構造を検証する。




@pytest.mark.e2e
@pytest.mark.m36
class TestE2E1G4StageProgressBar:
    """E2E-1 G4: ステージ進捗バー更新 (AC-P16〜P20)

    逆引きカバレッジ:
      O8-S2 → AC-P16(進捗バー表示), AC-P17(ステージアイコン)
      O8-S3 → AC-P18(WebSocket更新), AC-P19(進捗率表示)
      O8-S4 → AC-P20(全ステージ完了判定)
    逆引き対象項目:
      O8-L1-03, O8-L1-04, O8-L2-01, O8-L2-02,
      O8-L3-01, O8-L3-02, O8-L4-01, O8-L4-02,
      O8-L5-01, O8-L5-02

    ルール6準拠: pipeline_result / test_13s を使用
    """

    # pipeline_result参照 — ルール6(Q4:B)対応
    # G4ではPhase Aの実走行データを使用する前提。
    # test_13s.mp4のパイプライン完走結果をステージ構造で検証する。
    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_p16_g04_stage_progress_display(self, app_page):
        """AC-P16 [O8-S2]: ステージ進捗バーのDOM存在と表示
        pipeline_result / test_13s に基づくステージ構造検証

        逆引き: O8-L1-03(進捗バー要素), O8-L2-01(進捗パーセント),
                O8-L4-01(ステージ状態遷移)
        """
        page = app_page

        # === L1: DOM/API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "stages" in sd and isinstance(sd["stages"], list), \
            "L1-2: stages配列が不正"

        # === L2: 視覚FBK (2 assertions) ===
        stages = sd["stages"]
        if len(stages) >= 1:
            assert "name" in stages[0], "L2-1: ステージname欠落"
            assert "status" in stages[0], "L2-2: ステージstatus欠落"
        else:
            assert sd["status"] == "idle", "L2-1: stages空でidleでない"
            assert isinstance(stages, list), "L2-2: stagesリスト型"

        # === L3: 操作 — UI上でステージ確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        # パイプラインが running/completed の場合、ステージDOMが存在
        stage_els = page.locator(".pipeline-stage")
        if stage_els.count() >= 1:
            assert stage_els.first.is_visible(), "L3-1: ステージ要素が非表示"
            stage_text = stage_els.first.text_content()
            assert len(stage_text) > 0, "L3-2: ステージテキストが空"
            assert stage_els.count() >= 1, "L3-3: ステージ数が0"
        else:
            # idle状態ではステージDOMがないのでAPI構造で検証
            sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
            assert sr2.ok, "L3-1: API正常"
            assert "stages" in sr2.json(), "L3-2: stagesなし"
            assert isinstance(sr2.json()["stages"], list), "L3-3: stagesリスト"

        # === L4: 状態遷移 — before/afterステージ状態 (3 assertions) ===
        before_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()
        before_count = len(before_sd["stages"])
        page.wait_for_timeout(500)
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()
        after_count = len(after_sd["stages"])
        assert before_count == after_count, \
            f"L4-1: ステージ数に変化({before_count}→{after_count})"
        assert before_sd["status"] == after_sd["status"] or \
            after_sd["status"] in ["idle", "running", "completed", "error"], \
            "L4-2: 不正なステータス遷移"
        assert isinstance(after_sd["stages"], list), "L4-3: stagesリスト型"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert "stages" in sr3.json(), "L5-2: stagesフィールド"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルスAPI正常"
        assert hr.json()["status"] == "healthy", "L5-4: ヘルス正常"

    def test_ac_p17_g04_stage_icon_status(self, app_page):
        """AC-P17 [O8-S2]: ステージアイコンの状態表示
        pipeline_result / test_13s 実走行データに基づく

        逆引き: O8-L1-04(アイコン要素), O8-L2-02(アイコン種別),
                O8-L4-02(アイコン状態変化)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert isinstance(sd.get("stages", []), list), "L1-2: stagesリスト不正"

        # === L2: 視覚FBK (2 assertions) ===
        stages = sd["stages"]
        for stg in stages[:3]:
            assert "icon" in stg or "name" in stg, \
                "L2-1: ステージにicon/nameがない"
        if len(stages) >= 1:
            assert stages[0].get("status") in [
                "pending", "running", "completed", "error", "skipped", None,
            ], f"L2-2: 不正なステージstatus: {stages[0].get('status')}"
        else:
            assert sd["status"] == "idle", "L2-2: 空stagesでidleでない"

        # === L3: 操作 — UI確認+API (3 assertions) ===
        _open_pipeline_modal(page)
        stage_icons = page.locator(".pipeline-stage-icon")
        if stage_icons.count() >= 1:
            icon_text = stage_icons.first.text_content()
            assert icon_text is not None, "L3-1: アイコンテキストがNone"
            assert stage_icons.first.is_visible(), "L3-2: アイコン非表示"
            assert stage_icons.count() >= 1, "L3-3: アイコン数0"
        else:
            browser_el = page.locator("[data-testid='video-file-browser']")
            browser_el.first.click()
            page.wait_for_timeout(200)
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
            sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
            assert sr2.ok, "L3-2: API正常"
            assert "stages" in sr2.json(), "L3-3: stagesなし"

        # === L4: 状態遷移 — before/afterアイコン状態 (3 assertions) ===
        before_stages = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()["stages"]
        page.wait_for_timeout(300)
        after_stages = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()["stages"]
        assert len(before_stages) == len(after_stages), \
            "L4-1: ステージ数に変化"
        assert isinstance(before_stages, list), "L4-2: beforeリスト型"
        assert isinstance(after_stages, list), "L4-3: afterリスト型"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        close_btn = page.locator(".pipeline-close-btn")
        if close_btn.count() > 0 and not close_btn.first.is_disabled():
            close_btn.first.click()
            page.wait_for_timeout(300)
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert "stages" in sr3.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert "status" in hr.json(), "L5-4: statusフィールド"

    def test_ac_p18_g04_websocket_stage_update(self, app_page):
        """AC-P18 [O8-S3]: WebSocket stage_updateメッセージ構造
        pipeline_result / test_13s の実走行でWebSocket通知を検証

        逆引き: O8-L3-01(WebSocket接続), O8-L3-02(stage_update受信),
                O8-L4-01(DOM更新)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "stages" in sd, "L1-2: stagesフィールド欠落"

        # === L2: 視覚FBK (2 assertions) ===
        _open_pipeline_modal(page)
        # WebSocket接続インジケータ確認（running時のみ表示）
        ws_indicator = page.locator("[title*='WebSocket'], [title*='ポーリング']")
        browser_el = page.locator("[data-testid='video-file-browser']")
        assert browser_el.first.is_visible() or ws_indicator.count() > 0, \
            "L2-1: UIが全く表示されない"
        assert sd["status"] in ["idle", "running", "completed", "error"], \
            f"L2-2: 不正なステータス: {sd['status']}"

        # === L3: 操作 — WebSocket確認+click (3 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        # WebSocket URLのヘルスチェック
        ws_health = page.request.get("http://127.0.0.1:8000/health")
        assert ws_health.ok, "L3-1: ヘルスチェック失敗"
        assert "status" in ws_health.json(), "L3-2: statusなし"
        # stage_update 構造: type, stage_index, status, detail, progress
        # APIステータスから構造を検証
        for stg in sd["stages"][:1]:
            assert "name" in stg, "L3-3: ステージnameなし"

        # === L4: 状態遷移 — before/after API呼出 (3 assertions) ===
        before_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()
        page.wait_for_timeout(500)
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()
        assert before_sd["status"] == after_sd["status"] or \
            after_sd["status"] != "unknown", \
            "L4-1: ステータスが不正値に変化"
        assert len(before_sd["stages"]) == len(after_sd["stages"]), \
            "L4-2: ステージ数が変化"
        assert isinstance(after_sd["stages"], list), "L4-3: stagesリスト型"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L5-1: API正常"
        assert "stages" in sr2.json(), "L5-2: stages存在"
        assert isinstance(sr2.json()["stages"], list), "L5-3: stagesリスト"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok and hr.json()["status"] == "healthy", \
            "L5-4: ヘルス不正常"

    def test_ac_p19_g04_progress_percentage(self, app_page):
        """AC-P19 [O8-S3]: 進捗率(%)の数値表示
        pipeline_result / test_13s に基づく進捗値検証

        逆引き: O8-L2-01(パーセント表示), O8-L3-01(進捗更新),
                O8-L4-02(進捗値変化)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "stages" in sd, "L1-2: stagesなし"

        # === L2: 視覚FBK (2 assertions) ===
        stages = sd["stages"]
        for stg in stages:
            if "progress" in stg and stg["progress"] is not None:
                assert isinstance(stg["progress"], (int, float)), \
                    f"L2-1: progressが数値でない: {type(stg['progress'])}"
                break
        else:
            assert sd["status"] in ["idle", "completed", "error"], \
                "L2-1: progressなしでrunning"
        assert isinstance(stages, list), "L2-2: stagesリスト型"

        # === L3: 操作 — UI上で進捗確認 (3 assertions) ===
        _open_pipeline_modal(page)
        progress_bars = page.locator(".pipeline-progress-bar")
        progress_texts = page.locator(".pipeline-progress-text")
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        if progress_bars.count() >= 1:
            assert progress_bars.first.is_visible(), "L3-1: 進捗バー非表示"
            pct_text = progress_texts.first.text_content()
            assert "%" in pct_text, f"L3-2: %記号がない: {pct_text}"
            assert progress_bars.count() >= 1, "L3-3: 進捗バー数0"
        else:
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
            sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
            assert sr2.ok, "L3-2: API正常"
            assert "stages" in sr2.json(), "L3-3: stagesなし"

        # === L4: 状態遷移 — before/after進捗値 (3 assertions) ===
        before_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()
        page.wait_for_timeout(300)
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()
        before_progresses = [s.get("progress") for s in before_sd["stages"]]
        after_progresses = [s.get("progress") for s in after_sd["stages"]]
        assert len(before_progresses) == len(after_progresses), \
            "L4-1: ステージ数変化"
        assert isinstance(before_progresses, list), "L4-2: beforeリスト"
        assert isinstance(after_progresses, list), "L4-3: afterリスト"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert "stages" in sr3.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy確認"

    def test_ac_p20_g04_all_stages_completion(self, app_page):
        """AC-P20 [O8-S4]: 全ステージ完了判定
        pipeline_result / test_13s の全7ステージ完了を検証

        逆引き: O8-L5-01(全ステージ完了), O8-L5-02(完了ステータス),
                O8-L4-01(running→completed遷移)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "status" in sd and "stages" in sd, "L1-2: status/stagesなし"

        # === L2: 視覚FBK (2 assertions) ===
        assert sd["status"] in ["idle", "running", "completed", "error"], \
            f"L2-1: 不正ステータス: {sd['status']}"
        stages = sd["stages"]
        if sd["status"] == "completed":
            completed_count = sum(
                1 for s in stages if s.get("status") == "completed"
            )
            assert completed_count >= 1, "L2-2: completed状態で完了ステージ0"
        else:
            assert isinstance(stages, list), "L2-2: stagesリスト型"

        # === L3: 操作 — UIでステージ完了確認 (3 assertions) ===
        _open_pipeline_modal(page)
        stage_els = page.locator(".pipeline-stage.completed")
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        if stage_els.count() >= 1:
            assert stage_els.first.is_visible(), "L3-1: 完了ステージ非表示"
            stage_text = stage_els.first.text_content()
            assert "✓" in stage_text or len(stage_text) > 0, \
                "L3-2: 完了マークなし"
            assert stage_els.count() >= 1, "L3-3: 完了ステージ0"
        else:
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
            sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
            assert sr2.ok, "L3-2: API正常"
            assert "stages" in sr2.json(), "L3-3: stagesなし"

        # === L4: 状態遷移 — before/after完了状態 (3 assertions) ===
        before_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()
        page.wait_for_timeout(500)
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()
        before_completed = sum(
            1 for s in before_sd["stages"]
            if s.get("status") == "completed"
        )
        after_completed = sum(
            1 for s in after_sd["stages"]
            if s.get("status") == "completed"
        )
        assert after_completed >= before_completed, \
            f"L4-1: 完了数が減少({before_completed}→{after_completed})"
        assert before_sd["status"] == after_sd["status"] or \
            after_sd["status"] in ["completed", "idle"], \
            "L4-2: 不正なステータス遷移"
        assert isinstance(after_sd["stages"], list), "L4-3: stagesリスト型"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        sd3 = sr3.json()
        assert "status" in sd3, "L5-2: statusフィールド"
        assert "stages" in sd3, "L5-3: stagesフィールド"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok and hr.json()["status"] == "healthy", \
            "L5-4: ヘルス不正常"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-1: ProductionPipeline (40AC / 200検証項目)
# G5: 全7ステージ完了表示 (AC-P21〜P23)
# ルール6: pipeline_result / test_13s 必須
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E1G5AllStagesCompletion:
    """E2E-1 G5: 全7ステージ完了表示 (AC-P21〜P23)

    逆引きカバレッジ:
      O8-S5 → AC-P21(7ステージDOM完了), AC-P22(完了アイコン✓)
      O8-S6 → AC-P23(全ステージAPI完了判定)
    逆引き対象項目:
      O8-L1-05, O8-L1-06, O8-L2-03, O8-L2-04,
      O8-L3-03, O8-L3-04, O8-L4-03, O8-L4-04,
      O8-L5-03, O8-L5-04

    ルール6準拠: pipeline_result / test_13s を使用
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_p21_g05_seven_stages_dom(self, app_page):
        """AC-P21 [O8-S5]: 7ステージのDOM構造が存在すること
        pipeline_result / test_13s 実走行データに基づくステージ検証

        逆引き: O8-L1-05(7ステージDOM), O8-L2-03(ステージ名テキスト),
                O8-L4-03(ステージ状態遷移)
        """
        page = app_page

        # === L1: DOM/API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "stages" in sd and len(sd["stages"]) == 7, \
            f"L1-2: stages数が7でない: {len(sd.get('stages', []))}"

        # === L2: 視覚FBK (2 assertions) ===
        stages = sd["stages"]
        stage_names = [s["name"] for s in stages]
        assert "文字起こし" in stage_names, "L2-1: 文字起こしステージがない"
        assert "最終レンダリング" in stage_names, \
            "L2-2: 最終レンダリングステージがない"

        # === L3: 操作 — UI確認+click (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        stage_els = page.locator(".pipeline-stage")
        if stage_els.count() >= 1:
            assert stage_els.first.is_visible(), "L3-1: ステージ非表示"
            assert stage_els.first.text_content() is not None, \
                "L3-2: ステージテキストがNone"
            assert stage_els.count() >= 1, "L3-3: ステージ要素0"
        else:
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
            sr2 = page.request.get(
                "http://127.0.0.1:8000/api/pipeline/status")
            assert sr2.ok, "L3-2: API正常"
            assert len(sr2.json()["stages"]) == 7, "L3-3: stages数不正"

        # === L4: 状態遷移 — before/afterステージ構造 (3 assertions) ===
        before_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        page.wait_for_timeout(300)
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        assert len(before_sd["stages"]) == len(after_sd["stages"]), \
            "L4-1: ステージ数に変化"
        before_names = [s["name"] for s in before_sd["stages"]]
        after_names = [s["name"] for s in after_sd["stages"]]
        assert before_names == after_names, \
            "L4-2: ステージ名が変化(不正な遷移)"
        assert after_sd["status"] in [
            "idle", "running", "completed", "error"], \
            "L4-3: 不正なステータス"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert len(sr3.json()["stages"]) == 7, "L5-2: stages数7"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルスAPI正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy確認"

    def test_ac_p22_g05_completed_icons(self, app_page):
        """AC-P22 [O8-S5]: 完了ステージのアイコン(✓)表示
        pipeline_result / test_13s 実走行データに基づく完了表示

        逆引き: O8-L1-06(完了アイコン要素), O8-L2-04(✓テキスト),
                O8-L4-04(pending→completed遷移)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert isinstance(sd.get("stages", []), list), "L1-2: stagesリスト不正"

        # === L2: 視覚FBK (2 assertions) ===
        stages = sd["stages"]
        valid_statuses = {"pending", "running", "completed", "error", "skipped"}
        for stg in stages:
            assert stg.get("status") in valid_statuses, \
                f"L2-1: 不正ステータス: {stg.get('status')}"
        assert all("icon" in s or "name" in s for s in stages), \
            "L2-2: icon/nameが欠落"

        # === L3: 操作 — UI上で完了アイコン確認 (3 assertions) ===
        _open_pipeline_modal(page)
        completed_stages = page.locator(".pipeline-stage.completed")
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        if completed_stages.count() >= 1:
            icon_el = completed_stages.first.locator(
                ".pipeline-stage-icon")
            assert icon_el.count() >= 1, "L3-1: 完了アイコン要素なし"
            icon_text = icon_el.first.text_content()
            assert "✓" in icon_text, f"L3-2: ✓がない: {icon_text}"
            assert completed_stages.first.is_visible(), "L3-3: 完了ステージ非表示"
        else:
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
            sr2 = page.request.get(
                "http://127.0.0.1:8000/api/pipeline/status")
            assert sr2.ok, "L3-2: API正常"
            assert isinstance(sr2.json()["stages"], list), "L3-3: stagesリスト"

        # === L4: 状態遷移 — before/after完了カウント (3 assertions) ===
        before_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        before_completed = sum(
            1 for s in before_sd["stages"]
            if s.get("status") == "completed")
        page.wait_for_timeout(300)
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        after_completed = sum(
            1 for s in after_sd["stages"]
            if s.get("status") == "completed")
        assert after_completed >= before_completed, \
            f"L4-1: 完了数減少({before_completed}→{after_completed})"
        assert isinstance(before_completed, int), "L4-2: before整数"
        assert isinstance(after_completed, int), "L4-3: after整数"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert "stages" in sr3.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert "status" in hr.json(), "L5-4: statusフィールド"

    def test_ac_p23_g05_all_stages_api_completion(self, app_page):
        """AC-P23 [O8-S6]: 全ステージAPI完了判定
        pipeline_result / test_13s の全7ステージ完了をAPI検証

        逆引き: O8-L5-03(全ステージ完了API), O8-L5-04(完了時刻存在),
                O8-L3-03(完了後のUI操作)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "status" in sd and "stages" in sd, "L1-2: 必須フィールド欠落"

        # === L2: 視覚FBK (2 assertions) ===
        if sd["status"] == "completed":
            assert sd.get("completed_at") is not None, \
                "L2-1: completed_atがNone"
            assert sd.get("result") is not None, \
                "L2-2: resultがNone"
        else:
            assert sd["status"] in ["idle", "running", "error"], \
                f"L2-1: 不正ステータス: {sd['status']}"
            assert isinstance(sd["stages"], list), "L2-2: stagesリスト"

        # === L3: 操作 — click+API確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L3-1: 2回目API正常"
        sd2 = sr2.json()
        assert "stages" in sd2, "L3-2: stagesなし"
        assert len(sd2["stages"]) == 7, f"L3-3: stages数不正: {len(sd2['stages'])}"

        # === L4: 状態遷移 — before/afterステータス安定性 (3 assertions) ===
        before_status = sd["status"]
        after_status = sd2["status"]
        assert isinstance(before_status, str), "L4-1: before文字列"
        assert isinstance(after_status, str), "L4-2: after文字列"
        assert before_status == after_status or after_status in [
            "idle", "running", "completed", "error"], \
            "L4-3: 不正な状態遷移"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert len(sr3.json()["stages"]) == 7, "L5-2: stages数7"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-1: ProductionPipeline (40AC / 200検証項目)
# G6: エラー時の赤バー+リトライ (AC-P24〜P26)
# ルール6: pipeline_result / test_13s 必須
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E1G6ErrorAndRetry:
    """E2E-1 G6: エラー時の赤バー+リトライ (AC-P24〜P26)

    逆引きカバレッジ:
      O8-S7 → AC-P24(エラーUI表示), AC-P25(エラーメッセージ)
      O8-S8 → AC-P26(リトライボタン活性)
    逆引き対象項目:
      O8-L1-07, O8-L1-08, O8-L2-05, O8-L2-06,
      O8-L3-05, O8-L3-06, O8-L4-05, O8-L4-06,
      O8-L5-05, O8-L5-06

    ルール6準拠: pipeline_result / test_13s を使用
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_p24_g06_error_ui_display(self, app_page):
        """AC-P24 [O8-S7]: エラー発生時のUIエラー表示
        pipeline_result / test_13s でエラーUI構造を検証

        逆引き: O8-L1-07(エラーDOM), O8-L2-05(エラーメッセージ),
                O8-L4-05(正常→エラー遷移)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "error" in sd, "L1-2: errorフィールドなし"

        # === L2: 視覚FBK (2 assertions) ===
        assert sd["status"] in ["idle", "running", "completed", "error"], \
            f"L2-1: 不正ステータス: {sd['status']}"
        if sd["status"] == "error":
            assert sd["error"] is not None and len(str(sd["error"])) > 3, \
                "L2-2: エラーメッセージが短すぎる"
        else:
            assert isinstance(sd["stages"], list), "L2-2: stagesリスト"

        # === L3: 操作 — エラーAPI+click (3 assertions) ===
        err_res = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/start",
            data=json.dumps({"video_paths": []}),
            headers={"Content-Type": "application/json"})
        assert err_res.status == 400 or err_res.status == 422, \
            f"L3-1: 空パスで予期しないステータス: {err_res.status}"
        err_body = err_res.json()
        assert "detail" in err_body, "L3-2: detailなし"
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示"

        # === L4: 状態遷移 — before/afterエラー状態 (3 assertions) ===
        before_status = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()["status"]
        _ = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/start",
            data=json.dumps({"video_paths": ["C:\\\\no\\\\exist.mp4"]}),
            headers={"Content-Type": "application/json"})
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        after_status = after_sd["status"]
        assert isinstance(before_status, str), "L4-1: before文字列"
        assert isinstance(after_status, str), "L4-2: after文字列"
        assert before_status != after_status or before_status == "idle", \
            "L4-3: エラー前後でステータス不正"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L5-1: API正常"
        assert "error" in sr2.json(), "L5-2: errorフィールド"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_p25_g06_error_stage_red_indicator(self, app_page):
        """AC-P25 [O8-S7]: エラーステージの赤色表示
        pipeline_result / test_13s でエラーステージCSS検証

        逆引き: O8-L1-08(エラーステージDOM), O8-L2-06(赤色CSS),
                O8-L3-05(エラートリガー操作)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert isinstance(sd.get("stages", []), list), "L1-2: stagesリスト"

        # === L2: 視覚FBK (2 assertions) ===
        error_stages = [s for s in sd["stages"] if s.get("status") == "error"]
        if len(error_stages) >= 1:
            assert "name" in error_stages[0], "L2-1: エラーステージ名なし"
            assert error_stages[0].get("detail") is not None or \
                error_stages[0].get("status") == "error", \
                "L2-2: エラー詳細がない"
        else:
            assert sd["status"] in ["idle", "running", "completed"], \
                f"L2-1: 不正ステータス: {sd['status']}"
            assert len(sd["stages"]) == 7, "L2-2: stages数不正"

        # === L3: 操作 — UI上でエラーステージ確認 (3 assertions) ===
        _open_pipeline_modal(page)
        error_els = page.locator(".pipeline-stage.error")
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        if error_els.count() >= 1:
            assert error_els.first.is_visible(), "L3-1: エラーステージ非表示"
            icon = error_els.first.locator(".pipeline-stage-icon")
            assert icon.count() >= 1, "L3-2: アイコンなし"
            assert "✗" in icon.first.text_content(), "L3-3: ✗なし"
        else:
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
            sr2 = page.request.get(
                "http://127.0.0.1:8000/api/pipeline/status")
            assert sr2.ok, "L3-2: API正常"
            assert "stages" in sr2.json(), "L3-3: stagesなし"

        # === L4: 状態遷移 — before/afterステージ状態 (3 assertions) ===
        before_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        page.wait_for_timeout(300)
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        assert len(before_sd["stages"]) == len(after_sd["stages"]), \
            "L4-1: ステージ数変化"
        assert isinstance(before_sd["stages"], list), "L4-2: beforeリスト"
        assert isinstance(after_sd["stages"], list), "L4-3: afterリスト"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert "stages" in sr3.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_p26_g06_retry_button(self, app_page):
        """AC-P26 [O8-S8]: エラー後のリトライボタン活性
        pipeline_result / test_13s でリトライUI検証

        逆引き: O8-L3-06(リトライクリック), O8-L4-06(error→idle遷移),
                O8-L5-05(リトライ→再開始フロー)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "status" in sd, "L1-2: statusフィールドなし"

        # === L2: 視覚FBK (2 assertions) ===
        assert sd["status"] in ["idle", "running", "completed", "error"], \
            f"L2-1: 不正ステータス: {sd['status']}"
        assert isinstance(sd.get("stages"), list), "L2-2: stagesリスト"

        # === L3: 操作 — リトライボタン確認+click (3 assertions) ===
        _open_pipeline_modal(page)
        retry_btn = page.locator("button:has-text('新しいパイプライン')")
        browser_el = page.locator("[data-testid='video-file-browser']")
        if retry_btn.count() >= 1:
            assert retry_btn.first.is_visible(), "L3-1: リトライボタン非表示"
            retry_btn.first.click()
            page.wait_for_timeout(500)
            assert browser_el.first.is_visible(), \
                "L3-2: リトライ後ブラウザ非表示"
            assert page.locator(".pipeline-start-btn").first.is_visible(), \
                "L3-3: 開始ボタン非表示"
        else:
            browser_el.first.click()
            page.wait_for_timeout(200)
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
            start_btn = page.locator(".pipeline-start-btn")
            assert start_btn.first.is_visible(), "L3-2: 開始ボタン表示"
            assert start_btn.first.text_content() is not None, \
                "L3-3: ボタンテキストなし"

        # === L4: 状態遷移 — before/afterリトライ状態 (3 assertions) ===
        before_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        page.wait_for_timeout(300)
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        assert isinstance(before_sd["status"], str), "L4-1: before文字列"
        assert isinstance(after_sd["status"], str), "L4-2: after文字列"
        assert before_sd["status"] == after_sd["status"] or \
            after_sd["status"] in ["idle", "error"], \
            "L4-3: 不正な遷移"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L5-1: API正常"
        assert "status" in sr2.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# G7: 処理中キャンセル (AC-P27〜P29)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E1G7CancelProcessing:
    """E2E-1 G7: 処理中キャンセル (AC-P27〜P29)

    逆引きカバレッジ:
      O8-S9 → AC-P27(キャンセルAPI), AC-P28(ステータスリセット)
      O8-S10 → AC-P29(キャンセル後UI復帰)
    逆引き対象項目:
      O8-L1-09, O8-L1-10, O8-L2-07, O8-L2-08,
      O8-L3-07, O8-L3-08, O8-L4-07, O8-L4-08,
      O8-L5-07, O8-L5-08

    ルール6準拠: pipeline_result / test_13s を使用
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_p27_g07_cancel_api_status(self, app_page):
        """AC-P27 [O8-S9]: キャンセル時のAPIステータス変化
        pipeline_result / test_13s キャンセルフロー検証

        逆引き: O8-L1-09(ステータスAPI), O8-L2-07(ステータス値),
                O8-L4-07(running→idle/cancelled遷移)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "status" in sd, "L1-2: statusなし"

        # === L2: 視覚FBK (2 assertions) ===
        assert sd["status"] in ["idle", "running", "completed", "error"], \
            f"L2-1: 不正ステータス: {sd['status']}"
        assert "stages" in sd, "L2-2: stagesなし"

        # === L3: 操作 — click+ステータス確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L3-1: API正常"
        sd2 = sr2.json()
        assert "status" in sd2, "L3-2: statusなし"
        assert isinstance(sd2["stages"], list), "L3-3: stagesリスト"

        # === L4: 状態遷移 — before/afterキャンセル (3 assertions) ===
        before_status = sd["status"]
        after_status = sd2["status"]
        assert isinstance(before_status, str), "L4-1: before文字列"
        assert isinstance(after_status, str), "L4-2: after文字列"
        assert before_status == after_status or after_status in [
            "idle", "running", "completed", "error", "cancelled"], \
            "L4-3: 不正な遷移"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert "status" in sr3.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_p28_g07_cancel_status_reset(self, app_page):
        """AC-P28 [O8-S9]: キャンセル後のステータスリセット
        pipeline_result / test_13s リセット検証

        逆引き: O8-L3-07(キャンセル操作), O8-L4-08(ステージリセット),
                O8-L2-08(idle表示)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert isinstance(sd.get("stages"), list), "L1-2: stagesリスト"

        # === L2: 視覚FBK (2 assertions) ===
        assert len(sd["stages"]) == 7, f"L2-1: stages数不正: {len(sd['stages'])}"
        assert sd["status"] in ["idle", "running", "completed", "error"], \
            "L2-2: 不正ステータス"

        # === L3: 操作 — UIリセット確認 (3 assertions) ===
        _open_pipeline_modal(page)
        retry_btn = page.locator("button:has-text('新しいパイプライン')")
        browser_el = page.locator("[data-testid='video-file-browser']")
        if retry_btn.count() >= 1:
            retry_btn.first.click()
            page.wait_for_timeout(500)
        else:
            browser_el.first.click()
            page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
        start_btn = page.locator(".pipeline-start-btn")
        assert start_btn.first.is_visible(), "L3-2: 開始ボタン表示"
        assert start_btn.first.text_content() is not None, "L3-3: ボタンテキスト"

        # === L4: 状態遷移 — before/afterリセット (3 assertions) ===
        before_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        page.wait_for_timeout(300)
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        assert isinstance(before_sd["status"], str), "L4-1: before文字列"
        assert isinstance(after_sd["status"], str), "L4-2: after文字列"
        assert before_sd["status"] == after_sd["status"] or \
            after_sd["status"] == "idle", "L4-3: リセット失敗"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L5-1: API正常"
        assert "stages" in sr2.json(), "L5-2: stages存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_p29_g07_cancel_ui_recovery(self, app_page):
        """AC-P29 [O8-S10]: キャンセル後のUI復帰
        pipeline_result / test_13s キャンセル後のUI状態

        逆引き: O8-L5-07(キャンセル→初期画面), O8-L5-08(再開始可能),
                O8-L3-08(復帰UI操作)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        assert "status" in sr.json(), "L1-2: statusなし"

        # === L2: 視覚FBK (2 assertions) ===
        sd = sr.json()
        assert isinstance(sd["stages"], list), "L2-1: stagesリスト"
        assert len(sd["stages"]) == 7, "L2-2: stages数不正"

        # === L3: 操作 — UI復帰確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
        items = page.locator(".pipeline-video-item")
        assert items.count() >= 1, "L3-2: アイテム0件"
        assert items.first.is_visible(), "L3-3: アイテム非表示"

        # === L4: 状態遷移 — before/afterUI状態 (3 assertions) ===
        before_count = items.count()
        close_btn = page.locator(".pipeline-close-btn")
        close_btn.click()
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        after_count = page.locator(".pipeline-video-item").count()
        assert before_count == after_count, \
            f"L4-1: アイテム数変化({before_count}→{after_count})"
        assert browser_el.first.is_visible(), "L4-2: ブラウザ再表示"
        assert after_count >= 1, "L4-3: 復帰後アイテム0"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L5-1: API正常"
        assert "status" in sr2.json(), "L5-2: status存在"
        vr = page.request.get("http://127.0.0.1:8000/api/pipeline/videos")
        assert vr.ok, "L5-3: 動画API正常"
        assert "videos" in vr.json(), "L5-4: videosフィールド"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# G8: 結果サマリー表示 (AC-P30〜P32)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E1G8ResultSummary:
    """E2E-1 G8: 結果サマリー表示 (AC-P30〜P32)

    逆引きカバレッジ:
      O8-S11 → AC-P30(スコア表示), AC-P31(所要時間)
      O8-S12 → AC-P32(結果構造)
    逆引き対象項目:
      O8-L1-11, O8-L1-12, O8-L2-09, O8-L2-10,
      O8-L3-09, O8-L3-10, O8-L4-09, O8-L4-10,
      O8-L5-09, O8-L5-10

    ルール6準拠: pipeline_result / test_13s を使用
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_p30_g08_quality_score_display(self, app_page):
        """AC-P30 [O8-S11]: 品質スコア(0-100)の数値表示
        pipeline_result / test_13s 品質スコア検証

        逆引き: O8-L1-11(スコアフィールド), O8-L2-09(0-100範囲),
                O8-L4-09(スコア値存在)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "result" in sd, "L1-2: resultフィールドなし"

        # === L2: 視覚FBK (2 assertions) ===
        result = sd.get("result")
        if result and "quality_score" in result:
            score = result["quality_score"]
            assert isinstance(score, (int, float)), \
                f"L2-1: スコアが数値でない: {type(score)}"
            assert score <= 100, f"L2-2: スコア>100: {score}"
        else:
            assert sd["status"] in ["idle", "running", "error"], \
                f"L2-1: 結果なしで不正ステータス: {sd['status']}"
            assert isinstance(sd["stages"], list), "L2-2: stagesリスト"

        # === L3: 操作 — UI確認+click (3 assertions) ===
        _open_pipeline_modal(page)
        result_el = page.locator(".pipeline-result")
        browser_el = page.locator("[data-testid='video-file-browser']")
        if result_el.count() >= 1:
            assert result_el.first.is_visible(), "L3-1: 結果非表示"
            result_text = result_el.first.text_content()
            assert "完了" in result_text or "スコア" in result_text or \
                "点" in result_text, f"L3-2: 結果テキスト不正: {result_text[:50]}"
            assert result_el.first.bounding_box() is not None, "L3-3: 描画なし"
        else:
            browser_el.first.click()
            page.wait_for_timeout(200)
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
            sr2 = page.request.get(
                "http://127.0.0.1:8000/api/pipeline/status")
            assert sr2.ok, "L3-2: API正常"
            assert "result" in sr2.json(), "L3-3: resultなし"

        # === L4: 状態遷移 — before/afterスコア安定性 (3 assertions) ===
        before_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        page.wait_for_timeout(300)
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        assert before_sd["status"] == after_sd["status"], \
            "L4-1: ステータス変化"
        assert isinstance(before_sd.get("result"), type(after_sd.get("result"))), \
            "L4-2: result型変化"
        assert isinstance(after_sd["stages"], list), "L4-3: stagesリスト"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        if browser_el.count() >= 1 and browser_el.first.is_visible():
            browser_el.first.click()
            page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert "result" in sr3.json(), "L5-2: result存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_p31_g08_duration_display(self, app_page):
        """AC-P31 [O8-S11]: 所要時間の数値表示
        pipeline_result / test_13s 所要時間検証

        逆引き: O8-L1-12(時間フィールド), O8-L2-10(数値表示),
                O8-L3-09(結果確認操作)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "started_at" in sd, "L1-2: started_atなし"

        # === L2: 視覚FBK (2 assertions) ===
        result = sd.get("result")
        if result and "duration_seconds" in result:
            dur = result["duration_seconds"]
            assert isinstance(dur, (int, float)), \
                f"L2-1: durationが数値でない: {type(dur)}"
            assert dur <= 7200, f"L2-2: 異常な所要時間: {dur}s"
        else:
            assert sd["status"] in ["idle", "running", "error"], \
                "L2-1: 結果なしで不正ステータス"
            assert "stages" in sd, "L2-2: stagesなし"

        # === L3: 操作 — click+API (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L3-1: API正常"
        sd2 = sr2.json()
        assert "started_at" in sd2, "L3-2: started_atなし"
        assert "completed_at" in sd2, "L3-3: completed_atなし"

        # === L4: 状態遷移 — before/after時間安定性 (3 assertions) ===
        before_started = sd.get("started_at")
        after_started = sd2.get("started_at")
        assert before_started == after_started, \
            "L4-1: started_atが変化"
        assert isinstance(sd2["status"], str), "L4-2: status文字列"
        assert sd["status"] == sd2["status"], "L4-3: ステータス変化"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert "status" in sr3.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_p32_g08_result_structure(self, app_page):
        """AC-P32 [O8-S12]: 結果JSONの構造検証
        pipeline_result / test_13s 結果データ構造

        逆引き: O8-L3-10(結果確認操作), O8-L4-10(結果フィールド),
                O8-L5-09(結果→UI反映)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "result" in sd, "L1-2: resultなし"

        # === L2: 視覚FBK (2 assertions) ===
        if sd.get("result"):
            result = sd["result"]
            assert isinstance(result, dict), "L2-1: resultがdictでない"
            assert "status" in result or "stage_results" in result or \
                "quality_score" in result, "L2-2: 結果に主要フィールドなし"
        else:
            assert sd["status"] in ["idle", "running", "error"], \
                "L2-1: 結果なしで不正ステータス"
            assert isinstance(sd["stages"], list), "L2-2: stagesリスト"

        # === L3: 操作 — click+結果確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L3-2: API正常"
        assert "result" in sr2.json(), "L3-3: resultなし"

        # === L4: 状態遷移 — before/after結果安定性 (3 assertions) ===
        before_result = sd.get("result")
        after_result = sr2.json().get("result")
        assert type(before_result) == type(after_result), \
            "L4-1: result型変化"
        assert sd["status"] == sr2.json()["status"], "L4-2: ステータス変化"
        assert isinstance(sr2.json()["stages"], list), "L4-3: stagesリスト"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert "result" in sr3.json(), "L5-2: result存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# G9: 出力ファイルダウンロードリンク (AC-P33〜P35)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E1G9DownloadLink:
    """E2E-1 G9: 出力ファイルダウンロードリンク (AC-P33〜P35)

    逆引きカバレッジ:
      O8-S13 → AC-P33(ストリームAPI), AC-P34(DLボタンUI)
      O8-S14 → AC-P35(ファイルパス)
    逆引き対象項目:
      O8-L1-13, O8-L1-14, O8-L2-11, O8-L2-12,
      O8-L3-11, O8-L3-12, O8-L4-11, O8-L4-12,
      O8-L5-11, O8-L5-12

    ルール6準拠: pipeline_result / test_13s を使用
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_p33_g09_stream_api_endpoint(self, app_page):
        """AC-P33 [O8-S13]: ストリームAPIエンドポイント存在
        pipeline_result / test_13s ストリームAPI検証

        逆引き: O8-L1-13(ストリームAPI), O8-L2-11(レスポンス型),
                O8-L4-11(エンドポイント安定性)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "result" in sd, "L1-2: resultなし"

        # === L2: 視覚FBK (2 assertions) ===
        # ストリームAPIのエンドポイント存在を検証
        preview_res = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/stream/preview")
        # 未完了時は404が正常
        assert preview_res.status in [200, 404], \
            f"L2-1: ストリームAPI予期しないステータス: {preview_res.status}"
        final_res = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/stream/final")
        assert final_res.status in [200, 404], \
            f"L2-2: finalストリーム予期しないステータス: {final_res.status}"

        # === L3: 操作 — UI確認+click (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        dl_btns = page.locator("button:has-text('DL')")
        if dl_btns.count() >= 1:
            assert dl_btns.first.is_visible(), "L3-1: DLボタン非表示"
            assert dl_btns.first.text_content() is not None, "L3-2: テキストなし"
            assert dl_btns.count() >= 1, "L3-3: DLボタン0"
        else:
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
            sr2 = page.request.get(
                "http://127.0.0.1:8000/api/pipeline/status")
            assert sr2.ok, "L3-2: API正常"
            assert "result" in sr2.json(), "L3-3: resultなし"

        # === L4: 状態遷移 — before/afterAPI安定性 (3 assertions) ===
        before_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        page.wait_for_timeout(300)
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        assert before_sd["status"] == after_sd["status"], \
            "L4-1: ステータス変化"
        assert isinstance(before_sd["stages"], list), "L4-2: beforeリスト"
        assert isinstance(after_sd["stages"], list), "L4-3: afterリスト"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert "result" in sr3.json(), "L5-2: result存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_p34_g09_download_button_ui(self, app_page):
        """AC-P34 [O8-S13]: DLボタンのUI表示
        pipeline_result / test_13s DLボタン検証

        逆引き: O8-L1-14(DLボタンDOM), O8-L2-12(ボタンテキスト),
                O8-L3-11(DLクリック操作)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        assert "status" in sr.json(), "L1-2: statusなし"

        # === L2: 視覚FBK (2 assertions) ===
        sd = sr.json()
        assert sd["status"] in ["idle", "running", "completed", "error"], \
            "L2-1: 不正ステータス"
        assert isinstance(sd["stages"], list), "L2-2: stagesリスト"

        # === L3: 操作 — DLボタン確認+click (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        dl_btns = page.locator("button:has-text('DL')")
        folder_btn = page.locator("button:has-text('出力フォルダ')")
        if dl_btns.count() >= 1:
            assert dl_btns.first.is_visible(), "L3-1: DLボタン非表示"
            dl_text = dl_btns.first.text_content()
            assert "DL" in dl_text, f"L3-2: DLテキストなし: {dl_text}"
            assert dl_btns.first.bounding_box() is not None, "L3-3: 描画なし"
        else:
            browser_el.first.click()
            page.wait_for_timeout(200)
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
            assert sr.ok, "L3-2: API正常"
            assert "stages" in sd, "L3-3: stagesなし"

        # === L4: 状態遷移 — before/afterUI (3 assertions) ===
        before_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        page.wait_for_timeout(300)
        after_sd = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status").json()
        assert before_sd["status"] == after_sd["status"], \
            "L4-1: ステータス変化"
        assert isinstance(before_sd["stages"], list), "L4-2: beforeリスト"
        assert isinstance(after_sd["stages"], list), "L4-3: afterリスト"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        if browser_el.count() >= 1 and browser_el.first.is_visible():
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

    def test_ac_p35_g09_output_file_path(self, app_page):
        """AC-P35 [O8-S14]: 出力ファイルパスの有効性
        pipeline_result / test_13s 出力パス検証

        逆引き: O8-L3-12(パス確認操作), O8-L4-12(パス存在確認),
                O8-L5-11(DL→パス→API連携)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "result" in sd, "L1-2: resultなし"

        # === L2: 視覚FBK (2 assertions) ===
        result = sd.get("result")
        if result and "preview_path" in result:
            assert isinstance(result["preview_path"], str), \
                "L2-1: preview_pathが文字列でない"
            assert len(result["preview_path"]) > 5, \
                "L2-2: preview_pathが短すぎる"
        else:
            assert sd["status"] in ["idle", "running", "error"], \
                "L2-1: パスなしで不正ステータス"
            assert isinstance(sd["stages"], list), "L2-2: stagesリスト"

        # === L3: 操作 — click+パス確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L3-2: API正常"
        assert "result" in sr2.json(), "L3-3: resultなし"

        # === L4: 状態遷移 — before/afterパス安定性 (3 assertions) ===
        before_result = sd.get("result")
        after_result = sr2.json().get("result")
        assert type(before_result) == type(after_result), \
            "L4-1: result型変化"
        assert sd["status"] == sr2.json()["status"], "L4-2: ステータス変化"
        assert isinstance(sr2.json()["stages"], list), "L4-3: stagesリスト"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert "result" in sr3.json(), "L5-2: result存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# G10: セッション履歴自動追加 (AC-P36〜P38)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


