"""主張と判定手段の対応を突き合わせる実行系のテスト（P3 C-1）。

P2 では「どの項目が何を主張しているか」を人間が description を読んで数えていた。
3回の独立検証で3回とも数え漏れが見つかった。ここで固定するのは
**取りこぼしが機械的に出てくること**であって、正しく分類できることではない。
"""
from __future__ import annotations

import json

import pytest

from backend.ux_verification.claim_audit import (
    CLAIM_METHODS,
    UNJUDGEABLE_CLAIMS,
    UNSUPPORTED_CLAIMS,
    audit,
    for_repo,
)


# 名詞句は登録済みのものだけ通る（P3 C-3）。合成データが使う名詞句を足しておく。
# **実データの語彙は触らない。** 登録外を弾くこと自体を確かめるテストは、
# ここに無い名詞句を使う。
# 名詞句は「どのテンプレートで使ってよいか」まで登録する。
_ALL_TEMPLATES = frozenset({
    "値の指定", "〜のみ", "件数", "プリセット網羅", "可能である", "列挙の実在",
    "経路＋状態遷移", "保存キーの実在", "経路＋フィールド", "経路のみ",
    "リクエスト契約", "必須フィールド", "フィールドの実在", "フィールドを返す",
    "要素の実在",
})
_TEST_PHRASES = {
    p: _ALL_TEMPLATES for p in (
        "要素", "API", "APIが", "履歴キー", "対応拡張子", "パラメータ", "status",
        "ステータスがcompleted", "ステータスがcompletedのバッジ", "ID表示",
        "解除APIが", "事前企画APIが",
    )
}


@pytest.fixture(autouse=True)
def _extend_vocabulary(monkeypatch):
    from backend.ux_verification import claim_audit as ca

    monkeypatch.setattr(ca, "NOUN_PHRASES", {**ca.NOUN_PHRASES, **_TEST_PHRASES})


def _stories(tmp_path, items, name="o1_demo.json", ux_id="O-1"):
    path = tmp_path / name
    path.write_text(
        json.dumps({"ux_id": ux_id, "name": ux_id, "verification_items": items},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    return tmp_path


# claim ごとの、**述語の語彙に載っている** description。
# description の述語と claim の対応も監査するようになったので（P3 C-3）、
# 合成データも実データと同じ書き方にしないと `unparsed` で落ちる。
_DESC_FOR_CLAIM = {
    "dom_exists": "要素が存在する",
    "route_exists": "APIが正常応答",
    "response_field": "APIが正常応答しvideosが返る",
    "storage_key": "localStorageに履歴キーが存在する",
    "value_constraint": "4カテゴリ(a/b/c/d)が存在する",
    "value_exclusive": "対応拡張子のみ含まれる",
    "request_contract": "パラメータを受け付ける",
    "response_value": "success=true",
}


def _item(item_id, claim=None, description=None, **declared):
    out = {
        "id": item_id, "layer": 1,
        "description": description or _DESC_FOR_CLAIM.get(claim, "要素が存在する"),
    }
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
        _item("O1-L1-01", "response_field", description="statusフィールドが存在する",
              endpoint="GET /api/x"),
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


# --- 宣言内容（ラチェットが固定する対象）--------------------------------------


def test_declaration_keys_cover_every_judging_method():
    """新しい判定手段を足したら、その宣言も自動でラチェットの対象になる。

    ここを手で並べていると、増えたほうだけがラチェットの外に落ちて、
    その宣言だけ黙って差し替えられる（走査範囲の外のポケットの型）。
    """
    from backend.ux_verification.claim_audit import DECLARATION_KEYS

    required = {key for r in CLAIM_METHODS.values() if r for key in r}

    assert required <= set(DECLARATION_KEYS)
    assert "claim" in DECLARATION_KEYS, "claim の貼り替えも差し替えのうち"


def test_the_description_is_pinned_by_the_ratchet():
    """description を書き換えて主張を逃がす経路は、ラチェットで塞ぐ。

    強い述語の検査は語彙に依存し、語彙外の述語（`以外` `一致する` `巻き戻して`）は
    名詞句に吸収される——4回続けて同じ型で破られた（gate-verifier 14回目）。
    テンプレート検査は**新しい**項目の形しか保証できないので、既存項目の主張が
    黙って変わらないことはラチェットの仕事にする。
    """
    from backend.ux_verification.claim_audit import DECLARATION_KEYS

    assert "description" in DECLARATION_KEYS


def test_declaration_of_takes_only_what_the_item_declares():
    from backend.ux_verification.claim_audit import declaration_of

    item = {
        "id": "O1-L1-01", "description": "説明", "story_scene": "S1",
        "layer": 1, "test_method": "dom_exists",
        "claim": "response_field", "endpoint": "POST /x", "response_field": "success",
    }

    assert declaration_of(item) == {
        "claim": "response_field", "description": "説明",
        "endpoint": "POST /x", "response_field": "success",
    }, "layer や story_scene は宣言ではない"


def test_declaration_of_ignores_empty_values():
    """空文字の testid を「宣言している」と数えると、消しても差分が出ない。"""
    from backend.ux_verification.claim_audit import declaration_of

    assert declaration_of({"claim": "route_exists", "endpoint": "GET /x",
                           "testid": ""}) == {
        "claim": "route_exists", "endpoint": "GET /x"}


# --- description の述語と claim の対応（P3 C-3）---------------------------------
#
# claim は人が貼るラベルで、description との対応を誰も検証していなかった。
# 弱いラベルを選べば主張の一部を捨てたまま PASS にできた（gate-verifier 5回目）。


def test_a_value_claim_cannot_be_measured_by_field_existence(tmp_path):
    """`success=true` に response_field を貼る——実在した偽 PASS そのもの。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field", description="success=true",
              endpoint="POST /api/x", response_field="success"),
    ]))

    assert [r.reason for r in report.mismatched] == ["claim_too_weak"]


def test_an_exclusivity_claim_cannot_be_measured_by_presence(tmp_path):
    """「〜のみ」を value_constraint で測ると『のみ』が落ちる。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "value_constraint", description="対応拡張子のみ含まれる",
              endpoint="GET /api/x", value_literals=[".mp4"]),
    ]))

    assert [r.reason for r in report.mismatched] == ["claim_too_weak"]


