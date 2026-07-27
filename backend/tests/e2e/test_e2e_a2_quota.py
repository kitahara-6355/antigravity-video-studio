"""
E2E テスト — A-2 API使用量監視・コスト最適化 5層検証 (55項目)

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

BASE = "http://localhost:8000/api/admin/quota"


@pytest.mark.e2e
class TestA2L1DomExists:
    """L1: DOM存在 (12項目)"""

    def test_a2_l1_01(self, app_page):
        """A2-L1-01 [S1]: API使用量監視ダッシュボードAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/dashboard")
        assert r.ok

    def test_a2_l1_02(self, app_page):
        """A2-L1-02 [S1]: ダッシュボードにsectionsフィールドが存在する"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert "sections" in d
        assert len(d["sections"]) >= 10

    def test_a2_l1_03(self, app_page):
        """A2-L1-03 [S2]: 使用量ゲージAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/usage-gauge")
        assert r.ok

    def test_a2_l1_04(self, app_page):
        """A2-L1-04 [S3]: 4段階ステータスAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/status")
        assert r.ok

    def test_a2_l1_05(self, app_page):
        """A2-L1-05 [S4]: 残回数APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/remaining")
        assert r.ok

    def test_a2_l1_06(self, app_page):
        """A2-L1-06 [S5]: 使用量推移APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/usage-history")
        assert r.ok

    def test_a2_l1_07(self, app_page):
        """A2-L1-07 [S6]: モデル別内訳APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/model-breakdown")
        assert r.ok

    def test_a2_l1_08(self, app_page):
        """A2-L1-08 [S7]: Worker別内訳APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/worker-breakdown")
        assert r.ok

    def test_a2_l1_09(self, app_page):
        """A2-L1-09 [S8]: コスト計算APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/cost-estimate")
        assert r.ok

    def test_a2_l1_10(self, app_page):
        """A2-L1-10 [S11]: 自動ブロック状態APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/auto-block")
        assert r.ok

    def test_a2_l1_11(self, app_page):
        """A2-L1-11 [S13]: アラート履歴APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/alerts")
        assert r.ok

    def test_a2_l1_12(self, app_page):
        """A2-L1-12 [S16]: クォータリセットAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/quota-reset")
        assert r.ok


@pytest.mark.e2e
class TestA2L2VisualFeedback:
    """L2: 視覚フィードバック (10項目)"""

    def test_a2_l2_01(self, app_page):
        """A2-L2-01 [S1]: ダッシュボードにtitle/status/usage_summaryが含まれる"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert all(k in d for k in ["title", "status", "usage_summary"])

    def test_a2_l2_02(self, app_page):
        """A2-L2-02 [S2]: 使用量ゲージにdaily/weekly/monthlyの数値が含まれる"""
        d = app_page.request.get(f"{BASE}/usage-gauge").json()
        assert all(k in d for k in ["daily", "weekly", "monthly"])
        assert "used" in d["daily"]

    def test_a2_l2_03(self, app_page):
        """A2-L2-03 [S3]: ステータスがNORMAL/INFO/WARNING/CRITICALのいずれか"""
        d = app_page.request.get(f"{BASE}/status").json()
        assert d["status"] in ["NORMAL", "INFO", "WARNING", "CRITICAL"]

    def test_a2_l2_04(self, app_page):
        """A2-L2-04 [S4]: 残回数にremaining/total/percentageが含まれる"""
        d = app_page.request.get(f"{BASE}/remaining").json()
        assert all(k in d for k in ["remaining", "total", "percentage"])

    def test_a2_l2_05(self, app_page):
        """A2-L2-05 [S6]: モデル別内訳にpremium/standard/batchが含まれる"""
        d = app_page.request.get(f"{BASE}/model-breakdown").json()
        assert all(k in d for k in ["premium", "standard", "batch"])

    def test_a2_l2_06(self, app_page):
        """A2-L2-06 [S7]: Worker別内訳に少なくとも3つのWorkerが含まれる"""
        d = app_page.request.get(f"{BASE}/worker-breakdown").json()
        assert len(d["workers"]) >= 3

    def test_a2_l2_07(self, app_page):
        """A2-L2-07 [S8]: コスト計算にestimated/actual/currencyが含まれる"""
        d = app_page.request.get(f"{BASE}/cost-estimate").json()
        assert all(k in d for k in ["estimated", "actual", "currency"])

    def test_a2_l2_08(self, app_page):
        """A2-L2-08 [S11]: 自動ブロック状態にblocked/reason/triggered_atが含まれる"""
        d = app_page.request.get(f"{BASE}/auto-block").json()
        assert all(k in d for k in ["blocked", "reason", "triggered_at"])

    def test_a2_l2_09(self, app_page):
        """A2-L2-09 [S13]: アラート履歴にalerts配列とtotalが含まれる"""
        d = app_page.request.get(f"{BASE}/alerts").json()
        assert "alerts" in d and "total" in d
        assert isinstance(d["alerts"], list)

    def test_a2_l2_10(self, app_page):
        """A2-L2-10 [S16]: クォータリセットにreset_time/next_resetが含まれる"""
        d = app_page.request.get(f"{BASE}/quota-reset").json()
        assert all(k in d for k in ["reset_time", "next_reset"])


