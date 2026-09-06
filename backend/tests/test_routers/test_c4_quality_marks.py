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
def 実体のモジュールを使う():
    """他のテストが `sys.modules` に残した MagicMock を掃除する。

    `test_render_router.py` などが `patch.dict("sys.modules", {...})` で
    `branding_manager` を差し替えたまま漏らすことがある。**単体では緑なのに
    CI の全件実行だけ落ちる**という形で実際に踏んだ（`ae93f60` の CI
    run 33232106707）。私の判定が「前に走ったテストの後始末」で変わらないよう、
    **モジュールでないものだけ**を落とす（実体はそのまま使う）。
    """
    import sys
    import types

    for 名 in ("branding_manager", "branding.analytics_manager",
               "director_engine", "quality_gate_agent"):
        m = sys.modules.get(名)
        if m is not None and not isinstance(m, types.ModuleType):
            del sys.modules[名]
    yield


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


# ── 6周目の指摘（gate-verifier）──────────────────────────────────────
#
# 6周目の総当たりは **GET だけ**だったので、POST 側に2件残っていた。
# どちらも本番マウント済み・死蔵ではない・`8eef716` から変わっていない。


def test_公開後フィードバックは作り物を実績と呼ばない():
    """`POST /api/youtube/feedback-loop/{id}`（R1.5-C4・6周目 指摘1）。

    `post_publish_collector` の既定は `YOUTUBE_API_MODE=mock` で、
    `_generate_mock_data()` が `random.Random(seed)` で CTR・維持率・再生数を
    組み立てる（`real` は `NotImplementedError`＝**本番の既定で必ず作り物**）。
    それを `validation_report.actual` として `success: true` で返し、
    **`evolution_log.json`（Git 追跡下）へ現在時刻つきで焼き付け**、
    `GET /api/evolution` と `POST /api/youtube/pre-plan` が読み戻していた。

    `POST /api/youtube/retention-map` を 501 で止めたのと同じ扱いにする。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.youtube_optimizer import router

    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app, raise_server_exceptions=False).post(
        "/api/youtube/feedback-loop/W-テスト"
    )

    assert resp.status_code == 501, f"作り物の実績で {resp.status_code} を返した"
    detail = resp.json()["detail"]
    assert detail["implemented"] is False
    assert detail["feature"] == "post_publish_feedback"
    assert detail["ledger"] == "backend/config/feature_gaps.json"


def test_作り物の実績を台帳に書かない(tmp_path, monkeypatch):
    """`_record_post_publish_feedback` は `is_mock` を弾く（R1.5-C4・6周目 指摘1）。

    呼び出し元が 501 で止めるので通常ここには来ないが、
    **この台帳は Git 追跡下で、一度書くと残る。**二重に止める。
    """
    from routers import youtube_optimizer

    書いた = []
    monkeypatch.setattr(youtube_optimizer, "safe_load_json",
                        lambda *_a, **_k: 書いた.append("読んだ") or {})

    youtube_optimizer._record_post_publish_feedback(
        wagamama_id="W-テスト", video_id="vid",
        actual_metrics={"is_mock": True, "metrics": {"click_through_rate": 5.2}},
        validation={"analysis": {}},
    )
    assert not 書いた, "作り物なのに台帳を開いた"


def test_企画立案は作り物の学びを混ぜない(monkeypatch):
    """`POST /api/youtube/pre-plan` の学び収集（R1.5-C4・6周目 指摘1）。

    `evolution_log.json` には mock 時代の「実績」が12件焼き付いている
    （`actual_ctr 5.2` / `actual_retention 65.0` / `actual_views 1000`）。
    `is_real: true` が無い行は作り物とみなす（fail-closed）。

    **このテストは以前ソース文字列の grep だった**（`assert 'fb.get("is_real")
    is True' in src`）。挙動を一度も呼んでいないので、**絞り込みを外しても
    文字列がコメントに残るだけで緑のまま**だった（gate-verifier 7周目 指摘2 で
    変異生存が実測された）。挙動で見る形に書き直した。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import youtube_optimizer

    台帳 = {"post_publish_feedbacks": [
        {"wagamama_id": "偽", "actual_ctr": 5.2,
         "lessons_learned": ["これは作り物の学びです"]},
        {"wagamama_id": "真", "is_real": True, "actual_ctr": 3.1,
         "lessons_learned": ["これは実測の学びです"]},
    ]}

    class _在るパス:
        @staticmethod
        def exists():
            return True

    monkeypatch.setattr(youtube_optimizer, "_writable_path",
                        lambda *_a, **_k: _在るパス())
    monkeypatch.setattr(youtube_optimizer, "safe_load_json",
                        lambda *_a, **_k: 台帳)

    app = FastAPI()
    app.include_router(youtube_optimizer.router)
    data = TestClient(app, raise_server_exceptions=False).post(
        "/api/youtube/pre-plan", json={"topic": "一人キャンプ飯"}
    ).json()

    学び = data.get("past_lessons") or []
    assert "これは作り物の学びです" not in 学び,         "作り物の『実績』から出た学びを企画立案に混ぜた"
    assert "これは実測の学びです" in 学び,         "実測の学びまで落としている（門が広すぎる）"


def test_チャンネル統計が実測を名乗らない():
    """`POST /api/analytics/sync` と `/simulate`（R1.5-C4・6周目 指摘2）。

    出所は `branding/analytics_manager.py` の `mock_my_stats`
    （`# TODO: Replace with real YouTube API call`）。
    **登録者数と総再生数は収益化の到達度そのもの。**
    `simulate` で注入した数字が `sync` から実績の顔で出てきており、
    **収益化の閾値（登録者1,000人）を任意に超えた数字が通っていた。**
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.trinity import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    sync = client.post("/api/analytics/sync").json()
    assert sync["is_real"] is False
    assert sync["data_source"] == "sample"
    assert sync["stats"]["is_real"] is False
    assert sync["stats"]["last_updated"] is None, "同期していないのに同期時刻を打った"

    sim = client.post("/api/analytics/simulate?views=500000").json()
    assert sim["is_real"] is False
    assert sim["sync"]["stats"]["is_real"] is False


def test_成長ログの作り物に印が付く(monkeypatch):
    """`GET /api/evolution` / `GET /api/director/evolution`（R1.5-C4・6周目 指摘1）。

    **印を付ける場所は1箇所**（`get_evolution_log_for_display()`）。
    1経路ずつ塞ぐと「同じクラスの別経路」になる。
    保存側（`get_evolution_log()`）は素のままで、印はファイルへ書き戻らない。

    実ファイルの中身に依存すると、行が空のときに黙って素通りする空振りテストに
    なるので（**変異テストで実際にそうなっていた**）、既知の中身を差して見る。
    """
    from branding_manager import branding_manager

    作り物 = {"timestamp": "2026-06-08T09:05:08", "wagamama_id": "waga_001",
              "actual_ctr": 5.2, "actual_retention": 65.0, "actual_views": 1000}
    実績 = {"timestamp": "2026-08-29T00:00:00", "wagamama_id": "waga_002",
            "is_real": True, "actual_ctr": 3.1}
    元の台帳 = {"entries": [], "post_publish_feedbacks": [作り物, 実績]}

    monkeypatch.setattr(branding_manager, "get_evolution_log",
                        lambda: {**元の台帳,
                                 "post_publish_feedbacks": [dict(作り物), dict(実績)]})

    行 = branding_manager.get_evolution_log_for_display()["post_publish_feedbacks"]

    assert 行[0]["is_real"] is False, "作り物の『実績』に印が付いていない"
    assert 行[0]["data_source"] == "sample"
    assert 行[0]["actual_ctr"] == 5.2, "元の値を落としてはいけない"
    assert 行[1]["is_real"] is True, "本物の実績に作り物の印を付けた"
    assert "data_source" not in 行[1]

    # 印が保存側へ書き戻らないこと
    assert "data_source" not in 作り物


# ── 7周目に向けた自前の POST 掃引で見つかったもの ──────────────────
#
# 6周目の指摘で「総当たりが GET だけだった」と分かったので、POST も掃いた。
# 4カテゴリに当たる POST 50 経路のうち、200 で無印だったのは 12 件。
# そのうち条件文の「品質スコア」に当たるのが下の2件だった。


def test_見るものが無ければ品質は満点にならない():
    """`POST /api/quality/check` と `/verify`（R1.5-C4）。

    `_calculate_score()` は 100 点から減点する形なので、**入力が空だと
    減点対象が1つも見つからず必ず 100 点になる。**空の body を投げると
    `{"is_ready": true, "score": 100, "summary": "✅ 優秀な品質です。
    レンダリングを推奨します。"}` が返っていた。**動画を1フレームも
    見ていないのに「優秀・レンダリング推奨」。**

    4周目 C-5（`/api/review/summary` が1項目も採点せず 100.0）と同型。
    ただし**あちらは死蔵で、こちらはフロントエンドが呼ぶ本番経路**
    （`frontend/src/gateway/endpoints.js`）。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.quality import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    for path in ("/api/quality/check", "/api/quality/verify"):
        data = client.post(path, json={}).json()
        assert data["scored"] is False, f"{path}: 何も渡していないのに採点したと言った"
        assert data["score"] is None, f"{path}: 見ていないのに点を名乗った"
        assert data["is_ready"] is False, f"{path}: 見ていないのに合格と言った"

    # 材料があるときは従来どおり採点する（門が広すぎないこと）
    採点 = client.post("/api/quality/check",
                       json={"full_text": "これは検査対象の脚本です。"}).json()
    assert 採点["scored"] is True
    assert isinstance(採点["score"], int)


def test_QAエンジンが落ちたら進行可能と言わない():
    """`DirectorBrain.verify_production_quality()` の except（R1.5-C4）。

    `is_ready: True / score: 80 / 「自動チェックに失敗しましたが、進行可能です。」`
    を返していた。**QA エンジンが一度も走っていなくてもレンダリングへ進めた。**
    `calculate_quality_score()` の except を直したのと同じ形。
    """
    import json

    from director_engine import DirectorBrain

    brain = DirectorBrain()

    class _落ちるクライアント:
        class models:
            @staticmethod
            def generate_content(*_a, **_k):
                raise RuntimeError("接続できません")

    brain.client = _落ちるクライアント()
    result = json.loads(brain.verify_production_quality("脚本", [{"name": "s1"}], [{"text": "t"}]))

    assert result["is_ready"] is False, "検査が落ちたのに進行可能と言った"
    assert result["score"] is None, "検査していないのに点を名乗った"
    assert result["is_real"] is False
    assert "QAエンジンエラー" in result["final_verdict"]


# ── 7周目の指摘（gate-verifier）──────────────────────────────────────


def test_成長ログの読み口が3つとも印を通る():
    """**印を付ける場所は1つ**（R1.5-C4・7周目 指摘1）。

    6周目に `branding_manager.get_evolution_log_for_display()` へ集約し、
    その docstring に「読み口が2つあるので1箇所にする」と書いた。
    **読み口は3つあった。**

    | 読み口 | 経路 |
    |---|---|
    | `GET /api/evolution` | `routers/trinity.py` |
    | `GET /api/director/evolution` | `routers/legacy_director_router.py` |
    | `GET /api/v1/mcp/resources/evolution_log` | `mcp_server.py` |

    3つ目は `branding_manager` を通らず JSON を直接読むので、集約点を
    **迂回して印の無い `actual_ctr: 5.2` を 200 で返していた。**
    印そのものを `backend/evolution_log_marks.py` へ出し、
    **両方がそこに依存する**形にした。
    """
    import mcp_server
    from evolution_log_marks import 実績に印を付ける

    台帳 = {"post_publish_feedbacks": [
        {"wagamama_id": "偽", "actual_ctr": 5.2},
        {"wagamama_id": "真", "is_real": True, "actual_ctr": 3.1},
    ]}

    # 集約点そのもの
    行 = 実績に印を付ける(台帳)["post_publish_feedbacks"]
    assert 行[0]["is_real"] is False and 行[0]["data_source"] == "sample"
    assert 行[1]["is_real"] is True and "data_source" not in 行[1]
    assert "is_real" not in 台帳["post_publish_feedbacks"][0], "元の dict を書き換えた"

    # 第3の読み口が集約点を通っていること
    assert mcp_server.MCP_RESOURCES["evolution_log"]["loader"].__code__.co_names, \
        "loader が読めない"
    src = __import__("inspect").getsource(mcp_server._印つきで読む)
    assert "実績に印を付ける" in src


def test_MCPの読み口が印つきで返す(monkeypatch):
    """`GET /api/v1/mcp/resources/evolution_log` の実体（R1.5-C4・7周目 指摘1）。"""
    import mcp_server

    台帳 = {"post_publish_feedbacks": [{"wagamama_id": "偽", "actual_ctr": 5.2}]}
    monkeypatch.setattr(mcp_server, "_load_json_safely", lambda *_a, **_k: 台帳)

    出力 = mcp_server.MCP_RESOURCES["evolution_log"]["loader"]()
    行 = 出力["post_publish_feedbacks"]

    assert 行[0]["is_real"] is False, "MCP の読み口が印なしで作り物を返した"
    assert 行[0]["data_source"] == "sample"


def test_MCPの品質スコアは見ていないのに0点を返さない(monkeypatch):
    """`mcp_server._calculate_quality_score`（R1.5-C4・7周目）。

    `round(completed / max(len(stages), 1) * 100)` なので、**ステージが
    1つも無いと `0/1*100 = 0` になり、未計測が「0点」として出ていた。**
    条件文が名指しする「常に 0.0 になる quality_score」と同型。
    """
    import mcp_server

    未計測 = mcp_server._calculate_quality_score({"stages": [], "approved_at": None})
    assert 未計測["score"] is None, "見ていないのに 0 点を返した"
    assert 未計測["scored"] is False

    採点 = mcp_server._calculate_quality_score(
        {"stages": [{"completed": True}, {"completed": False}]})
    assert 採点["scored"] is True
    assert 採点["score"] == 50


def test_中身の無い入れ物では品質を採点しない():
    """材料の門が緩すぎないこと（R1.5-C4・7周目の副次指摘）。

    `POST /api/quality/check {"scenes":[{}]}`（空の dict 1個）が
    `score: 100 / 「✅ 優秀な品質です。レンダリングを推奨します。」` を
    通していた。4検査のうち3つは空を見たままだった。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.quality import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    for body in ({"scenes": [{}]}, {"segments": [{}]}, {"scenes": [{"name": ""}]}):
        data = client.post("/api/quality/check", json=body).json()
        assert data["scored"] is False, f"{body}: 中身が無いのに採点した"
        assert data["score"] is None, f"{body}: 見ていないのに点を名乗った"

    # 中身があれば従来どおり採点する（門が広すぎないこと）
    採点 = client.post("/api/quality/check",
                       json={"scenes": [{"name": "冒頭", "source_type": "LIVE"}]}).json()
    assert 採点["scored"] is True


# ── 8周目の指摘と、本文ベースの掃引で見つけたもの ──────────────────
#
# 8周目の指摘で分かった構造的な穴: **過去8周の掃引はパス文字列で母集団を作っていた。**
# `/api/render/start` はパスに4カテゴリの語を1つも持たないが、
# **応答本文に `quality_score` を持つ。**絞り込みを本文へ移して掃き直した。


def test_書き出し前の品質は本線の実測を読む():
    """`POST /api/render/start`（R1.5-C4・8周目の指摘）。

    `_get_quality_score()` は `return 95` の直書きだった。そのせいで:

    - 何も測っていないのに `quality_score: 95` を `success: true` で返し
    - **S17 の品質ブロック（`< 90`）が永久に偽**になり一度も止まらず
    - `force_render` が意味を失っていた

    本線（`pipeline_coordinator._write_quality_sidecar`）は最終動画の隣へ
    `*.quality.json` を書いている。**その文書自身が「消費者として宣言していた
    render は quality_score しか読んでおらず」と書いていた** —
    宣言していた消費者が、実は読んでいなかった。
    """
    import json as _json
    import unittest.mock as _m
    from pathlib import Path

    from routers import render as R

    # **ソース文字列の grep はしない。**7周目に「文字列がコメントに残るだけで
    # 通る」空振りを指摘されたので、挙動だけで見る

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "final_x.quality.json").write_text(
            _json.dumps({"score": 89}), encoding="utf-8")
        with _m.patch.object(R, "_writable_path", return_value=Path(d)):
            # サイドカーがあればその点を読む
            assert R._品質の実測("final_x.mp4")[0] == 89, "実測を読めていない"
            # 無ければ点を名乗らない
            assert R._品質の実測("final_無い.mp4")[0] is None, "測っていないのに点を返した"


def test_レビューできなかったら合格と言わない():
    """`SelfReviewEngine._fallback_review()`（R1.5-C4・8周目の本文掃引）。

    docstring が**「フォールバックレビュー（デフォルト合格）」**で、
    `passed: True / overall: 0.75` を返していた。
    `POST /api/antigravity/self-review/check` が本番にマウントされており、
    **AI レビューが一度も走らなくても `{"passed": true, "score": 0.75}`**
    が返っていた。`calculate_quality_score` /
    `verify_production_quality` と同じクラスの3件目。
    """
    from self_review_engine import SelfReviewEngine

    engine = SelfReviewEngine.__new__(SelfReviewEngine)
    r = engine._fallback_review()

    assert r.passed is False, "レビューしていないのに合格と言った"
    assert r.score.details.get("scored") is False
    assert r.score.details.get("is_real") is False
    assert r.issues, "採点していないことを伝えていない"


def test_ライバルの登録者数が実測を名乗らない():
    """`AnalyticsManager.scout_rivals()`（R1.5-C4・8周目の本文掃引）。

    `mock_rival_db` の固定値（TechStarter 180人 / TechMastery 15,000人）から
    `random.choice` で選ぶだけで、YouTube を検索してもいない。
    `GET /api/status` がこれを `subs` / `views` つきで返す。
    """
    from branding.analytics_manager import AnalyticsManager

    m = AnalyticsManager()
    r = m.scout_rivals({"subscribers": 150})

    assert r["is_real"] is False, "作り物のライバルに印が無い"
    assert r["data_source"] == "sample"


def test_進化ログツールが実測を名乗らない():
    """`GET /api/admin/integration/tool/evolution-log`（R1.5-C4・8周目）。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.admin_integration_router import router

    app = FastAPI()
    app.include_router(router)
    d = TestClient(app).get("/api/admin/integration/tool/evolution-log").json()

    assert d["is_real"] is False
    assert d["data_source"] == "sample"


