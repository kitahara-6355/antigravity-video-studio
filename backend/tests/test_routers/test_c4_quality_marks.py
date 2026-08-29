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
