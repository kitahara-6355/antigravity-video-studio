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


# ------------------------------------------------------------------
# 声は音量と音声認識の両方で見る（2026-10-14・38回目の書き出しで、すき間に認識の字が 91 字）
# ------------------------------------------------------------------

LIVE = {"pad_before_sec": 0.10, "pad_after_sec": 0.15}  # 既定の余白（切れる間は 0.55 秒から）


def _toks(text, start, step=0.15):
    return [(c, round(start + i * step, 3)) for i, c in enumerate(text)]


def test_a_soft_ending_the_recogniser_heard_is_kept():
    """素材の 7分38秒: 音量で見た声は「書くんです」の 458.0 秒で終わり、458.21 秒の「よ」が切れた。"""
    audio = _audio([(456.49, 458.0), (458.95, 459.5)], duration=470.0)
    assert _snap([(449.0, 458.0), (459.0, 465.0)], audio, **LIVE)[0][1] == pytest.approx(458.15)
    audio.heard = [457.85, 457.97, 458.09, 458.21, 458.95]
    out = _snap([(449.0, 458.0), (459.0, 465.0)], audio, **LIVE)
    assert out[0][1] == pytest.approx(458.21 + cut_plan.HEARD_CHAR_SEC + 0.15)
    # 次の発話（458.95 秒の「で」）の手前の間は切れる長さがあるので、つながない
    assert out[1][0] == pytest.approx(458.95 - 0.10)


def test_a_soft_start_the_recogniser_heard_is_kept():
    audio = _audio([(10.0, 12.0), (14.4, 16.0)])
    audio.heard = [10.5, 11.8, 14.0, 14.5]  # 14.0 秒の字は立ち上がりが弱く、音量では声の外
    out = _snap([(9.0, 12.0), (14.4, 20.0)], audio, **LIVE)
    assert out[1][0] == pytest.approx(14.0 - 0.10)


def test_a_far_recognised_character_does_not_join_a_pause():
    """認識の字でも、手前の間が切れる長さ（余白＋min_cut）あれば、声が続いているとはみなさない。"""
    audio = _audio([(10.0, 12.0), (14.4, 16.0)])
    audio.heard = [11.8, 12.8]  # 12.8 秒の字は 12.0 秒の声の終わりから 0.67 秒あと
    out = _snap([(9.0, 12.0), (14.4, 20.0)], audio, **LIVE)
    assert out[0][1] == pytest.approx(12.15)


ZONE20 = [  # 素材の 17分42秒〜18分01秒（38回目）
    dict(start=1061.58, end=1064.84, text="書道人口って　この10年で半減して",
         sourceStart=1061.58, sourceEnd=1072.08),
    dict(start=1064.84, end=1068.82, text="220万人とか何とか\n言われているんだけどさ",
         sourceStart=1061.58, sourceEnd=1072.08),
    dict(start=1068.82, end=1072.08, text="その数字って日本の人口の2%だよね",
         sourceStart=1061.58, sourceEnd=1072.08),
    dict(start=1076.58, end=1081.58, text="書道界って　それ2%の人しか相手に\nしてこなかったのよ",
         sourceStart=1076.58, sourceEnd=1081.58),
]
ZONE20_HEARD = (_toks("書道人口ってこの十年で半減して", 1062.0) + _toks("二百二十万人とか何か言われている", 1068.6)
                + _toks("はい", 1073.24, 0.48) + _toks("日本の人口の二％だよね", 1074.0, 0.212)
                + _toks("書道界ってそれ二％の人しか相手にしてこなかったのよ", 1076.7, 0.15))


def test_an_utterance_is_kept_until_its_words_were_heard(monkeypatch):
    """素材の 17分52秒: 文字起こしの発話の区間は「言われている」で終わり、「日本の人口の2%だよね」の
    4 秒を切って、字幕だけが声無しで出ていた。"""
    monkeypatch.setattr(cut_plan, "read_audio", lambda path: None)
    monkeypatch.setattr(cut_plan, "read_heard", lambda path: None)
    assert cut_plan.plan(ZONE20, "raw.mp4", keep_all=True, rules=RULES)[0][0] == (1061.58, 1072.08)
    monkeypatch.setattr(cut_plan, "read_heard", lambda path: ZONE20_HEARD)
    ranges, info = cut_plan.plan(ZONE20, "raw.mp4", keep_all=True, rules=RULES)
    last = [t for c, t in ZONE20_HEARD if c == "ね"][0]
    assert ranges[0] == (1061.58, pytest.approx(last + cut_plan.HEARD_CHAR_SEC))
    assert info["heard_widened"] == 1  # 次の発話は区間の中で聞こえているので広げない


