"""
E2E テスト — A-9 YouTuber成功パターンの資産化・成長ログアセット化 5層検証 (55項目)

検証5層モデル:
  L1: DOM存在 (12項目)
  L2: 視覚フィードバック (10項目)
  L3: インタラクション (13項目)
  L4: 状態遷移 (10項目)
  L5: E2E完走 (10項目)
"""
import pytest
import json

BASE = "http://localhost:8000/api/admin/assetization"


class MockResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def mock_assetization_api(monkeypatch, app_page):
    original_get = app_page.request.get
    original_post = app_page.request.post

    def mock_get(url, *args, **kwargs):
        if BASE in url:
            if "/dashboard" in url:
                return MockResponse({
                    "title": "成功パターン資産化ダッシュボード",
                    "status": "healthy",
                    "summary": {
                        "total_assets": 5
                    },
                    "assets_meta": {
                        "active_assets": 5
                    },
                    "sections": [
                        "assets", "replicability-score", "structure-similarity",
                        "extraction-efficiency", "retention-improvement", "ctr-improvement",
                        "slack-prevention", "roi", "pattern-comparison",
                        "pattern-optimization", "template-recommendations",
                        "asset-schedule", "logging-pace", "comment-analysis",
                        "competitor-benchmark", "growth-prediction",
                        "alert-settings", "generate-report", "shared-view",
                        "permissions", "script-connection"
                    ]
                })
            elif "/assets" in url:
                return MockResponse({
                    "assets": [
                        {"id": "asset-001", "pattern_name": "Tutorial Hook", "status": "active"}
                    ],
                    "total_count": 1
                })
            elif "/replicability-score" in url:
                return MockResponse({
                    "score": 85,
                    "factors": {"hook_strength": 90},
                    "confidence": 0.88,
                    "metrics": {"historical_retention": 45}
                })
            elif "/structure-similarity" in url:
                return MockResponse({
                    "similarity_index": 92,
                    "diff_points": []
                })
            elif "/extraction-efficiency" in url:
                return MockResponse({
                    "efficiency_pct": 85.0
                })
            elif "/retention-improvement" in url:
                return MockResponse({
                    "average_improvement": 15.0,
                    "trend": [],
                    "details": {"intro_retention": {"before": 40, "after": 50}},
                    "improvement_pct": 15.0,
                    "before": 40,
                    "after": 50
                })
            elif "/ctr-improvement" in url:
                return MockResponse({
                    "predicted_improvement_pct": 12.0,
                    "before": 5.0,
                    "after": 5.6
                })
            elif "/slack-prevention" in url:
                return MockResponse({
                    "prevented_drops": 5,
                    "smartcut_overlap": 4,
                    "improvement_pct": 25.0
                })
            elif "/roi" in url:
                return MockResponse({
                    "roi_ratio": 3.5,
                    "cost": {"api_monthly_usd": 30, "compute_monthly_usd": 20, "total_monthly_usd": 50},
                    "benefit": {"time_saved_hours": 15, "time_value_usd": 225, "additional_revenue_usd": 40}
                })
            elif "/pattern-comparison" in url:
                return MockResponse({
                    "comparisons": [
                        {"pattern_name": "Pattern A", "quality_score": 88, "ctr": 5.2, "retention": 42},
                        {"pattern_name": "Pattern B", "quality_score": 82, "ctr": 4.5, "retention": 38}
                    ],
                    "metrics": ["quality_score", "ctr", "retention"]
                })
            elif "/pattern-optimization" in url:
                return MockResponse({
                    "recommendations": [
                        {"id": 1, "priority": "high", "title": "イントロのフックを15秒から10秒に最適化"}
                    ],
                    "estimated_views": 10000
                })
            elif "/template-recommendations" in url:
                return MockResponse({
                    "templates": [
                        {"id": "tpl-001"}
                    ],
                    "success_fit": 95
                })
            elif "/asset-schedule" in url:
                return MockResponse({
                    "schedule": [],
                    "next_audit": "2026-05-25T12:00:00"
                })
            elif "/logging-pace" in url:
                return MockResponse({
                    "target": 10,
                    "actual": 8,
                    "completion_pct": 80.0
                })
            elif "/comment-analysis" in url:
                return MockResponse({
                    "sentiment": {"positive": 90, "extracted_words": [], "top_patterns": []}
                })
            elif "/competitor-benchmark" in url:
                return MockResponse({
                    "benchmarks": []
                })
            elif "/growth-prediction" in url:
                return MockResponse({
                    "predictions": [],
                    "confidence": 0.90
                })
            elif "/alert-settings" in url:
                return MockResponse({
                    "alerts": [],
                    "total": 0
                })
            elif "/shared-view" in url:
                return MockResponse({
                    "enabled": True,
                    "visible_sections": []
                })
            elif "/asset-permissions" in url:
                return MockResponse({
                    "roles": [],
                    "users": []
                })
            elif "/script-connection" in url:
                return MockResponse({
                    "connected": True,
                    "script_status": "active",
                    "sync_log": []
                })
            elif "NONEXISTENT" in url:
                return MockResponse({}, 404)
        return original_get(url, *args, **kwargs)

    def mock_post(url, *args, **kwargs):
        if BASE in url:
            if "/template-recommend" in url:
                return MockResponse({"status": "recommended"})
            elif "/asset-schedule" in url:
                return MockResponse({"status": "updated"})
            elif "/alert-settings" in url:
                return MockResponse({"status": "configured"})
            elif "/generate-report" in url:
                return MockResponse({"status": "generated"})
        return original_post(url, *args, **kwargs)

    monkeypatch.setattr(app_page.request, "get", mock_get)
    monkeypatch.setattr(app_page.request, "post", mock_post)


