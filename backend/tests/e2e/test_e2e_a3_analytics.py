"""
E2E テスト — A-3 YouTube Analytics連携・効果分析 5層検証 (55項目)

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

BASE = "http://localhost:8000/api/admin/analytics"


@pytest.mark.e2e
class TestA3L1DomExists:
    """L1: DOM存在 (12項目)"""

    def test_a3_l1_01(self, app_page):
        """A3-L1-01 [S1]: YouTube Analytics連携ダッシュボードAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/dashboard")
        assert r.ok

    def test_a3_l1_02(self, app_page):
        """A3-L1-02 [S1]: ダッシュボードにsectionsフィールドが存在する"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert "sections" in d
        assert len(d["sections"]) >= 10

    def test_a3_l1_03(self, app_page):
        """A3-L1-03 [S2]: CTR推移APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/ctr-trend")
        assert r.ok

    def test_a3_l1_04(self, app_page):
        """A3-L1-04 [S3]: 維持率推移APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/retention-trend")
        assert r.ok

    def test_a3_l1_05(self, app_page):
        """A3-L1-05 [S4]: 動画別実績APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/video-performance")
        assert r.ok

    def test_a3_l1_06(self, app_page):
        """A3-L1-06 [S5]: ベンチマークAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/benchmark")
        assert r.ok

    def test_a3_l1_07(self, app_page):
        """A3-L1-07 [S6]: テンプレート効果APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/template-effect")
        assert r.ok

    def test_a3_l1_08(self, app_page):
        """A3-L1-08 [S7]: SmartCut効果APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/smartcut-effect")
        assert r.ok

    def test_a3_l1_09(self, app_page):
        """A3-L1-09 [S11]: 改善提案APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/improvement-suggestions")
        assert r.ok

    def test_a3_l1_10(self, app_page):
        """A3-L1-10 [S14]: KPI達成度APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/kpi-achievement")
        assert r.ok

    def test_a3_l1_11(self, app_page):
        """A3-L1-11 [S18]: API接続管理APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/api-connection")
        assert r.ok

    def test_a3_l1_12(self, app_page):
        """A3-L1-12 [S22]: 成長予測APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/growth-forecast")
        assert r.ok


@pytest.mark.e2e
class TestA3L2VisualFeedback:
    """L2: 視覚フィードバック (10項目)"""

    def test_a3_l2_01(self, app_page):
        """A3-L2-01 [S1]: ダッシュボードにtitle/status/kpi_summaryが含まれる"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert all(k in d for k in ["title", "status", "kpi_summary"])

    def test_a3_l2_02(self, app_page):
        """A3-L2-02 [S2]: CTR推移にhistory配列とperiod_daysが含まれる"""
        d = app_page.request.get(f"{BASE}/ctr-trend").json()
        assert "history" in d and "period_days" in d
        assert isinstance(d["history"], list)

    def test_a3_l2_03(self, app_page):
        """A3-L2-03 [S3]: 維持率推移にhistory配列とperiod_daysが含まれる"""
        d = app_page.request.get(f"{BASE}/retention-trend").json()
        assert "history" in d and "period_days" in d
        assert isinstance(d["history"], list)

    def test_a3_l2_04(self, app_page):
        """A3-L2-04 [S4]: 動画別実績にvideos配列とtotalが含まれる"""
        d = app_page.request.get(f"{BASE}/video-performance").json()
        assert "videos" in d and "total" in d
        assert isinstance(d["videos"], list)

    def test_a3_l2_05(self, app_page):
        """A3-L2-05 [S5]: ベンチマークにindustry_avg/channel_avg/comparisonが含まれる"""
        d = app_page.request.get(f"{BASE}/benchmark").json()
        assert all(k in d for k in ["industry_avg", "channel_avg", "comparison"])

    def test_a3_l2_06(self, app_page):
        """A3-L2-06 [S6]: テンプレート効果にtemplates配列が含まれる"""
        d = app_page.request.get(f"{BASE}/template-effect").json()
        assert "templates" in d
        assert isinstance(d["templates"], list)

    def test_a3_l2_07(self, app_page):
        """A3-L2-07 [S7]: SmartCut効果にsettings配列が含まれる"""
        d = app_page.request.get(f"{BASE}/smartcut-effect").json()
        assert "settings" in d
        assert isinstance(d["settings"], list)

    def test_a3_l2_08(self, app_page):
        """A3-L2-08 [S11]: 改善提案にsuggestions配列とtotalが含まれる"""
        d = app_page.request.get(f"{BASE}/improvement-suggestions").json()
        assert "suggestions" in d and "total" in d
        assert isinstance(d["suggestions"], list)

    def test_a3_l2_09(self, app_page):
        """A3-L2-09 [S14]: KPI達成度にtarget/actual/achievement_rateが含まれる"""
        d = app_page.request.get(f"{BASE}/kpi-achievement").json()
        assert all(k in d for k in ["target", "actual", "achievement_rate"])

    def test_a3_l2_10(self, app_page):
        """A3-L2-10 [S18]: API接続管理にconnected/update_interval_minutesが含まれる"""
        d = app_page.request.get(f"{BASE}/api-connection").json()
        assert all(k in d for k in ["connected", "update_interval_minutes"])


