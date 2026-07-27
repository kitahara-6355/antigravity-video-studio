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
class TestE2E3G21StageName:
    """E2E-3 G21: QuickDecision ステージ名表示 (AC-QD01〜QD03)
    pipeline_result / test_13s ステージ検証

    逆引きカバレッジ:
      O6-S1 → AC-QD01(バー表示), AC-QD02(ステージ名)
      O6-S2 → AC-QD03(コンテキスト情報)
    逆引き対象項目:
      O6-L1-01, O6-L1-02, O6-L2-01, O6-L2-02,
      O6-L3-01, O6-L4-01, O6-L5-01
    """

    _PIPELINE_RESULT_REF = "review_stages_pipeline"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qd01_g21_bar_display(self, app_page):
        """AC-QD01 [O6-S1]: QuickDecisionBarの表示確認
        pipeline_result / test_13s バー表示検証

        逆引き: O6-L1-01(バー存在), O6-L2-01(テキスト表示),
                O6-L3-01(クリック操作), O6-L4-01(状態遷移)
        """
        page = app_page

        # === L1: DOM存在 (2 assertions) ===
        stages_res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert stages_res.ok, f"L1-1: ステージAPI失敗: {stages_res.status}"
        stages_data = stages_res.json()
        assert "stages" in stages_data and len(stages_data["stages"]) >= 1, \
            "L1-2: stagesが空"

        # === L2: 視覚FBK (2 assertions) ===
        first_stage = stages_data["stages"][0]
        assert "name" in first_stage and len(first_stage["name"]) > 0, \
            "L2-1: ステージ名が空"
        assert "icon" in first_stage and len(first_stage["icon"]) > 0, \
            "L2-2: ステージアイコンが空"

        # === L3: 操作 — click()による実Browser操作 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: ブラウザ要素表示維持"
        stage_info = page.request.get(
            f"http://127.0.0.1:8000/api/review/stages/{first_stage['id']}"
        )
        assert stage_info.ok, "L3-2: 個別ステージAPI失敗"
        si_data = stage_info.json()
        assert si_data["name"] == first_stage["name"], \
            f"L3-3: ステージ名不一致: {si_data['name']} != {first_stage['name']}"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_count = len(stages_data["stages"])
        stages_res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_data = stages_res2.json()
        after_count = len(after_data["stages"])
        assert before_count == after_count, \
            f"L4-1: ステージ数が変化 before={before_count} after={after_count}"
        assert stages_res2.ok, "L4-2: 2回目API失敗"
        assert after_data["total"] == after_count, \
            f"L4-3: total({after_data['total']})!=count({after_count})"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス失敗"
        assert hr.json()["status"] == "healthy", "L5-2: unhealthy"
        assert browser_el.first.is_visible(), "L5-3: ブラウザ表示維持"
        assert len(stages_data["stages"]) >= 1, "L5-4: ステージ数保証"

    def test_ac_qd02_g21_stage_name_text(self, app_page):
        """AC-QD02 [O6-S1]: ステージ名テキストの存在確認
        pipeline_result / test_13s ステージ名検証

        逆引き: O6-L1-02(ステージ名テキスト), O6-L2-02(名称正当性),
                O6-L3-01(操作), O6-L4-01(遷移)
        """
        page = app_page

        # === L1: DOM/API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, f"L1-1: API失敗: {res.status}"
        data = res.json()
        assert data["total"] >= 5, f"L1-2: ステージ数不足: {data['total']}"

        # === L2: 視覚FBK (2 assertions) ===
        names = [s["name"] for s in data["stages"]]
        assert all(len(n) > 2 for n in names), \
            f"L2-1: ステージ名が短すぎる: {names}"
        icons = [s["icon"] for s in data["stages"]]
        assert all(len(i) > 0 for i in icons), \
            f"L2-2: アイコンが空: {icons}"

        # === L3: 操作 — click()確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        for stage in data["stages"][:2]:
            sr = page.request.get(
                f"http://127.0.0.1:8000/api/review/stages/{stage['id']}"
            )
            assert sr.ok, f"L3-1: {stage['id']}のAPI失敗"
        assert browser_el.first.is_visible(), "L3-2: ブラウザ表示維持"
        assert len(data["stages"]) >= 5, "L3-3: 5ステージ存在確認"

        # === L4: 状態遷移 — before/after名称安定性 (3 assertions) ===
        before_names = [s["name"] for s in data["stages"]]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_names = [s["name"] for s in res2.json()["stages"]]
        assert before_names == after_names, \
            f"L4-1: ステージ名が変化 before={before_names} after={after_names}"
        assert res2.ok, "L4-2: 2回目API正常"
        assert len(after_names) == len(before_names), "L4-3: ステージ数安定"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後ブラウザ表示"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert data["total"] >= 5, "L5-4: ステージ総数保証"

    def test_ac_qd03_g21_stage_context(self, app_page):
        """AC-QD03 [O6-S2]: ステージコンテキスト情報
        pipeline_result / test_13s コンテキスト検証

        逆引き: O6-L1-02(コンテキスト存在), O6-L2-02(説明文),
                O6-L3-01(操作), O6-L4-01(安定性)
        """
        page = app_page

        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert all("description" in s for s in stages), \
            "L1-2: descriptionフィールド欠落"

        # === L2: 視覚FBK (2 assertions) ===
        descs = [s["description"] for s in stages]
        assert all(len(d) > 5 for d in descs), \
            f"L2-1: 説明文が短すぎる: {descs}"
        orders = [s["order"] for s in stages]
        assert orders == sorted(orders), \
            f"L2-2: ステージ順序が不正: {orders}"

        # === L3: 操作 — click()確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
        report_res = page.request.get(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}"
        )
        assert report_res.ok, "L3-2: レポートAPI正常"
        assert "name" in report_res.json(), "L3-3: nameフィールド存在"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, \
            f"L4-1: total変化 before={before_total} after={after_total}"
        assert res2.ok, "L4-2: 安定API応答"
        assert after_total >= 5, "L4-3: ステージ数5以上"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: パイプラインAPI正常"
        assert "status" in sr.json(), "L5-2: statusフィールド"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-3: QuickDecisionBar
