"""R1.5-C4b の門（`backend/c4_response_gate.py`）の契約。

## この門が意味を持つ条件（2026-09-17・面と鍵のラチェット）

1. **面が全部そろっていること。** 増えた面・消えた面・出口（status と種類）が変わった面を
   黙って通さない
2. **面ごとの鍵の集合が台帳どおりであること。** 新しい鍵は査読するまで落ちる
   （包括的な印の下に数字を足す形 — 23周目の形 — を止める）
3. **鍵名がすべて分類されていること。** 4カテゴリの鍵（と、その下の値）には印が要る
4. **例外は面ごと・鍵ごと。** 25周目 D-1 は、鍵1つの理由でパス全体を素通しにしていた
5. **`measured` の名乗りを台帳で押さえること**（22周目 M2 の形）。承認は面ごと
6. **未採点の点数が印の無いところへ出ないこと**（25周目 M-4b: HTML の「92.0点（合格）」）
7. **門が状態を書き換えないこと・隔離から漏れないこと**（25周目 D-5）
8. **確かめられなかったことを「違反なし」にしないこと**

`audit()` は副作用の無い純関数なので、アプリを起こさずに直接叩ける。
アプリを実際に起こす側は `--gate` の実行そのもので確かめる（CI のステップ）。
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import shutil
import subprocess
import sys
import types
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


def 面(face, body=None, *, status=200, kind="json", route=None, condition="既定",
      lines=None, unscored=False):
    o = {"face": face, "route": route or face, "condition": condition,
         "status": status, "kind": kind, "unscored": unscored}
    if kind == "json":
        o["body"] = body
    else:
        o["lines"] = list(lines or [])
    return o


def 台帳(**kw):
    base = {"category_names": {}, "non_category_names_reviewed": {},
            "non_category_names": [], "exemptions": [], "measured_claims": []}
    base.update(kw)
    return base


def 判定(門, 観測, 台帳_, 面台帳=None, 付帯=None):
    """面台帳を省いたら、観測そのものを台帳にする（形の検査を素通しにして他を見る）。"""
    if 面台帳 is None:
        面台帳 = 門.面台帳を作る(観測)
    return 門.audit(観測, 台帳_, 面台帳, 付帯)


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
    assert 出た and "$.watch_time_hours" in 出た[0]


def test_祖先の印で覆える(門):
    """`{**DATA_SOURCE, ...}` は応答の**先頭**に印を置く書き方。"""
    assert 門.名乗らない数字({"is_real": False, "stats": {"watch_time_hours": 15200}}) == []


def test_カテゴリ外の鍵は見ない(門):
    assert 門.名乗らない数字({"timeout_sec": 30}) == []


def test_空でない文字列も見る(門):
    """条件文の第1例 `video_id="placeholder_video_id"` は**文字列**。"""
    出た = 門.名乗らない数字({"video_id": "placeholder_video_id"})
    assert 出た and "placeholder_video_id" in 出た[0]
    assert 門.名乗らない数字({"video_id": ""}) == []


def test_真偽値は数字として数えない(門):
    assert 門.名乗らない数字({"passed": True}) == []
    assert 門.名乗らない数字({"passed": 4}) != []


def test_配列の中の辞書まで降りる(門):
    出た = 門.名乗らない数字({"history": [{"predicted_ctr": 4.0}]})
    assert 出た and "$.history[].predicted_ctr" in 出た[0]


def test_配列に並んだ値も見る(門):
    """`views: [100, 200]` は鍵が1つで値が2つ。**値の側に鍵名が無い**。"""
    出た = 門.名乗らない数字({"views": [100, 200]})
    assert len(出た) == 2 and all("$.views[]" in x for x in 出た), 出た


def test_台帳で4カテゴリにした鍵名も見る(門):
    """25周目 D-4 — `total_views` は危険鍵の列挙の外にあった。"""
    assert 門.名乗らない数字({"total_views": 850000}) == []
    出た = 門.名乗らない数字({"total_views": 850000}, lambda n: n == "total_views")
    assert 出た and "total_views" in 出た[0]


def test_4カテゴリの鍵の下の値も見る(門):
    """`category_scores: {"core": 77.8}` の `core` は鍵名だけでは点数と分からない。"""
    def カテゴリか(n):
        return n == "category_scores"

    出た = 門.名乗らない数字({"category_scores": {"core": 77.8}}, カテゴリか)
    assert 出た and "$.category_scores.core" in 出た[0]
    assert 門.名乗らない数字({"category_scores": {"core": 77.8}, "scored": True}, カテゴリか) == []


def test_例外は鍵ごとで隣の鍵は見る(門):
    """**25周目 D-1。** 鍵1つの例外で、同じ面の別の数字まで素通しにしない。"""
    本文 = {"agent": {"passed": 106}, "quality_score": 98.5}
    出た = 門.名乗らない数字(本文, None, frozenset({"$.agent.passed"}))
    assert len(出た) == 1 and "$.quality_score" in 出た[0], 出た


def test_例外にした器は祖先として数えない(門):
    """器の鍵を「ここでは4カテゴリではない」とした以上、下の値を器のせいで落とさない。"""
    def カテゴリか(n):
        return n in ("quality", "score")

    本文 = {"quality": {"resolution": "1080p", "score": 3}}
    出た = 門.名乗らない数字(本文, カテゴリか, frozenset({"$.quality"}))
    assert len(出た) == 1 and "$.quality.score" in 出た[0], 出た


def test_measured_を名乗る箇所を入れ子でも見つける(門):
    assert 門.measured_を名乗る箇所({"data_source": "measured"}) == ["$"]
    assert 門.measured_を名乗る箇所({"a": {"b": {"data_source": "measured"}}}) == ["$.a.b"]
    assert 門.measured_を名乗る箇所({"data_source": "sample"}) == []


def test_measured_は大小文字と空白で抜けられない(門):
    for 値 in ("measured", "Measured", "MEASURED", " measured ", "measured\n"):
        assert 門._実測を名乗っているか(値), 値
    for 値 in ("sample", "derived", "gemini", "", None, 3.5):
        assert not 門._実測を名乗っているか(値), 値


# ─────────────────── 形（鍵の集合） ───────────────────

def test_形は道と種類をまるごと持つ(門):
    assert 門.形({"a": [{"b": 1}], "c": None}) == [
        "$.a:list", "$.a[].b:num", "$.a[]:dict", "$.c:null", "$:dict"]


def test_形は鍵の中の記号で道を割らない(門):
    """モデル ID（`gemini-3.1-pro`）の `.` を段の区切りと取り違えない。"""
    assert '$["gemini-3.1-pro"]:str' in 門.形({"gemini-3.1-pro": "x"})


def test_形は中身の差し替えを見分ける(門):
    """`stats: {...}` を `stats: 15200` にしても道は変わらない。種類で止める。"""
    assert set(門.形({"stats": 15200})) - set(門.形({"stats": {"n": 1}})) == {"$.stats:num"}


def test_鍵名は器の鍵も含めて全部拾う(門):
    assert 門.鍵名({"a": {"b": [{"c": 1}]}}) == {"a", "b", "c"}


# ─────────────────── 本文の読み方 ───────────────────

def _応答(content: bytes, ctype: str, headers: dict | None = None):
    h = {"content-type": ctype, **(headers or {})}
    return SimpleNamespace(
        headers=h, content=content, text=content.decode("utf-8"),
        json=lambda: json.loads(content.decode("utf-8")))


def test_JSON_は_status_によらず本文として読む(門):
    """**25周目 D-3。** 404 の本文に数字を載せても、以前の門は見ていなかった。"""
    r = 門.本文を読む(_応答(b'{"quality_score": 98.5}', "application/json"))
    assert r == {"kind": "json", "body": {"quality_score": 98.5}}


def test_JSON_の_null_は読めない扱いにしない(門):
    """以前は `null` 本文を「JSON として読めない」と記録していた（事実と違う）。"""
    assert 門.本文を読む(_応答(b"null", "application/json")) == {"kind": "json", "body": None}


def test_HTML_は見える文字の行にする(門):
    html = ("<html><head><style>td{color:red}</style></head><body>"
            "<p>総合スコア: <strong>未計測</strong></p><table><tr><td>①</td><td>文字起こし</td></tr>"
            "</table><p>生成日時: 2026-09-17T12:00:00.123 / x</p><script>var a=1</script></body></html>")
    r = 門.本文を読む(_応答(html.encode("utf-8"), "text/html; charset=utf-8"))
    assert r["kind"] == "text"
    assert r["lines"] == ["総合スコア: 未計測", "① 文字起こし", "生成日時: <日時> / x"], r["lines"]
    # 見えない所（属性・スクリプト）も比べられるよう、生の本文を日時だけ伏せて持つ
    assert r["raw"] == html.replace("2026-09-17T12:00:00.123", "<日時>")


def test_空の本文はリダイレクト先を行にする(門):
    r = 門.本文を読む(_応答(b"", "text/plain", {"location": "/?error=no_code"}))
    assert r == {"kind": "none", "lines": ["Location: /?error=no_code"]}


# ─────────────────── 点数に連れて動く所（26周目: 番兵の完全一致をやめた） ───────────────────

def test_違う所は値と形と配列の位置で見る(門):
    assert 門.違う所({"a": 1, "b": [1, 2]}, {"a": 2, "b": [1, 3]}) == [("a",), ("b", 1)]
    assert 門.違う所({"a": 1}, {"a": 1, "c": 5}) == [("c",)]
    assert 門.違う所({"b": [1]}, {"b": [1, 2]}) == [("b", 1)]
    assert 門.違う所({"s": {"x": 1}}, {"s": 15200}) == [("s",)]


def test_違う所は日時と数の型の違いを無視する(門):
    assert 門.違う所({"t": "at 2026-09-17T12:00:00.1"}, {"t": "at 2026-09-18T01:02:03"}) == []
    assert 門.違う所({"n": 0}, {"n": 0.0}) == []
    assert 門.違う所({"n": True}, {"n": 1}) == [("n",)], "真偽値は数と分ける"


def test_道を書くは形の道と同じ書き方(門):
    assert 門.道を書く(("stages", 5, "data", "gemini-3.1-pro")) == '$.stages[5].data["gemini-3.1-pro"]'


def test_印で覆われているかは祖先と自分を見る(門):
    本文 = {"result": {"quality_scored": False, "score": 1}, "free": {"x": 1},
            "stages": [{"scored": True, "detail": "92点"}]}
    assert 門.印で覆われているか(本文, ("result", "score"))
    assert 門.印で覆われているか(本文, ("stages", 0, "detail"))
    assert not 門.印で覆われているか(本文, ("free", "x"))
    assert 門.印で覆われているか({"new": {"is_real": False, "v": 1}}, ("new",)), "足された器が自分で名乗る"
    assert not 門.印で覆われているか(本文, ("gone", "x")), "無い道は覆われていない"


def test_点数に連れて動く_JSON_は印が無ければ漏れ(門):
    """**書式を変えても抜けられない**（26周目 M6: `:.1f` で番兵の完全一致をすり抜けた）。"""
    甲 = 面("f", {"video_path": "73.2", "result": {"quality_scored": False, "quality_score": 73.21}})
    乙 = 面("f", {"video_path": "0.0", "result": {"quality_scored": False, "quality_score": 0}})
    r = 門.点数に連れて動く所(甲, 乙, 甲)
    assert r["漏れ"] == ["$.video_path"] and r["覆われた"] == 1, r


def test_片方の変種でしか名乗っていなければ漏れ(門):
    """点数によって印が消える形（高い点のときだけ `is_real` を付ける等）を通さない。"""
    甲 = 面("f", {"is_real": False, "n": 1})
    乙 = 面("f", {"n": 2})
    assert "$.n" in 門.点数に連れて動く所(甲, 乙, 甲)["漏れ"]


def test_点数と関係なく揺れる所は除く(門):
    甲 = 面("f", {"uptime": 1.2, "n": 1})
    甲2 = 面("f", {"uptime": 3.4, "n": 1})
    乙 = 面("f", {"uptime": 5.6, "n": 2})
    assert 門.点数に連れて動く所(甲, 乙, 甲2)["漏れ"] == ["$.n"]
    assert 門.点数に連れて動く所(甲, 乙, None)["漏れ"] == ["$.n", "$.uptime"]


def test_揺れる文字列でも点数の動きは拾う(門):
    """**27周目 M08。** 時刻と点数が同じ文字列に入ると、葉ごと捨てて点数の動きまで見逃していた。

    揺れた**部分だけ**を伏せた型に、もう片方の点数の回が当てはまるかで見る。
    """
    甲 = 面("f", {"detail": "02:24:37 完了 品質0点"})
    乙 = 面("f", {"detail": "02:24:39 完了 品質73.21点"})
    甲2 = 面("f", {"detail": "02:24:41 完了 品質0点"})
    assert 門.点数に連れて動く所(甲, 乙, 甲2)["漏れ"] == ["$.detail"]


def test_揺れるだけの文字列は漏れにしない(門):
    """揺れた所だけを伏せた型に当てはまるなら、点数とは関係ない（空振りを作らない）。"""
    甲 = 面("f", {"detail": "02:24:37 完了"})
    乙 = 面("f", {"detail": "02:24:39 完了"})
    甲2 = 面("f", {"detail": "02:24:41 完了"})
    r = 門.点数に連れて動く所(甲, 乙, 甲2)
    assert r["漏れ"] == [] and r["覆われた"] == 0, r


def test_点数に連れて動く文字は行で拾う(門):
    甲 = 面("r", kind="text", lines=["総合スコア: 未計測", "x"])
    乙 = 面("r", kind="text", lines=["総合スコア: 73.2点", "x"])
    甲["raw"], 乙["raw"] = "<p>未計測</p>", "<p>73.2点</p>"
    r = 門.点数に連れて動く所(甲, 乙, dict(甲))
    assert r["文字"] == ["総合スコア: 73.2点", "総合スコア: 未計測"] and not r["見えない所"]


def test_見えない所の点数も拾う(門):
    """**26周目 M10**: `<meter value="73.21">` は見える文字が「未計測」のままだった。"""
    甲 = 面("r", kind="text", lines=["総合スコア: 未計測"])
    乙 = dict(甲)
    甲["raw"], 乙["raw"] = '<meter value="0"></meter>未計測', '<meter value="73.21"></meter>未計測'
    r = 門.点数に連れて動く所(甲, 乙, dict(甲))
    assert r["文字"] == [] and r["見えない所"] is True
    # **27周目 M09**: 生の本文が毎回揺れても（キャッシュ避けなど）、揺れた所だけを伏せて見る
    揺れた = dict(甲)
    甲["raw"] = '<meter value="0"></meter>未計測<link href="/favicon.ico?v=111">'
    乙["raw"] = '<meter value="73.21"></meter>未計測<link href="/favicon.ico?v=222">'
    揺れた["raw"] = '<meter value="0"></meter>未計測<link href="/favicon.ico?v=333">'
    assert 門.点数に連れて動く所(甲, 乙, 揺れた)["見えない所"] is True
    # 揺れているだけなら見えない所は動いていない
    乙だけ揺れ = dict(乙)
    乙だけ揺れ["raw"] = '<meter value="0"></meter>未計測<link href="/favicon.ico?v=444">'
    assert 門.点数に連れて動く所(甲, 乙だけ揺れ, 揺れた)["見えない所"] is False


def test_点数の変種は表示の閾値をまたぐ(門):
    """**27周目 M07。** 同じ帯の中で点数を動かすと、閾値から作った文字だけが動く形を見逃す。

    合格・不合格は品質ゲートの90点の同じ側に置いたまま、表示のランク（95 / 90 / 80）はまたぐ。
    """
    def 帯(点):
        return "S" if 点 >= 95 else "A" if 点 >= 90 else "B" if 点 >= 80 else "C"

    for 条件, (甲, 乙) in 門.点数の変種.items():
        assert 帯(甲) != 帯(乙), f"{条件} の {甲} と {乙} が同じ帯"
        if 条件 not in 門._未採点の条件:
            assert (甲 >= 90) == (乙 >= 90), f"{条件} の2点が品質ゲートの合否をまたいでいる"
    assert 門.点数の変種[門.合格][0] >= 90 and 門.点数の変種[門.不合格][0] < 90


def test_改善ループの条件ではやり直しも本番の配線で進める(門, monkeypatch):
    """**27周目 E1。** 品質ゲートが不合格なら、本番はこのあと改善ループの「やり直し」を知らせる。

    **結果の通知だけの状態とは別の面**として見るので、条件で分ける（同じ面に畳むと、
    やり直しが上書きしてしまい、結果の通知の印が消えても気づけない）。
    """
    from agents.pipeline_types import StageResult
    pc = importlib.import_module("agents.pipeline_coordinator")
    呼ばれた = []

    async def 結果を(worker, 工程):
        呼ばれた.append(("結果", 工程.success))

    async def やり直しを(worker, qi, ctx):
        呼ばれた.append(("やり直し", qi))

    monkeypatch.setattr(pc.pipeline_coordinator, "_notify_result", 結果を)
    monkeypatch.setattr(pc.pipeline_coordinator, "_notify_retry", やり直しを)
    ctx = SimpleNamespace(quality_scored=False, quality_score=0)
    工程 = StageResult("品質チェック", False, "スコア: 85点")
    門._工程を進める((SimpleNamespace(index=5), 工程, ctx, True))
    門._工程を進める((SimpleNamespace(index=5), 工程, ctx, False))
    assert 呼ばれた == [("結果", False), ("やり直し", 1), ("結果", False)], 呼ばれた
    # 条件の一覧と点数の変種が揃っていること（改善ループは不合格と同じ帯）
    assert 門.改善ループ in 門.条件の一覧 and 門.点数の変種[門.改善ループ] == 門.点数の変種[門.不合格]
    # 点が出なかった実走もループに入る（本番は `verify` が偽なら入る）
    assert 門.改善ループ未採点 in 門.条件の一覧
    assert 門.点数の変種[門.改善ループ未採点] == 門.点数の変種[門.未採点]


def test_点数で出口が変わったら報告する(門):
    r = 門.点数に連れて動く所(面("f", {}), 面("f", {}, status=500), None)
    assert r["出口"] is True


# ─────────────────── audit: 印と承認 ───────────────────

def test_印の無い数字は違反になる(門):
    違反, _ = 判定(門, [面("GET /api/x", {"watch_time_hours": 15200})], 台帳())
    assert any("出所を名乗っていない" in v for v in 違反), 違反


def test_印があれば違反にならない(門):
    観測 = [面("GET /api/x", {"is_real": False, "data_source": "sample",
                             "watch_time_hours": 15200})]
    違反, _ = 判定(門, 観測, 台帳())
    assert 違反 == []


def test_台帳で4カテゴリにした鍵名に印が要る(門):
    観測 = [面("GET /api/x", {"total_views": 850000})]
    違反, _ = 判定(門, 観測, 台帳(category_names={"total_views": "総再生数（チャンネル統計）"}))
    assert any("出所を名乗っていない" in v and "total_views" in v for v in 違反), 違反


def test_例外は面ごとに効く(門):
    本文 = {"webhooks": [{"url": "https://example.com/hook"}]}
    例外 = [{"face": "GET /api/hooks", "key": "$.webhooks[].url",
             "reason": "Webhook の送信先設定。動画の URL ではない"}]
    違反, _ = 判定(門, [面("GET /api/hooks", 本文)],
                   台帳(exemptions=例外, non_category_names=["webhooks"]))
    assert 違反 == [], 違反
    # 同じ鍵でも別の面には効かない
    違反, _ = 判定(門, [面("GET /api/other", 本文)],
                   台帳(exemptions=例外, non_category_names=["webhooks"]))
    assert any("出所を名乗っていない" in v for v in 違反), 違反


def test_条件つきの面には既定の面の例外が効く(門):
    本文 = {"webhooks": [{"url": "https://example.com/hook"}]}
    例外 = [{"face": "GET /api/hooks", "key": "$.webhooks[].url",
             "reason": "Webhook の送信先設定。動画の URL ではない"}]
    観測 = [面("GET /api/hooks", 本文),
            面("GET /api/hooks［実走後・採点済み］", 本文, route="GET /api/hooks",
               condition="実走後・採点済み")]
    違反, _ = 判定(門, 観測, 台帳(exemptions=例外, non_category_names=["webhooks"]))
    assert 違反 == [], 違反
    # 既定の面の例外を引き継がなければ落ちる（空振りでないことの確認）
    違反, _ = 判定(門, 観測[1:], 台帳(exemptions=[{**例外[0], "face": "GET /api/elsewhere"}],
                                      non_category_names=["webhooks"]))
    assert any("出所を名乗っていない" in v for v in 違反), 違反


def test_台帳に無い_measured_は違反になる(門):
    """**`sample` → `measured` の反転を落とす**（22周目 M2 の形）。"""
    本文 = {"data_source": "measured", "is_real": True, "watch_time_hours": 15200}
    違反, _ = 判定(門, [面("GET /api/x", 本文)], 台帳())
    assert any("台帳に無い `measured`" in v for v in 違反), 違反
    承認 = [{"face": "GET /api/x", "reason": "ローカルの台帳を実際に数えた"}]
    違反, _ = 判定(門, [面("GET /api/x", 本文)], 台帳(measured_claims=承認))
    assert 違反 == []


def test_measured_の承認は面ごと(門):
    """採点済みのサイドカーの承認で、**未採点のサイドカー**の `measured` を通さない。"""
    承認 = [{"face": "*.quality.json［採点済み］", "reason": "ローカルの品質ゲートで採点した"}]
    観測 = [面("*.quality.json［未採点］", {"score": None, "data_source": "measured"},
               route="*.quality.json", condition="未採点", status=None)]
    違反, _ = 判定(門, 観測, 台帳(measured_claims=承認))
    assert any("台帳に無い `measured`" in v and "未採点" in v for v in 違反), 違反


def test_サイドカーは経路の名前で承認を引き継がない(門):
    """経路（`*.quality.json`）で承認を書いても、**分岐ごとの面**には効かない。

    GET の条件つきの面は既定の面の承認を引き継ぐが、サイドカーの分岐は
    採点したか否かそのものなので、引き継ぐと未採点の `measured` が通る。
    """
    承認 = [{"face": "*.quality.json", "reason": "経路の名前だけで書いた承認（効いてはいけない）"}]
    観測 = [面("*.quality.json［未採点］", {"score": None, "data_source": "measured"},
               route="*.quality.json", condition="未採点", status=None)]
    違反, _ = 判定(門, 観測, 台帳(measured_claims=承認))
    assert any("台帳に無い `measured`" in v for v in 違反), 違反


def test_条件つきの_GET_は既定の承認を引き継ぐ(門):
    本文 = {"data_source": "measured", "passed": 3}
    観測 = [面("GET /api/d［実走後・未採点］", 本文, route="GET /api/d",
               condition="実走後・未採点")]
    承認 = [{"face": "GET /api/d", "reason": "ローカルの自己診断を実際に走らせた"}]
    違反, _ = 判定(門, 観測, 台帳(measured_claims=承認))
    assert 違反 == [], 違反


def test_measured_を名乗るなら何を測ったか要る(門):
    違反, _ = 判定(門, [], 台帳(measured_claims=[{"face": "GET /api/x", "reason": "実測"}]))
    assert any("何を測ったか" in v for v in 違反), 違反


def _動いた面(unscored: bool, **動き):
    o = 面("GET /api/r［実走後・x］", kind="text", lines=["総合スコア: 73.2点"],
           route="GET /api/r", condition="実走後・x", unscored=unscored)
    o["動いた"] = {"漏れ": [], "覆われた": 0, "文字": [], "見えない所": False, "出口": False, **動き}
    return o


def test_未採点で画面の文字が動いたら違反になる(門):
    """**台帳で見せてよい面にしていても落とす**（未採点の点を見せる理由は無い）。"""
    台帳_ = 台帳(score_displays={"GET /api/r": "採点した点を見せるレポート。未採点では未計測"})
    for 動き in ({"文字": ["総合スコア: 73.2点"]}, {"見えない所": True}):
        違反, _ = 判定(門, [_動いた面(True, **動き)], 台帳_)
        assert any("未採点の点数が画面に出ています" in v for v in 違反), (動き, 違反)


def test_採点済みで文字が動くのは台帳で許した面だけ(門):
    違反, _ = 判定(門, [_動いた面(False, 文字=["総合スコア: 92点"])], 台帳())
    assert any("点数を文字で見せる面が台帳にありません" in v for v in 違反), 違反
    台帳_ = 台帳(score_displays={"GET /api/r": "採点した点を見せるレポート。未採点では未計測"})
    違反, 情報 = 判定(門, [_動いた面(False, 文字=["総合スコア: 92点"])], 台帳_)
    assert 違反 == [], 違反
    assert not [m for m in 情報 if "点数を見せなかった" in m], 情報


def test_点数に連れて動く無印の値と出口の変化は違反になる(門):
    違反, _ = 判定(門, [_動いた面(False, 漏れ=["$.video_path"])], 台帳())
    assert any("出所を名乗っていない値" in v and "$.video_path" in v for v in 違反), 違反
    違反, _ = 判定(門, [_動いた面(False, 出口=True)], 台帳())
    assert any("点数によって出口" in v for v in 違反), 違反


def test_点数を見せてよい面は理由が要り使われなければ知らせる(門):
    違反, 情報 = 判定(門, [], 台帳(score_displays={"GET /api/r": "見せる"}))
    assert any("見せてよい理由を書く" in v for v in 違反), 違反
    assert any("点数を見せなかった面の宣言" in m for m in 情報), 情報


# ─────────────────── audit: 面のラチェット ───────────────────

def test_呼び出せなかった面は違反になる(門):
    """**沈黙は緑ではない。** 落ちた経路ほど静かに通ってはいけない。"""
    観測 = [{**面("GET /api/x", kind="error"), "error": "Boom"}]
    違反, _ = 判定(門, 観測, 台帳(), {"faces": {}})
    assert any("呼び出せませんでした" in v for v in 違反), 違反


def test_台帳に無い面は違反になる(門):
    観測 = [面("GET /api/新顔", {"n": 1})]
    違反, _ = 判定(門, 観測, 台帳(non_category_names=["n"]), {"faces": {}})
    assert any("台帳に無い面" in v for v in 違反), 違反


def test_面が消えたら違反になる(門):
    """ルートが import に失敗して消えても、下限だけでは気づけない。"""
    面台帳 = 門.面台帳を作る([面("GET /api/a", {}), 面("GET /api/b", {})])
    違反, _ = 判定(門, [面("GET /api/a", {})], 台帳(), 面台帳)
    assert any("面が消えました" in v and "GET /api/b" in v for v in 違反), 違反


def test_新しい鍵が出たら落ちる(門):
    """**包括的な印の下に数字を足す形**（23周目）を止める。"""
    面台帳 = 門.面台帳を作る([面("GET /api/x", {"is_real": True, "ctr": 3.5})])
    観測 = [面("GET /api/x", {"is_real": True, "ctr": 3.5, "predicted_ctr": 7.7})]
    違反, _ = 判定(門, 観測, 台帳(), 面台帳)
    assert any("新しい鍵" in v and "predicted_ctr" in v for v in 違反), 違反


def test_鍵の種類が変わったら落ちる(門):
    面台帳 = 門.面台帳を作る([面("GET /api/x", {"stats": {"n": 1}})])
    違反, _ = 判定(門, [面("GET /api/x", {"stats": 15200})],
                   台帳(non_category_names=["stats", "n"]), 面台帳)
    assert any("新しい鍵" in v and "$.stats:num" in v for v in 違反), 違反


def test_鍵が減っても落とさない(門):
    """減るのは前進（出す数字が減った）。**台帳の掃除を促すだけ。**"""
    面台帳 = 門.面台帳を作る([面("GET /api/x", {"a": 1, "b": 2})])
    違反, 情報 = 判定(門, [面("GET /api/x", {"a": 1})],
                      台帳(non_category_names=["a", "b"]), 面台帳)
    assert 違反 == [], 違反
    assert any("出なくなった鍵" in m for m in 情報), 情報


def test_出所の印が消えたら落ちる(門):
    """**印の鍵が面から消えるのは退行。** 文字に埋まった点数（障害の見出しの「85→72」）は
    鍵名では見えないので、印が消えたこと自体を止める（26周目の見落としへの対処）。"""
    面台帳 = 門.面台帳を作る([面("GET /api/x", {"is_real": False, "data_source": "sample",
                                                "title": "品質スコア低下(85→72)"})])
    違反, _ = 判定(門, [面("GET /api/x", {"title": "品質スコア低下(85→72)"})],
                   台帳(non_category_names=["title"]), 面台帳)
    assert any("出所の印が消えました" in v and "$.data_source" in v for v in 違反), 違反
    # 印でない鍵が減るのは従来どおり情報
    面台帳 = 門.面台帳を作る([面("GET /api/x", {"a": 1, "b": 2})])
    違反, _ = 判定(門, [面("GET /api/x", {"a": 1})], 台帳(non_category_names=["a", "b"]), 面台帳)
    assert 違反 == [], 違反
    # 文字の面の行は道ではない（道に見える行が消えても印の消失ではない）
    面台帳 = 門.面台帳を作る([面("GET /r", kind="text", lines=["注意.data_source: 見本", "x"])])
    違反, _ = 判定(門, [面("GET /r", kind="text", lines=["x"])], 台帳(), 面台帳)
    assert 違反 == [], 違反


def test_出口が変わったら落ちる(門):
    面台帳 = 門.面台帳を作る([面("GET /api/x", {"detail": "x"}, status=404)])
    違反, _ = 判定(門, [面("GET /api/x", {"detail": "x"}, status=410)],
                   台帳(non_category_names=["detail"]), 面台帳)
    assert any("面の出口が変わりました" in v for v in 違反), 違反


def test_HTML_の行が変わったら落ちる(門):
    """**25周目 M-4b。** 未採点のレポートに合格点を出しても、以前の門は本文を見ていなかった。"""
    面台帳 = 門.面台帳を作る([面("GET /r", kind="text", lines=["総合スコア: 未計測"])])
    違反, _ = 判定(門, [面("GET /r", kind="text", lines=["総合スコア: 92.0点（合格）"])],
                   台帳(), 面台帳)
    assert any("新しい鍵" in v and "92.0点" in v for v in 違反), 違反


def test_条件つきの面は既定の形に収まれば台帳に要らない(門):
    既定の = 面("GET /api/s", {"a": 1})
    条件つき = 面("GET /api/s［実走後・採点済み］", {"a": 2}, route="GET /api/s",
                  condition="実走後・採点済み")
    面台帳 = 門.面台帳を作る([既定の, 条件つき])
    assert list(面台帳["faces"]) == ["GET /api/s"]
    違反, _ = 判定(門, [既定の, 条件つき], 台帳(non_category_names=["a"]), 面台帳)
    assert 違反 == [], 違反


def test_条件つきの面が既定からはみ出したら落ちる(門):
    面台帳 = 門.面台帳を作る([面("GET /api/s", {"a": 1})])
    条件つき = 面("GET /api/s［実走後・採点済み］", {"a": 2, "result": {"score": 1, "scored": True}},
                  route="GET /api/s", condition="実走後・採点済み")
    違反, _ = 判定(門, [面("GET /api/s", {"a": 1}), 条件つき],
                   台帳(non_category_names=["a", "result"]), 面台帳)
    assert any("台帳に無い面" in v and "実走後・採点済み" in v for v in 違反), 違反


def test_面台帳は条件つきの面の違いを載せる(門):
    既定の = 面("GET /api/s", {"a": 1})
    条件つき = 面("GET /api/s［実走後・採点済み］", {"a": 1, "b": 2}, route="GET /api/s",
                  condition="実走後・採点済み")
    面台帳 = 門.面台帳を作る([既定の, 条件つき])
    assert set(面台帳["faces"]) == {"GET /api/s", "GET /api/s［実走後・採点済み］"}


def test_面台帳の足し込みは既存の形との和(門):
    """別の環境（CI の Linux）で出た鍵を足すとき、手元の鍵を消さない。"""
    既存 = {"note": "n", "faces": {"GET /api/x": {"status": 200, "kind": "json",
                                                   "shape": ["$.linux:num", "$:dict"]}}}
    出す = 門.面台帳を作る([面("GET /api/x", {"win": 1})], 既存, 足すだけ=True)
    assert 出す["note"] == "n"
    assert 出す["faces"]["GET /api/x"]["shape"] == ["$.linux:num", "$.win:num", "$:dict"]


# ─────────────────── audit: 鍵名の分類 ───────────────────

def test_分類されていない鍵名は違反になる(門):
    違反, _ = 判定(門, [面("GET /api/x", {"foo": 1})], 台帳())
    assert any("分類されていない鍵名" in v and "foo" in v for v in 違反), 違反
    違反, _ = 判定(門, [面("GET /api/x", {"foo": 1})], 台帳(non_category_names=["foo"]))
    assert 違反 == [], 違反


def test_印の鍵は分類済みとして扱う(門):
    違反, _ = 判定(門, [面("GET /api/x", {"is_real": False, "data_source": "sample"})], 台帳())
    assert 違反 == [], 違反


def test_危険鍵は対象外に分類できない(門):
    for 台帳_ in (台帳(non_category_names=["views"]),
                 台帳(non_category_names_reviewed={"views": "ここでは再生数ではない"})):
        違反, _ = 判定(門, [], 台帳_)
        assert any("危険鍵" in v and "views" in v for v in 違反), 違反


def test_紛らわしい鍵名は一括で対象外にできない(門):
    違反, _ = 判定(門, [], 台帳(non_category_names=["total_views"]))
    assert any("紛らわしい鍵名" in v for v in 違反), 違反
    違反, _ = 判定(門, [], 台帳(non_category_names_reviewed={
        "total_views": "テスト用の理由。十分な長さがある"}))
    assert 違反 == [], 違反


def test_分類の理由が短いと違反になる(門):
    違反, _ = 判定(門, [], 台帳(non_category_names_reviewed={"rpm": "制限"}))
    assert any("対象外にする理由を書く" in v for v in 違反), 違反
    違反, _ = 判定(門, [], 台帳(category_names={"total_views": "再生数"}))
    assert any("4カテゴリに入れる理由を書く" in v for v in 違反), 違反


def test_二重の分類は違反になる(門):
    違反, _ = 判定(門, [], 台帳(category_names={"rpm": "収益の RPM（チャンネル統計）"},
                                non_category_names_reviewed={"rpm": "レート制限の上限値。収益ではない"}))
    assert any("対象外にも分類" in v for v in 違反), 違反


def test_例外にも理由が要る(門):
    違反, _ = 判定(門, [], 台帳(exemptions=[{"face": "GET /api/x", "key": "$.url", "reason": "設定"}]))
    assert any("例外にするなら理由" in v for v in 違反), 違反


def test_使われていない例外は情報で知らせる(門):
    例外 = [{"face": "GET /api/gone", "key": "$.url", "reason": "もう無い面への例外。掃除候補"}]
    違反, 情報 = 判定(門, [], 台帳(exemptions=例外))
    assert 違反 == []
    assert any("使われていない例外" in m for m in 情報), 情報


# ─────────────────── audit: 母集団と隔離 ───────────────────

def test_下限は本文を検査した既定の_GET_面で数える(門):
    """**25周目 D-7。** 以前は列挙したルート数を数えていた（本文を見たのは 298 < 300）。"""
    観測 = [
        面("GET /api/a", {}),
        面("GET /api/b", kind="text", lines=["x"]),
        面("GET /api/c", kind="none"),                       # 本文なし
        {**面("GET /api/d", kind="error"), "error": "Boom"},  # 呼べなかった
        面("GET /api/a［実走後・採点済み］", {}, route="GET /api/a", condition="実走後・採点済み"),
        面("*.quality.json［採点済み］", {}, route="*.quality.json", condition="採点済み"),
    ]
    違反, _ = 判定(門, 観測, 台帳(population_floor=3))
    assert any("下限を割りました" in v and "2 < 3" in v for v in 違反), 違反
    違反, _ = 判定(門, 観測, 台帳(population_floor=2))
    assert not [v for v in 違反 if "下限" in v], 違反


def test_下限が無い台帳では落とさない(門):
    違反, _ = 判定(門, [], 台帳())
    assert not [v for v in 違反 if "下限" in v]


def test_宣言していない_method_を外したら落ちる(門):
    違反, _ = 判定(門, [], 台帳(side_effect_methods=["POST"]),
                   付帯={"内訳": {"POST": 3, "DELETE": 1}})
    assert any("宣言していない method" in v and "DELETE" in v for v in 違反), 違反


def test_盲点が増えたら落ちる(門):
    違反, _ = 判定(門, [], 台帳(side_effect_blind_spot=["POST /api/a/score"]),
                   付帯={"盲点": ["POST /api/a/score", "POST /api/b/ctr"]})
    assert any("盲点が増えました" in v and "/api/b/ctr" in v for v in 違反), 違反


def test_盲点が減っても落とさない(門):
    違反, 情報 = 判定(門, [], 台帳(side_effect_blind_spot=["POST /api/a/score", "POST /api/b/ctr"]),
                      付帯={"盲点": ["POST /api/a/score"]})
    assert not [v for v in 違反 if "盲点" in v]
    assert any("盲点が減りました" in m for m in 情報), 情報


def test_WebSocket_は通り道として宣言が要る(門):
    """26周目: `/api` 配下の WebSocket が母集団の外の内訳に出ていなかった。"""
    内訳 = {"POST": 1, "WEBSOCKET": 2}
    違反, _ = 判定(門, [], 台帳(side_effect_methods=["POST"]), 付帯={"内訳": 内訳})
    assert any("宣言していない method" in v and "WEBSOCKET" in v for v in 違反), 違反
    台帳_ = 台帳(side_effect_methods=["POST"],
                excluded_transports={"WEBSOCKET": "接続して待つ通り道。1回叩いて本文を得られない"})
    違反, _ = 判定(門, [], 台帳_, 付帯={"内訳": 内訳})
    assert 違反 == [], 違反
    違反, _ = 判定(門, [], 台帳(excluded_transports={"WEBSOCKET": "待つ"}))
    assert any("通り道には理由を書く" in v for v in 違反), 違反


def test_パス引数の値の出どころが無ければ落ちる(門):
    """**26周目 M11/M12。** 合成の値だけでは、一覧が返す ID でしか開かない面が見えない。"""
    付帯 = {"パス引数": {"未宣言": ["GET /api/c/{id}"], "値が取れない": ["GET /api/d/{id} ← GET /api/d $.x[].id"],
                     "使われていない宣言": ["GET /api/gone/{id}"],
                     "上限より多い": ["GET /api/e/{id} ← GET /api/e $.x[].id（4 件 > 上限 2）"]}}
    違反, 情報 = 判定(門, [], 台帳(), 付帯=付帯)
    assert any("パス引数の値の出どころが台帳にありません" in v and "/api/c/{id}" in v for v in 違反), 違反
    assert any("一覧 API から値が取れません" in v and "/api/d/{id}" in v for v in 違反), 違反
    assert any("一覧が返す値を全部は叩けていません" in v and "/api/e/{id}" in v for v in 違反), 違反
    assert any("使われていないパス引数の宣言" in m for m in 情報), 情報


def test_一覧が上限より多くの値を返したら落ちる(門):
    """**27周目 M11。** 上限で黙って打ち切ると、一覧の3件目以降に足した数字が見えない。"""
    既定 = [面("GET /api/th", {"themes": [{"id": "warm"}, {"id": "cool"},
                                          {"id": "energetic"}, {"id": "calm"}]})]
    宣言 = {"GET /api/th/{id}": {"from": "GET /api/th", "take": "$.themes[].id", "limit": 2}}
    値, 問題 = 門.パス引数の値(["/api/th/{id}"], 既定, 台帳(path_values=宣言))
    assert 問題["上限より多い"] == ["GET /api/th/{id} ← GET /api/th $.themes[].id（4 件 > 上限 2）"], 問題
    assert 値["GET /api/th/{id}"] == ["warm", "cool"], "上限までは叩く"
    宣言["GET /api/th/{id}"]["limit"] = 4
    値, 問題 = 門.パス引数の値(["/api/th/{id}"], 既定, 台帳(path_values=宣言))
    assert 問題["上限より多い"] == [] and 値["GET /api/th/{id}"] == ["warm", "cool", "energetic", "calm"]


def test_パス引数の宣言は形と理由が要る(門):
    宣言 = {
        "GET /api/a/{id}": {"from": "GET /api/a", "take": "channels[].id"},
        "GET /api/b/{id}": {"values": ["x"], "reason": "短い"},
        "GET /api/c/{id}": {"none": "無い"},
        "GET /api/d/{id}": {"limit": 3},
        "GET /api/e/{id}": {"from": "GET /api/e", "take": "$.items[].id", "limit": 2, "order": "name"},
        "GET /api/f/{id}": {"from": "GET /api/f", "take": "$.items[].id", "order": "mtime"},
    }
    違反, _ = 判定(門, [], 台帳(path_values=宣言))
    assert any("取る値の道（take）を書く" in v and "/api/a/" in v for v in 違反), 違反
    assert any("決まった値を使うなら理由" in v and "/api/b/" in v for v in 違反), 違反
    assert any("出どころが無いなら理由" in v and "/api/c/" in v for v in 違反), 違反
    assert any("宣言の形が読めません" in v and "/api/d/" in v for v in 違反), 違反
    assert not [v for v in 違反 if "/api/e/" in v], 違反
    assert any("並べ方（order）は name だけ" in v and "/api/f/" in v for v in 違反), 違反


def test_門がリポジトリを書き換えたら落ちる(門):
    """**25周目 D-5。** 門は状態を書き換えてはいけない。"""
    違反, _ = 判定(門, [], 台帳(), 付帯={"書き換わったもの": ["変更 assets/asset_index.json"]})
    assert any("門がリポジトリを書き換えました" in v for v in 違反), 違反


def test_隔離の漏れは違反になる(門):
    違反, _ = 判定(門, [], 台帳(), 付帯={"漏れたモジュール": ["main (backend/main.py)"]})
    assert any("隔離の漏れ" in v for v in 違反), 違反


def test_書き換わったものは変更と作成と削除を拾う(門):
    前 = {"a": (1, 1), "b": (1, 1), "c": (1, 1)}
    後 = {"a": (1, 1), "b": (2, 5), "d": (1, 1)}
    assert 門.書き換わったもの(前, 後) == ["作成 d", "削除 c", "変更 b"]


def test_状態の指紋は書き込みを拾いバイトコードは数えない(門, tmp_path):
    """門は自分のモジュールを import するので `__pycache__` だけは書く。それ以外は全部拾う。"""
    (tmp_path / "logs").mkdir()
    (tmp_path / "a.json").write_text("1", encoding="utf-8")
    前 = 門.状態の指紋(tmp_path)
    (tmp_path / "logs" / "backend.log").write_text("x", encoding="utf-8")   # 無視されがちな置き場
    (tmp_path / "a.json").write_text("22", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "m.cpython-313.pyc").write_bytes(b"\0")
    後 = 門.状態の指紋(tmp_path)
    assert 門.書き換わったもの(前, 後) == ["作成 logs/backend.log", "変更 a.json"]


def test_漏れたモジュールは本物の下にあって複製の下に無いもの(門, tmp_path, monkeypatch):
    本物, 複製 = tmp_path / "real", tmp_path / "copy"
    for 名, 場所 in (("_c4t_real", 本物 / "backend" / "x.py"),
                     ("_c4t_copy", 複製 / "backend" / "x.py"),
                     ("_c4t_other", tmp_path / "elsewhere.py")):
        m = types.ModuleType(名)
        m.__file__ = str(場所)
        monkeypatch.setitem(sys.modules, 名, m)
    出た = [x for x in 門.漏れたモジュール(複製, 本物) if x.startswith("_c4t_")]
    assert 出た == ["_c4t_real (backend/x.py)"], 出た


def test_漏れたモジュールはリポジトリの中の仮想環境を数えない(門, tmp_path, monkeypatch):
    """`.venv` をリポジトリの中に置いた開発機で、依存ライブラリ全部を漏れと呼ばない。"""
    本物, 複製 = tmp_path / "real", tmp_path / "copy"
    m = types.ModuleType("_c4t_venv")
    m.__file__ = str(本物 / ".venv" / "Lib" / "site-packages" / "fastapi" / "__init__.py")
    monkeypatch.setitem(sys.modules, "_c4t_venv", m)
    出た = [x for x in 門.漏れたモジュール(複製, 本物, 除外=(本物 / ".venv",))
            if x.startswith("_c4t_")]
    assert 出た == [], 出た
    出た = [x for x in 門.漏れたモジュール(複製, 本物, 除外=()) if x.startswith("_c4t_")]
    assert 出た == ["_c4t_venv (.venv/Lib/site-packages/fastapi/__init__.py)"], 出た


def test_隔離の環境は実キーと網の抜け道を消す(門, tmp_path):
    元 = {"GOOGLE_API_KEY": "not-a-real-key", "GEMINI_API_KEY": "not-a-real-key",
          "GOOGLE_API_KEY_PRO": "not-a-real-key", "ANTIGRAVITY_ALLOW_NETWORK": "1",
          "OPENAI_API_KEY": "not-a-real-key", "HF_TOKEN": "not-a-real-token",
          "YOUTUBE_CLIENT_SECRET": "x", "GOOGLE_APPLICATION_CREDENTIALS": "/x/creds.json",
          "PATH": "p", "HOME": "/home/me"}
    作業場, 複製 = tmp_path / "w", tmp_path / "w" / "repo"
    env = 門.隔離の環境変数(作業場, 複製, 元)
    assert env["GOOGLE_API_KEY"] == "dummy_key_for_ci"
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY_PRO", "ANTIGRAVITY_ALLOW_NETWORK",
              "OPENAI_API_KEY", "HF_TOKEN", "YOUTUBE_CLIENT_SECRET",
              "GOOGLE_APPLICATION_CREDENTIALS"):
        assert k not in env, k
    assert env["ANTIGRAVITY_WRITABLE_ROOT"] == str(複製)
    assert env["ANTIGRAVITY_BASE_DIR"] == str(複製)
    assert Path(env["HOME"]).parent == 作業場 and Path(env["USERPROFILE"]).parent == 作業場
    assert Path(env["ANTIGRAVITY_APP_DATA_DIR"]).parent == 作業場
    assert env["PYTHONPATH"].split(__import__("os").pathsep)[0] == str(複製 / "backend")
    assert env["PATH"] == "p"


def test_門は外部のアプリを起こさない(門, monkeypatch):
    """**GET でも利用者のデスクトップに窓を開くものがある**（2026-09-17 に発見）。

    `GET /api/pipeline/open-folder` は `os.startfile()` を呼ぶので、Windows で門を
    走らせるたびにエクスプローラーが開いていた（1回で最大6枚）。Linux には
    `os.startfile` が無く、応答の形まで OS で変わっていた。**どの OS でも拒む。**
    """
    import os
    import webbrowser
    # 元に戻せるように monkeypatch に先に記録させる（門の関数が上書きしても戻る）
    monkeypatch.setattr(os, "startfile", lambda *a, **k: None, raising=False)
    for 名 in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(webbrowser, 名, lambda *a, **k: True)
    門._外のアプリを起こさない()
    with pytest.raises(OSError):
        os.startfile("C:/")
    for 名 in ("open", "open_new", "open_new_tab"):
        with pytest.raises(OSError):
            getattr(webbrowser, 名)("https://example.invalid/")


def test_起こす前に外部接続と外のアプリを封じる(門, tmp_path, monkeypatch):
    """封じる関数があっても、**アプリを読む前に呼ばなければ意味が無い。**

    26周目 G7/G7b — 以前の契約は main を先に sys.modules へ置いていたので、
    封じる呼び出しを `import main` の後ろへ移しても通った。**main を本当に読ませ、
    読まれた瞬間に封じてあったかを main 自身に記録させる。**
    """
    複製 = tmp_path / "repo"
    (複製 / "backend" / "tests").mkdir(parents=True)
    (複製 / "backend" / "tests" / "net_guard.py").write_text(
        "呼ばれた = []\n\ndef install():\n    呼ばれた.append('install')\n", encoding="utf-8")
    (複製 / "backend" / "main.py").write_text(
        "import os, sys\n"
        "ng = sys.modules.get('net_guard')\n"
        "読んだときに網があった = bool(ng and getattr(ng, '呼ばれた', None))\n"
        "読んだときに窓を封じていた = sys.modules['_c4t_順番'].順番 == ['外のアプリ']\n"
        "app = object()\n", encoding="utf-8")
    記録 = types.ModuleType("_c4t_順番")
    記録.順番 = []
    monkeypatch.setitem(sys.modules, "_c4t_順番", 記録)
    monkeypatch.setitem(sys.modules, "net_guard", sys.modules.get("net_guard"))
    # 後で元に戻す（無かったなら消す）ために記録させてから外す — 偽の main を他のテストに残さない
    monkeypatch.setitem(sys.modules, "main", None)
    del sys.modules["main"]
    monkeypatch.syspath_prepend(str(複製 / "backend"))
    monkeypatch.setattr(門, "_外のアプリを起こさない", lambda: 記録.順番.append("外のアプリ"))

    app = 門.起こす(複製)
    main = sys.modules["main"]
    assert app is main.app
    assert main.読んだときに網があった, "net_guard を main より先に入れていない"
    assert main.読んだときに窓を封じていた, "外のアプリを main より先に封じていない"

    # 複製の外の main を読んだら止める（隔離の漏れ）
    偽の_main = types.ModuleType("main")
    偽の_main.__file__ = str(tmp_path / "elsewhere" / "main.py")
    偽の_main.app = object()
    monkeypatch.setitem(sys.modules, "main", 偽の_main)
    with pytest.raises(RuntimeError):
        門.起こす(複製)


@pytest.mark.skipif(shutil.which("git") is None, reason="git が要る")
def test_複製は無視したファイルを入れない(門, tmp_path):
    """**`.env` や手元のデータを複製に持ち込まない。** CI のチェックアウトと同じものだけで測る。"""
    src = tmp_path / "src"
    src.mkdir()
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    (src / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (src / "tracked.txt").write_text("t", encoding="utf-8")
    (src / "gone.txt").write_text("g", encoding="utf-8")
    subprocess.run(["git", "-C", str(src), "add", "tracked.txt", "gone.txt"], check=True)
    (src / "gone.txt").unlink()                     # 作業ツリーで消した
    (src / "untracked.txt").write_text("u", encoding="utf-8")
    (src / "ignored.txt").write_text("secret", encoding="utf-8")
    先 = tmp_path / "dst"
    n = 門.複製する(src, 先)
    assert sorted(p.name for p in 先.iterdir()) == [".gitignore", "tracked.txt", "untracked.txt"]
    assert n == 3


# ─────────────────── 応答の集め方（小さなアプリで実際に叩く） ───────────────────

@pytest.fixture(scope="module")
def 小さなアプリ():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

    app = FastAPI()

    @app.get("/api/ok")
    def ok():
        return {"n": 1}

    @app.get("/api/nf/{item}")
    def nf(item: str):
        return JSONResponse(status_code=404, content={"quality_score": 98.5, "item": item})

    @app.get("/api/boom")
    def boom():
        raise HTTPException(status_code=500, detail="boom")

    @app.get("/api/page", response_class=HTMLResponse)
    def page():
        return "<p>総合スコア: <b>未計測</b></p>"

    @app.get("/api/go")
    def go():
        return RedirectResponse("/elsewhere", status_code=307)

    @app.post("/api/write")
    def write():
        return {"written": True}

    return app


def test_応答は_status_によらず本文まで集める(門, 小さなアプリ):
    """**25周目 D-3。** 200 以外の本文も、HTML も、面として持ち帰る。"""
    出た = {o["face"]: o for o in 門.応答を集める(小さなアプリ)}
    assert set(出た) == {"GET /api/ok", f"GET /api/nf/{門.探り値}", "GET /api/boom",
                         "GET /api/page", "GET /api/go"}, "POST は叩かない"
    nf = 出た[f"GET /api/nf/{門.探り値}"]
    assert (nf["status"], nf["kind"]) == (404, "json")
    assert nf["body"] == {"quality_score": 98.5, "item": 門.探り値}
    assert (出た["GET /api/boom"]["status"], 出た["GET /api/boom"]["kind"]) == (500, "json")
    assert 出た["GET /api/page"]["lines"] == ["総合スコア: 未計測"]


def test_応答はリダイレクトを追わない(門, 小さなアプリ):
    """追うと `/api` の外の面を測ることになる。"""
    go = {o["face"]: o for o in 門.応答を集める(小さなアプリ)}["GET /api/go"]
    assert (go["status"], go["kind"]) == (307, "none")
    assert go["lines"] == ["Location: /elsewhere"]


def test_条件つきの応答は面の名前に条件を持つ(門, 小さなアプリ):
    出た = 門.応答を集める(小さなアプリ, 門.未採点)
    ok = next(o for o in 出た if o["route"] == "GET /api/ok")
    assert ok["face"] == "GET /api/ok［実走後・未採点］" and ok["condition"] == 門.未採点


# ─────────────────── 入力条件（本番の書き出し口を実際に呼ぶ） ───────────────────

def test_サイドカーは分岐ごとに書かせる(門, tmp_path):
    """**25周目 D-2。** 以前は採点済みの1形でしか呼んでいなかった。"""
    出た = {o["face"]: o for o in 門.サイドカーを書かせる(tmp_path)}
    assert {k: v["kind"] for k, v in 出た.items()} == {
        "*.quality.json［採点済み］": "json",
        "*.quality.json［未採点］": "json",
        "*.quality.json［講評なし］": "none",
        "*.youtube.json［メタデータあり］": "json",
        "*.youtube.json［メタデータなし］": "none",
    }
    未 = 出た["*.quality.json［未採点］"]
    assert 未["unscored"] is True
    assert 未["body"]["score"] is None and 未["body"]["data_source"] == "unavailable"
    assert 出た["*.quality.json［採点済み］"]["body"]["data_source"] == "measured"


def test_状態を差したら必ず戻す(門, monkeypatch):
    偽 = types.ModuleType("routers.pipeline_router")
    偽._pipeline_state = {"status": "idle", "result": None}
    monkeypatch.setitem(sys.modules, "routers.pipeline_router", 偽)
    with pytest.raises(RuntimeError), 門.状態を差す({"status": "completed", "result": {"x": 1}}):
        assert 偽._pipeline_state == {"status": "completed", "result": {"x": 1}}
        raise RuntimeError("途中で落ちても")
    assert 偽._pipeline_state == {"status": "idle", "result": None}


# ─────────────────── 危険鍵の定義を二重管理しない ───────────────────

def test_危険鍵は_c4_inventory_と同じ定義を使う(門):
    """**網の内部で定義が食い違うのが21周目の指摘だった。**"""
    from backend import c4_inventory
    assert 門.RISK_KEY_RE.pattern == c4_inventory.RISK_KEY_RE.pattern


# ─────────────────── 台帳そのもの ───────────────────

@pytest.fixture(scope="module")
def 本物の台帳(門):
    return 門.load_ledger()


@pytest.fixture(scope="module")
def 本物の面台帳(門):
    return 門.load_faces()


def test_台帳は理由つきで必要な鍵がある(本物の台帳):
    assert set(本物の台帳) >= {
        "category_names", "non_category_names_reviewed", "non_category_names",
        "exemptions", "measured_claims", "population_floor", "side_effect_methods",
        "side_effect_blind_spot"}
    for e in 本物の台帳["exemptions"] + 本物の台帳["measured_claims"]:
        assert len(str(e.get("reason", ""))) >= 10, e
    assert "out_of_population" not in 本物の台帳, "面を丸ごと外す仕組みは持たない（25周目 D-1）"


def test_台帳の分類は重ならず危険鍵を外さない(門, 本物の台帳):
    カテゴリ = set(本物の台帳["category_names"])
    個別 = set(本物の台帳["non_category_names_reviewed"])
    一括 = set(本物の台帳["non_category_names"])
    assert not (カテゴリ & 個別) and not (カテゴリ & 一括) and not (個別 & 一括)
    assert not [n for n in 個別 | 一括 if 門.RISK_KEY_RE.match(n)]
    assert not [n for n in 一括 if 門.STRONG_VOCAB_RE.search(n)]


def test_台帳は_R1_5_C6_の監査に依存として数えられない(本物の台帳):
    """**観測した鍵名にはモデル ID が混ざる**（`fallback_chain` の鍵 `gemini-2.5-flash`）。

    2026-09-17、一括の鍵名を配列の値として持ったところ、`model_policy --sunset` が
    「設定データの値がそのまま API に渡ります」と数えて R1.5-C6 を落とした。
    **自分の修正が別の条件を壊した**ので、形をここで固定する（鍵名はキーとして持つ）。
    """
    from model_policy import _count_json_model_ids
    assert _count_json_model_ids(本物の台帳) == 0
    assert isinstance(本物の台帳["non_category_names"], dict)


def test_面台帳も_R1_5_C6_の監査に依存として数えられない(本物の面台帳):
    from model_policy import _count_json_model_ids
    assert _count_json_model_ids(本物の面台帳) == 0


def test_面台帳は形がそろっている(門, 本物の面台帳, 本物の台帳):
    faces = 本物の面台帳["faces"]
    既定の_GET = [k for k in faces if k.startswith("GET ") and "［" not in k]
    assert len(既定の_GET) >= 本物の台帳["population_floor"]
    for k, v in faces.items():
        assert set(v) == {"status", "kind", "shape"}, k
        assert v["kind"] in ("json", "text", "none", "binary"), k
        assert v["shape"] == sorted(set(v["shape"])), f"整列・重複なしで持つ: {k}"


def test_面台帳にサイドカーの全分岐がある(本物の面台帳):
    """**25周目 D-2** を台帳の側でも固定する。"""
    faces = 本物の面台帳["faces"]
    for 名 in ("*.quality.json［採点済み］", "*.quality.json［未採点］",
               "*.quality.json［講評なし］", "*.youtube.json［メタデータあり］",
               "*.youtube.json［メタデータなし］"):
        assert 名 in faces, 名
    未 = set(faces["*.quality.json［未採点］"]["shape"])
    assert {"$.score:null", "$.data_source:str", "$.scored:bool"} <= 未


def test_面台帳の未採点のレポートは未計測と言っている(本物の面台帳):
    """**25周目 M-4b** を台帳の側でも固定する（悪い状態で書き直した台帳を通さない）。"""
    行 = 本物の面台帳["faces"]["GET /api/pipeline/report［実走後・未採点］"]["shape"]
    assert "総合スコア: 未計測（品質ゲートを通していません）" in 行
    assert not [x for x in 行 if "73.21" in x]


def test_例外と承認は面台帳にある面を指す(本物の台帳, 本物の面台帳):
    """**台帳が腐っていないこと。** 例外の鍵は、その面の形に実際にある。"""
    faces = 本物の面台帳["faces"]
    for e in 本物の台帳["exemptions"]:
        assert e["face"] in faces, e
        assert any(s.rsplit(":", 1)[0] == e["key"] for s in faces[e["face"]]["shape"]), e
    for e in 本物の台帳["measured_claims"]:
        assert e["face"] in faces, e


def test_パス引数の宣言は面台帳のテンプレートと一対一(門, 本物の台帳, 本物の面台帳):
    """**テンプレート付きの GET は全部、値の出どころが台帳にある**（26周目 M11/M12）。

    面台帳には合成の値で叩いた面が1本ずつあるので、それと宣言を突き合わせる。
    """
    探りの面 = {k for k in 本物の面台帳["faces"] if 門.探り値 in k and "［" not in k}
    宣言 = 本物の台帳["path_values"]
    宣言の面 = {門._埋める(k, 門.探り値) for k in 宣言}
    assert 探りの面 == 宣言の面
    一覧から = [k for k, v in 宣言.items() if "from" in v]
    assert len(一覧から) >= 10, "一覧 API から値を取る宣言が少なすぎる"
    for k, v in 宣言.items():
        if "from" in v:
            assert v["from"] in 本物の面台帳["faces"], (k, v)


def test_面台帳に一覧の_ID_で開いた面がある(本物の面台帳):
    """C4a の名指し例（ch-001）と、7周目の迂回箇所（MCP の進化ログ）が門の視野に入っている。"""
    faces = 本物の面台帳["faces"]
    for 名 in ("GET /api/admin/channel/channels/ch-001", "GET /api/v1/mcp/resources/evolution_log"):
        assert 名 in faces and faces[名]["status"] == 200, 名


def test_点数を見せる面と通り道の宣言は実在する(本物の台帳, 本物の面台帳):
    faces = 本物の面台帳["faces"]
    for 経路 in 本物の台帳["score_displays"]:
        assert 経路 in faces and faces[経路]["kind"] == "text", 経路
    assert "WEBSOCKET" in 本物の台帳["excluded_transports"]
    ws = [x for x in 本物の台帳["side_effect_blind_spot"] if x.startswith("WEBSOCKET ")]
    assert len(ws) >= 2, ws


def test_台帳は_JSON_として妥当(門):
    json.loads(門.LEDGER_PATH.read_text(encoding="utf-8"))
    json.loads(門.FACES_PATH.read_text(encoding="utf-8"))


# ─────────────────── ルートの拾い方 ───────────────────

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
    class R:
        def __init__(s, p, m): s.path, s.methods = p, m
    class M:
        def __init__(s, p, rs): s.path, s.routes = p, rs
    app = SimpleNamespace(routes=[M("/api", [R("/inner", {"GET"})]),
                                  R("/api/top", {"GET"})])
    assert ("GET", "/api/inner") in 門.ルート一覧(app)
    assert ("GET", "/api/top") in 門.ルート一覧(app)


def test_ルート一覧は_openapi_からも拾う(門):
    """**`app.routes` を歩くだけでは新しい FastAPI で0件になる**（2026-09-13 に CI で観測）。"""
    app = SimpleNamespace(
        routes=[],
        openapi=lambda: {"paths": {
            "/api/a": {"get": {}, "post": {}},
            "/api/b/{x}": {"get": {}},
            "/other": {"get": {}},
        }},
    )
    一覧 = 門.ルート一覧(app)
    assert ("GET", "/api/a") in 一覧
    assert ("POST", "/api/a") in 一覧
    assert ("GET", "/api/b/{x}") in 一覧
    assert not [p for _, p in 一覧 if p == "/other"], "`/api` の外は拾わない"


def test_ルート一覧は両方の和を取る(門):
    """`include_in_schema=False` は openapi に出ないので、走査側でも拾う。"""
    class R:
        def __init__(s, p, m): s.path, s.methods = p, m
    app = SimpleNamespace(
        routes=[R("/api/hidden", {"GET"})],
        openapi=lambda: {"paths": {"/api/shown": {"get": {}}}},
    )
    一覧 = 門.ルート一覧(app)
    assert ("GET", "/api/hidden") in 一覧
    assert ("GET", "/api/shown") in 一覧


def test_openapi_が壊れていても走査側で拾う(門):
    def 壊れる(): raise RuntimeError("boom")
    class R:
        def __init__(s, p, m): s.path, s.methods = p, m
    app = SimpleNamespace(routes=[R("/api/a", {"GET"})], openapi=壊れる)
    assert ("GET", "/api/a") in 門.ルート一覧(app)


class _R:
    def __init__(s, p, m):
        s.path, s.methods = p, m


class APIWebSocketRoute:   # 型の名前で見分けるので、名前だけ本物に合わせる
    def __init__(s, p):
        s.path = p


def test_ルート一覧は新しい_FastAPI_の包みの中も辿る(門):
    """**fastapi 0.141 の `_IncludedRouter`**（中身は `original_router`、接頭辞は `include_context`）。

    ここを辿らないと、openapi に出ないルート（WebSocket・include_in_schema=False）が
    CI の版では1本も見えなかった（2026-09-17 に実物の構造を確かめた）。
    """
    内 = SimpleNamespace(routes=[APIWebSocketRoute("/api/pipeline/ws/pipeline"),
                                _R("/api/hidden", {"GET"})])
    包み = SimpleNamespace(original_router=内, include_context=SimpleNamespace(prefix="/api/v1"))
    外 = SimpleNamespace(original_router=SimpleNamespace(routes=[包み]),
                         include_context=SimpleNamespace(prefix=""))
    app = SimpleNamespace(routes=[外], openapi=lambda: {"paths": {}})
    一覧 = 門.ルート一覧(app)
    assert ("WEBSOCKET", "/api/v1/api/pipeline/ws/pipeline") in 一覧
    assert ("GET", "/api/v1/api/hidden") in 一覧


def test_WebSocket_は母集団に入れず盲点に全部載る(門):
    app = SimpleNamespace(routes=[APIWebSocketRoute("/api/x/ws"), APIWebSocketRoute("/ws/outside"),
                                  _R("/api/a", {"GET"})])
    assert 門.母集団(app) == ["/api/a"]
    assert 門.除外の内訳(app) == {"WEBSOCKET": 1}
    assert 門.盲点の一覧(app) == ["WEBSOCKET /api/x/ws"], "語に当たらなくても WebSocket は盲点"


def test_母集団は台帳で対応づけた値でも叩く(門):
    app = SimpleNamespace(routes=[_R("/api/ch/{channel_id}", {"GET"}), _R("/api/ch", {"GET"})])
    値 = {"GET /api/ch/{channel_id}": ["ch-001", "a b/c"]}
    assert 門.母集団(app, 値) == ["/api/ch", "/api/ch/a%20b%2Fc", f"/api/ch/{門.探り値}", "/api/ch/ch-001"]
    assert 門.GETのテンプレート(app) == ["/api/ch/{channel_id}"]


def test_取り出すは道の式で一覧の値を拾う(門):
    本文 = {"channels": [{"id": "ch-001"}, {"id": 2}, {"id": True}, {"id": ""}, {"name": "x"}],
            "names": ["a", "b"]}
    assert 門._取り出す(本文, "$.channels[].id") == ["ch-001", "2"], "真偽値と空は値にしない"
    assert 門._取り出す(本文, "$.names[]") == ["a", "b"]
    assert 門._取り出す(本文, "$.missing[].id") == []
    for 悪い in ("channels[].id", "$.channels[0].id", "$..id"):
        with pytest.raises(ValueError):
            門._取り出す(本文, 悪い)


def test_パス引数の値は台帳の宣言どおりに決まる(門):
    # 同じ ID が2回返っても、上限は別々の値で数える
    既定 = [面("GET /api/ch", {"channels": [{"id": "ch-001"}, {"id": "ch-001"}, {"id": "ch-002"},
                                            {"id": "ch-003"}]}),
            面("GET /api/empty", {"items": []}),
            # 更新時刻の新しい順に返す一覧（並びは環境で変わる）
            面("GET /api/logs", {"files": [{"name": "c.txt"}, {"name": "a.txt"}, {"name": "b.txt"}]})]
    宣言 = {
        "GET /api/ch/{id}": {"from": "GET /api/ch", "take": "$.channels[].id", "limit": 2},
        "GET /api/fmt/{f}": {"values": ["srt", "txt"], "reason": "コードで決まっている書き出し形式"},
        "GET /api/job/{id}": {"none": "ジョブは POST でしか生まれず一覧が無い"},
        "GET /api/empty/{id}": {"from": "GET /api/empty", "take": "$.items[].id"},
        "GET /api/gone/{id}": {"none": "もう無いルートへの宣言（掃除候補）"},
        "GET /api/logs/{name}": {"from": "GET /api/logs", "take": "$.files[].name", "limit": 2,
                                 "order": "name"},
        "GET /api/raw/{name}": {"from": "GET /api/logs", "take": "$.files[].name", "limit": 2},
    }
    テンプレート = ["/api/ch/{id}", "/api/empty/{id}", "/api/fmt/{f}", "/api/job/{id}", "/api/new/{id}",
                  "/api/logs/{name}", "/api/raw/{name}"]
    値, 問題 = 門.パス引数の値(テンプレート, 既定, 台帳(path_values=宣言))
    assert 値["GET /api/ch/{id}"] == ["ch-001", "ch-002"]
    # **並びが環境で変わる一覧は名前順に並べてから上限で切る**（CI の checkout は更新時刻がほぼ同じ）
    assert 値["GET /api/logs/{name}"] == ["a.txt", "b.txt"]
    assert 値["GET /api/raw/{name}"] == ["c.txt", "a.txt"], "order が無ければ一覧の並びのまま"
    assert 値["GET /api/fmt/{f}"] == ["srt", "txt"]
    assert "GET /api/job/{id}" not in 値
    assert 問題["未宣言"] == ["GET /api/new/{id}"]
    assert 問題["値が取れない"] == ["GET /api/empty/{id} ← GET /api/empty $.items[].id"]
    assert 問題["使われていない宣言"] == ["GET /api/gone/{id}"]


def test_観測の本体は条件ごとに点数を変えて比べる(門, tmp_path, monkeypatch, 小さなアプリ):
    """**26周目 G18**: `unscored` の旗を消しても契約が全部通った。子プロセスの中身を通しで回す。

    アプリは点数を無印で返す小さなもの。条件つきの面には「動いた」が付き、
    未採点の条件にだけ `unscored` が立ち、台帳で対応づけた値でも叩く。
    """
    from fastapi import FastAPI

    現在 = {"点": None}
    app = FastAPI()

    @app.get("/api/score")
    def score():
        return {"value": 現在["点"]}

    @app.get("/api/ch")
    def chs():
        return {"channels": [{"id": "ch-001"}]}

    @app.get("/api/ch/{cid}")
    def ch(cid: str):
        return {"id": cid}

    @contextlib.contextmanager
    def 差す(状態):
        現在["点"] = 状態["点"]
        try:
            yield
        finally:
            現在["点"] = None

    進めた: list = []
    (tmp_path / "repo").mkdir()
    monkeypatch.setattr(門, "起こす", lambda _複製: app)
    monkeypatch.setattr(門, "load_ledger", lambda _p=None: 台帳(path_values={
        "GET /api/ch/{cid}": {"from": "GET /api/ch", "take": "$.channels[].id"}}))
    monkeypatch.setattr(門, "実走後の状態", lambda 条件, 点: ({"点": 点}, ("工程", 条件, 点)))
    # 工程の進み方は、状態を差した**あと**に差した状態へ当てる
    monkeypatch.setattr(門, "_工程を進める", lambda 通知: 進めた.append((通知, 現在["点"])))
    monkeypatch.setattr(門, "状態を差す", 差す)
    monkeypatch.setattr(門, "サイドカーを書かせる", lambda _w: [])
    monkeypatch.setattr(門, "漏れたモジュール", lambda _c, _r: [])

    assert 門._観測の本体(tmp_path, tmp_path / "real") == 0
    出た = json.loads((tmp_path / "observed.json").read_text(encoding="utf-8"))
    観測 = {o["face"]: o for o in 出た["観測"]}
    assert "GET /api/ch/ch-001" in 観測, "台帳で対応づけた値で叩いていない"
    for 条件 in (門.合格, 門.不合格, 門.未採点, 門.改善ループ, 門.改善ループ未採点):
        o = 観測[f"GET /api/score［{条件}］"]
        assert o["unscored"] is (条件 in 門._未採点の条件), 条件
        assert o["動いた"]["漏れ"] == ["$.value"], (条件, o["動いた"])
        assert "GET /api/ch/ch-001［" + 条件 + "］" in 観測
    assert "動いた" not in 観測["GET /api/score"], "既定の条件は比べない"
    assert 出た["付帯"]["パス引数"]["未宣言"] == []
    assert len(進めた) == 15, 進めた   # 5条件 × 3回
    assert all(通知[2] == 差した点 for 通知, 差した点 in 進めた), "工程を差した状態の中で進めていない"


# ─────────────────── 本番側の配線（26周目の実在の漏れ） ───────────────────

def test_品質ゲートの工程は採点した印を持つ(門):
    """本番の QualityGateWorker に採点させ、その data が名乗っていることを見る。"""
    _worker, 工程, ctx = 門.品質ゲートを走らせる(92)
    assert 工程.success is True and 工程.data["scored"] is True
    assert ctx.quality_scored is True and ctx.quality_score == 92
    _, 落ちた, _ = 門.品質ゲートを走らせる(85)
    assert 落ちた.success is False and 落ちた.data["scored"] is True


def test_失敗した工程にも_data_を渡す(monkeypatch):
    """**90点未満の品質ゲートは失敗として返るが、見出しには点数が載る。** data を落とさない。"""
    import asyncio

    from agents.pipeline_coordinator import PipelineCoordinator
    from agents.pipeline_types import StageResult
    coord = PipelineCoordinator.__new__(PipelineCoordinator)
    届いた = []
    coord._progress_callback = lambda *a: 届いた.append(a)
    coord._ws_broadcast = None
    w = SimpleNamespace(index=5, name="品質チェック", icon="✅")
    asyncio.run(coord._notify_result(w, StageResult("品質チェック", False, "スコア: 85点", {"scored": True})))
    asyncio.run(coord._notify_result(w, StageResult("品質チェック", False, "落ちた")))
    asyncio.run(coord._notify_result(w, StageResult("品質チェック", True, "スコア: 92点", {"scored": True})))
    assert 届いた == [
        (5, "error", "スコア: 85点", -1, {"scored": True}),
        (5, "error", "落ちた", -1, None),
        (5, "completed", "スコア: 92点", 100, {"scored": True}),
    ]


def test_品質改善のやり直しにも印を載せる():
    """**27周目 E1。** 改善ループの「やり直し」の見出しに点数が載るのに data が無く、

    `GET /api/pipeline/status` の `stages[5].detail = "品質改善 1/3 (前回:0点)"` が無印で出ていた。
    """
    import asyncio

    from agents.pipeline_coordinator import PipelineCoordinator
    coord = PipelineCoordinator.__new__(PipelineCoordinator)
    届いた = []
    coord._progress_callback = lambda *a: 届いた.append(a)
    coord._ws_broadcast = None
    w = SimpleNamespace(index=5, name="品質チェック", icon="✅")
    採点済み = SimpleNamespace(quality_scored=True, quality_score=85)
    未採点 = SimpleNamespace(quality_scored=False, quality_score=0)
    asyncio.run(coord._notify_retry(w, 1, 採点済み))
    asyncio.run(coord._notify_retry(w, 2, 未採点))
    assert [(a[0], a[1], a[4]) for a in 届いた] == [
        (5, "retrying", {"scored": True, "score": 85}),
        (5, "retrying", {"scored": False, "score": 0}),
    ], 届いた
    assert "前回:85点" in 届いた[0][2] and "前回:0点" in 届いた[1][2]


def test_WebSocket_の品質不合格も出所を名乗る():
    """**27周目 E2。** WS は `stages[]` に無い数字を配る（未採点の実走では 0 が流れる）。"""
    import asyncio

    from agents.pipeline_coordinator import PipelineCoordinator
    coord = PipelineCoordinator.__new__(PipelineCoordinator)
    配った = []

    async def 記録(msg):
        配った.append(msg)

    coord._ws_broadcast = 記録
    asyncio.run(coord._notify_quality_blocked(
        SimpleNamespace(quality_scored=False, quality_score=0, quality_feedback=[])))
    assert 配った[0]["type"] == "quality_gate_blocked"
    assert 配った[0]["scored"] is False and 配った[0]["score"] == 0
    coord._ws_broadcast = None
    asyncio.run(coord._notify_quality_blocked(SimpleNamespace(quality_scored=True, quality_score=85,
                                                              quality_feedback=[])))
    assert len(配った) == 1, "配り先が無ければ何もしない"


def test_工程の見出しにも印を写す(monkeypatch):
    pr = importlib.import_module("routers.pipeline_router")
    monkeypatch.setattr(pr, "_pipeline_state", {"stages": [{"status": "pending", "detail": ""}],
                                                "current_stage": 0})
    pr._update_stage(0, "completed", "スコア: 92点", 100, {"scored": True, "score": 92})
    assert pr._pipeline_state["stages"][0]["scored"] is True
    pr._update_stage(0, "running", "やり直し")
    assert pr._pipeline_state["stages"][0]["scored"] is True, "data の無い更新で印を消さない"


def test_新しい実走は前の実走の点数と印を工程に残さない(monkeypatch):
    """**リセットは工程を初期の形に戻す**（27周目の前に自分で発見）。

    `_reset_state` は status と detail しか戻さず、前の実走の data（点数）と、
    `_update_stage` が写した印が、新しい実走の「待機中」の工程に残っていた。
    """
    from routers.pipeline_default_states import get_initial_pipeline_state
    pr = importlib.import_module("routers.pipeline_router")
    monkeypatch.setattr(pr, "_pipeline_state", get_initial_pipeline_state())
    pr._update_stage(5, "completed", "スコア: 96点", 100, {"scored": True, "score": 96})
    assert pr._pipeline_state["stages"][5]["scored"] is True
    pr._reset_state()
    assert pr._pipeline_state["stages"] == get_initial_pipeline_state()["stages"]


def test_実走後の状態は条件ごとに本番が作る(門):
    合, 合の通知 = 門.実走後の状態(門.合格, 97)
    assert 合["result"]["quality_scored"] is True and 合["result"]["quality_score"] == 97
    assert 合の通知[1].success is True and 合の通知[1].data["scored"] is True
    否, 否の通知 = 門.実走後の状態(門.不合格, 81)
    assert 否["result"]["quality_gate_report"]["status"] == "blocked"
    assert 否の通知[1].success is False
    未, 未の通知 = 門.実走後の状態(門.未採点, 73.21)
    assert 未["result"]["quality_scored"] is False and 未["result"]["quality_score"] == 73.21
    assert 未の通知[1].success is False and not 未の通知[1].data, "点を出せなかった工程は data を持たない"