def test_a_state_transition_cannot_be_measured_by_field_existence(tmp_path):
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field",
              description="解除APIが正常応答しlocked_segmentsが更新される",
              endpoint="POST /api/x", response_field="locked_segments"),
    ]))

    assert [r.reason for r in report.mismatched] == ["claim_too_weak"]


def test_a_description_outside_the_vocabulary_is_rejected(tmp_path):
    """語彙を閉じる。未登録の書き方で強い主張を書けば素通りしてしまう。

    ユーザー判断（2026-08-07）: マーカー検出だと辞書に無い語を見落とす。
    実際、最初のパターン表は「4カテゴリ」を拾えなかった。
    """
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "dom_exists", description="いい感じに動く", testid="x"),
    ]))

    assert [r.reason for r in report.mismatched] == ["unparsed"]


def test_declaring_it_unmeasurable_is_allowed_for_any_predicate(tmp_path):
    """「測れない」は述語の種類とは別の軸。どの述語にも貼れる。

    必ず FAIL に落ちるので偽の緑は作れない（ユーザー判断 2026-08-07）。
    O9-L1-12「エクスポートAPIが正常応答」が実例で、述語は経路の主張だが
    どの API を指しているかが仕様に無い。
    """
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "spec_incomplete", description="エクスポートAPIが正常応答"),
    ]))

    assert report.mismatched == []


def test_every_template_points_at_a_known_claim():
    """テンプレートを足して claim を書き忘れたら、対応表の外にポケットができる。"""
    import re as _re

    from backend.ux_verification.claim_audit import DESCRIPTION_TEMPLATES

    from backend.ux_verification.claim_audit import _STRONG_MARKERS

    for name, pattern, claims, accounts in DESCRIPTION_TEMPLATES:
        assert pattern.startswith("^") and pattern.endswith("$"), name
        _re.compile(pattern)
        assert claims, name
        for claim in claims:
            assert claim in CLAIM_METHODS, f"{name} → {claim}"
        # 引き受ける述語も語彙に載っていること（綴り間違いで検査が消えない）
        assert accounts <= set(_STRONG_MARKERS), name


def test_every_owner_l1_description_is_in_the_vocabulary():
    """122件すべてが語彙で書かれていること。1件でも外れたら CI が落ちる。"""
    from backend.ux_verification.claim_audit import parse_description

    report = for_repo("owner")
    unparsed = [r.item_id for r in report.rows
                if parse_description(r.description) is None]

    assert unparsed == []


