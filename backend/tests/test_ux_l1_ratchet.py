"""L1 判定結果のラチェットのテスト。

集計値だけを見るラチェットは「1件 PASS が消えて別の1件が PASS になった」を
見逃す。ここでは**項目ごと**に前回の判定と突き合わせる。
"""
import json

import pytest

from backend.ux_verification.executor import L1Report, L1Result, Verdict
from backend.ux_verification.l1_ratchet import L1Ratchet, load_baseline, write_baseline


def _result(item_id, verdict, story="O-1"):
    return L1Result(
        item_id=item_id,
        ux_story=story,
        story_scene="S1",
        description=item_id,
        testid=item_id.lower(),
        verdict=verdict,
        reason="found" if verdict is Verdict.PASS else "not_found",
        evidence="static_source_scan: どこか:1",
    )


def _report(pairs):
    return L1Report(
        persona="owner",
        results=[_result(i, v) for i, v in pairs],
        files_scanned=1,
    )


# --- ベースラインの読み書き ---------------------------------------------------


def test_write_and_load_baseline_roundtrip(tmp_path):
    path = tmp_path / "base.json"
    report = _report([("O1-L1-01", Verdict.PASS), ("O1-L1-02", Verdict.FAIL)])

    write_baseline(report, path)
    base = load_baseline(path)

    assert base["total"] == 2
    assert base["pass"] == 1
    assert base["items"]["O1-L1-01"] == "PASS"
    assert base["items"]["O1-L1-02"] == "FAIL"


def test_baseline_is_written_with_lf_and_trailing_newline(tmp_path):
    """Windows で書いても CRLF を混ぜない（差分がファイル全体になるのを防ぐ）。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)

    raw = path.read_bytes()

    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")


def test_load_baseline_returns_none_when_absent(tmp_path):
    assert load_baseline(tmp_path / "missing.json") is None


# --- 非退行の判定 -------------------------------------------------------------


def test_no_change_is_valid(tmp_path):
    path = tmp_path / "base.json"
    report = _report([("O1-L1-01", Verdict.PASS), ("O1-L1-02", Verdict.FAIL)])
    write_baseline(report, path)

    result = L1Ratchet().check(report, load_baseline(path))

    assert result.valid
    assert result.violations == []


def test_fail_to_pass_is_an_improvement_not_a_violation(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.FAIL)]), path)

    result = L1Ratchet().check(_report([("O1-L1-01", Verdict.PASS)]), load_baseline(path))

    assert result.valid
    assert result.improvements == ["O1-L1-01"]


def test_pass_to_fail_is_a_violation(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)

    result = L1Ratchet().check(_report([("O1-L1-01", Verdict.FAIL)]), load_baseline(path))

    assert not result.valid
    assert [v.kind for v in result.violations] == ["regressed"]
    assert result.violations[0].item_id == "O1-L1-01"


def test_swap_keeping_pass_count_is_still_a_violation(tmp_path):
    """PASS 数は 1 のまま。集計値だけ見るラチェットはこれを見逃す。"""
    path = tmp_path / "base.json"
    write_baseline(
        _report([("O1-L1-01", Verdict.PASS), ("O1-L1-02", Verdict.FAIL)]), path
    )

    result = L1Ratchet().check(
        _report([("O1-L1-01", Verdict.FAIL), ("O1-L1-02", Verdict.PASS)]),
        load_baseline(path),
    )

    assert not result.valid
    assert [v.item_id for v in result.violations] == ["O1-L1-01"]


def test_removing_an_item_is_a_violation(tmp_path):
    """検証項目の削除はルールブック §1.2 で禁止されている。"""
    path = tmp_path / "base.json"
    write_baseline(
        _report([("O1-L1-01", Verdict.PASS), ("O1-L1-02", Verdict.FAIL)]), path
    )

    result = L1Ratchet().check(_report([("O1-L1-01", Verdict.PASS)]), load_baseline(path))

    assert not result.valid
    kinds = {v.kind for v in result.violations}
    assert "removed" in kinds


def test_adding_an_item_is_allowed(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)

    result = L1Ratchet().check(
        _report([("O1-L1-01", Verdict.PASS), ("O1-L1-02", Verdict.FAIL)]),
        load_baseline(path),
    )

    assert result.valid
    assert result.added == ["O1-L1-02"]


def test_missing_baseline_is_valid_but_flagged(tmp_path):
    result = L1Ratchet().check(_report([("O1-L1-01", Verdict.PASS)]), None)

    assert result.valid
    assert result.baseline_missing


def test_report_text_lists_each_regression(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(
        _report([("O1-L1-01", Verdict.PASS), ("O1-L1-02", Verdict.PASS)]), path
    )

    result = L1Ratchet().check(
        _report([("O1-L1-01", Verdict.FAIL), ("O1-L1-02", Verdict.FAIL)]),
        load_baseline(path),
    )

    text = result.to_text()

    assert "O1-L1-01" in text
    assert "O1-L1-02" in text
    assert not result.valid


# --- 更新の安全弁 -------------------------------------------------------------


def test_update_refuses_when_there_is_a_regression(tmp_path):
    """退行したままベースラインを緩めれば、退行が無かったことになる。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)
    regressed = _report([("O1-L1-01", Verdict.FAIL)])

    with pytest.raises(ValueError, match="退行"):
        L1Ratchet().update(regressed, path)

    assert load_baseline(path)["items"]["O1-L1-01"] == "PASS"


def test_update_writes_when_improved(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.FAIL)]), path)

    L1Ratchet().update(_report([("O1-L1-01", Verdict.PASS)]), path)

    assert load_baseline(path)["items"]["O1-L1-01"] == "PASS"


def test_baseline_has_no_timestamp_so_diffs_stay_readable(tmp_path):
    """毎回書き換わる欄があると、実質的な変化が差分に埋もれる。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)

    raw = json.loads(path.read_text(encoding="utf-8"))

    assert "timestamp" not in raw
    assert "measured_at" not in raw
