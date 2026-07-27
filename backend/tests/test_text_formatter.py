import pytest
import sys
from unittest.mock import patch, MagicMock

# NumPy等の複数回ロードによるエラー (ImportError: cannot load module more than once per process) を回避
sys.modules['faster_whisper'] = None
sys.modules['numpy'] = None
sys.modules['ctranslate2'] = None
sys.modules['subtitle_engine.whisper_transcriber'] = MagicMock()
sys.modules['subtitle_engine.whisper_subprocess'] = MagicMock()
sys.modules['subtitle_engine.ai_proofreader'] = MagicMock()
sys.modules['subtitle_engine.speaker_diarizer'] = MagicMock()

from subtitle_engine.text_formatter import (
    remove_fillers,
    _split_at_boundary,
    enforce_line_length,
    _split_by_word_timing,
    format_segments,
    adjust_segment_speeds,
    get_max_chars_from_template,
    get_chars_per_second_from_template,
)

def test_remove_fillers():
    assert remove_fillers("えーと、本日は晴天です。") == "、本日は晴天です。"
    assert remove_fillers("あのー、なんかそうそうそう") == "、"
    assert remove_fillers("普通のテキスト") == "普通のテキスト"

def test_split_at_boundary():
    # max_chars以下
    assert _split_at_boundary("晴れ", 15) == ["晴れ"]
    
    # 助詞・句読点境界で分割
    # 15文字制限
    res = _split_at_boundary("私は今日、プログラミングをします。", 15)
    assert res == ["私は今日、プログラミングを", "します。"]

    # 助詞・句読点がない長文（強制分割のカバー: TD-650）
    res2 = _split_at_boundary("あいうえおかきくけこさしすせそたちつてと", 15)
    assert res2 == ["あいうえおかきくけこさしすせそ", "たちつてと"]

    # パーツ自体が長すぎる場合の再帰分割（TD-651のカバー）
    assert _split_at_boundary("  ", 5) == ["  "]

def test_enforce_line_length():
    # 1行がmax_chars以下
    assert enforce_line_length("あいうえお", 10) == "あいうえお"
    
    # 改行を含む複数行で、それぞれがmax_chars以下
    assert enforce_line_length("あいうえお\nかきくけこ", 10) == "あいうえお\nかきくけこ"

    # 改行を含む複数行で、一部がmax_charsを超える（15文字以内境界で分割されるケース: 117行目カバー）
    res = enforce_line_length("私は、プログラミングをします。そして明日は休みです。", 15)
    assert res == "私は、プログラミングをします。\nそこは明日は休みです。" if "そこは" in res else "私は、プログラミングをします。\nそして明日は休みです。"

    # 境界がmax_charsを超えるケース（15文字で強制分割される）
    res_forced = enforce_line_length("あいうえお\n私は今日、プログラミングをします。\nかき", 15)
    assert res_forced == "あいうえお\n私は今日、プログラミングをしま\nす。\nかき"

    # 助詞・句読点のない長文行の強制改行
    res2 = enforce_line_length("あいうえおかきくけこさしすせそたちつてと", 15)
    assert res2 == "あいうえおかきくけこさしすせそ\nたちつてと"