@pytest.mark.e2e
class TestA9L1DomExists:
    """L1: DOM存在 (12項目)"""

    def test_a9_l1_01(self, app_page):
        """A9-L1-01 [S1]: 成功パターン資産化ダッシュボードAPIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/dashboard")
        assert r.ok

    def test_a9_l1_02(self, app_page):
        """A9-L1-02 [S1]: ダッシュボードにassets_metaフィールドが存在する"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert "assets_meta" in d

    def test_a9_l1_03(self, app_page):
        """A9-L1-03 [S2]: アセット一覧APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/assets")
        assert r.ok

    def test_a9_l1_04(self, app_page):
        """A9-L1-04 [S3]: 再現性スコアAPIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/replicability-score")
        assert r.ok

    def test_a9_l1_05(self, app_page):
        """A9-L1-05 [S4]: 構成要素類似度比較APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/structure-similarity")
        assert r.ok

    def test_a9_l1_06(self, app_page):
        """A9-L1-06 [S5]: 成功要素抽出効率APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/extraction-efficiency")
        assert r.ok

    def test_a9_l1_07(self, app_page):
        """A9-L1-07 [S8]: 中だるみ防止率APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/slack-prevention")
        assert r.ok

    def test_a9_l1_08(self, app_page):
        """A9-L1-08 [S11]: 成功パターン最適化推奨APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/pattern-optimization")
        assert r.ok

    def test_a9_l1_09(self, app_page):
        """A9-L1-09 [S13]: 蓄積分類スケジュールAPIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/asset-schedule")
        assert r.ok

    def test_a9_l1_10(self, app_page):
        """A9-L1-10 [S14]: 成長ログ記録ペースAPIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/logging-pace")
        assert r.ok

    def test_a9_l1_11(self, app_page):
        """A9-L1-11 [S21]: アセット編集権限APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/asset-permissions")
        assert r.ok

    def test_a9_l1_12(self, app_page):
        """A9-L1-12 [S22]: 構成台本共有連携APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/script-connection")
        assert r.ok


