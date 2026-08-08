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