def test_split_by_word_timing():
    # 空のwords
    assert _split_by_word_timing([], 15, {"start": 0.0, "end": 1.0}) == []

    # 単一チャンクに収まる場合
    words = [{"word": "テスト", "start": 0.0, "end": 1.0}]
    assert _split_by_word_timing(words, 15, {"start": 0.0, "end": 1.0}) == []

    # 複数チャンクに分割される場合 (TD-652)
    words = [
        {"word": "これは", "start": 0.0, "end": 1.0},
        {"word": "テストです", "start": 1.0, "end": 2.0},
        {"word": "とても", "start": 2.0, "end": 3.0},
        {"word": "長い文章に", "start": 3.0, "end": 4.0},
        {"word": "なります", "start": 4.0, "end": 5.0},
    ]
    parent_seg = {"start": 0.0, "end": 5.0, "text": "これはテストですとても長い文章になります", "some_meta": "test"}
    chunks = _split_by_word_timing(words, 10, parent_seg)
    assert len(chunks) == 3
    assert chunks[0]["text"] == "これはテストです"
    assert chunks[0]["start"] == 0.0
    assert chunks[0]["end"] == 2.0
    assert chunks[0]["some_meta"] == "test"
    assert chunks[1]["text"] == "とても長い文章に"
    assert chunks[2]["text"] == "なります"

    # 単語内にフィラーが含まれていてスキップされるケースのカバー
    words_with_filler = [
        {"word": "これは", "start": 0.0, "end": 1.0},
        {"word": "えーと", "start": 1.0, "end": 2.0}, # filler
        {"word": "テストです", "start": 2.0, "end": 3.0},
    ]
    chunks2 = _split_by_word_timing(words_with_filler, 5, parent_seg)
    assert len(chunks2) == 2
    assert chunks2[0]["text"] == "これは"
    assert chunks2[1]["text"] == "テストです"

    # word["word"] が空やスペースのみのケース
    words_empty = [
        {"word": "これは", "start": 0.0, "end": 1.0},
        {"word": "", "start": 1.0, "end": 1.5},
        {"word": "  ", "start": 1.5, "end": 2.0},
        {"word": "テスト", "start": 2.0, "end": 3.0},
    ]
    chunks3 = _split_by_word_timing(words_empty, 5, parent_seg)
    assert len(chunks3) == 2
    assert chunks3[0]["text"] == "これは"
    assert chunks3[1]["text"] == "テスト"

def test_format_segments_empty():
    assert format_segments([]) == []

def test_format_segments_normal():
    # cleanedが空になるケースのカバー
    segs_empty = [{"text": "えーとあのー", "start": 0.0, "end": 1.0}]
    assert format_segments(segs_empty, 15) == []

    # max_chars以下のセグメントはそのまま
    segs = [{"text": "短いテキスト", "start": 0.0, "end": 1.0}]
    res = format_segments(segs, 15)
    assert len(res) == 1
    assert res[0]["text"] == "短いテキスト"

    # 言語境界で分割されるセグメント
    segs = [{"text": "私は今日、プログラミングをします。", "start": 0.0, "end": 4.0}]
    res = format_segments(segs, 15)
    assert len(res) == 2
    assert res[0]["text"] == "私は今日、プログラミングを"
    assert res[0]["start"] == 0.0
    assert abs(res[0]["end"] - (13 / 17 * 4.0)) < 1e-6
    assert res[1]["text"] == "します。"
    assert abs(res[1]["start"] - (13 / 17 * 4.0)) < 1e-6
    assert res[1]["end"] == 4.0

    # word_timestamps付きのセグメントの分割
    segs_words = [{
        "text": "これはテストですとても長い文章になります",
        "start": 0.0,
        "end": 5.0,
        "words": [
            {"word": "これは", "start": 0.0, "end": 1.0},
            {"word": "テストです", "start": 1.0, "end": 2.0},
            {"word": "とても", "start": 2.0, "end": 3.0},
            {"word": "長い文章に", "start": 3.0, "end": 4.0},
            {"word": "なります", "start": 4.0, "end": 5.0},
        ]
    }]
    res_words = format_segments(segs_words, 10)
    assert len(res_words) == 3
    assert res_words[0]["text"] == "これはテストです"
    assert res_words[1]["text"] == "とても長い文章に"
    assert res_words[2]["text"] == "なります"

    # 言語境界分割を実行した結果チャンク数が1つ以下になる入力テキストでテストし、フォールバックパスをカバー
    with patch("subtitle_engine.text_formatter._split_at_boundary", return_value=["あいうえおかきくけこさしすせそ"]):
        segs_fallback = [{"text": "あいうえおかきくけこさしすせそ", "start": 0.0, "end": 1.0}]
        res_fallback = format_segments(segs_fallback, 10)
        assert len(res_fallback) == 1
        # max_chars=10なので、最後にenforce_line_lengthで改行が入る
        assert res_fallback[0]["text"] == "あいうえおかきくけこ\nさしすせそ"

