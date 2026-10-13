"""表記の揺れを、動画の中で多い方の書き方にそろえる（2026-10-13）。

33回目の字幕は「僕」53・「ぼく」2、「分かる」8・「わかる」5 のように、同じ語が字幕によって
書き分けられていた。校閲（AI）は100行ずつ見るので、動画全体の書き方はそろわない。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from subtitle_engine import notation  # noqa: E402

GROUPS = [
    {"forms": ["僕", "ぼく"], "after": "はがのもにをとでだやへらかねよっさな", "noun": True},
    {"forms": ["分か", "わか"], "after": "らりるろっん"},
    {"forms": ["良か", "よか"], "after": "っろ"},
    {"forms": ["うれし", "嬉し"], "after": "いかくけさそ"},
]


def segs(*texts):
    return [{"start": float(i), "end": float(i) + 1, "text": t} for i, t in enumerate(texts)]


def texts(ss):
    return [s["text"] for s in ss]


def test_the_minority_spelling_takes_the_majority_one():
    # 実例（33回目）: 3分10秒の「ぼくはね」だけがひらがなで、ほかは「僕」
    ss = segs("僕が幼稚園から", "ぼくはね、中学校入ってね", "僕のデビューなんですよ")
    assert notation.unify_notation(ss, GROUPS) == {"ぼく→僕": 1}
    assert texts(ss) == ["僕が幼稚園から", "僕はね、中学校入ってね", "僕のデビューなんですよ"]


def test_a_verb_stem_is_unified_with_its_endings():
    ss = segs("誰が書いたか分かんないけど", "はい、わかりました", "見たらわかります？", "もう分からないけど",
              "分かる分かるっていうような")
    assert notation.unify_notation(ss, GROUPS) == {"わか→分か": 2}
    assert texts(ss)[1:3] == ["はい、分かりました", "見たら分かります？"]


def test_a_tie_goes_to_the_first_spelling_in_the_group():
    # 「嬉」は常用漢字表に無いので、組の最初は「うれし」
    ss = segs("そういうところが嬉しいですね", "うれしいね")
    assert notation.unify_notation(ss, GROUPS) == {"嬉し→うれし": 1}
    assert texts(ss)[0] == "そういうところがうれしいですね"


def test_the_same_letters_inside_another_word_are_left_alone():
    # 「自分から」の「分か」、「こわかった」の「わか」、「40分かな」「40分から」は別の語の一部
    ss = segs("わかりました", "わかんない", "分かった", "自分からやるんです", "すごくこわかったです",
              "30分とか40分かな", "40分からスタート")
    assert notation.unify_notation(ss, GROUPS) == {"分か→わか": 1}
    assert texts(ss)[2:] == ["わかった", "自分からやるんです", "すごくこわかったです",
                             "30分とか40分かな", "40分からスタート"]


def test_a_different_word_with_the_same_head_is_left_alone():
    # 「わかれば」は数えない（「別れ」と分けられない）。「若い」「わかめ」は別の語
    ss = segs("分かります", "分かった", "わかれば", "若い人が", "わかめ")
    assert notation.unify_notation(ss, GROUPS) == {}
    assert texts(ss)[2:] == ["わかれば", "若い人が", "わかめ"]


def test_a_quote_or_a_space_starts_a_word():
    ss = segs("「よかった」っていう話よ", "そこまでは　よかったんですけど", "それが良かったんじゃないですか？")
    assert notation.unify_notation(ss, GROUPS) == {"良か→よか": 1}
    assert texts(ss)[2] == "それがよかったんじゃないですか？"


def test_nothing_changes_when_only_one_spelling_is_used():
    ss = segs("僕は", "僕が", "わかりました")
    assert notation.unify_notation(ss, GROUPS) == {}
    assert texts(ss) == ["僕は", "僕が", "わかりました"]


def test_the_spellings_live_in_the_template_rules():
    from template_config import template_config

    groups = template_config.get_subtitle_rules()["notation_variants"]
    forms = [g["forms"] for g in groups]
    assert ["僕", "ぼく"] in forms and ["分か", "わか"] in forms
    assert all(len(f) >= 2 for f in forms)
    assert notation.unify_notation(segs("僕は", "ぼくが", "僕の")) == {"ぼく→僕": 1}


def test_the_proofread_step_unifies_before_formatting(monkeypatch):
    from agents.workers import proofread_worker
    from subtitle_engine import ai_proofreader
    from tests.fixtures.mock_pipeline import create_mock_ctx

    monkeypatch.setattr(proofread_worker, "_referee_for", lambda video_path: None)
    monkeypatch.setattr(proofread_worker, "_memo_for", lambda video_path: None)
    monkeypatch.setattr(ai_proofreader, "proofread_segments",
                        lambda segs_, return_stats=True, **kw: (segs_, {"total_batches": 1}))
    ctx = create_mock_ctx(segments=0)
    ctx.segments = segs("僕が幼稚園から", "ぼくはね、中学校入ってね", "僕のデビューなんですよ")
    result = asyncio.run(proofread_worker.ProofreadWorker().execute(ctx))
    assert "ぼく" not in "".join(s["text"] for s in ctx.segments)
    assert result.data["notation"] == {"ぼく→僕": 1}
    assert "表記1件" in result.detail