def test_words_heard_far_from_the_utterance_are_not_its_words(monkeypatch):
    """同じ言葉が別の所で聞こえても（突き合わせが取り違えても）、発話の区間から 5 秒より先は使わない。"""
    segs = [dict(start=10.0, end=11.0, text="こんにちは", sourceStart=10.0, sourceEnd=11.0)]
    monkeypatch.setattr(cut_plan, "read_audio", lambda path: None)
    monkeypatch.setattr(cut_plan, "read_heard", lambda path: _toks("こんにちは", 20.0))
    ranges, info = cut_plan.plan(segs, "raw.mp4", keep_all=True, rules=RULES)
    assert ranges == [(10.0, 11.0)] and "heard_widened" not in info


def _talk_then_question():
    """素材の 37分38秒〜（38回目）: 段取りの声のあと、次の質問の頭が段取りの声の区間の中で聞こえる。"""
    talk = dict(start=50.0, end=53.0, text="ちょっと切ります", sourceStart=50.0, sourceEnd=53.0)
    kept = [dict(start=40.0, end=48.0, text="あやかりたいと思います", sourceStart=40.0, sourceEnd=48.0),
            dict(start=53.5, end=56.0, text="先生がこれからやってみたいことは", sourceStart=53.5, sourceEnd=56.0)]
    heard = (_toks("あやかりたいと思います", 46.0) + _toks("ちょっと切ります", 50.2, 0.12)
             + _toks("先生がこれからやってみたいことは", 52.0))
    return talk, kept, heard


def test_dropped_talk_blocks_only_where_its_words_were_heard(monkeypatch):
    talk, kept, heard = _talk_then_question()
    monkeypatch.setattr(cut_plan, "read_audio", lambda path: None)
    monkeypatch.setattr(cut_plan, "read_heard", lambda path: heard)
    ranges, _ = cut_plan.plan(kept, "raw.mp4", keep_all=False, rules=RULES, exclude=[talk])
    assert ranges[1][0] == pytest.approx(52.0)
    # 区間だけ渡されたら（言葉が分からない）、その区間の向こうまでは広げない
    ranges, _ = cut_plan.plan(kept, "raw.mp4", keep_all=False, rules=RULES, exclude=[(50.0, 53.0)])
    assert ranges[1][0] == pytest.approx(53.0)


def test_the_recogniser_is_read_only_for_a_real_file(tmp_path):
    assert cut_plan.read_heard(None) is None
    assert cut_plan.read_heard(str(tmp_path / "missing.mp4")) is None


# --- だれも話さない場面（2026-10-14 字を書く場面）--------------------------------------------

WRITING = [_seg(1789.76, 1794.46, "先生に　今から書いていただきます"),
           _seg(1821.38, 1826.78, "はい"),
           _seg(1853.30, 1860.10, "はい　今ね　先生に素敵な字を書いていただいたので")]
SCENE_RULES = dict(RULES, keep_scenes=True, scene_min_sec=10.0)


def test_a_long_stretch_where_nobody_speaks_is_kept_as_a_scene():
    # 先生が字を書く約1分。間を詰めると、書き始めと「はい」の前後の約10秒だけになっていた
    ranges, info = cut_plan.plan(WRITING, None, keep_all=True, rules=SCENE_RULES)
    assert ranges == [(1789.76, 1860.10)]
    assert info["scenes"] == [(1794.46, 1821.38), (1826.78, 1853.30)]