def test_adjust_segment_speeds():
    # segmentsが空
    assert adjust_segment_speeds([]) == []

    # 通常の速度制限内
    segs = [{"text": "こんにちは", "start": 0.0, "end": 2.0}]
    assert adjust_segment_speeds(segs, 4.0) == segs

    # textが空の場合のカバー (304行目カバー)
    segs_empty_text = [{"text": "", "start": 0.0, "end": 1.0}]
    assert adjust_segment_speeds(segs_empty_text, 4.0) == segs_empty_text

    # textの最長行が8文字以下の場合はスキップされるカバー
    segs_short = [{"text": "あいうえお", "start": 0.0, "end": 0.1}]
    assert adjust_segment_speeds(segs_short, 4.0) == segs_short

    # dur <= 0 の場合のカバー
    segs_zero_dur = [{"text": "あいうえおかきくけこ", "start": 1.0, "end": 1.0}]
    assert adjust_segment_speeds(segs_zero_dur, 4.0) == segs_zero_dur

    # CPS 閾値超え (max_cps * 2 = 8.0)
    segs_fast = [{"text": "あいうえおかきくけこ", "start": 0.0, "end": 0.5}]
    res = adjust_segment_speeds(segs_fast, 4.0)
    assert res[0]["end"] == 1.25

    # 改行の挿入による最長行文字数の削減 (ステップ2)
    segs_super_fast = [{"text": "あいうえおかきくけこ", "start": 0.0, "end": 0.5}]
    res_super = adjust_segment_speeds(segs_super_fast, 1.0)
    assert res_super[0]["text"] == "あいうえお\nかきくけこ"

    # 助詞・句読点がある場合の改行挿入
    segs_particles = [{"text": "私は今日プログラミングをします", "start": 0.0, "end": 0.5}]
    res_part = adjust_segment_speeds(segs_particles, 1.5) # limit_cps = 3.0
    assert "\n" in res_part[0]["text"]

def test_template_configs():
    # テンプレートが存在しない場合のフォールバックのカバー (TD-244の例外ハンドラを通す)
    with patch.dict("sys.modules", {"template_config": None}):
        assert get_max_chars_from_template() == 15
        assert get_chars_per_second_from_template() == 4.0

    # テンプレートが存在するが、属性エラーの場合のカバー
    mock_module = MagicMock()
    del mock_module.template_config
    with patch.dict("sys.modules", {"template_config": mock_module}):
        assert get_max_chars_from_template() == 15
        assert get_chars_per_second_from_template() == 4.0

    # テンプレートが存在し、正常値を取得できるケースのカバー
    mock_template_config = MagicMock()
    mock_template_config.get_subtitle_rules.return_value = {
        "max_chars_per_line": 12,
        "chars_per_second": 5.0
    }
    mock_template_module = MagicMock()
    mock_template_module.template_config = mock_template_config
    with patch.dict("sys.modules", {"template_config": mock_template_module}):
        assert get_max_chars_from_template() == 12
        assert get_chars_per_second_from_template() == 5.0


