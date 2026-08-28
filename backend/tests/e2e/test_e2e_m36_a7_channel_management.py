"""
E2E テスト — A-7 チャンネル主ダッシュボード管理 5層検証 (55項目)

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

BASE = "http://localhost:8000/api/admin/channel"


@pytest.mark.e2e
class TestA7L1DomExists:
    """L1: DOM存在 (12項目)"""

    def test_a7_l1_01(self, app_page):
        """A7-L1-01 [S1]: チャンネル管理ダッシュボードAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/dashboard")
        assert r.ok

    def test_a7_l1_02(self, app_page):
        """A7-L1-02 [S1]: ダッシュボードにsectionsフィールドが存在する"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert "sections" in d
        assert len(d["sections"]) >= 10

    def test_a7_l1_03(self, app_page):
        """A7-L1-03 [S2]: チャンネル一覧APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/channels")
        assert r.ok

    def test_a7_l1_04(self, app_page):
        """A7-L1-04 [S3]: チャンネル詳細APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/channels/ch-001")
        assert r.ok

    def test_a7_l1_05(self, app_page):
        """A7-L1-05 [S4]: 効果サマリーAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/effect-summary")
        assert r.ok

    def test_a7_l1_06(self, app_page):
        """A7-L1-06 [S5]: 制作効率APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/production-efficiency")
        assert r.ok

    def test_a7_l1_07(self, app_page):
        """A7-L1-07 [S8]: 維持率改善APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/retention-improvement")
        assert r.ok

    def test_a7_l1_08(self, app_page):
        """A7-L1-08 [S11]: 最適化推奨APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/optimization-recommendations")
        assert r.ok

    def test_a7_l1_09(self, app_page):
        """A7-L1-09 [S13]: 投稿スケジュールAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/post-schedule")
        assert r.ok

    def test_a7_l1_10(self, app_page):
        """A7-L1-10 [S14]: 投稿ペース分析APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/posting-pace")
        assert r.ok

    def test_a7_l1_11(self, app_page):
        """A7-L1-11 [S21]: 権限管理APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/permissions")
        assert r.ok

    def test_a7_l1_12(self, app_page):
        """A7-L1-12 [S22]: YouTube API連携設定APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/youtube-connection")
        assert r.ok


@pytest.mark.e2e
class TestA7L2VisualFeedback:
    """L2: 視覚フィードバック (10項目)"""

    def test_a7_l2_01(self, app_page):
        """A7-L2-01 [S1]: ダッシュボードにtitle/status/summaryが含まれる"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert all(k in d for k in ["title", "status", "summary"])

    def test_a7_l2_02(self, app_page):
        """A7-L2-02 [S2]: チャンネル一覧にchannels配列とtotalが含まれる"""
        d = app_page.request.get(f"{BASE}/channels").json()
        assert "channels" in d and "total" in d
        assert isinstance(d["channels"], list)

    def test_a7_l2_03(self, app_page):
        """A7-L2-03 [S3]: チャンネル詳細にname/kpi/settings/performanceが含まれる"""
        d = app_page.request.get(f"{BASE}/channels/ch-001").json()
        assert all(k in d for k in ["name", "kpi", "settings", "performance"])

    def test_a7_l2_04(self, app_page):
        """A7-L2-04 [S4]: 効果サマリーにbefore/after/improvement_pctが含まれる"""
        d = app_page.request.get(f"{BASE}/effect-summary").json()
        assert all(k in d for k in ["before", "after", "improvement_pct"])

    def test_a7_l2_05(self, app_page):
        """A7-L2-05 [S11]: 最適化推奨にrecommendations配列とprioritized_countが含まれる"""
        d = app_page.request.get(f"{BASE}/optimization-recommendations").json()
        assert "recommendations" in d and "prioritized_count" in d

    def test_a7_l2_06(self, app_page):
        """A7-L2-06 [S12]: テンプレ推奨にtemplates配列とgenre_matchが含まれる"""
        d = app_page.request.get(f"{BASE}/template-recommendations").json()
        assert "templates" in d and "genre_match" in d

    def test_a7_l2_07(self, app_page):
        """A7-L2-07 [S13]: 投稿スケジュールにschedule配列とnext_postが含まれる"""
        d = app_page.request.get(f"{BASE}/post-schedule").json()
        assert "schedule" in d and "next_post" in d

    def test_a7_l2_08(self, app_page):
        """A7-L2-08 [S14]: ペース分析にtarget/actual/achievement_pctが含まれる"""
        d = app_page.request.get(f"{BASE}/posting-pace").json()
        assert all(k in d for k in ["target", "actual", "achievement_pct"])

    def test_a7_l2_09(self, app_page):
        """A7-L2-09 [S21]: 権限管理にroles配列とusersが含まれる"""
        d = app_page.request.get(f"{BASE}/permissions").json()
        assert "roles" in d and "users" in d

    def test_a7_l2_10(self, app_page):
        """A7-L2-10 [S22]: YouTube連携にconnected/channel_id/api_keyが含まれる"""
        d = app_page.request.get(f"{BASE}/youtube-connection").json()
        assert all(k in d for k in ["connected", "channel_id", "api_key"])