def test_the_production_talk_inside_a_scene_is_still_cut():
    # 書く場面の終わりの「はい。取ります。はい。」（段取りの声）は外したまま。そこから後ろの
    # 3 秒は場面にならない
    ranges, info = cut_plan.plan(WRITING, None, keep_all=True, rules=SCENE_RULES,
                                 exclude=[(1849.50, 1850.30)])
    assert ranges == [(1789.76, pytest.approx(1849.50 - RULES["pad_before_sec"])), (1853.30, 1860.10)]
    assert info["scenes"] == [(1794.46, 1821.38), (1826.78, 1849.50)]


def test_a_run_of_production_talk_is_not_a_scene():
    # 37分38〜47秒の形: 段取りの声が続く 10 秒は、1つ1つのすき間が短いので場面ではない
    segs = [_seg(2250.0, 2257.38, "前の話です"), _seg(2267.84, 2270.0, "先生が")]
    talk = [(2258.04, 2259.24), (2259.94, 2260.54), (2260.94, 2261.44), (2262.94, 2264.84),
            (2266.04, 2266.54), (2266.94, 2267.44)]
    ranges, info = cut_plan.plan(segs, None, keep_all=True, rules=SCENE_RULES, exclude=talk)
    assert ranges == [(2250.0, 2257.38), (2267.84, 2270.0)]
    assert "scenes" not in info


def test_a_pause_shorter_than_a_scene_is_still_cut():
    segs = [_seg(0.0, 5.0, "一"), _seg(14.0, 20.0, "二")]
    ranges, _ = cut_plan.plan(segs, None, keep_all=True, rules=SCENE_RULES)
    assert ranges == [(0.0, 5.0), (14.0, 20.0)]


def test_scenes_are_not_kept_when_content_is_selected():
    # 中身を選んで削るときの長いすき間は、選ばなかった発話の所（場面ではない）
    ranges, info = cut_plan.plan(WRITING, None, keep_all=False, rules=SCENE_RULES)
    assert len(ranges) == 3
    assert "scenes" not in info


def test_keeping_scenes_can_be_turned_off_in_the_template(monkeypatch):
    from template_config import template_config
    monkeypatch.setattr(template_config, "get_cut_rules", lambda: {"keep_scenes": False})
    rules = cut_plan.cut_rules()
    assert rules["keep_scenes"] is False
    ranges, _ = cut_plan.plan(WRITING, None, keep_all=True, rules=rules)
    assert len(ranges) == 3


# --- 音声認識が聞けなかった言葉の声（2026-10-17 ユーザー指摘）------------------------------------

UNHEARD = [  # 素材の 38分40秒〜（53回目）。2行目の「悪くなっちゃって」を認識が聞けなかった
    dict(start=2313.94, end=2318.37, text="これぐらい　前はこれぐらいの量で\n例えば100本作れたんだけども",
         sourceStart=2313.94, sourceEnd=2322.94),
    dict(start=2318.37, end=2322.94, text="今は30本ぐらいしか作れないとか\nその原毛の質まで悪くなっちゃって",
         sourceStart=2313.94, sourceEnd=2322.94),
    dict(start=2327.74, end=2334.64, text="イタチにおいてはもう入ってこないのね",
         sourceStart=2327.74, sourceEnd=2334.64),
]
UNHEARD_TOKENS = [(c, t) for c, t in zip(
    "百本作れた今は三十本ぐらいしか作れないとか原毛の質までイタチにおいては今",
    (2318.04, 2318.28, 2318.56, 2318.80, 2318.96, 2320.40, 2320.72, 2321.00, 2321.12, 2321.28, 2321.56,
     2321.64, 2321.68, 2321.84, 2321.92, 2322.16, 2322.36, 2322.52, 2322.68, 2322.84, 2323.16, 2324.23,
     2324.55, 2324.79, 2325.03, 2325.47, 2325.59, 2326.33, 2328.25, 2328.41, 2328.61, 2328.85, 2329.01,
     2329.21, 2329.45, 2330.70))]
UNHEARD_VOICE = [(2317.5, 2318.19), (2318.39, 2319.1), (2319.59, 2319.96), (2320.4, 2321.24), (2321.4, 2322.45),
                 (2322.71, 2323.47), (2324.15, 2325.72), (2326.29, 2326.73), (2326.89, 2327.73),
                 (2328.06, 2329.64), (2330.7, 2334.7)]


