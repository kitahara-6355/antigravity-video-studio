"""R1.5-C4b の門（`backend/c4_response_gate.py`）の契約。

## この門が意味を持つ条件

1. **印の無い数字を本当に見つけること。** 見つけられない形があれば、その形は
   名乗らずに外へ出られる
2. **印を「有る」と誤認しないこと。** `data_source: None` のような空の申告で
   通してしまうと、印を付ける意味が消える
3. **`measured` の名乗りを台帳で押さえること。** ここが効かないと
   `sample` → `measured` の反転が通る（gate-verifier 22周目 M2 の形）
4. **確かめられなかったことを「違反なし」にしないこと。** 呼び出しに失敗した
   ルートを黙って飛ばすと、落ちた経路ほど静かに通る

`audit()` は副作用が無い純関数なので、アプリを起こさずに直接叩ける。
アプリを実際にマウントする側は `--gate` の実行そのもので確かめる（CI のステップ）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_GATE = Path(__file__).resolve().parents[2] / "backend" / "c4_response_gate.py"


@pytest.fixture(scope="module")
def 門():
    spec = importlib.util.spec_from_file_location("c4_response_gate", _GATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["c4_response_gate"] = module
    spec.loader.exec_module(module)
    return module


# ─────────────────── 印の判定 ───────────────────

def test_空の申告は印に数えない(門):
    """`data_source: None` は何も言っていない。"""
    assert not 門.印を持つか({"data_source": None})
    assert not 門.印を持つか({"data_source": ""})
    assert not 門.印を持つか({"data_source": "   "})
    assert 門.印を持つか({"data_source": "sample"})


def test_偽の真偽印は印に数える(門):
    """`is_real: False` は「実物ではない」という**情報**なので印。"""
    assert 門.印を持つか({"is_real": False})
    assert 門.印を持つか({"checked": False})
    assert 門.印を持つか({"scored": False})
    assert not 門.印を持つか({"total": 5})


# ─────────────────── 名乗らない数字を見つけるか ───────────────────

def test_印の無い数字を見つける(門):
    出た = 門.名乗らない数字({"watch_time_hours": 15200})
    assert 出た and "watch_time_hours" in 出た[0]


def test_祖先の印で覆える(門):
    """`{**DATA_SOURCE, ...}` は応答の**先頭**に印を置く書き方。"""
    assert 門.名乗らない数字({"is_real": False, "stats": {"watch_time_hours": 15200}}) == []


def test_カテゴリ外の鍵は見ない(門):
    assert 門.名乗らない数字({"timeout_sec": 30}) == []


def test_空でない文字列も見る(門):
    """条件文の第1例 `video_id="placeholder_video_id"` は**文字列**。"""
    出た = 門.名乗らない数字({"video_id": "placeholder_video_id"})
    assert 出た and "placeholder_video_id" in 出た[0]
    # 空文字は「無い」を言っているので通す
    assert 門.名乗らない数字({"video_id": ""}) == []


def test_真偽値は数字として数えない(門):
    """`passed: True` は数字ではない。ここを数えると印だらけになる。"""
    assert 門.名乗らない数字({"passed": True}) == []
    assert 門.名乗らない数字({"passed": 4}) != []


def test_配列の中まで降りる(門):
    出た = 門.名乗らない数字({"history": [{"predicted_ctr": 4.0}]})
    assert 出た and "history[0].predicted_ctr" in 出た[0]


def test_measured_を名乗る箇所を入れ子でも見つける(門):
    assert 門.measured_を名乗る箇所({"data_source": "measured"}) == ["(応答の先頭)"]
    assert 門.measured_を名乗る箇所(
        {"a": {"b": {"data_source": "measured"}}}) == ["a.b"]
    assert 門.measured_を名乗る箇所({"data_source": "sample"}) == []


# ─────────────────── audit（落とすか） ───────────────────

空台帳 = {"out_of_population": [], "measured_claims": []}


def test_印の無い数字は違反になる(門):
    違反, _ = 門.audit([("/api/x", 200, {"watch_time_hours": 15200})], [], 空台帳)
    assert any("出所を名乗っていない" in v for v in 違反), 違反


def test_印があれば違反にならない(門):
    台帳 = {"out_of_population": [], "measured_claims": [],
            "observed": [{"path": "/api/x", "keys": ["watch_time_hours"]}]}
    違反, _ = 門.audit(
        [("/api/x", 200, {"is_real": False, "data_source": "sample",
                          "watch_time_hours": 15200})], [], 台帳)
    assert 違反 == []


def test_台帳に無い_measured_は違反になる(門):
    """**`sample` → `measured` の反転を落とす**（22周目 M2 の形）。"""
    本文 = {"data_source": "measured", "is_real": True, "watch_time_hours": 15200}
    違反, _ = 門.audit([("/api/x", 200, 本文)], [], 空台帳)
    assert any("台帳に無い `measured`" in v for v in 違反), 違反

    台帳 = {"out_of_population": [],
            "measured_claims": [{"path": "/api/x", "reason": "ローカルの台帳を実際に数えた"}],
            "observed": [{"path": "/api/x", "keys": ["watch_time_hours"]}]}
    違反, _ = 門.audit([("/api/x", 200, 本文)], [], 台帳)
    assert 違反 == []


def test_母集団の外に置いたルートは飛ばす(門):
    台帳 = {"out_of_population": [{"path": "/api/x", "reason": "開発プロセス指標なので対象外"}],
            "measured_claims": []}
    違反, 情報 = 門.audit([("/api/x", 200, {"watch_time_hours": 15200})], [], 台帳)
    assert 違反 == []
    assert any("母集団の外" in m for m in 情報)


def test_外すなら理由が要る(門):
    台帳 = {"out_of_population": [{"path": "/api/x", "reason": "不要"}], "measured_claims": []}
    違反, _ = 門.audit([], [], 台帳)
    assert any("理由を書く" in v for v in 違反), 違反


def test_measured_を名乗るなら何を測ったか要る(門):
    台帳 = {"out_of_population": [],
            "measured_claims": [{"path": "/api/x", "reason": "実測"}]}
    違反, _ = 門.audit([], [], 台帳)
    assert any("何を測ったか" in v for v in 違反), 違反


def test_呼び出せなかったルートは違反になる(門):
    """**沈黙は緑ではない。** 落ちた経路ほど静かに通ってはいけない。"""
    違反, _ = 門.audit([("/api/x", -1, {"_呼び出し例外": "Boom"})], [], 空台帳)
    assert any("呼び出せませんでした" in v for v in 違反), 違反


def test_印の無いサイドカーは違反になる(門):
    """**空振りだった**（2026-09-13 の指摘）。

    元は `空台帳` を渡していたので、鍵のラチェット側が
    「台帳に無いサイドカーが 4カテゴリの数字を書いています」を出し、
    `any("サイドカー" in v)` がそれで満たされていた。**印の検査を殺しても緑**だった。
    鍵は台帳に載せたうえで、**印の検査だけ**を見る。
    """
    台帳 = {"out_of_population": [], "measured_claims": [],
            "observed": [{"path": "*.quality.json", "keys": ["score"]}]}
    違反, _ = 門.audit([], [("*.quality.json", {"score": 89})], 台帳)
    assert any("出所を名乗っていないサイドカー" in v for v in 違反), 違反


def test_印のあるサイドカーは通る(門):
    """`measured` を名乗るサイドカーは、台帳の承認があってはじめて通る。"""
    台帳 = {"out_of_population": [],
            "measured_claims": [{"path": "*.quality.json",
                                 "reason": "ローカルの品質ゲートで実際に採点した"}],
            "observed": [{"path": "*.quality.json", "keys": ["score"]}]}
    違反, _ = 門.audit(
        [], [("*.quality.json", {"score": 89, "scored": True,
                                 "data_source": "measured"})], 台帳)
    assert 違反 == []


def test_サイドカーの未承認_measured_は違反になる(門):
    """**2026-09-13 まで、サイドカー側は `measured` の承認をまったく見ていなかった。**

    条文は母集団を「エンドポイント＋成果物ライタ」と定義しているのに、
    施行が半分だけだった。しかも `*.quality.json` は実際に未承認で名乗っていた。
    """
    台帳 = {"out_of_population": [], "measured_claims": [],
            "observed": [{"path": "*.quality.json", "keys": ["score"]}]}
    違反, _ = 門.audit(
        [], [("*.quality.json", {"score": 89, "scored": True,
                                 "data_source": "measured"})], 台帳)
    assert any("台帳に無い `measured`" in v and "サイドカー" in v for v in 違反), 違反


def test_書き出し口を呼べなかったら違反になる(門):
    """改名で門が静かに無力化するのを止める。"""
    違反, _ = 門.audit(
        [], [("*.quality.json", {"_呼び出し例外": "_write_quality_sidecar がありません"})],
        空台帳)
    assert any("呼べませんでした" in v for v in 違反), 違反


# ─────────────────── 危険鍵の定義を二重管理しない ───────────────────

def test_危険鍵は_c4_inventory_と同じ定義を使う(門):
    """**網の内部で定義が食い違うのが21周目の指摘だった。**

    2つの門が別々に危険鍵を定義すると、片方だけ広げたときに同じ失敗が起きる。
    """
    from backend import c4_inventory
    assert 門.RISK_KEY_RE.pattern == c4_inventory.RISK_KEY_RE.pattern


# ─────────────────── 台帳そのもの ───────────────────

def test_台帳は読めて必要な鍵がある(門):
    台帳 = 門.load_ledger()
    assert set(台帳) >= {"out_of_population", "measured_claims"}
    for 鍵 in ("out_of_population", "measured_claims"):
        for e in 台帳[鍵]:
            # サイドカーは `/api/` ではなく `*.quality.json` のような名前で載る
            assert e.get("path", "").startswith(("/api/", "*.")), e
            assert len(str(e.get("reason", ""))) >= 10, e


def test_台帳は_JSON_として妥当(門):
    json.loads(門.LEDGER_PATH.read_text(encoding="utf-8"))


# ─────────── 鍵のラチェット（包括的な印で覆う穴を塞ぐ） ───────────
#
# 包括的な印（応答の先頭の `{**DATA_SOURCE, ...}`）はその下の数字を全部覆うので、
# **印を持つ応答に新しい数字を足すと名乗らせないまま通る。**
# 実測で確かめた: `data_source: "measured"` を持つ応答に `predicted_ctr` を
# 足すと、印の検査だけでは緑のままだった。gate-verifier 23周目が静的側で
# 突いたのと同じ形（1段のローカル束縛・タプル・定数畳み込み）。
#
# **鍵は応答から観測する**ので、どう書いても隠れられない。


def test_出ている鍵は印の有無に関係なく拾う(門):
    assert 門.出ている鍵({"is_real": True, "ctr": 3.5}) == ["ctr"]
    assert 門.出ている鍵({"ctr": 3.5}) == ["ctr"]


def test_出ている鍵は入れ子と配列の中も見る(門):
    assert 門.出ている鍵({"a": {"b": [{"retention": 40.0}]}}) == ["retention"]


def test_出ている鍵は値が無いものを数えない(門):
    """`None` や空文字は「無い」を言っているので、鍵としては出ていない。"""
    assert 門.出ている鍵({"ctr": None, "video_id": ""}) == []
    assert 門.出ている鍵({"passed": True}) == [], "真偽値は数字ではない"


def test_鍵が増えたら落ちる(門):
    台帳 = {"out_of_population": [], "measured_claims": [],
            "observed": [{"path": "/api/x", "keys": ["ctr"]}]}
    本文 = {"is_real": True, "data_source": "sample", "ctr": 3.5, "predicted_ctr": 7.7}
    違反, _ = 門.audit([("/api/x", 200, 本文)], [], 台帳)
    assert any("新しい 4カテゴリの数字" in v and "predicted_ctr" in v for v in 違反), 違反


def test_鍵が同じなら通る(門):
    台帳 = {"out_of_population": [], "measured_claims": [],
            "observed": [{"path": "/api/x", "keys": ["ctr"]}]}
    違反, _ = 門.audit(
        [("/api/x", 200, {"is_real": True, "data_source": "sample", "ctr": 3.5})], [], 台帳)
    assert 違反 == []


def test_鍵が減っても落とさない(門):
    """減るのは前進（出す数字が減った）。**台帳の掃除を促すだけ。**"""
    台帳 = {"out_of_population": [], "measured_claims": [],
            "observed": [{"path": "/api/x", "keys": ["ctr", "retention"]}]}
    違反, 情報 = 門.audit(
        [("/api/x", 200, {"is_real": True, "data_source": "sample", "ctr": 3.5})], [], 台帳)
    assert 違反 == []
    assert any("出なくなった鍵" in m for m in 情報), 情報


def test_台帳に無いルートが数字を返したら落ちる(門):
    """**新しいエンドポイントが黙って数字を出すのを止める。**"""
    台帳 = {"out_of_population": [], "measured_claims": [], "observed": []}
    違反, _ = 門.audit(
        [("/api/新顔", 200, {"is_real": True, "data_source": "sample", "ctr": 3.5})], [], 台帳)
    assert any("台帳に無いルート" in v for v in 違反), 違反


def test_サイドカーにも鍵のラチェットが掛かる(門):
    台帳 = {"out_of_population": [], "measured_claims": [],
            "observed": [{"path": "*.quality.json", "keys": ["score"]}]}
    中身 = {"scored": True, "data_source": "measured", "score": 89, "predicted_ctr": 7.7}
    違反, _ = 門.audit([], [("*.quality.json", 中身)], 台帳)
    assert any("サイドカーに新しい 4カテゴリの数字" in v for v in 違反), 違反


def test_台帳の_observed_が実態と揃っている(門):
    """**台帳が腐っていないこと。** 母集団の外に置いたものは observed に入れない。"""
    台帳 = 門.load_ledger()
    外した = {e["path"] for e in 台帳["out_of_population"]}
    見た = set()
    for e in 台帳.get("observed", []):
        assert e["keys"], f"鍵が空なら observed に入れない: {e['path']}"
        assert e["path"] not in 外した, f"母集団の外なのに observed にある: {e['path']}"
        assert e["path"] not in 見た, f"observed に重複: {e['path']}"
        見た.add(e["path"])
    assert len(見た) >= 40, f"observed が {len(見た)} 件しかない。実測は43件だった"


# ─────────── 測っていないのに緑にしない（2026-09-13） ───────────
#
# CI でこの門は「✅ 0 ルートとサイドカー 2 件」を出して exit 0 を返していた
# （所要 約1秒・HTTP リクエスト 0本）。手元は 304 ルート。依存の版ずれで
# 母集団が空になったのに、**空を成功として報告した。**
# 契約に「沈黙は緑ではない」と書いておきながら、母集団そのものが 0 になる
# 経路を塞いでいなかった。ここが最優先の検査。


def test_母集団が下限を割ったら落ちる(門):
    台帳 = {"out_of_population": [], "measured_claims": [], "observed": [],
            "population_floor": 300}
    違反, _ = 門.audit([], [], 台帳)
    assert any("母集団が下限を割りました" in v for v in 違反), 違反


def test_母集団が0でも下限が0なら落ちない(門):
    """下限を置いていない台帳では従来どおり。**下限は台帳が決める。**"""
    違反, _ = 門.audit([], [], {"out_of_population": [], "measured_claims": []})
    assert not [v for v in 違反 if "下限" in v]


def test_下限を満たせば落ちない(門):
    台帳 = {"out_of_population": [], "measured_claims": [], "observed": [],
            "population_floor": 2}
    違反, _ = 門.audit([("/api/a", 404, None), ("/api/b", 404, None)], [], 台帳)
    assert not [v for v in 違反 if "下限" in v]


# ─────────── 外した先を隠さない ───────────

def test_宣言していない_method_を外したら落ちる(門):
    台帳 = {"out_of_population": [], "measured_claims": [],
            "side_effect_methods": ["POST"]}
    違反, _ = 門.audit([], [], 台帳, 内訳={"POST": 3, "DELETE": 1})
    assert any("宣言していない method" in v and "DELETE" in v for v in 違反), 違反


def test_盲点が増えたら落ちる(門):
    """**測れない範囲が知らないうちに広がるのを止める。**"""
    台帳 = {"out_of_population": [], "measured_claims": [],
            "side_effect_blind_spot": ["POST /api/a/score"]}
    違反, _ = 門.audit([], [], 台帳,
                       盲点=["POST /api/a/score", "POST /api/b/ctr"])
    assert any("盲点が増えました" in v and "/api/b/ctr" in v for v in 違反), 違反


def test_盲点が減っても落とさない(門):
    台帳 = {"out_of_population": [], "measured_claims": [],
            "side_effect_blind_spot": ["POST /api/a/score", "POST /api/b/ctr"]}
    違反, 情報 = 門.audit([], [], 台帳, 盲点=["POST /api/a/score"])
    assert not [v for v in 違反 if "盲点" in v]
    assert any("盲点が減りました" in m for m in 情報), 情報


# ─────────── 読めない応答を「数字が無い」と断定しない ───────────

def test_読めない応答が増えたら落ちる(門):
    """**本文を解析していないのだから「運んでいない」とは言えない。**

    ここには 500 が11件入っていたのに、門は「4カテゴリの数字を運んでいません」と
    言い切って情報に落としていた。
    """
    違反, _ = 門.audit([("/api/x", 500, None)], [], 空台帳)
    assert any("読めない応答が増えました" in v for v in 違反), 違反


def test_台帳に理由つきで載っていれば情報に落とす(門):
    台帳 = {"out_of_population": [], "measured_claims": [],
            "unreadable": [{"path": "/api/x", "status": 500,
                            "reason": "500。壊れている。別タスクで扱う"}]}
    違反, 情報 = 門.audit([("/api/x", 500, None)], [], 台帳)
    assert not [v for v in 違反 if "読めない応答" in v]
    assert any("/api/x (500)" in m for m in 情報), 情報


def test_読めない応答を理由なしに載せられない(門):
    """一覧に足すだけなら「壊れているものを追認する」ことになる。"""
    台帳 = {"out_of_population": [], "measured_claims": [],
            "unreadable": [{"path": "/api/x", "status": 500, "reason": "500"}]}
    違反, _ = 門.audit([], [], 台帳)
    assert any("読めない応答を台帳に載せるなら理由" in v for v in 違反), 違反


# ─────────── measured の表記ゆれ ───────────

def test_measured_は大小文字と空白で抜けられない(門):
    """`sample` → `measured` の反転を落とすのが目的なので、表記ゆれで抜けたら無意味。"""
    for 値 in ("measured", "Measured", "MEASURED", " measured ", "measured\n"):
        assert 門._実測を名乗っているか(値), 値
    for 値 in ("sample", "derived", "gemini", "", None, 3.5):
        assert not 門._実測を名乗っているか(値), 値


# ─────────── ルートの拾い方 ───────────

def test_母集団はパス引数に合成の値を入れる(門):
    class R:
        def __init__(s, p, m): s.path, s.methods = p, m
    app = SimpleNamespace(routes=[
        R("/api/a/{id}", {"GET"}), R("/api/b", {"GET"}),
        R("/api/c", {"POST"}), R("/other", {"GET"})])
    assert 門.母集団(app) == [f"/api/a/{門.探り値}", "/api/b"]


def test_除外の内訳は_GET_以外を数える(門):
    class R:
        def __init__(s, p, m): s.path, s.methods = p, m
    app = SimpleNamespace(routes=[
        R("/api/a", {"GET"}), R("/api/b", {"POST"}),
        R("/api/c", {"DELETE"}), R("/api/d", {"POST"})])
    assert 門.除外の内訳(app) == {"DELETE": 1, "POST": 2}


def test_ルート一覧は_Mount_の下も辿る(門):
    """**版が変わって拾えなくなったら母集団が 0 になる。** 入れ子も辿る。"""
    class R:
        def __init__(s, p, m): s.path, s.methods = p, m
    class M:
        def __init__(s, p, rs): s.path, s.routes = p, rs
    app = SimpleNamespace(routes=[M("/api", [R("/inner", {"GET"})]),
                                  R("/api/top", {"GET"})])
    assert ("GET", "/api/inner") in 門.ルート一覧(app)
    assert ("GET", "/api/top") in 門.ルート一覧(app)
