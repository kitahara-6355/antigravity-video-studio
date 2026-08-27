"""2026-10-16 に終了する 2.5 系への依存が見えること（R1-C5）。

gate-verifier の指摘（2026-08-20・1周目）:

> 2.5 系の可視化は成立していない。`artifact_gate` の check_models() は
> models_used が空のときだけ指摘し、2.5 系の使用・依存は一切見ない。
> 一方 `grep -rn "gemini-2\\.5"` は 64 箇所。今回の実走が触った LLM 経路は
> soul_feedback の1本だけなので、実行記録にはこれらの依存が原理的に現れない。

**実行記録だけでは依存は見えない。** 実走で通らなかった経路にも 2.5 系は
埋まっているので、静的な参照も併せて数える。

あわせて `--audit` の出力に「何と照合したのか」を出す。1周目では
`✅ 入替トリガーに当たっているものはありません` としか出ず、
**実 API に届いたのか、ダミーキーで照合を飛ばしたのかが読み手に分からなかった。**
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend import model_policy


# --- 2.5 系の棚卸し -----------------------------------------------------------

def test_段に2_5系が残っていれば数える():
    report = model_policy.sunset_report(
        tier_models={"batch": "gemini-2.5-flash", "premium": "gemini-3.7-flash"},
        runs=[], source_hits={},
    )

    assert report.tiers_at_risk == {"batch": "gemini-2.5-flash"}


def test_段が2_5系でなければ空():
    report = model_policy.sunset_report(
        tier_models={"premium": "gemini-3.7-flash"}, runs=[], source_hits={})

    assert report.tiers_at_risk == {}


def test_実行記録で実際に2_5系が動いていたら拾う():
    report = model_policy.sunset_report(
        tier_models={}, source_hits={},
        runs=[{"run_id": "r1",
               "models_used": ["gemini-2.5-flash", "local:ffmpeg"]}],
    )

    assert report.runs_at_risk == {"r1": ["gemini-2.5-flash"]}


def test_ローカル工程は危険に数えない():
    report = model_policy.sunset_report(
        tier_models={}, source_hits={},
        runs=[{"run_id": "r1", "models_used": ["local:whisper"]}])

    assert report.runs_at_risk == {}


def test_ソースの参照を数える(tmp_path):
    """**実走で通らない経路にも埋まっている。** 実行記録だけでは見えない。"""
    (tmp_path / "a.py").write_text(
        'MODEL = "gemini-2.5-flash"\nOTHER = "gemini-3.7-flash"\n',
        encoding="utf-8")
    (tmp_path / "b.py").write_text('x = "gemini-2.5-pro"\n', encoding="utf-8")
    sub = tmp_path / "tests"
    sub.mkdir()
    (sub / "test_c.py").write_text('y = "gemini-2.5-flash"\n', encoding="utf-8")

    hits = model_policy.scan_sunset_references(tmp_path)

    assert hits == {"a.py": 1, "b.py": 1}, "テストを数に入れている"


def test_ソースに無ければ0件(tmp_path):
    (tmp_path / "a.py").write_text('M = "gemini-3.7-flash"\n', encoding="utf-8")

    assert model_policy.scan_sunset_references(tmp_path) == {}


def test_期日までの残り日数が出る():
    import datetime as _dt

    report = model_policy.sunset_report(
        tier_models={}, runs=[], source_hits={},
        today=_dt.date(2026, 10, 6))

    assert report.days_left == 10


def test_期日を過ぎたら負にならず0():
    import datetime as _dt

    report = model_policy.sunset_report(
        tier_models={}, runs=[], source_hits={},
        today=_dt.date(2026, 11, 1))

    assert report.days_left == 0


# --- 出力 ---------------------------------------------------------------------

def test_依存があれば件数と場所が出る():
    report = model_policy.sunset_report(
        tier_models={}, runs=[],
        source_hits={"backend/agents/director.py": 3,
                     "backend/core/plugin.py": 2})

    text = model_policy.format_sunset(report)

    assert "5 箇所" in text
    assert "backend/agents/director.py" in text


def test_依存が0でも黙らない():
    """**不在を成功にしない。** 数えた結果 0 なのか、数えていないのか。"""
    text = model_policy.format_sunset(
        model_policy.sunset_report(tier_models={}, runs=[], source_hits={}))

    assert "0 箇所" in text


def test_実行記録が0件なら確かめられないと言う():
    """記録が無いのを「2.5 系を使っていない」と読ませない。"""
    text = model_policy.format_sunset(
        model_policy.sunset_report(tier_models={}, runs=[], source_hits={}))

    assert "実行記録がありません" in text


# --- --audit が何と照合したかを出す -------------------------------------------

def test_auditの出力に照合先が出る(monkeypatch):
    monkeypatch.setattr(model_policy, "live_model_ids",
                        lambda: ({"gemini-3.7-flash"} | {f"m{i}" for i in range(49)}, ""))

    text = model_policy.format_audit(*model_policy.audit())

    assert "50 件" in text, "実 API と照合した件数が出ていない"


def test_照合できなかったら理由が出る(monkeypatch):
    monkeypatch.setattr(
        model_policy, "live_model_ids",
        lambda: (set(), "実 API キーがありません（ダミーキー）"))

    text = model_policy.format_audit(*model_policy.audit())

    assert "ダミーキー" in text
    assert "照合できていません" in text


# --- 走査範囲 -----------------------------------------------------------------
#
# gate-verifier 2周目の指摘: 走査根が backend/ 配下だけで、
# agents/orchestration/orchestrator.py（4）・.claude/hooks/billing_gate.py（1）・
# scratch/run_weakness_orchestrator.py（1）の**計6箇所が数から漏れていた**。
# 可視化の成立は妨げないが、報告する件数が過少になる。


def test_リポジトリ全体を走査する(tmp_path):
    """**backend/ の外にも埋まっている。** 走査範囲が狭いと件数が過少になる。"""
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "a.py").write_text(
        'M = "gemini-2.5-flash"\n', encoding="utf-8")
    outside = tmp_path / "agents" / "orchestration"
    outside.mkdir(parents=True)
    (outside / "orchestrator.py").write_text(
        'M = "gemini-2.5-pro"\n', encoding="utf-8")
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "billing_gate.py").write_text(
        'M = "gemini-2.5-flash"\n', encoding="utf-8")

    hits = model_policy.scan_sunset_references(tmp_path)

    assert set(hits) == {
        "backend/a.py",
        "agents/orchestration/orchestrator.py",
        ".claude/hooks/billing_gate.py",
    }


def test_既定の走査根はリポジトリ直下():
    """`--sunset` を引数なしで呼んだときに backend/ だけを見ていないこと。"""
    hits = model_policy.scan_sunset_references()

    assert any(not name.startswith("backend/") for name in hits), (
        f"backend/ の外を走査していない: {sorted(hits)[:5]}"
    )


def test_フロントやビルド成果物は数えない(tmp_path):
    """node_modules や .venv を数に入れると件数が意味を失う。"""
    for junk in ("node_modules", ".venv", "__pycache__"):
        d = tmp_path / junk
        d.mkdir()
        (d / "x.py").write_text('M = "gemini-2.5-flash"\n', encoding="utf-8")
    (tmp_path / "real.py").write_text(
        'M = "gemini-2.5-flash"\n', encoding="utf-8")

    assert model_policy.scan_sunset_references(tmp_path) == {"real.py": 1}


def test_sunset_reportの既定も走査根を狭めない():
    """CLI が通る経路。`scan_sunset_references()` だけ直しても意味が無い。

    実際 1 回目の修正は `sunset_report` が `backend/` を明示的に渡していて、
    **`--sunset` の件数が変わらなかった。**
    """
    report = model_policy.sunset_report(tier_models={}, runs=[])

    # backend/ の外に実在する参照。**これが数に入っていること。**
    for outside in (".claude/hooks/billing_gate.py",
                    "agents/orchestration/orchestrator.py",
                    "scratch/run_weakness_orchestrator.py"):
        assert outside in report.source_hits, (
            f"{outside} が数に入っていない（走査根が backend/ に狭まっている）"
        )


# --- 本番と到達不能を区別する（R1.5-C6・2026-08-28）---------------------------
#
# 条件文: 「`--sunset` が段・実行記録・**本番モジュール**のいずれにも 2.5 系が
# 無いことを示し、残った参照（テスト・アーカイブ・到達不能な経路）は本番と
# 区別して数えられている。**区別できないうちは FAIL する**」
#
# 直す前は 71 箇所を1つの数として出すだけで、本番かどうかを言えなかった。


def test_本番の実行経路を静的に辿れる():
    """**本線の入口から import を辿って「本番」を定義する。**

    「本番かどうか」を人の感覚で決めない。`agents.pipeline_coordinator`
    （本線）と `main`（API）から辿れるものを本番とする。
    """
    from backend.model_policy import reachable_modules

    到達 = reachable_modules()

    assert "backend/agents/pipeline_coordinator.py" in 到達
    assert "backend/model_governance.py" in 到達
    # アーカイブは本線から辿れない
    assert not any("archives/" in p for p in 到達), [p for p in 到達 if "archives/" in p][:3]


def test_2_5系の参照を本番と到達不能に分ける():
    from backend.model_policy import classify_sunset_references

    分類 = classify_sunset_references()

    assert set(分類) == {"production_code", "production_doc", "unreachable"}
    # 分類の合計が走査の合計と一致すること（**取りこぼしを作らない**）
    from backend.model_policy import scan_sunset_references
    合計 = sum(scan_sunset_references().values())
    分類合計 = sum(sum(v.values()) for v in 分類.values())
    assert 分類合計 == 合計, (分類合計, 合計)


def test_文書の中の2_5系は依存ではない(tmp_path):
    """**docstring の例と、実際に使われる既定値を混ぜない。**

    `cost_guard.py` の 2 箇所は使い方を示す docstring で、依存ではない。
    """
    from backend.model_policy import split_code_and_doc

    src = '''"""使い方: guard.before_call("gemini-2.5-flash")"""
既定 = "gemini-2.5-flash"
# gemini-2.5-flash はコメント
'''
    f = tmp_path / "x.py"
    f.write_text(src, encoding="utf-8")

    コード, 文書 = split_code_and_doc(f)

    assert コード == 1, (コード, 文書)   # 代入だけが依存
    assert 文書 == 2                      # docstring とコメント


def test_本番にコード上の2_5系が残っていたらFAILする():
    """**区別できないうちは FAIL する**（条件文）。"""
    from backend.model_policy import sunset_gate

    残っている = sunset_gate({"production_code": {"backend/x.py": 1},
                              "production_doc": {}, "unreachable": {}})
    消えた = sunset_gate({"production_code": {},
                          "production_doc": {"backend/y.py": 3},
                          "unreachable": {"scratch/z.py": 9}})

    assert 残っている, "本番にコード参照が残っていたら違反を出すこと"
    assert 消えた == [], 消えた