def _plan_with(monkeypatch, segs, tokens, voice, exclude=(), keep_all=True, rules=None):
    monkeypatch.setattr(cut_plan, "read_heard", lambda path: tokens)
    monkeypatch.setattr(cut_plan, "read_audio", lambda path: _audio(voice, duration=voice[-1][1] + 5.0))
    return cut_plan.plan(segs, "raw.mp4", keep_all=keep_all, rules=dict(rules or RULES, **LIVE), exclude=exclude)


def test_the_voice_of_words_the_recogniser_missed_is_not_cut(monkeypatch):
    """素材の 38分45秒: 認識は「原毛の質まで」の「で」までしか聞けず、「悪くなっちゃって」の声
    （2326.29〜2327.73 秒）を間として切っていた。聞けなかった8字ぶんの声はその発話の声"""
    ranges, info = _plan_with(monkeypatch, UNHEARD, UNHEARD_TOKENS, UNHEARD_VOICE)
    assert any(a <= 2326.29 and 2327.73 <= b for a, b in ranges)
    assert info["unheard_widened"] == 1


def test_the_voice_after_the_heard_words_is_not_taken_beyond_the_missed_words(monkeypatch):
    # 聞けなかったのが「ね」1字なら、後ろの 1.4 秒の声はその字の声ではない（切ってよい間）
    segs = [_seg(10.0, 12.0, "書いてくださいね"), _seg(15.0, 17.0, "では次に")]
    tokens = list(zip("書いてください", (10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 11.4))) + list(zip("では次に", (15.2, 15.4, 15.6, 15.8)))
    voice = [(10.1, 11.6), (12.3, 13.7), (15.1, 16.0)]
    ranges, info = _plan_with(monkeypatch, segs, tokens, voice)
    assert len(ranges) == 2 and ranges[0][1] < 12.3
    assert "unheard_widened" not in info


def test_the_missed_words_do_not_take_the_voice_of_the_next_heard_words(monkeypatch):
    # 間のすぐ後ろの声に次の発話の聞こえた字があれば、その声は次の発話の声
    segs = [_seg(10.0, 12.0, "書いてくださいよろしくね"), _seg(13.0, 15.0, "では次に")]
    tokens = list(zip("書いてください", (10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 11.4))) + list(zip("では次に", (12.5, 12.7, 12.9, 13.1)))
    voice = [(10.1, 11.6), (12.4, 13.3)]
    out = cut_plan.unheard_reach(*cut_plan.heard_marks(segs, tokens), _audio(voice), walls=())
    assert out == {}


def test_the_voice_before_the_first_heard_word_is_kept_for_the_missed_words(monkeypatch):
    # 頭の「そっかごめんなさい」を聞けず、その声（12.4〜12.8 秒）が区間の外になっていた形（素材の 29分09秒）
    segs = [_seg(8.0, 11.0, "それではまた"), _seg(12.9, 15.5, "そっかごめんなさい今ここに持ってね")]
    tokens = list(zip("それではまた", (8.2, 8.4, 8.6, 8.8, 9.0, 9.2))) + list(zip("今ここに持ってね", (14.5, 14.7, 14.9, 15.0, 15.1, 15.3, 15.4, 15.5)))
    voice = [(8.1, 9.4), (12.4, 12.8), (13.1, 15.6)]
    ranges, info = _plan_with(monkeypatch, segs, tokens, voice)
    assert ranges[-1][0] <= 12.4 - LIVE["pad_before_sec"] + 1e-6
    assert info["unheard_widened"] == 1


def test_missed_words_do_not_reach_into_dropped_talk(monkeypatch):
    segs = [_seg(10.0, 12.0, "書いてくださいよろしくお願いします")]
    tokens = list(zip("書いてください", (10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 11.4)))
    voice = [(10.1, 11.6), (12.2, 13.0)]
    ranges, _ = _plan_with(monkeypatch, segs, tokens, voice, exclude=[(12.1, 13.1)])
    assert ranges[0][1] <= 12.1


# --- 映像の切り替わりの向こうが一瞬映る所（2026-10-17 ユーザー指摘）-------------------------------

