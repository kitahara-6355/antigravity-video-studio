"""R1.5-C4 の台帳（`backend/c4_inventory.py`）の契約。

**この台帳がゲートとして意味を持つ条件は2つだけ。**

1. **網が本当に拾うこと。** 拾えない形があれば、その形の偽 success は
   台帳に載らないまま緑になる。だから危険形6種を1つずつ試す
2. **食い違いを本当に落とすこと。** 漏れ・未解決・危険形の変化・印の消失で
   `audit()` が違反を返すこと

`_risk_kinds` の検査は「網の穴」を直接突くので、**ここが空振りすると
台帳全体が空振りになる**。値の等値ではなく「その形を入れたら検出が増える」で書く。
"""
from __future__ import annotations

import ast

import pytest

from backend import c4_inventory


def _kinds(src: str) -> list[str]:
    """関数1つのソースから危険形の内訳を出す。"""
    fn = ast.parse(src).body[0]
    return c4_inventory._risk_kinds(fn)


# ─────────────────── 網が拾うか（危険形6種） ───────────────────

def test_except_が値を返す形を拾う():
    """19・20周目の主犯。例外を握って定数を返すと採点が消える。"""
    src = (
        "def f():\n"
        "    try:\n"
        "        return measure()\n"
        "    except Exception:\n"
        "        return {'quality_score': 50}\n"
    )
    assert "except_returns" in _kinds(src)


def test_except_が値を返さない形は拾わない():
    """**握り潰して再送出するのは偽 success ではない。** 偽陽性を作らない。"""
    src = (
        "def f():\n"
        "    try:\n"
        "        return measure()\n"
        "    except Exception:\n"
        "        raise\n"
    )
    assert "except_returns" not in _kinds(src)


def test_カテゴリ鍵への数値直書きを拾う():
    """条件文が名指しする `watch_time_hours: 15200` がこの形。"""
    src = "def f():\n    return {'watch_time_hours': 15200}\n"
    assert "const_dict:watch_time_hours" in _kinds(src)


def test_カテゴリ外の鍵への数値直書きは拾わない():
    src = "def f():\n    return {'timeout_sec': 30}\n"
    assert not [k for k in _kinds(src) if k.startswith("const_dict")]


def test_真偽値は数値に数えない():
    """`True` は `isinstance(x, int)` を通るので、明示的に外していないと誤検出する。"""
    src = "def f():\n    return {'is_acceptable': True}\n"
    assert not [k for k in _kinds(src) if k.startswith("const_dict")]


def test_get_の既定値を拾う():
    src = "def f(d):\n    return d.get('quality_score', 50)\n"
    assert "default:quality_score" in _kinds(src)


def test_get_の既定値なしは拾わない():
    """既定値が無ければ `None` になる＝黙って数字を名乗らない。"""
    src = "def f(d):\n    return d.get('quality_score')\n"
    assert not [k for k in _kinds(src) if k.startswith("default:")]


def test_getattr_の既定値を拾う():
    src = "def f(o):\n    return getattr(o, 'allow_mock', True)\n"
    assert "getattr_default" in _kinds(src)


def test_or_の既定値を拾う():
    src = "def f(x):\n    return x.retention or 0.5\n"
    assert "or_default" in _kinds(src)


def test_数値リテラルの直返しを拾う():
    """条件文の「常に 0.0 になる quality_score」がこの形。"""
    src = "def f():\n    return 0.0\n"
    assert "const_return" in _kinds(src)


def test_負の数値も直返しとして拾う():
    """単項マイナスを見落とすと `-1` の番兵が素通りする。"""
    src = "def f():\n    return -1\n"
    assert "const_return" in _kinds(src)


def test_危険形が無い関数は空になる():
    src = "def f(d):\n    return compute(d['quality_score'])\n"
    assert _kinds(src) == []


def test_危険形は行番号を含まない():
    """**行番号を入れると無関係な編集で台帳が毎回ずれる。**

    **関数の開始行そのものをずらす。** 本文だけ変えても `fn.lineno` は動かないので、
    それでは行番号の混入を捕まえられない（この検査は最初そう書いてしまい、
    `sorted(出た + [str(fn.lineno)])` の変異が生き残った — 空振り10件目）。
    """
    a = _kinds("def f():\n    return 0.0\n")
    b = _kinds("# 前置き\n# 前置き\n\ndef f():\n    x = 1\n    return 0.0\n")
    assert ast.parse("# 前置き\n# 前置き\n\ndef f():\n    pass\n").body[0].lineno != 1, \
        "前置きで開始行がずれていない＝この検査は行番号混入を捕まえられない"
    assert a == b


# ─────────────────── scan（実態の抽出） ───────────────────

