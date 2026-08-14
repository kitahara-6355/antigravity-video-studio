"""UI と API の接続のラチェット（P4 C-4）。

C-4 が名指しした4つ — 走査0件で緑 / 呼び出しの削除 / unresolved の握りつぶし /
宣言の差し替え — が**実際に落ちる**ことを、コピーに対して確かめる。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.ux_verification.ui_api import FetchSite, UiApiReport, Verdict
from backend.ux_verification.ui_api_ratchet import (
    BASELINE,
    DECLARATION_KEYS,
    UiApiRatchet,
    load_baseline,
    passing_verdicts,
    site_key,
    write_baseline,
)


def _site(path="/api/x", method="GET", verdict=Verdict.MATCHED,
          file="src/App.jsx", declared="routers/demo.py:10") -> FetchSite:
    return FetchSite(file, 1, path, path, method, verdict, "", declared)


def _report(*sites, unreachable=()) -> UiApiReport:
    return UiApiReport(list(sites), files_scanned=1, endpoints_scanned=1,
                       unreachable=list(unreachable))


def _pinned(tmp_path: Path, report: UiApiReport) -> dict:
    write_baseline(report, tmp_path / "baseline.json")
    return load_baseline(tmp_path / "baseline.json")


# --- 1. 走査0件・ベースライン不在で緑にしない -------------------------------


def test_a_missing_baseline_is_a_failure_not_a_pass():
    result = UiApiRatchet().check(_report(_site()), None)

    assert not result.valid
    assert result.baseline_missing


def test_the_cli_fails_when_no_call_was_read(monkeypatch, capsys):
    from backend.ux_verification import ui_api_ratchet as mod

    monkeypatch.setattr(mod.UiApiExecutor, "for_repo",
                        classmethod(lambda cls: _Stub(_report())))

    assert mod.main(["--ratchet"]) == 1
    assert "1件も読み取れませんでした" in capsys.readouterr().out


class _Stub:
    def __init__(self, report):
        self._report = report

    def run(self):
        return self._report


# --- 2. 呼び出しの削除 --------------------------------------------------------


def test_a_deleted_call_is_a_violation(tmp_path):
    baseline = _pinned(tmp_path, _report(_site("/api/a"), _site("/api/b")))

    result = UiApiRatchet().check(_report(_site("/api/a")), baseline)

    assert not result.valid
    assert [v.kind for v in result.violations] == ["removed"]
    assert "/api/b" in result.violations[0].key


def test_deleting_every_call_does_not_look_like_no_change(tmp_path):
    baseline = _pinned(tmp_path, _report(_site("/api/a")))

    result = UiApiRatchet().check(_report(), baseline)

    assert not result.valid
    assert {v.kind for v in result.violations} == {"removed"}


# --- 3. unresolved の握りつぶし ----------------------------------------------


def test_widening_the_passing_verdicts_is_a_violation(tmp_path):
    """PASS 扱いの判定を増やすのは、呼び出しを1件も見ずに分かる弱化。"""
    baseline = _pinned(tmp_path, _report(_site()))
    baseline["passing_verdicts"] = ["matched"]

    import backend.ux_verification.ui_api_ratchet as mod
    original = mod.passing_verdicts
    mod.passing_verdicts = lambda: ["matched", "unresolved_url"]
    try:
        result = mod.UiApiRatchet().check(_report(_site()), baseline)
    finally:
        mod.passing_verdicts = original

    assert not result.valid
    assert [v.kind for v in result.violations] == ["semantics_widened"]


def test_a_call_that_stops_matching_is_a_violation(tmp_path):
    baseline = _pinned(tmp_path, _report(_site("/api/a")))

    result = UiApiRatchet().check(
        _report(_site("/api/a", verdict=Verdict.UNRESOLVED_METHOD)), baseline)

    assert not result.valid
    assert [v.kind for v in result.violations] == ["weakened"]


def test_the_passing_verdicts_pinned_today_are_exactly_matched():
    assert passing_verdicts() == ["matched"]


@pytest.mark.parametrize("field_name", [
    "scanned_files", "scanned_forms", "global_receivers", "mismatch_verdicts",
])
def test_any_change_to_the_scan_closure_is_a_violation(tmp_path, field_name):
    """**どちらに動いても違反。** 増えれば読めなかったものが読めたことになり、
    減れば見えていたものが見えなくなる。片方向だけ見ると縮小が素通りする。"""
    for mutate in (lambda v: [*v, "余計なもの"], lambda v: v[:-1]):
        baseline = _pinned(tmp_path, _report(_site()))
        baseline["scan_boundary"][field_name] = mutate(
            baseline["scan_boundary"][field_name])

        result = UiApiRatchet().check(_report(_site()), baseline)

        assert not result.valid, field_name
        assert [v.kind for v in result.violations] == ["scan_widened"], field_name


def test_replacing_an_unscannable_pattern_body_is_a_violation(tmp_path):
    """キー名だけ固定していると、正規表現を無効なものに差し替えるだけで
    その形の検出が黙って消える。**本体まで固定する。**"""
    baseline = _pinned(tmp_path, _report(_site()))
    forms = baseline["scan_boundary"]["unscanned_forms"]
    name = next(iter(forms))
    forms[name] = "(?!x)x"          # 絶対に当たらない正規表現

    result = UiApiRatchet().check(_report(_site()), baseline)

    assert not result.valid
    assert [v.kind for v in result.violations] == ["scan_widened"]


def test_the_unscannable_forms_are_pinned_by_pattern_not_by_name():
    from backend.ux_verification.ui_api_ratchet import scan_boundary

    forms = scan_boundary()["unscanned_forms"]

    assert isinstance(forms, dict)
    assert all(isinstance(v, str) and v for v in forms.values())


# --- 4. 宣言の差し替え --------------------------------------------------------


def test_the_same_call_hitting_a_different_declaration_is_a_violation(tmp_path):
    """パスもメソッドも変えずに当たり先だけ入れ替わる形を捕まえる。"""
    baseline = _pinned(tmp_path, _report(_site(declared="routers/a.py:10")))

    result = UiApiRatchet().check(
        _report(_site(declared="routers/b.py:99")), baseline)

    assert not result.valid
    assert [v.kind for v in result.violations] == ["substituted"]


def test_update_baseline_refuses_a_substitution(tmp_path):
    path = tmp_path / "baseline.json"
    write_baseline(_report(_site(declared="routers/a.py:10")), path)

    with pytest.raises(ValueError, match="宣言の差し替え"):
        UiApiRatchet().update(_report(_site(declared="routers/b.py:99")), path)


def test_redeclare_records_the_reason(tmp_path):
    path = tmp_path / "baseline.json"
    write_baseline(_report(_site(declared="routers/a.py:10")), path)

    UiApiRatchet().redeclare(_report(_site(declared="routers/b.py:99")), path,
                             "ルーターを分割したため")

    history = load_baseline(path)["redeclarations"]
    assert len(history) == 1
    assert history[0]["reason"] == "ルーターを分割したため"
    assert history[0]["after"] == "routers/b.py:99"


def test_redeclare_needs_a_reason(tmp_path):
    path = tmp_path / "baseline.json"
    write_baseline(_report(_site()), path)

    with pytest.raises(ValueError, match="理由"):
        UiApiRatchet().redeclare(_report(_site()), path, "   ")


def test_redeclare_does_not_swallow_a_deletion(tmp_path):
    path = tmp_path / "baseline.json"
    write_baseline(_report(_site("/api/a"), _site("/api/b")), path)

    with pytest.raises(ValueError, match="削除"):
        UiApiRatchet().redeclare(_report(_site("/api/a")), path, "理由")


# --- 記録そのものを守る -------------------------------------------------------


def test_a_baseline_missing_a_pinned_key_is_a_violation(tmp_path):
    """欄を消せば検査が消える、を塞ぐ。P3 C-4 の3回目の指摘と同型。"""
    for key in DECLARATION_KEYS:
        baseline = _pinned(tmp_path, _report(_site()))
        baseline.pop(key)

        result = UiApiRatchet().check(_report(_site()), baseline)

        assert not result.valid, key
        assert [v.kind for v in result.violations] == ["tampered"], key


def test_every_pinned_key_is_actually_read_by_check(tmp_path):
    """書いてあるのに読まれない欄を作らない（P3 C-4 の残余そのもの）。"""
    baseline = _pinned(tmp_path, _report(_site()))

    assert set(baseline) - {"method", "redeclarations"} == set(DECLARATION_KEYS)


def test_a_new_call_must_be_pinned_before_it_passes(tmp_path):
    baseline = _pinned(tmp_path, _report(_site("/api/a")))

    result = UiApiRatchet().check(
        _report(_site("/api/a"), _site("/api/b")), baseline)

    assert not result.valid
    assert [v.kind for v in result.violations] == ["unpinned_new"]


def test_making_a_file_unreachable_does_not_pass_silently(tmp_path):
    """到達不能にすれば判定の対象から外れる。外れたことを黙らせない。"""
    baseline = _pinned(tmp_path, _report(_site("/api/a")))

    result = UiApiRatchet().check(
        _report(_site("/api/a"), unreachable=["src/Orphan.jsx:5"]), baseline)

    assert not result.valid
    assert [v.kind for v in result.violations] == ["unreachable_grew"]


def test_emptying_the_declarations_does_not_disable_the_substitution_check(tmp_path):
    """空にすれば検査が消える、を塞ぐ。「空＝無検査」は fail-open。"""
    baseline = _pinned(tmp_path, _report(_site(declared="routers/a.py:10")))
    baseline["declarations"] = {k: "" for k in baseline["declarations"]}

    result = UiApiRatchet().check(_report(_site(declared="routers/a.py:10")),
                                  baseline)

    assert not result.valid
    assert [v.kind for v in result.violations] == ["tampered"]


def test_widening_passed_requires_widening_the_semantics_table():
    """PASS 判定の出どころが1つであること。表の外で広げられないこと。"""
    from backend.ux_verification.ui_api import VERDICT_SEMANTICS, Verdict

    for verdict in Verdict:
        site = _site(verdict=verdict)
        assert site.passed is (VERDICT_SEMANTICS[verdict]["PASS"] == "yes"), verdict


def test_deleting_a_nested_scan_boundary_key_is_a_violation(tmp_path):
    """入れ子の欄を1つ消せばその欄だけ無検査になる、を塞ぐ。"""
    baseline = _pinned(tmp_path, _report(_site()))
    baseline["scan_boundary"].pop("global_receivers")

    result = UiApiRatchet().check(_report(_site()), baseline)

    assert not result.valid
    assert [v.kind for v in result.violations] == ["tampered"]


def test_blanking_the_declaration_on_the_executor_side_is_a_violation(tmp_path):
    """ベースライン側だけ塞いでも、実行側に同じ「空＝無検査」が残る。"""
    baseline = _pinned(tmp_path, _report(_site(declared="routers/a.py:10")))

    result = UiApiRatchet().check(_report(_site(declared="")), baseline)

    assert not result.valid
    assert [v.kind for v in result.violations] == ["substituted"]


def test_an_unparsable_baseline_is_treated_as_missing(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text("{ not json", encoding="utf-8")

    assert load_baseline(path) is None


def test_the_site_key_ignores_line_numbers():
    a = FetchSite("src/App.jsx", 10, "x", "/api/x", "GET", Verdict.MATCHED)
    b = FetchSite("src/App.jsx", 99, "x", "/api/x", "GET", Verdict.MATCHED)

    assert site_key(a) == site_key(b)


# --- 実物 ---------------------------------------------------------------------


def test_the_repository_baseline_exists_and_pins_every_key():
    baseline = load_baseline(BASELINE)

    assert baseline is not None, "リポジトリのベースラインが無い"
    for key in DECLARATION_KEYS:
        assert key in baseline, key
    assert baseline["passing_verdicts"] == ["matched"]
    assert json.dumps(baseline)  # 直列化できる


# --- 呼び出し口への移行（P5） -------------------------------------------------
#
# `--migrate` は削除を受理する唯一の経路。**受理条件を緩めれば、そこが
# 「呼び出しを消して緑にする」抜け道になる。** 条件そのものを固定する。


_CATALOGUE = "src/gateway/endpoints.js"


def test_a_migration_is_accepted_when_the_catalogue_reaches_the_same_declaration(tmp_path):
    """呼び出しは消えたが、同じ宣言にカタログ経由で届いている。"""
    before = _report(_site(file="src/App.jsx", declared="routers/demo.py:10"))
    _pinned(tmp_path, before)
    after = _report(_site(file=_CATALOGUE, declared="routers/demo.py:10"))

    UiApiRatchet().migrate(after, tmp_path / "baseline.json", "P5 の移行")

    result = UiApiRatchet().check(after, load_baseline(tmp_path / "baseline.json"))
    assert result.valid


def test_a_migration_is_refused_when_the_catalogue_does_not_reach_it(tmp_path):
    """**届いていない削除は移行ではない。** ここを緩めると削除が通る。"""
    before = _report(_site(file="src/App.jsx", declared="routers/demo.py:10"),
                     _site(path="/api/y", file="src/App.jsx",
                           declared="routers/demo.py:20"))
    _pinned(tmp_path, before)
    # `/api/y` はカタログにも無い＝ただ消えた
    after = _report(_site(file=_CATALOGUE, declared="routers/demo.py:10"))

    with pytest.raises(ValueError, match="カタログに届いていない削除"):
        UiApiRatchet().migrate(after, tmp_path / "baseline.json", "P5 の移行")


def test_a_migration_needs_a_reason(tmp_path):
    _pinned(tmp_path, _report(_site(file="src/App.jsx")))
    after = _report(_site(file=_CATALOGUE))

    with pytest.raises(ValueError, match="理由が要ります"):
        UiApiRatchet().migrate(after, tmp_path / "baseline.json", "   ")


def test_a_migration_does_not_launder_a_weakened_verdict(tmp_path):
    """**移行のついでに判定を弱められない。** 削除以外の違反は受理しない。"""
    _pinned(tmp_path, _report(
        _site(file="src/App.jsx", declared="routers/demo.py:10"),
        _site(path="/api/y", file="src/Other.jsx", declared="routers/demo.py:20")))
    after = _report(
        _site(file=_CATALOGUE, declared="routers/demo.py:10"),
        # 同じ鍵のまま matched → not_declared に落ちた
        _site(path="/api/y", file="src/Other.jsx", verdict=Verdict.NOT_DECLARED,
              declared=""))

    with pytest.raises(ValueError, match="移行以外の違反"):
        UiApiRatchet().migrate(after, tmp_path / "baseline.json", "P5 の移行")


def test_a_migration_is_recorded_in_the_baseline_diff(tmp_path):
    """**受理した移行は必ず差分に出す。** 黙って消えた、を残さない。"""
    _pinned(tmp_path, _report(_site(file="src/App.jsx",
                                    declared="routers/demo.py:10")))
    after = _report(_site(file=_CATALOGUE, declared="routers/demo.py:10"))

    UiApiRatchet().migrate(after, tmp_path / "baseline.json", "P5 の移行")

    recorded = load_baseline(tmp_path / "baseline.json")["migrations"]
    assert [m["key"] for m in recorded] == ["src/App.jsx|GET|/api/x"]
    assert recorded[0]["reason"] == "P5 の移行"
    assert recorded[0]["now_via"] == "routers/demo.py:10"


def test_updating_the_baseline_keeps_the_migration_history(tmp_path):
    """履歴が `--update-baseline` で消えたら、移行の記録は歯止めにならない。"""
    _pinned(tmp_path, _report(_site(file="src/App.jsx",
                                    declared="routers/demo.py:10")))
    after = _report(_site(file=_CATALOGUE, declared="routers/demo.py:10"))
    UiApiRatchet().migrate(after, tmp_path / "baseline.json", "P5 の移行")

    grown = _report(_site(file=_CATALOGUE, declared="routers/demo.py:10"),
                    _site(path="/api/new", file=_CATALOGUE,
                          declared="routers/demo.py:30"))
    UiApiRatchet().update(grown, tmp_path / "baseline.json")

    assert load_baseline(tmp_path / "baseline.json")["migrations"]


# --- 読めなかった記述の解消（--resolve） --------------------------------------
#
# `unscanned_form` / `unresolved_url` は「ここに読めないものがある」という
# FAIL の印であって、突き合った呼び出しではない。コードごと直して消すのは
# **改善**なのに `removed` として一律に拒むと、読めない構文を永久に残すしか
# なくなる。**ただし matched の削除を紛れ込ませてはいけない。**


def test_resolving_an_unreadable_site_is_accepted(tmp_path):
    before = _report(_site(verdict=Verdict.UNSCANNED_FORM, declared=""),
                     _site(path="/api/y", declared="routers/demo.py:20"))
    _pinned(tmp_path, before)
    after = _report(_site(path="/api/y", declared="routers/demo.py:20"))

    UiApiRatchet().resolve(after, tmp_path / "baseline.json", "構文を直した")

    assert UiApiRatchet().check(
        after, load_baseline(tmp_path / "baseline.json")).valid


def test_resolving_refuses_to_delete_a_matched_call(tmp_path):
    """**突き合っていた呼び出しの削除は受理しない。** ここが緩めば抜け道になる。"""
    _pinned(tmp_path, _report(_site(declared="routers/demo.py:10"),
                              _site(path="/api/y", declared="routers/demo.py:20")))
    after = _report(_site(path="/api/y", declared="routers/demo.py:20"))

    with pytest.raises(ValueError, match="--resolve では受理しません"):
        UiApiRatchet().resolve(after, tmp_path / "baseline.json", "消したい")


def test_resolving_needs_a_reason(tmp_path):
    _pinned(tmp_path, _report(_site(verdict=Verdict.UNSCANNED_FORM, declared="")))
    after = _report(_site(path="/api/y", declared="routers/demo.py:20"))

    with pytest.raises(ValueError, match="理由が要ります"):
        UiApiRatchet().resolve(after, tmp_path / "baseline.json", "  ")


def test_resolving_is_recorded_in_the_baseline_diff(tmp_path):
    _pinned(tmp_path, _report(_site(verdict=Verdict.UNSCANNED_FORM, declared=""),
                              _site(path="/api/y", declared="routers/demo.py:20")))
    after = _report(_site(path="/api/y", declared="routers/demo.py:20"))

    UiApiRatchet().resolve(after, tmp_path / "baseline.json", "構文を直した")

    recorded = load_baseline(tmp_path / "baseline.json")["resolutions"]
    assert [r["was"] for r in recorded] == ["unscanned_form"]
    assert recorded[0]["reason"] == "構文を直した"


def test_updating_the_baseline_keeps_the_resolution_history(tmp_path):
    _pinned(tmp_path, _report(_site(verdict=Verdict.UNSCANNED_FORM, declared=""),
                              _site(path="/api/y", declared="routers/demo.py:20")))
    after = _report(_site(path="/api/y", declared="routers/demo.py:20"))
    UiApiRatchet().resolve(after, tmp_path / "baseline.json", "構文を直した")

    grown = _report(_site(path="/api/y", declared="routers/demo.py:20"),
                    _site(path="/api/z", declared="routers/demo.py:30"))
    UiApiRatchet().update(grown, tmp_path / "baseline.json")

    assert load_baseline(tmp_path / "baseline.json")["resolutions"]
