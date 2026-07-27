import pytest
from backend.ai_rhythm import analyze_rhythm, semantic_split

def test_analyze_rhythm_non_list():
    assert analyze_rhythm(None) == []
    assert analyze_rhythm("not a list") == []

def test_analyze_rhythm_invalid_elements():
    segments = [
        {"id": 1, "text": "hello"},
        "invalid_element",
        {"id": 2, "text": "world"}
    ]
    res = analyze_rhythm(segments)
    assert len(res) == 2
    assert res[0]['index'] == 1
    assert res[1]['index'] == 2

def test_analyze_rhythm_missing_id():
    segments = [
        {"text": "first"},
        {"id": 99, "text": "second"},
        {"text": "third"}
    ]
    res = analyze_rhythm(segments)
    assert res[0]['index'] == 0
    assert res[1]['index'] == 99
    assert res[2]['index'] == 2

def test_analyze_rhythm_non_str_text():
    segments = [
        {"id": 1, "text": None},
        {"id": 2, "text": 12345}
    ]
    res = analyze_rhythm(segments)
    assert res[0]['length'] == 0
    assert res[1]['length'] == 5
    assert res[1]['status'] == 'ok'

def test_analyze_rhythm_statuses():
    segments = [
        {"id": 1, "text": "ab"},
        {"id": 2, "text": "abc"},
        {"id": 3, "text": "a" * 18},
        {"id": 4, "text": "a" * 19},
        {"id": 5, "text": ""}
    ]
    res = analyze_rhythm(segments, target_chars=13)
    assert res[0]['status'] == 'too_short'
    assert res[0]['suggestion'] == 'merge'
    
    assert res[1]['status'] == 'ok'
    assert res[1]['suggestion'] is None
    
    assert res[2]['status'] == 'ok'
    assert res[2]['suggestion'] is None
    
    assert res[3]['status'] == 'too_long'
    assert res[3]['suggestion'] == 'split'
    
    assert res[4]['status'] == 'ok'
    assert res[4]['suggestion'] is None

def test_semantic_split_non_str():
    assert semantic_split(None) == [""]
    assert semantic_split(123) == ["123"]

def test_semantic_split_short_text():
    assert semantic_split("hello", target_chars=13) == ["hello"]

def test_semantic_split_punctuation():
    text = "konnichiwa\u3001sekai\u3002tesutodesu\uff01"
    res = semantic_split(text, target_chars=5) # ??????????????? 11, 6, 12 ????target_chars=5 ??????????????????
    # ?????????????? target_chars=12 ?????
    # ???????12 ???? 5 ????????????
    res_no_force = semantic_split(text, target_chars=12)
    assert res_no_force == ["konnichiwa\u3001", "sekai\u3002", "tesutodesu\uff01"]

def test_semantic_split_punctuation_continuous():
    text = "\u3001\u3002\uff01"
    res = semantic_split(text, target_chars=1)
    assert res == ["\u3001", "\u3002", "\uff01"]

def test_semantic_split_force_split():
    text = "a" * 40
    res = semantic_split(text, target_chars=13)
    assert res == ["a" * 10, "a" * 10, "a" * 10, "a" * 10]

def test_semantic_split_force_split_limit_cases():
    text = "a"
    res = semantic_split(text, target_chars=-5)
    assert res == ["a"]