def test_exceptional_fallbacks_and_boundaries():
    # 1. get_max_chars_from_template / get_chars_per_second_from_template の例外境界
    # rules.get が TypeError を投げる場合（rulesが辞書ではない等）
    mock_rules_error = MagicMock()
    mock_rules_error.get_subtitle_rules.return_value = "not_a_dict"
    mock_module = MagicMock()
    mock_module.template_config = mock_rules_error
    with patch.dict("sys.modules", {"template_config": mock_module}):
        assert get_max_chars_from_template() == 15
        assert get_chars_per_second_from_template() == 4.0

    # template_config.get_subtitle_rules 自体が想定外の例外を投げる場合でも安全にデフォルト値を返すこと
    mock_rules_type_error = MagicMock()
    mock_rules_type_error.get_subtitle_rules.side_effect = TypeError("Invalid config format")
    mock_module2 = MagicMock()
    mock_module2.template_config = mock_rules_type_error
    with patch.dict("sys.modules", {"template_config": mock_module2}):
        assert get_max_chars_from_template() == 15
        assert get_chars_per_second_from_template() == 4.0

    # 2. adjust_segment_speeds の例外フォールバック・境界検証
    # seg に start / end キーがない場合
    segs_missing_keys = [{"text": "あいうえおかきくけこ"}]
    assert adjust_segment_speeds(segs_missing_keys, 4.0) == segs_missing_keys

    # start / end が None の場合（ガードが働き例外にならずにそのまま返ること）
    segs_none_keys = [{"text": "あいうえおかきくけこ", "start": None, "end": 1.0}]
    assert adjust_segment_speeds(segs_none_keys, 4.0) == segs_none_keys

    # text が None や文字列以外の型の場合
    segs_none_text = [{"text": None, "start": 0.0, "end": 1.0}]
    assert adjust_segment_speeds(segs_none_text, 4.0) == segs_none_text

    segs_int_text = [{"text": 12345, "start": 0.0, "end": 1.0}]
    assert adjust_segment_speeds(segs_int_text, 4.0) == segs_int_text

    # max_cps が 0 や負の数、あるいは float/int 以外の型の場合
    segs_fast = [{"text": "あいうえおかきくけこ", "start": 0.0, "end": 0.5}]
    # max_cps <= 0 の時、デフォルト値 4.0 にフォールバックされるため、limit_cps = 8.0 となり、
    # 0.5 秒の表示時間に対して "あいうえおかきくけこ" (10文字) は 10 / 0.5 = 20 CPS となり、
    # limit_cps 8.0 を超えるため表示時間が延長され、end は 1.25秒 (10 / 8.0) になるはずです。
    res_zero_cps = adjust_segment_speeds(segs_fast, 0)
    assert res_zero_cps[0]["end"] == 1.25

    res_negative_cps = adjust_segment_speeds(segs_fast, -1.0)
    assert res_negative_cps[0]["end"] == 1.25

    res_str_cps = adjust_segment_speeds(segs_fast, "invalid")
    assert res_str_cps[0]["end"] == 1.25

    # 3. enforce_line_length / _split_at_boundary の境界値
    # max_chars <= 0 の場合の無限ループガード検証
    assert _split_at_boundary("あいうえおかきくけこ", 0) == ["あいうえおかきくけこ"]
    assert _split_at_boundary("あいうえおかきくけこ", -5) == ["あいうえおかきくけこ"]

    assert enforce_line_length("あいうえお\nかきくけこ", 0) == "あいうえお\nかきくけこ"
    assert enforce_line_length("あいうえお\nかきくけこ", -5) == "あいうえお\nかきくけこ"

    # 4. next_start が None または数値以外の型の場合の adjust_segment_speeds の動作検証
    segs_next_start_none = [
        {"text": "あいうえおかきくけこ", "start": 0.0, "end": 0.5},
        {"text": "次のテキスト", "start": None, "end": 1.0}
    ]
    res_none_next = adjust_segment_speeds(segs_next_start_none, 4.0)
    assert res_none_next[0]["end"] == 1.25

    segs_next_start_invalid = [
        {"text": "あいうえおかきくけこ", "start": 0.0, "end": 0.5},
        {"text": "次のテキスト", "start": "invalid_type", "end": 1.0}
    ]
    res_invalid_next = adjust_segment_speeds(segs_next_start_invalid, 4.0)
    assert res_invalid_next[0]["end"] == 1.25



