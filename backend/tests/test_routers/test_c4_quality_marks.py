"""R1.5-C4 — 本番から到達できる「品質スコア」が実測を名乗らないことの契約。

5周かけて**毎回「同じクラスの別経路」を見落としてきた**（1周目は testpaths 外、
4周目は1ファイル隣、5周目は直した方が死蔵だった）。ここで押さえるのは、
`gate-verifier` 5周目の後に総当たりで見つかった残りの4経路:

| 経路 | 何を偽っていたか |
|---|---|
| `pipeline_router` O-7 品質改善ループ | 72→85 のスコア推移。`improvement = 4  # シミュレーション` |
| `/api/admin/integration/tool/quality-score` | `score: 92, rank: "A"` + 現在時刻 |
| `/api/admin/incident/quality-degradation` | `current_score: 72` + 現在時刻 |
| `director_engine.calculate_quality_score()` の except | 採点が落ちても `is_acceptable: True` |

最後の1件がいちばん重い。**UI（`frontend/src/components/DirectorBriefing.jsx:531,552`）が
`is_acceptable` で緑の「制作開始 (Go)」を出す**ので、採点が一度も走らなくても
「合格しました」と見える。

台帳: `backend/config/feature_gaps.json`
"""

import os
import sys
import types

# ワークツリーのルートと backend を sys.path に追加する
current_dir = os.path.dirname(os.path.abspath(__file__))
tests_dir = os.path.dirname(current_dir)
backend_dir = os.path.dirname(tests_dir)
root_dir = os.path.dirname(backend_dir)

if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# routers/__init__.py 経由のロード（重い依存の連鎖）を避ける
if "routers" not in sys.modules:
    routers_mod = types.ModuleType("routers")
    routers_mod.__path__ = [os.path.join(backend_dir, "routers")]
    sys.modules["routers"] = routers_mod

import pytest


# ── 本番でこのブロックに属する経路（印が要る範囲） ──
#
# 前置きだけで数える。**新しい経路を足して印を忘れたら下の総当たりで落ちる。**
DEMO_PREFIXES = ("/api/pipeline/quality-gate", "/api/pipeline/improvement")


@pytest.fixture(autouse=True)
def インメモリ状態を戻す():
    """`_improvement_state` はモジュール変数なので、テスト間で汚れる。

    `apply` は同じ action を2回受け付けない（2回目は 400）。順序依存で
    落ちないよう、1件ずつ元に戻す。
    """
    import copy

    from routers.pipeline_router import _improvement_state, _quality_gate_state

    改善 = copy.deepcopy(_improvement_state)
    ゲート = copy.deepcopy(_quality_gate_state)
    yield
    _improvement_state.clear()
    _improvement_state.update(改善)
    _quality_gate_state.clear()
    _quality_gate_state.update(ゲート)


@pytest.fixture(name="pipeline_client")
def pipeline_client_fixture():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.pipeline_router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _呼ぶ(client, method, path):
    """path パラメータを埋めて 1 回叩く。"""
    path = path.replace("{category}", "audio").replace("{action_id}", "act-003")
    body = {"category": "audio"}
    return client.get(path) if method == "GET" else client.post(path, json=body)


def test_品質ゲートと改善ループの全経路が固定値の印を返す(pipeline_client):
    """**O-6 と O-7 の応答は1つ残らず「実在の数字ではない」と名乗る**（R1.5-C4）。

    どちらも `pipeline_default_states` の定数を返しているだけで、
    音声も映像も一度も読んでいない。O-6 は5周目に印を付けたが、
    **190行下の O-7 は無印のまま残っていた**（72→85 のスコア推移）。
    """
    from routers.pipeline_router import router

    印なし = []
    for route in router.routes:
        path = getattr(route, "path", "")
        if not path.startswith(DEMO_PREFIXES):
            continue
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            resp = _呼ぶ(pipeline_client, method, path)
            if resp.status_code != 200:
                印なし.append((method, path, resp.status_code))
                continue
            payload = resp.json()
            if not isinstance(payload, dict) or payload.get("is_real") is not False:
                印なし.append((method, path, str(payload)[:120]))

    assert not 印なし, 印なし


def test_改善ループのスコアは加点をシミュレートしたものだと名乗る(pipeline_client):
    """`+4点` は動画を直した結果ではない（R1.5-C4）。

    `apply` は `improvement = 4` を足しているだけで、
    レンダリングもエンコードもやり直していない。
    """
    data = pipeline_client.get("/api/pipeline/improvement/score-change").json()

    assert data["is_real"] is False
    assert data["data_source"] == "sample"

    applied = pipeline_client.post("/api/pipeline/improvement/apply/act-003").json()
    assert applied["is_real"] is False


def test_品質ゲートの検査時刻に現在時刻を打たない(pipeline_client):
    """検査していないのに「いま検査した」と言わない（R1.5-C4・5周目 C-6 の回帰止め）。"""
    from routers.pipeline_router import _quality_gate_state

    before = _quality_gate_state.get("checked_at")
    pipeline_client.post("/api/pipeline/quality-gate/check")
    assert _quality_gate_state.get("checked_at") == before


# ── admin デモ層に残っていた品質スコア ──


def test_ツール品質スコアが実測を名乗らない():
    """`/api/admin/integration/tool/quality-score`（R1.5-C4）。

    `score: 92 / rank: "A"` を現在時刻つきで返していた。
    2周目・4周目・5周目で直した `last_sync = now()` と同型。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.admin_integration_router import router

    app = FastAPI()
    app.include_router(router)
    data = TestClient(app).get("/api/admin/integration/tool/quality-score").json()

    assert data["is_real"] is False
    assert data["data_source"] == "sample"
    assert data["timestamp"] is None


def test_品質低下の検知が実測を名乗らない():
    """`/api/admin/incident/quality-degradation`（R1.5-C4）。

    `current_score: 72` と3点の推移を現在時刻つきで返していた。
    **一度も測っていない品質低下を「検知した」と言っていた。**
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.admin_incident_router import router

    app = FastAPI()
    app.include_router(router)
    data = TestClient(app).get("/api/admin/incident/quality-degradation").json()

    assert data["is_real"] is False
    assert data["data_source"] == "sample"
    assert data["timestamp"] is None


# ── 本線の品質スコア（UI に出る） ──


def test_採点に失敗したら合格と名乗らない():
    """**`is_acceptable` は採点できたときにしか True にならない**（R1.5-C4）。

    `DirectorBrain.calculate_quality_score()` は例外を握って
    `score: 50 / is_acceptable: True` を返していた。UI はこの値で
    緑の「制作開始 (Go)」を出す（`DirectorBriefing.jsx:531,552,554`）ので、
    **API が落ちていても「合格しました」と見えていた。**
    """
    import json

    from director_engine import DirectorBrain

    brain = DirectorBrain()

    class _落ちるクライアント:
        class models:
            @staticmethod
            def generate_content(*_a, **_k):
                raise RuntimeError("APIキーが無効です")

    brain.client = _落ちるクライアント()
    result = json.loads(brain.calculate_quality_score([{"scene": 1}], "Novice"))

    assert result["is_acceptable"] is False, "採点が落ちたのに合格と名乗った"
    assert result["is_real"] is False
    assert result["score"] is None, "採点していないのに点を名乗った"