def test_a_flash_of_the_previous_recording_at_a_cut_is_trimmed():
    """素材の 37分48秒: 4本目の収録の継ぎ目（2268.23 秒）の 0.44 秒手前から残していて、左にいた
    美麗さんが消えた3本目の終わりが映った。そこに言葉は無い（「先」は 2267.40 秒・「生」は 2269.08 秒）"""
    audio = _audio([(2267.36, 2267.72), (2268.06, 2268.65), (2268.95, 2270.67)])
    audio.heard = [2267.40, 2269.08, 2269.40]
    ranges, found = cut_plan.trim_flashes([(2247.28, 2258.12), (2267.79, 2275.15)], [2268.23], audio, 1.0)
    assert ranges == [(2247.28, 2258.12), (2267.79 + (2268.225 - 2267.79), 2275.15)]
    assert ranges[1][0] == pytest.approx(2268.23 - cut_plan.SHOT_EDGE_SEC)
    assert found == {"trimmed": [(2267.79, pytest.approx(2268.225))], "kept": []}


def test_a_flash_of_the_next_recording_before_a_cut_is_trimmed_too():
    audio = _audio([(10.0, 19.4)])
    audio.heard = [10.2, 19.2]
    ranges, found = cut_plan.trim_flashes([(9.9, 20.0)], [19.6], audio, 1.0)
    assert ranges == [(9.9, pytest.approx(19.595))] and len(found["trimmed"]) == 1


def test_a_flash_holding_words_is_kept_and_reported():
    # 言葉を切るよりは映り込みを残す（記録に残して知らせる）
    audio = _audio([(9.9, 12.0)])
    audio.heard = [10.1, 10.3, 11.0]
    ranges, found = cut_plan.trim_flashes([(9.8, 20.0)], [10.4], audio, 1.0)
    assert ranges == [(9.8, 20.0)] and found["kept"] == [(10.4, 0.6)]


def test_a_shot_longer_than_the_minimum_at_an_edge_is_left_alone():
    audio = _audio([(9.9, 12.0)])
    ranges, found = cut_plan.trim_flashes([(9.8, 20.0)], [11.2, 18.7], audio, 1.0)
    assert ranges == [(9.8, 20.0)] and found == {"trimmed": [], "kept": []}


def test_without_the_recogniser_a_flash_is_judged_by_the_voice():
    audio = _audio([(10.2, 12.0)])
    assert cut_plan.trim_flashes([(9.8, 20.0)], [10.1], audio, 1.0)[0] == [(pytest.approx(10.095), 20.0)]
    assert cut_plan.trim_flashes([(9.8, 20.0)], [10.4], audio, 1.0)[0] == [(9.8, 20.0)]


def test_plan_trims_a_flash_and_the_captions_still_fit_in_their_range(monkeypatch):
    from smart_cut_engine import retime_segments
    segs = [_seg(2247.0, 2257.9, "前の話です"),
            dict(start=2267.84, end=2272.84, text="先生がこれからの今から", sourceStart=2267.84, sourceEnd=2274.74),
            dict(start=2272.84, end=2274.74, text="何かあるんでしょうか？", sourceStart=2267.84, sourceEnd=2274.74)]
    tokens = (list(zip("前の話です", (2247.2, 2247.4, 2247.6, 2247.8, 2248.0)))
              + list(zip("生がこれからの今から", (2269.08, 2269.40, 2269.76, 2269.92, 2270.20, 2270.36, 2270.6,
                                                    2271.07, 2271.31, 2271.39)))
              + list(zip("何かあるんでしょうか", (2272.9, 2273.1, 2273.3, 2273.5, 2273.7, 2273.9, 2274.1, 2274.3,
                                                    2274.4, 2274.5))))
    monkeypatch.setattr(cut_plan, "read_shots", lambda path: [(1798.17, 19.7), (1823.13, 2.6), (2268.23, 7.03)])
    ranges, info = _plan_with(monkeypatch, segs, tokens, [(2247.1, 2257.8), (2267.7, 2268.65), (2268.95, 2274.6)])
    assert ranges[-1][0] == pytest.approx(2268.225)
    assert info["shot_changes"] == 2 and info["flashes_trimmed"] == [(pytest.approx(2267.6), pytest.approx(2268.225))]
    # 発話の区間（2267.84〜）は区間（2268.225〜）からはみ出したので、収めないと字幕が2行とも落ちる
    assert len(retime_segments([dict(s) for s in segs], ranges)[0]) == 1
    assert cut_plan.fit_spans(segs, ranges) == 2
    assert segs[1]["sourceStart"] == pytest.approx(2268.225) and segs[1]["start"] == pytest.approx(2268.225)
    assert segs[1]["end"] == 2272.84 and segs[2]["start"] == 2272.84
    assert len(retime_segments(segs, ranges)[0]) == 3


