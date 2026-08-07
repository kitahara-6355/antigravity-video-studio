"""L1 判定結果のラチェットのテスト。

集計値だけを見るラチェットは「1件 PASS が消えて別の1件が PASS になった」を
見逃す。ここでは**項目ごと**に前回の判定と突き合わせる。
"""
import json

import pytest

from backend.ux_verification.executor import L1Report, L1Result, Verdict
from backend.ux_verification.l1_ratchet import L1Ratchet, load_baseline, write_baseline


def _result(item_id, verdict, story="O-1", reason=None, declaration=None):
    return L1Result(
        item_id=item_id,
        ux_story=story,
        story_scene="S1",
        description=item_id,
        testid=item_id.lower(),
        verdict=verdict,
        reason=reason or ("found" if verdict is Verdict.PASS else "not_found"),
        evidence="static_source_scan: どこか:1",
        declaration=declaration if declaration is not None else {},
    )


def _report(pairs):
    """(item_id, verdict) か (item_id, verdict, reason) の並び。"""
    return L1Report(
        persona="owner",
        results=[_result(*p) if len(p) == 2 else _result(p[0], p[1], reason=p[2])
                 for p in pairs],
        files_scanned=1,
    )


def _declared(item_id, verdict, reason, declaration):
    """宣言内容つきの1項目レポート。"""
    return L1Report(
        persona="owner",
        results=[_result(item_id, verdict, reason=reason, declaration=declaration)],
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


def test_adding_an_item_must_be_pinned(tmp_path):
    """項目の追加は歓迎するが、ピンするまでは緑にしない。

    以前は `added` として黙って通していた。だがベースラインの `items` から
    1行消せば既存項目も「新しい項目」に化けるので、そこが穴になっていた
    （退行も宣言の差し替えも `added` に落ちて違反ゼロで通った）。
    """
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)

    result = L1Ratchet().check(
        _report([("O1-L1-01", Verdict.PASS), ("O1-L1-02", Verdict.FAIL)]),
        load_baseline(path),
    )

    assert not result.valid
    assert [v.kind for v in result.violations] == ["unpinned_new"]
    assert result.added == ["O1-L1-02"]


def test_update_pins_a_newly_added_item(tmp_path):
    """新しい項目のピンは --update-baseline でできる（理由は要らない）。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)
    grown = _report([("O1-L1-01", Verdict.PASS), ("O1-L1-02", Verdict.FAIL)])

    L1Ratchet().update(grown, path)

    assert L1Ratchet().check(grown, load_baseline(path)).valid


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

    # 内容判定を保ったまま直したので、これは普通の改善（弱化ではない）
    L1Ratchet().update(_report([("O1-L1-01", Verdict.PASS, "field_found")]), path)

    assert load_baseline(path)["tightenings"][-1]["reason"] == "厳しくした"


def test_ratchet_still_blocks_the_same_regression_without_tighten(tmp_path):
    """--tighten を使わなければ、厳格化由来でも普通に違反として止まる。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS)]), path)
    stricter = _report([("O1-L1-01", Verdict.FAIL, "field_not_found")])

    assert L1Ratchet().check(stricter, load_baseline(path)).valid is False


def test_tighten_refuses_when_content_verified_pass_regresses(tmp_path):
    """`field_found` → `field_not_found` は厳格化ではない。

    前回すでに内容まで見て PASS だった項目が落ちたのなら、それは
    **レスポンスからフィールドが消えた**——C-2 で守れるようにした退行そのもの。
    新しい理由コードだけを見ていると、厳格化と同じ顔で出てくる。
    """
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS, "field_found")]), path)
    regressed = _report([("O1-L1-01", Verdict.FAIL, "field_not_found")])

    with pytest.raises(ValueError, match="前回は内容まで見て PASS"):
        L1Ratchet().tighten(regressed, path, "厳しくしたことにする")

    assert load_baseline(path)["items"]["O1-L1-01"] == "PASS"