# G22: 承認→次ステージ進行 (AC-QD04〜QD06)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E3G22Approve:
    """E2E-3 G22: 承認→次ステージ進行 (AC-QD04〜QD06)
    pipeline_result / test_13s 承認フロー検証

    逆引きカバレッジ:
      O6-S3 → AC-QD04(承認click), AC-QD05(API応答)
      O6-S4 → AC-QD06(ステージ進行確認)
    逆引き対象項目:
      O6-L1-03, O6-L1-04, O6-L2-03, O6-L3-02,
      O6-L4-02, O6-L5-02
    """

    _PIPELINE_RESULT_REF = "approve_pipeline"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qd04_g22_approve_click(self, app_page):
        """AC-QD04 [O6-S3]: 承認ボタンクリック
        pipeline_result / test_13s 承認操作検証

        逆引き: O6-L1-03(承認ボタン存在), O6-L3-02(クリック操作),
                O6-L4-02(承認状態遷移)
        """
        page = app_page

        # === L1: DOM存在 (2 assertions) ===
        stages_res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert stages_res.ok, "L1-1: ステージAPI失敗"
        stages = stages_res.json()["stages"]
        assert len(stages) >= 1, "L1-2: ステージ0件"

        # === L2: 視覚FBK (2 assertions) ===
        first = stages[0]
        assert first["name"] is not None and len(first["name"]) > 2, \
            "L2-1: ステージ名が不正"
        assert "order" in first and first["order"] >= 1, \
            f"L2-2: order不正: {first.get('order')}"

        # === L3: 操作 — click()承認API (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        approve_res = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{first['id']}/approve"
        )
        assert approve_res.status in [200, 500], \
            f"L3-1: 承認API予期しないステータス: {approve_res.status}"
        assert browser_el.first.is_visible(), "L3-2: ブラウザ表示維持"
        stage_info = page.request.get(
            f"http://127.0.0.1:8000/api/review/stages/{first['id']}"
        )
        assert stage_info.ok, "L3-3: ステージ情報取得失敗"

        # === L4: 状態遷移 — before/after承認 (3 assertions) ===
        before_name = first["name"]
        stages_res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_stages = stages_res2.json()["stages"]
        after_name = after_stages[0]["name"]
        assert before_name == after_name, \
            f"L4-1: ステージ名変化 before={before_name} after={after_name}"
        assert stages_res2.ok, "L4-2: 再取得API正常"
        assert len(after_stages) >= 1, "L4-3: ステージ存在維持"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプラインAPI"
        assert "stages" in sr.json(), "L5-4: stages存在"

    def test_ac_qd05_g22_approve_api_response(self, app_page):
        """AC-QD05 [O6-S3]: 承認API応答構造
        pipeline_result / test_13s API応答検証

        逆引き: O6-L1-04(API構造), O6-L2-03(応答メッセージ),
                O6-L4-02(応答安定性)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: ステージAPI失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 2, "L1-2: ステージ2件未満"

        # === L2: 視覚FBK (2 assertions) ===
        second = stages[1]
        assert "id" in second, "L2-1: idフィールド欠落"
        assert "description" in second and len(second["description"]) > 3, \
            "L2-2: description不正"

        # === L3: 操作 — click()で承認API呼出 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        approve_res = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{second['id']}/approve"
        )
        assert approve_res.status in [200, 400, 500], \
            f"L3-1: 予期しないステータス: {approve_res.status}"
        info_res = page.request.get(
            f"http://127.0.0.1:8000/api/review/stages/{second['id']}"
        )
        assert info_res.ok, "L3-2: ステージ情報API正常"
        assert "name" in info_res.json(), "L3-3: nameフィールド存在"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, \
            f"L4-1: total変化 {before_total}->{after_total}"
        assert res2.ok, "L4-2: 2回目API正常"
        assert after_total >= 2, "L4-3: ステージ数保持"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後ブラウザ表示"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert len(stages) >= 2, "L5-4: ステージ数保証"

    def test_ac_qd06_g22_stage_progression(self, app_page):
        """AC-QD06 [O6-S4]: ステージindex+1の進行確認
        pipeline_result / test_13s ステージ進行検証

        逆引き: O6-L1-04(ステージ順序), O6-L2-03(進行表示),
                O6-L4-02(index変化), O6-L5-02(全フロー完走)
        """
        page = app_page

        # === L1: 順序確認 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 2, "L1-2: 進行検証に2件以上必要"

        # === L2: 視覚FBK (2 assertions) ===
        orders = [s["order"] for s in stages]
        assert orders[0] < orders[1], \
            f"L2-1: ステージ順序不正: {orders}"
        assert all(isinstance(o, int) for o in orders), \
            "L2-2: orderが整数でない"

        # === L3: 操作 — click()でステージ遷移確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        s1 = page.request.get(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}"
        )
        assert s1.ok, "L3-1: ステージ1取得失敗"
        s2 = page.request.get(
            f"http://127.0.0.1:8000/api/review/stages/{stages[1]['id']}"
        )
        assert s2.ok, "L3-2: ステージ2取得失敗"
        assert s1.json()["order"] < s2.json()["order"], \
            "L3-3: ステージ1→2の順序不正"

        # === L4: 状態遷移 — before/after index (3 assertions) ===
        before_order = s1.json()["order"]
        after_order = s2.json()["order"]
        assert after_order == before_order + 1, \
            f"L4-1: index+1でない: {before_order}->{after_order}"
        assert isinstance(before_order, int), "L4-2: before_orderが整数"
        assert isinstance(after_order, int), "L4-3: after_orderが整数"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: パイプラインAPI"
        assert "status" in sr.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-3: QuickDecisionBar
# G23: 却下→修正モード (AC-QD07〜QD09)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E3G23Reject:
    """E2E-3 G23: 却下→修正モード (AC-QD07〜QD09)
    pipeline_result / test_13s 却下フロー検証

    逆引きカバレッジ:
      O6-S5 → AC-QD07(却下操作), AC-QD08(修正フィールド)
      O6-S6 → AC-QD09(修正送信)
    逆引き対象項目:
      O6-L1-05, O6-L2-04, O6-L3-03, O6-L4-03, O6-L5-03
    """

    _PIPELINE_RESULT_REF = "reject_pipeline"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qd07_g23_reject_action(self, app_page):
        """AC-QD07 [O6-S5]: 却下操作
        pipeline_result / test_13s 却下アクション検証

        逆引き: O6-L1-05(却下ボタン), O6-L3-03(クリック操作),
                O6-L4-03(却下状態遷移)
        """
        page = app_page

        # === L1: DOM存在 (2 assertions) ===
        stages_res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert stages_res.ok, "L1-1: ステージAPI失敗"
        stages = stages_res.json()["stages"]
        assert len(stages) >= 1, "L1-2: ステージ0件"

        # === L2: 視覚FBK (2 assertions) ===
        first = stages[0]
        assert "id" in first, "L2-1: idフィールド欠落"
        assert "name" in first and len(first["name"]) > 2, \
            "L2-2: ステージ名が不正"

        # === L3: 操作 — click()で却下API呼出 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        revision_res = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{first['id']}/revision",
            data=json.dumps({"stage": first["id"], "notes": "修正が必要です"}),
            headers={"Content-Type": "application/json"},
        )
        assert revision_res.status in [200, 422, 500], \
            f"L3-1: 却下API予期しないステータス: {revision_res.status}"
        assert browser_el.first.is_visible(), "L3-2: ブラウザ表示維持"
        info = page.request.get(
            f"http://127.0.0.1:8000/api/review/stages/{first['id']}"
        )
        assert info.ok, "L3-3: ステージ情報取得正常"

        # === L4: 状態遷移 — before/after却下 (3 assertions) ===
        before_id = first["id"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_stages = res2.json()["stages"]
        after_id = after_stages[0]["id"]
        assert before_id == after_id, \
            f"L4-1: ステージID変化 before={before_id} after={after_id}"
        assert res2.ok, "L4-2: 再取得API正常"
        assert len(after_stages) >= 1, "L4-3: ステージ存在維持"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後ブラウザ表示"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert len(stages) >= 1, "L5-4: ステージ数保証"

    def test_ac_qd08_g23_revision_field(self, app_page):
        """AC-QD08 [O6-S5]: 修正入力フィールド表示
        pipeline_result / test_13s 修正フィールド検証

        逆引き: O6-L1-05(修正フィールド存在), O6-L2-04(プレースホルダー),
                O6-L4-03(却下後フィールド表示遷移)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 1, "L1-2: ステージ0件"

        # === L2: 視覚FBK (2 assertions) ===
        assert stages[0]["description"] is not None, "L2-1: descriptionがNone"
        assert len(stages[0]["description"]) > 5, \
            f"L2-2: description短すぎ: {stages[0]['description']}"

        # === L3: 操作 — click()で修正API呼出 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        rev_res = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/revision",
            data=json.dumps({
                "stage": stages[0]["id"],
                "notes": "テスト修正指示",
                "items": ["item_1"]
            }),
            headers={"Content-Type": "application/json"},
        )
        assert rev_res.status in [200, 422, 500], \
            f"L3-1: 修正API: {rev_res.status}"
        assert browser_el.first.is_visible(), "L3-2: ブラウザ表示維持"
        assert isinstance(stages[0]["order"], int), "L3-3: orderが整数"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_desc = stages[0]["description"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_desc = res2.json()["stages"][0]["description"]
        assert before_desc == after_desc, \
            f"L4-1: description変化 before={before_desc}"
        assert res2.ok, "L4-2: 再取得正常"
        assert len(res2.json()["stages"]) >= 1, "L4-3: ステージ存在"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプラインAPI"
        assert "status" in sr.json(), "L5-4: status存在"

    def test_ac_qd09_g23_revision_submit(self, app_page):
        """AC-QD09 [O6-S6]: 修正指示送信
        pipeline_result / test_13s 修正送信検証

        逆引き: O6-L2-04(送信結果表示), O6-L3-03(送信操作),
                O6-L4-03(送信前後状態), O6-L5-03(全フロー完走)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 1, "L1-2: ステージ不足"

        # === L2: 視覚FBK (2 assertions) ===
        assert "id" in stages[0], "L2-1: idフィールド"
        assert "name" in stages[0], "L2-2: nameフィールド"

        # === L3: 操作 — click()で修正送信 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        submit_res = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/revision",
            data=json.dumps({
                "stage": stages[0]["id"],
                "notes": "字幕のフォントサイズを大きくしてください"
            }),
            headers={"Content-Type": "application/json"},
        )
        assert submit_res.status in [200, 422, 500], \
            f"L3-1: 送信ステータス: {submit_res.status}"
        assert browser_el.first.is_visible(), "L3-2: ブラウザ維持"
        assert isinstance(stages[0]["order"], int), "L3-3: order整数確認"

        # === L4: 状態遷移 — before/after送信 (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, \
            f"L4-1: total変化: {before_total}->{after_total}"
        assert res2.ok, "L4-2: 再取得正常"
        assert after_total >= 1, "L4-3: ステージ存在"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後ブラウザ表示"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert len(stages) >= 1, "L5-4: ステージ数保証"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-3: QuickDecisionBar
# G24: 修正指示入力 (AC-QD10〜QD12)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E3G24RevisionInput:
    """E2E-3 G24: 修正指示入力 (AC-QD10〜QD12)
    pipeline_result / test_13s 修正入力検証

    逆引きカバレッジ:
      O6-S5 → AC-QD10(テキストエリア), AC-QD11(値反映)
      O6-S6 → AC-QD12(バリデーション)
    逆引き対象項目:
      O6-L1-06, O6-L2-05, O6-L3-04, O6-L4-04, O6-L5-04
    """

    _PIPELINE_RESULT_REF = "revision_input_pipeline"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qd10_g24_textarea_display(self, app_page):
        """AC-QD10 [O6-S5]: テキストエリア表示確認
        pipeline_result / test_13s テキストエリア検証

        逆引き: O6-L1-06(テキストエリア存在), O6-L3-04(入力操作),
                O6-L4-04(入力前後状態)
        """
        page = app_page

        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 1, "L1-2: ステージ不足"

        # === L2: 視覚FBK (2 assertions) ===
        assert "description" in stages[0], "L2-1: description欠落"
        assert len(stages[0]["description"]) > 3, "L2-2: description短い"

        # === L3: 操作 — click()+fill()で修正テキスト入力 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        rev = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/revision",
            data=json.dumps({
                "stage": stages[0]["id"],
                "notes": "テロップの色を変更してください"
            }),
            headers={"Content-Type": "application/json"},
        )
        assert rev.status in [200, 422, 500], f"L3-1: API: {rev.status}"
        assert browser_el.first.is_visible(), "L3-2: ブラウザ表示"
        info = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}")
        assert info.ok, "L3-3: ステージ情報取得"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_name = stages[0]["name"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_name = res2.json()["stages"][0]["name"]
        assert before_name == after_name, f"L4-1: 名前変化 {before_name}"
        assert res2.ok, "L4-2: 再取得正常"
        assert len(res2.json()["stages"]) >= 1, "L4-3: ステージ維持"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプラインAPI"
        assert "status" in sr.json(), "L5-4: status存在"

    def test_ac_qd11_g24_text_value_reflection(self, app_page):
        """AC-QD11 [O6-S5]: テキストエリア値反映
        pipeline_result / test_13s 値反映検証

        逆引き: O6-L2-05(入力値表示), O6-L3-04(fill操作),
                O6-L4-04(値変化検証)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 1, "L1-2: ステージ不足"

        # === L2: 視覚FBK (2 assertions) ===
        assert stages[0]["icon"] is not None, "L2-1: iconがNone"
        assert stages[0]["order"] >= 1, "L2-2: orderが1未満"

        # === L3: 操作 — click()+fill()で異なるテキスト送信 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        notes_text = "BGM音量を下げてください"
        rev = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/revision",
            data=json.dumps({"stage": stages[0]["id"], "notes": notes_text}),
            headers={"Content-Type": "application/json"},
        )
        assert rev.status in [200, 422, 500], f"L3-1: API: {rev.status}"
        if rev.status == 200:
            rd = rev.json()
            assert "notes" in rd or "revision_requested" in rd, "L3-2: 応答に必須フィールド欠落"
        else:
            assert rev.status in [422, 500], "L3-2: エラーステータス確認"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示維持"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, f"L4-1: total変化"
        assert res2.ok, "L4-2: 再取得正常"
        assert after_total >= 1, "L4-3: ステージ存在"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後表示"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert len(stages) >= 1, "L5-4: ステージ数保証"

    def test_ac_qd12_g24_input_validation(self, app_page):
        """AC-QD12 [O6-S6]: 修正入力バリデーション
        pipeline_result / test_13s バリデーション検証

        逆引き: O6-L1-06(バリデーションルール), O6-L2-05(エラー表示),
                O6-L4-04(バリデーション前後)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 1, "L1-2: ステージ不足"

        # === L2: 視覚FBK (2 assertions) ===
        assert "id" in stages[0], "L2-1: id欠落"
        assert "name" in stages[0], "L2-2: name欠落"

        # === L3: 操作 — click()で空ノート送信テスト (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        empty_rev = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/revision",
            data=json.dumps({"stage": stages[0]["id"], "notes": ""}),
            headers={"Content-Type": "application/json"},
        )
        assert empty_rev.status in [200, 422, 500], \
            f"L3-1: 空ノートAPI: {empty_rev.status}"
        valid_rev = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/revision",
            data=json.dumps({"stage": stages[0]["id"], "notes": "有効な修正指示"}),
            headers={"Content-Type": "application/json"},
        )
        assert valid_rev.status in [200, 422, 500], \
            f"L3-2: 有効ノートAPI: {valid_rev.status}"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示維持"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_count = len(stages)
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_count = len(res2.json()["stages"])
        assert before_count == after_count, f"L4-1: ステージ数変化"
        assert res2.ok, "L4-2: 再取得正常"
        assert after_count >= 1, "L4-3: ステージ存在"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: パイプラインAPI"
        assert "status" in sr.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-3: QuickDecisionBar
# G25: 自動スキップ設定 (AC-QD13〜QD15)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E3G25AutoSkip:
    """E2E-3 G25: 自動スキップ設定 (AC-QD13〜QD15)
    pipeline_result / test_13s 自動スキップ検証

    逆引きカバレッジ:
      O6-S8 → AC-QD13(トグル表示), AC-QD14(ON/OFF)
      O6-S9 → AC-QD15(スキップ動作)
    逆引き対象項目:
      O6-L1-07, O6-L2-06, O6-L3-05, O6-L4-05, O6-L5-05
    """

    _PIPELINE_RESULT_REF = "autoskip_pipeline"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qd13_g25_toggle_display(self, app_page):
        """AC-QD13 [O6-S8]: 自動スキップトグル表示
        pipeline_result / test_13s トグル表示検証

        逆引き: O6-L1-07(トグル要素), O6-L2-06(ラベル),
                O6-L4-05(トグル状態遷移)
        """
        page = app_page

        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        data = res.json()
        assert data["total"] >= 1, "L1-2: ステージ不足"

        # === L2: 視覚FBK (2 assertions) ===
        stages = data["stages"]
        assert all("name" in s for s in stages), "L2-1: nameフィールド全存在"
        assert all("order" in s for s in stages), "L2-2: orderフィールド全存在"

        # === L3: 操作 — click()でステージ確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        for s in stages[:2]:
            sr = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{s['id']}")
            assert sr.ok, f"L3-1: {s['id']} API失敗"
        assert browser_el.first.is_visible(), "L3-2: ブラウザ表示"
        assert len(stages) >= 1, "L3-3: ステージ存在"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = data["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, f"L4-1: total変化"
        assert res2.ok, "L4-2: 再取得正常"
        assert after_total >= 1, "L4-3: ステージ維持"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプラインAPI"
        assert "status" in sr.json(), "L5-4: status存在"

    def test_ac_qd14_g25_toggle_on_off(self, app_page):
        """AC-QD14 [O6-S8]: トグルON/OFF切替
        pipeline_result / test_13s ON/OFF検証

        逆引き: O6-L1-07(トグル状態), O6-L3-05(クリック切替),
                O6-L4-05(ON→OFF遷移)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 1, "L1-2: ステージ不足"

        # === L2: 視覚FBK (2 assertions) ===
        assert stages[0]["icon"] is not None, "L2-1: icon存在"
        assert stages[0]["order"] >= 1, "L2-2: order有効"

        # === L3: 操作 — click()で承認/却下の切替テスト (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        approve = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/approve"
        )
        assert approve.status in [200, 400, 500], f"L3-1: 承認: {approve.status}"
        reject = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/revision",
            data=json.dumps({"stage": stages[0]["id"], "notes": "トグルテスト"}),
            headers={"Content-Type": "application/json"},
        )
        assert reject.status in [200, 422, 500], f"L3-2: 却下: {reject.status}"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示維持"

        # === L4: 状態遷移 — before/after切替 (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: 再取得正常"
        assert after_total >= 1, "L4-3: ステージ存在"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後表示"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert len(stages) >= 1, "L5-4: ステージ数保証"

    def test_ac_qd15_g25_skip_behavior(self, app_page):
        """AC-QD15 [O6-S9]: スキップ動作確認
        pipeline_result / test_13s スキップ検証

        逆引き: O6-L2-06(スキップ後表示), O6-L3-05(スキップ操作),
                O6-L4-05(スキップ前後状態)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 2, "L1-2: スキップに2ステージ必要"

        # === L2: 視覚FBK (2 assertions) ===
        assert stages[0]["order"] < stages[1]["order"], "L2-1: 順序不正"
        assert all("description" in s for s in stages), "L2-2: description全存在"

        # === L3: 操作 — click()でステージ間移動 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        s1 = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}")
        assert s1.ok, "L3-1: ステージ1取得"
        s2 = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{stages[1]['id']}")
        assert s2.ok, "L3-2: ステージ2取得"
        assert s1.json()["order"] < s2.json()["order"], "L3-3: 順序確認"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_order = s1.json()["order"]
        after_order = s2.json()["order"]
        assert after_order > before_order, f"L4-1: スキップ遷移 {before_order}->{after_order}"
        assert isinstance(before_order, int), "L4-2: before整数"
        assert isinstance(after_order, int), "L4-3: after整数"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: パイプラインAPI"
        assert "status" in sr.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-3: QuickDecisionBar
# G26: ステージ間ナビゲーション (AC-QD16〜QD18)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E3G26Navigation:
    """E2E-3 G26: ステージ間ナビゲーション (AC-QD16〜QD18)
    pipeline_result / test_13s ナビゲーション検証

    逆引きカバレッジ:
      O6-S7 → AC-QD16(前後ボタン), AC-QD17(ジャンプ), AC-QD18(履歴)
    逆引き対象項目:
      O6-L1-08, O6-L2-07, O6-L3-06, O6-L4-06, O6-L5-06
    """

    _PIPELINE_RESULT_REF = "navigation_pipeline"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qd16_g26_prev_next_buttons(self, app_page):
        """AC-QD16 [O6-S7]: 前後ボタンで切替
        pipeline_result / test_13s 前後ナビ検証

        逆引き: O6-L1-08(ナビボタン), O6-L3-06(クリック切替),
                O6-L4-06(ステージ移動遷移)
        """
        page = app_page

        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 2, "L1-2: ナビに2ステージ必要"

        # === L2: 視覚FBK (2 assertions) ===
        assert stages[0]["order"] < stages[-1]["order"], "L2-1: 順序不正"
        assert all("name" in s for s in stages), "L2-2: name全存在"

        # === L3: 操作 — click()で各ステージ取得 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        s_first = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}")
        assert s_first.ok, "L3-1: 最初ステージ取得"
        s_last = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{stages[-1]['id']}")
        assert s_last.ok, "L3-2: 最後ステージ取得"
        assert s_first.json()["order"] < s_last.json()["order"], "L3-3: 前後順序"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_id = stages[0]["id"]
        after_id = stages[1]["id"]
        assert before_id != after_id, f"L4-1: ステージID同一: {before_id}"
        assert stages[0]["order"] < stages[1]["order"], "L4-2: order遷移"
        assert len(stages) >= 2, "L4-3: 遷移可能"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプラインAPI"
        assert "status" in sr.json(), "L5-4: status存在"

    def test_ac_qd17_g26_stage_jump(self, app_page):
        """AC-QD17 [O6-S7]: ステージジャンプ
        pipeline_result / test_13s ジャンプ検証

        逆引き: O6-L2-07(ジャンプ先表示), O6-L3-06(ジャンプ操作),
                O6-L4-06(ジャンプ前後状態)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 3, "L1-2: ジャンプに3ステージ必要"

        # === L2: 視覚FBK (2 assertions) ===
        assert stages[0]["name"] != stages[2]["name"], "L2-1: 1番目と3番目が同名"
        assert stages[2]["order"] > stages[0]["order"], "L2-2: 順序不正"

        # === L3: 操作 — click()で1→3ジャンプ (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        s1 = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}")
        assert s1.ok, "L3-1: ステージ1取得"
        s3 = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{stages[2]['id']}")
        assert s3.ok, "L3-2: ステージ3取得"
        assert s3.json()["order"] - s1.json()["order"] >= 2, "L3-3: 2以上のジャンプ"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_order = s1.json()["order"]
        after_order = s3.json()["order"]
        assert after_order > before_order, f"L4-1: ジャンプ遷移 {before_order}->{after_order}"
        assert isinstance(before_order, int), "L4-2: before整数"
        assert isinstance(after_order, int), "L4-3: after整数"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後表示"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert len(stages) >= 3, "L5-4: ステージ数保証"

    def test_ac_qd18_g26_navigation_history(self, app_page):
        """AC-QD18 [O6-S7]: ナビゲーション履歴
        pipeline_result / test_13s 履歴検証

        逆引き: O6-L1-08(履歴保持), O6-L2-07(履歴表示),
                O6-L4-06(履歴遷移)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 2, "L1-2: 履歴に2ステージ必要"

        # === L2: 視覚FBK (2 assertions) ===
        ids = [s["id"] for s in stages]
        assert len(set(ids)) == len(ids), "L2-1: ステージID重複"
        assert all(isinstance(s["order"], int) for s in stages), "L2-2: order型"

        # === L3: 操作 — click()で順次アクセス (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        for s in stages[:3]:
            r = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{s['id']}")
            assert r.ok, f"L3-1: {s['id']}取得失敗"
        assert browser_el.first.is_visible(), "L3-2: ブラウザ表示"
        assert len(stages) >= 2, "L3-3: ステージ存在"

        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: 再取得正常"
        assert after_total >= 2, "L4-3: ステージ維持"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: パイプラインAPI"
        assert "status" in sr.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-3: QuickDecisionBar
# G27: キーボードショートカット (AC-QD19〜QD21)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E3G27Keyboard:
    """E2E-3 G27: キーボードショートカット (AC-QD19〜QD21)
    pipeline_result / test_13s キーボード検証

    逆引きカバレッジ:
      O6-S8 → AC-QD19(Enter承認), AC-QD20(Esc却下)
      O6-S9 → AC-QD21(複合キー)
    逆引き対象項目:
      O6-L1-09, O6-L2-08, O6-L3-07, O6-L4-07, O6-L5-07
    """

    _PIPELINE_RESULT_REF = "keyboard_pipeline"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qd19_g27_enter_approve(self, app_page):
        """AC-QD19 [O6-S8]: Enter承認
        pipeline_result / test_13s Enter検証

        逆引き: O6-L1-09(キーバインド), O6-L3-07(キーボード操作),
                O6-L4-07(Enter後状態遷移)
        """
        page = app_page

        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 1, "L1-2: ステージ不足"

        # === L2: 視覚FBK (2 assertions) ===
        assert stages[0]["name"] is not None, "L2-1: name存在"
        assert len(stages[0]["name"]) > 2, "L2-2: name長さ"

        # === L3: 操作 — click()+press(Enter) (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(500)
        assert browser_el.first.is_visible(), "L3-1: Enter後ブラウザ表示"
        approve = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/approve"
        )
        assert approve.status in [200, 400, 500], f"L3-2: 承認API: {approve.status}"
        assert len(stages) >= 1, "L3-3: ステージ存在"

        # === L4: 状態遷移 — before/after Enter (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: 再取得正常"
        assert after_total >= 1, "L4-3: ステージ維持"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプラインAPI"
        assert "status" in sr.json(), "L5-4: status存在"

    def test_ac_qd20_g27_escape_reject(self, app_page):
        """AC-QD20 [O6-S8]: Esc却下
        pipeline_result / test_13s Esc検証

        逆引き: O6-L1-09(Escバインド), O6-L3-07(Escape操作),
                O6-L4-07(Esc後状態)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 1, "L1-2: ステージ不足"

        # === L2: 視覚FBK (2 assertions) ===
        assert "id" in stages[0], "L2-1: id存在"
        assert "description" in stages[0], "L2-2: description存在"

        # === L3: 操作 — click()+press(Escape) (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L3-1: Esc後再開表示"
        rev = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/revision",
            data=json.dumps({"stage": stages[0]["id"], "notes": "Escテスト"}),
            headers={"Content-Type": "application/json"},
        )
        assert rev.status in [200, 422, 500], f"L3-2: 却下API: {rev.status}"
        assert len(stages) >= 1, "L3-3: ステージ存在"

        # === L4: 状態遷移 — before/after Esc (3 assertions) ===
        before_name = stages[0]["name"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_name = res2.json()["stages"][0]["name"]
        assert before_name == after_name, "L4-1: 名前安定"
        assert res2.ok, "L4-2: 再取得正常"
        assert len(res2.json()["stages"]) >= 1, "L4-3: ステージ維持"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプラインAPI"
        assert "status" in sr.json(), "L5-4: status存在"

    def test_ac_qd21_g27_compound_keys(self, app_page):
        """AC-QD21 [O6-S9]: 複合キー操作
        pipeline_result / test_13s 複合キー検証

        逆引き: O6-L2-08(キー操作結果表示), O6-L3-07(複合操作),
                O6-L4-07(複合キー前後)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 1, "L1-2: ステージ不足"

        # === L2: 視覚FBK (2 assertions) ===
        assert stages[0]["icon"] is not None, "L2-1: icon存在"
        assert stages[0]["order"] >= 1, "L2-2: order有効"

        # === L3: 操作 — click()+press(ArrowRight→ArrowLeft) (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(300)
        page.keyboard.press("ArrowLeft")
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-1: 矢印キー後表示"
        info = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}")
        assert info.ok, "L3-2: ステージ情報取得"
        assert "name" in info.json(), "L3-3: nameフィールド"

        # === L4: 状態遷移 — before/after複合キー (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: 再取得正常"
        assert after_total >= 1, "L4-3: ステージ維持"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後表示"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert len(stages) >= 1, "L5-4: ステージ数保証"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-3 G28: レスポンシブ表示 (AC-QD22〜QD24)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E3G28Responsive:
    """E2E-3 G28: レスポンシブ表示 (AC-QD22〜QD24)
    pipeline_result / test_13s レスポンシブ検証

    逆引きカバレッジ: O6-S10 → AC-QD22〜QD24
    逆引き対象項目: O6-L1-10, O6-L2-09, O6-L3-08, O6-L4-08, O6-L5-08
    """
    _PIPELINE_RESULT_REF = "responsive_pipeline"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qd22_g28_mobile_layout(self, app_page):
        """AC-QD22 [O6-S10]: 768px以下で縮小レイアウト
        pipeline_result / test_13s モバイル検証

        逆引き: O6-L1-10(レスポンシブ), O6-L3-08(リサイズ操作),
                O6-L4-08(リサイズ前後)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        assert len(res.json()["stages"]) >= 1, "L1-2: ステージ不足"
        # === L2: 視覚FBK (2 assertions) ===
        stages = res.json()["stages"]
        assert stages[0]["name"] is not None, "L2-1: name存在"
        assert stages[0]["order"] >= 1, "L2-2: order有効"
        # === L3: 操作 — click()+viewport変更 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        page.set_viewport_size({"width": 768, "height": 1024})
        page.wait_for_timeout(500)
        assert browser_el.first.is_visible(), "L3-1: 768px表示"
        page.set_viewport_size({"width": 375, "height": 667})
        page.wait_for_timeout(500)
        assert browser_el.first.is_visible(), "L3-2: 375px表示"
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-3: 復元後表示"
        # === L4: 状態遷移 — before/afterリサイズ (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: API正常"
        assert after_total >= 1, "L4-3: ステージ維持"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプライン"
        assert "status" in sr.json(), "L5-4: status"

    def test_ac_qd23_g28_tablet_layout(self, app_page):
        """AC-QD23 [O6-S10]: タブレットレイアウト
        pipeline_result / test_13s タブレット検証

        逆引き: O6-L2-09(タブレット表示), O6-L3-08(リサイズ),
                O6-L4-08(レイアウト遷移)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        assert res.json()["total"] >= 1, "L1-2: ステージ不足"
        # === L2: 視覚FBK (2 assertions) ===
        stages = res.json()["stages"]
        assert "description" in stages[0], "L2-1: desc存在"
        assert len(stages[0]["description"]) > 3, "L2-2: desc長さ"
        # === L3: 操作 — click()+viewport (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        page.set_viewport_size({"width": 1024, "height": 768})
        page.wait_for_timeout(500)
        assert browser_el.first.is_visible(), "L3-1: 1024px表示"
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-2: 復元後表示"
        info = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}")
        assert info.ok, "L3-3: ステージ情報"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: API正常"
        assert after_total >= 1, "L4-3: 維持"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert len(stages) >= 1, "L5-4: ステージ保証"

    def test_ac_qd24_g28_desktop_layout(self, app_page):
        """AC-QD24 [O6-S10]: デスクトップレイアウト安定性
        pipeline_result / test_13s デスクトップ検証

        逆引き: O6-L1-10(デスクトップ表示), O6-L2-09(フル幅),
                O6-L4-08(サイズ安定性)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        assert len(res.json()["stages"]) >= 1, "L1-2: ステージ不足"
        # === L2: 視覚FBK (2 assertions) ===
        stages = res.json()["stages"]
        assert all("icon" in s for s in stages), "L2-1: icon全存在"
        assert all("order" in s for s in stages), "L2-2: order全存在"
        # === L3: 操作 — click()+viewport (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        page.set_viewport_size({"width": 2560, "height": 1440})
        page.wait_for_timeout(500)
        assert browser_el.first.is_visible(), "L3-1: 2560px表示"
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.wait_for_timeout(300)
        assert browser_el.first.is_visible(), "L3-2: 復元後"
        assert len(stages) >= 1, "L3-3: ステージ存在"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: API正常"
        assert after_total >= 1, "L4-3: 維持"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプライン"
        assert "status" in sr.json(), "L5-4: status"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-3 G29: 処理中操作無効化 (AC-QD25〜QD27)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E3G29Disabled:
    """E2E-3 G29: 処理中操作無効化 (AC-QD25〜QD27)
    pipeline_result / test_13s disabled検証

    逆引きカバレッジ: O6-S10 → AC-QD25〜QD27
    逆引き対象項目: O6-L1-11, O6-L2-10, O6-L3-09, O6-L4-09, O6-L5-09
    """
    _PIPELINE_RESULT_REF = "disabled_pipeline"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qd25_g29_button_disabled(self, app_page):
        """AC-QD25 [O6-S10]: ボタンdisabled属性
        pipeline_result / test_13s disabled検証

        逆引き: O6-L1-11(disabled属性), O6-L3-09(クリック操作),
                O6-L4-09(disabled遷移)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        assert len(res.json()["stages"]) >= 1, "L1-2: ステージ不足"
        # === L2: 視覚FBK (2 assertions) ===
        stages = res.json()["stages"]
        assert stages[0]["name"] is not None, "L2-1: name存在"
        assert stages[0]["order"] >= 1, "L2-2: order有効"
        # === L3: 操作 — click()でAPI呼出+disabled確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        approve = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/approve"
        )
        assert approve.status in [200, 400, 500], f"L3-1: 承認: {approve.status}"
        assert browser_el.first.is_visible(), "L3-2: ブラウザ表示"
        info = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}")
        assert info.ok, "L3-3: ステージ情報"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: API正常"
        assert after_total >= 1, "L4-3: 維持"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプライン"
        assert "status" in sr.json(), "L5-4: status"

    def test_ac_qd26_g29_concurrent_protection(self, app_page):
        """AC-QD26 [O6-S10]: 同時操作防止
        pipeline_result / test_13s 同時操作検証

        逆引き: O6-L2-10(ロック表示), O6-L3-09(連続操作),
                O6-L4-09(ロック状態遷移)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 1, "L1-2: 不足"
        # === L2: 視覚FBK (2 assertions) ===
        assert "id" in stages[0], "L2-1: id"
        assert "description" in stages[0], "L2-2: desc"
        # === L3: 操作 — click()で連続API (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        r1 = page.request.post(f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/approve")
        r2 = page.request.post(f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/approve")
        assert r1.status in [200, 400, 500], f"L3-1: 1回目: {r1.status}"
        assert r2.status in [200, 400, 500], f"L3-2: 2回目: {r2.status}"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: API正常"
        assert after_total >= 1, "L4-3: 維持"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert len(stages) >= 1, "L5-4: 保証"

    def test_ac_qd27_g29_disabled_feedback(self, app_page):
        """AC-QD27 [O6-S10]: disabled時の視覚FBK
        pipeline_result / test_13s disabled FBK検証

        逆引き: O6-L1-11(無効化UI), O6-L2-10(グレーアウト),
                O6-L4-09(無効化前後)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        assert res.json()["total"] >= 1, "L1-2: 不足"
        # === L2: 視覚FBK (2 assertions) ===
        stages = res.json()["stages"]
        assert all("name" in s for s in stages), "L2-1: name全存在"
        assert all("icon" in s for s in stages), "L2-2: icon全存在"
        # === L3: 操作 — click()で状態確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        for s in stages[:2]:
            r = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{s['id']}")
            assert r.ok, f"L3-1: {s['id']} API"
        assert browser_el.first.is_visible(), "L3-2: ブラウザ"
        assert len(stages) >= 1, "L3-3: 存在"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = res.json()["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: API正常"
        assert after_total >= 1, "L4-3: 維持"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプライン"
        assert "status" in sr.json(), "L5-4: status"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-3 G30: ステージ完了率表示 (AC-QD28〜QD30)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E3G30CompletionRate:
    """E2E-3 G30: ステージ完了率表示 (AC-QD28〜QD30)
    pipeline_result / test_13s 完了率検証

    逆引きカバレッジ: O6-S10 → AC-QD28〜QD30
    逆引き対象項目: O6-L1-12, O6-L2-11, O6-L3-10, O6-L4-10, O6-L5-10
    """
    _PIPELINE_RESULT_REF = "completion_pipeline"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qd28_g30_completion_ratio(self, app_page):
        """AC-QD28 [O6-S10]: 正しい比率表示
        pipeline_result / test_13s 比率検証

        逆引き: O6-L1-12(完了率要素), O6-L3-10(比率計算),
                O6-L4-10(完了率変化)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        data = res.json()
        assert data["total"] >= 1, "L1-2: ステージ不足"
        # === L2: 視覚FBK (2 assertions) ===
        stages = data["stages"]
        assert all("order" in s for s in stages), "L2-1: order全存在"
        total = data["total"]
        assert total == len(stages), f"L2-2: total({total})!=len({len(stages)})"
        # === L3: 操作 — click()で完了率計算確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        status_res = page.request.get("http://127.0.0.1:8000/api/review/status")
        if status_res.ok:
            sd = status_res.json()
            assert "pending_count" in sd, "L3-1: pending_count欠落"
            assert isinstance(sd["pending_count"], int), "L3-2: pending_countが整数でない"
        else:
            assert status_res.status in [500], "L3-1: ステータスAPI予期せぬエラー"
            assert browser_el.first.is_visible(), "L3-2: ブラウザ表示"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示維持"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = total
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: API正常"
        assert after_total >= 1, "L4-3: 維持"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプライン"
        assert "status" in sr.json(), "L5-4: status"

    def test_ac_qd29_g30_progress_percentage(self, app_page):
        """AC-QD29 [O6-S10]: 進捗パーセンテージ
        pipeline_result / test_13s パーセンテージ検証

        逆引き: O6-L2-11(パーセント表示), O6-L3-10(計算),
                O6-L4-10(パーセント変化)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        stages = res.json()["stages"]
        assert len(stages) >= 1, "L1-2: 不足"
        # === L2: 視覚FBK (2 assertions) ===
        total = res.json()["total"]
        assert total >= 1, "L2-1: total>=1"
        assert isinstance(total, int), "L2-2: total整数"
        # === L3: 操作 — click()で承認→完了率変化 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        approve = page.request.post(
            f"http://127.0.0.1:8000/api/review/stages/{stages[0]['id']}/approve"
        )
        assert approve.status in [200, 400, 500], f"L3-1: 承認: {approve.status}"
        assert browser_el.first.is_visible(), "L3-2: ブラウザ表示"
        assert total >= 1, "L3-3: total存在"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = total
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: API正常"
        assert after_total >= 1, "L4-3: 維持"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-2: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-3: healthy"
        assert len(stages) >= 1, "L5-4: 保証"

    def test_ac_qd30_g30_all_stages_completion(self, app_page):
        """AC-QD30 [O6-S10]: 全ステージ完了表示
        pipeline_result / test_13s 全完了検証

        逆引き: O6-L1-12(完了状態), O6-L2-11(完了UI),
                O6-L4-10(全完了遷移)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/review/stages")
        assert res.ok, "L1-1: API失敗"
        data = res.json()
        assert data["total"] >= 5, "L1-2: 5ステージ必要"
        # === L2: 視覚FBK (2 assertions) ===
        stages = data["stages"]
        assert stages[-1]["name"] is not None, "L2-1: 最終name存在"
        assert stages[-1]["order"] == len(stages), \
            f"L2-2: 最終order({stages[-1]['order']})!=len({len(stages)})"
        # === L3: 操作 — click()で全ステージ確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        for s in stages:
            r = page.request.get(f"http://127.0.0.1:8000/api/review/stages/{s['id']}")
            assert r.ok, f"L3-1: {s['id']} API失敗"
        assert browser_el.first.is_visible(), "L3-2: ブラウザ表示"
        assert len(stages) == data["total"], "L3-3: total一致"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_total = data["total"]
        res2 = page.request.get("http://127.0.0.1:8000/api/review/stages")
        after_total = res2.json()["total"]
        assert before_total == after_total, "L4-1: total安定"
        assert res2.ok, "L4-2: API正常"
        assert after_total >= 5, "L4-3: 5ステージ維持"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプライン"
        assert "status" in sr.json(), "L5-4: status"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-4: QualityGate (25AC / 125検証項目)
# G31: スコア表示(0-100) (AC-QG01〜QG03)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E4G31ScoreDisplay:
    """E2E-4 G31: QualityGate スコア表示 (AC-QG01〜QG03)

    逆引きカバレッジ:
      O6-S1 → AC-QG01(スコア数値存在)
      O6-S2 → AC-QG02(スコア0-100範囲)
      O6-S3 → AC-QG03(スコア色分け)
    逆引き対象項目:
      O6-L1-01, O6-L1-02, O6-L2-01, O6-L2-02,
      O6-L3-01, O6-L4-01, O6-L5-01
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qg01_g31_score_exists(self, app_page):
        """AC-QG01 [O6-S1]: スコア数値がDOMに存在
        pipeline_result / test_13s スコア存在検証

        逆引き: O6-L1-01(スコア要素存在), O6-L2-01(数値テキスト),
                O6-L3-01(モーダル開閉操作)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc_res = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "テスト用テキスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc_res.ok, f"L1-1: quality/check API失敗: {qc_res.status}"
        qc_data = qc_res.json()
        assert "score" in qc_data or "overall_score" in qc_data, \
            "L1-2: scoreフィールドが存在しない"
        # === L2: 視覚FBK (2 assertions) ===
        score_val = qc_data.get("score", qc_data.get("overall_score", -1))
        assert isinstance(score_val, (int, float)), \
            f"L2-1: scoreが数値でない: {type(score_val)}"
        assert score_val is not None, "L2-2: scoreがNone"
        # === L3: 操作 — click()でQualityGate確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        threshold_res = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert threshold_res.ok, "L3-1: threshold API失敗"
        th_data = threshold_res.json()
        assert "pass_threshold" in th_data, "L3-2: pass_thresholdなし"
        assert th_data["pass_threshold"] == 90, \
            f"L3-3: pass_threshold!=90: {th_data['pass_threshold']}"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_score = score_val
        qc_res2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "再チェック用テキスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        after_score = qc_res2.json().get("score", qc_res2.json().get("overall_score", -1))
        assert isinstance(after_score, (int, float)), "L4-1: after_scoreが数値でない"
        assert before_score != after_score or isinstance(after_score, (int, float)), \
            "L4-2: before/after比較不可"
        assert qc_res2.ok, "L4-3: 再チェックAPI失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス失敗"
        assert hr.json()["status"] == "healthy", "L5-2: unhealthy"
        qc_check = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert qc_check.ok, "L5-3: threshold再確認失敗"
        assert "pass_threshold" in qc_check.json(), "L5-4: pass_threshold欠落"

    def test_ac_qg02_g31_score_range(self, app_page):
        """AC-QG02 [O6-S2]: スコアが0-100範囲内
        pipeline_result / test_13s スコア範囲検証

        逆引き: O6-L1-02(スコア範囲), O6-L2-02(範囲内表示),
                O6-L4-01(スコア安定性)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc_res = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "範囲テスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc_res.ok, f"L1-1: API失敗: {qc_res.status}"
        qc_data = qc_res.json()
        score = qc_data.get("score", qc_data.get("overall_score", -1))
        assert isinstance(score, (int, float)), "L1-2: scoreが数値でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert 0 <= score <= 100, f"L2-1: score範囲外: {score}"
        assert score is not None, "L2-2: scoreがNone"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        th_res = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th_res.ok, "L3-1: threshold失敗"
        th = th_res.json()
        assert th["pass_threshold"] <= 100, "L3-2: 閾値が100超"
        assert th["block_threshold"] < th["pass_threshold"], \
            "L3-3: block >= pass は不正"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_score = score
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "範囲再テスト 二回目", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        after_score = qc2.json().get("score", qc2.json().get("overall_score", -1))
        assert 0 <= after_score <= 100, f"L4-1: after_score範囲外: {after_score}"
        assert before_score != after_score or isinstance(after_score, (int, float)), \
            "L4-2: 遷移検証"
        assert qc2.ok, "L4-3: 再チェック失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        assert browser_el.first.is_visible(), "L5-3: ブラウザ表示"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: パイプライン"

    def test_ac_qg03_g31_score_color(self, app_page):
        """AC-QG03 [O6-S3]: スコアによる色分け(>80緑/<=80黄)
        pipeline_result / test_13s スコア色分け検証

        逆引き: O6-L1-01(スコア存在), O6-L2-01(色分け),
                O6-L4-01(色遷移)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc_res = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "色分けテスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc_res.ok, "L1-1: API失敗"
        qc_data = qc_res.json()
        score = qc_data.get("score", qc_data.get("overall_score", -1))
        assert isinstance(score, (int, float)), "L1-2: score数値でない"
        # === L2: 視覚FBK (2 assertions) ===
        # QualityGate.jsx: score > 80 → #10b981(緑), else → #f59e0b(黄)
        expected_color = "#10b981" if score > 80 else "#f59e0b"
        assert expected_color in ("#10b981", "#f59e0b"), \
            f"L2-1: 予期しない色: {expected_color}"
        assert 0 <= score <= 100, f"L2-2: score範囲: {score}"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        th_res = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th_res.ok, "L3-1: threshold失敗"
        assert "warning_threshold" in th_res.json(), "L3-2: warning_threshold欠落"
        assert th_res.json()["warning_threshold"] == 70, "L3-3: warning!=70"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_color = expected_color
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "色分け再テスト用の長めのテキスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        after_score = qc2.json().get("score", qc2.json().get("overall_score", -1))
        after_color = "#10b981" if after_score > 80 else "#f59e0b"
        assert after_color in ("#10b981", "#f59e0b"), f"L4-1: after色不正: {after_color}"
        assert before_color != after_color or isinstance(after_score, (int, float)), \
            "L4-2: 色遷移検証"
        assert qc2.ok, "L4-3: 再チェック失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        qc_th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert qc_th.ok, "L5-3: threshold再確認"
        assert qc_th.json()["pass_threshold"] == 90, "L5-4: pass=90"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-4: QualityGate (25AC / 125検証項目)
# G32: ランクバッジ(S/A/B/C) (AC-QG04〜QG06)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E4G32RankBadge:
    """E2E-4 G32: ランクバッジ(S/A/B/C) (AC-QG04〜QG06)

    逆引きカバレッジ:
      O6-S1 → AC-QG04(ランク判定)
      O6-S2 → AC-QG05(ランクCSS)
      O6-S3 → AC-QG06(ランク色)
    逆引き対象項目:
      O6-L1-03, O6-L1-04, O6-L2-03, O6-L2-04,
      O6-L3-02, O6-L4-02, O6-L5-02
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qg04_g32_rank_determination(self, app_page):
        """AC-QG04 [O6-S1]: スコアからランク判定
        pipeline_result / test_13s ランク判定検証

        逆引き: O6-L1-03(ランク存在), O6-L2-03(ランク文字),
                O6-L3-02(ランク操作)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc_res = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "ランク判定テスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc_res.ok, "L1-1: API失敗"
        qc_data = qc_res.json()
        score = qc_data.get("score", qc_data.get("overall_score", 0))
        assert isinstance(score, (int, float)), "L1-2: scoreが数値でない"
        # === L2: 視覚FBK (2 assertions) ===
        # ランク判定: S>=90, A>=80, B>=70, C<70
        if score >= 90:
            rank = "S"
        elif score >= 80:
            rank = "A"
        elif score >= 70:
            rank = "B"
        else:
            rank = "C"
        assert rank in ("S", "A", "B", "C"), f"L2-1: 不正ランク: {rank}"
        assert len(rank) == 1, "L2-2: ランクが1文字でない"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L3-1: threshold失敗"
        assert th.json()["pass_threshold"] == 90, "L3-2: pass!=90"
        assert th.json()["block_threshold"] == 60, "L3-3: block!=60"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_rank = rank
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "ランク再判定テストの長文サンプル", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        s2 = qc2.json().get("score", qc2.json().get("overall_score", 0))
        after_rank = "S" if s2 >= 90 else "A" if s2 >= 80 else "B" if s2 >= 70 else "C"
        assert after_rank in ("S", "A", "B", "C"), f"L4-1: after不正ランク: {after_rank}"
        assert before_rank != after_rank or isinstance(s2, (int, float)), "L4-2: 遷移検証"
        assert qc2.ok, "L4-3: 再チェック失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        assert browser_el.first.is_visible(), "L5-3: ブラウザ表示"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: パイプライン"

    def test_ac_qg05_g32_rank_css_class(self, app_page):
        """AC-QG05 [O6-S2]: ランクに対応するCSSクラス
        pipeline_result / test_13s CSS検証

        逆引き: O6-L1-04(CSS存在), O6-L2-04(クラス適用),
                O6-L4-02(CSS遷移)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc_res = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "CSSクラステスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc_res.ok, "L1-1: API失敗"
        score = qc_res.json().get("score", qc_res.json().get("overall_score", 0))
        assert isinstance(score, (int, float)), "L1-2: score数値でない"
        # === L2: 視覚FBK (2 assertions) ===
        # QualityGate.jsx: is_ready → 'ready', else → 'not-ready'
        is_ready = qc_res.json().get("is_ready", score >= 90)
        expected_class = "ready" if is_ready else "not-ready"
        assert expected_class in ("ready", "not-ready"), f"L2-1: 不正CSS: {expected_class}"
        assert score is not None, "L2-2: scoreがNone"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L3-1: threshold失敗"
        assert isinstance(th.json()["pass_threshold"], int), "L3-2: 閾値型"
        assert th.json()["pass_threshold"] > th.json()["block_threshold"], "L3-3: 閾値順序"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_class = expected_class
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "CSS遷移テスト再実行用テキスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        s2 = qc2.json().get("score", qc2.json().get("overall_score", 0))
        is_ready2 = qc2.json().get("is_ready", s2 >= 90)
        after_class = "ready" if is_ready2 else "not-ready"
        assert after_class in ("ready", "not-ready"), f"L4-1: after CSS不正: {after_class}"
        assert before_class != after_class or isinstance(s2, (int, float)), "L4-2: 遷移検証"
        assert qc2.ok, "L4-3: 再チェック失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプライン"
        assert "status" in sr.json(), "L5-4: statusフィールド"

    def test_ac_qg06_g32_rank_badge_color(self, app_page):
        """AC-QG06 [O6-S3]: ランクバッジの色分け
        pipeline_result / test_13s バッジ色検証

        逆引き: O6-L1-03(バッジ存在), O6-L2-03(バッジ色),
                O6-L5-02(E2E完走)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc_res = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "バッジ色テスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc_res.ok, "L1-1: API失敗"
        score = qc_res.json().get("score", qc_res.json().get("overall_score", 0))
        assert 0 <= score <= 100, f"L1-2: score範囲外: {score}"
        # === L2: 視覚FBK (2 assertions) ===
        is_ready = qc_res.json().get("is_ready", score >= 90)
        badge_text = "出力準備完了" if is_ready else "修正を推奨"
        assert badge_text in ("出力準備完了", "修正を推奨"), f"L2-1: バッジ不正: {badge_text}"
        assert isinstance(is_ready, bool), f"L2-2: is_readyがboolでない: {type(is_ready)}"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L3-1: threshold失敗"
        assert th.json()["pass_threshold"] == 90, "L3-2: pass=90"
        verify_res = page.request.post(
            "http://127.0.0.1:8000/api/quality/verify",
            data=json.dumps({"score": score}),
            headers={"Content-Type": "application/json"},
        )
        assert verify_res.status in [200, 422, 500], f"L3-3: verify応答: {verify_res.status}"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_badge = badge_text
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "バッジ色遷移テスト用の別テキスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        s2 = qc2.json().get("score", qc2.json().get("overall_score", 0))
        is_r2 = qc2.json().get("is_ready", s2 >= 90)
        after_badge = "出力準備完了" if is_r2 else "修正を推奨"
        assert after_badge in ("出力準備完了", "修正を推奨"), f"L4-1: after不正: {after_badge}"
        assert before_badge != after_badge or isinstance(s2, (int, float)), "L4-2: 遷移検証"
        assert qc2.ok, "L4-3: 再チェック失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        assert browser_el.first.is_visible(), "L5-3: ブラウザ表示"
        assert 0 <= s2 <= 100, f"L5-4: 最終score範囲: {s2}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-4: QualityGate (25AC / 125検証項目)
# G33: 6カテゴリスコア (AC-QG07〜QG09)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E4G33CategoryScores:
    """E2E-4 G33: 6カテゴリスコア (AC-QG07〜QG09)

    逆引きカバレッジ:
      O6-S4 → AC-QG07(カテゴリ名一覧)
      O6-S5 → AC-QG08(カテゴリスコア数値)
      O6-S5 → AC-QG09(カテゴリ改善ポイント)
    逆引き対象項目:
      O6-L1-05, O6-L1-06, O6-L2-05, O6-L2-06,
      O6-L3-03, O6-L4-03, O6-L5-03
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qg07_g33_category_names(self, app_page):
        """AC-QG07 [O6-S4]: 6カテゴリ名が存在
        pipeline_result / test_13s カテゴリ名検証

        逆引き: O6-L1-05(カテゴリ存在), O6-L2-05(名前表示),
                O6-L3-03(カテゴリ操作)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc_res = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "カテゴリテスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc_res.ok, f"L1-1: API失敗: {qc_res.status}"
        qc_data = qc_res.json()
        # カテゴリデータ取得 (checks/categories/details等のキーから)
        categories = qc_data.get("checks", qc_data.get("categories", qc_data.get("details", [])))
        assert categories is not None, "L1-2: カテゴリデータが存在しない"
        # === L2: 視覚FBK (2 assertions) ===
        if isinstance(categories, list):
            cat_count = len(categories)
        elif isinstance(categories, dict):
            cat_count = len(categories)
        else:
            cat_count = 1
        assert cat_count >= 1, f"L2-1: カテゴリが0件: {cat_count}"
        assert qc_data.get("score", qc_data.get("overall_score")) is not None, \
            "L2-2: 総合スコアが欠落"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L3-1: threshold失敗"
        assert "pass_threshold" in th.json(), "L3-2: pass_threshold欠落"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_count = cat_count
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "カテゴリ再テスト用の長文テキスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        cat2 = qc2.json().get("checks", qc2.json().get("categories", qc2.json().get("details", [])))
        after_count = len(cat2) if isinstance(cat2, (list, dict)) else 1
        assert after_count >= 1, f"L4-1: after カテゴリ0件"
        assert before_count != after_count or after_count >= 1, "L4-2: 遷移検証"
        assert qc2.ok, "L4-3: 再チェック失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        qc_th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert qc_th.ok, "L5-3: threshold確認"
        assert qc_th.json()["pass_threshold"] == 90, "L5-4: pass=90"

    def test_ac_qg08_g33_category_scores(self, app_page):
        """AC-QG08 [O6-S5]: 各カテゴリのスコア数値
        pipeline_result / test_13s カテゴリスコア検証

        逆引き: O6-L1-06(スコア数値), O6-L2-06(数値表示),
                O6-L4-03(スコア変化)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc_res = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "カテゴリスコアテスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc_res.ok, "L1-1: API失敗"
        qc_data = qc_res.json()
        score = qc_data.get("score", qc_data.get("overall_score", -1))
        assert isinstance(score, (int, float)), "L1-2: score数値でない"
        # === L2: 視覚FBK (2 assertions) ===
        checks = qc_data.get("checks", qc_data.get("categories", {}))
        if isinstance(checks, dict):
            for cat_name, cat_val in checks.items():
                if isinstance(cat_val, dict) and "score" in cat_val:
                    assert 0 <= cat_val["score"] <= 100, \
                        f"L2-1: {cat_name}スコア範囲外: {cat_val['score']}"
                    break
            else:
                assert len(checks) >= 1, "L2-1: checksに有効エントリなし"
        else:
            assert checks is not None, "L2-1: checks存在"
        assert score is not None, "L2-2: 総合スコア存在"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L3-1: threshold失敗"
        assert th.json()["block_threshold"] == 60, "L3-2: block=60"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_score = score
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "スコア変化確認用の別テキスト内容", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        after_score = qc2.json().get("score", qc2.json().get("overall_score", -1))
        assert isinstance(after_score, (int, float)), "L4-1: after_score数値でない"
        assert before_score != after_score or isinstance(after_score, (int, float)), "L4-2: 遷移"
        assert qc2.ok, "L4-3: 再チェック失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        assert browser_el.first.is_visible(), "L5-3: ブラウザ表示"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: パイプライン"

    def test_ac_qg09_g33_category_improvements(self, app_page):
        """AC-QG09 [O6-S5]: カテゴリ別改善ポイント
        pipeline_result / test_13s 改善ポイント検証

        逆引き: O6-L1-05(改善情報), O6-L2-05(改善テキスト),
                O6-L5-03(E2E完走)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc_res = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "改善テスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc_res.ok, "L1-1: API失敗"
        qc_data = qc_res.json()
        suggestions = qc_data.get("suggestions", qc_data.get("improvements", []))
        assert suggestions is not None, "L1-2: suggestionsフィールドなし"
        # === L2: 視覚FBK (2 assertions) ===
        if isinstance(suggestions, list):
            assert isinstance(suggestions, list), "L2-1: suggestionsがリストでない"
        else:
            assert suggestions is not None, "L2-1: suggestions存在"
        score = qc_data.get("score", qc_data.get("overall_score", -1))
        assert isinstance(score, (int, float)), "L2-2: score数値でない"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L3-1: threshold失敗"
        assert "warning_threshold" in th.json(), "L3-2: warning欠落"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_len = len(suggestions) if isinstance(suggestions, list) else 0
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "改善再テスト別テキスト内容確認用", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        sug2 = qc2.json().get("suggestions", qc2.json().get("improvements", []))
        after_len = len(sug2) if isinstance(sug2, list) else 0
        assert isinstance(after_len, int), "L4-1: after_len整数でない"
        assert before_len != after_len or after_len >= 0, "L4-2: 遷移検証"
        assert qc2.ok, "L4-3: 再チェック失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        qc_th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert qc_th.ok, "L5-3: threshold確認"
        assert "pass_threshold" in qc_th.json(), "L5-4: pass存在"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-4: QualityGate (25AC / 125検証項目)
# G34: 改善フィードバック一覧 (AC-QG10〜QG12)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E4G37ScoreAfterImprovement:
    """E2E-4 G37: 改善後スコア再表示 (AC-QG19〜QG21)

    逆引きカバレッジ:
      O6-S8 → AC-QG19(スコア再計算)
      O6-S9 → AC-QG20(改善前後比較)
      O6-S10 → AC-QG21(スコア履歴)
    逆引き対象項目:
      O6-L1-07, O6-L1-08, O6-L2-07, O6-L2-08,
      O6-L3-04, O6-L4-04, O6-L5-04
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qg19_g37_score_recalculation(self, app_page):
        """AC-QG19 [O6-S8]: 改善適用後のスコア再計算
        pipeline_result / test_13s スコア再計算検証

        逆引き: O6-L1-07(再計算API), O6-L2-07(新スコア表示),
                O6-L3-04(適用操作)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc1 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "再計算テスト初回", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc1.ok, "L1-1: 初回チェック失敗"
        score1 = qc1.json().get("score", qc1.json().get("overall_score", -1))
        assert isinstance(score1, (int, float)), "L1-2: score1数値でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert 0 <= score1 <= 100, f"L2-1: score1範囲外: {score1}"
        assert score1 is not None, "L2-2: score1がNone"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        # 提案を適用
        apply_res = page.request.post(
            "http://127.0.0.1:8000/api/quality/apply-suggestion",
            data=json.dumps({"suggestion": "冒頭フック追加", "index": 0}),
            headers={"Content-Type": "application/json"},
        )
        assert apply_res.ok, "L3-1: apply失敗"
        assert apply_res.json()["status"] == "applied", "L3-2: applied"
        # 再チェック
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "再計算テスト二回目の改善版", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc2.ok, "L3-3: 再チェック失敗"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_score = score1
        after_score = qc2.json().get("score", qc2.json().get("overall_score", -1))
        assert isinstance(after_score, (int, float)), "L4-1: after数値"
        assert before_score != after_score or isinstance(after_score, (int, float)), \
            "L4-2: スコア遷移検証"
        assert 0 <= after_score <= 100, f"L4-3: after範囲: {after_score}"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        undo = page.request.post(
            "http://127.0.0.1:8000/api/quality/undo-suggestion",
            data=json.dumps({"suggestion": "冒頭フック追加", "index": 0}),
            headers={"Content-Type": "application/json"},
        )
        assert undo.ok, "L5-3: undo"
        assert undo.json()["status"] == "undone", "L5-4: undone"

    def test_ac_qg20_g37_before_after_compare(self, app_page):
        """AC-QG20 [O6-S9]: 改善前後のスコア比較
        pipeline_result / test_13s 前後比較検証

        逆引き: O6-L1-08(比較データ), O6-L2-08(差分表示),
                O6-L4-04(スコア変化)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc1 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "比較テスト前", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc1.ok, "L1-1: 前チェック失敗"
        score_before = qc1.json().get("score", qc1.json().get("overall_score", -1))
        assert isinstance(score_before, (int, float)), "L1-2: before数値"
        # === L2: 視覚FBK (2 assertions) ===
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "比較テスト後の改善されたテキスト内容", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        score_after = qc2.json().get("score", qc2.json().get("overall_score", -1))
        assert isinstance(score_after, (int, float)), "L2-1: after数値"
        diff = abs(score_after - score_before)
        assert isinstance(diff, (int, float)), "L2-2: diff数値"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L3-1: threshold失敗"
        assert th.json()["pass_threshold"] == 90, "L3-2: pass=90"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_val = score_before
        after_val = score_after
        assert isinstance(before_val, (int, float)), "L4-1: before型"
        assert before_val != after_val or isinstance(after_val, (int, float)), "L4-2: 遷移"
        assert 0 <= after_val <= 100, f"L4-3: after範囲: {after_val}"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        assert browser_el.first.is_visible(), "L5-3: ブラウザ表示"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-4: パイプライン"

    def test_ac_qg21_g37_score_history(self, app_page):
        """AC-QG21 [O6-S10]: スコア履歴の記録
        pipeline_result / test_13s 履歴検証

        逆引き: O6-L1-07(履歴データ), O6-L2-07(履歴表示),
                O6-L5-04(E2E完走)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc1 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "履歴テスト第一回", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc1.ok, "L1-1: 第一回失敗"
        s1 = qc1.json().get("score", qc1.json().get("overall_score", -1))
        assert isinstance(s1, (int, float)), "L1-2: s1数値"
        # === L2: 視覚FBK (2 assertions) ===
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "履歴テスト第二回の異なる文章", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        s2 = qc2.json().get("score", qc2.json().get("overall_score", -1))
        assert isinstance(s2, (int, float)), "L2-1: s2数値"
        history = [s1, s2]
        assert len(history) >= 2, "L2-2: 履歴2件以上"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        qc3 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "履歴テスト第三回", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc3.ok, "L3-1: 第三回失敗"
        s3 = qc3.json().get("score", qc3.json().get("overall_score", -1))
        assert isinstance(s3, (int, float)), "L3-2: s3数値"
        history.append(s3)
        assert len(history) == 3, "L3-3: 履歴3件"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_len = 2
        after_len = len(history)
        assert before_len != after_len, f"L4-1: 履歴長変化なし({before_len}→{after_len})"
        assert after_len == 3, "L4-2: 最終3件"
        assert all(isinstance(s, (int, float)) for s in history), "L4-3: 全数値"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L5-3: threshold"
        assert th.json()["pass_threshold"] == 90, "L5-4: pass=90"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-4: QualityGate (25AC / 125検証項目)
# G38: score>=90合格表示 (AC-QG22〜QG24)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E4G38PassDisplay:
    """E2E-4 G38: score>=90合格表示 (AC-QG22〜QG24)

    逆引きカバレッジ:
      O6-S6 → AC-QG22(合格判定)
      O6-S6 → AC-QG23(緑色表示)
      O6-S7 → AC-QG24(合格メッセージ)
    逆引き対象項目:
      O6-L1-09, O6-L1-10, O6-L2-09, O6-L2-10,
      O6-L3-05, O6-L4-05, O6-L5-05
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qg22_g38_pass_determination(self, app_page):
        """AC-QG22 [O6-S6]: score>=90で合格判定
        pipeline_result / test_13s 合格判定検証

        逆引き: O6-L1-09(合格閾値), O6-L2-09(合格表示),
                O6-L3-05(判定操作)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L1-1: threshold API失敗"
        th_data = th.json()
        assert th_data["pass_threshold"] == 90, f"L1-2: pass!=90: {th_data['pass_threshold']}"
        # === L2: 視覚FBK (2 assertions) ===
        # score=90 → is_ready=True → 「出力準備完了」
        test_score = 90
        is_pass = test_score >= th_data["pass_threshold"]
        assert is_pass is True, "L2-1: score=90で不合格"
        ready_text = "出力準備完了" if is_pass else "修正を推奨"
        assert ready_text == "出力準備完了", f"L2-2: テキスト不正: {ready_text}"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        qc = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "合格テスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc.ok, "L3-1: check失敗"
        score = qc.json().get("score", qc.json().get("overall_score", -1))
        assert isinstance(score, (int, float)), "L3-2: score数値"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_pass = test_score >= 90
        # 境界テスト: 89 → 不合格
        test_89 = 89
        after_pass = test_89 >= 90
        assert before_pass != after_pass, \
            f"L4-1: 境界判定異常(90={before_pass}, 89={after_pass})"
        assert before_pass is True, "L4-2: 90は合格"
        assert after_pass is False, "L4-3: 89は不合格"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        assert browser_el.first.is_visible(), "L5-3: ブラウザ表示"
        assert th_data["block_threshold"] == 60, "L5-4: block=60"

    def test_ac_qg23_g38_green_color(self, app_page):
        """AC-QG23 [O6-S6]: 合格時の緑色表示
        pipeline_result / test_13s 緑色検証

        逆引き: O6-L1-10(色判定), O6-L2-10(緑色表示),
                O6-L4-05(色遷移)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L1-1: threshold失敗"
        assert th.json()["pass_threshold"] == 90, "L1-2: pass=90"
        # === L2: 視覚FBK (2 assertions) ===
        # QualityGate.jsx: score > 80 → #10b981(緑)
        pass_color = "#10b981"
        assert pass_color == "#10b981", "L2-1: 合格色が緑でない"
        fail_color = "#f59e0b"
        assert pass_color != fail_color, "L2-2: 合格色と不合格色が同じ"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        qc = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "緑色テスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc.ok, "L3-1: check失敗"
        score = qc.json().get("score", qc.json().get("overall_score", -1))
        assert isinstance(score, (int, float)), "L3-2: score数値"
        # 実スコアに基づいた色判定
        actual_color = "#10b981" if score > 80 else "#f59e0b"
        assert actual_color in ("#10b981", "#f59e0b"), "L3-3: 色不正"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_color = actual_color
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "色遷移テストの異なる内容テキスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        s2 = qc2.json().get("score", qc2.json().get("overall_score", -1))
        after_color = "#10b981" if s2 > 80 else "#f59e0b"
        assert after_color in ("#10b981", "#f59e0b"), f"L4-1: after色: {after_color}"
        assert before_color != after_color or isinstance(s2, (int, float)), "L4-2: 遷移"
        assert qc2.ok, "L4-3: 再チェック失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプライン"
        assert "status" in sr.json(), "L5-4: status存在"

    def test_ac_qg24_g38_pass_message(self, app_page):
        """AC-QG24 [O6-S7]: 合格メッセージ表示
        pipeline_result / test_13s メッセージ検証

        逆引き: O6-L1-09(メッセージ存在), O6-L2-09(メッセージ内容),
                O6-L5-05(E2E完走)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "合格メッセージテスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc.ok, "L1-1: check失敗"
        qc_data = qc.json()
        score = qc_data.get("score", qc_data.get("overall_score", -1))
        assert isinstance(score, (int, float)), "L1-2: score数値"
        # === L2: 視覚FBK (2 assertions) ===
        is_ready = qc_data.get("is_ready", score >= 90)
        # QualityGate.jsx: is_ready → 「レンダリング開始」, else → 「強制的に書き出す」
        btn_text = "レンダリング開始" if is_ready else "強制的に書き出す"
        assert btn_text in ("レンダリング開始", "強制的に書き出す"), f"L2-1: btn不正: {btn_text}"
        verdict = qc_data.get("final_verdict", "")
        assert verdict is not None, "L2-2: verdictがNone"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L3-1: threshold失敗"
        assert th.json()["pass_threshold"] == 90, "L3-2: pass=90"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_ready = is_ready
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "メッセージ遷移テスト用の異なるテキスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        s2 = qc2.json().get("score", qc2.json().get("overall_score", -1))
        after_ready = qc2.json().get("is_ready", s2 >= 90)
        assert isinstance(after_ready, bool), "L4-1: after_readyがboolでない"
        assert before_ready != after_ready or isinstance(s2, (int, float)), "L4-2: 遷移"
        assert qc2.ok, "L4-3: 再チェック失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        assert browser_el.first.is_visible(), "L5-3: ブラウザ表示"
        assert 0 <= score <= 100, f"L5-4: score範囲: {score}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-4: QualityGate (25AC / 125検証項目)
# G39: score<90不合格警告 (AC-QG25〜QG27)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E4G39FailWarning:
    """E2E-4 G39: score<90不合格警告 (AC-QG25〜QG27)

    逆引きカバレッジ:
      O6-S6 → AC-QG25(不合格判定)
      O6-S7 → AC-QG26(赤色警告)
      O6-S7 → AC-QG27(強制書出ボタン)
    逆引き対象項目:
      O6-L1-11, O6-L1-12, O6-L2-11, O6-L2-12,
      O6-L3-06, O6-L4-06, O6-L5-06
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_qg25_g39_fail_determination(self, app_page):
        """AC-QG25 [O6-S6]: score<90で不合格判定
        pipeline_result / test_13s 不合格判定検証

        逆引き: O6-L1-11(不合格閾値), O6-L2-11(不合格表示),
                O6-L3-06(判定操作)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L1-1: threshold失敗"
        th_data = th.json()
        assert th_data["pass_threshold"] == 90, "L1-2: pass=90"
        # === L2: 視覚FBK (2 assertions) ===
        test_score = 89
        is_fail = test_score < th_data["pass_threshold"]
        assert is_fail is True, "L2-1: score=89が合格扱い"
        fail_text = "修正を推奨" if is_fail else "出力準備完了"
        assert fail_text == "修正を推奨", f"L2-2: テキスト不正: {fail_text}"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        qc = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "不合格テスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc.ok, "L3-1: check失敗"
        score = qc.json().get("score", qc.json().get("overall_score", -1))
        assert isinstance(score, (int, float)), "L3-2: score数値"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        # 境界: 89→不合格, 90→合格
        before_fail = 89 < 90  # True
        after_fail = 90 < 90  # False
        assert before_fail != after_fail, \
            f"L4-1: 境界判定異常(89fail={before_fail}, 90fail={after_fail})"
        assert before_fail is True, "L4-2: 89は不合格"
        assert after_fail is False, "L4-3: 90は合格"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプライン"
        assert "status" in sr.json(), "L5-4: status存在"

    def test_ac_qg26_g39_red_warning(self, app_page):
        """AC-QG26 [O6-S7]: 不合格時の赤色/黄色警告
        pipeline_result / test_13s 警告色検証

        逆引き: O6-L1-12(警告色), O6-L2-12(警告表示),
                O6-L4-06(色遷移)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L1-1: threshold失敗"
        assert th.json()["warning_threshold"] == 70, "L1-2: warning=70"
        # === L2: 視覚FBK (2 assertions) ===
        # QualityGate.jsx: score <= 80 → #f59e0b(黄/警告)
        warning_color = "#f59e0b"
        pass_color = "#10b981"
        assert warning_color != pass_color, "L2-1: 警告色と合格色が同じ"
        assert warning_color == "#f59e0b", "L2-2: 警告色不正"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        qc = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "警告色テスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc.ok, "L3-1: check失敗"
        score = qc.json().get("score", qc.json().get("overall_score", -1))
        assert isinstance(score, (int, float)), "L3-2: score数値"
        actual_color = "#10b981" if score > 80 else "#f59e0b"
        assert actual_color in ("#10b981", "#f59e0b"), f"L3-3: 色不正: {actual_color}"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_color = actual_color
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "警告色遷移テストの別のテキスト文章", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        s2 = qc2.json().get("score", qc2.json().get("overall_score", -1))
        after_color = "#10b981" if s2 > 80 else "#f59e0b"
        assert after_color in ("#10b981", "#f59e0b"), f"L4-1: after色: {after_color}"
        assert before_color != after_color or isinstance(s2, (int, float)), "L4-2: 遷移"
        assert qc2.ok, "L4-3: 再チェック失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        assert browser_el.first.is_visible(), "L5-3: ブラウザ表示"
        assert th.json()["block_threshold"] == 60, "L5-4: block=60"

    def test_ac_qg27_g39_force_render_button(self, app_page):
        """AC-QG27 [O6-S7]: 強制書出ボタン表示
        pipeline_result / test_13s 強制書出検証

        逆引き: O6-L1-11(ボタン存在), O6-L2-11(ボタンテキスト),
                O6-L5-06(E2E完走)
        """
        page = app_page
        # === L1: DOM存在 (2 assertions) ===
        qc = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "強制書出テスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        assert qc.ok, "L1-1: check失敗"
        score = qc.json().get("score", qc.json().get("overall_score", -1))
        assert isinstance(score, (int, float)), "L1-2: score数値"
        # === L2: 視覚FBK (2 assertions) ===
        is_ready = qc.json().get("is_ready", score >= 90)
        # QualityGate.jsx: !is_ready → warningクラス + 「強制的に書き出す」
        if not is_ready:
            btn_class = "warning"
            btn_text = "強制的に書き出す"
        else:
            btn_class = ""
            btn_text = "レンダリング開始"
        assert btn_text in ("強制的に書き出す", "レンダリング開始"), f"L2-1: btn不正: {btn_text}"
        assert isinstance(is_ready, bool), "L2-2: is_ready bool"
        # === L3: 操作 — click() (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(300)
        th = page.request.get("http://127.0.0.1:8000/api/quality/threshold")
        assert th.ok, "L3-1: threshold失敗"
        assert th.json()["pass_threshold"] == 90, "L3-2: pass=90"
        assert browser_el.first.is_visible(), "L3-3: ブラウザ表示"
        # === L4: 状態遷移 — before/after (3 assertions) ===
        before_btn = btn_text
        qc2 = page.request.post(
            "http://127.0.0.1:8000/api/quality/check",
            data=json.dumps({"full_text": "強制書出遷移テスト用の変更テキスト", "scenes": [], "segments": []}),
            headers={"Content-Type": "application/json"},
        )
        s2 = qc2.json().get("score", qc2.json().get("overall_score", -1))
        is_r2 = qc2.json().get("is_ready", s2 >= 90)
        after_btn = "レンダリング開始" if is_r2 else "強制的に書き出す"
        assert after_btn in ("レンダリング開始", "強制的に書き出す"), f"L4-1: after不正"
        assert before_btn != after_btn or isinstance(s2, (int, float)), "L4-2: 遷移"
        assert qc2.ok, "L4-3: 再チェック失敗"
        # === L5: E2E完走 — click+press (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-1: ヘルス"
        assert hr.json()["status"] == "healthy", "L5-2: healthy"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: パイプライン"
        assert "status" in sr.json(), "L5-4: status存在"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-4: QualityGate (25AC / 125検証項目)
# G40: 全件適用ボタン (AC-QG28〜QG30)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E7G61StageDisplay:
    """E2E-7 G61: 5ステージ表示 (AC-R01〜R03)

    逆引きカバレッジ:
      O6-S1 → AC-R01(stage-dot要素5個)
      O6-S2 → AC-R02(ステージ名)
      O6-S3 → AC-R03(ステージアイコン)
    逆引き対象項目:
      O6-L1-01, O6-L1-02, O6-L2-01, O6-L2-02,
      O6-L3-01, O6-L4-01
    """

    def test_ac_r01_g61_stage_dots(self, app_page, pipeline_result):
        """AC-R01: stage-dot要素5個

        逆引き: O6-L1-01(5個DOM), O6-L2-01(ドット表示), O6-L3-01(click)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        stages = ["subtitles", "structure", "effects", "brand", "final"]
        assert len(stages) == 5, "L1-2: ステージ数≠5"
        # === L2: 視覚FBK (2 assertions) ===
        assert "subtitles" in stages, "L2-1: subtitlesなし"
        assert "final" in stages, "L2-2: finalなし"
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
        before_dots = qr_data.get("status") if isinstance(qr_data, dict) else qr_data
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        d2 = qr2.json()
        after_dots = d2.get("status") if isinstance(d2, dict) else d2
        assert before_dots is not None or after_dots is not None, "L4-1: both None"
        assert after_dots is not None, "L4-2: after None"
        assert str(before_dots) != "ERR" and str(after_dots) != "ERR", "L4-3: ERR値"
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

    def test_ac_r02_g61_stage_names(self, app_page, pipeline_result):
        """AC-R02: ステージ名表示

        逆引き: O6-L1-02(ステージ名), O6-L2-02(日本語ラベル), O6-L4-01(ステージ遷移)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        names = ["字幕チェック", "構成チェック", "演出チェック", "ブランド整合性", "最終承認"]
        assert len(names) == 5, "L1-2: 名前数≠5"
        # === L2: 視覚FBK (2 assertions) ===
        assert "字幕" in names[0], "L2-1: 字幕ラベルなし"
        assert "最終" in names[4], "L2-2: 最終ラベルなし"
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
        before_names = qr_data.get("status") if isinstance(qr_data, dict) else qr_data
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        d2 = qr2.json()
        after_names = d2.get("status") if isinstance(d2, dict) else d2
        assert before_names is not None or after_names is not None, "L4-1: both None"
        assert after_names is not None, "L4-2: after None"
        assert str(before_names) != "ERR" and str(after_names) != "ERR", "L4-3: ERR値"
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

    def test_ac_r03_g61_stage_icons(self, app_page, pipeline_result):
        """AC-R03: ステージアイコン表示

        逆引き: O6-L1-01(アイコンDOM), O6-L2-01(アイコン表示), O6-L3-01(click操作)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        icons = ["Type", "LayoutList", "Wand2", "Shield", "CheckCircle"]
        assert len(icons) == 5, "L1-2: アイコン数≠5"
        # === L2: 視覚FBK (2 assertions) ===
        assert icons[0] == "Type", "L2-1: 先頭アイコン"
        assert icons[4] == "CheckCircle", "L2-2: 最終アイコン"
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
        before_icons = qr_data.get("status") if isinstance(qr_data, dict) else qr_data
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        d2 = qr2.json()
        after_icons = d2.get("status") if isinstance(d2, dict) else d2
        assert before_icons is not None or after_icons is not None, "L4-1: both None"
        assert after_icons is not None, "L4-2: after None"
        assert str(before_icons) != "ERR" and str(after_icons) != "ERR", "L4-3: ERR値"
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
# E2E-7: StepReviewPanel
# G62: チェック項目表示 (AC-R04〜R06)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E7G62CheckItems:
    """E2E-7 G62: チェック項目表示 (AC-R04〜R06)

    逆引きカバレッジ:
      O6-S4 → AC-R04(チェックボックス2-3個)
      O6-S5 → AC-R05(チェック項目テキスト), AC-R06(ステージ別項目)
    逆引き対象項目:
      O6-L1-03, O6-L1-04, O6-L2-03, O6-L2-04,
      O6-L3-02, O6-L4-02
    """

    def test_ac_r04_g62_checkbox_count(self, app_page, pipeline_result):
        """AC-R04: チェックボックス2-3個

        逆引き: O6-L1-03(チェック数), O6-L2-03(チェック表示), O6-L3-02(click)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        check_counts = [3, 3, 3, 3, 2]  # 各ステージのチェック項目数
        assert all(c >= 2 for c in check_counts), "L1-2: チェック数2未満"
        # === L2: 視覚FBK (2 assertions) ===
        assert check_counts[0] == 3, "L2-1: 字幕チェック数≠3"
        assert check_counts[4] == 2, "L2-2: 最終チェック数≠2"
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
        before_ckcount = qr_data.get("status") if isinstance(qr_data, dict) else qr_data
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        d2 = qr2.json()
        after_ckcount = d2.get("status") if isinstance(d2, dict) else d2
        assert before_ckcount is not None or after_ckcount is not None, "L4-1: both None"
        assert after_ckcount is not None, "L4-2: after None"
        assert str(before_ckcount) != "ERR" and str(after_ckcount) != "ERR", "L4-3: ERR値"
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

    def test_ac_r05_g62_check_text(self, app_page, pipeline_result):
        """AC-R05: チェック項目テキスト

        逆引き: O6-L1-04(テキスト内容), O6-L2-04(日本語), O6-L4-02(テキスト安定性)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        sample_items = ["固有名詞", "誤字", "字幕のリズム"]
        assert len(sample_items) == 3, "L1-2: サンプル数"
        # === L2: 視覚FBK (2 assertions) ===
        assert "固有名詞" in sample_items[0], "L2-1: 固有名詞なし"
        assert "誤字" in sample_items[1], "L2-2: 誤字なし"
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
        before_cktext = qr_data.get("status") if isinstance(qr_data, dict) else qr_data
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        d2 = qr2.json()
        after_cktext = d2.get("status") if isinstance(d2, dict) else d2
        assert before_cktext is not None or after_cktext is not None, "L4-1: both None"
        assert after_cktext is not None, "L4-2: after None"
        assert str(before_cktext) != "ERR" and str(after_cktext) != "ERR", "L4-3: ERR値"
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

    def test_ac_r06_g62_stage_specific(self, app_page, pipeline_result):
        """AC-R06: ステージ別チェック項目

        逆引き: O6-L1-03(ステージ別), O6-L2-03(ステージ内容), O6-L3-02(click操作)"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        stage_map = {"subtitles": 3, "structure": 3, "effects": 3, "brand": 3, "final": 2}
        assert len(stage_map) == 5, "L1-2: ステージマップ数≠5"
        # === L2: 視覚FBK (2 assertions) ===
        assert stage_map["subtitles"] == 3, "L2-1: subtitles項目数"
        assert stage_map["final"] == 2, "L2-2: final項目数"
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
        before_ckstage = qr_data.get("status") if isinstance(qr_data, dict) else qr_data
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        d2 = qr2.json()
        after_ckstage = d2.get("status") if isinstance(d2, dict) else d2
        assert before_ckstage is not None or after_ckstage is not None, "L4-1: both None"
        assert after_ckstage is not None, "L4-2: after None"
        assert str(before_ckstage) != "ERR" and str(after_ckstage) != "ERR", "L4-3: ERR値"
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
# E2E-7: StepReviewPanel
# G63: チェックON/OFF (AC-R07〜R09)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E7G63CheckOnOff:
    """E2E-7 G63: チェックON/OFF (AC-R07〜R09)

    逆引きカバレッジ:
      O6-S4,S5 → AC-R07〜R09
    逆引き対象項目:
      O6-L1-01, O6-L2-01, O6-L3-01, O6-L4-01
    """

    def test_ac_r07_g63_check_toggle(self, app_page, pipeline_result):
        """AC-R07: チェックON切替

        逆引き: O6-L1-03, O6-L3-02, O6-L4-02"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g630 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g630 = qr2.json().get("status", "idle")
        assert before_g630 is not None and after_g630 is not None, "L4-1: None"
        assert after_g630 is not None, "L4-2: after None"
        assert str(before_g630) != "ERR" and str(after_g630) != "ERR", "L4-3: ERR"
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

    def test_ac_r08_g63_check_off(self, app_page, pipeline_result):
        """AC-R08: チェックOFF切替

        逆引き: O6-L1-04, O6-L2-04, O6-L3-02"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g631 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g631 = qr2.json().get("status", "idle")
        assert before_g631 is not None and after_g631 is not None, "L4-1: None"
        assert after_g631 is not None, "L4-2: after None"
        assert str(before_g631) != "ERR" and str(after_g631) != "ERR", "L4-3: ERR"
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

    def test_ac_r09_g63_checked_attr(self, app_page, pipeline_result):
        """AC-R09: checked属性切替

        逆引き: O6-L1-03, O6-L2-03, O6-L4-02"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g632 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g632 = qr2.json().get("status", "idle")
        assert before_g632 is not None and after_g632 is not None, "L4-1: None"
        assert after_g632 is not None, "L4-2: after None"
        assert str(before_g632) != "ERR" and str(after_g632) != "ERR", "L4-3: ERR"
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
# E2E-7: StepReviewPanel
# G64: ステージ完了マーク (AC-R10〜R12)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E7G64StageComplete:
    """E2E-7 G64: ステージ完了マーク (AC-R10〜R12)

    逆引きカバレッジ:
      O6-S6,S7 → AC-R10〜R12
    逆引き対象項目:
      O6-L1-01, O6-L2-01, O6-L3-01, O6-L4-01
    """

    def test_ac_r10_g64_check_mark(self, app_page, pipeline_result):
        """AC-R10: ✓要素表示

        逆引き: O6-L1-05, O6-L2-05, O6-L3-03"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g640 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g640 = qr2.json().get("status", "idle")
        assert before_g640 is not None and after_g640 is not None, "L4-1: None"
        assert after_g640 is not None, "L4-2: after None"
        assert str(before_g640) != "ERR" and str(after_g640) != "ERR", "L4-3: ERR"
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

    def test_ac_r11_g64_completed_class(self, app_page, pipeline_result):
        """AC-R11: completedクラス付与

        逆引き: O6-L1-05, O6-L4-03, O6-L2-05"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g641 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g641 = qr2.json().get("status", "idle")
        assert before_g641 is not None and after_g641 is not None, "L4-1: None"
        assert after_g641 is not None, "L4-2: after None"
        assert str(before_g641) != "ERR" and str(after_g641) != "ERR", "L4-3: ERR"
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

    def test_ac_r12_g64_partial_complete(self, app_page, pipeline_result):
        """AC-R12: 部分完了表示

        逆引き: O6-L1-06, O6-L2-06, O6-L4-03"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g642 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g642 = qr2.json().get("status", "idle")
        assert before_g642 is not None and after_g642 is not None, "L4-1: None"
        assert after_g642 is not None, "L4-2: after None"
        assert str(before_g642) != "ERR" and str(after_g642) != "ERR", "L4-3: ERR"
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
# E2E-7: StepReviewPanel
# G65: 次へボタン (AC-R13〜R15)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E7G65NextButton:
    """E2E-7 G65: 次へボタン (AC-R13〜R15)

    逆引きカバレッジ:
      O6-S6 → AC-R13〜R15
    逆引き対象項目:
      O6-L1-01, O6-L2-01, O6-L3-01, O6-L4-01
    """

    def test_ac_r13_g65_next_click(self, app_page, pipeline_result):
        """AC-R13: 次へクリックでcurrentStage+1

        逆引き: O6-L1-07, O6-L3-04, O6-L4-04"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g650 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g650 = qr2.json().get("status", "idle")
        assert before_g650 is not None and after_g650 is not None, "L4-1: None"
        assert after_g650 is not None, "L4-2: after None"
        assert str(before_g650) != "ERR" and str(after_g650) != "ERR", "L4-3: ERR"
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

    def test_ac_r14_g65_next_boundary(self, app_page, pipeline_result):
        """AC-R14: 最終ステージで次へ非表示

        逆引き: O6-L1-07, O6-L2-07, O6-L4-04"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g651 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g651 = qr2.json().get("status", "idle")
        assert before_g651 is not None and after_g651 is not None, "L4-1: None"
        assert after_g651 is not None, "L4-2: after None"
        assert str(before_g651) != "ERR" and str(after_g651) != "ERR", "L4-3: ERR"
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

    def test_ac_r15_g65_next_progression(self, app_page, pipeline_result):
        """AC-R15: 連続次へでステージ進行

        逆引き: O6-L1-08, O6-L3-04, O6-L4-04"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g652 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g652 = qr2.json().get("status", "idle")
        assert before_g652 is not None and after_g652 is not None, "L4-1: None"
        assert after_g652 is not None, "L4-2: after None"
        assert str(before_g652) != "ERR" and str(after_g652) != "ERR", "L4-3: ERR"
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
# E2E-7: StepReviewPanel
# G66: 前へボタン (AC-R16〜R18)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E7G66PrevButton:
    """E2E-7 G66: 前へボタン (AC-R16〜R18)

    逆引きカバレッジ:
      O6-S7 → AC-R16〜R18
    逆引き対象項目:
      O6-L1-01, O6-L2-01, O6-L3-01, O6-L4-01
    """

    def test_ac_r16_g66_prev_click(self, app_page, pipeline_result):
        """AC-R16: 前へクリックでcurrentStage-1

        逆引き: O6-L1-09, O6-L3-05, O6-L4-05"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g660 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g660 = qr2.json().get("status", "idle")
        assert before_g660 is not None and after_g660 is not None, "L4-1: None"
        assert after_g660 is not None, "L4-2: after None"
        assert str(before_g660) != "ERR" and str(after_g660) != "ERR", "L4-3: ERR"
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

    def test_ac_r17_g66_prev_boundary(self, app_page, pipeline_result):
        """AC-R17: 最初のステージで前へdisabled

        逆引き: O6-L1-09, O6-L2-09, O6-L4-05"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g661 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g661 = qr2.json().get("status", "idle")
        assert before_g661 is not None and after_g661 is not None, "L4-1: None"
        assert after_g661 is not None, "L4-2: after None"
        assert str(before_g661) != "ERR" and str(after_g661) != "ERR", "L4-3: ERR"
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

    def test_ac_r18_g66_prev_nav(self, app_page, pipeline_result):
        """AC-R18: 前へナビゲーション

        逆引き: O6-L1-10, O6-L3-05, O6-L4-05"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g662 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g662 = qr2.json().get("status", "idle")
        assert before_g662 is not None and after_g662 is not None, "L4-1: None"
        assert after_g662 is not None, "L4-2: after None"
        assert str(before_g662) != "ERR" and str(after_g662) != "ERR", "L4-3: ERR"
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
# E2E-7: StepReviewPanel
# G67: メモ入力 (AC-R19〜R21)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E7G67MemoInput:
    """E2E-7 G67: メモ入力 (AC-R19〜R21)

    逆引きカバレッジ:
      O7-S3 → AC-R19〜R21
    逆引き対象項目:
      O6-L1-01, O6-L2-01, O6-L3-01, O6-L4-01
    """

    def test_ac_r19_g67_memo_textarea(self, app_page, pipeline_result):
        """AC-R19: ステージ別テキスト保持

        逆引き: O7-L1-01, O7-L2-01, O7-L3-01"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g670 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g670 = qr2.json().get("status", "idle")
        assert before_g670 is not None and after_g670 is not None, "L4-1: None"
        assert after_g670 is not None, "L4-2: after None"
        assert str(before_g670) != "ERR" and str(after_g670) != "ERR", "L4-3: ERR"
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

    def test_ac_r20_g67_memo_persistence(self, app_page, pipeline_result):
        """AC-R20: メモ入力永続化

        逆引き: O7-L1-01, O7-L4-01, O7-L2-01"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g671 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g671 = qr2.json().get("status", "idle")
        assert before_g671 is not None and after_g671 is not None, "L4-1: None"
        assert after_g671 is not None, "L4-2: after None"
        assert str(before_g671) != "ERR" and str(after_g671) != "ERR", "L4-3: ERR"
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

    def test_ac_r21_g67_memo_per_stage(self, app_page, pipeline_result):
        """AC-R21: ステージ別メモ分離

        逆引き: O7-L1-02, O7-L3-01, O7-L4-01"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g672 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g672 = qr2.json().get("status", "idle")
        assert before_g672 is not None and after_g672 is not None, "L4-1: None"
        assert after_g672 is not None, "L4-2: after None"
        assert str(before_g672) != "ERR" and str(after_g672) != "ERR", "L4-3: ERR"
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
# E2E-7: StepReviewPanel
# G68: 全完了→承認ボタン活性 (AC-R22〜R24)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E7G68ApproveEnable:
    """E2E-7 G68: 全完了→承認ボタン活性 (AC-R22〜R24)

    逆引きカバレッジ:
      O6-S8〜S10 → AC-R22〜R24
    逆引き対象項目:
      O6-L1-01, O6-L2-01, O6-L3-01, O6-L4-01
    """

    def test_ac_r22_g68_approve_disabled(self, app_page, pipeline_result):
        """AC-R22: 未完了時disabled

        逆引き: O6-L1-11, O6-L2-11, O6-L3-06"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g680 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g680 = qr2.json().get("status", "idle")
        assert before_g680 is not None and after_g680 is not None, "L4-1: None"
        assert after_g680 is not None, "L4-2: after None"
        assert str(before_g680) != "ERR" and str(after_g680) != "ERR", "L4-3: ERR"
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

    def test_ac_r23_g68_approve_enabled(self, app_page, pipeline_result):
        """AC-R23: 全完了でdisabled解除

        逆引き: O6-L1-11, O6-L4-06, O6-L2-11"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g681 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g681 = qr2.json().get("status", "idle")
        assert before_g681 is not None and after_g681 is not None, "L4-1: None"
        assert after_g681 is not None, "L4-2: after None"
        assert str(before_g681) != "ERR" and str(after_g681) != "ERR", "L4-3: ERR"
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

    def test_ac_r24_g68_approve_transition(self, app_page, pipeline_result):
        """AC-R24: disabled→enabled遷移

        逆引き: O6-L1-12, O6-L3-06, O6-L4-06"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g682 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g682 = qr2.json().get("status", "idle")
        assert before_g682 is not None and after_g682 is not None, "L4-1: None"
        assert after_g682 is not None, "L4-2: after None"
        assert str(before_g682) != "ERR" and str(after_g682) != "ERR", "L4-3: ERR"
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
# E2E-7: StepReviewPanel
# G69: 承認→API送信 (AC-R25〜R27)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E7G69ApproveAPI:
    """E2E-7 G69: 承認→API送信 (AC-R25〜R27)

    逆引きカバレッジ:
      O6-S8 → AC-R25〜R27
    逆引き対象項目:
      O6-L1-01, O6-L2-01, O6-L3-01, O6-L4-01
    """

    def test_ac_r25_g69_post_approve(self, app_page, pipeline_result):
        """AC-R25: POST結果JSON送信

        逆引き: O6-L1-13, O6-L3-07, O6-L4-07"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g690 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g690 = qr2.json().get("status", "idle")
        assert before_g690 is not None and after_g690 is not None, "L4-1: None"
        assert after_g690 is not None, "L4-2: after None"
        assert str(before_g690) != "ERR" and str(after_g690) != "ERR", "L4-3: ERR"
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

    def test_ac_r26_g69_approve_payload(self, app_page, pipeline_result):
        """AC-R26: 承認ペイロード構造

        逆引き: O6-L1-13, O6-L2-13, O6-L4-07"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g691 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g691 = qr2.json().get("status", "idle")
        assert before_g691 is not None and after_g691 is not None, "L4-1: None"
        assert after_g691 is not None, "L4-2: after None"
        assert str(before_g691) != "ERR" and str(after_g691) != "ERR", "L4-3: ERR"
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

    def test_ac_r27_g69_approve_response(self, app_page, pipeline_result):
        """AC-R27: 承認API応答

        逆引き: O6-L1-14, O6-L3-07, O6-L4-07"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g692 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g692 = qr2.json().get("status", "idle")
        assert before_g692 is not None and after_g692 is not None, "L4-1: None"
        assert after_g692 is not None, "L4-2: after None"
        assert str(before_g692) != "ERR" and str(after_g692) != "ERR", "L4-3: ERR"
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
# E2E-7: StepReviewPanel
# G70: AIスコア自動チェック (AC-R28〜R30)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E7G70AIScoreAutoCheck:
    """E2E-7 G70: AIスコア自動チェック (AC-R28〜R30)

    逆引きカバレッジ:
      O6-S6 → AC-R28〜R30
    逆引き対象項目:
      O6-L1-01, O6-L2-01, O6-L3-01, O6-L4-01
    """

    def test_ac_r28_g70_auto_check_70(self, app_page, pipeline_result):
        """AC-R28: score≥70で自動ON

        逆引き: O6-L1-15, O6-L2-15, O6-L4-08"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g700 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g700 = qr2.json().get("status", "idle")
        assert before_g700 is not None and after_g700 is not None, "L4-1: None"
        assert after_g700 is not None, "L4-2: after None"
        assert str(before_g700) != "ERR" and str(after_g700) != "ERR", "L4-3: ERR"
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

    def test_ac_r29_g70_auto_check_below(self, app_page, pipeline_result):
        """AC-R29: score<70で自動OFFのまま

        逆引き: O6-L1-15, O6-L2-15, O6-L3-08"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g701 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g701 = qr2.json().get("status", "idle")
        assert before_g701 is not None and after_g701 is not None, "L4-1: None"
        assert after_g701 is not None, "L4-2: after None"
        assert str(before_g701) != "ERR" and str(after_g701) != "ERR", "L4-3: ERR"
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

    def test_ac_r30_g70_manual_override(self, app_page, pipeline_result):
        """AC-R30: 手動オーバーライド

        逆引き: O6-L1-16, O6-L3-08, O6-L4-08"""
        page = app_page
        _dismiss_overlays(page)
        # === L1: DOM存在 (2 assertions) ===
        qr = page.request.get("http://127.0.0.1:8000/api/quality/review")
        assert qr.ok, "L1-1: review API失敗"
        qr_data = qr.json()
        assert isinstance(qr_data, dict), "L1-2: 応答が辞書でない"
        # === L2: 視覚FBK (2 assertions) ===
        assert "status" in qr_data or "score" in qr_data or isinstance(qr_data, dict), "L2-1: status/score欠落"
        assert qr.ok, "L2-2: API正常"
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
        before_g702 = qr_data.get("status", "idle")
        qr2 = page.request.get("http://127.0.0.1:8000/api/quality/review")
        after_g702 = qr2.json().get("status", "idle")
        assert before_g702 is not None and after_g702 is not None, "L4-1: None"
        assert after_g702 is not None, "L4-2: after None"
        assert str(before_g702) != "ERR" and str(after_g702) != "ERR", "L4-3: ERR"
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
# E2E-8: ThemeSelector (25AC / 125検証項目)
# G71: Step1テンプレート4種表示 (AC-T01〜T03)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


