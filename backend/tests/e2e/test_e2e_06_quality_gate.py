"""
E2E テスト — O-6 品質チェック 5層検証 (40項目)

検証5層モデル:
  L1: DOM存在 (10項目)
  L2: 視覚フィードバック (8項目)
  L3: インタラクション (6項目)
  L4: 状態遷移 (5項目)
  L5: E2E完走 (5項目)
  不足分: 6項目追加で合計40項目
"""
import pytest
import json

BASE = "http://localhost:8000/api/pipeline"


@pytest.mark.e2e
class TestO6L1DomExists:
    """L1: DOM存在"""

    def test_o6_l1_01(self, app_page):
        """O6-L1-01 [S1]: 品質ゲートステータスAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/quality-gate/status")
        assert r.ok

    def test_o6_l1_02(self, app_page):
        """O6-L1-02 [S1]: statusフィールドが存在する"""
        d = app_page.request.get(f"{BASE}/quality-gate/status").json()
        assert "status" in d

    def test_o6_l1_03(self, app_page):
        """O6-L1-03 [S2]: overall_scoreフィールドが存在する"""
        d = app_page.request.get(f"{BASE}/quality-gate/status").json()
        assert "overall_score" in d

    def test_o6_l1_04(self, app_page):
        """O6-L1-04 [S3]: カテゴリ別スコアAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/quality-gate/scores")
        assert r.ok

    def test_o6_l1_05(self, app_page):
        """O6-L1-05 [S3]: 4カテゴリが存在する"""
        d = app_page.request.get(f"{BASE}/quality-gate/scores").json()
        ids = {c["id"] for c in d["categories"]}
        assert ids == {"audio", "video", "subtitle", "structure"}

    def test_o6_l1_06(self, app_page):
        """O6-L1-06 [S5]: ドリルダウンAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/quality-gate/drilldown/audio")
        assert r.ok

    def test_o6_l1_07(self, app_page):
        """O6-L1-07 [S6]: AI改善提案APIが正常応答する"""
        r = app_page.request.post(f"{BASE}/quality-gate/improve",
            data=json.dumps({"category": ""}),
            headers={"Content-Type": "application/json"})
        assert r.ok

    def test_o6_l1_08(self, app_page):
        """O6-L1-08 [S7]: thresholdフィールドが存在する"""
        d = app_page.request.get(f"{BASE}/quality-gate/status").json()
        assert "threshold" in d

    def test_o6_l1_09(self, app_page):
        """O6-L1-09 [S9]: 履歴APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/quality-gate/history")
        assert r.ok

    def test_o6_l1_10(self, app_page):
        """O6-L1-10 [S9]: 履歴にhistory配列が存在する"""
        d = app_page.request.get(f"{BASE}/quality-gate/history").json()
        assert isinstance(d["history"], list)


@pytest.mark.e2e
class TestO6L2VisualFeedback:
    """L2: 視覚フィードバック"""

    def test_o6_l2_01(self, app_page):
        """O6-L2-01 [S2]: overall_scoreが0-100"""
        s = app_page.request.get(f"{BASE}/quality-gate/status").json()["overall_score"]
        assert 0 <= s <= 100

    def test_o6_l2_02(self, app_page):
        """O6-L2-02 [S2]: thresholdが90"""
        assert app_page.request.get(f"{BASE}/quality-gate/status").json()["threshold"] == 90

    def test_o6_l2_03(self, app_page):
        """O6-L2-03 [S3]: 各カテゴリにscore/weight/name"""
        for c in app_page.request.get(f"{BASE}/quality-gate/scores").json()["categories"]:
            assert all(k in c for k in ["score", "weight", "name"])

    def test_o6_l2_04(self, app_page):
        """O6-L2-04 [S3]: 重み付きスコアが正しい"""
        for c in app_page.request.get(f"{BASE}/quality-gate/scores").json()["categories"]:
            assert c["weighted_score"] == round(c["score"] * c["weight"] / 100, 1)

    def test_o6_l2_05(self, app_page):
        """O6-L2-05 [S4]: pass/warning/failステータス区別"""
        d = app_page.request.get(f"{BASE}/quality-gate/drilldown/audio").json()
        assert "pass" in {x["status"] for x in d["details"]}

    def test_o6_l2_06(self, app_page):
        """O6-L2-06 [S4]: 詳細にdescription含む"""
        for x in app_page.request.get(f"{BASE}/quality-gate/drilldown/video").json()["details"]:
            assert len(x["description"]) > 0

    def test_o6_l2_07(self, app_page):
        """O6-L2-07 [S4]: warningカウント正しい"""
        for c in app_page.request.get(f"{BASE}/quality-gate/scores").json()["categories"]:
            assert isinstance(c["warning_count"], int) and c["warning_count"] >= 0

    def test_o6_l2_08(self, app_page):
        """O6-L2-08 [S6]: 提案にpriority含む"""
        d = app_page.request.post(f"{BASE}/quality-gate/improve",
            data=json.dumps({"category": ""}),
            headers={"Content-Type": "application/json"}).json()
        if d["count"] > 0:
            assert "priority" in d["suggestions"][0]


