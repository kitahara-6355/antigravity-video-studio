"""
E2E テスト — A-5 異常検知・自動復旧 5層検証 (55項目)

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

BASE = "http://localhost:8000/api/admin/incident"


@pytest.mark.e2e
class TestA5L1DomExists:
    """L1: DOM存在 (12項目)"""

    def test_a5_l1_01(self, app_page):
        """A5-L1-01 [S1]: 異常検知・自動復旧ダッシュボードAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/dashboard")
        assert r.ok

    def test_a5_l1_02(self, app_page):
        """A5-L1-02 [S1]: ダッシュボードにsectionsフィールドが存在する"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert "sections" in d
        assert len(d["sections"]) >= 10

    def test_a5_l1_03(self, app_page):
        """A5-L1-03 [S2]: API枠超過検知APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/quota-breach")
        assert r.ok

    def test_a5_l1_04(self, app_page):
        """A5-L1-04 [S3]: パイプライン障害検知APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/pipeline-failures")
        assert r.ok

    def test_a5_l1_05(self, app_page):
        """A5-L1-05 [S4]: 品質低下検知APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/quality-degradation")
        assert r.ok

    def test_a5_l1_06(self, app_page):
        """A5-L1-06 [S5]: 自動リトライ状態APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/auto-retry")
        assert r.ok

    def test_a5_l1_07(self, app_page):
        """A5-L1-07 [S7]: アラート一覧APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/alerts")
        assert r.ok

    def test_a5_l1_08(self, app_page):
        """A5-L1-08 [S8]: インシデント履歴APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/incidents")
        assert r.ok

    def test_a5_l1_09(self, app_page):
        """A5-L1-09 [S11]: SLA監視APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/sla")
        assert r.ok

    def test_a5_l1_10(self, app_page):
        """A5-L1-10 [S15]: パフォーマンス監視APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/performance")
        assert r.ok

    def test_a5_l1_11(self, app_page):
        """A5-L1-11 [S16]: Worker障害分離APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/worker-isolation")
        assert r.ok

    def test_a5_l1_12(self, app_page):
        """A5-L1-12 [S20]: ダウンタイム計測APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/downtime")
        assert r.ok


@pytest.mark.e2e
class TestA5L2VisualFeedback:
    """L2: 視覚フィードバック (10項目)"""

    def test_a5_l2_01(self, app_page):
        """A5-L2-01 [S1]: ダッシュボードにtitle/status/summaryが含まれる"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert all(k in d for k in ["title", "status", "summary"])

    def test_a5_l2_02(self, app_page):
        """A5-L2-02 [S2]: API枠超過にlevel/message/thresholdが含まれる"""
        d = app_page.request.get(f"{BASE}/quota-breach").json()
        assert all(k in d for k in ["level", "message", "threshold"])

    def test_a5_l2_03(self, app_page):
        """A5-L2-03 [S3]: パイプライン障害にfailures配列とtotalが含まれる"""
        d = app_page.request.get(f"{BASE}/pipeline-failures").json()
        assert "failures" in d and "total" in d
        assert isinstance(d["failures"], list)

    def test_a5_l2_04(self, app_page):
        """A5-L2-04 [S4]: 品質低下にcurrent_score/threshold/degraded_workersが含まれる"""
        d = app_page.request.get(f"{BASE}/quality-degradation").json()
        assert all(k in d for k in ["current_score", "threshold", "degraded_workers"])

    def test_a5_l2_05(self, app_page):
        """A5-L2-05 [S7]: アラートにalerts配列とactive_countが含まれる"""
        d = app_page.request.get(f"{BASE}/alerts").json()
        assert "alerts" in d and "active_count" in d
        assert isinstance(d["alerts"], list)

    def test_a5_l2_06(self, app_page):
        """A5-L2-06 [S8]: インシデント履歴にincidents配列とtotalが含まれる"""
        d = app_page.request.get(f"{BASE}/incidents").json()
        assert "incidents" in d and "total" in d
        assert isinstance(d["incidents"], list)

    def test_a5_l2_07(self, app_page):
        """A5-L2-07 [S11]: SLA監視にuptime_pct/target_pct/mttrが含まれる"""
        d = app_page.request.get(f"{BASE}/sla").json()
        assert all(k in d for k in ["uptime_pct", "target_pct", "mttr_minutes"])

    def test_a5_l2_08(self, app_page):
        """A5-L2-08 [S15]: パフォーマンスにcpu_pct/memory_pct/disk_pctが含まれる"""
        d = app_page.request.get(f"{BASE}/performance").json()
        assert all(k in d for k in ["cpu_pct", "memory_pct", "disk_pct"])

    def test_a5_l2_09(self, app_page):
        """A5-L2-09 [S16]: Worker分離にworkers配列と各Worker状態が含まれる"""
        d = app_page.request.get(f"{BASE}/worker-isolation").json()
        assert "workers" in d
        assert isinstance(d["workers"], list)
        assert len(d["workers"]) >= 7

    def test_a5_l2_10(self, app_page):
        """A5-L2-10 [S20]: ダウンタイムにtotal_minutes/mttr_minutes/incidentsが含まれる"""
        d = app_page.request.get(f"{BASE}/downtime").json()
        assert all(k in d for k in ["total_minutes", "mttr_minutes", "incidents"])