# --- 文末だけを見ない（gate-verifier 10回目）------------------------------------
#
# 最初の実装は「先に当たったパターンを採る」形で、文末の動詞しか閉じていなかった。
# `success=true` は強い述語に当たるのに、`…正常応答し success=true が返る` と
# 書くと「経路＋フィールド」に落ちて値の主張が消えた。
# **同じ主張が空白の有無で強弱に振れていた。**


def test_a_value_claim_buried_mid_sentence_is_rejected(tmp_path):
    """`success=true` が文中にあるとテンプレートに丸ごと一致しない → unparsed。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field",
              description="事前企画APIが正常応答し success=true が返る",
              endpoint="POST /api/x", response_field="success"),
    ]))

    assert [r.reason for r in report.mismatched] == ["unparsed"]


def test_an_unregistered_combination_of_predicates_is_rejected(tmp_path):
    """述語そのものは既知でも、**組み合わせ**が未登録なら通さない。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "dom_exists",
              description="3件以上のセグメントがlocalStorageに存在する", testid="x"),
    ]))

    assert [r.reason for r in report.mismatched] == ["unparsed"]


# --- 機械が型付けできないスロットは人に宣言させる -------------------------------
#
# `hook_score を返す`（フィールドの実在）と `ステータスが completed を返す`
# （値の主張）は、どちらも「〜を返す」で終わる。completed が値なのか
# フィールド名なのかを機械は知らない。ユーザー判断（2026-08-07）で、
# 判別できないものは項目自身に宣言させ、**空欄を機械が許さない**ことにした。


def test_an_untypable_slot_requires_an_explicit_note(tmp_path):
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field", description="ステータスがcompletedを返す",
              endpoint="GET /api/x", response_field="status"),
    ]))

    assert [r.reason for r in report.mismatched] == ["value_note_required"]


def test_an_explicit_note_settles_it(tmp_path):
    """宣言と一致していれば、明記で片が付く。

    `completed` はフィールド名だと宣言しているので、response_field も
    `completed` でなければ辻褄が合わない（18回目でここも照合するようにした）。
    """
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field", description="ステータスがcompletedを返す",
              endpoint="GET /api/x", response_field="completed",
              value_note="completed はフィールド名で、値の主張ではない"),
    ]))

    assert report.mismatched == []


def test_a_note_does_not_excuse_a_field_that_is_not_declared(tmp_path):
    """明記があっても、埋め込まれたフィールド名が宣言に無ければ通さない。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field", description="ステータスがcompletedを返す",
              endpoint="GET /api/x", response_field="status",
              value_note="completed はフィールド名で、値の主張ではない"),
    ]))

    assert [r.reason for r in report.mismatched] == ["slot_not_declared"]


def test_an_ascii_identifier_slot_needs_no_note(tmp_path):
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field", description="hook_scoreが返る",
              endpoint="GET /api/x", response_field="hook_score"),
    ]))

    assert report.mismatched == []


def test_the_identifier_check_is_ascii_only():
    """`\w` は Unicode なので日本語も識別子扱いになる。ASCII に限る。"""
    from backend.ux_verification.claim_audit import needs_value_note

    assert not needs_value_note("hook_scoreが返る")
    assert needs_value_note("BGM設定が含まれる")
    assert needs_value_note("ロゴ設定が含まれる"), "フィールド系は識別子でなければ必ず"
    assert not needs_value_note("進捗バーが存在する"), "純粋な UI 名は対象外"


def test_the_value_note_is_pinned_by_the_ratchet():
    """宣言を消せば検査が消える。ラチェットの固定対象に入っていること。"""
    from backend.ux_verification.claim_audit import DECLARATION_KEYS

    assert "value_note" in DECLARATION_KEYS


def test_every_owner_l1_item_that_needs_a_note_has_one():
    from backend.ux_verification.claim_audit import needs_value_note

    report = for_repo("owner")
    missing = [r.item_id for r in report.rows if r.reason == "value_note_required"]

    assert missing == []
    # 検査が空振りしていないこと（1件も要求していないなら何も守っていない）
    assert any(needs_value_note(r.description) for r in report.rows)


def test_a_clause_break_is_not_a_way_out(tmp_path):
    """読点で強い主張を節の外へ押し出せた（12回目）。

    マーカー方式は「当たった述語」しか見ず、当たらなかった部分は黙って
    捨てられた。いまは**文全体**をテンプレートに突き合わせ、部分一致は認めない。
    """
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description("ステータスが completed を返す。") is None
    assert parse_description("推奨レスポンスの status が completed を返す（S3）") is None
    assert parse_description(
        "事前企画APIが正常応答し、success が true を返すことを確認する") is None
    assert parse_description("ステータスが completed になり、hook_score を返す") is None


def test_a_strong_predicate_buried_in_the_slot_is_rejected(tmp_path):
    """スロットに強い述語が埋まっていたら、その主張は測られていない。"""
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description(
        "固定APIが正常応答しlocked_segmentsが更新されlocked_segmentsを返す") is None
    assert parse_description("レスポンスは3秒以内にstatusを返す") is None
    assert parse_description("拡張子はmp4に限られvideosを返す") is None


def test_a_value_claim_with_a_trailing_clause_is_still_caught(tmp_path):
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field",
              description="事前企画APIが正常応答し、success が true を返すことを確認する",
              endpoint="POST /api/x", response_field="success"),
    ]))

    assert [r.reason for r in report.mismatched] == ["unparsed"]


def test_an_element_claim_with_an_ascii_token_needs_a_note(tmp_path):
    """`ステータス表示が completed で存在する` ＋ dom_exists ＋ testid で、
    値の主張を要素の実在で緑にできた（5回目の型の DOM 側）。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "dom_exists",
              description="ステータスがcompletedのバッジが存在する",
              testid="status-badge"),
    ]))

    assert [r.reason for r in report.mismatched] == ["value_note_required"]


