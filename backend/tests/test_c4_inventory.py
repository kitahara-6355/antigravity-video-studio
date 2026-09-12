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

NL = chr(10)


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


def test_真偽値の_True_は成功を名乗るので拾う():
    """**2026-09-12 に契約を反転した**（案A・gate-verifier 22周目）。

    ここは元々「`True` は `isinstance(x, int)` を通るので明示的に外す」という
    契約だった。数値リテラルだけを危険と見なす設計だったので筋は通っていたが、
    **`is_acceptable: True` は「品質チェックに通った」と名乗る値そのもの**で、
    22周目の M7b はこれを突いた（採点に失敗した経路を合格に戻しても緑だった）。

    述語を「入力に依存せず、かつ成功を名乗りうる値」に置き換えたので、
    `True` は拾い、`False`（＝通っていない）は拾わない。
    """
    src = "def f():\n    return {'is_acceptable': True}\n"
    assert "const_dict:is_acceptable" in _kinds(src)

    正直 = "def f():\n    return {'is_acceptable': False}\n"
    assert not [k for k in _kinds(正直) if k.startswith("const_dict")], \
        "False は「通っていない」を言っているので危険形ではない"


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


# ─────────────────── 21周目の指摘で塞いだ穴 ───────────────────
#
# gate-verifier 21周目が「**直したばかりの欠陥を戻してもゲートが素通りする**」ことを
# 実測で示した。網とラチェットの穴を塞いだので、それぞれに検査を置く。


def test_21周目_キーワード引数の数値を拾う():
    """`quality_score=0.85`（gate-verifier 21周目の指摘）。

    `_risk_kinds` は dict リテラル・`.get` 既定・`or` 既定・`getattr`・定数 return・
    `except` return しか見ておらず、**キーワード引数の数値リテラルを見ていなかった**。
    そのため `generation_engine` で直した `quality_score=None` を `0.85` に戻しても
    fingerprint が動かず、ゲートが緑のまま通っていた。
    """
    assert "const_kwarg:quality_score" in _kinds(
        "def f():" + NL + "    return R(request_id='x', quality_score=0.85)" + NL)
    # カテゴリ外の鍵は拾わない（過剰検出しない）
    assert not [k for k in _kinds("def f():" + NL + "    return R(timeout=30)" + NL)
                if k.startswith("const_kwarg")]


def test_21周目_属性への数値代入を拾う():
    """`result.quality_score = 0.85` / `score = 50.0`。永続化の直前に多い形。"""
    assert "const_assign:quality_score" in _kinds(
        "def f(r):" + NL + "    r.quality_score = 0.85" + NL)
    assert "const_assign:score" in _kinds("def f():" + NL + "    score = 50.0" + NL)
    assert not [k for k in _kinds("def f():" + NL + "    timeout = 30" + NL)
                if k.startswith("const_assign")]


def test_21周目_expected_ctr_も危険鍵に入っている():
    """`expected_ctr: 5.0` を戻しても fingerprint が動かなかった。

    `RISK_KEY_RE` は `^…$` の完全一致なので、`expected_ctr` / `ctr_score` が
    入っていないと `thumbnail_engine/generator.py` の修正を守れない。
    """
    assert "const_dict:expected_ctr" in _kinds(
        "def f():" + NL + "    return {'expected_ctr': 5.0}" + NL)
    assert "const_dict:ctr_score" in _kinds(
        "def f():" + NL + "    return {'ctr_score': 5.0}" + NL)


def test_21周目_印の検査をコメントで満たせない():
    """**印を全部消してコメントに `is_real` と書くだけで通っていた。**"""
    # **クォート付きで書く。** `MARK_RE` はクォートに挟まれた形しか見ないので、
    # 裸の `is_real` をコメントに置いても元から一致せず、
    # **コメント除去の有無を区別できない**（最初そう書いて変異が生き残った）
    コメント行 = '    # ' + chr(39) + 'is_real' + chr(39) + ' を消した'
    コメントだけ = "def f():" + NL + コメント行 + NL + "    return {'score': 5.0}" + NL
    assert not c4_inventory._印がある(コメントだけ), "コメントで印の検査を満たしている"
    本物 = "def f():" + NL + "    return {'score': None, 'is_real': False}" + NL
    assert c4_inventory._印がある(本物)