def test_fitting_leaves_spans_that_are_inside_a_range_alone():
    segs = [_seg(10.0, 12.0, "一"), dict(start=12.0, end=13.0, text="二", sourceStart=12.0, sourceEnd=14.3)]
    assert cut_plan.fit_spans(segs, [(9.9, 13.9)]) == 0  # 終わりは 0.5 秒まではみ出してよい
    assert segs[1]["sourceEnd"] == 14.3


def test_a_line_wholly_outside_the_shrunk_span_is_moved_in_with_its_length():
    segs = [dict(start=10.0, end=10.3, text="一", sourceStart=10.0, sourceEnd=14.0)]
    assert cut_plan.fit_spans(segs, [(10.5, 14.0)]) == 1
    assert (segs[0]["start"], segs[0]["end"]) == (10.5, pytest.approx(10.8))


SCDET_OUT = """frame:0    pts:1798170000 pts_time:1798.17
lavfi.scd.mafd=20.338
lavfi.scd.score=19.734
lavfi.scd.time=1798.17
frame:1    pts:2268230000 pts_time:2268.23
lavfi.scd.mafd=7.117
lavfi.scd.score=7.034
lavfi.scd.time=2268.23
"""


def test_the_shot_changes_are_read_from_ffmpeg_once_and_cached(tmp_path, monkeypatch):
    video = tmp_path / "raw.mp4"
    video.write_bytes(b"x" * 100)
    calls = []

    def run(args, **kw):
        calls.append(args)
        return type("P", (), {"returncode": 0, "stdout": SCDET_OUT, "stderr": ""})()

    monkeypatch.setattr(cut_plan.subprocess, "run", run)
    assert cut_plan.read_shots(video) == [(1798.17, 19.734), (2268.23, 7.034)]
    assert "settb=AVTB,scdet=threshold=2.0:sc_pass=1,metadata=print:file=-" in calls[0]
    assert cut_plan.read_shots(video) == [(1798.17, 19.734), (2268.23, 7.034)]
    assert len(calls) == 1 and list(tmp_path.glob("_shots_*.json"))
    assert cut_plan.read_shots(None) is None and cut_plan.read_shots(tmp_path / "missing.mp4") is None


def test_the_shot_time_is_read_from_the_microsecond_pts_not_the_rounded_text():
    # pts_time は有効数字6桁（10000 秒を超えると 0.1 秒刻み）。pts から読む
    out = "frame:0    pts:10000033333 pts_time:10000\nlavfi.scd.score=8.5\n"
    assert cut_plan._parse_scdet(out) == [(10000.033333, 8.5)]


def test_the_smartcut_stage_fits_the_captions_and_reports_a_flash_it_kept(monkeypatch):
    from agents.pipeline_types import PipelineContext
    from agents.workers.smartcut_worker import SmartCutWorker
    segs = [dict(start=10.0, end=12.0, text="一", sourceStart=10.0, sourceEnd=12.0)]
    monkeypatch.setattr(cut_plan, "plan", lambda *a, **k: (
        [(10.395, 12.0)], {"flashes_trimmed": [(10.0, 10.395)], "flashes_kept": [(1830.0, 0.5)]}))
    ctx = PipelineContext(video_path="raw.mp4", target_minutes=1)
    note = SmartCutWorker()._plan_cuts(ctx, segs, keep_all=True)
    assert segs[0]["sourceStart"] == 10.395 and ctx.cut_ranges == [(10.395, 12.0)]
    assert "1秒未満だけ映る1か所（素材の 0:10ほか）は切り落とした" in note
    assert any("30:30" in w and "言葉があるので切っていません" in w for w in ctx.warnings)
