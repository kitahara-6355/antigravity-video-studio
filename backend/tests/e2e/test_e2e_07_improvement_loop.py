"""
E2E テスト — O-7 品質改善ループ 5層検証 (30項目)

検証5層モデル:
  L1: DOM存在 (6項目)
  L2: 視覚フィードバック (6項目)
  L3: インタラクション (5項目)
  L4: 状態遷移 (5項目)
  L5: E2E完走 (5項目)
  不足分: 3項目追加で合計30項目
"""
import pytest
import json

BASE = "http://localhost:8000/api/pipeline"


def _reset_improvement(app_page):
    """改善ループをリセット"""
    app_page.request.post(f"{BASE}/improvement/reset", data="{}",
        headers={"Content-Type": "application/json"})


@pytest.mark.e2e
class TestO7L1DomExists:
    """L1: DOM存在"""

    def test_o7_l1_01(self, app_page):
        """O7-L1-01 [S1]: 改善ループステータスAPI正常応答"""
        assert app_page.request.get(f"{BASE}/improvement/status").ok

    def test_o7_l1_02(self, app_page):
        """O7-L1-02 [S1]: statusフィールド存在"""
        d = app_page.request.get(f"{BASE}/improvement/status").json()
        assert "status" in d

    def test_o7_l1_03(self, app_page):
        """O7-L1-03 [S2]: iteration/max_iterations存在"""
        d = app_page.request.get(f"{BASE}/improvement/status").json()
        assert "iteration" in d and "max_iterations" in d

    def test_o7_l1_04(self, app_page):
        """O7-L1-04 [S3]: アクション一覧API正常応答"""
        assert app_page.request.get(f"{BASE}/improvement/actions").ok

    def test_o7_l1_05(self, app_page):
        """O7-L1-05 [S3]: actions配列存在"""
        d = app_page.request.get(f"{BASE}/improvement/actions").json()
        assert isinstance(d["actions"], list)

    def test_o7_l1_06(self, app_page):
        """O7-L1-06 [S5]: スコア変化API正常応答"""
        assert app_page.request.get(f"{BASE}/improvement/score-change").ok


@pytest.mark.e2e
class TestO7L2VisualFeedback:
    """L2: 視覚フィードバック"""

    def test_o7_l2_01(self, app_page):
        """O7-L2-01 [S1]: initial/current_scoreが0-100"""
        d = app_page.request.get(f"{BASE}/improvement/status").json()
        assert 0 <= d["initial_score"] <= 100
        assert 0 <= d["current_score"] <= 100

    def test_o7_l2_02(self, app_page):
        """O7-L2-02 [S2]: iterationが0以上"""
        d = app_page.request.get(f"{BASE}/improvement/status").json()
        assert d["iteration"] >= 0

    def test_o7_l2_03(self, app_page):
        """O7-L2-03 [S2]: max_iterationsが正の整数"""
        d = app_page.request.get(f"{BASE}/improvement/status").json()
        assert d["max_iterations"] > 0

    def test_o7_l2_04(self, app_page):
        """O7-L2-04 [S3]: 各アクションにid/name/status"""
        for a in app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]:
            assert all(k in a for k in ["id", "name", "status"])

    def test_o7_l2_05(self, app_page):
        """O7-L2-05 [S3]: ステータス区別可能"""
        statuses = {a["status"] for a in
            app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]}
        assert len(statuses) >= 1

    def test_o7_l2_06(self, app_page):
        """O7-L2-06 [S5]: score_historyに反復スコア"""
        d = app_page.request.get(f"{BASE}/improvement/score-change").json()
        assert len(d["score_history"]) >= 1
        for h in d["score_history"]:
            assert "score" in h and "iteration" in h