@pytest.mark.e2e
class TestA7L3Interaction:
    """L3: インタラクション (13項目)"""

    def test_a7_l3_01(self, app_page):
        """A7-L3-01 [S2]: チャンネル一覧の各チャンネルにid/name/statusが含まれる"""
        d = app_page.request.get(f"{BASE}/channels").json()
        for ch in d["channels"]:
            assert all(k in ch for k in ["id", "name", "status"])

    def test_a7_l3_02(self, app_page):
        """A7-L3-02 [S3]: チャンネル詳細のKPIにsubscribers/views/watch_timeが含まれる"""
        d = app_page.request.get(f"{BASE}/channels/ch-001").json()
        kpi = d["kpi"]
        assert all(k in kpi for k in ["subscribers", "views", "watch_time_hours"])

    def test_a7_l3_03(self, app_page):
        """A7-L3-03 [S5]: 制作効率のreduction_pctが0-100の範囲で返される"""
        d = app_page.request.get(f"{BASE}/production-efficiency").json()
        assert 0 <= d["reduction_pct"] <= 100

    def test_a7_l3_04(self, app_page):
        """A7-L3-04 [S6]: 品質向上度APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/quality-improvement")
        assert r.ok

    def test_a7_l3_05(self, app_page):
        """A7-L3-05 [S7]: CTR改善率APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/ctr-improvement")
        assert r.ok

    def test_a7_l3_06(self, app_page):
        """A7-L3-06 [S8]: 維持率改善にsmartcut_impact/quality_gate_impactが含まれる"""
        d = app_page.request.get(f"{BASE}/retention-improvement").json()
        assert all(k in d for k in ["smartcut_impact", "quality_gate_impact"])

    def test_a7_l3_07(self, app_page):
        """A7-L3-07 [S9]: ROI計算APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/roi")
        assert r.ok

    def test_a7_l3_08(self, app_page):
        """A7-L3-08 [S10]: チャンネル比較APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/channel-comparison")
        assert r.ok

    def test_a7_l3_09(self, app_page):
        """A7-L3-09 [S11]: 最適化推奨の各項目にpriority/titleが含まれる"""
        d = app_page.request.get(f"{BASE}/optimization-recommendations").json()
        for rec in d["recommendations"]:
            assert all(k in rec for k in ["priority", "title"])

    def test_a7_l3_10(self, app_page):
        """A7-L3-10 [S12]: テンプレ推奨APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/template-recommend",
            data=json.dumps({"channel_id": "ch-001", "genre": "tech"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "recommended"

    def test_a7_l3_11(self, app_page):
        """A7-L3-11 [S13]: 投稿スケジュール更新APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/post-schedule",
            data=json.dumps({"channel_id": "ch-001", "schedule": [{"day": "Monday", "time": "19:00"}]}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "updated"

    def test_a7_l3_12(self, app_page):
        """A7-L3-12 [S14]: ペース分析のachievement_pctが0以上の数値である"""
        d = app_page.request.get(f"{BASE}/posting-pace").json()
        assert isinstance(d["achievement_pct"], (int, float))
        assert d["achievement_pct"] >= 0

    def test_a7_l3_13(self, app_page):
        """A7-L3-13 [S15]: コメント分析APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/comment-analysis")
        assert r.ok


@pytest.mark.e2e
class TestA7L4StateTransition:
    """L4: 状態遷移 (10項目)"""

    def test_a7_l4_01(self, app_page):
        """A7-L4-01 [S6]: 品質向上度にaverage_improvement/trend/detailsが含まれる"""
        d = app_page.request.get(f"{BASE}/quality-improvement").json()
        assert all(k in d for k in ["average_improvement", "trend", "details"])

    def test_a7_l4_02(self, app_page):
        """A7-L4-02 [S7]: CTR改善率にimprovement_pct/before/afterが含まれる"""
        d = app_page.request.get(f"{BASE}/ctr-improvement").json()
        assert all(k in d for k in ["improvement_pct", "before", "after"])

    def test_a7_l4_03(self, app_page):
        """A7-L4-03 [S9]: ROI計算にroi_ratio/cost/benefitが含まれる"""
        d = app_page.request.get(f"{BASE}/roi").json()
        assert all(k in d for k in ["roi_ratio", "cost", "benefit"])

    def test_a7_l4_04(self, app_page):
        """A7-L4-04 [S10]: チャンネル比較にcomparisons配列とmetricsが含まれる"""
        d = app_page.request.get(f"{BASE}/channel-comparison").json()
        assert "comparisons" in d and "metrics" in d
        assert isinstance(d["comparisons"], list)

    def test_a7_l4_05(self, app_page):
        """A7-L4-05 [S15]: コメント分析にsentiment/requests/top_topicsが含まれる"""
        d = app_page.request.get(f"{BASE}/comment-analysis").json()
        assert all(k in d for k in ["sentiment", "requests", "top_topics"])

    def test_a7_l4_06(self, app_page):
        """A7-L4-06 [S16]: 競合ベンチマークAPIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/competitor-benchmark")
        assert r.ok
        assert "benchmarks" in r.json()

    def test_a7_l4_07(self, app_page):
        """A7-L4-07 [S17]: 成長予測APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/growth-prediction")
        assert r.ok
        assert "predictions" in r.json()

    def test_a7_l4_08(self, app_page):
        """A7-L4-08 [S18]: アラート設定APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/alert-settings",
            data=json.dumps({"channel_id": "ch-001", "metric": "ctr", "threshold": 3.0, "condition": "below"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "configured"

    def test_a7_l4_09(self, app_page):
        """A7-L4-09 [S19]: レポート生成APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/generate-report",
            data=json.dumps({"channel_id": "ch-001", "format": "pdf"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "generated"

    def test_a7_l4_10(self, app_page):
        """A7-L4-10 [S20]: Owner向けビュー設定APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/owner-view")
        assert r.ok
        assert "visible_sections" in r.json()


@pytest.mark.e2e
class TestA7L5EndToEnd:
    """L5: E2E完走 (10項目)"""

    def test_a7_l5_01(self, app_page):
        """A7-L5-01 [S16]: ダッシュボード→チャンネル一覧→詳細→競合ベンチの完走"""
        assert app_page.request.get(f"{BASE}/dashboard").ok
        chs = app_page.request.get(f"{BASE}/channels").json()
        assert chs["total"] >= 1
        detail = app_page.request.get(f"{BASE}/channels/{chs['channels'][0]['id']}").json()
        assert "kpi" in detail
        bench = app_page.request.get(f"{BASE}/competitor-benchmark").json()
        assert "benchmarks" in bench

    def test_a7_l5_02(self, app_page):
        """A7-L5-02 [S17]: 効果サマリー→CTR改善→成長予測の完走"""
        effect = app_page.request.get(f"{BASE}/effect-summary").json()
        assert effect["improvement_pct"]["ctr"] > 0
        ctr = app_page.request.get(f"{BASE}/ctr-improvement").json()
        assert ctr["improvement_pct"] > 0
        growth = app_page.request.get(f"{BASE}/growth-prediction").json()
        assert growth["confidence"] > 0

    def test_a7_l5_03(self, app_page):
        """A7-L5-03 [S18]: 制作効率→品質向上→ROI→アラート設定の完走"""
        eff = app_page.request.get(f"{BASE}/production-efficiency").json()
        assert eff["reduction_pct"] > 0
        qi = app_page.request.get(f"{BASE}/quality-improvement").json()
        assert qi["average_improvement"] > 0
        roi = app_page.request.get(f"{BASE}/roi").json()
        assert roi["roi_ratio"] > 1
        alert = app_page.request.post(f"{BASE}/alert-settings",
            data=json.dumps({"channel_id": "ch-001", "metric": "quality_score", "threshold": 80}),
            headers={"Content-Type": "application/json"}).json()
        assert alert["status"] == "configured"

    def test_a7_l5_04(self, app_page):
        """A7-L5-04 [S19]: コメント分析→最適化推奨→レポート生成の完走"""
        ca = app_page.request.get(f"{BASE}/comment-analysis").json()
        assert ca["total_comments_analyzed"] > 0
        rec = app_page.request.get(f"{BASE}/optimization-recommendations").json()
        assert rec["prioritized_count"] >= 1
        rpt = app_page.request.post(f"{BASE}/generate-report",
            data=json.dumps({"channel_id": "ch-001", "format": "html"}),
            headers={"Content-Type": "application/json"}).json()
        assert rpt["status"] == "generated"

    def test_a7_l5_05(self, app_page):
        """A7-L5-05 [S19]: 投稿スケジュール→ペース分析→テンプレ推奨の完走"""
        sched = app_page.request.get(f"{BASE}/post-schedule").json()
        assert "next_post" in sched
        pace = app_page.request.get(f"{BASE}/posting-pace").json()
        assert pace["achievement_pct"] >= 0
        tpl = app_page.request.get(f"{BASE}/template-recommendations").json()
        assert len(tpl["templates"]) >= 1

    def test_a7_l5_06(self, app_page):
        """A7-L5-06 [S20]: 全GETエンドポイント疎通確認の完走"""
        endpoints = [
            "/dashboard", "/channels", "/channels/ch-001",
            "/effect-summary", "/production-efficiency",
            "/quality-improvement", "/ctr-improvement",
            "/retention-improvement", "/roi",
            "/channel-comparison", "/optimization-recommendations",
            "/template-recommendations", "/post-schedule",
            "/posting-pace", "/comment-analysis",
            "/competitor-benchmark", "/growth-prediction",
            "/alert-settings", "/owner-view",
            "/permissions", "/youtube-connection",
        ]
        for ep in endpoints:
            r = app_page.request.get(f"{BASE}{ep}")
            assert r.ok, f"Endpoint {ep} failed with status {r.status}"

    def test_a7_l5_07(self, app_page):
        """A7-L5-07 [S21]: 権限管理→Owner向けビュー→YouTube連携の完走"""
        perm = app_page.request.get(f"{BASE}/permissions").json()
        assert len(perm["roles"]) >= 3
        owner = app_page.request.get(f"{BASE}/owner-view").json()
        assert owner["enabled"] is True
        yt = app_page.request.get(f"{BASE}/youtube-connection").json()
        # **接続していないので false**（R1.5-C4）
        assert yt["connected"] is False
        assert yt["is_real"] is False

    def test_a7_l5_08(self, app_page):
        """A7-L5-08 [S21]: チャンネル比較→維持率改善→ROI計算の完走"""
        comp = app_page.request.get(f"{BASE}/channel-comparison").json()
        assert len(comp["comparisons"]) >= 2
        ret = app_page.request.get(f"{BASE}/retention-improvement").json()
        assert ret["improvement_pct"] > 0
        roi = app_page.request.get(f"{BASE}/roi").json()
        assert roi["roi_ratio"] > 0

    def test_a7_l5_09(self, app_page):
        """A7-L5-09 [S22]: YouTube連携にconnected状態が反映される"""
        d = app_page.request.get(f"{BASE}/youtube-connection").json()
        # **接続していないので false**（R1.5-C4）。連携の状態が
        # 反映されていることが要件で、true であることではない
        assert d["connected"] is False
        assert "channel_id" in d
        assert d["quota_used_today"] >= 0
        assert d["is_real"] is False

    def test_a7_l5_10(self, app_page):
        """A7-L5-10 [S22]: 無効なチャンネルID指定で404エラーの完走"""
        r = app_page.request.get(f"{BASE}/channels/NONEXISTENT")
        assert r.status == 404