def test_21周目_辞書の先頭で展開する印を拾う():
    """`{**DATA_SOURCE, ...}` は文字列リテラルが本文に出てこない。

    これを見ないと `admin_channel_router` の `**DATA_SOURCE` を消しても
    「印は元から無い」と見なして素通りする（`watch_time_hours: 15200` が無印になる）。

    **接頭辞を必須にすると `**DATA_SOURCE` そのものが外れる**ので、
    接頭辞の無い名前も通ることを見る（最初その書き方で穴が残った）。
    """
    展開 = "def f():" + NL + "    return {**DATA_SOURCE, 'score': 1}" + NL
    修飾 = "def f():" + NL + "    return {**A.DATA_SOURCE, 'score': 1}" + NL
    無関係 = "def f():" + NL + "    return {**OTHER, 'score': 1}" + NL
    assert c4_inventory._印がある(展開)
    assert c4_inventory._印がある(修飾)
    assert not c4_inventory._印がある(無関係)


def test_21周目_属性代入で立てた印を拾う():
    """`report.scored = False` のように**属性で印を立てる**形。

    文字列の `scored` は `to_dict()` 側にしか無いことがあり、
    関数本文の字面だけでは「印なし」に見える
    （`quality_gate_agent.run_gate` が実際にそうだった）。
    """
    印あり = "def f(r):" + NL + "    r.scored = False" + NL + "    return r" + NL
    印なし = "def f(r):" + NL + "    r.total = 5" + NL + "    return r" + NL
    assert c4_inventory._印がある(印あり, ast.parse(印あり).body[0])
    assert not c4_inventory._印がある(印なし, ast.parse(印なし).body[0])


def test_21周目_裸の_score_も候補に入る():
    """**網の内部で定義が食い違っていた。**

    `RISK_KEY_RE` は `score` を危険鍵に数えているのに、カテゴリ語は
    `quality_score` 等に限られていたため、`{"score": 72}` を返す
    `admin_channel_router.get_quality_improvement` が候補にすらならなかった。
    """
    ids = {c["id"] for c in c4_inventory.scan()}
    assert "backend/routers/admin_channel_router.py::get_quality_improvement" in ids, \
        "裸の score を返す本番経路が候補から漏れている"


# ─────────────── 22周目の指摘で「列挙」から「定義」へ変えた分 ───────────────
#
# gate-verifier 22周目は、条件文の第1例（`video_id="placeholder_video_id"`）を
# 戻してもゲートが緑のままであることを実測で示した。原因は `_is_number` が
# **数値リテラルしか見ていなかった**こと。危険な形を列挙する設計なので、
# 列挙から漏れた書き方（文字列・真偽値・モジュール定数・定数への呼び出し）が素通りした。
#
# 列挙を続けるかぎり次の書き方が必ず残るので、述語を
# **「入力に依存せず、かつ成功を名乗りうる値」**という定義に置き換えた（案A）。


def _名乗る(式: str):
    木 = ast.parse("def f(a):" + NL + "    return {'score': " + 式 + "}" + NL)
    fn = 木.body[0]
    return c4_inventory._成功を名乗る値(
        fn.body[0].value.values[0], c4_inventory._束縛された名前(fn))


def test_文字列も真偽値も成功を名乗る():
    """`video_id="placeholder_video_id"` / `is_acceptable=True`（22周目の M1・M7b）。"""
    assert _名乗る("'placeholder_video_id'")
    assert _名乗る("True")
    assert _名乗る("0.85")


def test_0_は除外しない():
    """条件文が名指しする「常に 0.0 になる quality_score」がこれ。"""
    assert _名乗る("0")
    assert _名乗る("0.0")


def test_無い_分からない_は成功を名乗らない():
    """`False` / `None` / `""` は「測れなかった」を言っているだけ。

    ここを危険に数えると、**正しく付けた印そのものが危険形になり**、
    台帳が毎回ずれて誰も見なくなる。
    """
    assert not _名乗る("None")
    assert not _名乗る("False")
    assert not _名乗る("''")


def test_モジュール定数は成功を名乗る():
    """`_FALLBACK_SCORE` / `_DEFAULT_CTR`（22周目の M7・M8）。

    **マジックナンバーを定数に括り出すのはレビューが薦める形**なので、
    ここを見ないと「直した」はずの既定値が名前に化けて戻ってくる。
    """
    assert _名乗る("_FALLBACK_SCORE")
    assert _名乗る("DEFAULT_CTR")
    # 引数から来る値は入力に依存するので危険ではない
    assert not _名乗る("a")


