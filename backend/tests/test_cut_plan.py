"""切る所の決め方（`cut_plan`）。

2026-10-13 ユーザー指摘:
- 「26秒『まいります』の発話フレーズの最後の言葉が切れている」
- 「冒頭1分10秒までの『あいさつ・ゲスト紹介』までのフレーズは、ノーカットの方が感じが良い」

中身を全部残すようにしたら、収録の段取りの声（37分38秒「ちょっと切ります」「撮った？」）が
出てきたので外す規則も足した。
"""
import sys
from pathlib import Path

import numpy as np
import pytest

_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

import cut_plan
from subtitle_engine.sync import SpeechMap

RULES = {"pad_before_sec": 0.15, "pad_after_sec": 0.25, "min_cut_sec": 0.3,
         "max_shift_sec": 2.0, "keep_opening": True, "opening_max_sec": 180.0}


def _audio(runs, duration=None, levels=None):
    """声の区間 runs（素材の秒）から、10ms ごとの音量と声の地図を作る。"""
    duration = duration if duration is not None else (runs[-1][1] + 5.0 if runs else 10.0)
    n = int(round(duration / cut_plan.FRAME_SEC))
    if levels is None:
        levels = np.full(n, -60.0)
        for on, off in runs:
            levels[int(round(on / cut_plan.FRAME_SEC)):int(round(off / cut_plan.FRAME_SEC))] = -20.0
    speech = SpeechMap(onsets=[a for a, _ in runs], offsets=[b for _, b in runs], duration=duration)
    return cut_plan.SourceAudio(levels=levels, speech=speech)


def _snap(ranges, audio, cut_through_voice=False, walls=(), **over):
    rules = dict(RULES, **over)
    out, _ = cut_plan.snap_to_pauses(ranges, audio, rules, cut_through_voice=cut_through_voice,
                                     walls=walls)
    return [(round(a, 2), round(b, 2)) for a, b in out]


# ------------------------------------------------------------------
# 声の中で切らない
# ------------------------------------------------------------------

def test_the_26_second_cut_keeps_the_end_of_the_phrase():
    """37回目の 26秒: 文字起こしの区間は 30.04 秒で終わり、声（「ます」）は 30.33 秒まで続いていた。"""
    audio = _audio([(27.00, 30.33), (31.56, 32.11)])
    out = _snap([(13.0, 30.04), (31.04, 46.04)], audio)
    assert out[0][1] == pytest.approx(30.33 + 0.25)
    assert out[1][0] == pytest.approx(31.04), "話し始めの前は十分空いているので動かさない"


def test_a_cut_never_starts_inside_the_voice():
    audio = _audio([(10.0, 12.0), (14.2, 16.0)])
    out = _snap([(9.0, 12.5), (14.6, 20.0)], audio)
    assert out[1][0] == pytest.approx(14.2 - 0.15)


def test_the_voice_running_across_the_gap_is_never_cut():
    """発話の区間の間でも、声が途切れずに続いていれば切らない（81秒の質問と答えの継ぎ目）。"""
    audio = _audio([(80.79, 82.69)])
    out = _snap([(74.94, 81.14), (81.64, 90.64)], audio)
    assert out == [(74.94, 90.64)]


def test_a_pause_too_short_to_cut_after_padding_is_kept():
    # 声の終わり 10.0・次の話し始め 10.5 → 余白を残すと切れるのは 0.1 秒だけ
    audio = _audio([(8.0, 10.0), (10.5, 12.0)])
    out = _snap([(7.0, 9.8), (10.4, 13.0)], audio)
    assert out == [(7.0, 13.0)]


def test_ranges_are_only_ever_extended():
    """字幕は発話の区間で残す区間に割り当てるので、区間を縮めると字幕が落ちる。"""
    audio = _audio([(10.0, 11.0), (20.0, 21.0)])
    out = _snap([(9.0, 12.0), (19.0, 22.0)], audio)
    assert out == [(9.0, 12.0), (19.0, 22.0)]


def test_the_padding_is_kept_even_when_the_cut_was_in_a_pause():
    """区間の終わりが声の終わりのすぐ後ろ（余白より近い）なら、余白まで延ばす。"""
    audio = _audio([(10.0, 11.0), (14.0, 15.0)])
    out = _snap([(9.0, 11.1), (13.95, 16.0)], audio)
    assert out == [(9.0, 11.25), (13.85, 16.0)]