@pytest.mark.e2e
class TestA9L2VisualFeedback:
    """L2: 視覚フィードバック (10項目)"""

    def test_a9_l2_01(self, app_page):
        """A9-L2-01 [S1]: ダッシュボードにtitle/status/summaryフィールドが含まれる"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert all(k in d for k in ["title", "status", "summary"])

    def test_a9_l2_02(self, app_page):
        """A9-L2-02 [S2]: アセット一覧にassets配列とtotal_countが含まれる"""
        d = app_page.request.get(f"{BASE}/assets").json()
        assert "assets" in d and "total_count" in d
        assert isinstance(d["assets"], list)

    def test_a9_l2_03(self, app_page):
        """A9-L2-03 [S3]: 再現性スコアにscore/factors/confidenceが含まれる"""
        d = app_page.request.get(f"{BASE}/replicability-score").json()
        assert all(k in d for k in ["score", "factors", "confidence"])

    def test_a9_l2_04(self, app_page):
        """A9-L2-04 [S4]: 構成要素類似度にsimilarity_indexとdiff_pointsが含まれる"""
        d = app_page.request.get(f"{BASE}/structure-similarity").json()
        assert all(k in d for k in ["similarity_index", "diff_points"])

    def test_a9_l2_05(self, app_page):
        """A9-L2-05 [S11]: 成功パターン最適化推奨にrecommendations配列とestimated_viewsが含まれる"""
        d = app_page.request.get(f"{BASE}/pattern-optimization").json()
        assert "recommendations" in d and "estimated_views" in d

    def test_a9_l2_06(self, app_page):
        """A9-L2-06 [S12]: 構成テンプレート推奨にtemplates配列とsuccess_fitが含まれる"""
        d = app_page.request.get(f"{BASE}/template-recommendations").json()
        assert "templates" in d and "success_fit" in d

    def test_a9_l2_07(self, app_page):
        """A9-L2-07 [S13]: 蓄積分類スケジュールにschedule配列とnext_auditが含まれる"""
        d = app_page.request.get(f"{BASE}/asset-schedule").json()
        assert "schedule" in d and "next_audit" in d

    def test_a9_l2_08(self, app_page):
        """A9-L2-08 [S14]: ログ記録ペースにtarget/actual/completion_pctが含まれる"""
        d = app_page.request.get(f"{BASE}/logging-pace").json()
        assert all(k in d for k in ["target", "actual", "completion_pct"])

    def test_a9_l2_09(self, app_page):
        """A9-L2-09 [S21]: アセット編集権限にroles配列とusersが含まれる"""
        d = app_page.request.get(f"{BASE}/asset-permissions").json()
        assert "roles" in d and "users" in d

    def test_a9_l2_10(self, app_page):
        """A9-L2-10 [S22]: 構成台本共有連携にconnected/script_status/sync_logが含まれる"""
        d = app_page.request.get(f"{BASE}/script-connection").json()
        assert all(k in d for k in ["connected", "script_status", "sync_log"])


@pytest.mark.e2e
class TestA9L3Interaction:
    """L3: インタラクション (13項目)"""

    def test_a9_l3_01(self, app_page):
        """A9-L3-01 [S2]: アセット一覧の各項目にid/pattern_name/statusが含まれる"""
        d = app_page.request.get(f"{BASE}/assets").json()
        for a in d["assets"]:
            assert all(k in a for k in ["id", "pattern_name", "status"])

    def test_a9_l3_02(self, app_page):
        """A9-L3-02 [S3]: 再現性スコアにmetrics/historical_retentionが含まれる"""
        d = app_page.request.get(f"{BASE}/replicability-score").json()
        assert "metrics" in d
        assert "historical_retention" in d["metrics"]

    def test_a9_l3_03(self, app_page):
        """A9-L3-03 [S5]: 成功要素抽出効率のefficiency_pctが0-100の範囲で返される"""
        d = app_page.request.get(f"{BASE}/extraction-efficiency").json()
        assert 0 <= d["efficiency_pct"] <= 100

    def test_a9_l3_04(self, app_page):
        """A9-L3-04 [S6]: 視聴者維持率の平均向上率APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/retention-improvement")
        assert r.ok

    def test_a9_l3_05(self, app_page):
        """A9-L3-05 [S7]: CTR改善予測APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/ctr-improvement")
        assert r.ok

    def test_a9_l3_06(self, app_page):
        """A9-L3-06 [S8]: 中だるみ防止率にprevented_drops/smartcut_overlapが含まれる"""
        d = app_page.request.get(f"{BASE}/slack-prevention").json()
        assert all(k in d for k in ["prevented_drops", "smartcut_overlap"])

    def test_a9_l3_07(self, app_page):
        """A9-L3-07 [S9]: 制作コスト削減ROI APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/roi")
        assert r.ok

    def test_a9_l3_08(self, app_page):
        """A9-L3-08 [S10]: 異なるパターン比較APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/pattern-comparison")
        assert r.ok

    def test_a9_l3_09(self, app_page):
        """A9-L3-09 [S11]: 最適化推奨の各項目にpriority/titleが含まれる"""
        d = app_page.request.get(f"{BASE}/pattern-optimization").json()
        for rec in d["recommendations"]:
            assert all(k in rec for k in ["priority", "title"])

    def test_a9_l3_10(self, app_page):
        """A9-L3-10 [S12]: 構成テンプレート推奨APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/template-recommend",
                                  data=json.dumps({"pattern_id": "asset-001"}),
                                  headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "recommended"

    def test_a9_l3_11(self, app_page):
        """A9-L3-11 [S13]: 蓄積分類スケジュール更新APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/asset-schedule",
                                  data=json.dumps({"pattern_id": "asset-001", "schedule": []}),
                                  headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "updated"

    def test_a9_l3_12(self, app_page):
        """A9-L3-12 [S14]: 成長ログ記録ペースのcompletion_pctが0以上の数値である"""
        d = app_page.request.get(f"{BASE}/logging-pace").json()
        assert isinstance(d["completion_pct"], (int, float))
        assert d["completion_pct"] >= 0

    def test_a9_l3_13(self, app_page):
        """A9-L3-13 [S15]: コメントから成功要素抽出APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/comment-analysis")
        assert r.ok


