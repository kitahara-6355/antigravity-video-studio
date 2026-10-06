"""字幕の仕上げ（2026-10-06 ユーザー指摘・恒久対策）。

- 句読点を出さない
- 「では」など話題に掛からない文頭語は「、」が無くても外す
- 字幕の切れ目は行の折り目より優先（「この対談では、/各界で」＋「ご活躍…」を作らない）
- 校閲（AI）が落ちたバッチは分けて再実行し、残れば品質ゲートが合格させない
- 辞書の hint は機械的に置き換えず、校閲に文脈で判断させる
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from subtitle_engine import text_formatter as tf  # noqa: E402


@pytest.mark.parametrize("text,expected", [
    ("はい、いえいえ。", "はい　いえいえ"),
    ("こんにちは、\n書家の北原美麗です。", "こんにちは\n書家の北原美麗です"),
    ("本当ですか？", "本当ですか？"),
    ("。", ""),
])
def test_strip_punctuation(text, expected):
    assert tf.strip_punctuation(text) == expected


def test_bare_lead_word_is_removed_without_comma():
    assert tf.strip_lead_words("では記念すべき第1回目", [], ["では"]) == "記念すべき第1回目"
    assert tf.strip_lead_words("では\n記念すべき", [], ["では"]) == "記念すべき"
    # 後ろにひらがなが続くのは別の語（「ではありません」）
    assert tf.strip_lead_words("ではありません", [], ["では"]) == "ではありません"
    # 文の途中の「では」は残す
    assert tf.strip_lead_words("この対談では各界の", [], ["では"]) == "この対談では各界の"


def test_default_rules_drop_dewa_and_punctuation():
    from template_constants import _DEFAULT_SUBTITLE_RULES as rules
    assert "では" in rules["omit_lead_words_bare"]
    assert rules["strip_punctuation"] is True


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_caption_break_beats_line_break():
    caps = tf.split_into_captions(
        "今回から始まるこの対談では、各界でご活躍されている方をお招きし、"
        "大切にされている言葉を書いていただきます。", 15, 2)
    assert caps[0].replace("\n", "").endswith("対談では、")
    assert not any(c.replace("\n", "").endswith("各界で") for c in caps)


def test_hint_entries_are_not_replaced_mechanically(tmp_path):
    import json
    from proper_noun_dict import ProperNounDictionary
    path = tmp_path / "pn.json"
    path.write_text(json.dumps({"version": 1, "entries": [
        {"id": "a", "incorrect": "読んでいただいて", "correct": "呼んでいただいて", "type": "hint"},
        {"id": "b", "incorrect": "初会", "correct": "初回", "type": "word"},
    ]}, ensure_ascii=False), encoding="utf-8")
    d = ProperNounDictionary(path)
    text, fixes = d.apply_corrections("本を読んでいただいて初会の")
    assert text == "本を読んでいただいて初回の"
    assert [f["corrected"] for f in fixes] == ["初回"]


def test_failed_batches_are_split_and_retried():
    from agents.workers.proofread_worker import _repair_failed_batches
    segs = [{"text": f"t{i}"} for i in range(8)]
    calls = []

    def fake(sub, return_stats=True):
        calls.append(len(sub))
        # 4行のまとまりは落ちる。2行なら通る
        if len(sub) > 2:
            return sub, {"failed_batches": 1, "accepted_items": 0}
        for s in sub:
            s["text"] += "!"
        return sub, {"failed_batches": 0, "accepted_items": len(sub)}

    stats = _repair_failed_batches(segs, {"failed_ranges": [[0, 8]], "failed_batches": 1}, fake)
    assert stats["failed_batches"] == 0 and stats["failed_ranges"] == []
    assert all(s["text"].endswith("!") for s in segs)
    assert calls[:2] == [4, 4]


def test_unrepaired_batches_stay_failed():
    from agents.workers.proofread_worker import _repair_failed_batches
    segs = [{"text": "x"} for _ in range(4)]
    stats = _repair_failed_batches(segs, {"failed_ranges": [[0, 4]], "failed_batches": 1},
                                   lambda sub, return_stats=True: (sub, {"failed_batches": 1}))
    assert stats["failed_batches"] > 0


def test_quality_gate_blocks_unproofread_subtitles(tmp_path, monkeypatch):
    from quality_gate_plugins import SubtitleCoverageCheck
    from subtitle_engine import coverage
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    monkeypatch.setattr(coverage, "check_media",
                        lambda *a, **k: coverage.CoverageReport(10.0, 5.0, 0.0))
    ctx = SimpleNamespace(segments=[{"text": "a", "start": 0, "end": 1}], video_path=str(media),
                          preview_path=None, verified_quiet=[], transcript_coverage=None,
                          proofread_failed_ranges=[[0, 50]])
    result = SubtitleCoverageCheck().analyze(ctx)
    assert result["blocking"] is True
    assert any("未校閲" in f for f in result["feedback"])


@pytest.mark.parametrize("orig,new,ok", [
    ("います。", "では記念すべき第1回めのゲストは日本デザイン", False),   # 番号ずれ（実走）
    ("こんにちは。もう初会ね。読んでいただいて。", "こんにちは。もう初回ね。呼んでいただいて。", True),
    ("えー、あの、そうですね", "そうですね", True),
    ("先生どうぞよろしく", "先生、どうぞよろしく。", True),
])
def test_proofread_rejects_text_from_another_line(orig, new, ok):
    from subtitle_engine.ai_proofreader import _plausible_correction
    assert _plausible_correction(orig, new) is ok


def test_flash_caption_is_merged_into_neighbour():
    from subtitle_engine import sync
    items = [{"start": 0.0, "end": 2.0, "text": "お腹が"},
             {"start": 2.07, "end": 2.4, "text": "すくようになった"},
             {"start": 3.5, "end": 5.0, "text": "次の文"}]
    n = sync._merge_flashes(items, 0.8)
    assert n == 1 and items[0]["text"] == "お腹が\nすくようになった" and items[0]["end"] == 2.4


def test_punctuation_only_caption_is_dropped():
    out = tf.format_segments([{"text": "。", "start": 0.0, "end": 1.0},
                              {"text": "次です。", "start": 1.0, "end": 2.0}], 15)
    if tf._strip_punctuation_enabled():
        assert [s["text"] for s in out] == ["次です"]


def test_flash_caption_is_rewrapped_into_a_two_line_neighbour():
    # 実例（2分36秒）: 「もう強烈な」が 0.49 秒で消えた。隣は2行なので行として足せなかった。
    # 2つを続けて1枚（2行・1行18字）に組み直せるなら、そうする
    from subtitle_engine import sync
    items = [{"start": 0.0, "end": 0.4, "text": "もう強烈な"},
             {"start": 0.47, "end": 3.5, "text": "それのが\n良かったんじゃないですか？"}]
    n = sync._merge_flashes(items, 0.8, max_chars=18, max_lines=2)
    assert n == 1
    text = items[1]["text"]
    assert text.replace("\n", "").replace("\u3000", "") == "もう強烈なそれのが良かったんじゃないですか？"
    assert text.count("\n") <= 1 and all(len(line) <= 18 for line in text.split("\n"))
    assert items[1]["start"] == 0.0


def test_flash_caption_that_does_not_fit_stays():
    from subtitle_engine import sync
    items = [{"start": 0.0, "end": 0.4, "text": "知って初めて書く"},
             {"start": 0.47, "end": 3.5,
              "text": "だからもう頭の中は整理できてるから\n書くのは30分か40分か"}]
    assert sync._merge_flashes(items, 0.8, max_chars=18, max_lines=2) == 0


@pytest.mark.parametrize("orig,new,neighbours,ok", [
    # かなだけの行を漢字に直すのは変換の直し（2026-10-06 実走で「単純」を捨てていた）
    ("たんじゅ、たんじゅ。", "単純、単純。", (), True),
    # ただし隣の行の文なら番号ずれ
    ("います。", "では記念すべき第1回めのゲストは日本デザイン", ("", "では記念すべき第1回目のゲストは日本デザイン"), False),
    ("たんじゅ、たんじゅ。", "記念すべき第一回目", ("記念すべき第一回目のゲスト", ""), False),
    # 漢字を含む行を別の文にするのは、これまでどおり捨てる
    ("新版画賞と、あと 2 日後これ工事って言", "新版画賞と、あと二兎を追う者は一兎をも得", (), False),
])
def test_kana_line_may_be_converted_to_kanji(orig, new, neighbours, ok):
    from subtitle_engine.ai_proofreader import _plausible_correction
    assert _plausible_correction(orig, new, neighbours) is ok


def test_echo_of_a_word_cut_by_the_chunk_boundary_is_dropped():
    # 実例（30 秒）: 30 秒ごとに切って起こすと、境目をまたいだ「まいります」の尻尾が
    # 次の区切りの頭に「います。」として残り、「では」の所に字幕が出た
    from subtitle_engine import gemini_transcriber as gt
    segs = [{"start": 23.1, "end": 29.8, "text": "皆さまにお届けしてまいります。"},
            {"start": 30.0, "end": 31.2, "text": "います。"},
            {"start": 31.2, "end": 43.7, "text": "では記念すべき"}]
    assert [s["text"] for s in gt.drop_boundary_echoes(segs, 30)] == [
        "皆さまにお届けしてまいります。", "では記念すべき"]


def test_segment_at_a_boundary_that_is_not_an_echo_stays():
    from subtitle_engine import gemini_transcriber as gt
    segs = [{"start": 23.1, "end": 29.8, "text": "はい。"},
            {"start": 30.0, "end": 31.2, "text": "います。"},
            {"start": 40.0, "end": 41.0, "text": "はい。"}]
    assert len(gt.drop_boundary_echoes(segs, 30)) == 3


def test_shifted_line_is_never_rescued_by_the_referee():
    from subtitle_engine.ai_proofreader import _correction_verdict
    assert _correction_verdict("います。", "では記念すべき第1回めのゲストは日本デザイン",
                               ["", "では記念すべき第1回目のゲストは日本デザイン"]) == "shifted"
    assert _correction_verdict("歌詞織 です ギャラ は", "菓子折り、ギャラは", []) == "dissimilar"
    assert _correction_verdict("もう初会ね", "もう初回ね", []) == "ok"


def test_lead_word_at_the_head_of_a_later_caption_is_removed():
    # 実例（39分17秒）: 「…思ってるところで、じゃあ筆が本当に入ってこなかったら…」を
    # 分けた2枚目が「じゃあ筆が」で始まった
    text = "で、ちょっと大変なことになるなって思ってるところで、じゃあ筆が本当に入ってこなかったら、筆作ろうかなみたいな。"
    out = tf.format_segments([{"text": text, "start": 0.0, "end": 8.0}], 18)
    assert out and not any(s["text"].startswith("じゃあ") for s in out)


@pytest.mark.parametrize("text,expected", [
    ("あの", True),
    ("えー、あの。", True),
    ("えっと", True),
    ("あの映画のタイトル", False),
])
def test_filler_only_caption_is_not_shown(text, expected):
    # 実例（4分02秒）: 「あの」だけの字幕が 0.9 秒出た。音声認識にも聞こえていない
    from template_constants import _DEFAULT_SUBTITLE_RULES as rules
    assert tf.is_standalone_omittable(text, rules["omit_standalone_words"]) is expected


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_a_lone_kanji_is_not_split_from_its_compound():
    # 実例（56 秒）: BudouX が「一般社団法人」を「一般社団法｜人」と分け、
    # 行の折り目が「一般社団法\n人日本デザイン…」になった
    caps = tf.split_into_captions(
        "を主宰されていて、そして、一般社団法人日本デザイン書道作家協会の理事長で", 18, 2)
    lines = [line for c in caps for line in c.split("\n")]
    assert not any(line.startswith("人") for line in lines)
    assert any("一般社団法人" in line for line in lines)