def test_the_first_start_and_the_last_end_are_padded_too():
    audio = _audio([(1.5, 4.0), (5.0, 9.0)], duration=9.1)
    out = _snap([(1.6, 3.9), (5.0, 8.5)], audio)
    assert out[0][0] == pytest.approx(1.35)
    assert out[-1][1] == pytest.approx(9.1), "素材の長さを超えない"


def _long_voice():
    levels = np.full(3000, -60.0)
    levels[1000:2600] = -20.0          # 10.0〜26.0 秒は声
    levels[1130:1150] = -45.0          # 11.3 秒あたりが一番静か（間とみなすほど長くない）
    return _audio([(10.0, 26.0), (28.0, 29.0)], duration=30.0, levels=levels)


def test_when_content_is_selected_a_long_voice_is_cut_at_its_quietest_point():
    """中身を選んで削るとき、声が max_shift_sec を超えて続くなら延ばしきらずに一番静かな所で切る
    （削った発話まで残さない）。"""
    out = _snap([(0.0, 10.5), (28.0, 29.5)], _long_voice(), cut_through_voice=True)
    assert 11.25 <= out[0][1] <= 11.5
    assert out[1] == (27.85, 29.5)


def test_when_everything_is_kept_a_long_voice_is_never_cut():
    """中身を全部残すとき、すき間の声（笑い声・起こし漏れ）は切らずに残す。"""
    out = _snap([(0.0, 10.5), (28.0, 29.5)], _long_voice())
    assert out == [(0.0, 26.25), (27.85, 29.5)]


def test_without_audio_the_ranges_are_left_alone():
    ranges = [(1.0, 2.0), (3.0, 4.0)]
    out, info = cut_plan.snap_to_pauses(ranges, None, RULES)
    assert out == ranges and info == {}


def test_snapping_reports_what_it_moved():
    audio = _audio([(27.00, 30.33), (31.56, 32.11), (40.0, 42.0)])
    _, info = cut_plan.snap_to_pauses([(13.0, 30.04), (31.04, 40.3), (40.5, 45.0)], audio, RULES)
    assert info == {"gaps": 2, "extended_end": 1, "pulled_start": 0, "joined": 1, "quiet": 0}


# ------------------------------------------------------------------
# 冒頭（あいさつ・紹介）は切らない
# ------------------------------------------------------------------

def _seg(start, end, text, **extra):
    return dict(start=start, end=end, text=text, sourceStart=start, sourceEnd=end, **extra)


OPENING = [
    _seg(1.4, 4.1, "こんにちは、書家の北原美麗です。"),
    _seg(4.9, 12.3, "このチャンネルでは書を通して人々の心に触れ、その思いを深くお聞きしていきます。"),
    _seg(46.04, 46.84, "こんにちは。"),
    _seg(67.94, 74.44, "え、著者としても筆文字デザインの書籍が多数おありだということです。"),
    _seg(74.94, 76.64, "まず先生が、"),
    _seg(76.64, 81.14, "え、最初に書に出会ったきっかけっていうのはなんかありますでしょうか？"),
    _seg(81.64, 90.64, "あの、私あの小学校3年生の時にお習字をスタートしたんですけど、"),
]


def test_the_opening_ends_where_the_sentence_of_the_first_question_begins():
    assert cut_plan.opening_end(OPENING, 180.0) == pytest.approx(74.94)


def test_the_sentence_start_is_found_after_the_punctuation_is_stripped():
    """校閲の後の字幕は句読点が外れている。文末だった印（`_ends_sentence`）で文の頭を探す。"""
    lines = [
        _seg(67.94, 74.44, "著者としても筆文字デザインの書籍が\n多数おありだということです",
             _ends_sentence=True, _ends_punct=True),
        _seg(74.94, 76.64, "まず先生が", _ends_punct=True),
        _seg(76.64, 81.14, "最初に書に\n出会ったきっかけっていうのは"),
        _seg(76.64, 81.14, "何かありますでしょうか？"),
    ]
    assert cut_plan.opening_end(lines, 180.0) == pytest.approx(74.94)


def test_no_opening_is_kept_when_the_first_question_comes_too_late():
    late = [_seg(1.0, 5.0, "こんにちは。"), _seg(200.0, 204.0, "どう思いますか？")]
    assert cut_plan.opening_end(late, 180.0) is None
    assert cut_plan.opening_end([_seg(1.0, 5.0, "こんにちは。")], 180.0) is None


