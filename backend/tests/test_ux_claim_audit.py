"""主張と判定手段の対応を突き合わせる実行系のテスト（P3 C-1）。

P2 では「どの項目が何を主張しているか」を人間が description を読んで数えていた。
3回の独立検証で3回とも数え漏れが見つかった。ここで固定するのは
**取りこぼしが機械的に出てくること**であって、正しく分類できることではない。
"""
from __future__ import annotations

import json

from backend.ux_verification.claim_audit import (
    CLAIM_METHODS,
    UNJUDGEABLE_CLAIMS,
    UNSUPPORTED_CLAIMS,
    audit,
    for_repo,
)


def _stories(tmp_path, items, name="o1_demo.json", ux_id="O-1"):
    path = tmp_path / name
    path.write_text(
        json.dumps({"ux_id": ux_id, "name": ux_id, "verification_items": items},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    return tmp_path


def _item(item_id, claim=None, **declared):
    out = {"id": item_id, "layer": 1, "description": item_id}
    if claim is not None:
        out["claim"] = claim
    out.update(declared)
    return out


# --- 対応が取れている ---------------------------------------------------------


def test_dom_claim_with_a_testid_is_matched(tmp_path):
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "dom_exists", testid="drop-zone"),
    ]))

    assert report.mismatched == []


def test_response_field_claim_needs_both_declarations(tmp_path):
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field",
              endpoint="GET /api/x", response_field="videos"),
    ]))

    assert report.mismatched == []


# --- 取りこぼしが出てくる -----------------------------------------------------


def test_missing_claim_is_reported(tmp_path):
    """新しい項目を足して claim を書き忘れたら、ここで出る。

    P2 の数え漏れはすべてこの型（誰も種類を書いていないので誰も数えられない）。
    """
    report = audit(_stories(tmp_path, [_item("O1-L1-01", testid="x")]))

    assert [r.reason for r in report.mismatched] == ["no_claim"]


def test_unknown_claim_is_reported(tmp_path):
    report = audit(_stories(tmp_path, [_item("O1-L1-01", "気合", testid="x")]))

    assert [r.reason for r in report.mismatched] == ["unknown_claim"]


def test_route_claim_judged_by_a_testid_is_a_mismatch(tmp_path):
    """P2 で3回とも見落とした型。

    「動画一覧APIが正常応答を返す」は経路の主張なのに testid しか持たず、
    DOM 要素の実在だけで PASS していた。
    """
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "route_exists", testid="video-file-browser"),
    ]))

    assert [r.reason for r in report.mismatched] == ["not_declared"]