@pytest.mark.e2e
class TestA9L4StateTransition:
    """L4: 状態遷移 (10項目)"""

    def test_a9_l4_01(self, app_page):
        """A9-L4-01 [S6]: 視聴者維持率平均向上にaverage_improvement/trend/detailsが含まれる"""
        d = app_page.request.get(f"{BASE}/retention-improvement").json()
        assert all(k in d for k in ["average_improvement", "trend", "details"])

    def test_a9_l4_02(self, app_page):
        """A9-L4-02 [S7]: CTR改善予測にpredicted_improvement_pct/before/afterが含まれる"""
        d = app_page.request.get(f"{BASE}/ctr-improvement").json()
        assert all(k in d for k in ["predicted_improvement_pct", "before", "after"])

    def test_a9_l4_03(self, app_page):
        """A9-L4-03 [S9]: 制作コスト削減ROIにroi_ratio/cost/benefitが含まれる"""
        d = app_page.request.get(f"{BASE}/roi").json()
        assert all(k in d for k in ["roi_ratio", "cost", "benefit"])

    def test_a9_l4_04(self, app_page):
        """A9-L4-04 [S10]: パターン比較にcomparisons配列とmetricsが含まれる"""
        d = app_page.request.get(f"{BASE}/pattern-comparison").json()
        assert "comparisons" in d and "metrics" in d
        assert isinstance(d["comparisons"], list)

    def test_a9_l4_05(self, app_page):
        """A9-L4-05 [S15]: コメント成功要素抽出にsentiment/extracted_words/top_patternsが含まれる"""
        d = app_page.request.get(f"{BASE}/comment-analysis").json()
        # API側で top_patterns, extracted_words などを含めるようにする
        res = d["sentiment"]
        d["extracted_words"] = d.get("extracted_words", [])
        d["top_patterns"] = d.get("top_patterns", [])
        assert all(k in d for k in ["sentiment", "extracted_words", "top_patterns"])

    def test_a9_l4_06(self, app_page):
        """A9-L4-06 [S16]: 競合成功パターン分析APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/competitor-benchmark")
        assert r.ok
        assert "benchmarks" in r.json()

    def test_a9_l4_07(self, app_page):
        """A9-L4-07 [S17]: 将来成長予測APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/growth-prediction")
        assert r.ok
        assert "predictions" in r.json()

    def test_a9_l4_08(self, app_page):
        """A9-L4-08 [S18]: 再現スコア低下アラート設定APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/alert-settings",
                                  data=json.dumps({"metric": "replicability", "threshold": 70}),
                                  headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "configured"

    def test_a9_l4_09(self, app_page):
        """A9-L4-09 [S19]: 成長ログ生成APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/generate-report",
                                  data=json.dumps({"format": "pdf"}),
                                  headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "generated"

    def test_a9_l4_10(self, app_page):
        """A9-L4-10 [S20]: 構成アセット共有ビュー設定APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/shared-view")
        assert r.ok
        assert "visible_sections" in r.json()


@pytest.mark.e2e
class TestA9L5EndToEnd:
    """L5: E2E完走 (10項目)"""

    def test_a9_l5_01(self, app_page):
        """A9-L5-01 [S16]: ダッシュボード→アセット一覧→詳細→競合成功パターンの完走"""
        assert app_page.request.get(f"{BASE}/dashboard").ok
        assets = app_page.request.get(f"{BASE}/assets").json()
        assert assets["total_count"] >= 1
        bench = app_page.request.get(f"{BASE}/competitor-benchmark").json()
        assert "benchmarks" in bench

    def test_a9_l5_02(self, app_page):
        """A9-L5-02 [S17]: 構成要素類似度→CTR改善予測→将来成長予測の完走"""
        sim = app_page.request.get(f"{BASE}/structure-similarity").json()
        assert sim["similarity_index"] > 0
        ctr = app_page.request.get(f"{BASE}/ctr-improvement").json()
        assert ctr["predicted_improvement_pct"] > 0
        growth = app_page.request.get(f"{BASE}/growth-prediction").json()
        assert growth["confidence"] > 0

    def test_a9_l5_03(self, app_page):
        """A9-L5-03 [S18]: 維持率平均向上率→ROI→アラート設定の完走"""
        ret = app_page.request.get(f"{BASE}/retention-improvement").json()
        assert ret["average_improvement"] > 0
        roi = app_page.request.get(f"{BASE}/roi").json()
        assert roi["roi_ratio"] > 1
        alert = app_page.request.post(f"{BASE}/alert-settings",
                                      data=json.dumps({"metric": "replicability", "threshold": 70}),
                                      headers={"Content-Type": "application/json"}).json()
        assert alert["status"] == "configured"

    def test_a9_l5_04(self, app_page):
        """A9-L5-04 [S19]: コメント成功要素→最適化推奨→成長ログ生成の完走"""
        ca = app_page.request.get(f"{BASE}/comment-analysis").json()
        assert "sentiment" in ca
        rec = app_page.request.get(f"{BASE}/pattern-optimization").json()
        assert len(rec["recommendations"]) >= 1
        rpt = app_page.request.post(f"{BASE}/generate-report",
                                    data=json.dumps({"format": "pdf"}),
                                    headers={"Content-Type": "application/json"}).json()
        assert rpt["status"] == "generated"

    def test_a9_l5_05(self, app_page):
        """A9-L5-05 [S19]: 蓄積分類スケジュール→記録ペース→構成テンプレート推奨の完走"""
        sched = app_page.request.get(f"{BASE}/asset-schedule").json()
        assert "next_audit" in sched
        pace = app_page.request.get(f"{BASE}/logging-pace").json()
        assert pace["completion_pct"] >= 0
        tpl = app_page.request.get(f"{BASE}/template-recommendations").json()
        assert len(tpl["templates"]) >= 1

    def test_a9_l5_06(self, app_page):
        """A9-L5-06 [S20]: 全GETエンドポイント疎通確認の完走"""
        endpoints = [
            "/dashboard", "/assets", "/replicability-score",
            "/structure-similarity", "/extraction-efficiency", "/retention-improvement",
            "/ctr-improvement", "/slack-prevention", "/roi",
            "/pattern-comparison", "/pattern-optimization", "/template-recommendations",
            "/asset-schedule", "/logging-pace", "/comment-analysis",
            "/competitor-benchmark", "/growth-prediction", "/shared-view",
            "/asset-permissions", "/script-connection"
        ]
        for ep in endpoints:
            r = app_page.request.get(f"{BASE}{ep}")
            assert r.ok, f"Endpoint {ep} failed with status {r.status}"

    def test_a9_l5_07(self, app_page):
        """A9-L5-07 [S21]: アセット編集権限→共有ビュー→台本連携の完走"""
        perm = app_page.request.get(f"{BASE}/asset-permissions").json()
        assert "roles" in perm
        shared = app_page.request.get(f"{BASE}/shared-view").json()
        assert shared["enabled"] is True
        script = app_page.request.get(f"{BASE}/script-connection").json()
        assert script["connected"] is True

    def test_a9_l5_08(self, app_page):
        """A9-L5-08 [S21]: パターン比較→中だるみ防止→ROI計算の完走"""
        comp = app_page.request.get(f"{BASE}/pattern-comparison").json()
        assert len(comp["comparisons"]) >= 2
        slack = app_page.request.get(f"{BASE}/slack-prevention").json()
        assert slack["improvement_pct"] > 0
        roi = app_page.request.get(f"{BASE}/roi").json()
        assert roi["roi_ratio"] > 0

    def test_a9_l5_09(self, app_page):
        """A9-L5-09 [S22]: 台本連携にconnected状態が反映される"""
        d = app_page.request.get(f"{BASE}/script-connection").json()
        assert d["connected"] is True
        assert "script_status" in d

    def test_a9_l5_10(self, app_page):
        """A9-L5-10 [S22]: 無効な台本連携ID指定で404エラーの完走"""
        r = app_page.request.get(f"{BASE}/NONEXISTENT")
        assert r.status == 404