def test_tighten_still_accepts_a_route_only_pass_becoming_strict(tmp_path):
    """経路の実在だけで PASS だったものが落ちるのは、厳格化として正しい。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS, "found")]), path)
    stricter = _report([("O1-L1-01", Verdict.FAIL, "field_not_found")])

    L1Ratchet().tighten(stricter, path, "レスポンス内容まで見るようにした")

    assert load_baseline(path)["items"]["O1-L1-01"] == "FAIL"


def test_tighten_refuses_when_the_baseline_has_no_reasons(tmp_path):
    """理由が無いベースラインでは厳格化と退行を区別できない。通さない。"""
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS, "field_found")]), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    del payload["reasons"]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="判定理由"):
        L1Ratchet().tighten(
            _report([("O1-L1-01", Verdict.FAIL, "field_not_found")]),
            path, "厳しくした",
        )


def test_baseline_records_the_reason_of_every_item(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS, "field_found"),
                            ("O1-L1-02", Verdict.PASS, "found")]), path)

    assert load_baseline(path)["reasons"] == {
        "O1-L1-01": "field_found", "O1-L1-02": "found",
    }


# --- 判定の弱化 ---------------------------------------------------------------
#
# verdict だけを見ていると「判定の強さが落ちた」ことに気づけない。
# 項目から response_field を消すだけで内容の判定が丸ごと巻き戻り、
# しかもラチェットは緑のままになる。


def test_losing_content_judgment_while_staying_pass_is_a_violation(tmp_path):
    """field_found → found。PASS のままなので verdict 比較では検出できない。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS, "field_found")]), path)

    result = L1Ratchet().check(
        _report([("O1-L1-01", Verdict.PASS, "found")]), load_baseline(path)
    )

    assert not result.valid
    assert [v.kind for v in result.violations] == ["weakened"]


def test_dropping_a_failing_content_check_is_not_an_improvement(tmp_path):
    """field_not_found → found は FAIL → PASS。放置すると「改善」に見える。

    宣言を消せば落ちていた8件がまとめて PASS に戻り、充足率が上がったように
    見える。これを緑にすると、判定を消すことで数字を作れてしまう。
    """
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.FAIL, "field_not_found")]), path)

    result = L1Ratchet().check(
        _report([("O1-L1-01", Verdict.PASS, "found")]), load_baseline(path)
    )

    assert not result.valid
    assert result.improvements == []
    assert "判定の弱化" in result.to_text()


def test_keeping_the_content_judgment_is_still_valid(tmp_path):
    """内容判定を保ったままの FAIL → PASS は、普通の改善。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.FAIL, "field_not_found")]), path)

    result = L1Ratchet().check(
        _report([("O1-L1-01", Verdict.PASS, "field_found")]), load_baseline(path)
    )

    assert result.valid
    assert result.improvements == ["O1-L1-01"]


def test_route_only_items_are_unaffected(tmp_path):
    """もともと内容を見ていない項目は、この規則の対象外。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS, "found")]), path)

    result = L1Ratchet().check(
        _report([("O1-L1-01", Verdict.PASS, "found")]), load_baseline(path)
    )

    assert result.valid


def test_tighten_refuses_when_one_items_reason_was_deleted(tmp_path):
    """reasons を辞書ごと消さなくても、1項目分を消せば素通りできてしまった。"""
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS, "field_found"),
                            ("O1-L1-02", Verdict.PASS, "found")]), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    del payload["reasons"]["O1-L1-01"]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="前回の判定理由がベースラインに無い"):
        L1Ratchet().tighten(
            _report([("O1-L1-01", Verdict.FAIL, "field_not_found"),
                     ("O1-L1-02", Verdict.PASS, "found")]),
            path, "厳しくした",
        )


# --- 宣言の差し替え -----------------------------------------------------------
#
# 理由コードは「何を測ったか」の**種類**しか持たない。どれを測ったかは宣言に
# しかないので、宣言を差し替えれば同じ理由コードのまま別物を測れる。
# `response_field` を `hook_score` → `success` のような**実在するが別の
# フィールド**に付け替えると、`field_not_found` の FAIL が `field_found` の
# PASS になり、違反ゼロ・改善1件として記録された（gate-verifier 5回目 / C-4）。

_HOOK = {"claim": "response_field", "endpoint": "POST /x",
         "response_field": "hook_score"}
_SUCCESS = {"claim": "response_field", "endpoint": "POST /x",
            "response_field": "success"}


def test_baseline_records_the_declaration_of_every_item(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.FAIL, "field_not_found", _HOOK), path)

    assert load_baseline(path)["declarations"] == {"O1-L1-01": _HOOK}


def test_substituting_a_declaration_to_buy_a_pass_is_a_violation(tmp_path):
    """検証者が実証した抜け道そのもの。FAIL → PASS だが実装は何も変わっていない。"""
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.FAIL, "field_not_found", _HOOK), path)

    result = L1Ratchet().check(
        _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS),
        load_baseline(path),
    )

    assert not result.valid
    assert [v.kind for v in result.violations] == ["substituted"]
    assert result.improvements == [], "要求を取り替えただけのものを改善に数えない"
    assert "hook_score" in result.to_text() and "success" in result.to_text()