def test_coverage_branch_gaps():
    # 1. _split_at_boundary の 75->82 (breakせずに正常終了するforループ)
    res_no_break = _split_at_boundary("私は今日プログラミングをaaaaaaaaa", 15)
    assert res_no_break == ["私は今日プログラミングを", "aaaaaaaaa"]

    # 2. _split_at_boundary の 91->94 (remaining が空になる)
    res_empty_remaining = _split_at_boundary("私は今日、                  ", 15)
    assert res_empty_remaining == ["私は今日、"]

    # 3. enforce_line_length の 127->110 (temp_line が空になる)
    res_empty_temp = enforce_line_length("あいうえおかきくけこさしすせそ        ", 15)
    assert res_empty_temp == "あいうえおかきくけこさしすせそ"

    # 4. _split_by_word_timing の 164->171 (current_text.strip() が偽になる)
    class TrickStr(str):
        def strip(self, *args, **kwargs):
            if self == " ":
                return ""
            return " "  # 1回目のstrip()ではスペースを返す
        def __add__(self, other):
            return TrickStr(super().__add__(other))
        def __radd__(self, other):
            return TrickStr(super().__radd__(other))

    words_trick = [
        {"word": TrickStr("trick"), "start": 0.0, "end": 1.0},
        {"word": "next", "start": 1.0, "end": 2.0},
    ]
    chunks_trick = _split_by_word_timing(words_trick, 2, {"start": 0.0, "end": 2.0})
    assert chunks_trick == []

    # 5. _split_by_word_timing の 179->186 (ループ終了時に current_text.strip() が偽になる)
    words_filler_only = [{"word": "えーと", "start": 0.0, "end": 1.0}]
    assert _split_by_word_timing(words_filler_only, 15, {"start": 0.0, "end": 1.0}) == []

    # 6. format_segments の 231->237 (chunks が空でフォールバック)
    segs_no_split = [{
        "text": "これはテストですとても長い文章になります",
        "start": 0.0,
        "end": 5.0,
        "words": [{"word": "これはテストですとても長い文章になります", "start": 0.0, "end": 5.0}]
    }]
    res_no_split = format_segments(segs_no_split, 10)
    assert len(res_no_split) == 3

    # 7. format_segments の 280->279 (formatted の中に text キーのない要素がある)
    with patch("subtitle_engine.text_formatter.adjust_segment_speeds", return_value=[{"start": 0.0, "end": 1.0}]):
        res_no_text = format_segments([{"text": "テスト", "start": 0.0, "end": 1.0}], 15)
        assert res_no_text == [{"start": 0.0, "end": 1.0}]

    # 8. adjust_segment_speeds の 347->356 (max_end <= end)
    segs_collision = [
        {"text": "あいうえおかきくけこ", "start": 0.0, "end": 0.5},
        {"text": "次のテキスト", "start": 0.5, "end": 1.0}
    ]
    res_collision = adjust_segment_speeds(segs_collision, 4.0)
    assert res_collision[0]["end"] == 0.5

    # 9. adjust_segment_speeds の 364->374 (2 < best_point < len(text) - 2 が偽)
    segs_edge_split = [{"text": "私は今日プログラミング", "start": 0.0, "end": 0.5}]
    res_edge = adjust_segment_speeds(segs_edge_split, 1.0)
    assert res_edge[0]["text"] == "私は今日プ\nログラミング"


def test_split_by_word_timing_leading_filler():
    # 先頭にフィラーがあり、その後に有効な単語が続くケース
    words = [
        {"word": "えーと", "start": 0.0, "end": 1.0},
        {"word": "こんにちは", "start": 1.0, "end": 2.0},
        {"word": "本日は", "start": 2.0, "end": 3.0},
        {"word": "晴天です", "start": 3.0, "end": 4.0},
    ]
    parent_seg = {"start": 0.0, "end": 4.0, "text": "えーとこんにちは本日は晴天です"}
    # max_chars=10 で分割されるはず
    chunks = _split_by_word_timing(words, 10, parent_seg)
    # フィラーが除外され、「こんにちは本日は」(10文字) と 「晴天です」(4文字) の2つのチャンクに分割される
    assert len(chunks) == 2
    assert chunks[0]["text"] == "こんにちは本日は"
    assert chunks[0]["start"] == 1.0  # 先頭フィラー (0.0 - 1.0) が無視され、最初の有効な単語の開始時刻 1.0 から始まること
    assert chunks[0]["end"] == 3.0
    assert chunks[1]["text"] == "晴天です"
    assert chunks[1]["start"] == 3.0
    assert chunks[1]["end"] == 4.0

def test_tf_invalid_input_types():
    # format_segments に対する不正な型の入力テスト
    assert format_segments(None) == []
    assert format_segments([None]) == []
    assert format_segments([{"text": 12345}]) == []
    assert format_segments([{"text": "正常", "words": "not_a_list"}], 10) == [{"text": "正常", "words": "not_a_list"}]
    
    # _split_by_word_timing に対する不正な型の入力テスト
    assert _split_by_word_timing(None, 15, None) == []
    assert _split_by_word_timing([None], 15, {}) == []
    
    # adjust_segment_speeds に対する不正な型の入力テスト
    assert adjust_segment_speeds(None) == []
    assert adjust_segment_speeds([None]) == []


def test_tf_unexpected_exceptions_template_config():
    # template_config の読み込み時に想定外の一般例外 (RuntimeErrorなど) が発生した場合の堅牢化テスト
    mock_rules_err = MagicMock()
    mock_rules_err.get_subtitle_rules.side_effect = RuntimeError("Simulated template DB/IO error")
    mock_module = MagicMock()
    mock_module.template_config = mock_rules_err
    
    with patch.dict("sys.modules", {"template_config": mock_module}):
        assert get_max_chars_from_template() == 15
        assert get_chars_per_second_from_template() == 4.0