def test_analyze_rhythm_edge_cases():
    # target_chars = 13
    # 境界値: length > target_chars + 5 (19文字以上が too_long)
    # 境界値: length < 3 and length > 0 (1, 2文字が too_short, 0文字は ok)
    
    # 18文字 (OK)
    res = analyze_rhythm([{"id": 1, "text": "a" * 18}])
    assert res[0]['status'] == 'ok'
    assert res[0]['suggestion'] is None
    
    # 19文字 (too_long)
    res = analyze_rhythm([{"id": 2, "text": "a" * 19}])
    assert res[0]['status'] == 'too_long'
    assert res[0]['suggestion'] == 'split'
    
    # 3文字 (OK)
    res = analyze_rhythm([{"id": 3, "text": "abc"}])
    assert res[0]['status'] == 'ok'
    
    # 2文字 (too_short)
    res = analyze_rhythm([{"id": 4, "text": "ab"}])
    assert res[0]['status'] == 'too_short'
    assert res[0]['suggestion'] == 'merge'
    
    # 0文字 (ok)
    res = analyze_rhythm([{"id": 5, "text": ""}])
    assert res[0]['status'] == 'ok'

    # target_charsを変更
    # target_chars = 5 (too_long境界は 5+5=10文字超、つまり11文字以上)
    res = analyze_rhythm([{"id": 10, "text": "a" * 10}], target_chars=5)
    assert res[0]['status'] == 'ok'
    res = analyze_rhythm([{"id": 11, "text": "a" * 11}], target_chars=5)
    assert res[0]['status'] == 'too_long'

    # target_charsが極端な値 (負の値)
    res = analyze_rhythm([{"id": 12, "text": "a"}], target_chars=-5)
    assert res[0]['status'] == 'too_long'

def test_analyze_rhythm_missing_text_key():
    # textキーがない辞書
    segments = [{"id": 1}]
    res = analyze_rhythm(segments)
    assert res[0]['length'] == 0
    assert res[0]['status'] == 'ok'

def test_semantic_split_english_punctuation():
    # 英語の句読点では分割されないことを確認
    text = "hello, world! testing python."
    res = semantic_split(text, target_chars=30)
    assert res == [text]

def test_semantic_split_extreme_target_chars():
    # target_charsが非常に小さい場合でも無限ループせず正しく分割されること
    text = "ab"
    assert semantic_split(text, target_chars=0) == ["ab"]
    
    long_text = "abcdef"
    assert semantic_split(long_text, target_chars=0) == ["abc", "def"]

    res = semantic_split("a", target_chars=-10)
    assert res == ["a"]

def test_semantic_split_control_characters():
    # 改行やタブが含まれる場合
    text = "hello\nworld\ttest"
    res = semantic_split(text, target_chars=20)
    assert res == [text]

def test_analyze_rhythm_robustness():
    # セグメント要素に None や無効な型が混入している場合
    segments = [
        {"id": 1, "text": "hello"},
        None,
        {"id": 2, "text": "world"},
        "not_a_dict",
        {"id": "seg-3", "text": "test"} # IDが文字列
    ]
    res = analyze_rhythm(segments)
    assert len(res) == 3
    assert res[0]['index'] == 1
    assert res[1]['index'] == 2
    assert res[2]['index'] == "seg-3"

def test_semantic_split_japanese_complex_punctuation():
    # 全角記号（、。！？）がランダムに混在、かつ連続するテキスト
    text = "こんにちは、、世界！！テストですか？？？"
    res = semantic_split(text, target_chars=5)
    assert len(res) > 0
    assert "".join(res) == text

def test_semantic_split_special_chars():
    # 改行コード、タブ、サロゲートペアなどの検証
    text = "𠮷野家で\n朝食を\t食べる。"
    res = semantic_split(text, target_chars=5)
    assert len(res) > 0
    assert "".join(res) == text



def test_analyze_rhythm_target_chars_zero():
    from backend.ai_rhythm import analyze_rhythm
    # target_chars = 0 の場合、境界は 5文字 (0 + 5)
    # 5文字 (ok)
    res = analyze_rhythm([{"id": 1, "text": "a" * 5}], target_chars=0)
    assert res[0]['status'] == 'ok'
    
    # 6文字 (too_long)
    res = analyze_rhythm([{"id": 2, "text": "a" * 6}], target_chars=0)
    assert res[0]['status'] == 'too_long'
    assert res[0]['suggestion'] == 'split'


def test_analyze_rhythm_none_id():
    from backend.ai_rhythm import analyze_rhythm
    # IDが None の場合でも正しく動作し、index として None が設定されること
    segments = [{"id": None, "text": "hello"}]
    res = analyze_rhythm(segments)
    assert res[0]['index'] is None
    assert res[0]['status'] == 'ok'