def test_substituting_a_declaration_while_staying_pass_is_a_violation(tmp_path):
    """verdict も理由コードも動かない。宣言を記録していないと見えない。"""
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)

    result = L1Ratchet().check(
        _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS),
        load_baseline(path),
    )

    assert not result.valid
    assert [v.kind for v in result.violations] == ["substituted"]


def test_relabelling_the_claim_is_a_substitution(tmp_path):
    """`claim` の貼り替えで unjudgeable の FAIL を PASS にする経路。

    判定できないと結論した項目に弱い claim を貼り直すと PASS になる。
    claim も宣言のうちなので、ここで止まる。
    """
    path = tmp_path / "base.json"
    write_baseline(
        _declared("O4-L1-05", Verdict.FAIL, "unjudgeable",
                  {"claim": "parameter_coverage", "endpoint": "POST /y"}), path)

    result = L1Ratchet().check(
        _declared("O4-L1-05", Verdict.PASS, "field_found",
                  {"claim": "response_field", "endpoint": "POST /y",
                   "response_field": "success"}),
        load_baseline(path),
    )

    assert not result.valid
    assert [v.kind for v in result.violations] == ["substituted"]
    assert result.improvements == []


def test_unchanged_declaration_is_valid(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.FAIL, "field_not_found", _HOOK), path)

    result = L1Ratchet().check(
        _declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), load_baseline(path)
    )

    assert result.valid
    assert result.improvements == ["O1-L1-01"], "実装が直った改善は通す"


# --- 検出器を黙って無効化させない ----------------------------------------------
#
# 記録が無いものは「変化なし」ではなく「分からない」。ブロックを消すだけで
# 検出器が黙って効かなくなる状態を、成功として通さない。


@pytest.mark.parametrize("block", ["reasons", "declarations"])
def test_deleting_a_whole_block_from_the_baseline_is_a_violation(tmp_path, block):
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    del payload[block]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = L1Ratchet().check(
        _declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), load_baseline(path)
    )

    assert not result.valid
    assert [v.kind for v in result.violations] == ["tampered"]


@pytest.mark.parametrize("block", ["reasons", "declarations"])
def test_update_refuses_to_silently_repin_a_deleted_block(tmp_path, block):
    """--update-baseline で黙って締め直せると、消すだけで抜けられる。"""
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    del payload[block]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        L1Ratchet().update(
            _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS), path)


def test_deleting_one_items_declaration_is_a_violation(tmp_path):
    """辞書ごと消さなくても、1項目分を消せば素通りできてはいけない。"""
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    del payload["declarations"]["O1-L1-01"]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = L1Ratchet().check(
        _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS),
        load_baseline(path),
    )

    # 一部の冊にだけ残っている＝記録を消した跡。何が失われたか言えないので
    # 差し替え（substituted）に格下げせず、締め直しでも直せなくする。
    assert [v.kind for v in result.violations] == ["tampered"]
    with pytest.raises(ValueError, match="宣言の差し替えでは説明できない"):
        L1Ratchet().redeclare(
            _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS),
            path, "ピンし直す")


# --- 差し替えの締め直し（--redeclare）------------------------------------------
#
# 宣言を変えること自体は正当な作業。禁じるのは**黙って**変えることのほう。


def test_redeclare_accepts_a_substitution_and_records_before_and_after(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.FAIL, "field_not_found", _HOOK), path)

    L1Ratchet().redeclare(
        _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS),
        path, "hook_score は別エンドポイントの綴り間違いだった",
    )

    base = load_baseline(path)
    history = base["redeclarations"][-1]
    assert history["reason"] == "hook_score は別エンドポイントの綴り間違いだった"
    assert history["items"]["O1-L1-01"]["before"] == _HOOK
    assert history["items"]["O1-L1-01"]["after"] == _SUCCESS
    assert base["declarations"]["O1-L1-01"] == _SUCCESS


def test_redeclare_requires_a_reason(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)

    with pytest.raises(ValueError, match="理由は必須"):
        L1Ratchet().redeclare(
            _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS), path, "  ")


