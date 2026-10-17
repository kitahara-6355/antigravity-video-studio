"""機械の要確認: 字幕と別の音声認識が食い違う字幕に印を付ける（2026-10-17）。

北原さんの14か所の多くは、音声認識（ReazonSpeech）が正しく聞いていた所を、文字起こしか校閲が別の字に
していた。通しで見る人に、食い違う所を先に示す。
"""
from subtitle_engine import review_flags, review_sheet


def _tokens(text, a, b):
    step = (b - a) / max(1, len(text))
    return [[ch, round(a + k * step, 2)] for k, ch in enumerate(text)]


def _caps(*rows):
    return [{"i": k, "t": t, "a": a, "b": b} for k, (t, a, b) in enumerate(rows)]


def test_a_caption_whose_words_the_recogniser_heard_differently_is_flagged():
    caps = _caps(("ケータリングが入ってるんで", 570.0, 573.0), ("藤田さん", 573.0, 575.0),
                 ("ご飯食べましょうかって言って", 575.0, 578.0))
    toks = _tokens("ケータリングが入ってるんで", 570.0, 573.0) + _tokens("久木田さん", 573.0, 575.0) \
        + _tokens("ご飯食べましょうかって言って", 575.0, 578.0)
    flags = review_flags.flag_captions(caps, toks)
    assert [f["i"] for f in flags] == [1]
    assert "藤田" in flags[0]["why"] and "久木田" in flags[0]["why"]


def test_a_different_number_is_flagged_even_when_written_another_way():
    caps = _caps(("それで来年はユネスコ無形文化遺産に", 1080.0, 1083.0), ("なるであろうね　10月にはね", 1083.0, 1086.0))
    toks = _tokens("それで来年はユネスコ無形文化遺産に", 1080.0, 1083.0) + _tokens("なるであろうね十一月にはね", 1083.0, 1086.0)
    assert [f["i"] for f in review_flags.flag_captions(caps, toks)] == [1]


def test_the_same_words_in_another_spelling_are_not_flagged():
    caps = _caps(("分かりました　8歳です", 10.0, 13.0), ("コピーライター", 13.0, 15.0))
    toks = _tokens("わかりました八歳です", 10.0, 13.0) + _tokens("こぴーらいたー", 13.0, 15.0)
    assert review_flags.flag_captions(caps, toks) == []


def test_number_values_read_kanji_numerals():
    assert [review_flags.number_value(t) for t in ("十一", "二千二十", "20万", "四千万", "23")] == \
        [11, 2020, 200000, 40000000, 23]


def test_the_review_sheet_carries_the_flags_when_given_the_recogniser_tokens():
    sidecar = {"segments": [{"start": 0.0, "end": 2.0, "text": "藤田さん"}], "ranges": [[573.0, 575.0]]}
    sheet = review_sheet.export(sidecar, "r53", "53回目", "v.mp4", _tokens("久木田さん", 573.0, 575.0))
    assert [f["i"] for f in sheet["flags"]] == [0]
    assert "flags" not in review_sheet.export(sidecar, "r53", "53回目", "v.mp4")