def test_semantic_split_only_punctuation():
    from backend.ai_rhythm import semantic_split
    # 句読点のみで構成されるテキストが target_chars を超える場合
    # 「、」は句読点なので、1文字ずつに分割されるはず
    text = "、、、、"
    res = semantic_split(text, target_chars=2)
    assert res == ["、", "、", "、", "、"]


def test_semantic_split_continuous_punctuation_behavior():
    from backend.ai_rhythm import semantic_split
    # 連続する句読点がある場合、後ろの句読点が単独のチャンクになる挙動を確認する
    text = "こんにちは。。世界"
    res = semantic_split(text, target_chars=5)
    assert res == ["こんにちは。", "。", "世界"]


def test_analyze_rhythm_invalid_target_chars_type(caplog):
    import logging
    from backend.ai_rhythm import analyze_rhythm
    
    # target_chars が文字列の場合 (デフォルトの 13 にリセットされるはず)
    res = analyze_rhythm([{"id": 1, "text": "a" * 18}], target_chars="invalid")
    assert res[0]['status'] == 'ok'
    res = analyze_rhythm([{"id": 2, "text": "a" * 19}], target_chars="invalid")
    assert res[0]['status'] == 'too_long'
    
    # target_chars が負の数の場合 (リセットされず負の数として動作する)
    # target_chars = -5 のとき境界は -5 + 5 = 0文字超
    res = analyze_rhythm([{"id": 3, "text": ""}], target_chars=-5)
    assert res[0]['status'] == 'ok'
    res = analyze_rhythm([{"id": 4, "text": "a"}], target_chars=-5)
    assert res[0]['status'] == 'too_long'


def test_analyze_rhythm_exception_during_iteration(caplog):
    import logging
    from backend.ai_rhythm import analyze_rhythm
    
    class BadSegment(dict):
        def get(self, key, default=None):
            if key == 'text':
                raise RuntimeError("Database connection failed")
            return super().get(key, default)
            
    segments = [
        {"id": 1, "text": "normal"},
        BadSegment({"id": 2, "text": "will_fail"})
    ]
    with caplog.at_level(logging.ERROR):
        res = analyze_rhythm(segments)
    
    assert len(res) == 2
    assert res[0]['status'] == 'ok'
    assert res[1]['status'] == 'error'
    assert res[1]['length'] == 0


def test_semantic_split_invalid_target_chars_type():
    from backend.ai_rhythm import semantic_split
    
    # target_chars が無効な型 (デフォルトの 13 にリセットされるはず)
    res = semantic_split("a" * 20, target_chars="invalid")
    assert len(res) > 1
    
    # target_chars が負の数の場合 (そのまま負の数として動作する)
    res = semantic_split("a" * 10, target_chars=-5)
    assert len(res) == 10
    assert all(len(x) == 1 for x in res)


def test_semantic_split_exception_handling(monkeypatch):
    import re
    from backend.ai_rhythm import semantic_split
    
    def mock_split(*args, **kwargs):
        raise re.error("Regex internal failure")
    monkeypatch.setattr(re, "split", mock_split)
    
    res = semantic_split("test_text", target_chars=5)
    assert res == ["test_text"]


def test_semantic_split_unexpected_exception():
    from backend.ai_rhythm import semantic_split
    
    class BadText:
        def __str__(self):
            raise RuntimeError("Unexpected string conversion error")
            
    bad_obj = BadText()
    res = semantic_split(bad_obj, target_chars=5)
    assert res == [bad_obj]