def test_redeclare_refuses_when_a_real_regression_is_mixed_in(tmp_path):
    """差し替えに紛れ込ませて退行を通せるなら、履歴を残す意味が無くなる。"""
    path = tmp_path / "base.json"
    write_baseline(
        L1Report(persona="owner", results=[
            _result("O1-L1-01", Verdict.PASS, reason="field_found",
                    declaration=_HOOK),
            _result("O1-L1-02", Verdict.PASS, reason="found", declaration=_HOOK),
        ], files_scanned=1), path)

    mixed = L1Report(persona="owner", results=[
        _result("O1-L1-01", Verdict.PASS, reason="field_found", declaration=_SUCCESS),
        _result("O1-L1-02", Verdict.FAIL, reason="not_found", declaration=_HOOK),
    ], files_scanned=1)

    with pytest.raises(ValueError, match="宣言の差し替えでは説明できない"):
        L1Ratchet().redeclare(mixed, path, "直した")

    assert load_baseline(path)["items"]["O1-L1-02"] == "PASS"


def test_tighten_cannot_launder_a_substitution(tmp_path):
    """--tighten は「厳しくした」ための穴。差し替えをここから通させない。"""
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)

    with pytest.raises(ValueError, match="厳格化では説明できない"):
        L1Ratchet().tighten(
            _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS),
            path, "厳しくしたことにする")


def test_redeclaration_history_survives_a_later_update(tmp_path):
    """締め直すたびに履歴が消えると、差し替えた事実が1回で失われる。"""
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.FAIL, "field_not_found", _HOOK), path)
    L1Ratchet().redeclare(
        _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS), path, "直した")

    L1Ratchet().update(
        _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS), path)

    assert load_baseline(path)["redeclarations"][-1]["reason"] == "直した"


# --- 実データが宣言を持っていること --------------------------------------------


# --- 記録の欠落を目隠しに使わせない --------------------------------------------
#
# gate-verifier 6回目。`unpinned` を足したことで「記録の不在」は違反になったが、
# 対象が reasons と declarations の2冊だけで、**項目の在否を決めている items
# 自身**が対象外だった。加えて unpinned が退行の判定より前に短絡していたため、
# 記録を1行消すだけで退行を隠せた。


def test_deleting_an_item_from_the_items_book_does_not_hide_a_regression(tmp_path):
    """`items` から1行消すと、その項目は「新しい項目」に化けていた。

    before に居なくなるので退行の比較ループに一度も入らず、宣言の差し替えも
    verdict の後退もまとめて緑で通った（exit 0）。
    """
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    del payload["items"]["O1-L1-01"]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    broken = _declared("O1-L1-01", Verdict.FAIL, "not_found", _SUCCESS)
    result = L1Ratchet().check(broken, load_baseline(path))

    assert not result.valid
    # verdict の記録が消えている以上、退行したかどうかは誰にも言えない。
    # 締め直しで先に進めず、git から戻すしかない状態にする。
    assert "tampered" in {v.kind for v in result.violations}
    with pytest.raises(ValueError):
        L1Ratchet().redeclare(broken, path, "ピンし直す")
    with pytest.raises(ValueError):
        L1Ratchet().update(broken, path)