def test_every_gap_before_the_theme_is_joined():
    ranges = [(1.4, 4.1), (4.9, 12.3), (13.0, 30.04), (31.04, 46.04), (46.84, 52.04),
              (52.84, 74.44), (74.94, 81.14), (81.64, 90.64), (91.5, 95.0)]
    out = cut_plan.join_opening(ranges, 74.94)
    assert out == [(1.4, 81.14), (81.64, 90.64), (91.5, 95.0)]


def test_plan_joins_the_opening_and_then_snaps_the_rest(monkeypatch):
    segs = OPENING + [_seg(95.0, 99.0, "それで興味があったんで。")]
    audio = _audio([(1.5, 4.0), (5.0, 12.4), (74.9, 82.0), (82.4, 90.9), (95.2, 99.3)], duration=100.0)
    monkeypatch.setattr(cut_plan, "read_audio", lambda path: audio)
    ranges, info = cut_plan.plan(segs, "raw.mp4", keep_all=True, rules=RULES)
    assert info["opening_until"] == pytest.approx(74.94)
    assert ranges[0][0] == pytest.approx(1.35)
    # 冒頭は1つの区間（あいさつの間も残る）。本題に入ってからは間を切る
    assert ranges[0][1] == pytest.approx(90.9 + 0.25)
    assert ranges[1][0] == pytest.approx(95.0)
    assert len(ranges) == 2


def test_plan_without_keeping_the_opening_cuts_the_greeting_pauses_too(monkeypatch):
    monkeypatch.setattr(cut_plan, "read_audio", lambda path: None)
    ranges, info = cut_plan.plan(OPENING, "raw.mp4", keep_all=False, rules=RULES)
    assert "opening_until" not in info
    assert ranges[:2] == [(1.4, 4.1), (4.9, 12.3)]


def test_rules_come_from_the_template(monkeypatch):
    class _T:
        @staticmethod
        def get_cut_rules():
            return {"pad_after_sec": 0.4, "keep_opening": False, "min_cut_sec": "x", "pad_before_sec": -1}
    import template_config
    monkeypatch.setattr(template_config, "template_config", _T())
    rules = cut_plan.cut_rules()
    assert rules["pad_after_sec"] == 0.4 and rules["keep_opening"] is False
    # 読めない値・負の値は既定のまま
    assert rules["min_cut_sec"] == cut_plan.DEFAULT_CUT_RULES["min_cut_sec"]
    assert rules["pad_before_sec"] == cut_plan.DEFAULT_CUT_RULES["pad_before_sec"]


def test_merge_ranges_matches_the_old_render_rule():
    segs = [_seg(0, 2, "あ"), _seg(2.2, 4, "い"), _seg(10, 12, "う"), _seg(11, 11.5, "え")]
    assert cut_plan.merge_ranges(segs, 0.3) == [(0, 4), (10, 12)]


# ------------------------------------------------------------------
# 収録の段取りの声
# ------------------------------------------------------------------

DEFAULT = cut_plan.DEFAULT_CUT_RULES

# 3本目の素材の終わり（37分27秒〜）。カメラを止めて、4本目で次の質問から撮り直している
TAKE_END = [
    _seg(2247.38, 2257.38, "趣味ってばそうですね。料理ですかね。はあ、素晴らしいと思います。"
                           "あの、あやかりたいと思います。私も。"),
    _seg(2258.04, 2259.24, "ちょっと切ります。"),
    _seg(2259.94, 2260.54, "ちょっと切ります。"),
    _seg(2260.94, 2261.44, "はい。"),
    _seg(2262.94, 2264.84, "ちょっと待って。いい。よし。"),
    _seg(2266.04, 2266.54, "撮った？"),
    _seg(2266.94, 2267.44, "切、止めた？"),
    _seg(2267.84, 2274.74, "えーと先生がこれからの今からやってみたいとかっていうようなことは"
                           "何かあるんでしょうか？"),
]


def test_the_talk_around_stopping_the_camera_is_found():
    assert cut_plan.production_talk(TAKE_END, DEFAULT) == {1, 2, 3, 4, 5, 6}


def test_the_misheard_cue_at_the_end_of_the_writing_scene_is_found():
    """書いている場面の終わり（30分49秒）。「撮ります」が「取ります」と起こされた。"""
    segs = [_seg(1830.24, 1833.34, "うーん"), _seg(1849.5, 1850.3, "はい。取ります。はい。"),
            _seg(1853.3, 1860.1, "はい、え、今ね、先生に素敵な字を書いていただいたので、"
                                 "ちょっと見せていただいていいですか？はい。")]
    assert cut_plan.production_talk(segs, DEFAULT) == {1}