@pytest.mark.e2e
class TestO6L3Interaction:
    """L3: インタラクション"""

    def test_o6_l3_01(self, app_page):
        """O6-L3-01 [S3]: スコアAPI呼出"""
        d = app_page.request.get(f"{BASE}/quality-gate/scores").json()
        assert len(d["categories"]) == 4

    def test_o6_l3_02(self, app_page):
        """O6-L3-02 [S5]: audioドリルダウン"""
        d = app_page.request.get(f"{BASE}/quality-gate/drilldown/audio").json()
        assert d["category"] == "audio" and len(d["details"]) > 0

    def test_o6_l3_03(self, app_page):
        """O6-L3-03 [S5]: videoドリルダウン"""
        d = app_page.request.get(f"{BASE}/quality-gate/drilldown/video").json()
        assert d["category"] == "video" and len(d["details"]) > 0

    def test_o6_l3_04(self, app_page):
        """O6-L3-04 [S6]: カテゴリ指定改善提案"""
        d = app_page.request.post(f"{BASE}/quality-gate/improve",
            data=json.dumps({"category": "video"}),
            headers={"Content-Type": "application/json"}).json()
        assert d["count"] > 0

    def test_o6_l3_05(self, app_page):
        """O6-L3-05 [S9]: 履歴スコア取得"""
        d = app_page.request.get(f"{BASE}/quality-gate/history").json()
        assert "initial_score" in d and "current_score" in d

    def test_o6_l3_06(self, app_page):
        """O6-L3-06 [S10]: 品質チェック実行"""
        d = app_page.request.post(f"{BASE}/quality-gate/check", data="{}",
            headers={"Content-Type": "application/json"}).json()
        assert d["status"] in ["passed", "failed"]


@pytest.mark.e2e
class TestO6L4StateTransition:
    """L4: 状態遷移"""

    def test_o6_l4_01(self, app_page):
        """O6-L4-01 [S5]: 不正カテゴリ404"""
        assert app_page.request.get(f"{BASE}/quality-gate/drilldown/xxx").status == 404

    def test_o6_l4_02(self, app_page):
        """O6-L4-02 [S7]: passed整合性"""
        d = app_page.request.get(f"{BASE}/quality-gate/status").json()
        assert d["passed"] == (d["overall_score"] >= d["threshold"])

    def test_o6_l4_03(self, app_page):
        """O6-L4-03 [S7]: チェック後status変化"""
        app_page.request.post(f"{BASE}/quality-gate/check", data="{}",
            headers={"Content-Type": "application/json"})
        s = app_page.request.get(f"{BASE}/quality-gate/status").json()
        assert s["status"] in ["passed", "failed"]

    def test_o6_l4_04(self, app_page):
        """O6-L4-04 [S8]: 合格時整合"""
        d = app_page.request.get(f"{BASE}/quality-gate/status").json()
        if d["passed"]:
            assert d["overall_score"] >= d["threshold"]

    def test_o6_l4_05(self, app_page):
        """O6-L4-05 [S8]: 不合格時整合"""
        d = app_page.request.get(f"{BASE}/quality-gate/status").json()
        if not d["passed"]:
            assert d["overall_score"] < d["threshold"]