@pytest.mark.e2e
class TestA3L3Interaction:
    """L3: インタラクション (13項目)"""

    def test_a3_l3_01(self, app_page):
        """A3-L3-01 [S2]: CTR推移の30日間データが配列で返される"""
        d = app_page.request.get(f"{BASE}/ctr-trend").json()
        assert len(d["history"]) == 30
        assert "ctr" in d["history"][0]

    def test_a3_l3_02(self, app_page):
        """A3-L3-02 [S3]: 維持率推移の30日間データが配列で返される"""
        d = app_page.request.get(f"{BASE}/retention-trend").json()
        assert len(d["history"]) == 30
        assert "retention" in d["history"][0]

    def test_a3_l3_03(self, app_page):
        """A3-L3-03 [S4]: 動画別実績の各エントリにtitle/ctr/retentionが含まれる"""
        d = app_page.request.get(f"{BASE}/video-performance").json()
        for v in d["videos"]:
            assert all(k in v for k in ["title", "ctr", "retention"])

    def test_a3_l3_04(self, app_page):
        """A3-L3-04 [S6]: テンプレート効果の各項目にname/avg_ctr/avg_retentionが含まれる"""
        d = app_page.request.get(f"{BASE}/template-effect").json()
        for t in d["templates"]:
            assert all(k in t for k in ["name", "avg_ctr", "avg_retention"])

    def test_a3_l3_05(self, app_page):
        """A3-L3-05 [S8]: AI提案効果APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/ai-suggestion-effect")
        assert r.ok
        d = r.json()
        assert "adopted" in d and "rejected" in d

    def test_a3_l3_06(self, app_page):
        """A3-L3-06 [S9]: チャプター効果APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/chapter-effect")
        assert r.ok

    def test_a3_l3_07(self, app_page):
        """A3-L3-07 [S10]: サムネイル効果APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/thumbnail-effect")
        assert r.ok

    def test_a3_l3_08(self, app_page):
        """A3-L3-08 [S11]: 改善提案の各項目にcategory/impact/descriptionが含まれる"""
        d = app_page.request.get(f"{BASE}/improvement-suggestions").json()
        for s in d["suggestions"]:
            assert all(k in s for k in ["category", "impact", "description"])

    def test_a3_l3_09(self, app_page):
        """A3-L3-09 [S12]: 改善提案適用APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/apply-suggestion",
            data=json.dumps({"suggestion_id": 1}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "applied"

    def test_a3_l3_10(self, app_page):
        """A3-L3-10 [S13]: KPI設定APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/kpi-settings",
            data=json.dumps({"target_ctr": 6.0, "target_retention": 55.0}),
            headers={"Content-Type": "application/json"})
        assert r.ok

    def test_a3_l3_11(self, app_page):
        """A3-L3-11 [S13]: KPI設定後に新しい値が反映される"""
        app_page.request.post(f"{BASE}/kpi-settings",
            data=json.dumps({"target_ctr": 7.0, "target_retention": 60.0}),
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/kpi-settings").json()
        assert d["target_ctr"] == 7.0

    def test_a3_l3_12(self, app_page):
        """A3-L3-12 [S15]: トレンド分析APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/trend-analysis")
        assert r.ok

    def test_a3_l3_13(self, app_page):
        """A3-L3-13 [S16]: 競合分析APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/competitor-analysis")
        assert r.ok


@pytest.mark.e2e
class TestA3L4StateTransition:
    """L4: 状態遷移 (10項目)"""

    def test_a3_l4_01(self, app_page):
        """A3-L4-01 [S8]: AI提案効果にadopted/rejected/impact_diffが含まれる"""
        d = app_page.request.get(f"{BASE}/ai-suggestion-effect").json()
        assert all(k in d for k in ["adopted", "rejected", "impact_diff"])

    def test_a3_l4_02(self, app_page):
        """A3-L4-02 [S9]: チャプター効果にwith_chapters/without_chaptersが含まれる"""
        d = app_page.request.get(f"{BASE}/chapter-effect").json()
        assert all(k in d for k in ["with_chapters", "without_chapters"])

    def test_a3_l4_03(self, app_page):
        """A3-L4-03 [S10]: サムネイル効果にthumbnails配列とcorrelation_scoreが含まれる"""
        d = app_page.request.get(f"{BASE}/thumbnail-effect").json()
        assert "thumbnails" in d and "correlation_score" in d
        assert isinstance(d["thumbnails"], list)

    def test_a3_l4_04(self, app_page):
        """A3-L4-04 [S12]: 無効な提案ID指定で適切なエラーが返る"""
        r = app_page.request.post(f"{BASE}/apply-suggestion",
            data=json.dumps({"suggestion_id": 9999}),
            headers={"Content-Type": "application/json"})
        assert r.status == 404

    def test_a3_l4_05(self, app_page):
        """A3-L4-05 [S13]: 無効なKPI値(負数)で適切なエラーが返る"""
        r = app_page.request.post(f"{BASE}/kpi-settings",
            data=json.dumps({"target_ctr": -1.0, "target_retention": 50.0}),
            headers={"Content-Type": "application/json"})
        assert r.status == 400

    def test_a3_l4_06(self, app_page):
        """A3-L4-06 [S14]: KPI達成度が0-100%の範囲で返される"""
        d = app_page.request.get(f"{BASE}/kpi-achievement").json()
        overall = d["achievement_rate"]["overall"]
        assert 0 <= overall <= 100

    def test_a3_l4_07(self, app_page):
        """A3-L4-07 [S15]: トレンド分析にtrends配列が含まれる"""
        d = app_page.request.get(f"{BASE}/trend-analysis").json()
        assert "trends" in d
        assert isinstance(d["trends"], list)
        assert len(d["trends"]) > 0

    def test_a3_l4_08(self, app_page):
        """A3-L4-08 [S16]: 競合分析にcompetitors配列が含まれる"""
        d = app_page.request.get(f"{BASE}/competitor-analysis").json()
        assert "competitors" in d
        assert isinstance(d["competitors"], list)

    def test_a3_l4_09(self, app_page):
        """A3-L4-09 [S17]: レポート生成APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/generate-report",
            data=json.dumps({"period": "monthly"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "generated"

    def test_a3_l4_10(self, app_page):
        """A3-L4-10 [S18]: API接続設定の更新が反映される"""
        app_page.request.post(f"{BASE}/api-connection",
            data=json.dumps({"update_interval_minutes": 30, "enabled": True}),
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/api-connection").json()
        assert d["update_interval_minutes"] == 30


@pytest.mark.e2e
class TestA3L5EndToEnd:
    """L5: E2E完走 (10項目)"""

    def test_a3_l5_01(self, app_page):
        """A3-L5-01 [S17]: ダッシュボード→CTR確認→ベンチマーク→レポート生成の完走"""
        assert app_page.request.get(f"{BASE}/dashboard").ok
        ctr = app_page.request.get(f"{BASE}/ctr-trend").json()
        assert len(ctr["history"]) == 30
        bm = app_page.request.get(f"{BASE}/benchmark").json()
        assert "industry_avg" in bm
        rpt = app_page.request.post(f"{BASE}/generate-report",
            data=json.dumps({"period": "monthly"}),
            headers={"Content-Type": "application/json"}).json()
        assert rpt["status"] == "generated"

    def test_a3_l5_02(self, app_page):
        """A3-L5-02 [S19]: API接続確認→キャッシュ状態→フォールバック確認の完走"""
        conn = app_page.request.get(f"{BASE}/api-connection").json()
        assert "connected" in conn
        cache = app_page.request.get(f"{BASE}/cache-fallback").json()
        assert "cache_available" in cache
        assert "data_freshness" in cache

    def test_a3_l5_03(self, app_page):
        """A3-L5-03 [S19]: 動画別実績→テンプレ効果→SmartCut効果→改善提案の完走"""
        vp = app_page.request.get(f"{BASE}/video-performance").json()
        assert vp["total"] > 0
        te = app_page.request.get(f"{BASE}/template-effect").json()
        assert len(te["templates"]) > 0
        sc = app_page.request.get(f"{BASE}/smartcut-effect").json()
        assert len(sc["settings"]) > 0
        sg = app_page.request.get(f"{BASE}/improvement-suggestions").json()
        assert sg["total"] > 0

    def test_a3_l5_04(self, app_page):
        """A3-L5-04 [S20]: 効果要約ダッシュボード→KPI確認→成長予測の完走"""
        od = app_page.request.get(f"{BASE}/owner-dashboard").json()
        assert "summary" in od
        kpi = app_page.request.get(f"{BASE}/kpi-achievement").json()
        assert "achievement_rate" in kpi
        gf = app_page.request.get(f"{BASE}/growth-forecast").json()
        assert "forecast_subscribers" in gf

    def test_a3_l5_05(self, app_page):
        """A3-L5-05 [S20]: KPI設定→達成度確認→改善提案→適用の完走"""
        app_page.request.post(f"{BASE}/kpi-settings",
            data=json.dumps({"target_ctr": 5.0, "target_retention": 50.0}),
            headers={"Content-Type": "application/json"})
        kpi = app_page.request.get(f"{BASE}/kpi-achievement").json()
        assert kpi["achievement_rate"]["overall"] > 0
        sg = app_page.request.get(f"{BASE}/improvement-suggestions").json()
        assert sg["total"] > 0
        apply_r = app_page.request.post(f"{BASE}/apply-suggestion",
            data=json.dumps({"suggestion_id": 2}),
            headers={"Content-Type": "application/json"})
        assert apply_r.ok

    def test_a3_l5_06(self, app_page):
        """A3-L5-06 [S21]: 期間比較→トレンド分析→競合分析の完走"""
        pc = app_page.request.get(f"{BASE}/period-comparison").json()
        assert "diff" in pc
        tr = app_page.request.get(f"{BASE}/trend-analysis").json()
        assert len(tr["trends"]) > 0
        ca = app_page.request.get(f"{BASE}/competitor-analysis").json()
        assert len(ca["competitors"]) > 0

    def test_a3_l5_07(self, app_page):
        """A3-L5-07 [S21]: 全GETエンドポイント疎通確認の完走"""
        endpoints = [
            "/dashboard", "/ctr-trend", "/retention-trend",
            "/video-performance", "/benchmark",
            "/template-effect", "/smartcut-effect",
            "/ai-suggestion-effect", "/chapter-effect",
            "/thumbnail-effect", "/improvement-suggestions",
            "/kpi-settings", "/kpi-achievement",
            "/trend-analysis", "/competitor-analysis",
            "/api-connection", "/cache-fallback",
            "/owner-dashboard", "/period-comparison",
            "/growth-forecast",
        ]
        for ep in endpoints:
            r = app_page.request.get(f"{BASE}{ep}")
            assert r.ok, f"Endpoint {ep} failed with status {r.status}"

    def test_a3_l5_08(self, app_page):
        """A3-L5-08 [S21]: AI提案効果→チャプター効果→サムネイル効果の完走"""
        ai = app_page.request.get(f"{BASE}/ai-suggestion-effect").json()
        assert ai["impact_diff"]["ctr_diff"] > 0
        ch = app_page.request.get(f"{BASE}/chapter-effect").json()
        assert ch["with_chapters"]["avg_retention"] > ch["without_chapters"]["avg_retention"]
        th = app_page.request.get(f"{BASE}/thumbnail-effect").json()
        assert th["correlation_score"] > 0

    def test_a3_l5_09(self, app_page):
        """A3-L5-09 [S22]: 成長予測にforecast_subscribers/forecast_viewsが含まれる"""
        d = app_page.request.get(f"{BASE}/growth-forecast").json()
        assert all(k in d for k in ["forecast_subscribers", "forecast_views"])
        assert d["forecast_subscribers"]["30_days"] > d["forecast_subscribers"]["current"]

    def test_a3_l5_10(self, app_page):
        """A3-L5-10 [S22]: 無効なKPI設定(負数)で400エラーの完走"""
        r = app_page.request.post(f"{BASE}/kpi-settings",
            data=json.dumps({"target_ctr": -5.0, "target_retention": -10.0}),
            headers={"Content-Type": "application/json"})
        assert r.status == 400