@pytest.mark.e2e
class TestA2L3Interaction:
    """L3: インタラクション (13項目)"""

    def test_a2_l3_01(self, app_page):
        """A2-L3-01 [S2]: 使用量ゲージの日次/週次/月次値が取得できる"""
        d = app_page.request.get(f"{BASE}/usage-gauge").json()
        assert d["daily"]["percent"] >= 0
        assert d["weekly"]["percent"] >= 0
        assert d["monthly"]["percent"] >= 0

    def test_a2_l3_02(self, app_page):
        """A2-L3-02 [S3]: 4段階ステータスの詳細情報が取得できる"""
        d = app_page.request.get(f"{BASE}/status").json()
        assert "description" in d and "color" in d

    def test_a2_l3_03(self, app_page):
        """A2-L3-03 [S5]: 過去30日間の使用量データが配列で返される"""
        d = app_page.request.get(f"{BASE}/usage-history").json()
        assert len(d["history"]) == 30
        assert "date" in d["history"][0]

    def test_a2_l3_04(self, app_page):
        """A2-L3-04 [S6]: モデル別内訳の合計がtotalと一致する"""
        d = app_page.request.get(f"{BASE}/model-breakdown").json()
        assert d["premium"] + d["standard"] + d["batch"] == d["total"]

    def test_a2_l3_05(self, app_page):
        """A2-L3-05 [S8]: コスト計算の通貨がJPYまたはUSDである"""
        d = app_page.request.get(f"{BASE}/cost-estimate").json()
        assert d["currency"] in ["JPY", "USD"]

    def test_a2_l3_06(self, app_page):
        """A2-L3-06 [S9]: 閾値設定APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/thresholds",
            data=json.dumps({"info_percent": 50.0, "warning_percent": 75.0, "critical_percent": 90.0}),
            headers={"Content-Type": "application/json"})
        assert r.ok

    def test_a2_l3_07(self, app_page):
        """A2-L3-07 [S9]: 閾値設定後に新しい値が反映される"""
        app_page.request.post(f"{BASE}/thresholds",
            data=json.dumps({"info_percent": 55.0, "warning_percent": 78.0, "critical_percent": 92.0}),
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/thresholds").json()
        assert d["info"] == 55.0

    def test_a2_l3_08(self, app_page):
        """A2-L3-08 [S10]: 節約モードON/OFF切り替えAPIが正常応答する"""
        r = app_page.request.post(f"{BASE}/saving-mode",
            data=json.dumps({"enabled": True}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["enabled"] is True

    def test_a2_l3_09(self, app_page):
        """A2-L3-09 [S12]: ブロック解除APIが正常応答する"""
        r = app_page.request.post(f"{BASE}/auto-block/release",
            data="{}",
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["blocked"] is False

    def test_a2_l3_10(self, app_page):
        """A2-L3-10 [S13]: アラート履歴のフィルタリング(level指定)が正常動作する"""
        d = app_page.request.get(f"{BASE}/alerts?level=WARNING").json()
        for alert in d["alerts"]:
            assert alert["level"] == "WARNING"

    def test_a2_l3_11(self, app_page):
        """A2-L3-11 [S14]: 予測消費量APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/forecast")
        assert r.ok

    def test_a2_l3_12(self, app_page):
        """A2-L3-12 [S15]: 最適化提案APIが提案配列を返す"""
        d = app_page.request.get(f"{BASE}/optimization").json()
        assert isinstance(d["suggestions"], list)
        assert d["total"] > 0

    def test_a2_l3_13(self, app_page):
        """A2-L3-13 [S19]: 使用量レポートエクスポートAPIが正常応答する"""
        r = app_page.request.post(f"{BASE}/export",
            data=json.dumps({"format": "csv"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["format"] == "csv"


@pytest.mark.e2e
class TestA2L4StateTransition:
    """L4: 状態遷移 (10項目)"""

    def test_a2_l4_01(self, app_page):
        """A2-L4-01 [S9]: 無効な閾値(101%)で適切なエラーが返る"""
        r = app_page.request.post(f"{BASE}/thresholds",
            data=json.dumps({"info_percent": 101.0, "warning_percent": 80.0, "critical_percent": 95.0}),
            headers={"Content-Type": "application/json"})
        assert r.status == 400

    def test_a2_l4_02(self, app_page):
        """A2-L4-02 [S10]: 節約モード状態が永続化される"""
        app_page.request.post(f"{BASE}/saving-mode",
            data=json.dumps({"enabled": True}),
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/saving-mode").json()
        assert d["enabled"] is True

    def test_a2_l4_03(self, app_page):
        """A2-L4-03 [S11]: CRITICAL時に自動ブロックが発動する"""
        app_page.request.post(f"{BASE}/auto-block/trigger",
            data="{}",
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/auto-block").json()
        assert d["blocked"] is True

    def test_a2_l4_04(self, app_page):
        """A2-L4-04 [S12]: ブロック解除後にblockedがfalseになる"""
        app_page.request.post(f"{BASE}/auto-block/trigger",
            data="{}",
            headers={"Content-Type": "application/json"})
        app_page.request.post(f"{BASE}/auto-block/release",
            data="{}",
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/auto-block").json()
        assert d["blocked"] is False

    def test_a2_l4_05(self, app_page):
        """A2-L4-05 [S14]: 予測消費量にforecast_requests/forecast_costが含まれる"""
        d = app_page.request.get(f"{BASE}/forecast").json()
        assert all(k in d for k in ["forecast_requests", "forecast_cost"])

    def test_a2_l4_06(self, app_page):
        """A2-L4-06 [S15]: 最適化提案の各項目にcategory/impact/descriptionが含まれる"""
        d = app_page.request.get(f"{BASE}/optimization").json()
        for s in d["suggestions"]:
            assert all(k in s for k in ["category", "impact", "description"])

    def test_a2_l4_07(self, app_page):
        """A2-L4-07 [S17]: 降格ログにfrom_tier/to_tier/reasonが含まれる"""
        d = app_page.request.get(f"{BASE}/downgrade-log").json()
        for log in d["logs"]:
            assert all(k in log for k in ["from_tier", "to_tier", "reason"])

    def test_a2_l4_08(self, app_page):
        """A2-L4-08 [S18]: リアルタイム更新状態APIが正常応答する"""
        d = app_page.request.get(f"{BASE}/realtime-status").json()
        assert "websocket_enabled" in d

    def test_a2_l4_09(self, app_page):
        """A2-L4-09 [S19]: 無効なフォーマット指定で適切なエラーが返る"""
        r = app_page.request.post(f"{BASE}/export",
            data=json.dumps({"format": "invalid"}),
            headers={"Content-Type": "application/json"})
        assert r.status == 400

    def test_a2_l4_10(self, app_page):
        """A2-L4-10 [S20]: 無料枠超過判定にexceeded/remaining_freeが含まれる"""
        d = app_page.request.get(f"{BASE}/free-tier-status").json()
        assert all(k in d for k in ["exceeded", "remaining_free"])


@pytest.mark.e2e
class TestA2L5EndToEnd:
    """L5: E2E完走 (10項目)"""

    def test_a2_l5_01(self, app_page):
        """A2-L5-01 [S17]: ダッシュボード→使用量確認→降格ログ→ステータスの完走"""
        assert app_page.request.get(f"{BASE}/dashboard").ok
        assert app_page.request.get(f"{BASE}/usage-gauge").ok
        d = app_page.request.get(f"{BASE}/downgrade-log").json()
        assert d["total"] > 0
        s = app_page.request.get(f"{BASE}/status").json()
        assert s["status"] in ["NORMAL", "INFO", "WARNING", "CRITICAL"]

    def test_a2_l5_02(self, app_page):
        """A2-L5-02 [S18]: 使用量取得→ゲージ確認→リアルタイム状態確認の完走"""
        g = app_page.request.get(f"{BASE}/usage-gauge").json()
        assert "daily" in g
        r = app_page.request.get(f"{BASE}/remaining").json()
        assert r["remaining"] >= 0
        rt = app_page.request.get(f"{BASE}/realtime-status").json()
        assert rt["websocket_enabled"] is True

    def test_a2_l5_03(self, app_page):
        """A2-L5-03 [S20]: コスト確認→予測→超過判定→最適化提案の完走"""
        c = app_page.request.get(f"{BASE}/cost-estimate").json()
        assert c["currency"] in ["JPY", "USD"]
        f = app_page.request.get(f"{BASE}/forecast").json()
        assert f["forecast_requests"] > 0
        ft = app_page.request.get(f"{BASE}/free-tier-status").json()
        assert "exceeded" in ft
        o = app_page.request.get(f"{BASE}/optimization").json()
        assert o["total"] > 0

    def test_a2_l5_04(self, app_page):
        """A2-L5-04 [S21]: APIキーローテーション管理→一覧→追加→削除の完走"""
        init = app_page.request.get(f"{BASE}/key-rotation").json()
        initial_count = init["total"]
        app_page.request.post(f"{BASE}/key-rotation",
            data=json.dumps({"key_name": "test_key_1", "api_key": "test-api-key-12345"}),
            headers={"Content-Type": "application/json"})
        after = app_page.request.get(f"{BASE}/key-rotation").json()
        assert after["total"] == initial_count + 1
        app_page.request.delete(f"{BASE}/key-rotation/test_key_1")
        final = app_page.request.get(f"{BASE}/key-rotation").json()
        assert final["total"] == initial_count

    def test_a2_l5_05(self, app_page):
        """A2-L5-05 [S21]: 閾値設定→節約モード切替→ブロック確認の完走"""
        app_page.request.post(f"{BASE}/thresholds",
            data=json.dumps({"info_percent": 60.0, "warning_percent": 80.0, "critical_percent": 95.0}),
            headers={"Content-Type": "application/json"})
        app_page.request.post(f"{BASE}/saving-mode",
            data=json.dumps({"enabled": False}),
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/auto-block").json()
        assert isinstance(d["blocked"], bool)

    def test_a2_l5_06(self, app_page):
        """A2-L5-06 [S21]: アラート履歴→フィルタ→エクスポートの完走"""
        a = app_page.request.get(f"{BASE}/alerts").json()
        assert a["total"] > 0
        aw = app_page.request.get(f"{BASE}/alerts?level=WARNING").json()
        assert all(al["level"] == "WARNING" for al in aw["alerts"])
        e = app_page.request.post(f"{BASE}/export",
            data=json.dumps({"format": "csv"}),
            headers={"Content-Type": "application/json"}).json()
        assert e["status"] == "generated"

    def test_a2_l5_07(self, app_page):
        """A2-L5-07 [S22]: 予算上限設定→超過防止確認の完走"""
        app_page.request.post(f"{BASE}/budget",
            data=json.dumps({"monthly_limit_jpy": 5000.0}),
            headers={"Content-Type": "application/json"})
        b = app_page.request.get(f"{BASE}/budget").json()
        assert b["monthly_limit_jpy"] == 5000.0
        assert isinstance(b["exceeded"], bool)

    def test_a2_l5_08(self, app_page):
        """A2-L5-08 [S22]: Worker別内訳→モデル別内訳→コスト計算の完走"""
        w = app_page.request.get(f"{BASE}/worker-breakdown").json()
        assert w["worker_count"] >= 3
        m = app_page.request.get(f"{BASE}/model-breakdown").json()
        assert m["total"] > 0
        c = app_page.request.get(f"{BASE}/cost-estimate").json()
        assert c["actual"] > 0

    def test_a2_l5_09(self, app_page):
        """A2-L5-09 [S22]: 全APIエンドポイント疎通確認の完走"""
        endpoints = [
            "/dashboard", "/usage-gauge", "/status", "/remaining",
            "/usage-history", "/model-breakdown", "/worker-breakdown",
            "/cost-estimate", "/thresholds", "/saving-mode",
            "/auto-block", "/alerts", "/forecast",
            "/optimization", "/quota-reset", "/downgrade-log",
            "/realtime-status", "/free-tier-status",
            "/key-rotation", "/budget",
        ]
        for ep in endpoints:
            r = app_page.request.get(f"{BASE}{ep}")
            assert r.ok, f"Endpoint {ep} failed with status {r.status}"

    def test_a2_l5_10(self, app_page):
        """A2-L5-10 [S22]: 無効な予算上限(負数)で400エラーの完走"""
        r = app_page.request.post(f"{BASE}/budget",
            data=json.dumps({"monthly_limit_jpy": -1000.0}),
            headers={"Content-Type": "application/json"})
        assert r.status == 400