def test_定数だけを包んだ呼び出しも成功を名乗る():
    assert _名乗る("float(62.5)")
    assert not _名乗る("len(a)")


def test_関数の中で代入された名前は入力側に数える():
    src = ("def f(a):" + NL + "    x = a * 2" + NL + "    return {'score': x}" + NL)
    fn = ast.parse(src).body[0]
    束縛 = c4_inventory._束縛された名前(fn)
    assert "x" in 束縛 and "a" in 束縛
    assert not c4_inventory._成功を名乗る値(fn.body[1].value.values[0], 束縛)


def test_印は値まで記録する():
    """**有無だけでは足りない**（22周目の M2: `is_real: False` を `True` に反転）。"""
    偽 = ast.parse("def f():" + NL + "    return {'is_real': False}" + NL).body[0]
    真 = ast.parse("def f():" + NL + "    return {'is_real': True}" + NL).body[0]
    assert c4_inventory._印の内訳(偽) == ["is_real=False"]
    assert c4_inventory._印の内訳(真) == ["is_real=True"]
    assert c4_inventory._印の内訳(偽) != c4_inventory._印の内訳(真), "反転が指紋に出ていない"


def test_展開した定数の中身まで記録する():
    """`{**DATA_SOURCE, ...}` の `DATA_SOURCE` は**関数の外**にある。

    名前だけ記録すると、定数の中身を `is_real: True` へ反転しても関数側は
    何も変わらず素通りする（22周目の M2。固定値のチャンネル統計20経路）。
    """
    src = ("DATA_SOURCE = {'data_source': 'sample', 'is_real': False}" + NL
           + "def f():" + NL + "    return {**DATA_SOURCE, 'score': 1}" + NL)
    木 = ast.parse(src)
    定数 = c4_inventory._モジュール定数の印(木)
    内訳 = c4_inventory._印の内訳(木.body[1], 定数)
    assert "spread:DATA_SOURCE" in 内訳
    assert "DATA_SOURCE.is_real=False" in 内訳, 内訳
    assert "DATA_SOURCE.data_source='sample'" in 内訳, 内訳


def test_展開元を反転すると内訳が変わる():
    def 内訳(値):
        src = ("DATA_SOURCE = {'is_real': " + 値 + "}" + NL
               + "def f():" + NL + "    return {**DATA_SOURCE, 'score': 1}" + NL)
        木 = ast.parse(src)
        return c4_inventory._印の内訳(木.body[1], c4_inventory._モジュール定数の印(木))
    assert 内訳("False") != 内訳("True"), "定数の反転が指紋に出ていない"


def test_印の名乗り方が変わったら再確認を要求する():
    台帳 = _台帳(fingerprint=["const_dict:score"])
    台帳[0]["marks"] = ["is_real=False"]
    実態 = _実態(fingerprint=["const_dict:score"], has_mark=True)
    実態[0]["marks"] = ["is_real=True"]
    違反, _ = c4_inventory.audit(台帳, 実態)
    assert any("印の名乗り方が変わった" in v for v in 違反), 違反


def test_危険形を持つのに生成文で対象外にできない():
    """22周目の指摘 C-3。対象外238件のうち76件が生成文1種類だった。"""
    台帳 = _台帳(status="out_of_scope", fingerprint=["const_dict:score"],
                reason="掃引済みファイルだが、この関数は4カテゴリの数字・判定を作らないと"
                       "判断された（同ファイルの所見 3 件のいずれもこの関数の範囲に無い）")
    不備 = c4_inventory.check_entries(台帳)
    assert any("生成文で対象外" in m for m in 不備), 不備


def test_危険形が無ければ生成文でも落とさない():
    """**言い回しを禁じているのではない。** 数字を作らない site では正しい理由。"""
    台帳 = _台帳(status="out_of_scope", fingerprint=[],
                reason="掃引済みファイルだが、この関数は4カテゴリの数字・判定を作らないと"
                       "判断された（同ファイルの所見 3 件のいずれもこの関数の範囲に無い）")
    assert not [m for m in c4_inventory.check_entries(台帳) if "生成文で対象外" in m]