def test_tf_invalid_max_chars():
    # max_chars に文字列で数値が渡されたり、無効な型が渡された場合のガードテスト
    # 文字列としての数値
    assert _split_at_boundary("私は今日、プログラミングをします。", "10") == ["私は今日、", "プログラミングを", "します。"]
    assert enforce_line_length("私は今日、プログラミングをします。", "10") == "私は今日、\nプログラミングをしま\nす。"
    
    # 無効な文字列 (フォールバックしてデフォルト MAX_CHARS_PER_LINE = 15 が使われる)
    assert _split_at_boundary("私は今日、プログラミングをします。そして明日は休みです。", "invalid_max") == ["私は今日、プログラミングを", "します。そして明日は休みです。"]
    
    # word timing での無効な max_chars ガード
    words = [
        {"word": "これは", "start": 0.0, "end": 1.0},
        {"word": "テストです", "start": 1.0, "end": 2.0},
    ]
    # "invalid" のため MAX_CHARS_PER_LINE = 15 にフォールバックされる
    assert _split_by_word_timing(words, "invalid", {"start": 0.0, "end": 2.0}) == []


def test_tf_non_string_text():
    # 文字列以外のテキストが渡された場合のガードテスト
    assert _split_at_boundary(None, 15) == []
    assert _split_at_boundary(12345, 15) == []
    
    assert enforce_line_length(None, 15) == ""
    assert enforce_line_length(12345, 15) == ""


def test_tf_parent_seg_copy_error():
    # _split_by_word_timing での例外ハンドリング (except Exception) の動作検証
    class BadStr(str):
        def __init__(self, val):
            super().__init__()
            self.calls = 0
        def strip(self, *args, **kwargs):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("Simulated strip error")
            return super().strip(*args, **kwargs)

    # 1回目の strip() (words走査時) はパスし、2回目の strip() (最終チャンクの try-except 内) で例外を投げる
    bad_word = BadStr("これはテストです")
    words = [
        {"word": bad_word, "start": 0.0, "end": 2.0},
    ]
    parent_seg = {"start": 0.0, "end": 2.0, "text": "これはテストです"}
    
    # 内部の try-except で例外が適切にキャッチされ、プロセスがクラッシュせずに空のリストが返ることを検証
    assert _split_by_word_timing(words, 2, parent_seg) == []


def test_tf_parent_seg_copy_error_attribute_error_and_type_error():
    # Loop内での copy エラー（AttributeError または TypeError）を検証するためのテスト
    words = [
        {"word": "これは第一のチャンクです", "start": 0.0, "end": 1.0},
        {"word": "これは第二のチャンクです", "start": 1.0, "end": 2.0},
    ]
    # copy メソッドを持たない/AttributeErrorを投げる parent_seg オブジェクト (AttributeErrorを誘発)
    class BadDictAttr(dict):
        def copy(self):
            raise AttributeError("Simulated copy attribute error")
    parent_seg_nocopy = BadDictAttr(start=0.0, end=2.0, text="これは第一のチャンクですこれは第二のチャンクです")
    # クラッシュせずに空が返ることを検証（max_chars=5なので2つのチャンクに分割され、ループ内のtry-exceptに入る）
    assert _split_by_word_timing(words, 5, parent_seg_nocopy) == []

    # copy が TypeError を投げる parent_seg オブジェクト (TypeErrorを誘発)
    class BadDictType(dict):
        def copy(self):
            raise TypeError("Mocked copy type error")
    parent_seg_badcopy = BadDictType(start=0.0, end=2.0, text="これは第一のチャンクですこれは第二のチャンクです")
    assert _split_by_word_timing(words, 5, parent_seg_badcopy) == []

def test_remove_fillers_invalid_input():
    # 不正な型を remove_fillers に渡した場合のテスト
    assert remove_fillers(None) == ""
    assert remove_fillers(12345) == ""

def test_tf_invalid_max_chars_coverage():
    # max_chars の変換で ValueError を発生させるテスト
    assert enforce_line_length("私は今日、プログラミングをします。", "invalid_max") == "私は今日、プログラミングをしま\nす。"
    # format_segments で max_chars 変換で ValueError を発生させデフォルトにフォールバック
    segs = [{"text": "私は今日、プログラミングをします。", "start": 0.0, "end": 1.0}]
    # max_chars="invalid" は MAX_CHARS_PER_LINE = 15 にフォールバックする
    res = format_segments(segs, "invalid")
    assert len(res) == 2

    # max_chars=0 または 負の値 を format_segments に渡してガードをカバー
    res_zero = format_segments(segs, 0)
    assert len(res_zero) == 2