def test_scan_は本番の候補を返す():
    実態 = c4_inventory.scan()
    assert len(実態) > 100, "4カテゴリの候補が極端に少ない＝網が壊れている"
    ids = {c["id"] for c in 実態}
    # 条件文が名指しする経路は必ず候補に入る
    assert any("youtube_uploader" in i for i in ids), "投稿の経路が候補から漏れている"
    assert any("thumbnail_analyzer" in i for i in ids), "品質スコアの経路が候補から漏れている"


def test_scan_の_id_は一意():
    """**台帳の1行が2つの実体を指すと、片方の退行を見逃す。**

    実際に `_deprecated/pipeline_coordinator.py::execute` が衝突していた
    （別クラスの同名メソッド）。
    """
    ids = [c["id"] for c in c4_inventory.scan()]
    重複 = {i for i in ids if ids.count(i) > 1}
    assert not 重複, f"id が重複しています: {sorted(重複)[:10]}"


def test_同名メソッドが別クラスなら別の_id():
    src = (
        "class A:\n"
        "    def run(self):\n"
        "        return {'quality_score': 50}\n"
        "class B:\n"
        "    def run(self):\n"
        "        return {'quality_score': 50}\n"
    )
    名 = [q for _, q in c4_inventory._walk_functions(ast.parse(src))]
    assert 名 == ["A.run", "B.run"], 名


def test_入れ子関数も辿る():
    """`ast.walk` をやめた副作用で入れ子を落としていないか。"""
    src = (
        "def outer():\n"
        "    def inner():\n"
        "        return {'retention': 0.5}\n"
        "    return inner\n"
    )
    名 = [q for _, q in c4_inventory._walk_functions(ast.parse(src))]
    assert "outer" in 名
    assert any("inner" in n for n in 名), 名


def test_scan_はテストとアーカイブを含まない():
    for c in c4_inventory.scan():
        assert "/tests/" not in c["file"], c["file"]
        assert not c["file"].startswith("archives/"), c["file"]
        assert "__pycache__" not in c["file"], c["file"]


# ─────────────────── audit（食い違いを落とすか） ───────────────────

def _実態(fingerprint=(), has_mark=False):
    return [{
        "id": "backend/x.py::f", "file": "backend/x.py", "symbol": "f",
        "line": 1, "categories": ["品質スコア"],
        "fingerprint": list(fingerprint), "has_mark": has_mark,
    }]


def _台帳(status="marked", fingerprint=(), reason="出所の印を付けた"):
    return [{
        "id": "backend/x.py::f", "file": "backend/x.py", "symbol": "f",
        "category": "品質スコア", "status": status, "reason": reason,
        "fingerprint": list(fingerprint),
    }]


def test_台帳に無い候補は違反になる():
    """**掃引の完全性そのもの。** ここが落ちないなら台帳はゲートにならない。"""
    違反, _ = c4_inventory.audit([], _実態())
    assert any("台帳に無い候補" in m for m in 違反)


def test_台帳と実態が揃っていれば違反ゼロ():
    違反, _ = c4_inventory.audit(_台帳(fingerprint=["const_return"]),
                                 _実態(fingerprint=["const_return"], has_mark=True))
    assert 違反 == []


def test_危険形が増えたら再確認で落ちる():
    """**自分の修正が新しい既定値を持ち込んだら、その周のうちに赤くする。**

    20周目の最大の発見（掃引の完了宣言は修正コミットごとに無効化される）への対処。
    """
    違反, _ = c4_inventory.audit(
        _台帳(fingerprint=["const_return"]),
        _実態(fingerprint=["const_return", "default:quality_score"], has_mark=True),
    )
    assert any("危険形が変わった" in m for m in 違反)
    assert any("default:quality_score" in m for m in 違反)


def test_危険形が減っても再確認で落ちる():
    """減るのは前進だが、**台帳の記述が古くなる**ので黙って通さない。"""
    違反, _ = c4_inventory.audit(
        _台帳(fingerprint=["const_return", "or_default"]),
        _実態(fingerprint=["const_return"], has_mark=True),
    )
    assert any("危険形が変わった" in m for m in 違反)


def test_印が消えたら落ちる():
    違反, _ = c4_inventory.audit(_台帳(fingerprint=["const_return"]),
                                 _実態(fingerprint=["const_return"], has_mark=False))
    assert any("印" in m and "消えて" in m for m in 違反)


def test_対象外は印が無くても落ちない():
    """`out_of_scope` は印を付けない。**理由が台帳にあることが条件。**"""
    違反, _ = c4_inventory.audit(
        _台帳(status="out_of_scope", fingerprint=["const_return"],
              reason="本番から到達しない開発用ツール"),
        _実態(fingerprint=["const_return"], has_mark=False),
    )
    assert 違反 == []