@pytest.mark.e2e
class TestA5L3Interaction:
    """L3: インタラクション (13項目)"""

    def test_a5_l3_01(self, app_page):
        """A5-L3-01 [S2]: API枠超過のlevelがNORMAL/WARNING/CRITICALのいずれかである"""
        d = app_page.request.get(f"{BASE}/quota-breach").json()
        assert d["level"] in ["NORMAL", "WARNING", "CRITICAL"]

    def test_a5_l3_02(self, app_page):
        """A5-L3-02 [S3]: パイプライン障害の各failureにworker/error/timestampが含まれる"""
        d = app_page.request.get(f"{BASE}/pipeline-failures").json()
        for f in d["failures"]:
            assert all(k in f for k in ["worker", "error", "timestamp"])

    def test_a5_l3_03(self, app_page):
        """A5-L3-03 [S5]: 自動リトライにretry_count/max_retries/statusが含まれる"""
        d = app_page.request.get(f"{BASE}/auto-retry").json()
        assert all(k in d for k in ["retry_count", "max_retries", "status"])

    def test_a5_l3_04(self, app_page):
        """A5-L3-04 [S5]: リトライ実行APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/retry",
            data=json.dumps({"session_id": "test_session"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "retry_started"

    def test_a5_l3_05(self, app_page):
        """A5-L3-05 [S6]: 手動介入APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/manual-intervention",
            data=json.dumps({"incident_id": "INC-001", "action": "restart"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "intervention_applied"

    def test_a5_l3_06(self, app_page):
        """A5-L3-06 [S7]: アラートのack(確認)APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/alert-ack",
            data=json.dumps({"alert_id": 1}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "acknowledged"

    def test_a5_l3_07(self, app_page):
        """A5-L3-07 [S8]: インシデント詳細APIがincident_idで正常応答する"""
        r = app_page.request.get(f"{BASE}/incidents/INC-001")
        assert r.ok
        d = r.json()
        assert d["id"] == "INC-001"

    def test_a5_l3_08(self, app_page):
        """A5-L3-08 [S9]: 根本原因分析APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/rca/INC-001")
        assert r.ok
        d = r.json()
        assert "root_cause" in d

    def test_a5_l3_09(self, app_page):
        """A5-L3-09 [S10]: 復旧手順ガイドAPIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/recovery-guide")
        assert r.ok

    def test_a5_l3_10(self, app_page):
        """A5-L3-10 [S11]: SLAのuptime_pctが0-100の範囲で返される"""
        d = app_page.request.get(f"{BASE}/sla").json()
        assert 0 <= d["uptime_pct"] <= 100

    def test_a5_l3_11(self, app_page):
        """A5-L3-11 [S12]: 障害レポート生成APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/incident-report",
            data=json.dumps({"incident_id": "INC-001", "format": "pdf"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "generated"

    def test_a5_l3_12(self, app_page):
        """A5-L3-12 [S13]: エスカレーションAPIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/escalate",
            data=json.dumps({"incident_id": "INC-001", "channels": ["slack"]}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "escalated"

    def test_a5_l3_13(self, app_page):
        """A5-L3-13 [S14]: 復旧確認APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/recovery-check")
        assert r.ok


@pytest.mark.e2e
class TestA5L4StateTransition:
    """L4: 状態遷移 (10項目)"""

    def test_a5_l4_01(self, app_page):
        """A5-L4-01 [S6]: 手動介入の結果にstatus/action_taken/timestampが含まれる"""
        r = app_page.request.post(f"{BASE}/manual-intervention",
            data=json.dumps({"incident_id": "INC-001", "action": "skip"}),
            headers={"Content-Type": "application/json"})
        d = r.json()
        assert all(k in d for k in ["status", "action_taken", "timestamp"])

    def test_a5_l4_02(self, app_page):
        """A5-L4-02 [S9]: RCAにroot_cause/category/recommendationsが含まれる"""
        d = app_page.request.get(f"{BASE}/rca/INC-001").json()
        assert all(k in d for k in ["root_cause", "category", "recommendations"])
        assert isinstance(d["recommendations"], list)

    def test_a5_l4_03(self, app_page):
        """A5-L4-03 [S10]: 復旧手順にsteps配列とincident_typeが含まれる"""
        d = app_page.request.get(f"{BASE}/recovery-guide").json()
        assert "steps" in d and "incident_type" in d
        assert isinstance(d["steps"], list)
        assert len(d["steps"]) >= 3

    def test_a5_l4_04(self, app_page):
        """A5-L4-04 [S12]: 障害レポート生成後にdownload_urlが含まれる"""
        r = app_page.request.post(f"{BASE}/incident-report",
            data=json.dumps({"incident_id": "INC-001", "format": "html"}),
            headers={"Content-Type": "application/json"})
        d = r.json()
        assert "download_url" in d
        assert d["download_url"].endswith(".html")

    def test_a5_l4_05(self, app_page):
        """A5-L4-05 [S13]: エスカレーション後にnotified_channels配列が含まれる"""
        r = app_page.request.post(f"{BASE}/escalate",
            data=json.dumps({"incident_id": "INC-002", "channels": ["slack", "discord"]}),
            headers={"Content-Type": "application/json"})
        d = r.json()
        assert "notified_channels" in d
        assert isinstance(d["notified_channels"], list)
        assert "slack" in d["notified_channels"]

    def test_a5_l4_06(self, app_page):
        """A5-L4-06 [S14]: 復旧確認にchecklist配列とall_passedが含まれる"""
        d = app_page.request.get(f"{BASE}/recovery-check").json()
        assert "checklist" in d and "all_passed" in d
        assert isinstance(d["checklist"], list)
        assert len(d["checklist"]) >= 3

    def test_a5_l4_07(self, app_page):
        """A5-L4-07 [S16]: Worker分離で各Workerにstatus/isolatedフラグが含まれる"""
        d = app_page.request.get(f"{BASE}/worker-isolation").json()
        for w in d["workers"]:
            assert all(k in w for k in ["name", "status", "isolated"])

    def test_a5_l4_08(self, app_page):
        """A5-L4-08 [S17]: セルフヒーリングにtrigger/action/resultが含まれる"""
        d = app_page.request.get(f"{BASE}/self-healing").json()
        assert "events" in d
        for ev in d["events"]:
            assert all(k in ev for k in ["trigger", "action", "result"])

    def test_a5_l4_09(self, app_page):
        """A5-L4-09 [S18]: 障害パターンにpatterns配列とtotal_learnedが含まれる"""
        d = app_page.request.get(f"{BASE}/patterns").json()
        assert "patterns" in d and "total_learned" in d
        assert isinstance(d["patterns"], list)

    def test_a5_l4_10(self, app_page):
        """A5-L4-10 [S19]: 予防保守提案にsuggestions配列とprioritized_countが含まれる"""
        d = app_page.request.get(f"{BASE}/preventive").json()
        assert "suggestions" in d and "prioritized_count" in d
        assert isinstance(d["suggestions"], list)


@pytest.mark.e2e
class TestA5L5EndToEnd:
    """L5: E2E完走 (10項目)"""

    def test_a5_l5_01(self, app_page):
        """A5-L5-01 [S17]: ダッシュボード→障害検知→自動リトライ→復旧確認の完走"""
        assert app_page.request.get(f"{BASE}/dashboard").ok
        pf = app_page.request.get(f"{BASE}/pipeline-failures").json()
        assert pf["total"] >= 0
        ar = app_page.request.get(f"{BASE}/auto-retry").json()
        assert ar["max_retries"] >= 1
        rc = app_page.request.get(f"{BASE}/recovery-check").json()
        assert "all_passed" in rc

    def test_a5_l5_02(self, app_page):
        """A5-L5-02 [S17]: 障害検知→セルフヒーリング→Worker分離→復旧の完走"""
        pf = app_page.request.get(f"{BASE}/pipeline-failures").json()
        assert isinstance(pf["failures"], list)
        sh = app_page.request.get(f"{BASE}/self-healing").json()
        assert sh["total"] >= 0
        wi = app_page.request.get(f"{BASE}/worker-isolation").json()
        assert wi["total_workers"] >= 7
        rc = app_page.request.get(f"{BASE}/recovery-check").json()
        assert isinstance(rc["checklist"], list)

    def test_a5_l5_03(self, app_page):
        """A5-L5-03 [S18]: インシデント履歴→RCA→障害パターン学習の完走"""
        inc = app_page.request.get(f"{BASE}/incidents").json()
        assert inc["total"] >= 1
        rca = app_page.request.get(f"{BASE}/rca/{inc['incidents'][0]['id']}").json()
        assert "root_cause" in rca
        pat = app_page.request.get(f"{BASE}/patterns").json()
        assert pat["total_learned"] >= 1

    def test_a5_l5_04(self, app_page):
        """A5-L5-04 [S19]: パフォーマンス監視→品質低下検知→予防保守提案の完走"""
        perf = app_page.request.get(f"{BASE}/performance").json()
        assert perf["cpu_pct"] >= 0
        qd = app_page.request.get(f"{BASE}/quality-degradation").json()
        assert qd["threshold"] == 90
        prev = app_page.request.get(f"{BASE}/preventive").json()
        assert prev["prioritized_count"] >= 1

    def test_a5_l5_05(self, app_page):
        """A5-L5-05 [S20]: SLA監視→ダウンタイム計測→障害レポートの完走"""
        sla = app_page.request.get(f"{BASE}/sla").json()
        assert sla["uptime_pct"] > 0
        dt = app_page.request.get(f"{BASE}/downtime").json()
        assert dt["total_minutes"] >= 0
        rpt = app_page.request.post(f"{BASE}/incident-report",
            data=json.dumps({"incident_id": "INC-001", "format": "pdf"}),
            headers={"Content-Type": "application/json"}).json()
        assert rpt["status"] == "generated"

    def test_a5_l5_06(self, app_page):
        """A5-L5-06 [S21]: 全GETエンドポイント疎通確認の完走"""
        endpoints = [
            "/dashboard", "/quota-breach", "/pipeline-failures",
            "/quality-degradation", "/auto-retry", "/alerts",
            "/incidents", "/recovery-guide", "/sla",
            "/performance", "/worker-isolation", "/self-healing",
            "/patterns", "/preventive", "/downtime",
            "/status-page", "/recovery-check",
        ]
        for ep in endpoints:
            r = app_page.request.get(f"{BASE}{ep}")
            assert r.ok, f"Endpoint {ep} failed with status {r.status}"

    def test_a5_l5_07(self, app_page):
        """A5-L5-07 [S21]: アラート→エスカレーション→ステータスページ更新の完走"""
        alerts = app_page.request.get(f"{BASE}/alerts").json()
        assert alerts["active_count"] >= 0
        esc = app_page.request.post(f"{BASE}/escalate",
            data=json.dumps({"incident_id": "INC-001", "channels": ["slack"]}),
            headers={"Content-Type": "application/json"}).json()
        assert esc["status"] == "escalated"
        sp = app_page.request.get(f"{BASE}/status-page").json()
        assert "overall_status" in sp

    def test_a5_l5_08(self, app_page):
        """A5-L5-08 [S21]: 手動介入→復旧確認→障害クローズの完走"""
        mi = app_page.request.post(f"{BASE}/manual-intervention",
            data=json.dumps({"incident_id": "INC-003", "action": "restart"}),
            headers={"Content-Type": "application/json"}).json()
        assert mi["status"] == "intervention_applied"
        rc = app_page.request.get(f"{BASE}/recovery-check").json()
        assert isinstance(rc["checklist"], list)
        inc = app_page.request.get(f"{BASE}/incidents/INC-003").json()
        assert inc["id"] == "INC-003"

    def test_a5_l5_09(self, app_page):
        """A5-L5-09 [S22]: 障害対応ログのタイムライン表示が正常応答する"""
        r = app_page.request.get(f"{BASE}/timeline/INC-001")
        assert r.ok
        d = r.json()
        assert "timeline" in d
        assert d["total_events"] >= 1

    def test_a5_l5_10(self, app_page):
        """A5-L5-10 [S22]: 無効なincident_id指定で404エラーの完走"""
        r = app_page.request.get(f"{BASE}/incidents/NONEXISTENT")
        assert r.status == 404
        r2 = app_page.request.get(f"{BASE}/rca/NONEXISTENT")
        assert r2.status == 404
        r3 = app_page.request.get(f"{BASE}/timeline/NONEXISTENT")
        assert r3.status == 404