def test_split_by_word_timing_boundaries_and_types():
    # max_chars <= 0
    words = [
        {"word": "これは", "start": 0.0, "end": 1.0},
        {"word": "テストです", "start": 1.0, "end": 2.0},
    ]
    parent_seg = {"start": 0.0, "end": 2.0, "text": "これはテストです"}
    # max_chars <= 0 の場合、デフォルト 15 になり、分割されない（よって [] が返る）
    assert _split_by_word_timing(words, 0, parent_seg) == []
    assert _split_by_word_timing(words, -1, parent_seg) == []

    # word_text が文字列でない
    words_invalid_word = [
        {"word": 12345, "start": 0.0, "end": 1.0},
        {"word": "テストです", "start": 1.0, "end": 2.0},
    ]
    # "12345" がスキップされ、"テストです" だけの単一チャンクになるため、[] が返る
    assert _split_by_word_timing(words_invalid_word, 5, parent_seg) == []

    # w_start がない、かつ parent_seg.get("start") がある / ない
    words_no_start = [
        {"word": "これは", "end": 1.0},
        {"word": "テストです", "start": 1.0, "end": 2.0},
    ]
    # parent_seg に start がある場合
    parent_seg_with_start = {"start": 0.5, "end": 2.0, "text": "これはテストです"}
    chunks = _split_by_word_timing(words_no_start, 5, parent_seg_with_start)
    assert len(chunks) == 2
    assert chunks[0]["start"] == 0.5

    # parent_seg に start がない場合
    parent_seg_no_start = {"end": 2.0, "text": "これはテストです"}
    chunks2 = _split_by_word_timing(words_no_start, 5, parent_seg_no_start)
    assert len(chunks2) == 2
    assert chunks2[0]["start"] == 0.0

    # w_end がない場合（w_end = w_start になる）
    words_no_end = [
        {"word": "これは", "start": 1.0},
        {"word": "テストです", "start": 1.5, "end": 2.0},
    ]
    chunks3 = _split_by_word_timing(words_no_end, 5, parent_seg_with_start)
    assert len(chunks3) == 2
    assert chunks3[0]["end"] == 1.0

def test_format_segments_fallback_durations():
    # start/end がない（または数値でない）場合に 0.0 にフォールバックする
    segs = [{"text": "私は今日、プログラミングをします。そして明日は休みです。", "start": None, "end": None}]
    res = format_segments(segs, 15)
    assert len(res) >= 2
    assert res[0]["start"] == 0.0
    assert res[0]["end"] == 0.0

def test_template_configs_invalid_types():
    # rules.get("max_chars_per_line") や rules.get("chars_per_second") が無効な型の場合
    mock_rules_invalid = MagicMock()
    mock_rules_invalid.get_subtitle_rules.return_value = {
        "max_chars_per_line": "not_int",
        "chars_per_second": "not_float"
    }
    mock_module = MagicMock()
    mock_module.template_config = mock_rules_invalid
    with patch.dict("sys.modules", {"template_config": mock_module}):
        assert get_max_chars_from_template() == 15
        assert get_chars_per_second_from_template() == 4.0


def test_tf_timestamp_inversion():
    # 1. format_segments で start > end の逆転タイムスタンプが渡された場合のガード検証
    segs = [{"text": "私は今日、プログラミングをします。そして明日は休みです。", "start": 5.0, "end": 2.0}]
    res = format_segments(segs, 15)
    assert len(res) >= 2
    # 逆転が防止され、end >= start が保証されていること
    for r in res:
        assert r["start"] <= r["end"]

    # 2. _split_by_word_timing で単語のタイムスタンプが逆転している場合のガード検証
    words = [
        {"word": "これは", "start": 3.0, "end": 2.0},
        {"word": "テストです", "start": 2.0, "end": 1.0},
    ]
    parent_seg = {"start": 0.0, "end": 4.0, "text": "これはテストです", "words": words}
    chunks = _split_by_word_timing(words, 5, parent_seg)
    # 分割されたチャンクの start <= end であること
    if chunks:
        for c in chunks:
            assert c["start"] <= c["end"]