# ── 9周目の指摘 — 未計測の番兵値が生産側 0.0 / 判定側 None で食い違っていた ──
#
# 8周目に入れた門は `None` を未計測の印にしていたが、**生産側
# （`PipelineContext.quality_score`）の既定は `0.0`（float）**なので、
# 未計測の枝に**本番から到達できなかった**。0.0 は実際に取りうる点なので、
# 値の側で「無い」を表そうとすると必ず取り違える。
# **「測ったかどうか」を値と別に持つ**（`quality_scored`）ことで根を断つ。


def test_採点したかどうかを値と別に持つ():
    """`PipelineContext.quality_scored`（R1.5-C4・9周目の指摘）。

    立てるのは `QualityGateWorker` だけ。**既定は False。**
    """
    from agents.pipeline_types import PipelineContext
    from core.context import ProductionContext

    ctx = PipelineContext(video_path="d.mp4", session_id="s1")
    assert ctx.quality_scored is False, "既定で採点済みになっている"
    assert ctx.quality_score == 0, "既定値は 0 のまま（消費側が多いので変えない）"

    # 旧い方の context にも同じ取り違えがあったので揃える
    pc = ProductionContext()
    assert pc.quality_scored is False
    assert pc.quality_score == 0.0


def test_実行結果に採点の有無が載る():
    """`_build_result` が `quality_scored` を持ち回す（R1.5-C4・9周目）。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent.parent
           / "agents" / "pipeline_coordinator.py").read_text(encoding="utf-8")
    # 挙動で見たいが `_build_result` は大量の ctx を要求するので、
    # ここでは載っていることだけ確かめ、表示側は下の2件で挙動を見る
    assert '"quality_scored"' in src
    assert '"scored": getattr(ctx, "quality_scored", False)' in src


def test_レポートは未計測を0点と書かない():
    """`GET /api/pipeline/report`（R1.5-C4・9周目 指摘B）。

    生産側が出す `quality_details["score"] = 0.0` をそのまま
    「総合スコア: **0.0点**」と HTML に埋めていた。しかも HTML の埋め込みは
    `採点した` の門をまったく通っていなかった。
    """
    from routers.pipeline_report import _品質の表示

    assert _品質の表示({"score": 0.0}) == "未計測（品質ゲートを通していません）"
    assert _品質の表示({"score": 0.0, "scored": False}) == \
        "未計測（品質ゲートを通していません）"
    assert _品質の表示({"score": 0.0, "scored": True}) == "0.0点", \
        "採点した 0 点は 0 点と書く（未計測と混ぜない）"
    assert _品質の表示({"score": 89, "scored": True}) == "89点"


def test_書き出しは未計測なら止まる():
    """`POST /api/render/start`（R1.5-C4・2026-08-29 ユーザー決定）。

    **`force_render` でも越えられない。** 90点未満なら「悪いと分かったうえで
    出す」判断ができるが、未計測は判断の材料そのものが無い。
    UI は `force_render: !is_ready` で常に押してくるので、越えられるように
    すると門が無いのと同じになる。

    止めても実作業は1つも止まらない — **この経路は何もレンダリングしていない**
    （`_render_jobs` に dict を登録するだけ）。本線は `RenderWorker` で書き出す。
    """
    import unittest.mock as _m

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import render as R

    app = FastAPI()
    app.include_router(R.router)
    client = TestClient(app, raise_server_exceptions=False)

    with _m.patch.object(R, "_品質の実測", return_value=(None, None)), \
         _m.patch.object(R, "detect_gpu",
                         return_value={"gpu_available": False,
                                       "recommended_encoder": "libx264"}):
        for body in ({}, {"force_render": True}):
            d = client.post("/api/render/start", json=body).json()
            assert d["success"] is False, f"{body}: 未計測なのに通した"
            assert d["error"] == "quality_unmeasured"
            assert d["force_render_available"] is False


def test_書き出しの点はその動画のもの():
    """`_品質の実測()` は**動画を指定しないと点を返さない**（R1.5-C4・9周目）。

    8周目は「最新の `*.quality.json` を mtime で1件」返していたので、
    **直前に測った別の動画の点**が `is_real: true / data_source: "derived"`
    としてこの書き出しに付いていた。**どの動画の点か分からないなら実測ではない。**
    """
    import json as _json
    import tempfile
    import unittest.mock as _m
    from pathlib import Path

    from routers import render as R

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "final_A.quality.json").write_text(
            _json.dumps({"score": 89}), encoding="utf-8")

        with _m.patch.object(R, "_writable_path", return_value=Path(d)):
            assert R._品質の実測() == (None, None), "動画を言わずに点を得た"
            assert R._品質の実測("存在しない.mp4") == (None, None)
            点, 出所 = R._品質の実測("final_A.mp4")
            assert 点 == 89
            assert 出所.endswith("final_A.quality.json")


def test_品質ゲートを通ったら旗が立つ():
    """`QualityGateWorker` が `ctx.quality_scored` を**実際に立てる**
    （R1.5-C4・gate-verifier 10周目 N-2・空振り①）。

    9周目に旗そのものは足したが、**立つことを確かめるテストが1件も無かった。**
    `quality_gate_worker.py` の `ctx.quality_scored = True` を消しても
    **26件が緑のまま**だった（変異が生存）。

    旗が立たなければ `GET /api/pipeline/report` の⑤行と
    `POST /api/render/start` は**採点済みの実走まで「未計測」で止める**。
    fail-closed 側なので偽の success にはならないが、**門が常に閉じるなら
    門が無いのと同じ**（9周目に「旗が常に同じ値なら何も変えていない」と
    書いたのと同型）。
    """
    import asyncio

    from agents.pipeline_types import PipelineContext
    from agents.workers.quality_gate_worker import QualityGateWorker

    ctx = PipelineContext(video_path="d.mp4", session_id="s-flag")
    ctx.segments = [{"text": "あ", "start": 0.0, "end": 1.0}]
    ctx.declared_gaps = set()  # 台帳の読み込みを避ける（実行は止めない）

    assert ctx.quality_scored is False, "実行前から採点済みになっている"

    asyncio.run(QualityGateWorker().execute(ctx))

    assert ctx.quality_scored is True, \
        "品質ゲートを通したのに旗が立たない（門が常に閉じる＝門が無いのと同じ）"
    assert isinstance(ctx.quality_score, (int, float)), "点が入っていない"


def test_レポートの品質行が未計測を0点と書かない():
    """`GET /api/pipeline/report` の**⑤行**（R1.5-C4・10周目 N-2・空振り②）。

    9周目の欠陥そのものを戻す変異——`採点した` を値判定
    （`isinstance(quality_score, (int, float))`）に戻す——で
    **26件が緑のまま**だった。

    既存の `test_レポートは未計測を0点と書かない` が守っているのは
    `_品質の表示()`（HTML 埋め込み側）で、**⑤行は別の場所に同じ判定を
    持っている**。生産側の既定は `score: 0.0`（float）なので、値で判定すると
    未計測の実走が「スコア: 0点 / カテゴリ: 0点」に戻る。

    **経路経由で見る**（直接呼べる関数が無いため）。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import pipeline_report as PR
    from routers.pipeline_router import _pipeline_state

    app = FastAPI()
    app.include_router(PR.router)  # router 側が prefix="/api/pipeline" を持つ
    client = TestClient(app, raise_server_exceptions=False)

    元の状態 = dict(_pipeline_state)
    try:
        # 生産側が未計測のときに実際に出す形。**`score` は 0.0 が入る**
        _pipeline_state["status"] = "completed"
        _pipeline_state["result"] = {
            "stage_results": [],
            "quality_details": {"score": 0.0, "scored": False,
                                "category_report": [], "category_scores": {}},
        }
        html = client.get("/api/pipeline/report").text
        assert "スコア: 未計測" in html, \
            "未計測の実走の⑤行が未計測と出ない（値判定に戻っている）"
        assert "スコア: 0点" not in html, "未計測を 0 点と書いた"
        assert "スコア: 0.0点" not in html, "未計測を 0.0 点と書いた"

        # 採点した 0 点は 0 点と書く（未計測と混ぜない＝門が広すぎないこと）
        _pipeline_state["result"] = {
            "stage_results": [],
            "quality_details": {"score": 0.0, "scored": True,
                                "category_report": [], "category_scores": {}},
        }
        html = client.get("/api/pipeline/report").text
        assert "スコア: 0.0点" in html, "採点した 0 点まで未計測にしている"
        assert "スコア: 未計測" not in html

        # 採点した 89 点
        _pipeline_state["result"] = {
            "stage_results": [],
            "quality_details": {"score": 89, "scored": True,
                                "category_report": [], "category_scores": {}},
        }
        assert "スコア: 89点" in client.get("/api/pipeline/report").text
    finally:
        _pipeline_state.clear()
        _pipeline_state.update(元の状態)


def test_実行結果の採点の有無は挙動で確かめる():
    """`_build_result` が `quality_scored` を**実際に持ち回す**（R1.5-C4・10周目）。

    既存の `test_実行結果に採点の有無が載る` は**ソース文字列の grep** で、
    引継ぎに「grep をテストにしない（コメントに文字列が残るだけで通る）」と
    書いた罠そのものだった。**呼んで確かめる。**
    """
    import unittest.mock as _m

    from agents.pipeline_coordinator import PipelineCoordinator
    from agents.pipeline_types import PipelineContext

    coordinator = PipelineCoordinator.__new__(PipelineCoordinator)

    ctx = PipelineContext(video_path="d.mp4", session_id="s-build")
    with _m.patch.object(PipelineCoordinator, "_generate_improvement_suggestions",
                         return_value=[]):
        未計測 = coordinator._build_result(ctx, "completed", 0.0)
        assert 未計測["quality_scored"] is False
        assert 未計測["quality_details"]["scored"] is False, \
            "未計測なのに採点済みで出た"

        ctx.quality_scored = True
        ctx.quality_score = 89
        採点済み = coordinator._build_result(ctx, "completed", 0.0)
        assert 採点済み["quality_scored"] is True
        assert 採点済み["quality_details"]["scored"] is True, \
            "採点したのに旗が伝わっていない"
        assert 採点済み["quality_details"]["score"] == 89


def test_チャンネル統計の読み口が2つとも印を通る():
    """**印を付ける場所は1つ**（R1.5-C4・gate-verifier 10周目 N-1）。

    6周目・8周目の印は `branding/analytics_manager.py` の**中**に付けた。
    そこを通るのは `POST /api/analytics/sync` を**叩いた後**だけで、
    **永続台帳 `branding/user_model.json` を素で返す読み口には届いて
    いなかった。** `GET /api/status` が登録者 150 人・総再生 4,500 回・
    ライバル「TechStarter」を**無印**で、しかも
    `last_updated: "2026-06-28T02:53:11.581892"` 付きで返していた。

    `evolution_log` でまったく同じことをやって集約したのに、こちらには
    同じ手当てをしていなかった。**読み口は2つある**:

    | 読み口 | 経路 |
    |---|---|
    | `GET /api/status` | `routers/trinity.py` |
    | `GET /api/settings` | `settings_manager.get_all_settings()` |

    10周目が名指ししたのは前者だけ。**後者は同じクラスの別経路**
    （8周目と同じ轍）なので、経路ごとではなく集約点で塞ぐ。
    """
    from user_model_marks import 実績を持つ値に印を付ける

    台帳 = {
        "external_status": {
            "youtube": {"subscribers": 150, "total_views": 4500,
                        "last_updated": "2026-06-28T02:53:11.581892"},
            "rivals": {"nemesis": {"name": "TechStarter", "subs": 180}},
            "quests": [{"type": "NEMESIS_BATTLE", "target_val": 180,
                        "current_val": 150}],
        }
    }

    印つき = 実績を持つ値に印を付ける(台帳)["external_status"]
    assert 印つき["youtube"]["is_real"] is False
    assert 印つき["youtube"]["data_source"] == "sample"
    assert 印つき["youtube"]["last_updated"] is None, \
        "一度も同期していないのに同期時刻が残っている"
    assert 印つき["rivals"]["is_real"] is False
    assert 印つき["rivals"]["nemesis"]["is_real"] is False, \
        "外側だけの印は、UI が nemesis を取り出した時点で消える"
    assert 印つき["quests"][0]["is_real"] is False
    assert 印つき["quests"][0]["data_source"] == "derived"

    # **元の dict を書き換えない**（印がファイルへ書き戻ると本物と区別できない）
    assert "is_real" not in 台帳["external_status"]["youtube"]
    assert 台帳["external_status"]["youtube"]["last_updated"] == \
        "2026-06-28T02:53:11.581892"

    # 本物には付けない（門が広すぎないこと）
    本物 = 実績を持つ値に印を付ける(
        {"external_status": {"youtube": {"subscribers": 9, "is_real": True}}})
    assert 本物["external_status"]["youtube"]["is_real"] is True
    assert "data_source" not in 本物["external_status"]["youtube"]


def test_永続台帳の読み口が印つきで返す():
    """`GET /api/status` と `GET /api/settings` の実体（R1.5-C4・10周目 N-1）。

    **集約点を通っていること自体を経路で確かめる。**
    """
    import unittest.mock as _m

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import branding_manager as BM
    from routers.trinity import router

    台帳 = {
        "profiles": {},
        "external_status": {
            "youtube": {"subscribers": 150, "total_views": 4500,
                        "last_updated": "2026-06-28T02:53:11.581892"},
            "rivals": {"benchmark": {"name": "TechMastery", "subs": 15000}},
        },
    }

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with _m.patch.object(BM.branding_manager, "user_model", 台帳):
        status = client.get("/api/status").json()
        assert status["external_status"]["youtube"]["is_real"] is False, \
            "GET /api/status が無印のチャンネル統計を返した"
        assert status["external_status"]["youtube"]["last_updated"] is None
        assert status["external_status"]["rivals"]["benchmark"]["is_real"] is False

        # 同じ台帳を返すもう1つの読み口
        from settings_manager import settings_manager
        with _m.patch.object(settings_manager, "_ensure_constitution",
                             return_value={}):
            設定 = settings_manager.get_all_settings()
        assert 設定["user_model"]["external_status"]["youtube"]["is_real"] is False, \
            "GET /api/settings が無印のチャンネル統計を返した"

    # 台帳そのものは素のまま（印が保存側へ回り込んでいない）
    assert "is_real" not in 台帳["external_status"]["youtube"]


def test_旧いコンテキストでも採点の有無は旗で決まる():
    """`ProductionContext.quality_scored` を**繋ぐ**（R1.5-C4・10周目 N-3）。

    9周目に旗を足したが、`core/context.py` の側は
    **どこからも代入されず・読まれず・`to_dict`/`from_dict` にも
    載っていない死んだ旗**だった。消費側
    （`progressive_review_plugin` / `report_generator_plugin`）は
    `not quality_score` の**値判定**のままで、
    **9周目に直したのとまったく同じ欠陥が1ファイル隣に残っていた**
    （「1ファイル隣に同じものが残っていた」は4周目にも踏んだ型）。

    値判定だと「測って 0 点」と「未計測」が区別できない。**旗で決める。**
    """
    from core.context import ProductionContext
    from plugins.report_generator_plugin import ReportGeneratorPlugin

    # 旗は値と一緒に運ばれる
    ctx = ProductionContext()
    assert ctx.quality_scored is False, "既定で採点済みになっている"
    ctx.quality_score = 89.0
    ctx.quality_scored = True
    復元 = ProductionContext.from_dict(ctx.to_dict())
    assert 復元.quality_scored is True, "旗が往復で消えた（点だけ戻ると未計測に化ける）"
    assert ProductionContext.from_dict({}).quality_scored is False

    # 消費側が旗を見ている
    plugin = ReportGeneratorPlugin()

    未計測 = ProductionContext()
    未計測.quality_score = 0.0
    assert "未計測" in plugin._generate_report(未計測)

    測って0点 = ProductionContext()
    測って0点.quality_score = 0.0
    測って0点.quality_scored = True
    出力 = plugin._generate_report(測って0点)
    assert "0.0/100" in 出力, "採点した 0 点まで未計測にしている（門が広すぎる）"
    assert "未計測" not in 出力


