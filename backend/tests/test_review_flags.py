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


# --- ほかの聞き取りも使う（2026-10-19） ---------------------------------------------------------
# 台帳の直し26件（ゼロからの版でまだ要る所）のうち、音声認識との食い違いだけでは20件にしか印が
# 付かなかった。2回目・3回目の起こしとの食い違いも見ると24件（残り2件は表記と、後の直しで
# 取り消した直し）。正しい字が別の聞き取りに出ていた所は11件あり、候補から選ぶだけで直せる。

def _segs(*rows):
    return [{"start": a, "end": b, "text": t} for t, a, b in rows]


def test_a_caption_two_other_readings_disagree_with_is_flagged_with_their_words_as_options():
    caps = _caps(("寒いわ　暑いわ　焦るわ", 710.0, 713.0), ("ご飯食べましょう", 713.0, 715.0))
    sources = {
        "音声認識": _tokens("寒いわ暑いわ焦るわご飯食べましょう", 710.0, 715.0),
        "2回目": review_flags.reading_tokens(_segs(("寒いわ、暑いわ、折れるわ。ご飯食べましょう。", 710.0, 715.0))),
        "3回目": review_flags.reading_tokens(_segs(("寒いわ暑いわ折れるわ", 710.0, 713.0))),
    }
    flags = review_flags.flag_with_readings(caps, sources)
    assert [f["i"] for f in flags] == [0]
    assert flags[0]["by"] == ["2回目", "3回目"]
    assert flags[0]["tier"] == 1
    assert [o["t"] for o in flags[0]["options"]] == ["寒いわ　暑いわ　折れるわ"]
    assert flags[0]["options"][0]["by"] == ["2回目", "3回目"]


def test_a_caption_only_the_recogniser_disagrees_with_is_flagged_in_the_second_tier():
    caps = _caps(("藤田さん", 573.0, 575.0),)
    sources = {"音声認識": _tokens("久木田さん", 573.0, 575.0),
               "2回目": review_flags.reading_tokens(_segs(("藤田さん。", 573.0, 575.0)))}
    flags = review_flags.flag_with_readings(caps, sources)
    assert [(f["i"], f["tier"], f["by"]) for f in flags] == [(0, 2, ["音声認識"])]
    assert [o["t"] for o in flags[0]["options"]] == ["久木田さん"]


def test_one_reading_alone_other_than_the_recogniser_does_not_flag():
    caps = _caps(("今日ね初めての", 2567.0, 2569.0),)
    sources = {"音声認識": _tokens("今日ね初めての", 2567.0, 2569.0),
               "2回目": review_flags.reading_tokens(_segs(("去年初めてですね", 2567.0, 2569.0)))}
    assert review_flags.flag_with_readings(caps, sources) == []


def test_the_review_sheet_flags_with_the_readings_when_given():
    sidecar = {"segments": [{"start": 0.0, "end": 3.0, "text": "暑いわ　焦るわ"}], "ranges": [[710.0, 713.0]]}
    readings = {"2回目": _segs(("暑いわ、折れるわ。", 710.0, 713.0)), "3回目": _segs(("暑いわ折れるわ", 710.0, 713.0))}
    sheet = review_sheet.export(sidecar, "z", "ゼロ", "v.mp4", _tokens("暑いわ焦るわ", 710.0, 713.0), readings=readings)
    assert [(f["i"], f["tier"]) for f in sheet["flags"]] == [(0, 1)]
    assert sheet["flags"][0]["options"][0]["t"] == "暑いわ　折れるわ"


def test_rows_read_again_over_overlapping_windows_are_not_interleaved():
    """3回目の読み直しは窓が重なる。字を時刻で並べると2つの窓の字が交互に混ざった（「主の催先さ生れが」）。"""
    toks = review_flags.reading_tokens(_segs(("主催されている", 1030.0, 1034.0), ("主催されている", 1030.5, 1034.5)))
    assert "".join(ch for ch, _ in toks) == "主催されている"


def test_an_option_keeps_the_gaps_and_line_breaks_of_the_caption():
    """候補はそのまま「正しくは」に入るので、字幕の空白と改行は残し、違う字だけを替える。"""
    assert review_flags.patched("暑いわ　焦るわ", "暑いわ折れるわ") == "暑いわ　折れるわ"
    assert review_flags.patched("それで来年は\nユネスコに　10月にはね", "それで来年はユネスコに11月にはね") == \
        "それで来年は\nユネスコに　11月にはね"
    assert review_flags.patched("藤田さん", "久木田さん") == "久木田さん"


def test_a_different_number_gets_the_number_of_the_other_reading_as_its_option():
    caps = _caps(("なるであろうね　10月にはね", 1083.0, 1086.0),)
    sources = {"音声認識": _tokens("なるであろうね十一月にはね", 1083.0, 1086.0),
               "2回目": review_flags.reading_tokens(_segs(("なるであろうね、11月にはね。", 1083.0, 1086.0)))}
    flags = review_flags.flag_with_readings(caps, sources)
    assert [(o["t"], o["by"]) for o in flags[0]["options"]] == \
        [("なるであろうね　十一月にはね", ["音声認識"]), ("なるであろうね　11月にはね", ["2回目"])]
