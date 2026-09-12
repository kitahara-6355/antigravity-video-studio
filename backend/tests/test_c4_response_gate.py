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
    違反, _ = 門.audit([], [("*.quality.json", {"score": 89})], 空台帳)
    assert any("サイドカー" in v for v in 違反), 違反


def test_印のあるサイドカーは通る(門):
    台帳 = {"out_of_population": [], "measured_claims": [],
            "observed": [{"path": "*.quality.json", "keys": ["score"]}]}
    違反, _ = 門.audit(
        [], [("*.quality.json", {"score": 89, "scored": True,
                                 "data_source": "measured"})], 台帳)
    assert 違反 == []


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
            assert e.get("path", "").startswith("/api/"), e
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