def test_honest_は印が無くても落ちない():
    """**実測している経路に印を強要しない。**

    `marked` にしてしまうと「印が消えた」で落ちるが、実際に測って計算している
    関数は `is_real` を持つ必要が無い。理由は要る（判断だから）。
    """
    違反, _ = c4_inventory.audit(
        _台帳(status="honest", fingerprint=["const_return"],
              reason="実測値から計算しており、測れない経路では例外を上げる"),
        _実態(fingerprint=["const_return"], has_mark=False),
    )
    assert 違反 == []


def test_honest_も理由が無ければ落ちる():
    不備 = c4_inventory.check_entries([{
        "id": "a::b", "file": "a", "symbol": "b", "category": "品質スコア",
        "status": "honest", "reason": "実測", "fingerprint": [],
    }])
    assert any("理由を書く" in m for m in 不備)


def test_honest_でも危険形が増えたら落ちる():
    """**`honest` は免罪符ではない。** 新しい既定値が入ったら再確認させる。"""
    違反, _ = c4_inventory.audit(
        _台帳(status="honest", fingerprint=[], reason="実測値から計算しており印は要らない"),
        _実態(fingerprint=["default:quality_score"], has_mark=False),
    )
    assert any("危険形が変わった" in m for m in 違反)


def test_未解決は落ちる():
    違反, _ = c4_inventory.audit(_台帳(status="unresolved", fingerprint=[], reason="まだ直していない"),
                                 _実態())
    assert any("未解決の偽 success" in m for m in 違反)


def test_ソースから消えた_site_は違反ではなく情報():
    """消えたのは前進なので止めない。**掃除を促すだけ。**"""
    違反, 情報 = c4_inventory.audit(_台帳(fingerprint=[]), [])
    assert 違反 == []
    assert any("ソースに無い" in m for m in 情報)


# ─────────────────── check_entries（記載不備） ───────────────────

def test_理由の無い対象外は落ちる():
    """**「あとで書く」を許さない。** 理由の無い対象外は後から読めない。"""
    不備 = c4_inventory.check_entries([{
        "id": "a::b", "file": "a", "symbol": "b", "category": "品質スコア",
        "status": "out_of_scope", "reason": "対象外", "fingerprint": [],
    }])
    assert any("理由を書く" in m for m in 不備)


def test_不正な_status_は落ちる():
    不備 = c4_inventory.check_entries([{
        "id": "a::b", "file": "a", "symbol": "b", "category": "品質スコア",
        "status": "たぶん大丈夫", "reason": "十分に長い理由を書いた", "fingerprint": [],
    }])
    assert any("status は" in m for m in 不備)


def test_id_の重複は落ちる():
    e = {"id": "a::b", "file": "a", "symbol": "b", "category": "品質スコア",
         "status": "marked", "reason": "出所の印を付けた", "fingerprint": []}
    assert any("重複" in m for m in c4_inventory.check_entries([e, dict(e)]))


def test_カテゴリ外は落ちる():
    """**範囲を勝手に広げない。** 4カテゴリ以外を `marked` で載せられない。"""
    不備 = c4_inventory.check_entries([{
        "id": "a::b", "file": "a", "symbol": "b", "category": "ブランド力",
        "status": "marked", "reason": "出所の印を付けた", "fingerprint": [],
    }])
    assert any("category は" in m for m in 不備)


def test_fingerprint_が空リストなのは不備ではない():
    """危険形が無い site は正常。**空リストを「欠け」と数えない。**"""
    不備 = c4_inventory.check_entries([{
        "id": "a::b", "file": "a", "symbol": "b", "category": "品質スコア",
        "status": "marked", "reason": "出所の印を付けた", "fingerprint": [],
    }])
    assert 不備 == []


# ─────────────────── 台帳そのもの ───────────────────

def test_台帳が読めて記載不備が無い():
    """**正典と同じ扱い。** 台帳が壊れていたらゲートは意味を失う。"""
    inv = c4_inventory.load_inventory()
    assert c4_inventory.check_entries(inv.get("sites", [])) == []


def test_ゲートが実態と揃っている():
    """`--gate` が exit 0 になること＝ C-2 の判定そのもの。"""
    inv = c4_inventory.load_inventory()
    違反, _ = c4_inventory.audit(inv.get("sites", []))
    assert 違反 == [], "台帳と実態が食い違っています:\n  " + "\n  ".join(違反[:20])


@pytest.mark.parametrize("argv", [["--show"], ["--gate"]])
def test_cli_が動く(argv, capsys):
    assert c4_inventory.main(argv) == 0
    assert capsys.readouterr().out.strip()