def test_an_unregistered_phrasing_of_existence_is_rejected(tmp_path):
    """「で存在する」は語彙に無い書き方。緑にはならない。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "dom_exists",
              description="ステータス表示がcompletedで存在する", testid="status-badge"),
    ]))

    assert [r.reason for r in report.mismatched] == ["unparsed"]


def test_a_plain_japanese_ui_name_needs_no_note(tmp_path):
    """ユーザー判断（2026-08-07）: 純粋な UI 名は対象外。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "dom_exists", description="進捗バーが存在する",
              testid="progress-bar"),
    ]))

    assert report.mismatched == []


# --- 検査対象は文全体（gate-verifier 13回目）------------------------------------
#
# 強い述語の走査を**名前付きスロットだけ**にしていたので、テンプレートの無名部分や
# 括弧の中に逃がせた。読点を使わずに「経路＋フィールド」へ化けさせられた。


def test_a_strong_predicate_in_an_unnamed_part_is_rejected():
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description(
        "locked_segmentsが更新され固定解除APIが正常応答しlocked_segmentsを返す") is None


def test_a_strong_predicate_inside_parentheses_is_rejected():
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description(
        "3カテゴリ(A/B/C が更新され3件以内で反映される)が存在する") is None


def test_a_template_must_account_for_the_predicates_it_carries():
    """テンプレート自身が持つ強い述語は引き受けとして宣言されていること。"""
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description("動画リストに対応拡張子のみ含まれる") is not None
    assert parse_description("セグメントが3件以上表示される") is not None
    assert parse_description("推奨APIで再計算が可能(undo相当)") is not None
    assert parse_description("固定解除APIが正常応答しlocked_segmentsが更新される") is not None