def test_response_field_claim_without_the_field_is_a_mismatch(tmp_path):
    """endpoint だけでは「statusフィールドが存在する」を判定できない。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field", endpoint="GET /api/x"),
    ]))

    assert [r.reason for r in report.mismatched] == ["not_declared"]


def test_claim_with_an_unimplemented_method_is_reported(tmp_path, monkeypatch):
    """判定手段が未実装なことを隠さない。宣言を消して PASS に逃がさせない。"""
    monkeypatch.setitem(CLAIM_METHODS, "未実装の主張", ())
    report = audit(_stories(tmp_path, [_item("O1-L1-01", "未実装の主張")]))

    assert [r.reason for r in report.mismatched] == ["no_method"]


def test_claim_concluded_unjudgeable_is_not_a_mismatch(tmp_path):
    """「判定できない」と結論するのも対応のうち。

    ただし PASS に逃がさないことが前提で、そちらは executor 側で
    unjudgeable の FAIL として固定している。
    """
    report = audit(_stories(tmp_path, [_item("O5-L1-06", "idempotency")]))

    assert report.mismatched == []


def test_the_two_unsupported_states_are_distinguished():
    """「未実装」と「原理的に判定できないと結論した」は別物。

    同じ扱いにすると、実装をサボったものと結論を出したものが混ざり、
    「あと何を作れば終わるのか」が分からなくなる。
    """
    assert set(UNSUPPORTED_CLAIMS) == {
        k for k, v in CLAIM_METHODS.items() if v == ()
    }
    assert set(UNJUDGEABLE_CLAIMS) == {
        k for k, v in CLAIM_METHODS.items() if v is None
    }
    assert not (set(UNSUPPORTED_CLAIMS) & set(UNJUDGEABLE_CLAIMS))


# --- 出力 --------------------------------------------------------------------


def test_report_explains_what_is_missing(tmp_path):
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "route_exists", testid="x"),
    ]))

    text = report.mismatched[0].as_text()

    assert "endpoint" in text
    assert "testid" in text


def test_keys_are_sorted_for_a_stable_diff(tmp_path):
    report = audit(_stories(tmp_path, [
        _item("O1-L1-02"), _item("O1-L1-01"),
    ]))

    assert report.keys() == ["O1-L1-01", "O1-L1-02"]


# --- 実リポジトリ -------------------------------------------------------------


def test_every_owner_l1_item_declares_a_claim():
    """1件でも claim が無ければ、その項目は誰にも数えられていない。"""
    report = for_repo("owner")

    assert report.total == 122
    assert [r.item_id for r in report.mismatched if r.reason == "no_claim"] == []


def test_owner_l1_claim_kinds_cover_every_item():
    report = for_repo("owner")

    assert sum(report.by_claim().values()) == 122
    assert "(未記入)" not in report.by_claim()


def test_owner_l1_has_no_mismatch_left():
    """P3 C-3。主張と判定手段の対応が取れていない項目がゼロ。"""
    report = for_repo("owner")

    assert report.mismatched == [], "; ".join(
        r.item_id for r in report.mismatched
    )

def test_gate_fails_when_something_is_mismatched(tmp_path, monkeypatch):
    """CI ゲート。対応が取れていない項目が1件でもあれば exit 1。"""
    from backend.ux_verification import claim_audit as ca

    monkeypatch.setattr(ca, "for_repo", lambda persona="owner": ca.audit(
        _stories(tmp_path, [_item("O1-L1-01", "route_exists", testid="x")])
    ))

    assert ca.main(["--persona", "owner", "--gate"]) == 1


def test_gate_fails_when_no_item_was_read(tmp_path, monkeypatch):
    """走査できなかったことを『対応ゼロ』として通さない。

    ストーリーを見失っただけで緑になるなら、ディレクトリを1つ消せば
    ゲートを黙らせられる。
    """
    from backend.ux_verification import claim_audit as ca

    monkeypatch.setattr(ca, "for_repo",
                        lambda persona="owner": ca.audit(tmp_path / "empty"))

    assert ca.main(["--persona", "owner", "--gate"]) == 1


def test_gate_passes_on_the_real_repo():
    from backend.ux_verification import claim_audit as ca

    assert ca.main(["--persona", "owner", "--gate"]) == 0

# --- 走査範囲が判定側とずれない ------------------------------------------------
#
# 監査の範囲が実行系より狭いと、「対応ゼロ」は「監査が見ている範囲では対応ゼロ」
# という意味しか持たない。その隙間に置いた項目は3つのゲートすべてをすり抜ける。


def _executor_ids(stories_dir):
    from backend.ux_verification.executor import iter_l1_items

    return sorted(
        (item.get("id") or item.get("item_id") or "")
        for _, item in iter_l1_items(stories_dir, "O")
    )


def test_audit_sees_exactly_what_the_executor_judges(tmp_path):
    stories = _stories(tmp_path, [_item("O1-L1-01", "dom_exists", testid="x")])

    assert sorted(r.item_id for r in audit(stories).rows) == _executor_ids(stories)


def test_an_extra_story_file_is_not_invisible_to_the_audit(tmp_path):
    """ファイル名が o* で始まらないストーリーも判定側は読む。"""
    _stories(tmp_path, [_item("O1-L1-01", "dom_exists", testid="x")])
    _stories(tmp_path, [_item("O13-L1-01", endpoint="GET /api/x")],
             name="zz_extra_story.json", ux_id="O-13")

    report = audit(tmp_path)

    assert sorted(r.item_id for r in report.rows) == _executor_ids(tmp_path)
    assert [r.reason for r in report.mismatched] == ["no_claim"]


def test_an_id_without_the_l1_marker_is_still_audited(tmp_path):
    """判定側は ID ではなく layer で選ぶ。ID の形だけで除外しない。"""
    stories = _stories(tmp_path, [
        _item("O1-L1-01", "dom_exists", testid="x"),
        _item("O1-S9-99", endpoint="GET /api/x"),
    ])

    report = audit(stories)

    assert sorted(r.item_id for r in report.rows) == _executor_ids(stories)
    assert [r.item_id for r in report.mismatched] == ["O1-S9-99"]


def test_non_layer1_items_are_left_alone(tmp_path):
    """L2 以降は P3 のスコープ外。判定側も拾わない。"""
    stories = _stories(tmp_path, [
        _item("O1-L1-01", "dom_exists", testid="x"),
        {"id": "O1-L2-01", "layer": 2, "description": "L2"},
    ])

    assert [r.item_id for r in audit(stories).rows] == ["O1-L1-01"]


# --- 判定の意味を言葉で固定する ------------------------------------------------


def test_every_claim_states_what_it_does_not_verify():
    """分類だけして意味を書かないと、判定が妥当か読み手に分からない。

    「正常応答を返す」を経路の実在で PASS にしているのが妥当かどうかは、
    route_exists が何を確かめないかを書いて初めて読める。
    """
    from backend.ux_verification.claim_audit import CLAIM_SEMANTICS

    assert set(CLAIM_SEMANTICS) == set(CLAIM_METHODS), (
        "claim を足したら意味も書く"
    )
    for claim, (verifies, does_not) in CLAIM_SEMANTICS.items():
        assert verifies and does_not, claim


def test_unjudgeable_claims_have_no_verifies_clause():
    """判定手段が無いものが『確かめる』を持っていたら、分類か実装が食い違っている。"""
    from backend.ux_verification.claim_audit import CLAIM_SEMANTICS

    for claim in UNJUDGEABLE_CLAIMS:
        assert CLAIM_SEMANTICS[claim][0] == "（判定手段なし）", claim


def test_semantics_output_lists_every_claim(capsys):
    from backend.ux_verification import claim_audit as ca

    assert ca.main(["--semantics"]) == 0
    out = capsys.readouterr().out
    for claim in CLAIM_METHODS:
        assert claim in out
