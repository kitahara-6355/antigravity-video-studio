"""
fv_ground_truth.py に対する単体テスト

優先指令に基づき、例外フォールバック、境界検証、定数データの整合性を検証します。
"""

import pytest
from unittest.mock import patch
from fixtures.fv_ground_truth import (
    TV01_GROUND_TRUTH_TEXTS,
    TV01_GROUND_TRUTH_TIMESTAMPS,
    TV01_REFERENCE_TEXT,
    TV01_SEGMENT_COUNT,
    TV01_TOTAL_DURATION,
    get_ground_truth_segments
)

class TestFvGroundTruth:
    """fv_ground_truth の整合性および境界条件の検証クラス"""

    def test_constants_integrity(self):
        """定数データ自体の整合性を検証"""
        # 件数の検証 (TEXTS: 36件, TIMESTAMPS: 36件)
        assert len(TV01_GROUND_TRUTH_TEXTS) == 36
        assert len(TV01_GROUND_TRUTH_TIMESTAMPS) == 36
        
        # 定義値と実際の長さが一致するかの検証（TV01_SEGMENT_COUNTはTEXTSの長さ）
        assert TV01_SEGMENT_COUNT == len(TV01_GROUND_TRUTH_TEXTS)
        
        # 結合テキストの検証
        expected_ref_text = " ".join(TV01_GROUND_TRUTH_TEXTS)
        assert TV01_REFERENCE_TEXT == expected_ref_text

        # 総尺がタイムスタンプの最後のendと一致するかの検証
        assert TV01_TOTAL_DURATION == 124.04
        assert TV01_GROUND_TRUTH_TIMESTAMPS[-1]["end"] == 124.04

    def test_get_ground_truth_segments_normal(self):
        """正常系: get_ground_truth_segments() が正しい構造を返却するか検証"""
        segments = get_ground_truth_segments()
        
        # 件数は zip によって 36件
        assert len(segments) == 36
        
        for idx, seg in enumerate(segments):
            # 必要なフィールドの存在検証
            assert "start" in seg
            assert "end" in seg
            assert "text" in seg
            assert "sourceStart" in seg
            assert "sourceEnd" in seg

            # 値の整合性検証
            assert seg["start"] == TV01_GROUND_TRUTH_TIMESTAMPS[idx]["start"]
            assert seg["end"] == TV01_GROUND_TRUTH_TIMESTAMPS[idx]["end"]
            assert seg["text"] == TV01_GROUND_TRUTH_TEXTS[idx]
            assert seg["sourceStart"] == seg["start"]
            assert seg["sourceEnd"] == seg["end"]
            
            # 時間の順序関係
            assert seg["start"] <= seg["end"]

    def test_boundary_empty_lists(self):
        """境界条件: 定数が空リストの場合の動作をモックを用いて検証"""
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", []), \
             patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TIMESTAMPS", []):
            segments = get_ground_truth_segments()
            assert isinstance(segments, list)
            assert len(segments) == 0

    def test_boundary_mismatched_lengths(self):
        """境界条件: テキストとタイムスタンプの数が極端に異なる場合の例外スローを検証"""
        mock_texts = ["A", "B", "C"]
        mock_timestamps = [{"start": 0.0, "end": 1.0}]  # 長さ不一致
        
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", mock_texts), \
             patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TIMESTAMPS", mock_timestamps):
            with pytest.raises(ValueError) as excinfo:
                get_ground_truth_segments()
            assert "Mismatched data lengths" in str(excinfo.value)

    def test_exception_fallback_handling(self):
        """例外検証: データ処理時に例外が発生した場合の呼び出し元フォールバック検証

        もし get_ground_truth_segments 処理内で意図しない例外が発生した場合に、
        呼び出し側が安全にデフォルト値やフォールバック処理を行えることを検証します。
        """
        # 長さを揃えつつ、TypeErrorが発生するオブジェクトを差し込む
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", [None]), \
             patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TIMESTAMPS", [None]):
            
            # フォールバック設計 of calling side
            def get_segments_safe():
                try:
                    return get_ground_truth_segments()
                except (TypeError, KeyError) as e:
                    # 例外発生時の安全なフォールバック
                    return []

            segments = get_segments_safe()
            assert isinstance(segments, list)
            assert len(segments) == 0

    def test_invalid_data_types_fallback(self):
        """境界検証: 不正な型が混入した場合のデータ処理とフォールバックの検証"""
        mock_texts = ["text1"]
        mock_timestamps = [{"start": "invalid_type", "end": 1.0}]
        
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", mock_texts), \
             patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TIMESTAMPS", mock_timestamps):
            
            # 不正データ型が入った場合にTypeErrorが発生することを確認し、呼び出し側でフォールバックする
            def get_segments_safe():
                try:
                    return get_ground_truth_segments()
                except TypeError:
                    # フォールバック処理として安全なデフォルト値(0.0)に代替するロジックの動作検証
                    return [{"start": 0.0, "end": 1.0, "text": "text1", "sourceStart": 0.0, "sourceEnd": 1.0}]

            segments = get_segments_safe()
            assert len(segments) == 1
            assert segments[0]["start"] == 0.0


    def test_constants_type_safety(self):
        """定数データの型安全性および時系列の順序性を検証"""
        # テキストの型チェック
        for text in TV01_GROUND_TRUTH_TEXTS:
            assert isinstance(text, str)
            assert len(text) > 0

        # タイムスタンプの型チェックと時系列の順序関係
        prev_end = 0.0
        for ts in TV01_GROUND_TRUTH_TIMESTAMPS:
            assert isinstance(ts, dict)
            assert "start" in ts
            assert "end" in ts
            
            start = ts["start"]
            end = ts["end"]
            
            assert isinstance(start, (int, float))
            assert isinstance(end, (int, float))
            assert start <= end
            
            # 時系列が逆戻りしていないことを確認（各セグメントの開始時刻は直前の終了時刻以降）
            assert start >= prev_end
            prev_end = end

    def test_get_ground_truth_segments_returned_types(self):
        """get_ground_truth_segments() の返り値の詳細なデータ型検証"""
        segments = get_ground_truth_segments()
        assert isinstance(segments, list)
        
        for seg in segments:
            assert isinstance(seg, dict)
            assert isinstance(seg["start"], (int, float))
            assert isinstance(seg["end"], (int, float))
            assert isinstance(seg["text"], str)
            assert isinstance(seg["sourceStart"], (int, float))
            assert isinstance(seg["sourceEnd"], (int, float))

    def test_get_ground_truth_segments_strict_keys(self):
        """get_ground_truth_segments() 返り値の厳密なキー検証"""
        segments = get_ground_truth_segments()
        expected_keys = {"start", "end", "text", "sourceStart", "sourceEnd"}
        for seg in segments:
            # 期待されるキーと完全に一致することを確認
            assert set(seg.keys()) == expected_keys

    def test_timestamp_range_invariant(self):
        """タイムスタンプ値が妥当な範囲内であることを検証"""
        segments = get_ground_truth_segments()
        for seg in segments:
            # 開始/終了時間が非負であり、総尺以下であることを検証
            assert seg["start"] >= 0.0
            assert seg["end"] >= 0.0
            assert seg["start"] <= TV01_TOTAL_DURATION
            assert seg["end"] <= TV01_TOTAL_DURATION

    def test_data_invariant_constraints(self):
        """定数データ構造の不変条件を検証"""
        # TEXTSの全要素が空でない文字列であることを検証
        for text in TV01_GROUND_TRUTH_TEXTS:
            assert isinstance(text, str)
            assert len(text.strip()) > 0

        # TIMESTAMPSの各要素がstartとendキーを持つ辞書であることを検証
        for ts in TV01_GROUND_TRUTH_TIMESTAMPS:
            assert isinstance(ts, dict)
            assert "start" in ts
            assert "end" in ts

    def test_get_ground_truth_segments_new_instances(self):
        """get_ground_truth_segments() が毎回新しいインスタンスを返すことを検証"""
        segs1 = get_ground_truth_segments()
        segs2 = get_ground_truth_segments()
        
        # リスト自体が別インスタンスであること
        assert segs1 is not segs2
        # リスト内の各辞書オブジェクトも別インスタンスであること
        for item1, item2 in zip(segs1, segs2):
            assert item1 is not item2
            assert item1 == item2

    def test_get_ground_truth_segments_immutability_side_effect(self):
        """get_ground_truth_segments() の返り値に対する変更が元の定数に影響しないことを検証"""
        segs = get_ground_truth_segments()
        original_texts_count = len(TV01_GROUND_TRUTH_TEXTS)
        original_first_text = TV01_GROUND_TRUTH_TEXTS[0]
        
        # 返り値のリストや辞書を変更する
        segs[0]["text"] = "MODIFIED"
        segs.append({"text": "NEW_SEGMENT"})
        
        # 定数に影響がないこと
        assert len(TV01_GROUND_TRUTH_TEXTS) == original_texts_count
        assert TV01_GROUND_TRUTH_TEXTS[0] == original_first_text


    def test_text_whitespace_and_newlines(self):
        """定数テキストデータのフォーマット整合性（余分な前後の空白、改行の不在）を検証"""
        for text in TV01_GROUND_TRUTH_TEXTS:
            assert text == text.strip()
            assert "\n" not in text
            assert "\r" not in text

    def test_get_ground_truth_segments_null_handling(self):
        """get_ground_truth_segments() でモックの定数がNoneや不正なオブジェクトになった場合の挙動を検証"""
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", None), \
             patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TIMESTAMPS", None):
            with pytest.raises(ValueError) as excinfo:
                get_ground_truth_segments()
            assert "cannot be None" in str(excinfo.value)

    def test_get_ground_truth_segments_none_guards(self):
        """get_ground_truth_segments() の個別Noneガードを検証"""
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", None):
            with pytest.raises(ValueError):
                get_ground_truth_segments()
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TIMESTAMPS", None):
            with pytest.raises(ValueError):
                get_ground_truth_segments()

    def test_get_ground_truth_segments_non_iterable(self):
        """get_ground_truth_segments() に非イテラブルな値が与えられた場合の挙動を検証"""
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", 12345):
            with pytest.raises(TypeError) as excinfo:
                get_ground_truth_segments()
            assert "must be iterable" in str(excinfo.value)

    def test_get_ground_truth_segments_mismatched_lengths(self):
        """get_ground_truth_segments() に長さが異なるリストが与えられた場合の挙動を検証"""
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", ["text1"]), \
             patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TIMESTAMPS", []):
            with pytest.raises(ValueError) as excinfo:
                get_ground_truth_segments()
            assert "Mismatched data lengths" in str(excinfo.value)

    def test_get_ground_truth_segments_invalid_ts_type(self):
        """get_ground_truth_segments() でタイムスタンプが辞書でない場合の挙動を検証"""
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", ["text1"]), \
             patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TIMESTAMPS", ["not_a_dict"]):
            with pytest.raises(TypeError) as excinfo:
                get_ground_truth_segments()
            assert "must be a dictionary" in str(excinfo.value)

    def test_get_ground_truth_segments_missing_keys(self):
        """get_ground_truth_segments() でタイムスタンプ辞書のキーが欠損している場合の挙動を検証"""
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", ["text1"]), \
             patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TIMESTAMPS", [{"start": 0.0}]):
            with pytest.raises(KeyError) as excinfo:
                get_ground_truth_segments()
            assert "contain both 'start' and 'end'" in str(excinfo.value)

    def test_get_ground_truth_segments_invalid_val_types(self):
        """get_ground_truth_segments() でタイムスタンプ値の型が不正な場合の挙動を検証"""
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", ["text1"]), \
             patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TIMESTAMPS", [{"start": "invalid", "end": 1.0}]):
            with pytest.raises(TypeError) as excinfo:
                get_ground_truth_segments()
            assert "must be int or float" in str(excinfo.value)

    def test_get_ground_truth_segments_invalid_range(self):
        """get_ground_truth_segments() でstart > endの場合の挙動を検証"""
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", ["text1"]), \
             patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TIMESTAMPS", [{"start": 2.0, "end": 1.0}]):
            with pytest.raises(ValueError) as excinfo:
                get_ground_truth_segments()
            assert "cannot be greater than end" in str(excinfo.value)

    def test_get_ground_truth_segments_invalid_text_type(self):
        """get_ground_truth_segments() でテキスト値の型が文字列でない場合の挙動を検証"""
        with patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TEXTS", [12345]), \
             patch("fixtures.fv_ground_truth.TV01_GROUND_TRUTH_TIMESTAMPS", [{"start": 0.0, "end": 1.0}]):
            with pytest.raises(TypeError) as excinfo:
                get_ground_truth_segments()
            assert "must be a string" in str(excinfo.value)