def test_a_bare_value_in_the_slot_is_caught_by_the_declaration(tmp_path):
    """`completed を返す` の completed は値。宣言した response_field に無い。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field", description="completed を返す",
              endpoint="GET /api/x", response_field="status"),
    ]))

    assert [r.reason for r in report.mismatched] == ["slot_not_declared"]


def test_a_slot_that_names_the_declared_field_is_fine(tmp_path):
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field", description="hook_score含む",
              endpoint="GET /api/x", response_field="hook_score"),
    ]))

    assert report.mismatched == []


def test_a_semicolon_is_a_clause_break_too(tmp_path):
    """`；` で別節に主張を逃がせた（14回目）。読点だけが区切りではない。"""
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description(
        "ステータスがcompletedに一致する；シーン固定APIが正常応答を返す") is None
    assert parse_description("A" + chr(10) + "Bが正常応答") is None


# --- 名詞句の語彙（gate-verifier 15回目・ユーザー判断 2026-08-07）-----------------
#
# 強い述語の検査は語彙に依存し、語彙外の述語は名詞句に吸収される。
# **足すたびに次の未登録語で抜ける。5回作り直して5回ともそうだった。**
# 名詞句そのものを閉じて、はじめて原理的に閉じる。


def test_an_unregistered_noun_phrase_is_rejected():
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description(
        "アップロードAPIがmp4以外を拒否し5個までに制限したうえで正常応答を返す") is None
    assert parse_description("ステータスがcompletedに一致するAPIが正常応答を返す") is None


def test_a_registered_noun_phrase_passes():
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description("動画一覧APIが正常応答を返す") is not None
    assert parse_description("進捗バーが存在する") is not None


def test_an_ascii_identifier_slot_needs_no_registration():
    """フィールド名は `slot_not_declared` が宣言と突き合わせるので登録不要。"""
    from backend.ux_verification.claim_audit import NOUN_PHRASES, parse_description

    assert "hook_score" not in NOUN_PHRASES
    assert parse_description("hook_score含む") is not None


def test_every_owner_l1_noun_phrase_is_registered():
    """実データが全件テンプレートに一致すること（語彙が実装から drift しない）。"""
    from backend.ux_verification.claim_audit import parse_description

    report = for_repo("owner")
    unparsed = [r.item_id for r in report.rows
                if parse_description(r.description) is None]

    assert unparsed == []


def test_the_unnamed_prefix_is_checked_too():
    """「経路＋フィールド」の前置は名前が無く、辞書が掛かっていなかった（16回目）。"""
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description(
        "セグメントが3つ残った状態で正常応答し hook_score を返す") is None
    assert parse_description(
        "全セグメントを巻き戻して正常応答し hook_score を返す") is None


def test_a_phrase_cannot_move_to_a_weaker_template():
    """判定不能の項目のために登録した名詞句を、PASS できる形へ移せた（16回目）。

    辞書は「名詞句 → 使ってよいテンプレート」まで持つ。
    """
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description("推奨APIで再計算が可能(undo相当)") is not None
    assert parse_description("推奨APIで再計算が正常応答する") is None


def test_an_empty_slot_is_not_a_field_claim():
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description("正常応答しを返す") is None


# --- 強い主張用テンプレートの照合（gate-verifier 17回目）------------------------
#
# `値の指定` と `列挙の実在` だけ、スロットが ASCII 識別子に見えるために
# 名詞句の辞書も宣言照合も飛ばしていた。


def test_a_value_template_does_not_allow_a_second_clause():
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description("success=true、locked_segmentsは巻き戻る") is None
    assert parse_description("success=true。校閲進捗バーが存在する") is None
    assert parse_description("success=true以外") is None
    assert parse_description("success=true") is not None


def test_the_written_value_must_match_the_declaration(tmp_path):
    """description が false と書いているのに expected_value が true なら嘘。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_value", description="success=false",
              endpoint="POST /api/x", response_field="success",
              expected_value="true"),
    ]))

    assert [r.reason for r in report.mismatched] == ["slot_not_declared"]


def test_the_written_field_must_match_the_declaration(tmp_path):
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_value", description="hook_score=0.9",
              endpoint="POST /api/x", response_field="success",
              expected_value="true"),
    ]))

    assert [r.reason for r in report.mismatched] == ["slot_not_declared"]


def test_an_enumeration_must_match_the_declared_literals(tmp_path):
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "value_constraint",
              description="4カテゴリ(a/b/c/d)が存在する",
              endpoint="GET /api/x", value_literals=["a", "b", "c"]),
    ]))

    assert [r.reason for r in report.mismatched] == ["slot_not_declared"]


# --- 名詞句に埋め込まれたフィールド名・経路（gate-verifier 18回目）---------------


def test_a_field_name_buried_in_a_noun_phrase_is_matched(tmp_path):
    """`候補にtimestamp…` の timestamp も宣言と突き合わせる。

    スロット全体が ASCII 識別子のときしか見ていなかったので、`候補に` を
    足すだけで照合が消えた——同じ主張が書き方の違いで強弱に振れる型。
    """
    def _row(field):
        return audit(_stories(tmp_path, [
            _item("O1-L1-01", "response_field",
                  description="候補にtimestampフィールドが存在する",
                  endpoint="GET /api/smartcut/all-candidates",
                  response_field=field, value_note="timestamp はフィールド名"),
        ]))

    assert [r.reason for r in _row("type").mismatched] == ["slot_not_declared"]
    assert _row("timestamp").mismatched == []