def test_analyze_rhythm_edge_cases_nan_inf_bool():
    import math
    from backend.ai_rhythm import analyze_rhythm
    
    # target_chars が nan の場合
    res = analyze_rhythm([{"id": 1, "text": "a" * 18}], target_chars=float('nan'))
    assert res[0]['status'] == 'ok' # デフォルトの13になり、18文字は ok (13+5=18以下)
    res2 = analyze_rhythm([{"id": 2, "text": "a" * 19}], target_chars=float('nan'))
    assert res2[0]['status'] == 'too_long' # 19文字は too_long
    
    # target_chars が inf の場合
    res3 = analyze_rhythm([{"id": 3, "text": "a" * 19}], target_chars=float('inf'))
    assert res3[0]['status'] == 'too_long' # デフォルト13になり too_long
    
    # target_chars が bool (True) の場合
    res4 = analyze_rhythm([{"id": 4, "text": "a" * 19}], target_chars=True)
    assert res4[0]['status'] == 'too_long' # デフォルト13になり too_long

def test_semantic_split_nan_inf_bool():
    import math
    from backend.ai_rhythm import semantic_split
    
    # nan
    res = semantic_split("a" * 20, target_chars=float('nan'))
    assert len(res) > 1 # デフォルトの13になり、分割される
    
    # inf
    res2 = semantic_split("a" * 20, target_chars=float('inf'))
    assert len(res2) > 1 # デフォルトの13になり、分割される
    
    # bool (True)
    res3 = semantic_split("a" * 20, target_chars=True)
    assert len(res3) > 1 # デフォルトの13になり、分割される

def test_resolve_target_chars_extra_types():
    from backend.ai_rhythm import _resolve_target_chars
    # 複素数
    assert _resolve_target_chars(3 + 4j) == 13
    # リスト
    assert _resolve_target_chars([13]) == 13
    # 辞書
    assert _resolve_target_chars({"val": 13}) == 13
    # 極端に大きい数
    assert _resolve_target_chars(1e100) == 1e100

def test_extract_segment_text_raise_on_str():
    from backend.ai_rhythm import _extract_segment_text
    class ExceptionStr:
        def __str__(self):
            raise RuntimeError("Fatal str conversion")
    # 例外が発生することを確認（_analyze_single_segment でキャッチされるはず）
    with pytest.raises(RuntimeError):
        _extract_segment_text({"text": ExceptionStr()})

def test_analyze_rhythm_extra_keys_and_empty():
    # 空の辞書
    res = analyze_rhythm([{}])
    assert len(res) == 1
    assert res[0]['length'] == 0
    assert res[0]['status'] == 'ok'
    
    # 余分なキーがある辞書
    res2 = analyze_rhythm([{"id": 5, "text": "hello", "extra_key": "ignored", "another": 123}])
    assert len(res2) == 1
    assert res2[0]['index'] == 5
    assert res2[0]['length'] == 5
    assert res2[0]['status'] == 'ok'

def test_force_split_limit_cases_split_index_zero():
    from backend.ai_rhythm import semantic_split
    # split_index == 0 のケース
    # len(current_chunk) == 1 で、 target_chars + 5 < 1 となる場合。
    # target_chars = -5 のとき target_chars + 5 = 0。
    # current_chunk の長さが 1 の場合、 1 > 0 なので force split 条件を満たす。
    # split_index = 1 // 2 = 0 となる。
    # この時、無限ループせず正しく処理されることをテスト。
    res = semantic_split("a", target_chars=-5)
    assert res == ["a"]
    
    # target_chars が非常に大きい場合
    res2 = semantic_split("a" * 100, target_chars=10**18)
    assert res2 == ["a" * 100]

def test_reattach_punctuations_empty_and_special():
    from backend.ai_rhythm import _reattach_punctuations
    # 空のパーツ
    assert _reattach_punctuations(["", ""], "、") == []
    # 句読点のみ
    assert _reattach_punctuations(["、", "。"], "、。") == ["、", "。"]



def test_analyze_rhythm_extreme_float_target_chars():
    # target_chars が極小浮動小数点数（0.001）や負のゼロ（-0.0）の場合
    res1 = analyze_rhythm([{"id": 1, "text": "aaa"}], target_chars=0.001)
    # 長さ3なので too_short (len < 3) にはならず、3 <= 5.001 なので ok
    assert res1[0]['status'] == 'ok'
    
    res2 = analyze_rhythm([{"id": 2, "text": "a" * 6}], target_chars=0.001)
    # 6 > 5.001 なので too_long
    assert res2[0]['status'] == 'too_long'
    
    res3 = analyze_rhythm([{"id": 3, "text": "aaa"}], target_chars=-0.0)
    # 長さ3。-0.0 + 5 = 5.0。3 <= 5.0 なので ok
    assert res3[0]['status'] == 'ok'