def test_段階レビューも採点の有無を旗で決める():
    """`progressive_review_plugin._review_final()`（R1.5-C4・10周目 N-3）。

    **自分の変異テストで見つけた5件目の空振り。** N-3 を直したあと
    `report_generator_plugin` の変異は死ぬのに、**1ファイル隣の
    `progressive_review_plugin` は値判定に戻しても緑のまま**だった。
    「1ファイル隣に同じものが残っていた」を**また**やりかけた。

    `metadata["measured"]` は `_review_stage` の合格数の集計に効くので、
    ここが値判定に戻ると**未計測の実走が「0.0/100・不合格」という
    測定結果**として集計に入る。
    """
    from core.context import ProductionContext
    from plugins.progressive_review_plugin import ProgressiveReviewPlugin

    plugin = ProgressiveReviewPlugin()

    def 品質の項目(ctx):
        items, _issues, _sug = plugin._review_final(ctx)
        return next(i for i in items if i.id == "quality_score")

    未計測 = ProductionContext()
    未計測.quality_score = 0.0
    項目 = 品質の項目(未計測)
    assert 項目.metadata["measured"] is False
    assert 項目.metadata["score"] is None
    assert "未計測" in 項目.content

    測って0点 = ProductionContext()
    測って0点.quality_score = 0.0
    測って0点.quality_scored = True
    項目 = 品質の項目(測って0点)
    assert 項目.metadata["measured"] is True, "採点した 0 点まで未計測にしている"
    assert 項目.metadata["score"] == 0.0
    assert "未計測" not in 項目.content


