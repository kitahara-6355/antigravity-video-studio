"""L1 判定結果のラチェットのテスト。

集計値だけを見るラチェットは「1件 PASS が消えて別の1件が PASS になった」を
見逃す。ここでは**項目ごと**に前回の判定と突き合わせる。
"""
import json

import pytest

from backend.ux_verification.executor import L1Report, L1Result, Verdict
from backend.ux_verification.l1_ratchet import L1Ratchet, load_baseline, write_baseline


def _result(item_id, verdict, story="O-1", reason=None):
    return L1Result(
        item_id=item_id,
        ux_story=story,
        story_scene="S1",
        description=item_id,
        testid=item_id.lower(),
        verdict=verdict,
        reason=reason or ("found" if verdict is Verdict.PASS else "not_found"),
        evidence="static_source_scan: どこか:1",
    )


def _report(pairs):
    """(item_id, verdict) か (item_id, verdict, reason) の並び。"""
    return L1Report(
        persona="owner",
        results=[_result(*p) if len(p) == 2 else _result(p[0], p[1], reason=p[2])
                 for p in pairs],
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


# --- ベースラインの不在を成功にしない ------------------------------------------


def test_cli_fails_when_baseline_is_missing(tmp_path, monkeypatch):
    """ベースラインを消すだけでラチェットを無効化できてはいけない。

    退行を抱えたままファイルを1つ消せば緑になる、という抜け道を塞ぐ。
    """
    from backend.ux_verification import executor as ex

    monkeypatch.setattr(ex, "_project_root", lambda: _repo_root())
    monkeypatch.setattr(
        "backend.ux_verification.l1_ratchet.baseline_path",
        lambda persona: tmp_path / "does_not_exist.json",
    )

    assert ex.main(["--persona", "owner", "--ratchet"]) == 1


def test_committed_baseline_exists_and_covers_every_owner_l1_item():
    """コミット済みベースラインが消えていないことを固定する。"""
    from backend.ux_verification.executor import L1Executor
    from backend.ux_verification.l1_ratchet import baseline_path, load_baseline

    base = load_baseline(baseline_path("owner"))

    assert base is not None, "l1_owner_baseline.json がコミットされていない"
    report = L1Executor.for_repo().run("owner")
    assert set(base["items"]) == {r.item_id for r in report.results}


def _repo_root():
    from pathlib import Path
    return Path(__file__).resolve().parents[2]


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


# --- 判定の厳格化 -------------------------------------------------------------
#
# ラチェットは「実装が退行していないこと」を守る道具で、「測り方を厳しくしては
# いけない」という意味ではない。だが両者はどちらも PASS の減少として現れるので、
# 機械的に区別できないと「厳しくした」と言えば何でも通せてしまう。


def test_tighten_accepts_a_regression_caused_by_a_stricter_judgment(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)
    stricter = _report([("O1-L1-01", Verdict.FAIL, "field_not_found")])

    L1Ratchet().tighten(stricter, path, "レスポンス内容まで見るようにした")

    assert load_baseline(path)["items"]["O1-L1-01"] == "FAIL"


def test_tighten_refuses_a_real_regression(tmp_path):
    """実体が消えた（not_found）のは厳格化では説明できない。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)
    broken = _report([("O1-L1-01", Verdict.FAIL, "not_found")])

    with pytest.raises(ValueError, match="厳格化では説明できない"):
        L1Ratchet().tighten(broken, path, "厳しくしたことにする")

    assert load_baseline(path)["items"]["O1-L1-01"] == "PASS"


def test_tighten_refuses_when_an_item_disappeared(tmp_path):
    """項目そのものが消えるのは厳格化ではない。消せば FAIL は出なくなる。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS),
                            ("O1-L1-02", Verdict.PASS)]), path)
    fewer = _report([("O1-L1-01", Verdict.PASS)])

    with pytest.raises(ValueError, match="厳格化では説明できない"):
        L1Ratchet().tighten(fewer, path, "整理した")


def test_tighten_requires_a_reason(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)
    stricter = _report([("O1-L1-01", Verdict.FAIL, "field_not_found")])

    with pytest.raises(ValueError, match="理由は必須"):
        L1Ratchet().tighten(stricter, path, "   ")


def test_tighten_records_the_reason_in_the_baseline(tmp_path):
    """理由が残らなければ、次に見た人には退行と区別が付かない。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)
    stricter = _report([("O1-L1-01", Verdict.FAIL, "field_not_found")])

    L1Ratchet().tighten(stricter, path, "レスポンス内容まで見るようにした")

    history = load_baseline(path)["tightenings"]
    assert history[-1]["reason"] == "レスポンス内容まで見るようにした"
    assert history[-1]["items"] == ["O1-L1-01"]


def test_tightening_history_survives_a_later_update(tmp_path):
    """締め直すたびに履歴が消えると、厳格化した事実が1回で失われる。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)
    L1Ratchet().tighten(_report([("O1-L1-01", Verdict.FAIL, "field_not_found")]),
                        path, "厳しくした")

    L1Ratchet().update(_report([("O1-L1-01", Verdict.PASS)]), path)

    assert load_baseline(path)["tightenings"][-1]["reason"] == "厳しくした"


def test_ratchet_still_blocks_the_same_regression_without_tighten(tmp_path):
    """--tighten を使わなければ、厳格化由来でも普通に違反として止まる。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)
    stricter = _report([("O1-L1-01", Verdict.FAIL, "field_not_found")])

    assert L1Ratchet().check(stricter, load_baseline(path)).valid is False