def test_危険形を持つ対象外で同じ理由を使い回せない():
    """生成文を1種類禁じるだけでは、次の定型文で同じ穴が開く。"""
    台帳 = []
    for i in range(c4_inventory.SHARED_REASON_LIMIT + 1):
        台帳.append({
            "id": f"backend/x.py::f{i}", "file": "backend/x.py", "symbol": f"f{i}",
            "category": "品質スコア", "status": "out_of_scope",
            "reason": "この経路は見たが問題ないと判断した（十分な長さの定型文）",
            "fingerprint": ["const_dict:score"],
        })
    assert any("使い回して" in m for m in c4_inventory.check_entries(台帳))
    # 上限以下なら通る（凍結モジュールのように正当に共有できる根拠がある）
    assert not [m for m in c4_inventory.check_entries(台帳[:-1]) if "使い回して" in m]


# ─────── 1段の間接参照を透かす（gate-verifier 23周目・2026-09-13） ───────
#
# 23周目は「`watch = 15200` と一度置くだけでゲートは緑になる」ことを実測で示した。
# 述語は「関数の外から来る名前」を危険と見なしていたので、**関数の中で定数を代入した
# 名前は素通り**だった。実在の site（`admin_analytics_router.get_benchmark` が
# `industry_avg_ctr = 3.5` を返す）も指紋が空のままだった。


def test_一度だけ定数を代入した名前を透かす():
    src = ("def f():" + NL + "    watch = 15200" + NL
           + "    return {'watch_time_hours': watch}" + NL)
    assert "const_dict:watch_time_hours" in _kinds(src)


def test_タプル展開の定数も透かす():
    src = ("def f():" + NL + "    a, b = 3.5, 40.0" + NL
           + "    return {'ctr': a, 'retention': b}" + NL)
    assert set(_kinds(src)) == {"const_dict:ctr", "const_dict:retention"}


def test_定数畳み込みを透かす():
    assert "const_dict:watch_time_hours" in _kinds(
        "def f():" + NL + "    return {'watch_time_hours': 15000 + 200}" + NL)


def test_固定値の_f_string_を透かす():
    assert "const_dict:video_id" in _kinds(
        "def f():" + NL + "    return {'video_id': f'{1234}_id'}" + NL)


def test_引数から来た名前は透かさない():
    """**偽陽性を作らない。** 入力で変わる値は偽 success ではない。"""
    src = ("def f(x):" + NL + "    watch = x" + NL
           + "    return {'watch_time_hours': watch}" + NL)
    assert not [k for k in _kinds(src) if k.startswith("const_dict")]


def test_再代入された名前は透かさない():
    """一度でも入力から代入されうるなら、その値は呼び出しに依存する。"""
    src = ("def f(x):" + NL + "    watch = 15200" + NL + "    watch = x" + NL
           + "    return {'watch_time_hours': watch}" + NL)
    assert not [k for k in _kinds(src) if k.startswith("const_dict")]


def test_ループ変数になる名前は透かさない():
    """**定数を代入した名前が、後でループ変数にもなる形。**

    最初この検査は `for watch in xs:` だけを書いていたが、それでは
    `watch` に定数を代入する行が無いので**そもそも定数の候補に入らず、
    ループ変数を外す処理を殺しても緑のままだった**（空振り）。
    定数の代入とループ束縛が同じ名前に来る形にして、初めて効く。
    """
    src = ("def f(xs):" + NL
           + "    watch = 15200" + NL
           + "    for watch in xs:" + NL
           + "        return {'watch_time_hours': watch}" + NL)
    assert not [k for k in _kinds(src) if k.startswith("const_dict")],         "ループで上書きされる名前を定数として透かしている"


def test_入力を含む演算は透かさない():
    assert not [k for k in _kinds(
        "def f(x):" + NL + "    return {'watch_time_hours': x + 200}" + NL)
        if k.startswith("const_dict")]


def test_メソッド呼び出しの既定値を定数と取り違えない():
    """`d.get('score', 0)` は**引数だけ見ると定数2つ**だが、`d` は入力。

    呼び出し先を見ないと、既定値つきの `.get` を全部「入力に依存しない」と
    誤判定する（実測で 40 site 以上が偽陽性になった）。
    """
    src = "def f(d):" + NL + "    s = d.get('score', 0)" + NL + "    return R(score=s)" + NL
    assert not [k for k in _kinds(src) if k.startswith("const_")]
    assert "default:score" in _kinds(src), "`.get` の既定値そのものは今までどおり拾う"


def test_定数を包んだ呼び出しは透かす():
    assert "const_dict:ctr" in _kinds(
        "def f():" + NL + "    return {'ctr': float(62.5)}" + NL)