def test_analyze_rhythm_nested_invalid_types(caplog):
    import logging
    # segments に辞書以外のコレクション（set, tuple, list）が含まれている場合の動作
    segments = [
        {"id": 1, "text": "valid"},
        (1, 2), # tuple
        [3, 4], # list
        {5, 6}, # set
        {"id": 2, "text": "valid_again"}
    ]
    with caplog.at_level(logging.WARNING):
        res = analyze_rhythm(segments)
    
    assert len(res) == 2
    assert res[0]['index'] == 1
    assert res[1]['index'] == 2
    
    warnings = [rec.message for rec in caplog.records if rec.levelname == "WARNING"]
    assert any("Segment at index 1 is not a dict" in w for w in warnings)
    assert any("Segment at index 2 is not a dict" in w for w in warnings)
    assert any("Segment at index 3 is not a dict" in w for w in warnings)

def test_semantic_split_huge_target_chars():
    # target_chars が非常に大きな値（1e10 等）の時、元のテキストがそのまま返される
    text = "こんにちは、世界。これはテストです。"
    res = semantic_split(text, target_chars=1e10)
    assert res == [text]

def test_analyze_single_segment_attribute_error(caplog):
    import logging
    from backend.ai_rhythm import analyze_rhythm
    
    class AttributeErrorSegment(dict):
        def get(self, key, default=None):
            if key == 'text':
                raise AttributeError("Simulated attribute error")
            return super().get(key, default)
            
    segments = [AttributeErrorSegment({"id": 1})]
    with caplog.at_level(logging.ERROR):
        res = analyze_rhythm(segments)
    
    assert len(res) == 1
    assert res[0]['status'] == 'error'
    assert any("Error processing segment" in rec.message for rec in caplog.records)

def test_semantic_split_overflow_error_mock(monkeypatch, caplog):
    import logging
    from backend.ai_rhythm import semantic_split
    
    # _resolve_target_chars をモックして OverflowError を発生させる
    import backend.ai_rhythm as ai_rhythm
    def mock_resolve_target_chars(*args, **kwargs):
        raise OverflowError("Simulated integer overflow")
        
    monkeypatch.setattr(ai_rhythm, "_resolve_target_chars", mock_resolve_target_chars)
    
    with caplog.at_level(logging.ERROR):
        res = semantic_split("test text", target_chars=13)
        
    assert res == ["test text"]
    assert any("Unexpected error in semantic_split" in rec.message for rec in caplog.records)

def test_reattach_punctuations_more_patterns():
    from backend.ai_rhythm import _reattach_punctuations
    
    # 句読点が先頭に来る場合
    assert _reattach_punctuations(["、", "hello"], "、") == ["、", "hello"]
    
    # 連続した句読点
    assert _reattach_punctuations(["hello", "、", "。", "world"], "、。") == ["hello、", "。", "world"]

def test_split_by_japanese_punctuations_regex_error(monkeypatch, caplog):
    import re
    import logging
    from backend.ai_rhythm import _split_by_japanese_punctuations
    
    def mock_re_split(*args, **kwargs):
        raise re.error("Regex compile error")
        
    monkeypatch.setattr(re, "split", mock_re_split)
    
    with caplog.at_level(logging.ERROR):
        res = _split_by_japanese_punctuations("hello", "、")
        
    assert res == ["hello"]
    assert any("Regex split failed in semantic_split" in rec.message for rec in caplog.records)


def test_resolve_target_chars_none_and_bool_false():
    from backend.ai_rhythm import _resolve_target_chars
    # target_chars = None の場合、デフォルトの 13 にリセットされること
    assert _resolve_target_chars(None) == 13
    # target_chars = False の場合、デフォルトの 13 にリセットされること
    assert _resolve_target_chars(False) == 13