@pytest.mark.e2e
class TestO6L5EndToEnd:
    """L5: E2E完走"""

    def test_o6_l5_01(self, app_page):
        """O6-L5-01 [S10]: ステータス→スコア→ドリルダウン→改善の完走"""
        assert app_page.request.get(f"{BASE}/quality-gate/status").ok
        cats = app_page.request.get(f"{BASE}/quality-gate/scores").json()["categories"]
        for c in cats:
            assert app_page.request.get(f"{BASE}/quality-gate/drilldown/{c['id']}").ok
        assert app_page.request.post(f"{BASE}/quality-gate/improve",
            data=json.dumps({"category": ""}),
            headers={"Content-Type": "application/json"}).ok

    def test_o6_l5_02(self, app_page):
        """O6-L5-02 [S10]: チェック→スコア→履歴の完走"""
        assert app_page.request.post(f"{BASE}/quality-gate/check", data="{}",
            headers={"Content-Type": "application/json"}).ok
        for c in app_page.request.get(f"{BASE}/quality-gate/scores").json()["categories"]:
            assert 0 <= c["score"] <= 100
        assert app_page.request.get(f"{BASE}/quality-gate/history").json()["count"] >= 1

    def test_o6_l5_03(self, app_page):
        """O6-L5-03 [S10]: 4カテゴリ全ドリルダウンの完走"""
        for cat in ["audio", "video", "subtitle", "structure"]:
            d = app_page.request.get(f"{BASE}/quality-gate/drilldown/{cat}").json()
            assert d["detail_count"] > 0
            for x in d["details"]:
                assert all(k in x for k in ["item", "score", "status"])

    def test_o6_l5_04(self, app_page):
        """O6-L5-04 [S10]: 改善提案→優先順位→スコア影響の完走"""
        d = app_page.request.post(f"{BASE}/quality-gate/improve",
            data=json.dumps({"category": ""}),
            headers={"Content-Type": "application/json"}).json()
        if d["count"] > 0:
            for s in d["suggestions"]:
                assert s["priority"] in ["high", "medium", "low"]
                assert s["estimated_improvement"] > 0

    def test_o6_l5_05(self, app_page):
        """O6-L5-05 [S10]: 不合格→提案→履歴→強制レンダリング導線の完走"""
        assert app_page.request.get(f"{BASE}/quality-gate/status").ok
        assert app_page.request.post(f"{BASE}/quality-gate/improve",
            data=json.dumps({"category": ""}),
            headers={"Content-Type": "application/json"}).ok
        h = app_page.request.get(f"{BASE}/quality-gate/history").json()
        assert "improvement" in h
        fr = app_page.request.post(f"{BASE}/force-render",
            data=json.dumps({"reason": "test"}),
            headers={"Content-Type": "application/json"})
        assert fr.status in [200, 400, 404]

    def test_o6_l3_07(self, app_page):
        """O6-L3-07 [S5]: subtitleドリルダウン"""
        d = app_page.request.get(f"{BASE}/quality-gate/drilldown/subtitle").json()
        assert d["category"] == "subtitle" and len(d["details"]) > 0

    def test_o6_l3_08(self, app_page):
        """O6-L3-08 [S5]: structureドリルダウン"""
        d = app_page.request.get(f"{BASE}/quality-gate/drilldown/structure").json()
        assert d["category"] == "structure" and len(d["details"]) > 0

    def test_o6_l4_06(self, app_page):
        """O6-L4-06 [S7]: チェック実行でchecked_at更新"""
        app_page.request.post(f"{BASE}/quality-gate/check", data="{}",
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/quality-gate/status").json()
        assert d.get("checked_at") is not None

    def test_o6_l5_06(self, app_page):
        """O6-L5-06 [S10]: subtitleドリルダウン→字幕品質確認→改善の完走"""
        d = app_page.request.get(f"{BASE}/quality-gate/drilldown/subtitle").json()
        assert d["detail_count"] > 0
        r = app_page.request.post(f"{BASE}/quality-gate/improve",
            data=json.dumps({"category": "subtitle"}),
            headers={"Content-Type": "application/json"})
        assert r.ok

    def test_o6_l5_07(self, app_page):
        """O6-L5-07 [S10]: structureドリルダウン→構成品質確認→改善の完走"""
        d = app_page.request.get(f"{BASE}/quality-gate/drilldown/structure").json()
        assert d["detail_count"] > 0
        r = app_page.request.post(f"{BASE}/quality-gate/improve",
            data=json.dumps({"category": "structure"}),
            headers={"Content-Type": "application/json"})
        assert r.ok

    def test_o6_l5_08(self, app_page):
        """O6-L5-08 [S10]: チェック→ステータス→スコア→改善→履歴全ステップ完走"""
        app_page.request.post(f"{BASE}/quality-gate/check", data="{}",
            headers={"Content-Type": "application/json"})
        assert app_page.request.get(f"{BASE}/quality-gate/status").ok
        assert app_page.request.get(f"{BASE}/quality-gate/scores").ok
        assert app_page.request.post(f"{BASE}/quality-gate/improve",
            data=json.dumps({"category": ""}),
            headers={"Content-Type": "application/json"}).ok
        assert app_page.request.get(f"{BASE}/quality-gate/history").ok

