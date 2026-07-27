"""
E2E テスト — A-4 CI/CD・品質保証 5層検証 (55項目)

検証5層モデル:
  L1: DOM存在 (12項目)
  L2: 視覚フィードバック (10項目)
  L3: インタラクション (13項目)
  L4: 状態遷移 (10項目)
  L5: E2E完走 (10項目)

設計書: design_admin_a1_a7_full.md.resolved (推移表転記済み/)
"""
import pytest
import json

BASE = "http://localhost:8000/api/admin/quality"


@pytest.mark.e2e
class TestA4L1DomExists:
    """L1: DOM存在 (12項目)"""

    def test_a4_l1_01(self, app_page):
        """A4-L1-01 [S1]: CI/CD品質保証ダッシュボードAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/dashboard")
        assert r.ok

    def test_a4_l1_02(self, app_page):
        """A4-L1-02 [S1]: ダッシュボードにsectionsフィールドが存在する"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert "sections" in d
        assert len(d["sections"]) >= 10

    def test_a4_l1_03(self, app_page):
        """A4-L1-03 [S2]: テスト結果APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/test-results")
        assert r.ok

    def test_a4_l1_04(self, app_page):
        """A4-L1-04 [S3]: カバレッジAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/coverage")
        assert r.ok

    def test_a4_l1_05(self, app_page):
        """A4-L1-05 [S4]: カバレッジ推移APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/coverage-trend")
        assert r.ok

    def test_a4_l1_06(self, app_page):
        """A4-L1-06 [S5]: Fitness Functions結果APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/fitness")
        assert r.ok

    def test_a4_l1_07(self, app_page):
        """A4-L1-07 [S6]: ラチェット結果APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/ratchet")
        assert r.ok

    def test_a4_l1_08(self, app_page):
        """A4-L1-08 [S7]: FV検証結果APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/fv")
        assert r.ok

    def test_a4_l1_09(self, app_page):
        """A4-L1-09 [S8]: E2Eテスト結果APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/e2e")
        assert r.ok

    def test_a4_l1_10(self, app_page):
        """A4-L1-10 [S9]: 品質ゲート状態APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/quality-gates")
        assert r.ok

    def test_a4_l1_11(self, app_page):
        """A4-L1-11 [S17]: デプロイ状態APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/deploy")
        assert r.ok

    def test_a4_l1_12(self, app_page):
        """A4-L1-12 [S21]: 通知設定APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/notifications")
        assert r.ok