def test_レポートは未計測を全項目クリアと書かない():
    """`GET /api/pipeline/report` のフィードバック欄（R1.5-C4・11周目の指摘）。

    **「確かめられなかった」を「問題なし」にしない。** 採点していなければ
    指摘は当然0件なので、空を「全項目クリア」と読むと**測っていないことが
    合格として出る**。実走なしでサーバを起動して叩くだけで、同じページに

        ⑤ ❌ 品質ゲート  スコア: 未計測 / カテゴリ: 未計測
        0/8合格
        総合スコア: 未計測（品質ゲートを通していません）
        ✅ フィードバック: なし（全項目クリア）   ← これ

    と並んで出ていた。**N-2 で直した⑤行の3行下**、同じ関数ブロックの中。
    「1ファイル隣」どころか「3行下」で、4周目・9周目・10周目と同じ型。

    リポジトリ自身が `cost_guard.py` / `feature_gaps.py` / `artifact_gate.py` で
    「『確かめられなかった』を『問題なし』にしない」と書いているのに、
    ここだけ破れていた。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import pipeline_report as PR
    from routers.pipeline_router import _pipeline_state

    app = FastAPI()
    app.include_router(PR.router)  # router 側が prefix="/api/pipeline" を持つ
    client = TestClient(app, raise_server_exceptions=False)

    元の状態 = dict(_pipeline_state)
    try:
        # ① 実走していない（起動直後そのもの）
        _pipeline_state.clear()
        html = client.get("/api/pipeline/report").text
        assert "全項目クリア" not in html, "実走していないのに全項目クリアと出した"

        # ② 実走はしたが品質ゲートを通していない
        _pipeline_state["status"] = "completed"
        _pipeline_state["result"] = {
            "stage_results": [],
            "quality_details": {"score": 0.0, "scored": False, "feedback": [],
                                "category_report": [], "category_scores": {}},
        }
        html = client.get("/api/pipeline/report").text
        assert "全項目クリア" not in html, "未計測なのに全項目クリアと出した"
        assert "未計測" in html

        # ③ 採点して指摘0件 — **ここは緑でよい**（門が広すぎないことの確認）
        _pipeline_state["result"] = {
            "stage_results": [],
            "quality_details": {"score": 95, "scored": True, "feedback": [],
                                "category_report": [], "category_scores": {}},
        }
        html = client.get("/api/pipeline/report").text
        assert "全項目クリア" in html, "採点して指摘0件まで未計測にしている"

        # ④ 採点して指摘あり
        _pipeline_state["result"] = {
            "stage_results": [],
            "quality_details": {"score": 70, "scored": True,
                                "feedback": ["音量が小さすぎます"],
                                "category_report": [], "category_scores": {}},
        }
        html = client.get("/api/pipeline/report").text
        assert "音量が小さすぎます" in html
        assert "全項目クリア" not in html

        # ⑤ 指摘はあるが旗が無い — **指摘は必ず出す**。
        # 旗の有無で隠すと、実際に出た指摘を握り潰すことになる（未計測より悪い）。
        # 旗を見てよいのは**空だったときだけ**
        _pipeline_state["result"] = {
            "stage_results": [],
            "quality_details": {"feedback": ["音量が小さすぎます"],
                                "category_report": [], "category_scores": {}},
        }
        html = client.get("/api/pipeline/report").text
        assert "音量が小さすぎます" in html, "実際に出た指摘を旗の都合で隠した"
    finally:
        _pipeline_state.clear()
        _pipeline_state.update(元の状態)


def test_実行記録は未計測を0点として残さない(tmp_path, monkeypatch):
    """`_trigger_dream_learning` の制作ナレッジ（R1.5-C4・12周目の指摘）。

    **応答本文に出ない経路**で、名指しされた `quality_score` が旗なしの
    値として残っていた。`QualityGateWorker` は `FATAL_WORKERS` に入って
    いないので、品質ゲートが結果を返さなくても実走は `degraded` で続き、
    **ここは必ず走る**。そのとき `ctx.quality_score` は既定の 0 で、
    既存の記録（`run_20260826_060153.json` の `"quality_score": 50`）と
    **同じ形になり、読み手に実測 0 点と未計測が区別できない**。
    """
    import asyncio
    import json as _json
    import sys
    import types

    from agents.pipeline_coordinator import PipelineCoordinator
    from agents.pipeline_types import PipelineContext

    # DreamEngine の副作用（VERIFIED_FACTS.md 等の追跡ファイル書き換え）を止める
    偽エンジン = types.ModuleType("agents.dream_engine")

    class _偽:
        def increment_session_count(self): pass
        async def should_dream(self): return False

    偽エンジン.dream_engine = _偽()
    monkeypatch.setitem(sys.modules, "agents.dream_engine", 偽エンジン)

    import agents.pipeline_coordinator as PC
    monkeypatch.setattr(PC, "_writable_path", lambda *_a, **_k: tmp_path)
    monkeypatch.delenv("AVS_SKIP_LEARNING_SIDE_EFFECTS", raising=False)

    coordinator = PipelineCoordinator.__new__(PipelineCoordinator)

    def 記録を読む():
        files = sorted(tmp_path.glob("run_*.json"))
        assert files, "ナレッジが書かれていない"
        return _json.loads(files[-1].read_text(encoding="utf-8"))

    # ① 未計測（品質ゲートが結果を返さなかった degraded 実走）
    ctx = PipelineContext(video_path="never_scored.mp4", session_id="s-k1")
    asyncio.run(coordinator._trigger_dream_learning(ctx))
    記録 = 記録を読む()
    assert 記録["quality_scored"] is False
    assert 記録["quality_score"] is None, "未計測を 0 点として記録した"

    # ② 採点した 0 点は 0 点として残す（門が広すぎないこと）
    for f in tmp_path.glob("run_*.json"):
        f.unlink()
    ctx2 = PipelineContext(video_path="scored_zero.mp4", session_id="s-k2")
    ctx2.quality_scored = True
    ctx2.quality_score = 0
    asyncio.run(coordinator._trigger_dream_learning(ctx2))
    記録2 = 記録を読む()
    assert 記録2["quality_scored"] is True
    assert 記録2["quality_score"] == 0, "採点した 0 点まで消している"


def test_未計測の実走から確かめた事実を作らない(tmp_path, monkeypatch):
    """`tick_loop._action_pipeline_knowledge`（R1.5-C4・12周目の指摘）。

    書き込み先は **`VERIFIED_FACTS.md`（恒久的に残る「確かめた事実」）**。
    もとは `score > 0` で判断していた——**番兵値で「測ったか」を決める**
    読み方で、9周目に本線で根治したのと同じ型。旧い記録には旗が無いので
    **旗が無ければ採点していないとみなす**（fail-closed）。
    """
    import asyncio
    import json as _json

    import agents.tick_loop as TL

    knowledge_dir = tmp_path / "pipeline_knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(TL, "_writable_path", lambda *_a, **_k: knowledge_dir)

    足された = []

    class _偽ストア:
        def add_fact(self, **kw):
            足された.append(kw)

    import agents.memory.verified_facts as VF
    monkeypatch.setattr(VF, "verified_facts_store", _偽ストア())

    def 走らせる(記録):
        for f in knowledge_dir.glob("run_*.json"):
            f.unlink()
        (knowledge_dir / "run_001.json").write_text(
            _json.dumps(記録, ensure_ascii=False), encoding="utf-8")
        足された.clear()
        asyncio.run(TL.TickLoop()._action_pipeline_knowledge())
        return [f for f in 足された if "品質スコア" in f.get("content", "")]

    # ① 未計測（旗なし・0点）— **事実にしない**
    assert 走らせる({"video": "a.mp4", "quality_score": 0}) == [], \
        "未計測から品質スコアの『確かめた事実』を作った"

    # ② 旗なしで点だけある旧い記録 — 測ったか分からないので作らない
    assert 走らせる({"video": "b.mp4", "quality_score": 50}) == [], \
        "旗の無い記録を実測として扱った"

    # ③ 採点した 0 点 — **事実にする**（門が広すぎないこと）
    事実 = 走らせる({"video": "c.mp4", "quality_score": 0, "quality_scored": True})
    assert len(事実) == 1, "採点した 0 点を落とした"
    assert "0点" in 事実[0]["content"]

    # ④ 採点した 85 点
    事実 = 走らせる({"video": "d.mp4", "quality_score": 85, "quality_scored": True})
    assert len(事実) == 1 and "85点" in 事実[0]["content"]


def test_採点できなかった実走を完了と呼ばない():
    """**未計測なら `completed` にならない**（R1.5-C4・13周目の裏取り）。

    13周目は「`QualityGateWorker` は `FATAL_WORKERS` に入っていないので
    未計測でも `completed` に到達する」と述べて UI の反例を挙げたが、
    **その到達性は成り立たない**。`_settle_outcomes()` は落ちた工程を
    致命／劣化に分け、**劣化があれば `degraded`**（`completed` ではない）。
    品質ゲートが例外・Hook 拒否で結果を返さなければ劣化に入る。

    UI 側（`ProductionPipeline.jsx:385`）は `status === "completed"` でしか
    仕上げウィザードを出さないので、**未計測のまま UI に届く経路が無い**
    ことがこの不変条件で決まる。

    **ここが崩れたら UI の「未計測」の枝が本当に必要になる**ので、
    不変条件そのものを固定しておく。
    """
    from agents.pipeline_coordinator import (
        FATAL_STAGES, PipelineCoordinator, STATUS_COMPLETED, STATUS_DEGRADED)
    from agents.pipeline_types import PipelineContext

    coordinator = PipelineCoordinator.__new__(PipelineCoordinator)
    ctx = PipelineContext(video_path="d.mp4", session_id="s-settle")
    ctx.skipped_features = []

    # 品質ゲートが結果を返さなかった実走
    coordinator._outcomes = {"文字起こし": True, "品質チェック": False}
    致命, 劣化 = coordinator._settle_outcomes(ctx)

    assert "品質チェック" not in FATAL_STAGES, "前提が変わった（致命に昇格した）"
    assert 致命 == [], 致命
    assert 劣化 == ["品質チェック"], 劣化

    # 呼び出し側と同じ式で状態を決める
    final_status = STATUS_DEGRADED if 劣化 else STATUS_COMPLETED
    assert final_status == STATUS_DEGRADED
    assert final_status != STATUS_COMPLETED, \
        "未計測の実走が completed になった（UI が仕上げウィザードを出す）"
    assert "品質チェック" in ctx.skipped_features, "落ちた工程が記録に出ていない"

    # 全部通ったときだけ completed
    ctx2 = PipelineContext(video_path="d.mp4", session_id="s-settle2")
    ctx2.skipped_features = []
    coordinator._outcomes = {"文字起こし": True, "品質チェック": True}
    致命2, 劣化2 = coordinator._settle_outcomes(ctx2)
    assert (STATUS_DEGRADED if 劣化2 else STATUS_COMPLETED) == STATUS_COMPLETED, \
        "全部通ったのに完了と呼べない（門が広すぎる）"


def test_実体から引いたと名乗る数字が実体と一致する():
    """**印があっても嘘なら同じこと**（R1.5-C4・gate-verifier 14周目の指摘）。

    `GET /api/admin/quality/ratchet` は `is_real: true /
    data_source: "derived" / source: "…/v8_baseline.json"` を名乗りながら、
    `layer_distribution` に**そのファイルに存在しない固定値**
    （L1:168/L2:140/L3:182/L4:140/L5:140 = **合計 770**）を混ぜていた。

    **770 はこの経路の docstring が「作り物」と名指しした旧値そのもの**で、
    しかも同じ応答の `total_items` は 1045。**内部で矛盾したまま
    「実測」の札が付いていた。**

    これまでの掃引は**「印が無いもの」を探していた**ので、
    **印はあるが中身が嘘**というこの形を素通りさせていた。
    だからここでは印の有無ではなく、**数字が出所と一致するか**を見る。
    """
    import json
    from pathlib import Path as _Path

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.admin_quality_router import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    ルート = _Path(__file__).resolve().parent.parent.parent.parent
    出所 = ルート / "backend/ux_verification/snapshots/v8_baseline.json"
    実体 = json.loads(出所.read_text(encoding="utf-8"))

    data = client.get("/api/admin/quality/ratchet").json()
    assert data["is_real"] is True and data["data_source"] == "derived"

    # 名乗ったからには一致していること
    assert data["pass_items"] == 実体["pass_count"]
    assert data["fail_items"] == 実体["fail_count"]
    assert data["skip_items"] == 実体["skip_count"]
    assert data["correlation_rate"] == 実体["pass_rate"]
    assert data["total_items"] == (
        実体["pass_count"] + 実体["fail_count"] + 実体["skip_count"])

    # **出所に無いものを値として出さない。**
    assert "layer_distribution" not in 実体, \
        "出所が層別分布を持つようになった。引いて返すよう直すこと"
    assert data["layer_distribution"] is None, \
        "出所に無い層別分布を『実測』として返した"
    assert data.get("note"), "引けなかったことを言っていない"

    # 作り物の 770 がどこにも出ていないこと
    本文 = json.dumps(data, ensure_ascii=False)
    assert "770" not in 本文, f"作り物の合計 770 が実測の札で出ている: {本文[:200]}"


def test_戦略会議室が読む鍵が印つきで揃っている():
    """`Boardroom.jsx` の「ライバル出現」カードの供給契約（R1.5-C4・15周目の指摘）。

    あのカードは `GadgetReviewer / You: 200 / Target: 250 / 差分: 50 人 /
    TechMastery / 目標: 10,000 人` を **JSX に直書き**していた。
    `external_status` を受け取っているのに一度も使っておらず、
    **バックエンドの作り物の値（登録者150・TechStarter 180・差分30）とも
    食い違う数字**を「You:」＝利用者自身の登録者数として描いていた。
    `admin_channel_router` の `watch_time_hours: 15200` と同じクラスが、
    印の付かないままフロントに残っていた。

    直書きをやめて `GET /api/settings` の `external_status` から描くようにした。
    **ここではその供給側の契約を固定する** — フロントに test runner が無いので
    JSX そのものは自動検証できないが、**画面が読む鍵が消えたり無印になったら
    ここで落ちる**。
    """
    import unittest.mock as _m

    import branding_manager as BM

    台帳 = {
        "profiles": {},
        "external_status": {
            "youtube": {"subscribers": 150, "total_views": 4500},
            "rivals": {
                "nemesis": {"name": "TechStarter", "subs": 180},
                "benchmark": {"name": "TechMastery", "subs": 15000, "genre": "Tech"},
            },
        },
    }

    with _m.patch.object(BM.branding_manager, "user_model", 台帳):
        from settings_manager import settings_manager
        with _m.patch.object(settings_manager, "_ensure_constitution", return_value={}):
            外部 = settings_manager.get_all_settings()["user_model"]["external_status"]

    # 画面が「作り物です」の帯を出すための旗
    assert 外部["rivals"]["is_real"] is False, "画面が警告を出せない"

    # 画面が描く鍵（消えたら「未取得」表示に落ちる＝嘘は出ないが、契約は保つ）
    assert 外部["rivals"]["nemesis"]["name"] == "TechStarter"
    assert 外部["rivals"]["nemesis"]["subs"] == 180
    assert 外部["rivals"]["benchmark"]["name"] == "TechMastery"
    assert 外部["rivals"]["benchmark"]["subs"] == 15000
    assert 外部["rivals"]["benchmark"]["genre"] == "Tech"
    assert 外部["youtube"]["subscribers"] == 150

    # 中身にも印が要る（UI が nemesis を取り出した時点で消えないこと）
    assert 外部["rivals"]["nemesis"]["is_real"] is False
    assert 外部["rivals"]["benchmark"]["is_real"] is False


def test_戦略会議室に数字を直書きしない():
    """**直書きの再発を止める**（R1.5-C4・15周目の指摘）。

    フロントに test runner が無いので、ここだけは描画ではなくソースを見る。
    **文字列 grep をテストにするのは本来避ける**（コメントに残るだけで通る）
    が、ここでは逆向き——**「この数字が JSX の描画部に出てはいけない」**——
    なので、コメントに書いてあっても落ちないよう**コメント行を除いてから**
    数える。
    """
    from pathlib import Path as _Path

    js = (_Path(__file__).resolve().parent.parent.parent.parent
          / "frontend" / "src" / "components" / "Boardroom.jsx"
          ).read_text(encoding="utf-8")

    # ブロックコメントを落とす（説明文に旧値を残せるようにするため）
    import re
    描画部 = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    描画部 = "\n".join(行 for 行 in 描画部.splitlines()
                     if not 行.strip().startswith("//"))

    for 旧値 in ("GadgetReviewer", "You: 200", "Target: 250",
                "差分: 50 人", "目標: 10,000 人"):
        assert 旧値 not in 描画部, f"作り物のチャンネル統計が直書きで戻っている: {旧値}"

    # 供給元から描いていること
    assert "external_status" in 描画部, "external_status を使わずに描いている"

    # **同じファイルの別カードも見る**（R1.5-C4・gate-verifier 17周目の指摘）。
    # 15周目はライバルカードだけを直し、禁止語もその5個だけにしたので、
    # **同ファイル上部のレーダーが無検査のまま残っていた** —
    # `ranks?.biz_rank?.xp || 10` の `ranks` は**トップレベルには存在せず**
    # （実体は `profiles.<役割>.ranks`）、レーダーは
    # 「クリエイター能力分布」と称して **10 / 20 / 50 の定数を常時描いていた。**
    for 旧値 in ("|| 10", "|| 20", "|| 50", '"Identify"',
                '"Create your first masterpiece"'):
        assert 旧値 not in 描画部, f"レーダー／ミッションの定数が戻っている: {旧値}"
    assert "profiles?.owner?.ranks" in 描画部 or "profiles?.admin?.ranks" in 描画部, \
        "段位を `profiles.<役割>.ranks` から読んでいない（存在しない鍵に落ちる）"


def test_作り物の再生数から出たXPに印が付く():
    """`profiles.*.ranks.biz_rank`（R1.5-C4・2026-09-03 ユーザー決定）。

    `branding_manager.process_analytics_update()` の
    `calculated_xp = int(current_views / 100)` は、**作り物の総再生 4,500**
    から **XP 45** を作る。それを `SoulPassport.jsx` が `XP 45` と
    **無印で**描いていた（15周目の記録）。

    ユーザー判断で C4 の対象に含めた。`quests` と同じ **`derived`**
    （統計そのものではないが、統計から出た値）。

    **`tech_rank` には付けない** — あちらは `ingest_report()` の XP 付与から
    積まれるもので、チャンネル統計から出ていない（門が広すぎないこと）。
    """
    from user_model_marks import 実績を持つ値に印を付ける

    台帳 = {
        "external_status": {"youtube": {"subscribers": 150, "total_views": 4500}},
        "profiles": {
            "owner": {"ranks": {"biz_rank": {"xp": 45}}},
            "admin": {"ranks": {"tech_rank": {"level": "Editor", "xp": 185}}},
        },
    }

    印つき = 実績を持つ値に印を付ける(台帳)["profiles"]

    biz = 印つき["owner"]["ranks"]["biz_rank"]
    assert biz["is_real"] is False, "作り物の再生数から出た XP が無印で出た"
    assert biz["data_source"] == "derived"
    assert biz["xp"] == 45, "値まで消している"

    tech = 印つき["admin"]["ranks"]["tech_rank"]
    assert "is_real" not in tech, "tech_rank はチャンネル統計から出ていない（門が広すぎる）"
    # **無い段位を作らない。** `biz_rank` を持たないプロファイルに
    # `tech_rank` の中身を写して段位をでっち上げると、`tech_rank` 自体は
    # 無印のまま通ってしまう（この行が無いと変異 M24 が生き残る）
    assert "biz_rank" not in 印つき["admin"]["ranks"], \
        "biz_rank を持たないプロファイルに biz_rank を作った"
    assert 印つき["admin"]["ranks"]["tech_rank"]["xp"] == 185, "tech_rank を書き換えた"

    # 元の dict を書き換えない
    assert "is_real" not in 台帳["profiles"]["owner"]["ranks"]["biz_rank"]

    # 本物には付けない
    本物 = 実績を持つ値に印を付ける(
        {"profiles": {"owner": {"ranks": {"biz_rank": {"xp": 9, "is_real": True}}}}})
    assert 本物["profiles"]["owner"]["ranks"]["biz_rank"]["is_real"] is True
    assert "data_source" not in 本物["profiles"]["owner"]["ranks"]["biz_rank"]


def test_品質ゲートの画面が未計測を判定として描かない():
    """`QualityGate.jsx`（R1.5-C4・面(b)「人が読む文字列」の掃引）。

    `is_ready ? '✅ 出力準備完了' : '⚠️ 修正を推奨'` と二択で描いており、
    **未計測でも「⚠️ 修正を推奨」という判定**が出ていた（測っていないので
    判定できない）。`score || '--'` も**実測 0 点を '--' に潰して**いた。

    供給元は3つあり、**いずれも「測ったか」を渡している**のに、
    受け側が1つも受け取っていなかった:

    | 供給元 | 渡していたもの |
    |---|---|
    | `ProductionPipeline.jsx` | `scored` |
    | `ProductionWizard.jsx` | `scored` |
    | `EditorPage.jsx`（`POST /api/director/verify-quality`）| 失敗時 `score: null` + `is_real: false` |

    **フロントに test runner が無い**ので、ここだけはソースを見る。
    コメントに旧コードを残せるよう、**コメントを外してから**数える。
    """
    import re
    from pathlib import Path as _Path

    ルート = _Path(__file__).resolve().parent.parent.parent.parent
    js = (ルート / "frontend" / "src" / "components" / "QualityGate.jsx"
          ).read_text(encoding="utf-8")

    描画部 = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    描画部 = "\n".join(行 for 行 in 描画部.splitlines()
                     if not 行.strip().startswith("//"))

    assert "採点した" in 描画部, "「測ったか」を見ずに描いている"
    assert "'⚠️ 未計測'" in 描画部 or '"⚠️ 未計測"' in 描画部, \
        "未計測の表示が無い（測っていないのに判定を出す）"
    assert "{score || '--'}" not in 描画部, \
        "実測 0 点を '--' に潰している（`||` は 0 を falsy として弾く）"


def test_供給元が品質ゲートの画面に旗を渡している():
    """上のテストの相方 — **供給側が旗を渡していること**（R1.5-C4）。

    受け側が旗を見るようになっても、**渡す側が落としたら元に戻る**
    （10周目・13周目・15周目がすべてこの形だった）。
    """
    import re
    from pathlib import Path as _Path

    ルート = _Path(__file__).resolve().parent.parent.parent.parent

    def 描画部を読む(相対):
        js = (ルート / 相対).read_text(encoding="utf-8")
        s = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        return "\n".join(行 for 行 in s.splitlines()
                         if not 行.strip().startswith("//"))

    # **`scored:` の有無だけを見ない。** 失敗時の `scored: false` でも
    # 満たせてしまうので、**計算した旗を渡していること**を見る
    for 相対 in ("frontend/src/components/ProductionPipeline.jsx",
                "frontend/src/components/ProductionWizard.jsx"):
        assert "scored: 採点した" in 描画部を読む(相対), \
            f"{相対} が品質ゲートへ「計算した旗」を渡していない"

    # **旗を立てるだけでは足りない**（R1.5-C4・16周目の指摘）。
    # 16周目は「`scored: true` を立てているが、その中身は
    # `is_real:false` の定数 85 点」という状態を見つけた。
    # このテストは当時 `"scored:"` の有無しか見ておらず**素通りさせた**。
    描画部 = 描画部を読む("frontend/src/components/ProductionPipeline.jsx")
    assert "statusData.is_real" in 描画部, \
        "供給元が応答の `is_real` を見ていない（定数を『採点した』と名乗れてしまう）"
    assert "stage.data?.quality_score" not in 描画部, \
        "実測の鍵名を取り違えている（`StageResult.data` は `score`）"
    assert "stage.data?.score" in 描画部, "本線の実測を読んでいない"


def test_不合格レポートの有無を番兵値で決めない():
    """`_build_result` の `quality_gate_report`（R1.5-C4・面(a)の掃引）。

    `if ctx.quality_score < 90 and ctx.quality_score > 0:` という
    **番兵値**で組み立てていた。`> 0` のせいで**採点して 0 点**の実走は
    レポートが作られず、`POST /api/pipeline/force-render` が

        品質ゲート不合格レポートが存在しません（**品質合格済みの可能性**）

    と返す——**最悪の点なのに「合格したかも」と言う**。
    9周目に本線で根治したのと同じ型が、`_build_result` の中に残っていた。
    """
    import unittest.mock as _m

    from agents.pipeline_coordinator import PipelineCoordinator
    from agents.pipeline_types import PipelineContext

    coordinator = PipelineCoordinator.__new__(PipelineCoordinator)

    def 作る(点, 旗):
        ctx = PipelineContext(video_path="d.mp4", session_id="s-gate")
        ctx.quality_score = 点
        ctx.quality_scored = 旗
        with _m.patch.object(PipelineCoordinator,
                             "_generate_improvement_suggestions", return_value=[]):
            return coordinator._build_result(ctx, "completed", 0.0)["quality_gate_report"]

    # **採点した 0 点はレポートを作る**（ここが番兵値だと落ちる）
    零点 = 作る(0, True)
    assert 零点 is not None, "採点した 0 点でレポートが作られない（force-render が『合格済みの可能性』と言う）"
    assert 零点["status"] == "blocked"
    assert 零点["score"] == 0
    assert 零点["gap"] == 90

    # 採点した 85 点も作る
    assert 作る(85, True) is not None

    # 未計測は作らない（fail-closed。門が広すぎないこと）
    assert 作る(0, False) is None, "未計測なのに不合格レポートを作った"

    # 合格はレポート不要
    assert 作る(95, True) is None


# ============================================================
# 18周目（gate-verifier）— 反例1 と、契約の穴2件
#
# 反例1: `director_engine.generate_production_report()` の except が
#   `issue_detected: "特になし" / xp_grant: 50` を**印なしで**返し、
#   `routers/director.py` の `if xp > 0:` がその 50 を
#   `user_model.json` の `tech_rank` に**恒久保存**していた。
#   分析が一度も走っていないのに「問題は検出されなかった」と言い、
#   その失敗が実績として台帳に残る。
#
# 契約の穴: 18周目の verifier が変異を当てたところ、**C4 の条件文が
#   名指ししている2つ**を変異させても、この44件は全部緑のままだった:
#     - `youtube_uploader.upload_video()` の placeholder success
#     - `admin_channel_router` の固定値
#   条件文が名指しするものを契約が守っていないのは穴なので、ここで塞ぐ。
# ============================================================


def test_18周目_分析が落ちたレポートが実績を名乗らない():
    """`generate_production_report()` の except（R1.5-C4・18周目 反例1）。

    ここは以前こう返していた:

        {"summary": "セッション完了", "success_factor": "完了したこと",
         "issue_detected": "特になし", "xp_grant": 50}

    `"特になし"` は**分析が走っていないのに「問題は検出されなかった」**という判定。
    さらに `xp_grant: 50` が `routers/director.py` を通って
    `user_model.json` の `tech_rank` に恒久保存されていた。
    `backend/user_model_marks.py` は「`tech_rank` は実行動で稼ぐ値だから
    印を付けない」と宣言しているので、この経路がその宣言ごと嘘にしていた。
    """
    import json as _json
    import unittest.mock as _m

    from director_engine import DirectorBrain

    brain = DirectorBrain.__new__(DirectorBrain)
    brain.chat_model = "gemini-3.6-flash"
    brain.client = _m.MagicMock()
    brain.client.models.generate_content.side_effect = RuntimeError("API Error")

    出力 = _json.loads(brain.generate_production_report([], {}, "Novice"))

    # **実績を出さない**（これが台帳に焼き付いていた）
    assert 出力["xp_grant"] == 0, "分析が落ちたのに実績 XP を出した"

    # **判定を名乗らない**
    assert 出力["issue_detected"] is None, "分析していないのに『問題なし』と判定した"
    assert 出力["success_factor"] is None

    # **印が付く**
    assert 出力["is_real"] is False
    assert 出力["data_source"] == "unavailable"
    assert "分析は行われていません" in 出力["summary"]


def test_18周目_分析できたレポートには出所の印が付く():
    """反例1の相方 — **成功側にも印が要る**（R1.5-C4・18周目）。

    失敗側だけ `is_real: false` にしても、成功側が無印だと
    「印が無い＝どちらか分からない」状態が残る。工程ごとにどのモデルが
    出したかを残すのは `CLAUDE.md` のモデル見える化の要求でもある。
    """
    import json as _json
    import unittest.mock as _m

    from director_engine import DirectorBrain

    brain = DirectorBrain.__new__(DirectorBrain)
    brain.chat_model = "gemini-3.6-flash"
    brain.client = _m.MagicMock()
    応答 = _m.MagicMock()
    応答.text = '{"summary": "ok", "xp_grant": 70}'
    brain.client.models.generate_content.return_value = 応答

    出力 = _json.loads(brain.generate_production_report([], {}, "Novice"))
    assert 出力["is_real"] is True
    assert 出力["data_source"] == "gemini:gemini-3.6-flash", \
        "どのモデルが出した分析か分からない"
    assert 出力["xp_grant"] == 70, "実際の分析結果を握り潰した"


def test_18周目_印のないレポートで実績台帳を書き換えない():
    """`routers/director.py` の XP 付与（R1.5-C4・18周目 反例1の到達点）。

    エンジン側が直っても、**ルーターが `is_real: false` を無視したら元に戻る**
    （10周目・13周目・15周目がすべて「片側だけ直して戻る」形だった）。
    """
    import asyncio
    import importlib
    import unittest.mock as _m

    # **`import routers.director as D` と書かない**（R1.5-C4・19周目）。
    # `backend/routers/__init__.py` は `from .X import router as X` で
    # **モジュール名と同じ名前を APIRouter オブジェクトに束縛する**。
    # 単体実行ではこのファイルが `routers` をスタブ化しているのでモジュールが
    # 取れるが、**全件実行で本物の `__init__` が読まれていると
    # `import a.b as c` の属性参照が APIRouter を掴む**（CI で実際に踏んだ）。
    # `importlib.import_module` は `sys.modules` から引くのでこれを避けられる。
    D = importlib.import_module("routers.director")

    def 叩く(レポート):
        要求 = D.ReportRequest(storyboard_plan=[], quality_score={})
        脳 = _m.MagicMock()
        脳.generate_production_report.return_value = レポート
        台帳 = _m.MagicMock()
        with _m.patch.dict("sys.modules", {
            "director_engine": _m.MagicMock(brain=脳),
            "branding_manager": _m.MagicMock(branding_manager=台帳),
        }):
            結果 = asyncio.run(D.generate_report(要求))
        return 結果, 台帳.update_user_rank

    # 分析していないレポート → **台帳を触らない**
    結果, 書き込み = 叩く('{"xp_grant": 50, "is_real": false, "data_source": "unavailable"}')
    assert 結果["xp_grant"] == 50, "応答からレポートが消えた"
    assert 書き込み.call_count == 0, "分析していないレポートで tech_rank を書き換えた"

    # 分析できたレポート → 通常どおり付与する（門が広すぎないこと）
    結果, 書き込み = 叩く('{"xp_grant": 70, "is_real": true}')
    書き込み.assert_called_once_with("tech_rank", amount=70)

    # 印が無いレポート（旧来の形）は従来どおり付与する
    # ——**門を広げすぎて既存の挙動を壊していないこと**の確認
    結果, 書き込み = 叩く('{"xp_grant": 30}')
    書き込み.assert_called_once_with("tech_rank", amount=30)


def test_18周目_XPを持たないレポートに既定の実績を与えない():
    """`branding_manager.ingest_report()`（R1.5-C4・18周目 反例1と同型）。

    `report_data.get('xp_grant', 50)` という既定値だったので、
    **実績を主張していないレポートに黙って 50 XP** が付いていた。
    """
    import unittest.mock as _m

    from branding_manager import BrandingManager

    bm = BrandingManager.__new__(BrandingManager)
    bm.log_evolution = _m.MagicMock()
    bm.update_user_rank = _m.MagicMock()

    # `xp_grant` が無い → 0。台帳を触らない
    結果 = bm.ingest_report({"agenda_proposal": "次の一手"})
    assert 結果["xp_granted"] == 0, "実績を主張していないレポートに XP を与えた"
    assert bm.update_user_rank.call_count == 0

    # 分析していない印がある → 0
    bm.update_user_rank.reset_mock()
    assert bm.ingest_report({"xp_grant": 50, "is_real": False})["xp_granted"] == 0
    assert bm.update_user_rank.call_count == 0

    # 通常の付与は通る（門が広すぎないこと）
    bm.update_user_rank.reset_mock()
    assert bm.ingest_report({"xp_grant": 30})["xp_granted"] == 30
    bm.update_user_rank.assert_called_once_with("tech_rank", amount=30)


def test_18周目_段位は存在する鍵から読む():
    """存在しない鍵へのフォールバックが定数を作らないこと（R1.5-C4・18周目）。

    17周目に `Boardroom.jsx` のレーダーで見つけたのと同じ形が
    バックエンドにも残っていた:

        user_model.get('ranks', {}).get('biz_rank', {}).get('level', 'Novice')

    **`user_model` に top-level の `ranks` は存在しない**（実体は
    `profiles.<役割>.ranks.<段位>`）。つまりこの読み口は
    **どんな段位の利用者でも常に 'Novice'** に落ちていた。
    """
    from director_engine import DirectorBrain

    解決 = DirectorBrain._resolve_rank_level

    実体の形 = {
        "profiles": {
            "owner": {"ranks": {"biz_rank": {"level": "Expert"}}},
            "admin": {"ranks": {"tech_rank": {"level": "Editor"}}},
        }
    }
    assert 解決(実体の形, "owner", "biz_rank") == "Expert"
    assert 解決(実体の形, "admin", "tech_rank") == "Editor"

    # **架空の形からは読めない**（読めたら旧実装のまま）
    架空の形 = {"ranks": {"biz_rank": {"level": "Expert"}}}
    assert 解決(架空の形, "owner", "biz_rank") is None, \
        "存在しない鍵の形から段位を読んでいる（旧実装のまま）"

    # 読めないときは定数を名乗らない
    assert 解決({}, "owner", "biz_rank") is None
    assert 解決(None, "owner", "biz_rank") is None
    assert 解決({"profiles": {"owner": {}}}, "owner", "biz_rank") is None


def test_18周目_採点の入力に段位を捏造しない():
    """`calculate_quality_score()` の既定引数（R1.5-C4・18周目）。

    既定が `biz_rank="Novice"` だったので、画面が段位を送らない限り
    **どの利用者の絵コンテも「Novice / 期待値 Basic」で採点**されていた。
    品質スコアは C4 が名指しする4カテゴリの1つ。
    """
    import inspect

    from director_engine import DirectorBrain

    for 名前 in ("calculate_quality_score", "generate_production_report"):
        既定 = inspect.signature(getattr(DirectorBrain, 名前)).parameters["biz_rank"].default
        assert 既定 is None, f"{名前}() が段位の既定値に定数を置いている（{既定!r}）"

    # 呼び出し口（リクエスト模型）も同様
    from routers.director import QualityScoreRequest, ReportRequest

    for 模型 in (QualityScoreRequest, ReportRequest):
        assert 模型.model_fields["biz_rank"].default is None, \
            f"{模型.__name__} が段位の既定値に定数を置いている"


def test_18周目_オートパイロット率は実際の設定から読む():
    """存在しない鍵へのフォールバック（R1.5-C4・18周目・4カテゴリの周辺）。

    `user_model.get('automation_settings', {})` は**存在しない鍵**で、
    実体は `collaborative_settings`（`branding_manager.set_auto_pilot()` の
    書き込み先）。**利用者が何％に設定しても常に 0.9** を読んでいた。
    """
    import unittest.mock as _m

    from director_engine import DirectorBrain

    brain = DirectorBrain.__new__(DirectorBrain)
    brain.persona_consultant = "{channel_name}{biz_rank}{biz_advice_mode}"
    brain.persona_director = "{tech_rank}{tech_advice_mode}"
    brain.persona_common = "{auto_pilot_percent}"

    利用者 = {
        "profiles": {
            "owner": {"ranks": {"biz_rank": {"level": "Novice"}}},
            "admin": {"ranks": {"tech_rank": {"level": "Novice"}}},
        },
        "collaborative_settings": {"auto_pilot_ratio": 0.5},
    }

    with _m.patch("director_engine.branding_manager") as 台帳:
        台帳.constitution = {"channel_name": "C"}
        台帳.user_model = 利用者
        台帳.get_context_block.return_value = ""
        台帳.get_deep_context.return_value = ""
        指示 = brain._get_system_instruction(mode="consult")

    assert "50" in 指示, "利用者の設定（0.5）が指示書に届いていない"
    assert "90" not in 指示, "存在しない鍵の既定値 0.9 を読んでいる"


def test_18周目_投稿の未実装は成功を名乗らない(tmp_path):
    """**C4 条件文が名指しする `upload_video()`**（18周目・契約の穴）。

    18周目の verifier が `success=False, status="failed"` を
    `success=True, status="uploaded"` に変異させたところ、
    **この契約ファイル44件は全部緑のままだった。**
    条件文が名指ししているものを契約が守っていなかったので塞ぐ。
    """
    import asyncio

    from services.youtube_uploader import (YouTubeCredentials, YouTubeUploaderService,
                                           youtube_uploader)

    # **手前の門（未認証・ファイル無し）で止まると、未実装の枝に届かない。**
    # verifier の変異 M3 が刺さるのはこの枝なので、認証済み・実ファイルありで叩く。
    動画 = tmp_path / "d.mp4"
    動画.write_bytes(bytes(1))

    投稿器 = YouTubeUploaderService()
    投稿器._credentials = YouTubeCredentials(access_token="dummy-token", client_id="cid", client_secret="cs")

    結果 = asyncio.run(投稿器.upload_video(str(動画), "題", "説明", ["tag"]))

    assert 結果.success is False, "未実装の投稿が成功を名乗った"
    assert 結果.status != "uploaded", f"投稿していないのに uploaded と記録した（{結果.status!r}）"
    assert 結果.error == "not_implemented", f"未実装の理由が消えている（{結果.error!r}）"
    assert not 結果.video_id, f"実在しない動画 ID を返した（{結果.video_id!r}）"

    # 手前の門も成功を名乗らないこと
    未認証 = asyncio.run(youtube_uploader.upload_video(str(動画), "題", "説明", ["tag"]))
    assert 未認証.success is False
    assert not 未認証.video_id


def test_18周目_チャンネル統計の固定値が印を落とさない():
    """**C4 条件文が名指しする `admin_channel_router` の固定値**（18周目・契約の穴）。

    18周目の verifier が `"data_source": "sample", "is_real": False` を
    `"measured", True` に変異させたところ、**この契約ファイル44件は
    全部緑のままだった。** 条件文が名指ししているので塞ぐ。
    """
    import asyncio
    import importlib

    # 属性参照で APIRouter を掴まないよう `importlib` で引く（上と同じ理由）
    A = importlib.import_module("routers.admin_channel_router")

    # 印そのもの（ここが verifier の変異 M4 の対象）
    assert A.DATA_SOURCE["is_real"] is False, \
        "YouTube に接続していない固定値が実測を名乗っている"
    assert A.DATA_SOURCE["data_source"] == "sample", \
        f"出所の印が sample でない（{A.DATA_SOURCE['data_source']!r}）"

    # **印が実際に応答へ載ること。** 定数だけ直しても経路が付け忘れたら戻る
    本文 = asyncio.run(A.get_channel_detail(A._channels[0]["id"]))
    assert 本文["is_real"] is False
    assert 本文["data_source"] == "sample"

    # C4 の条件文が名指しした 15200 が、印なしで出ていないこと
    assert 本文["kpi"]["watch_time_hours"] == 15200, "経路が変わった（テストを見直す）"
    assert 本文["connected"] is False, "接続していないのに接続済みと名乗っている"


def test_18周目_魂パスポートが段位を定数で描かない():
    """`SoulPassport.jsx` の admin(tech) 側（R1.5-C4・18周目・自力発見）。

    17周目に owner(biz) 側だけ直して **admin(tech) 側が取り残されていた**:
      - `level || "Apprentice"` … 段位が読めなくても "Apprentice" と名乗る
      - `xp || 0`               … 未取得と実際の 0 が区別できない
    """
    import re
    from pathlib import Path as _Path

    ルート = _Path(__file__).resolve().parent.parent.parent.parent

    def 描画部を読む(相対):
        js = (ルート / 相対).read_text(encoding="utf-8")
        s = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        return "\n".join(行 for 行 in s.splitlines()
                         if not 行.strip().startswith("//"))

    描画部 = 描画部を読む("frontend/src/components/SoulPassport.jsx")

    assert '"Apprentice"' not in 描画部, \
        "段位が読めないときに 'Apprentice' と名乗っている"
    assert "tech_rank?.xp || 0" not in 描画部, \
        "未取得の XP と実際の 0 が区別できない（`??` を使う）"

    # 相方の biz 側も戻っていないこと（17周目の修正の回帰防止）
    assert '"Dreamer"' not in 描画部

    # 段位を送る側も捏造しないこと
    送り出し = 描画部を読む("frontend/src/components/DirectorBriefing.jsx")
    assert "biz_rank: 'Novice'" not in 送り出し, \
        "画面が段位 'Novice' を捏造して送っている"


# ============================================================
# 19周目（18周目の反例を受けた自主掃引で見つけたもの）
#
# 18周目の反例は「except 節の辞書リテラル」で、17周目に作った式単位の掃引を
# すり抜けた。そこで掃引軸を4本足して掃いた結果、**本線から到達する同種が
# 3件**出た。いずれも「計測していない／検査していないのに、実測・確認済みを
# 名乗る」形で、うち2件は永続化される。
# ============================================================


def test_19周目_落ちた品質検査を黙って捨てない():
    """`quality_gate_plugins.run_all_plugins()` の except（R1.5-C4・19周目）。

    プラグインが1本でも例外を投げると、except がログを出すだけで
    **その項目の減点も「そのカテゴリを検査した」という事実も丸ごと消えて**いた。
    品質ゲートは 100点からの減点方式なので、

        **検査が壊れているほどスコアが上がる。**

    しかも呼び出し元（`agents/workers/quality_gate_worker.py`）は直後に
    `ctx.quality_scored = True` を立てるので、「22項目を検査した実測値」として
    force-render の判定まで通ってしまう。

    本線から到達する: `quality_gate_worker.py:153` が `run_all_plugins` を呼ぶ。
    """
    import quality_gate_plugins as Q

    class 落ちる検査:
        name = "gv19_always_fails"
        category = "core"
        capability = None

        def analyze(self, ctx, template_config=None):
            raise RuntimeError("わざと落とす")

    class 通る検査:
        name = "gv19_deducts"
        category = "core"
        capability = None

        def analyze(self, ctx, template_config=None):
            return {"deductions": 20, "feedback": ["減点20"]}

    class 文脈:
        declared_gaps = set()

    元 = Q.PLUGIN_REGISTRY[:]
    try:
        Q.PLUGIN_REGISTRY[:] = [通る検査(), 落ちる検査()]
        結果 = Q.run_all_plugins(文脈(), None)
    finally:
        Q.PLUGIN_REGISTRY[:] = 元

    # **落ちた検査が記録に残る**
    assert 結果["all_plugins_ran"] is False, "検査が落ちたのに『全項目を検査した』と名乗った"
    落ちた = 結果["failed_plugins"]
    assert len(落ちた) == 1, f"落ちた検査が記録されていない（{落ちた}）"
    assert 落ちた[0]["name"] == "gv19_always_fails"
    assert 落ちた[0]["category"] == "core"
    assert "RuntimeError" in 落ちた[0]["error"]

    # **利用者が読む文言にも出る**（記録だけでは画面に届かない）
    assert any("検査されていません" in f for f in 結果["feedback"]), \
        "落ちた検査が利用者向けの文言に出ていない"

    # 通った検査の減点は生きている（門が広すぎないこと）
    assert 結果["total_deductions"] > 0

    # 全部通ったときは印が立つ（fail-open になっていないこと）
    try:
        Q.PLUGIN_REGISTRY[:] = [通る検査()]
        正常 = Q.run_all_plugins(文脈(), None)
    finally:
        Q.PLUGIN_REGISTRY[:] = 元
    assert 正常["all_plugins_ran"] is True
    assert 正常["failed_plugins"] == []


def test_19周目_落ちた検査が実行記録まで届く():
    """上の相方 — **worker が拾わなければ画面にも記録にも届かない**（R1.5-C4・19周目）。

    10周目・13周目・15周目はすべて「片側だけ直して元に戻る」形だった。
    **`quality_gate_worker` を実際に走らせて確かめる**（ソース文字列の検査だと、
    同じ語が別の場所に残っているだけで素通りする——実際に1度素通りさせた）。
    """
    import asyncio

    import quality_gate_plugins as Q
    from agents.pipeline_types import PipelineContext
    from agents.workers.quality_gate_worker import QualityGateWorker

    class 落ちる検査:
        name = "gv19_worker_fails"
        category = "core"
        capability = None

        def analyze(self, ctx, template_config=None):
            raise RuntimeError("わざと落とす")

    def 走らせる(登録):
        ctx = PipelineContext(video_path="d.mp4", session_id="s-gv19w")
        ctx.segments = [{"text": "あ", "start": 0.0, "end": 1.0}]
        ctx.declared_gaps = set()
        元 = Q.PLUGIN_REGISTRY[:]
        try:
            Q.PLUGIN_REGISTRY[:] = 登録
            結果 = asyncio.run(QualityGateWorker().execute(ctx))
        finally:
            Q.PLUGIN_REGISTRY[:] = 元
        return ctx, 結果

    # ── 検査が落ちた実走 ──
    ctx, 結果 = 走らせる([落ちる検査()])

    報告 = ctx.quality_gate_report
    assert 報告.get("all_plugins_ran") is False,         "検査が落ちたのに実行記録が『全項目を検査した』と言っている"
    落ちた = 報告.get("failed_plugins") or []
    assert any(p.get("name") == "gv19_worker_fails" for p in 落ちた),         f"落ちた検査が実行記録に残っていない（{落ちた}）"

    # **画面へ渡る側にも載る**（記録だけだと UI に届かない）
    assert 結果.data.get("all_plugins_ran") is False,         "画面へ渡すデータに『全項目を検査したか』が無い"
    assert any(p.get("name") == "gv19_worker_fails"
               for p in (結果.data.get("failed_plugins") or [])),         "画面へ渡すデータに落ちた検査が無い"

    # ── 全部通った実走（門が広すぎないこと） ──
    class 通る検査:
        name = "gv19_worker_ok"
        category = "core"
        capability = None

        def analyze(self, ctx, template_config=None):
            return {"deductions": 0, "feedback": []}

    ctx2, 結果2 = 走らせる([通る検査()])
    assert ctx2.quality_gate_report.get("all_plugins_ran") is True
    assert (ctx2.quality_gate_report.get("failed_plugins") or []) == []



def test_19周目_完了サマリーが採点の旗を見る():
    """`ProductionWizard.jsx` の完了サマリー（R1.5-C4・19周目）。

    同じファイルの上（`採点した` / `effectiveScore`）で旗を組み立てているのに、
    **完了サマリーのカードだけがそれを迂回して生の `quality_score` を描いていた。**
    16周目に `ProductionPipeline.jsx` で直したのと同じ形が姉妹ファイルに残っていた。
    """
    import re
    from pathlib import Path as _Path

    ルート = _Path(__file__).resolve().parent.parent.parent.parent

    def 描画部を読む(相対):
        js = (ルート / 相対).read_text(encoding="utf-8")
        s = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        return "\n".join(行 for 行 in s.splitlines()
                         if not 行.strip().startswith("//"))

    描画部 = 描画部を読む("frontend/src/components/ProductionWizard.jsx")

    assert "qualityGateData.scored ?" in 描画部, \
        "完了サマリーが採点の旗を見ていない"
    assert "{quality_score}点" not in 描画部, \
        "完了サマリーが旗を迂回して生の点を描いている"
    assert "未計測" in 描画部, "未計測のときに未計測と書いていない"


def test_19周目_AIスコアで人間のチェックを自動でONにしない():
    """`StepReviewPanel.jsx` の自動チェック（R1.5-C4・19周目）。

    AI のカテゴリスコアが 70点以上だと、そのステージの**人間用チェック項目を
    全部 true に自動で倒していた**。倒される項目は
    「固有名詞（人名・地名・社名）は正しいですか？」のような、
    **人が目で見ないと答えられない問い**。

    `isStageComplete()` はチェック状態だけを見るので、自動 ON のまま
    `handleApprove()` が `completed: true` を送り、
    **誰も見ていないレビューが「確認済み」として永続化**されていた。
    """
    import re
    from pathlib import Path as _Path

    ルート = _Path(__file__).resolve().parent.parent.parent.parent
    js = (ルート / "frontend/src/components/StepReviewPanel.jsx").read_text(encoding="utf-8")
    s = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    描画部 = "\n".join(行 for 行 in s.splitlines() if not 行.strip().startswith("//"))

    assert "autoChecks" not in 描画部, \
        "AI スコアで人間のチェック項目を自動 ON にしている"
    assert "checkItems.forEach((_, i) => { checks[i] = true; })" not in 描画部, \
        "人間用チェック項目を機械が全部 true にしている"

    # AI スコアの表示自体は残っていること（情報を消しただけにしない）
    assert "getStageScore" in 描画部, "AI スコアのバッジまで消してしまった"


def test_19周目_CE1_実登録プラグインが検査できなくても見逃さない(tmp_path):
    """`analyze()` の中で握り潰した例外を拾う（R1.5-C4・19周目 CE-1）。

    19周目に入れた門（`run_all_plugins` の try）は
    **`analyze()` の外へ出た例外しか拾わない**。ところが実際に登録されている
    プラグイン（Loudness / Resolution / Codec / AudioPresence / Bitrate /
    AIRule / ThumbnailQuality）は**自分の中で例外を握り潰し**、try の前で 0 に
    初期化した `deductions` をそのまま返す。つまり:

        **ffmpeg が壊れているだけで broadcast / core が 100.0「✅ 優秀」になり、
        `all_plugins_ran: true` / `failed_plugins: []` のまま force-render まで通る。**

    「検査していない」が「検査して減点ゼロだった」に化けていた。

    **このテストは合成プラグインを使わない。** 19周目に最初に書いた契約は
    `analyze()` が `RuntimeError` を投げる合成プラグインで `PLUGIN_REGISTRY` を
    差し替えていたため、**実登録プラグインは一度もこの契約を通らなかった**
    （gate-verifier 19周目の指摘）。ここでは実レジストリのまま ffmpeg だけ壊す。
    """
    import asyncio
    import unittest.mock as _m

    import video_editor_engine
    from agents.pipeline_types import PipelineContext
    from agents.workers.quality_gate_worker import QualityGateWorker

    # プレビューが実在しないと各プラグインは早期 return するので実ファイルを置く
    プレビュー = tmp_path / "preview.mp4"
    プレビュー.write_bytes(b"x" * 4096)

    def 走らせる(壊す):
        ctx = PipelineContext(video_path="d.mp4", session_id="s-ce1")
        ctx.preview_path = str(プレビュー)
        ctx.segments = [{"text": "あ", "start": 0.0, "end": 1.0}]
        ctx.declared_gaps = set()
        if not 壊す:
            asyncio.run(QualityGateWorker().execute(ctx))
            return ctx
        落ちる = _m.MagicMock(
            side_effect=FileNotFoundError("ffmpeg: No such file or directory"))
        with _m.patch.object(video_editor_engine.video_editor.ffmpeg,
                             "get_video_info", 落ちる),              _m.patch.object(video_editor_engine.video_editor.ffmpeg,
                             "run_command", 落ちる):
            asyncio.run(QualityGateWorker().execute(ctx))
        return ctx

    # ── ffmpeg が壊れている（本番で普通に起きる状態） ──
    ctx = 走らせる(壊す=True)
    報告 = ctx.quality_gate_report

    assert 報告.get("all_plugins_ran") is False,         "ffmpeg が壊れて検査できていないのに『全項目を検査した』と名乗った"

    落ちた名 = {p.get("name") for p in (報告.get("failed_plugins") or [])}
    # verifier が名指しした4件。**握り潰しは analyze() の中なので、
    # 外側の try だけでは1件も拾えない**
    for 名 in ("loudness_check", "resolution_check", "codec_check",
              "audio_presence_check"):
        assert 名 in 落ちた名,             f"{名} が検査できていないのに記録に残っていない（{sorted(落ちた名)}）"

    # 利用者向けの文言にも出る（記録だけでは画面に届かない）
    assert any("検査されていません" in f for f in (ctx.quality_feedback or [])),         "検査できなかったことが利用者向けの文言に出ていない"

    # ── ffmpeg が生きている（門が広すぎないこと） ──
    正常 = 走らせる(壊す=False)
    落ちた名2 = {p.get("name") for p in (正常.quality_gate_report.get("failed_plugins") or [])}
    for 名 in ("loudness_check", "resolution_check", "codec_check",
              "audio_presence_check"):
        assert 名 not in 落ちた名2,             f"ffmpeg が生きているのに {名} を『検査できなかった』と記録した"


def test_19周目_維持率予測に捏造した成分を混ぜない():
    """`RetentionPredictionCheck`（R1.5-C4・19周目・保留リスト #2）。

    **条件文が名指しする「retention 分析」そのもの。** 2つ偽があった:

    1. `+ 70 * weights["hook_strength_weight"]` — コメントに
       「フック強度はHookStrengthCheckから」と書きながら**一度も参照しておらず**、
       予測維持率の **25% が捏造**だった
    2. ペーシングが測れないとき `pacing_score = 50`。**50 は実際に取りうる点**なので、
       実測した 50 と測れなかった 50 が区別できない

    `HookStrengthCheck` は `PLUGIN_REGISTRY` でこのプラグインより前に走るので、
    `run_all_plugins` が積んだ実測値を引く。引けなければ予測を名乗らない。
    """
    import quality_gate_plugins as Q

    重み = {
        "target_retention_percent": 80,
        "dead_air_max": 3.0,
        "scoring": {
            "segment_density_weight": 0.3,
            "hook_strength_weight": 0.25,
            "dead_air_penalty_weight": 0.25,
            "pacing_consistency_weight": 0.2,
        },
    }

    class 設定:
        is_active = True
        template_id = "t"

        def get_retention_prediction_config(self):
            return 重み

    def 文脈(フック=None, segs=None):
        class C:
            preview_path = None
            declared_gaps = set()
        c = C()
        c.segments = segs if segs is not None else [
            {"text": "あ", "start": float(i * 3), "end": float(i * 3 + 2.0)}
            for i in range(6)
        ]
        if フック is not None:
            c._quality_plugin_results = {
                "hook_strength_check": {"details": {"hook_score": フック}}
            }
        return c

    # ── フック強度が実測されている → 予測を出し、**その実測値を使う** ──
    低い = Q.RetentionPredictionCheck().analyze(文脈(フック=10), 設定())
    高い = Q.RetentionPredictionCheck().analyze(文脈(フック=100), 設定())
    assert 低い["checked"] is True and 高い["checked"] is True
    assert 低い["details"]["hook_score"] == 10
    assert 高い["details"]["hook_score"] == 100
    assert 低い["details"]["predicted_retention"] != 高い["details"]["predicted_retention"],         "フック強度を変えても予測が動かない（定数を足している）"
    差 = 高い["details"]["predicted_retention"] - 低い["details"]["predicted_retention"]
    assert abs(差 - (100 - 10) * 0.25) < 0.2,         f"実測のフック強度が重みどおりに効いていない（差 {差}）"

    # ── フック強度が無い → **予測を名乗らない** ──
    無し = Q.RetentionPredictionCheck().analyze(文脈(フック=None), 設定())
    assert 無し["checked"] is False, "フック強度が無いのに予測を出した"
    assert 無し["details"]["predicted_retention"] is None
    assert 無し["deductions"] == 0
    assert "hook_strength" in (無し["details"].get("unmeasured") or [])

    # ── ペーシングが測れない → **定数 50 で埋めない** ──
    測れない = Q.RetentionPredictionCheck().analyze(
        文脈(フック=70, segs=[{"text": "あ", "start": 0.0, "end": 2.0}]
            + [{"text": "い", "start": float(i), "end": float(i)} for i in range(3, 8)]),
        設定())
    assert 測れない["details"]["pacing_score"] is None, "測れなかったペーシングを 50 で埋めた"
    assert 測れない["checked"] is False
    assert 測れない["details"]["predicted_retention"] is None

    # ── 本線（run_all_plugins）では実測フックが渡る ──
    class 本線文脈:
        preview_path = None
        declared_gaps = set()
        segments = [{"text": "あ", "start": float(i * 3), "end": float(i * 3 + 2.5)}
                    for i in range(8)]

    結果 = Q.run_all_plugins(本線文脈(), None)
    予測 = (結果["plugin_results"].get("retention_prediction_check") or {})
    assert 予測.get("checked") is True,         "本線でフック強度の実測値が渡っていない（配線が切れている）"
    assert isinstance(予測.get("details", {}).get("hook_score"), (int, float))


def test_19周目_予測検証が計測していない実測を名乗らない():
    """`services/prediction_validator.py` の `validate_prediction`（R1.5-C4・19周目）。

    `actual`（＝実測）という名前の下に**既定値**が入っていた:

        "ctr": metrics.get("click_through_rate", 0.0)
        "elapsed_hours": actual_metrics_dict.get("elapsed_hours", 24)

    `elapsed_hours` は `services/post_publish_collector.py` の `_generate_mock_data()`
    でしか産出されない鍵で、実 API 統合（api_mode が real）は NotImplementedError を
    投げる。**実データが流れ始めた日にこそ 24 が効き続ける。**
    CTR が届かないほうはもっと悪く、0.0 が「実測 CTR」になり、予測 5.0% に対して
    「誤差 100%・重大な乖離」という**計測していない判定**まで出ていた。

    しかもこのレポートは台帳（Wagamama Ledger）の feedback レーンへ入り
    `wagamama_manager._save()` で**恒久保存される**（18周目に直した
    「作り物が台帳に焼き付く」と同型）。だから返り値だけでなく
    **保存された側**まで確かめる。

    本線から到達する: `routers/youtube_optimizer.py:1062` の feedback-loop が
    :1166 で `validate_prediction` を呼び、:1178 で status を見て success を決める。
    """
    import asyncio
    from services.prediction_validator import PredictionValidator

    class 台帳:
        def __init__(self, 予測):
            self.record = {
                "wagamama_id": "W-001",
                "lanes": {"experience": {"predicted_ctr": 予測}},
            }
            self.saved = 0

        def get_record(self, wagamama_id):
            return self.record

        def _save(self):
            self.saved += 1

    v = PredictionValidator()

    # ── 正常系（実測が揃っている）は今までどおり通す。門が常に閉じたら門が無いのと同じ ──
    m = 台帳(5.0)
    r = asyncio.run(v.validate_prediction(
        "W-001",
        {"metrics": {"click_through_rate": 8.0}, "elapsed_hours": 72},
        wagamama_manager=m))
    assert r.get("status") not in ("error", "skipped"), "実測が揃っているのに止めた（正常系まで塞いだ）"
    assert r["analysis"]["checked"] is True
    assert r["analysis"]["difference"] == 3.0
    assert r["analysis"]["significant_deviation"] is True
    assert m.saved == 1
    保存 = m.record["lanes"]["feedback"]["validation_report"]
    assert 保存["actual"]["is_real"] is True, "台帳側に実測の印が届いていない"
    assert 保存["actual"]["data_source"] == "measured"

    # ── elapsed_hours を既定値 24 で埋めない。**台帳側も** ──
    m2 = 台帳(5.0)
    r2 = asyncio.run(v.validate_prediction(
        "W-001", {"metrics": {"click_through_rate": 5.2}}, wagamama_manager=m2))
    assert r2["actual"]["elapsed_hours"] is None, "計測していない経過時間を 24 で埋めた"
    assert m2.record["lanes"]["feedback"]["validation_report"]["actual"]["elapsed_hours"] is None, \
        "台帳に既定値の 24 が焼き付いた（返り値だけ直しても意味がない）"
    assert r2["actual"]["measured_at"] is None, "計測していないのに収集時刻を付けた"

    # ── 実測 CTR が届いていない → 0.0 を実績と呼ばない・乖離を判定しない・台帳に書かない ──
    m3 = 台帳(5.0)
    r3 = asyncio.run(v.validate_prediction(
        "W-001", {"elapsed_hours": 30}, wagamama_manager=m3))
    assert r3.get("status") == "skipped", "計測していないのに success 側へ返した"
    assert r3["actual"]["ctr"] is None, "届いていない CTR を 0.0 で埋めた"
    assert r3["actual"]["is_real"] is False
    assert r3["actual"]["data_source"] == "unavailable"
    assert r3["analysis"]["checked"] is False
    assert r3["analysis"]["significant_deviation"] is None, "計測していないのに乖離を判定した"
    assert r3["analysis"]["error_margin_pct"] is None
    assert m3.saved == 0, "未計測のレポートで台帳を保存した"
    assert "feedback" not in m3.record["lanes"], "未計測のレポートを台帳へ恒久保存した"

    # ── 収集側が作り物（is_mock）だと言っている → 実測として台帳に焼き付けない ──
    m4 = 台帳(5.0)
    r4 = asyncio.run(v.validate_prediction(
        "W-001",
        {"metrics": {"click_through_rate": 4.4}, "elapsed_hours": 24, "is_mock": True},
        wagamama_manager=m4))
    assert r4.get("status") == "skipped"
    assert r4["actual"]["data_source"] == "sample"
    assert r4["actual"]["ctr"] is None
    assert m4.saved == 0, "作り物のレポートで台帳を保存した"

    # ── 予測 CTR が 0 以下 → 誤差率は割れない。「誤差 0%・乖離なし」と名乗らない ──
    m5 = 台帳(0.0)
    r5 = asyncio.run(v.validate_prediction(
        "W-001",
        {"metrics": {"click_through_rate": 2.0}, "elapsed_hours": 24},
        wagamama_manager=m5))
    assert r5["analysis"]["error_margin_pct"] is None, "割れない誤差率を 0 で埋めた"
    assert r5["analysis"]["significant_deviation"] is None, "判定していないのに『乖離なし』と書いた"
    assert r5["analysis"]["difference"] == 2.0, "実際に引き算できる差まで消した"


def test_19周目_YouTube全体スコアが分析の有無を見る():
    """`YouTubeOptimizerPanel.jsx` のヘッダー「全体スコア」（R1.5-C4・19周目）。

    以前は 4 要素を **三項の定数だけ**で足していた
    （`(hook_score || 0)*0.3 + (候補3件以上 ? 100 : 50)*0.3 + ...`）。
    どの項も「件数が閾値以上か」しか見ておらず、**その分析が走ったかを
    見ていなかった。** サムネ生成が候補を返せなくても 50 点、SEO メタデータが
    null でも 60 点が付き、4 要素すべて未計測でもヘッダーに数字が出ていた。
    16周目 `ProductionPipeline.jsx` / 19周目 `ProductionWizard.jsx` と同型。

    「消えたこと」だけでは弱いので、**新しい判定を実際に見ていること**
    （要素ごとの `走った` と、走った要素だけを分母にする加重平均）も見る。
    """
    import re
    from pathlib import Path as _Path

    ルート = _Path(__file__).resolve().parent.parent.parent.parent

    def 描画部を読む(相対):
        js = (ルート / 相対).read_text(encoding="utf-8")
        s = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        return "\n".join(行 for 行 in s.splitlines()
                         if not 行.strip().startswith("//"))

    描画部 = 描画部を読む("frontend/src/components/YouTubeOptimizerPanel.jsx")

    # (1) 分析の有無を見ない定数フォールバックが戻っていない
    for 旧式 in (
        "(optimizationData.hook_score || 0) * 0.3",
        "optimizationData.thumbnail_candidates?.length >= 3 ? 100 : 50",
        "optimizationData.seo_metadata?.tags?.length >= 15 ? 100 : 60",
        "optimizationData.highlights?.length >= 3 ? 100 : 50",
    ):
        assert 旧式 not in 描画部, f"分析の有無を見ない定数フォールバックが戻っている: {旧式}"

    # (2) 4 要素それぞれが「分析が走ったか」を実際に見ている
    assert "!!optimizationData?.hook_analysis" in 描画部, \
        "フックが分析の有無を見ずに採点されている"
    assert "Array.isArray(optimizationData?.thumbnail_candidates)" in 描画部, \
        "サムネが分析の有無を見ずに採点されている"
    assert "!!optimizationData?.seo_metadata" in 描画部 \
        and "Array.isArray(optimizationData.seo_metadata.tags)" in 描画部, \
        "SEO が判定の材料の有無を見ずに採点されている"
    assert "Array.isArray(optimizationData?.highlights)" in 描画部, \
        "山場が分析の有無を見ずに採点されている"
    assert "走った: true" not in 描画部, \
        "常に採点済みの旗を立てている（門が開きっぱなし）"
    assert 描画部.count("走った") >= 6, \
        "要素ごとの「走ったか」の旗が足りない"

    # (3) 走っていない要素を点に含めない（分母が走った要素の重みで動く）
    assert "採点要素.filter(e => e.走った)" in 描画部, \
        "走った要素だけを集めていない"
    assert "/ 重みの合計" in 描画部, \
        "分母が固定で、走らなかった要素の分まで薄めて採点している"

    # (4) 1 つも走っていなければ点を出さない（0 は実際に取りうる点なので印にならない）
    assert re.search(r"重みの合計 > 0[\s\S]{0,400}?:\s*null;", 描画部), \
        "採点できた要素が無いときに 0 を置いている"

    # (5) 描画が採点の旗を見て「未計測」と書く
    assert "{全体スコアを採点した ? (" in 描画部, "描画が採点の旗を見ていない"
    assert "全体スコア: 未計測" in 描画部, "未計測のときに未計測と書いていない"
    assert "未計測の要素.length > 0 &&" in 描画部, \
        "どの要素が未計測だったかを画面に出していない"
    assert 描画部.index("全体スコアを採点した ?") < 描画部.index("Math.round(overallScore)"), \
        "旗より先に数字を描いている"

    # (6) 巻き込み事故の防止 — footer の SEO 表示はユーザー決定で limits 送り。
    #     未取得時に悲観側へ倒れるので偽の success ではなく、消してはいけない
    assert "tags?.length >= 15 ? '良好' : '改善余地あり'" in 描画部, \
        "limits 送りにした footer の SEO 表示を巻き込んで消している"


def test_19周目_チャンネル統計は未計測を実測として返さない():
    """**C4 条件文の「チャンネル統計」**（R1.5-C4・19周目・保留リスト #6）。

    `services/youtube_analytics_client.py` の `get_channel_performance()` は、
    3つの経路が**どれも同じ見た目の `ChannelPerformance`** を返していた:

    | 経路 | 何を偽っていたか |
    |---|---|
    | API 未接続・キャッシュ無し | 生成したままの `avg_ctr=0.0` / `total_views=0` |
    | API 未接続・キャッシュあり | いつのものか分からない値。取得時刻も付かない。`cached.get(key, 0)` で欠損まで 0 に化け、`total_subscribers` は復元すらしていなかった |
    | API 呼び出しが落ちた | except が log を出すだけで**空の `perf` がそのまま返る** |

    最後の1件が19周目の掃引が「いちばん取りこぼしやすい」と名指しした形
    （**例外を握り潰した後、try の前で初期化済みの変数がそのまま成果として返る**）。
    `avg_ctr=0.0` は「計測したら CTR 0% だった」と読めるので呼び手からは
    成功と区別が付かず、`performance_cache.json` と
    `get_performance_benchmarks` の基準値へ流れていた。

    到達: `main.py` → `routers/__init__.py` → `admin_quota_router`
    → `service_container` の `youtube_analytics` → `YouTubeAnalyticsClient`。
    """
    import asyncio

    from unittest.mock import MagicMock

    from services.youtube_analytics_client import (ChannelPerformance,
                                                   YouTubeAnalyticsClient)

    def 客(接続):
        c = YouTubeAnalyticsClient()
        c._save_cache = lambda: None            # 共有の状態ファイルを書かない
        c._cache = {"videos": {}, "channel": {}, "last_updated": ""}
        c._available = 接続
        return c

    # ── 1. API 未接続・キャッシュ無し → 0 を実測として返さない ──
    未接続 = asyncio.run(客(False).get_channel_performance())
    assert 未接続.is_real is False, "一度も接続していないチャンネル統計が実測を名乗った"
    assert 未接続.data_source == "unavailable", f"出所の印が無い（{未接続.data_source!r}）"
    assert 未接続.total_views is None, "計測していない総再生数を 0 として返した"
    assert 未接続.avg_ctr is None, "計測していない CTR を 0.0 として返した"
    assert 未接続.total_subscribers is None, "計測していない登録者数を 0 として返した"
    assert 未接続.last_sync is None, "同期していないのに同期時刻が入っている"
    assert 未接続.unavailable_reason, "なぜ実測でないかが残っていない"

    # ── 2. API 呼び出しが落ちた → except の後で空の perf が実測として返らない ──
    落ちた客 = 客(True)
    壊れた = MagicMock()
    壊れた.reports().query.side_effect = OSError("boom")
    落ちた客._analytics_service = 壊れた
    落ちた = asyncio.run(落ちた客.get_channel_performance())
    assert 落ちた.is_real is False, "取得が落ちたのに実測を名乗った"
    assert 落ちた.total_views is None, "取得が落ちたのに総再生数 0 を実測として返した"
    assert 落ちた.avg_ctr is None, "取得が落ちたのに CTR 0.0 を実測として返した"
    assert 落ちた.last_sync is None, "取得していないのに同期時刻が入っている"
    assert "OSError" in (落ちた.unavailable_reason or ""), \
        f"失敗の理由が握り潰されている（{落ちた.unavailable_reason!r}）"
    assert 落ちた客._cache["channel"] == {}, "取得が落ちた値が台帳に焼き付いた"

    # ── 3. キャッシュ由来 → 値は残すが、実測でも「いま同期した」でもない ──
    キャッシュ客 = 客(False)
    キャッシュ客._cache["channel"] = {"avg_ctr": 4.5, "total_views": 8000}
    キャッシュ客._cache["last_updated"] = ""     # 取得時刻が残っていない
    キャッシュ = asyncio.run(キャッシュ客.get_channel_performance())
    assert キャッシュ.avg_ctr == 4.5, "キャッシュの値まで捨てた（門が常に閉じている）"
    assert キャッシュ.is_real is False, "キャッシュ由来の値が実測を名乗った"
    assert キャッシュ.data_source == "cache", \
        f"出所の印が cache でない（{キャッシュ.data_source!r}）"
    assert キャッシュ.last_sync is None, \
        "取得時刻が無いのに現在時刻を付けた（いま同期したように見える）"
    assert キャッシュ.total_subscribers is None, \
        "キャッシュに無い登録者数を 0 で埋めた（0 は実際に取りうる値なので印にならない）"

    # ── 4. 正常系は今までどおり実測を返す（門が常に閉じるなら門が無いのと同じ）──
    正常客 = 客(True)
    応答 = MagicMock()
    応答.reports().query().execute.return_value = {"rows": [
        ["2026-05-22", 100, 500, 0.04, 150.0, 40.0, 5],
        ["2026-05-21", 200, 1000, 0.06, 170.0, 44.0, 10],
    ]}
    正常客._analytics_service = 応答
    正常 = asyncio.run(正常客.get_channel_performance(days=7))
    assert 正常.is_real is True, "API が返した実測値に印が付かない（門が常に閉じている）"
    assert 正常.data_source == "analytics_api"
    assert 正常.last_sync, "実測したのに取得時刻が残っていない"
    assert (正常.total_views, 正常.total_subscribers, 正常.avg_ctr) == (300, 15, 5.0), \
        "正常系の集計が変わった（テストを見直す）"
    # 印は台帳へ書き戻さない。書き戻すと次に読んだとき本物と区別できなくなる
    assert set(正常客._cache["channel"]) & {"is_real", "data_source", "last_sync"} == set(), \
        "印がキャッシュへ焼き付いている"
    assert 正常客._cache["channel"]["total_views"] == 300

    # ── 5. 辞書にしても印が落ちない（外へ出るのはこの形）──
    素 = ChannelPerformance().to_dict()
    assert 素["is_real"] is False and 素["data_source"] == "unavailable", \
        "既定が fail-closed でない（初期化しただけの値が実測を名乗る）"
    assert 素["last_sync"] is None
    assert 落ちた.to_dict()["is_real"] is False, "辞書にした時点で印が消えた"


def test_19周目_SmartCut戦略が未応答のとき実測を名乗らない():
    """R1.5-C4: Strategist が答えていないカット戦略が、実測の顔で台帳に載らないこと。

    保留リスト #8。本番の smartcut ルーター（backend/routers/smartcut.py:414,433）が
    SmartCutStrategyService を生成し、その CutStrategy は
    evolution_sync_service.record_strategy から evolution_log.json の
    strategy_detail に丸ごと永続化される。

    | 何が偽だったか | どこ |
    |---|---|
    | 未応答の定数戦略に generated_at だけ現在時刻が付く（「いま算出した」に見える） | CutStrategy.default() |
    | JSON がパースできさえすれば、鍵が欠けても項目ごとの既定値で埋まり、model_used に本物のモデル名が入る | _parse_response |

    後者がとくに悪い。`{}` を返しただけで「AI生成戦略・ブランド整合性0.50」という
    実測の顔の戦略が出来上がり、default() が持っている「Strategist未応答」の印を迂回していた。
    """
    import json
    from unittest.mock import MagicMock
    from services.smartcut_strategy_service import SmartCutStrategyService, CutStrategy

    def 応答(payload):
        m = MagicMock()
        m.text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return m

    サービス = SmartCutStrategyService(max_sessions=2)

    # ── (a) 未応答の定数戦略が「いま算出した」に見えないこと ──
    既定 = CutStrategy.default()
    assert 既定.generated_at is None, "生成していないのに現在時刻を名乗っている"
    assert 既定.model_used == "default"
    assert "未応答" in 既定.summary

    # ── 正常系は今までどおり通ること。門が常に閉じるなら門が無いのと同じ ──
    満額 = {
        "summary": "実測の戦略",
        "position_weights": {"intro": 1.2, "body": 1.0, "highlight": 1.1, "outro": 0.9},
        "brand_alignment_score": 0.87,
        "recommended_cut_rate": 0.45,
    }
    正常 = サービス._parse_response(応答(満額), "gemini-3.6-flash")
    assert 正常.model_used == "gemini-3.6-flash", "正常系まで止めている（門が常に閉じている）"
    assert 正常.summary == "実測の戦略"
    assert 正常.brand_alignment_score == 0.87
    assert 正常.recommended_cut_rate == 0.45
    assert isinstance(正常.generated_at, str) and 正常.generated_at, "実応答なのに生成時刻が消えている"

    囲み = サービス._parse_response(
        応答("```json\n" + json.dumps(満額, ensure_ascii=False) + "\n```"), "gemini-3.6-flash")
    assert 囲み.model_used == "gemini-3.6-flash" and 囲み.summary == "実測の戦略"

    # 0 は「実際に取りうる値」。欠落と混同して門を閉じないこと
    ゼロ = サービス._parse_response(
        応答(dict(満額, brand_alignment_score=0, recommended_cut_rate=0)), "gemini-3.6-flash")
    assert ゼロ.model_used == "gemini-3.6-flash", "0 は実際に取りうる値なのに欠落と誤判定している"
    assert ゼロ.brand_alignment_score == 0.0

    # ── (b) 鍵が1つでも欠けたら、既定値で黙って埋めずに default() と同じ印を付けること ──
    for 欠落 in ("summary", "position_weights", "brand_alignment_score", "recommended_cut_rate"):
        壊れ = dict(満額)
        壊れ.pop(欠落)
        結果 = サービス._parse_response(応答(壊れ), "gemini-3.6-flash")
        assert 結果.model_used == "default", f"{欠落} が無いのに本物のモデル名を名乗った"
        assert 結果.summary == 既定.summary, f"{欠落} が無いのに AI が書いた戦略の顔をしている"
        assert 結果.generated_at is None, f"{欠落} が無いのに生成時刻が付いた"

    # 鍵はあるが答えていない（null）も同じ扱い
    null応答 = サービス._parse_response(
        応答(dict(満額, brand_alignment_score=None)), "gemini-3.6-flash")
    assert null応答.model_used == "default" and null応答.generated_at is None

    # 数値として読めないスコアを 0.5 で埋めないこと
    不正 = サービス._parse_response(
        応答(dict(満額, brand_alignment_score="invalid_score")), "gemini-3.6-flash")
    assert 不正.model_used == "default", "数値として読めないスコアを 0.5 で埋めて実測の顔にした"
    assert 不正.generated_at is None

    非辞書 = サービス._parse_response(応答("[1, 2, 3]"), "gemini-3.6-flash")
    assert 非辞書.model_used == "default" and 非辞書.generated_at is None

    # ── 台帳（evolution_sync_service.record_strategy が組む形）が壊れず、印が残ること ──
    台帳 = {
        "insight": f"ブランド整合性: {既定.brand_alignment_score:.2f}, "
                   f"推奨カット率: {既定.recommended_cut_rate:.1%}",
        "model_used": 既定.model_used,
        "generated_at": 既定.generated_at,
    }
    復元 = json.loads(json.dumps(台帳, ensure_ascii=False))
    assert 復元["generated_at"] is None, "台帳に作り物の時刻が残っている"
    assert 復元["model_used"] == "default"


def test_19周目_評価の無いテンプレートが平均満足度を名乗らない(tmp_path, monkeypatch):
    """`themes_router.get_template_stats()` の満足度と件数（R1.5-C4・19周目）。

    19周目の verifier の指摘:

    > 「テンプレート選択統計」は4カテゴリのどれにも素直に入らない。**むしろ
    > 同関数 L183 の `avg_satisfaction[tid] = 3.0`（誰も評価していないのに
    > 中央値を「平均満足度」として返す）のほうが偽の success として明確。**

    あわせて、台帳（`backend/branding/evolution_log.json`）が無い・壊れている
    ときに `total_selections: 0` を返し、**「集計できなかった」が
    「集計して0件だった」に化けていた**のも塞ぐ。

    どちらも管理者向けのテンプレート選択統計（getTemplateStats）がそのまま
    画面に描く数字で、`backend/main.py:253` で本番にマウントされている。

    **本丸は書き込み側だった。** `POST /themes/apply` が記録のたびに
    `satisfaction: 3` を台帳へ焼き付けるので、統計側の 3.0 だけ止めても
    実運用では平均が常に 3.0 のままになる（同じクラスの別経路）。
    """
    import asyncio
    import importlib
    import json

    monkeypatch.setenv("ANTIGRAVITY_WRITABLE_ROOT", str(tmp_path))
    台帳 = tmp_path / "backend" / "branding" / "evolution_log.json"
    台帳.parent.mkdir(parents=True, exist_ok=True)

    # 属性参照で APIRouter を掴まないよう importlib で引く（このファイルの他と同じ）
    T = importlib.import_module("routers.themes_router")

    # 本番にマウントされている読み口であること（経路が消えたら気付く）
    assert "/themes/stats" in {getattr(r, "path", "") for r in T.router.routes}, \
        "統計の読み口がルーターから外れている（テストを見直す）"

    def 統計():
        return asyncio.run(T.get_template_stats())

    def 台帳を書く(obj):
        台帳.write_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    # ── ① 誰も評価していない → 平均満足度を名乗らない ──
    台帳を書く({"template_selections": [
        {"template_id": "nhk_documentary", "theme_id": "cool"},
        {"template_id": "nhk_documentary", "theme_id": "warm", "satisfaction": "未評価"},
    ]})
    無評価 = 統計()
    assert 無評価["total_selections"] == 2, "選択の件数まで消してはいけない"
    assert 無評価["avg_satisfaction"]["nhk_documentary"] is None, \
        f"評価が1件も無いのに平均満足度を返した（{無評価['avg_satisfaction']['nhk_documentary']!r}）"
    assert 無評価["rated_counts"]["nhk_documentary"] == 0
    assert "nhk_documentary" in 無評価["unrated_templates"]

    # ── ② 評価が実在する → 今までどおり平均を出す（門が常に閉じないこと）──
    台帳を書く({"template_selections": [
        {"template_id": "nhk_documentary", "theme_id": "cool", "satisfaction": 4},
        {"template_id": "nhk_documentary", "theme_id": "warm", "satisfaction": 5},
        {"template_id": "mrbeast_entertainment", "theme_id": "energetic", "satisfaction": 2},
    ]})
    実測 = 統計()
    assert 実測["avg_satisfaction"]["nhk_documentary"] == 4.5
    assert 実測["avg_satisfaction"]["mrbeast_entertainment"] == 2.0
    assert 実測["rated_counts"]["nhk_documentary"] == 2
    assert 実測["checked"] is True and 実測["is_real"] is True
    assert 実測["total_selections"] == 3

    # ── ③ 台帳を集計できない → 0 件と名乗らない ──
    for 壊し方, 中身 in (
        ("0バイト", b""),
        ("壊れたJSON", b"{broken"),
        ("dictでない", b"[]"),
        ("選択欄の型が違う", b'{"template_selections": {}}'),
    ):
        台帳.write_bytes(中身)
        不能 = 統計()
        assert 不能["total_selections"] is None, \
            f"{壊し方}: 集計できなかったのに件数 {不能['total_selections']!r} を名乗った"
        assert 不能["checked"] is False and 不能["is_real"] is False, \
            f"{壊し方}: 未集計が実測を名乗っている"
        assert 不能["data_source"] == "unavailable", \
            f"{壊し方}: 出所の印が unavailable でない（{不能['data_source']!r}）"
        assert 不能.get("skip_reason"), f"{壊し方}: 集計できなかった理由が残っていない"

    # 台帳そのものが無いときも同じ
    台帳.unlink()
    無し = 統計()
    assert 無し["total_selections"] is None and 無し["is_real"] is False, \
        "台帳が無いのに「集計して0件だった」と名乗った"
    assert 無し["skip_reason"] == "ledger_missing"

    # ── ④ 台帳は読めて記録が無い → **こちらは本物の 0 件** ──
    台帳.write_bytes(b"{}")
    本物のゼロ = 統計()
    assert 本物のゼロ["total_selections"] == 0, "読めた台帳の0件まで未集計にしてはいけない"
    assert 本物のゼロ["checked"] is True and 本物のゼロ["is_real"] is True
    assert 本物のゼロ["data_source"] == "measured"

    # ── ⑤ 書き込み側が作り物の評価を台帳へ焼き付けない ──
    台帳.unlink()
    T._record_template_selection("nhk_documentary", "warm")
    行 = json.loads(台帳.read_text(encoding="utf-8"))["template_selections"]
    assert len(行) == 1
    assert 行[0]["satisfaction"] is None, \
        f"誰も評価していないのに評価値 {行[0]['satisfaction']!r} を台帳へ書いた"
    適用後 = 統計()
    assert 適用後["total_selections"] == 1
    assert 適用後["avg_satisfaction"]["nhk_documentary"] is None, \
        "台帳の既定値から平均満足度が生えている（3.0 の再発）"


# ── R1.5-C4（19周目）: サムネイル品質スコアが「見ていない画像」を採点したと名乗る ──
#
# `backend/services/thumbnail_analyzer.py` の `analyze_image` は
# `result.get("face_score", 50)` を4軸ぶん並べていた。Gemini Vision が
# **JSON としてはパースできるが採点キーを持たない**応答（キー欠落・別スキーマ・
# 数値でない値）を返すと、4軸すべてが黙って 50 点に化け、`overall_score` 50.0 /
# `verdict`「⚠️ 改善推奨」/ `detail`「Vision API分析: 50点」/
# `analysis_mode`「gemini_vision」がそのまま返っていた。
# **画像を一度も採点できていないのに「Vision API で分析した 50点」**を名乗る。
# `JSONDecodeError` のときだけ `text_match` に落ちて正直だったので、
# 「パースは通るが中身が違う」経路にだけ印が無かった（gate-verifier 19周目 保留リスト #1）。
#
# 到達: backend/main.py:236 `include_router(youtube_optimizer_router)`
#   → backend/routers/youtube_optimizer.py:2308 `analyze_thumbnail_image`
#   → :2324 `thumbnail_analyzer.analyze_image(req.image_path)`（戻り値を加工せず応答にする）


def test_19周目_サムネイル採点キーが欠けた応答は軸の点も総合点も名乗らない(tmp_path):
    """採点キーが無い軸は点を名乗らない。総合点・判定・CTR予測も出さない。

    以前は既定値 50 で4軸すべてが埋まり、`analysis_mode` は `gemini_vision` のままだった。
    """
    import sys
    import types
    from unittest.mock import MagicMock, patch

    偽ファクトリ = types.ModuleType("gemini_client_factory")
    クライアント = MagicMock()
    応答 = MagicMock()
    応答.text = '{"face_score": 90}'  # text / contrast / composition が無い
    クライアント.models.generate_content.return_value = 応答
    偽ファクトリ.get_gemini_client = lambda *a, **k: クライアント

    画像 = tmp_path / "c4_19_missing.jpg"
    画像.write_bytes(b"dummy jpg data")

    with patch.dict(sys.modules, {"gemini_client_factory": 偽ファクトリ}):
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        結果 = ThumbnailAnalyzer().analyze_image(str(画像))

    assert 結果["analysis_mode"] != "gemini_vision", (
        f"3軸の採点が無いのに Vision の採点を名乗っている: {結果['analysis_mode']}"
    )
    assert 結果["overall_score"] is None, (
        f"4軸そろっていないのに総合点を名乗っている: {結果['overall_score']}"
    )
    assert 結果["verdict"] is None, f"総合判定を名乗っている: {結果['verdict']}"
    assert 結果["predicted_ctr_impact"] is None, (
        f"CTR予測を名乗っている: {結果['predicted_ctr_impact']}"
    )
    assert 結果.get("is_real") is False, f"is_real の印が無い: {結果.get('is_real')}"
    assert 結果.get("data_source") == "unavailable", (
        f"data_source の印が無い: {結果.get('data_source')}"
    )

    軸 = {c["name"]: c for c in 結果["checks"]}
    for 名前 in ("テキスト可読性", "カラーコントラスト", "構図パターン"):
        assert 軸[名前]["score"] is None, (
            f"{名前}: 採点が無いのに {軸[名前]['score']} 点を名乗っている"
        )
        assert "Vision API分析" not in 軸[名前]["detail"], (
            f"{名前}: 採点していないのに分析したと読める detail: {軸[名前]['detail']}"
        )
    # 読めた軸まで捨てない。門が常に閉じるなら門が無いのと同じ
    assert 軸["顔クローズアップ"]["score"] == 90, "読めた軸まで捨てている（門が閉じすぎ）"


def test_19周目_サムネイル採点が数値でない応答も未計測として扱う(tmp_path):
    """文字列・範囲外・bool・null は採点として読めない。0〜100 の数値だけを本物とみなす。

    `true` を黙って 1 点、`"85"` を 85 点として扱うと、やはり見ていない画像の点になる。
    """
    import sys
    import types
    from unittest.mock import MagicMock, patch

    偽ファクトリ = types.ModuleType("gemini_client_factory")
    クライアント = MagicMock()
    応答 = MagicMock()
    応答.text = (
        '{"face_score": "85", "text_score": 150, '
        '"contrast_score": true, "composition_score": null}'
    )
    クライアント.models.generate_content.return_value = 応答
    偽ファクトリ.get_gemini_client = lambda *a, **k: クライアント

    画像 = tmp_path / "c4_19_bogus.jpg"
    画像.write_bytes(b"dummy jpg data")

    with patch.dict(sys.modules, {"gemini_client_factory": 偽ファクトリ}):
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        結果 = ThumbnailAnalyzer().analyze_image(str(画像))

    assert 結果["analysis_mode"] != "gemini_vision", (
        f"採点として読めない値しか無いのに Vision の採点を名乗っている: {結果['analysis_mode']}"
    )
    assert 結果["overall_score"] is None, (
        f"採点として読めない値から総合点を作っている: {結果['overall_score']}"
    )
    for 軸 in 結果["checks"]:
        assert 軸["score"] is None, (
            f"{軸['name']}: 採点として読めない値を {軸['score']} 点として名乗っている"
        )


def test_19周目_サムネイル4軸すべて読めた正常系はこれまでどおり実測を名乗る(tmp_path):
    """**門が常に閉じるなら門が無いのと同じ。** 正常系は修正前と同じ値を返す。

    0 点も「実際に取りうる採点」なので、印と取り違えて止めてはいけない。
    """
    import sys
    import types
    from unittest.mock import MagicMock, patch

    偽ファクトリ = types.ModuleType("gemini_client_factory")
    クライアント = MagicMock()
    応答 = MagicMock()
    応答.text = (
        '```json\n{"face_score": 85, "text_score": 75, "contrast_score": 90, '
        '"composition_score": 80, "overall_impression": "良い", '
        '"top_improvement": "特にありません"}\n```'
    )
    クライアント.models.generate_content.return_value = 応答
    偽ファクトリ.get_gemini_client = lambda *a, **k: クライアント

    画像 = tmp_path / "c4_19_ok.jpg"
    画像.write_bytes(b"dummy jpg data")

    with patch.dict(sys.modules, {"gemini_client_factory": 偽ファクトリ}):
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        分析器 = ThumbnailAnalyzer()
        結果 = 分析器.analyze_image(str(画像))

        零点 = MagicMock()
        零点.text = (
            '{"face_score": 0, "text_score": 0, '
            '"contrast_score": 0, "composition_score": 0}'
        )
        クライアント.models.generate_content.return_value = 零点
        零の結果 = 分析器.analyze_image(str(画像))

    assert 結果["analysis_mode"] == "gemini_vision", f"正常系まで止めている: {結果['analysis_mode']}"
    assert 結果["overall_score"] == 82.5, f"正常系の総合点が変わった: {結果['overall_score']}"
    assert 結果["verdict"] == "✅ 高品質", f"正常系の判定が変わった: {結果['verdict']}"
    assert 結果["predicted_ctr_impact"] is not None, "正常系の CTR 予測まで消している"
    assert [c["score"] for c in 結果["checks"]] == [85, 75, 90, 80], (
        f"正常系の軸の点が変わった: {[c['score'] for c in 結果['checks']]}"
    )
    assert 結果["checks"][0]["detail"] == "Vision API分析: 85点", (
        f"正常系の detail が変わった: {結果['checks'][0]['detail']}"
    )

    assert 零の結果["analysis_mode"] == "gemini_vision", (
        "0点は実際に取りうる採点なので止めてはいけない"
    )
    assert 零の結果["overall_score"] == 0.0, f"0点の総合点が出ていない: {零の結果['overall_score']}"


def test_19周目_サムネイル4軸に既定点のフォールバックが戻っていない():
    """`result.get("<軸>_score", 50)` 型の既定値が実コードへ復活していないことの静的ガード。

    「何が偽だったか」を残すコメント内の引用は対象外にする（このリポジトリの慣習）。
    """
    import re
    from pathlib import Path

    import services.thumbnail_analyzer as サムネ

    ソース = Path(サムネ.__file__).read_text(encoding="utf-8")
    実コード = "\n".join(
        行 for 行 in ソース.splitlines() if not 行.lstrip().startswith("#")
    )
    見つかった = re.findall(
        r"get\(\s*[\"'](?:face|text|contrast|composition)_score[\"']\s*,\s*[0-9]",
        実コード,
    )
    assert 見つかった == [], f"採点キーの既定値フォールバックが戻っている: {見つかった}"


# ============================================================
# 20周目（gate-verifier）
#
# CE-1 産出元の無い軸を 0 として測定値の顔で描く（Boardroom.jsx）
# CE-2 集計が1行も成立していないのに実測を名乗る（**19周目の修正が作った偽**）
# CE-3 画像を一度も開かずに総合点と所見を返す（thumbnail_analyzer）
# M9   `elapsed_hours` の既定値 24 の再発を契約が捕まえなかった（空振り）
# ============================================================


def test_20周目_CE1_産出元の無い軸をレーダーに描かない():
    """`Boardroom.jsx` のレーダー（R1.5-C4・20周目 CE-1）。

    `brand_rank` は**リポジトリ全体でこのファイルにしか存在しない**
    （他のヒットは自身のビルド成果物のみ）。産出元が無いので
    `?? 0` は**恒久的に 0** で、それが domain=[0,100] のレーダー
    「クリエイター能力分布」の3軸目として描かれていた。
    隣の「ビジネス力」には作り物の警告帯が付くのに、
    **一度も計算されていないブランド力にだけ印が無かった。**

    17周目にこのレーダーの `|| 10/20/50` を直したとき、
    **3軸のうち2軸だけを直していた。**
    """
    import re
    from pathlib import Path as _Path

    ルート = _Path(__file__).resolve().parent.parent.parent.parent

    def 描画部を読む(相対):
        js = (ルート / 相対).read_text(encoding="utf-8")
        s = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        return "\n".join(行 for 行 in s.splitlines()
                         if not 行.strip().startswith("//"))

    描画部 = 描画部を読む("frontend/src/components/Boardroom.jsx")

    # **値が無い軸を 0 や定数で埋めない**
    assert "?? 0, fullMark: 100" not in 描画部, \
        "測っていない軸を 0 としてレーダーに描いている"
    assert "|| 10" not in 描画部 and "|| 20" not in 描画部 and "|| 50" not in 描画部, \
        "17周目に直した定数フォールバックが戻っている"

    # **描くのは実測できた軸だけ**
    assert "軸の候補" in 描画部, "軸ごとに実測できたかを判定していない"
    assert "x.value !== null" in 描画部, "未計測の軸をレーダーから外していない"

    # **外すだけで隠さない**（利用者に未計測だと分かること）。
    # **文言の存在だけを見ない** — 20周目に自分で当てた変異 Q2 が
    # `{未計測の軸.length > 0 && (` を `{false && (` にしても緑のまま通った。
    # 条件式そのものが生きていることを見る
    assert "{未計測の軸.length > 0 && (" in 描画部, \
        "未計測の軸を出す条件が切られている（文言だけ残っても画面には出ない）"
    assert "まだ計測していません" in 描画部, \
        "軸を外しただけで、未計測であることが画面に出ていない"


def test_20周目_CE2_集計できていないのに実測を名乗らない():
    """`youtube_analytics_client.get_channel_performance()`（R1.5-C4・20周目 CE-2）。

    **19周目の修正が新しく作った偽。** `_aggregate_channel_performance()` は
    `response` が dict でない／`rows` が空／`len(r) >= 7` を満たす行が1つも無い、
    のいずれでも**何も代入せずに帰る**のに、呼び出し元が直後に
    `mark_measured()` を**無条件で**呼んでいた。

    その結果、**API が空の応答を返しただけで**
    `avg_ctr: 0.0 / total_views: 0` が `is_real: True` /
    `data_source: "analytics_api"` / `last_sync: 現在時刻` を得ていた。
    さらにその 0 が `_save_cache()` でキャッシュに焼き付いていた。
    """
    import asyncio
    import unittest.mock as _m

    from services.youtube_analytics_client import (ChannelPerformance,
                                                   YouTubeAnalyticsClient)

    def 走らせる(応答):
        c = YouTubeAnalyticsClient()
        # API 経路に入れる（`_available` が False だとキャッシュ経路に落ちる）
        c._available = True
        c._cache = {}          # 実ファイルのキャッシュを持ち込まない
        c._save_cache = _m.MagicMock()  # 実ファイルを汚さない
        with _m.patch.object(c, "_fetch_channel_analytics_report",
                             new=_m.AsyncMock(return_value=応答)):
            return asyncio.run(c.get_channel_performance(28)), c

    # ── 集計できる行が1つも無い応答（本番で普通に起きる） ──
    for 名, 応答 in (("rows なし", {"rows": []}),
                   ("列が足りない", {"rows": [[1, 2, 3]]}),
                   ("dict でない", None),
                   ("エラー本文", {"error": {"code": 403}})):
        perf, c = 走らせる(応答)
        assert perf.is_real is False, f"{名}: 集計できていないのに実測を名乗った"
        assert perf.data_source != "analytics_api", \
            f"{名}: 集計できていないのに analytics_api を名乗った"
        assert perf.last_sync is None, f"{名}: 未計測なのに同期時刻が付いた"
        assert perf.total_views is None, f"{名}: 未計測の再生数を 0 で埋めた"
        assert perf.avg_ctr is None, f"{名}: 未計測の CTR を 0.0 で埋めた"
        assert c._save_cache.call_count == 0, f"{名}: 作り物をキャッシュに焼き付けた"

    # ── 集計できる行がある（門が広すぎないこと） ──
    行 = [["2026-09-01", 100, 10, 0.05, 30.0, 50.0, 3]]
    perf, c = 走らせる({"rows": 行})
    assert perf.is_real is True, "実測できたのに未計測に倒した（門が常に閉じる）"
    assert perf.data_source == "analytics_api"
    assert perf.total_views == 100
    assert perf.last_sync is not None
    assert c._save_cache.call_count == 1

    # 集計関数そのものが「集計できたか」を返すこと
    c2 = YouTubeAnalyticsClient()
    assert c2._aggregate_channel_performance({"rows": []}, ChannelPerformance()) is False
    assert c2._aggregate_channel_performance({"rows": 行}, ChannelPerformance()) is True


def test_20周目_CE3_画像を見ずに総合点を出さない(tmp_path):
    """`thumbnail_analyzer.analyze_image()` のフォールバック（R1.5-C4・20周目 CE-3）。

    画像が無い / クライアント未設定 / JSONDecodeError / 汎用 except の4経路が
    すべて `self.analyze({"concept": path.stem})` に落ちていた。
    `analyze()` は `text_overlay` も `style` も無い辞書を採点するので、
    **ファイル名の長さを「テキスト可読性」として採点**し、
    「テキスト12文字 — モバイルでギリギリ読める」という**画像を見ていない所見**と
    総合点 57.5 / `verdict: "❌ 要修正"` を 200 で返していた。印は1つも無かった。

    **部分失敗（1軸だけ読めない）では総合点を出さないのに、
    4軸すべてを一度も見ていないこの経路だけが点を出す**逆転が起きていた。
    """
    import sys as _sys
    import types as _types
    import unittest.mock as _m

    from services.thumbnail_analyzer import thumbnail_analyzer

    def 未計測であること(結果, 名):
        assert 結果["overall_score"] is None, f"{名}: 画像を見ずに総合点を出した"
        assert 結果["verdict"] is None, f"{名}: 画像を見ずに判定を出した"
        assert 結果["predicted_ctr_impact"] is None, f"{名}: 画像を見ずに CTR 予測を出した"
        assert 結果["analysis_mode"] == "image_unanalyzed", \
            f"{名}: 解析していないのに {結果['analysis_mode']} を名乗った"
        assert 結果["is_real"] is False and 結果["data_source"] == "unavailable"
        assert len(結果["checks"]) == 4
        for c in 結果["checks"]:
            assert c["score"] is None, f"{名}: 見ていない軸に点が付いた"
            assert "文字" not in (c["detail"] or ""), \
                f"{名}: ファイル名の長さを所見にしている（{c['detail']}）"

    # 1) 画像が存在しない
    未計測であること(thumbnail_analyzer.analyze_image(str(tmp_path / "無い.png")), "画像なし")

    # 2) クライアント未設定
    画像 = tmp_path / "サムネ_テスト.png"
    画像.write_bytes(b"x" * 32)
    偽 = _types.ModuleType("gemini_client_factory")
    偽.get_gemini_client = lambda: None
    with _m.patch.dict(_sys.modules, {"gemini_client_factory": 偽}):
        未計測であること(thumbnail_analyzer.analyze_image(str(画像)), "クライアント未設定")

    # 3) Vision の応答が JSON として壊れている
    偽2 = _types.ModuleType("gemini_client_factory")
    client = _m.MagicMock()
    応答 = _m.MagicMock()
    応答.text = "{壊れた"
    client.models.generate_content.return_value = 応答
    偽2.get_gemini_client = lambda: client
    with _m.patch.dict(_sys.modules, {"gemini_client_factory": 偽2}):
        未計測であること(thumbnail_analyzer.analyze_image(str(画像)), "応答が壊れている")

    # 4) 正常系（4軸すべて読める）は今までどおり点を出す（門が広すぎないこと）
    偽3 = _types.ModuleType("gemini_client_factory")
    client3 = _m.MagicMock()
    応答3 = _m.MagicMock()
    応答3.text = ('{"face_score": 85, "text_score": 75, '
                 '"contrast_score": 90, "composition_score": 80}')
    client3.models.generate_content.return_value = 応答3
    偽3.get_gemini_client = lambda: client3
    with _m.patch.dict(_sys.modules, {"gemini_client_factory": 偽3}):
        正常 = thumbnail_analyzer.analyze_image(str(画像))
    assert 正常["analysis_mode"] == "gemini_vision", "正常系まで止めている"
    assert 正常["overall_score"] == 82.5
    assert 正常["is_real"] is True


def test_20周目_M9_経過時間の既定値24が戻らない():
    """19周目の変異 M9 が生き残った穴を塞ぐ（R1.5-C4・20周目）。

    gate-verifier 20周目が `elapsed_hours ... else None` を `else 24` に
    変異させたところ、契約69件が**全部緑のまま**だった。
    C4 の条件文が名指しした `.get("elapsed_hours", 24)` の**再発を
    契約が捕まえられない**という空振りなので塞ぐ。
    """
    import asyncio

    from services.prediction_validator import PredictionValidator

    class 台帳:
        def __init__(self):
            self.record = {"wagamama_id": "W",
                           "lanes": {"experience": {"predicted_ctr": 5.0}}}
            self.saved = 0

        def get_record(self, i):
            return self.record

        def _save(self):
            self.saved += 1

    v = PredictionValidator()

    # 経過時間が届いていない → **24 で埋めない**
    m = 台帳()
    r = asyncio.run(v.validate_prediction(
        "W", {"metrics": {"click_through_rate": 5.2}}, wagamama_manager=m))
    assert r["actual"]["elapsed_hours"] is None, "経過時間を既定値 24 で埋めた"
    assert r["actual"]["elapsed_hours"] != 24
    # **台帳側にも 24 が焼き付かないこと**
    保存 = m.record.get("lanes", {}).get("feedback", {}).get("validation_report")
    if 保存 is not None:
        assert 保存["actual"]["elapsed_hours"] is None

    # **実測 CTR が無い側でも 24 で埋めない**（ここが 20周目の変異 M9 / Q8 の枝）。
    # `計測できている` は CTR だけで決まるので、CTR がある限り三項の else 側に
    # 一度も入らない。**CTR が無いケースを通さないと既定値 24 の再発を捕まえられない。**
    m3 = 台帳()
    r3 = asyncio.run(v.validate_prediction(
        "W", {"elapsed_hours": 30}, wagamama_manager=m3))
    assert r3["actual"]["elapsed_hours"] is None, \
        "実測 CTR が無いのに経過時間を既定値で埋めた"
    assert r3["actual"]["elapsed_hours"] != 24
    assert r3["status"] == "skipped"

    m4 = 台帳()
    r4 = asyncio.run(v.validate_prediction("W", {}, wagamama_manager=m4))
    assert r4["actual"]["elapsed_hours"] is None
    assert r4["actual"]["elapsed_hours"] != 24

    # 届いていれば通す（門が広すぎないこと）
    m2 = 台帳()
    r2 = asyncio.run(v.validate_prediction(
        "W", {"metrics": {"click_through_rate": 5.2}, "elapsed_hours": 72},
        wagamama_manager=m2))
    assert r2["actual"]["elapsed_hours"] == 72