def test_an_acronym_is_not_treated_as_a_field_name():
    """`BGM` `SEO` `API` は名前の一部。小文字スネークだけをフィールド名と読む。"""
    from backend.ux_verification.claim_audit import _FIELD_LIKE

    assert _FIELD_LIKE.match("timestamp")
    assert not _FIELD_LIKE.match("BGM")
    assert not _FIELD_LIKE.match("SEO")
    assert not _FIELD_LIKE.match("Whisper")


def test_a_phrase_must_point_at_its_registered_endpoint(tmp_path):
    """`動画一覧API` に別の経路を宣言しても通っていた（18回目）。"""
    def _row(endpoint):
        return audit(_stories(tmp_path, [
            _item("O1-L1-01", "route_exists",
                  description="動画一覧APIが正常応答を返す", endpoint=endpoint),
        ]))

    assert [r.reason for r in _row("GET /api/health").mismatched] == ["slot_not_declared"]
    assert _row("GET /api/pipeline/videos").mismatched == []


def test_an_identifier_slot_is_only_exempt_where_it_is_cross_checked():
    """ASCII 識別子の免除は「宣言と突き合わされるテンプレート」に限る（19回目）。

    照合が走らないテンプレート（経路のみ・リクエスト契約・保存キーの実在）で
    免除していたので、主語と測る対象が無関係でも通った。
    ハイフンをアンダースコアに替えるだけで検査が消えていた。
    """
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description("analyze_scriptAPIが正常応答する") is None
    assert parse_description("localStorageにhistory_keyが存在する") is None
    assert parse_description("target_durationを受け取る") is None


def test_the_endpoint_registry_is_scoped_per_template(tmp_path):
    """同じ名詞句でもテンプレートが違えば指す経路が違う。

    `locked_segments` は「経路＋フィールド」では lock、「経路＋状態遷移」では
    unlock を指す。名詞句だけで引くと取り違える。
    """
    from backend.ux_verification.claim_audit import PHRASE_ENDPOINTS

    assert all(isinstance(k, tuple) and len(k) == 2 for k in PHRASE_ENDPOINTS)


# --- 前置と純粋 UI 名（gate-verifier 20回目）------------------------------------


def test_the_prefix_endpoint_is_matched(tmp_path):
    """`固定APIが正常応答し…` の前置が経路と突き合わされていなかった。"""
    def _row(endpoint):
        return audit(_stories(tmp_path, [
            _item("O1-L1-01", "response_field",
                  description="固定APIが正常応答しlocked_segmentsが返る",
                  endpoint=endpoint, response_field="locked_segments"),
        ]))

    assert [r.reason for r in _row("POST /api/smartcut/unlock").mismatched] == [
        "slot_not_declared"]
    assert _row("POST /api/smartcut/lock").mismatched == []


def test_an_identifier_prefix_is_not_exempt():
    """免除はスロットだけ。prefix はどこでも照合されないので登録が要る。"""
    from backend.ux_verification.claim_audit import parse_description

    assert parse_description("unlock_api正常応答しlocked_segmentsを返す") is None


def test_a_plain_ui_name_is_a_dom_claim_only(tmp_path):
    """純粋な UI 名に response_field を貼れば、無関係な API で緑にできた。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field", description="進捗バーが存在する",
              endpoint="GET /api/render/health", response_field="status"),
    ]))

    assert [r.reason for r in report.mismatched] == ["claim_too_weak"]


# --- 略称を含む UI 名と列挙の件数（gate-verifier 21回目）------------------------


def test_a_ui_name_with_an_acronym_is_still_a_dom_claim(tmp_path):
    """`CTR予測` `SEOスコア` は UI 名。大文字略称で固定から漏れていた。"""
    report = audit(_stories(tmp_path, [
        _item("O1-L1-01", "response_field", description="CTR予測が存在",
              endpoint="GET /api/pipeline/videos", response_field="videos",
              value_note="CTR は指標の名前"),
    ]))

    assert [r.reason for r in report.mismatched] == ["claim_too_weak"]


def test_the_enumeration_count_must_match(tmp_path):
    """先頭の件数がどの層でも照合されず「99カテゴリ」と主張できた。"""
    def _row(desc):
        return audit(_stories(tmp_path, [
            _item("O1-L1-01", "value_constraint", description=desc,
                  endpoint="GET /api/pipeline/quality-gate/scores",
                  value_literals=["audio", "video"]),
        ]))

    assert [r.reason for r in _row("99カテゴリ(audio/video)が存在する").mismatched] == [
        "slot_not_declared"]
    assert _row("2カテゴリ(audio/video)が存在する").mismatched == []