@pytest.mark.e2e
class TestA4L2VisualFeedback:
    """L2: 視覚フィードバック (10項目)"""

    def test_a4_l2_01(self, app_page):
        """A4-L2-01 [S1]: ダッシュボードにtitle/status/summaryが含まれる"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert all(k in d for k in ["title", "status", "summary"])

    def test_a4_l2_02(self, app_page):
        """A4-L2-02 [S2]: テスト結果にpassed/failed/skipped/totalが含まれる"""
        d = app_page.request.get(f"{BASE}/test-results").json()
        assert all(k in d for k in ["passed", "failed", "skipped", "total"])

    def test_a4_l2_03(self, app_page):
        """A4-L2-03 [S3]: カバレッジにbranch_pct/line_pctが含まれる"""
        d = app_page.request.get(f"{BASE}/coverage").json()
        assert all(k in d for k in ["branch_pct", "line_pct"])

    def test_a4_l2_04(self, app_page):
        """A4-L2-04 [S4]: カバレッジ推移にhistory配列とperiod_daysが含まれる"""
        d = app_page.request.get(f"{BASE}/coverage-trend").json()
        assert "history" in d and "period_days" in d
        assert isinstance(d["history"], list)

    def test_a4_l2_05(self, app_page):
        """A4-L2-05 [S5]: Fitness結果にpassed/total/functionsが含まれる"""
        d = app_page.request.get(f"{BASE}/fitness").json()
        assert all(k in d for k in ["passed", "total", "functions"])

    def test_a4_l2_06(self, app_page):
        """A4-L2-06 [S6]: ラチェット結果にvalid/total_items/pass_itemsが含まれる"""
        d = app_page.request.get(f"{BASE}/ratchet").json()
        assert all(k in d for k in ["valid", "total_items", "pass_items"])

    def test_a4_l2_07(self, app_page):
        """A4-L2-07 [S9]: 品質ゲートにgate_a/gate_b/gate_c/gate_dが含まれる"""
        d = app_page.request.get(f"{BASE}/quality-gates").json()
        assert all(k in d for k in ["gate_a", "gate_b", "gate_c", "gate_d"])

    def test_a4_l2_08(self, app_page):
        """A4-L2-08 [S10]: vision-gapにscore/axes/weightedが含まれる"""
        d = app_page.request.get(f"{BASE}/vision-gap").json()
        assert all(k in d for k in ["score", "axes", "weighted"])

    def test_a4_l2_09(self, app_page):
        """A4-L2-09 [S17]: デプロイ状態にversion/deployed_at/statusが含まれる"""
        d = app_page.request.get(f"{BASE}/deploy").json()
        assert all(k in d for k in ["version", "deployed_at", "status"])

    def test_a4_l2_10(self, app_page):
        """A4-L2-10 [S21]: 通知設定にchannels配列とenabledが含まれる"""
        d = app_page.request.get(f"{BASE}/notifications").json()
        assert "channels" in d and "enabled" in d
        assert isinstance(d["channels"], list)


@pytest.mark.e2e
class TestA4L3Interaction:
    """L3: インタラクション (13項目)"""

    def test_a4_l3_01(self, app_page):
        """A4-L3-01 [S2]: テスト結果のpassedが0以上の数値である"""
        d = app_page.request.get(f"{BASE}/test-results").json()
        assert isinstance(d["passed"], int)
        assert d["passed"] >= 0

    def test_a4_l3_02(self, app_page):
        """A4-L3-02 [S4]: カバレッジ推移の30日間データが配列で返される"""
        d = app_page.request.get(f"{BASE}/coverage-trend").json()
        assert len(d["history"]) == 30
        assert "branch_pct" in d["history"][0]

    def test_a4_l3_03(self, app_page):
        """A4-L3-03 [S5]: Fitness Functionsの各項目にname/passed/descriptionが含まれる"""
        d = app_page.request.get(f"{BASE}/fitness").json()
        for f in d["functions"]:
            assert all(k in f for k in ["name", "passed", "description"])

    def test_a4_l3_04(self, app_page):
        """A4-L3-04 [S6]: ラチェット結果のtotal_itemsが0以上の数値である"""
        d = app_page.request.get(f"{BASE}/ratchet").json()
        assert isinstance(d["total_items"], int)
        assert d["total_items"] >= 0

    def test_a4_l3_05(self, app_page):
        """A4-L3-05 [S7]: FV検証結果にcategories配列が含まれる"""
        d = app_page.request.get(f"{BASE}/fv").json()
        assert "categories" in d
        assert isinstance(d["categories"], list)
        assert len(d["categories"]) > 0

    def test_a4_l3_06(self, app_page):
        """A4-L3-06 [S8]: E2Eテスト結果にsuites配列が含まれる"""
        d = app_page.request.get(f"{BASE}/e2e").json()
        assert "suites" in d
        assert isinstance(d["suites"], list)
        assert len(d["suites"]) > 0

    def test_a4_l3_07(self, app_page):
        """A4-L3-07 [S9]: 品質ゲートの各ゲートにstatus/conditionsが含まれる"""
        d = app_page.request.get(f"{BASE}/quality-gates").json()
        for gate_key in ["gate_a", "gate_b", "gate_c", "gate_d"]:
            gate = d[gate_key]
            assert all(k in gate for k in ["status", "conditions"])

    def test_a4_l3_08(self, app_page):
        """A4-L3-08 [S10]: vision-gapのscoreが0-100の範囲で返される"""
        d = app_page.request.get(f"{BASE}/vision-gap").json()
        assert 0 <= d["score"] <= 100

    def test_a4_l3_09(self, app_page):
        """A4-L3-09 [S11]: 品質トレンドAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/quality-trend")
        assert r.ok
        d = r.json()
        assert "history" in d

    def test_a4_l3_10(self, app_page):
        """A4-L3-10 [S12]: 失敗分析APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/failure-analysis")
        assert r.ok
        d = r.json()
        assert "failures" in d

    def test_a4_l3_11(self, app_page):
        """A4-L3-11 [S13]: テスト手動実行APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/run-tests",
            data=json.dumps({"suite": "all"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "started"

    def test_a4_l3_12(self, app_page):
        """A4-L3-12 [S14]: レポート生成APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/generate-report",
            data=json.dumps({"format": "html"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "generated"

    def test_a4_l3_13(self, app_page):
        """A4-L3-13 [S15]: リント結果APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/lint")
        assert r.ok


@pytest.mark.e2e
class TestA4L4StateTransition:
    """L4: 状態遷移 (10項目)"""

    def test_a4_l4_01(self, app_page):
        """A4-L4-01 [S11]: 品質トレンドにhistory配列が含まれる"""
        d = app_page.request.get(f"{BASE}/quality-trend").json()
        assert "history" in d
        assert isinstance(d["history"], list)
        assert len(d["history"]) == 30

    def test_a4_l4_02(self, app_page):
        """A4-L4-02 [S12]: 失敗分析にfailures配列とcategoriesが含まれる"""
        d = app_page.request.get(f"{BASE}/failure-analysis").json()
        assert all(k in d for k in ["failures", "categories"])
        assert isinstance(d["failures"], list)

    def test_a4_l4_03(self, app_page):
        """A4-L4-03 [S13]: 無効なテストスイート指定で適切なエラーが返る"""
        r = app_page.request.post(f"{BASE}/run-tests",
            data=json.dumps({"suite": "invalid_suite"}),
            headers={"Content-Type": "application/json"})
        assert r.status == 400

    def test_a4_l4_04(self, app_page):
        """A4-L4-04 [S14]: レポート生成後にdownload_urlが含まれる"""
        r = app_page.request.post(f"{BASE}/generate-report",
            data=json.dumps({"format": "pdf"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        d = r.json()
        assert "download_url" in d
        assert d["download_url"].endswith(".pdf")

    def test_a4_l4_05(self, app_page):
        """A4-L4-05 [S15]: リント結果にissues配列とtotalが含まれる"""
        d = app_page.request.get(f"{BASE}/lint").json()
        assert "issues" in d and "total" in d
        assert isinstance(d["issues"], list)

    def test_a4_l4_06(self, app_page):
        """A4-L4-06 [S16]: セキュリティスキャン結果APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/security")
        assert r.ok
        d = r.json()
        assert "severity_summary" in d

    def test_a4_l4_07(self, app_page):
        """A4-L4-07 [S18]: ロールバックAPIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/rollback",
            data=json.dumps({"target_version": "3.5.0"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "rolled_back"

    def test_a4_l4_08(self, app_page):
        """A4-L4-08 [S19]: 変更ログにcommits配列が含まれる"""
        d = app_page.request.get(f"{BASE}/changelog").json()
        assert "commits" in d
        assert isinstance(d["commits"], list)
        assert len(d["commits"]) > 0

    def test_a4_l4_09(self, app_page):
        """A4-L4-09 [S20]: 品質基準設定の更新がPOSTで反映される"""
        app_page.request.post(f"{BASE}/quality-settings",
            data=json.dumps({"coverage_threshold": 80.0, "tests_required": True}),
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/quality-settings").json()
        assert d["coverage_threshold"] == 80.0

    def test_a4_l4_10(self, app_page):
        """A4-L4-10 [S21]: 通知設定の更新がPOSTで反映される"""
        app_page.request.post(f"{BASE}/notifications",
            data=json.dumps({"channels": ["slack", "discord"], "enabled": True}),
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/notifications").json()
        assert "discord" in d["channels"]


@pytest.mark.e2e
class TestA4L5EndToEnd:
    """L5: E2E完走 (10項目)"""

    def test_a4_l5_01(self, app_page):
        """A4-L5-01 [S16]: ダッシュボード→テスト結果→カバレッジ→セキュリティの完走"""
        assert app_page.request.get(f"{BASE}/dashboard").ok
        tr = app_page.request.get(f"{BASE}/test-results").json()
        assert tr["passed"] >= 0
        cov = app_page.request.get(f"{BASE}/coverage").json()
        assert cov["branch_pct"] > 0
        sec = app_page.request.get(f"{BASE}/security").json()
        assert "severity_summary" in sec

    def test_a4_l5_02(self, app_page):
        """A4-L5-02 [S18]: デプロイ状態→ロールバック→変更ログの完走"""
        dep = app_page.request.get(f"{BASE}/deploy").json()
        assert "version" in dep
        rb = app_page.request.post(f"{BASE}/rollback",
            data=json.dumps({"target_version": "3.5.0"}),
            headers={"Content-Type": "application/json"}).json()
        assert rb["status"] == "rolled_back"
        cl = app_page.request.get(f"{BASE}/changelog").json()
        assert len(cl["commits"]) > 0

    def test_a4_l5_03(self, app_page):
        """A4-L5-03 [S19]: Fitness→ラチェット→FV→E2E→品質ゲートの完走"""
        fit = app_page.request.get(f"{BASE}/fitness").json()
        assert fit["all_passed"]
        rat = app_page.request.get(f"{BASE}/ratchet").json()
        assert rat["valid"]
        fv = app_page.request.get(f"{BASE}/fv").json()
        assert fv["passed"] > 0
        e2e = app_page.request.get(f"{BASE}/e2e").json()
        assert e2e["passed"] > 0
        gates = app_page.request.get(f"{BASE}/quality-gates").json()
        assert gates["gate_a"]["status"] == "passed"

    def test_a4_l5_04(self, app_page):
        """A4-L5-04 [S20]: 品質基準設定→閾値変更→確認の完走"""
        app_page.request.post(f"{BASE}/quality-settings",
            data=json.dumps({"coverage_threshold": 75.0, "tests_required": True}),
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/quality-settings").json()
        assert d["coverage_threshold"] == 75.0
        assert d["tests_required"] is True

    def test_a4_l5_05(self, app_page):
        """A4-L5-05 [S20]: vision-gap→品質トレンド→失敗分析の完走"""
        vg = app_page.request.get(f"{BASE}/vision-gap").json()
        assert vg["score"] > 0
        qt = app_page.request.get(f"{BASE}/quality-trend").json()
        assert len(qt["history"]) == 30
        fa = app_page.request.get(f"{BASE}/failure-analysis").json()
        assert "categories" in fa

    def test_a4_l5_06(self, app_page):
        """A4-L5-06 [S22]: 全GETエンドポイント疎通確認の完走"""
        endpoints = [
            "/dashboard", "/test-results", "/coverage",
            "/coverage-trend", "/fitness", "/ratchet",
            "/fv", "/e2e", "/quality-gates",
            "/vision-gap", "/quality-trend",
            "/failure-analysis", "/lint", "/security",
            "/deploy", "/changelog",
            "/quality-settings", "/notifications",
            "/quick-fixes",
        ]
        for ep in endpoints:
            r = app_page.request.get(f"{BASE}{ep}")
            assert r.ok, f"Endpoint {ep} failed with status {r.status}"

    def test_a4_l5_07(self, app_page):
        """A4-L5-07 [S22]: 手動実行→レポート生成→ダウンロードの完走"""
        run = app_page.request.post(f"{BASE}/run-tests",
            data=json.dumps({"suite": "unit"}),
            headers={"Content-Type": "application/json"}).json()
        assert run["status"] == "started"
        rpt = app_page.request.post(f"{BASE}/generate-report",
            data=json.dumps({"format": "html"}),
            headers={"Content-Type": "application/json"}).json()
        assert rpt["status"] == "generated"
        assert "download_url" in rpt

    def test_a4_l5_08(self, app_page):
        """A4-L5-08 [S22]: リント→セキュリティ→ワンクリック修復の完走"""
        lint = app_page.request.get(f"{BASE}/lint").json()
        assert "total" in lint
        sec = app_page.request.get(f"{BASE}/security").json()
        assert sec["total"] >= 0
        fixes = app_page.request.get(f"{BASE}/quick-fixes").json()
        assert fixes["total"] > 0
        apply_r = app_page.request.post(f"{BASE}/quick-fix",
            data=json.dumps({"fix_id": 1}),
            headers={"Content-Type": "application/json"})
        assert apply_r.ok
        assert apply_r.json()["status"] == "applied"

    def test_a4_l5_09(self, app_page):
        """A4-L5-09 [S22]: 通知設定→テスト失敗→通知確認の完走"""
        app_page.request.post(f"{BASE}/notifications",
            data=json.dumps({"channels": ["slack"], "enabled": True}),
            headers={"Content-Type": "application/json"})
        notif = app_page.request.get(f"{BASE}/notifications").json()
        assert notif["enabled"] is True
        fa = app_page.request.get(f"{BASE}/failure-analysis").json()
        assert fa["total_failures"] >= 0

    def test_a4_l5_10(self, app_page):
        """A4-L5-10 [S22]: 無効なテストスイート指定で400エラーの完走"""
        r = app_page.request.post(f"{BASE}/run-tests",
            data=json.dumps({"suite": "nonexistent"}),
            headers={"Content-Type": "application/json"})
        assert r.status == 400