def test_deleting_an_item_from_every_book_is_caught_by_the_counters(tmp_path):
    """3冊すべてから消せば「新しい項目」に化けた（7回目の穴）。

    集計欄（total / pass / fail）はどこからも照合されていなかったので、
    間引いた跡が残らなかった。items と突き合わせて必ず落とす。
    """
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(
        L1Report(persona="owner", results=[
            _result("O1-L1-01", Verdict.PASS, reason="field_found",
                    declaration=_HOOK),
            _result("O1-L1-02", Verdict.PASS, reason="found", declaration=_HOOK),
        ], files_scanned=1), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    for book in ("items", "reasons", "declarations"):
        del payload[book]["O1-L1-01"]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    weakened = L1Report(persona="owner", results=[
        _result("O1-L1-01", Verdict.FAIL, reason="not_found", declaration=_SUCCESS),
        _result("O1-L1-02", Verdict.PASS, reason="found", declaration=_HOOK),
    ], files_scanned=1)
    result = L1Ratchet().check(weakened, load_baseline(path))

    assert not result.valid
    assert "tampered" in {v.kind for v in result.violations}
    with pytest.raises(ValueError):
        L1Ratchet().update(weakened, path)


def test_deleting_an_item_from_the_story_and_every_book_is_caught(tmp_path):
    """項目そのものを消してベースラインからも消す経路（7回目の穴1）。

    `removed` は「before に居て after に居ない」でしか出ないので、記録ごと
    消せば発火しない。集計欄との突き合わせが最後の網になる。
    """
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(
        L1Report(persona="owner", results=[
            _result("O1-L1-01", Verdict.PASS, reason="found", declaration=_HOOK),
            _result("O1-L1-02", Verdict.PASS, reason="found", declaration=_HOOK),
        ], files_scanned=1), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    for book in ("items", "reasons", "declarations"):
        del payload[book]["O1-L1-01"]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    shrunk = _declared("O1-L1-02", Verdict.PASS, "found", _HOOK)
    result = L1Ratchet().check(shrunk, load_baseline(path))

    assert not result.valid
    assert "tampered" in {v.kind for v in result.violations}


def test_unpinned_does_not_short_circuit_the_regression_check(tmp_path):
    """記録の欠落と退行が同じ項目に乗ったら、両方とも報告する。

    unpinned で打ち切っていた頃は退行が報告されず、--redeclare が
    「差し替えだけ」と判断して受理していた。
    """
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    del payload["declarations"]["O1-L1-01"]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = L1Ratchet().check(
        _declared("O1-L1-01", Verdict.FAIL, "not_found", _SUCCESS), load_baseline(path)
    )

    # 退行で打ち切らないので、判定の弱化も同時に出る（片方だけだと締め直しの
    # 履歴にもう片方が残らない）。
    assert {v.kind for v in result.violations} == {"tampered", "regressed", "weakened"}


def test_redeclare_cannot_pin_over_a_regression_hidden_by_a_deleted_record(tmp_path):
    """記録を1行消して退行を未ピンの陰に隠し、--redeclare で締め直す経路。"""
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    del payload["declarations"]["O1-L1-01"]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="宣言の差し替えでは説明できない"):
        L1Ratchet().redeclare(
            _declared("O1-L1-01", Verdict.FAIL, "not_found", _SUCCESS),
            path, "宣言をピンし直す")

    assert load_baseline(path)["items"]["O1-L1-01"] == "PASS"


def test_update_cannot_repin_over_a_partially_deleted_record(tmp_path):
    """一部の冊にだけ残っている＝記録を消した跡。理由なしでは締め直せない。"""
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    del payload["declarations"]["O1-L1-01"]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        L1Ratchet().update(
            _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS), path)


# --- 集計欄の照合（8回目）------------------------------------------------------
#
# 集計欄の**値の書き換え**だけを見て `recorded is not None` で素通りさせていたので、
# 3つの欄をキーごと消せば照合が丸ごと消え、ピンの間引きが exit 0 で通った。
# 無い欄は「合っている」ではなく「照合できない」。


@pytest.mark.parametrize("field_name", ["total", "pass", "fail"])
def test_deleting_a_counter_field_is_a_violation(tmp_path, field_name):
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    del payload[field_name]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = L1Ratchet().check(
        _declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), load_baseline(path)
    )

    assert not result.valid
    assert [v.kind for v in result.violations] == ["tampered"]


def test_deleting_counters_and_records_cannot_launder_a_weakening(tmp_path):
    """8回目の②。集計欄ごと消せば弱化が `unpinned_new` に化けて締め直せた。"""
    import json as _json

    path = tmp_path / "base.json"
    write_baseline(
        L1Report(persona="owner", results=[
            _result("O1-L1-01", Verdict.PASS, reason="field_found",
                    declaration=_HOOK),
            _result("O1-L1-02", Verdict.PASS, reason="found", declaration=_HOOK),
        ], files_scanned=1), path)
    payload = _json.loads(path.read_text(encoding="utf-8"))
    for book in ("items", "reasons", "declarations"):
        del payload[book]["O1-L1-01"]
    for counter in ("total", "pass", "fail"):
        del payload[counter]
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    weakened = L1Report(persona="owner", results=[
        _result("O1-L1-01", Verdict.PASS, reason="found",
                declaration={"claim": "route_exists", "endpoint": "POST /x"}),
        _result("O1-L1-02", Verdict.PASS, reason="found", declaration=_HOOK),
    ], files_scanned=1)

    assert not L1Ratchet().check(weakened, load_baseline(path)).valid
    with pytest.raises(ValueError):
        L1Ratchet().update(weakened, path)