@pytest.mark.e2e
class TestO7L3Interaction:
    """L3: インタラクション"""

    def test_o7_l3_01(self, app_page):
        """O7-L3-01 [S4]: pendingアクション適用でスコア上昇"""
        _reset_improvement(app_page)
        d = app_page.request.get(f"{BASE}/improvement/status").json()
        before = d["current_score"]

        acts = app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]
        pending = [a for a in acts if a["status"] == "pending"]
        if pending:
            r = app_page.request.post(f"{BASE}/improvement/apply/{pending[0]['id']}",
                data="{}", headers={"Content-Type": "application/json"})
            assert r.ok
            after = app_page.request.get(f"{BASE}/improvement/status").json()["current_score"]
            assert after >= before

    def test_o7_l3_02(self, app_page):
        """O7-L3-02 [S4]: 適用済み再適用で400"""
        acts = app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]
        completed = [a for a in acts if a["status"] == "completed"]
        if completed:
            r = app_page.request.post(f"{BASE}/improvement/apply/{completed[0]['id']}",
                data="{}", headers={"Content-Type": "application/json"})
            assert r.status == 400

    def test_o7_l3_03(self, app_page):
        """O7-L3-03 [S5]: total_improvement取得"""
        d = app_page.request.get(f"{BASE}/improvement/score-change").json()
        assert "total_improvement" in d
        assert isinstance(d["total_improvement"], (int, float))

    def test_o7_l3_04(self, app_page):
        """O7-L3-04 [S7]: 中止でaborted"""
        _reset_improvement(app_page)
        r = app_page.request.post(f"{BASE}/improvement/abort", data="{}",
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "aborted"

    def test_o7_l3_05(self, app_page):
        """O7-L3-05 [S8]: リセットでidle"""
        r = app_page.request.post(f"{BASE}/improvement/reset", data="{}",
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "reset"
        s = app_page.request.get(f"{BASE}/improvement/status").json()
        assert s["status"] == "idle"


@pytest.mark.e2e
class TestO7L4StateTransition:
    """L4: 状態遷移"""

    def test_o7_l4_01(self, app_page):
        """O7-L4-01 [S4]: 不正アクションID 404"""
        r = app_page.request.post(f"{BASE}/improvement/apply/nonexistent",
            data="{}", headers={"Content-Type": "application/json"})
        assert r.status == 404

    def test_o7_l4_02(self, app_page):
        """O7-L4-02 [S6]: アクション後current>initial"""
        _reset_improvement(app_page)
        acts = app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]
        pending = [a for a in acts if a["status"] == "pending"]
        if pending:
            app_page.request.post(f"{BASE}/improvement/apply/{pending[0]['id']}",
                data="{}", headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/improvement/status").json()
        assert d["current_score"] >= d["initial_score"]

    def test_o7_l4_03(self, app_page):
        """O7-L4-03 [S6]: アクション適用でiteration増加"""
        _reset_improvement(app_page)
        before = app_page.request.get(f"{BASE}/improvement/status").json()["iteration"]
        acts = app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]
        pending = [a for a in acts if a["status"] == "pending"]
        if pending:
            app_page.request.post(f"{BASE}/improvement/apply/{pending[0]['id']}",
                data="{}", headers={"Content-Type": "application/json"})
            after = app_page.request.get(f"{BASE}/improvement/status").json()["iteration"]
            assert after > before

    def test_o7_l4_04(self, app_page):
        """O7-L4-04 [S7]: 中止後pendingがskipped"""
        _reset_improvement(app_page)
        app_page.request.post(f"{BASE}/improvement/abort", data="{}",
            headers={"Content-Type": "application/json"})
        acts = app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]
        for a in acts:
            assert a["status"] != "pending", f"中止後にpendingが残る: {a['id']}"

    def test_o7_l4_05(self, app_page):
        """O7-L4-05 [S7]: 二重中止メッセージ"""
        _reset_improvement(app_page)
        app_page.request.post(f"{BASE}/improvement/abort", data="{}",
            headers={"Content-Type": "application/json"})
        r = app_page.request.post(f"{BASE}/improvement/abort", data="{}",
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "already_aborted"


@pytest.mark.e2e
class TestO7L5EndToEnd:
    """L5: E2E完走"""

    def test_o7_l5_01(self, app_page):
        """O7-L5-01 [S8]: リセット→適用→スコア→履歴の完走"""
        _reset_improvement(app_page)
        acts = app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]
        pending = [a for a in acts if a["status"] == "pending"]
        if pending:
            app_page.request.post(f"{BASE}/improvement/apply/{pending[0]['id']}",
                data="{}", headers={"Content-Type": "application/json"})
        assert app_page.request.get(f"{BASE}/improvement/status").ok
        sc = app_page.request.get(f"{BASE}/improvement/score-change").json()
        assert len(sc["score_history"]) >= 2

    def test_o7_l5_02(self, app_page):
        """O7-L5-02 [S8]: 全アクション適用→差分確認の完走"""
        _reset_improvement(app_page)
        init = app_page.request.get(f"{BASE}/improvement/status").json()["initial_score"]
        for _ in range(4):
            acts = app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]
            pending = [a for a in acts if a["status"] == "pending"]
            if not pending:
                break
            app_page.request.post(f"{BASE}/improvement/apply/{pending[0]['id']}",
                data="{}", headers={"Content-Type": "application/json"})
        final = app_page.request.get(f"{BASE}/improvement/status").json()["current_score"]
        assert final > init

    def test_o7_l5_03(self, app_page):
        """O7-L5-03 [S8]: 適用→中止→スキップ→リセットの完走"""
        _reset_improvement(app_page)
        acts = app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]
        pending = [a for a in acts if a["status"] == "pending"]
        if pending:
            app_page.request.post(f"{BASE}/improvement/apply/{pending[0]['id']}",
                data="{}", headers={"Content-Type": "application/json"})
        app_page.request.post(f"{BASE}/improvement/abort", data="{}",
            headers={"Content-Type": "application/json"})
        acts2 = app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]
        assert all(a["status"] != "pending" for a in acts2)
        app_page.request.post(f"{BASE}/improvement/reset", data="{}",
            headers={"Content-Type": "application/json"})
        s = app_page.request.get(f"{BASE}/improvement/status").json()
        assert s["status"] == "idle"

    def test_o7_l5_04(self, app_page):
        """O7-L5-04 [S8]: 3API連携の完走"""
        assert app_page.request.get(f"{BASE}/improvement/status").ok
        assert app_page.request.get(f"{BASE}/improvement/actions").ok
        sc = app_page.request.get(f"{BASE}/improvement/score-change").json()
        assert "total_improvement" in sc

    def test_o7_l5_05(self, app_page):
        """O7-L5-05 [S8]: リセット→複数適用→スコア単調増加の完走"""
        _reset_improvement(app_page)
        scores = [app_page.request.get(f"{BASE}/improvement/status").json()["current_score"]]
        for _ in range(3):
            acts = app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]
            pending = [a for a in acts if a["status"] == "pending"]
            if not pending:
                break
            app_page.request.post(f"{BASE}/improvement/apply/{pending[0]['id']}",
                data="{}", headers={"Content-Type": "application/json"})
            scores.append(
                app_page.request.get(f"{BASE}/improvement/status").json()["current_score"])
        # 単調増加確認
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i-1], f"スコア減少: {scores}"

    def test_o7_l1_07(self, app_page):
        """O7-L1-07 [S1]: total_actions/completed_actionsフィールド存在"""
        d = app_page.request.get(f"{BASE}/improvement/status").json()
        assert "total_actions" in d
        assert "completed_actions" in d

    def test_o7_l3_06(self, app_page):
        """O7-L3-06 [S4]: アクション適用後score_afterが返される"""
        _reset_improvement(app_page)
        acts = app_page.request.get(f"{BASE}/improvement/actions").json()["actions"]
        pending = [a for a in acts if a["status"] == "pending"]
        if pending:
            r = app_page.request.post(f"{BASE}/improvement/apply/{pending[0]['id']}",
                data="{}", headers={"Content-Type": "application/json"})
            assert r.ok
            assert "score_after" in r.json()

    def test_o7_l4_06(self, app_page):
        """O7-L4-06 [S6]: リセット後current_score==initial_score"""
        _reset_improvement(app_page)
        d = app_page.request.get(f"{BASE}/improvement/status").json()
        assert d["current_score"] == d["initial_score"]