def test_the_same_words_inside_a_sentence_are_content():
    segs = [_seg(1495.44, 1498.04, "何か、大切にしていることって。"),
            _seg(1500.0, 1503.0, "その時に写真を撮ってもらったんです。"),
            _seg(1503.5, 1504.5, "紙を切ります。")]
    assert cut_plan.production_talk(segs, DEFAULT) == set()


def test_a_reply_away_from_the_talk_is_kept():
    segs = [_seg(10.0, 11.0, "はい。"), _seg(20.0, 21.0, "撮った？"), _seg(23.5, 24.0, "はい。"),
            _seg(30.0, 31.0, "はい。")]
    assert cut_plan.production_talk(segs, DEFAULT) == {1, 2}


def test_the_lines_of_one_utterance_are_read_together():
    """校閲の整形で1つの発話が数行に分かれても、行はみな同じ sourceStart/sourceEnd を持つ。
    行だけ見ると段取りの言葉でも、発話としては中身のことがある。"""
    segs = [dict(start=5.0, end=5.6, text="撮った？", sourceStart=5.0, sourceEnd=8.0),
            dict(start=5.6, end=8.0, text="その一言に救われました", sourceStart=5.0, sourceEnd=8.0),
            dict(start=9.0, end=9.6, text="ちょっと", sourceStart=9.0, sourceEnd=10.2),
            dict(start=9.6, end=10.2, text="切ります", sourceStart=9.0, sourceEnd=10.2)]
    assert cut_plan.production_talk(segs, DEFAULT) == {2, 3}


def test_captions_without_punctuation_are_read_the_same():
    """校閲の後の字幕は句読点が外れ、行の途中は全角スペースになっている。"""
    segs = [_seg(2266.04, 2266.54, "撮った？"), _seg(2266.94, 2267.44, "切　止めた？"),
            _seg(2262.94, 2264.84, "ちょっと待って　いい　よし")]
    assert cut_plan.production_talk(segs, DEFAULT) == {0, 1, 2}


def test_a_range_is_not_extended_into_the_dropped_talk():
    """声が途切れずに段取りの声へ続いていても、外した発話の手前で一番静かな所で切る。"""
    levels = np.full(2000, -60.0)
    levels[1000:1400] = -20.0          # 10.0〜14.0 秒は声が続く
    levels[1215:1225] = -40.0          # 12.2 秒あたりが一番静か
    audio = _audio([(10.0, 14.0)], duration=20.0, levels=levels)
    out = _snap([(9.9, 12.0), (16.0, 18.0)], audio, walls=[(12.3, 14.0)])
    assert out[0][1] == pytest.approx(12.2, abs=0.06)
    assert out[1] == (16.0, 18.0)


def test_a_gap_holding_dropped_talk_is_cut_even_when_it_is_short():
    audio = _audio([(8.0, 10.0), (10.1, 10.3), (10.4, 12.0)])
    # 外さなければ、余白を残すと間が無いのでつなぐ（段取りの声が入る）
    assert _snap([(7.0, 10.0), (10.4, 13.0)], audio) == [(7.0, 13.0)]
    out = _snap([(7.0, 10.0), (10.4, 13.0)], audio, walls=[(10.1, 10.3)])
    assert len(out) == 2
    assert out[0][1] <= 10.1 and out[1][0] >= 10.3


def test_the_opening_is_not_joined_across_dropped_talk():
    ranges = [(1.4, 4.1), (4.9, 12.3), (13.0, 30.04)]
    out = cut_plan.join_opening(ranges, 20.0, walls=[(12.4, 12.9)])
    assert out == [(1.4, 12.3), (13.0, 30.04)]


def test_the_production_talk_rules_come_from_the_template(monkeypatch):
    class _T:
        @staticmethod
        def get_cut_rules():
            return {"production_cues": ["バミり"], "production_ok_words": "はい",
                    "drop_production_talk": False}
    import template_config
    monkeypatch.setattr(template_config, "template_config", _T())
    rules = cut_plan.cut_rules()
    assert rules["production_cues"] == ["バミり"] and rules["drop_production_talk"] is False
    # 一覧でない値は既定のまま。既定の一覧は書き換わらない
    assert rules["production_ok_words"] == DEFAULT["production_ok_words"]
    rules["production_ok_words"].append("x")
    assert "x" not in DEFAULT["production_ok_words"]