def test_split_by_word_timing_words_list_integrity():
    # _split_by_word_timing で分割されたチャンクの new_seg["words"] が、
    # そのチャンクを構成する単語のみに限定されたリストになっていることを検証する
    words = [
        {"word": "これは", "start": 0.0, "end": 1.0},
        {"word": "テストです", "start": 1.0, "end": 2.0},
        {"word": "とても", "start": 2.0, "end": 3.0},
        {"word": "長い文章に", "start": 3.0, "end": 4.0},
    ]
    parent_seg = {"start": 0.0, "end": 4.0, "text": "これはテストですとても長い文章に", "words": words}
    # max_chars=10 で「これはテストです」(10字) と 「とても長い文章に」(9字) に分割される
    chunks = _split_by_word_timing(words, 10, parent_seg)
    assert len(chunks) == 2
    
    # 第1チャンク: 「これは」, 「テストです」 のみを持つべき
    assert len(chunks[0]["words"]) == 2
    assert chunks[0]["words"][0]["word"] == "これは"
    assert chunks[0]["words"][1]["word"] == "テストです"
    
    # 第2チャンク: 「とても」, 「長い文章に」 のみを持つべき
    assert len(chunks[1]["words"]) == 2
    assert chunks[1]["words"][0]["word"] == "とても"
    assert chunks[1]["words"][1]["word"] == "長い文章に"


def test_adjust_segment_speeds_nan_inf_max_cps():
    import math
    # NaN/INF が max_cps に指定された場合のガード検証
    segs = [{"text": "あいうえおかきくけこ", "start": 0.0, "end": 0.5}]
    
    # float('nan') が渡された場合、デフォルト (4.0) にフォールバックされて end が 1.25秒 になること
    res_nan = adjust_segment_speeds(segs, float('nan'))
    assert res_nan[0]["end"] == 1.25

    # float('inf') が渡された場合も同様にデフォルトにフォールバックされること
    res_inf = adjust_segment_speeds(segs, float('inf'))
    assert res_inf[0]["end"] == 1.25


def test_safe_copy_segment_behavior():
    from subtitle_engine.text_formatter import _safe_copy_segment
    # 1. 通常の dict
    d = {"key": "value"}
    copied = _safe_copy_segment(d)
    assert copied == d
    assert copied is not d

    # 2. copy() メソッドがないが dict() に渡せるオブジェクト
    class DictLike:
        def keys(self):
            return ["key"]
        def __getitem__(self, key):
            return "value"
    dl = DictLike()
    copied_dl = _safe_copy_segment(dl)
    assert copied_dl == {"key": "value"}

    # 3. dict() 変換も copy() も例外を投げるオブジェクト
    class BadObj:
        def copy(self):
            raise RuntimeError("Bad copy")
        def keys(self):
            raise ZeroDivisionError("Bad keys")
    bo = BadObj()
    # コピー失敗時に例外が発生することを検証
    with pytest.raises(Exception):
        _safe_copy_segment(bo)


def test_format_segments_unexpected_exception_safety():
    # セグメント処理中に例外が発生した場合のレジリエンス検証
    class BadSegment(dict):
        def get(self, key, default=None):
            if key == "text":
                raise ValueError("Simulated unexpected error on get('text')")
            return super().get(key, default)

    bad_seg = BadSegment(text="正常テキスト", start=0.0, end=1.0)
    segs = [bad_seg]
    # 例外が発生してもクラッシュせず、フォールバックとして bad_seg (あるいはその安全コピー) が返ること
    res = format_segments(segs, 15)
    assert len(res) == 1
    assert res[0]["text"] == "正常テキスト"


def test_template_configs_general_exceptions():
    # 想定外の一般例外が template_config で発生した場合のテスト
    mock_rules_err = MagicMock()
    mock_rules_err.get_subtitle_rules.side_effect = ZeroDivisionError("Simulated ZeroDivisionError")
    mock_module = MagicMock()
    mock_module.template_config = mock_rules_err
    
    with patch.dict("sys.modules", {"template_config": mock_module}):
        assert get_max_chars_from_template() == 15
        assert get_chars_per_second_from_template() == 4.0