def test_update_records_what_it_newly_pinned(tmp_path):
    """理由は要らないが記録は要る。何をピンしたかが残らないと追えない。"""
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)
    grown = L1Report(persona="owner", results=[
        _result("O1-L1-01", Verdict.PASS, reason="field_found", declaration=_HOOK),
        _result("O1-L1-02", Verdict.FAIL, reason="not_found", declaration=_SUCCESS),
    ], files_scanned=1)

    L1Ratchet().update(grown, path)

    pinned = load_baseline(path)["pins"][-1]["items"]
    assert pinned["O1-L1-02"] == {"verdict": "FAIL", "declaration": _SUCCESS}


def test_committed_baseline_pins_the_declaration_of_every_owner_l1_item():
    """宣言が載っていないベースラインでは、差し替えを検出できない。"""
    from backend.ux_verification.executor import L1Executor
    from backend.ux_verification.l1_ratchet import baseline_path, load_baseline

    base = load_baseline(baseline_path("owner"))
    report = L1Executor.for_repo().run("owner")

    assert set(base.get("declarations") or {}) == {r.item_id for r in report.results}
    assert all(d.get("claim") for d in base["declarations"].values()), \
        "claim の無い項目があると、貼り替えの前後が比較できない"


def test_executor_attaches_the_declaration_to_every_result():
    """`_route` が載せ忘れると、ベースラインは空の宣言を 122件ピンして緑になる。"""
    from backend.ux_verification.executor import L1Executor

    report = L1Executor.for_repo().run("owner")

    assert report.results, "項目が0件では何も守れない"
    assert all(r.declaration for r in report.results)


def test_a_substitution_does_not_disable_the_weakening_detector(tmp_path):
    """宣言の差し替えで打ち切ると、弱化の検出器が回らなくなる（10回目）。

    `field_found` → `found` を差し替えと一緒に出せば、--redeclare が
    理由1本で受理してしまった（3層のうち2層目が、3層目が発火するときだけ無効）。
    """
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)
    weakened = _declared("O1-L1-01", Verdict.PASS, "found",
                         {"claim": "route_exists", "endpoint": "POST /x"})

    result = L1Ratchet().check(weakened, load_baseline(path))

    assert {v.kind for v in result.violations} == {"substituted", "weakened"}
    with pytest.raises(ValueError, match="宣言の差し替えでは説明できない"):
        L1Ratchet().redeclare(weakened, path, "理由")


def test_settle_accepts_a_tightening_that_also_changes_the_declaration(tmp_path):
    """判定手段を強めると宣言も変わる。片方ずつだと互いに拒否して詰む。"""
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)
    parked = _declared("O1-L1-01", Verdict.FAIL, "unjudgeable",
                       {"claim": "state_transition", "endpoint": "POST /x"})

    with pytest.raises(ValueError):
        L1Ratchet().tighten(parked, path, "厳しくした")
    with pytest.raises(ValueError):
        L1Ratchet().redeclare(parked, path, "貼り替えた")

    L1Ratchet().settle(parked, path, "測れないと結論した", "claim を貼り替えた")

    base = load_baseline(path)
    assert base["items"]["O1-L1-01"] == "FAIL"
    assert base["tightenings"][-1]["reason"] == "測れないと結論した"
    assert base["redeclarations"][-1]["reason"] == "claim を貼り替えた"


def test_settle_refuses_anything_that_is_not_a_tightening_or_a_substitution(tmp_path):
    """緩めるための道具にしない。"""
    path = tmp_path / "base.json"
    write_baseline(_report([("O1-L1-01", Verdict.PASS, "field_found"),
                            ("O1-L1-02", Verdict.PASS, "found")]), path)
    weakened = _report([("O1-L1-01", Verdict.PASS, "found"),
                        ("O1-L1-02", Verdict.PASS, "found")])

    with pytest.raises(ValueError, match="厳格化とも差し替えとも説明できない"):
        L1Ratchet().settle(weakened, path, "理由A", "理由B")


def test_settle_requires_both_reasons(tmp_path):
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.PASS, "field_found", _HOOK), path)

    with pytest.raises(ValueError, match="両方書いて"):
        L1Ratchet().settle(
            _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS),
            path, "理由だけ", "  ")


def test_a_substitution_is_never_counted_as_an_improvement(tmp_path):
    """打ち切りをやめた副作用で、差し替えが改善に数えられてはいけない。"""
    path = tmp_path / "base.json"
    write_baseline(_declared("O1-L1-01", Verdict.FAIL, "field_not_found", _HOOK), path)

    result = L1Ratchet().check(
        _declared("O1-L1-01", Verdict.PASS, "field_found", _SUCCESS),
        load_baseline(path),
    )

    assert result.improvements == []