def test_resolve_target_chars_negative_infinity():
    from backend.ai_rhythm import _resolve_target_chars
    # target_chars = float('-inf') の場合、デフォルトの 13 にリセットされること
    assert _resolve_target_chars(float('-inf')) == 13

def test_resolve_target_chars_huge_integer():
    from backend.ai_rhythm import _resolve_target_chars
    # 非常に大きい整数の場合、リセットされずそのままの値が返ること
    assert _resolve_target_chars(10**100) == 10**100

def test_reattach_punctuations_leading_punctuation():
    from backend.ai_rhythm import _reattach_punctuations
    # 句読点が先頭にある場合
    punctuations = "、。！？"
    parts = ["", "、", "こんにちは", "。"]
    assert _reattach_punctuations(parts, punctuations) == ["、", "こんにちは。"]

def test_reattach_punctuations_multiple_continuous_punctuations():
    from backend.ai_rhythm import _reattach_punctuations
    # 句読点のみが連続している場合
    punctuations = "、。！？"
    parts = ["、", "。", "！", "？"]
    assert _reattach_punctuations(parts, punctuations) == ["、", "。", "！", "？"]

def test_extract_segment_text_other_primitives():
    from backend.ai_rhythm import _extract_segment_text
    # 文字列以外のプリミティブ（float, bool, None）
    assert _extract_segment_text({"text": 3.14}) == 4   # "3.14" -> 長さ 4
    assert _extract_segment_text({"text": True}) == 4   # "True" -> 長さ 4
    assert _extract_segment_text({"text": None}) == 0   # "" -> 長さ 0



def test_split_by_japanese_punctuations_empty_and_invalid_types():
    from backend.ai_rhythm import _split_by_japanese_punctuations
    # 空文字列の場合
    assert _split_by_japanese_punctuations("hello", "") == ["hello"]
    # None の場合
    assert _split_by_japanese_punctuations("hello", None) == ["hello"]
    # 非文字列の場合
    assert _split_by_japanese_punctuations("hello", 123) == ["hello"]

def test_semantic_split_float_target_chars():
    from backend.ai_rhythm import semantic_split
    # target_chars が浮動小数点数（例: 13.5）の場合に正しく動作すること
    text = "a" * 20
    res = semantic_split(text, target_chars=13.5)
    assert res == ["a" * 10, "a" * 10]


def test_analyze_rhythm_completely_invalid_segments():
    # すべての要素が無効な型の場合
    segments = [None, "invalid", 123]
    res = analyze_rhythm(segments)
    assert res == []

def test_semantic_split_surrogate_pairs():
    # サロゲートペア文字を含むテキストの分割テスト
    text = "𠮷野家で美味しい牛丼を食べた。⚡️🔥"
    res = semantic_split(text, target_chars=5)
    assert "".join(res) == text


def test_analyze_rhythm_extreme_overflow_target_chars():
    # target_chars が極めて大きい float (1e308等) での比較で例外が起きないことの検証
    res = analyze_rhythm([{"id": 1, "text": "aaa"}], target_chars=1e308)
    assert res[0]['status'] == 'ok'


def test_split_by_japanese_punctuations_invalid_regex_characters(caplog):
    import logging
    from backend.ai_rhythm import _split_by_japanese_punctuations
    # punctuations にエスケープしないと正規表現エラーになる文字（例: "z-a" ）が含まれる場合
    # _split_by_japanese_punctuations の try-except 処理が機能してフォールバックすることを確認
    with caplog.at_level(logging.ERROR):
        res = _split_by_japanese_punctuations("hello-world", "z-a")
    assert res == ["hello-world"]
    assert any("Regex split failed in semantic_split" in rec.message for rec in caplog.records)


def test_force_split_long_chunks_empty_chunks():
    from backend.ai_rhythm import _force_split_long_chunks
    # chunks に空文字列が含まれる場合、無限ループにならずにそのまま返されることを確認
    assert _force_split_long_chunks([""], 13) == [""]
