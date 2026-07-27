# -*- coding: utf-8 -*-
import pytest
from pathlib import Path
from antigravity_pipeline import AntigravityPipeline

def test_normalize_subtitles_for_quality():
    pipeline = AntigravityPipeline()
    
    # テストデータ準備:
    # 1. 表示速度超過 (CPS = 19文字 / 1.0秒 = 19.0) のセグメント。目標表示時間は 19 / 5.5 = 3.45秒。
    # 2. 1行15文字超過 (28文字) のセグメント。
    segments = [
        {"id": "seg_001", "start": 0.0, "end": 1.0, "text": "非常に短い時間で多くの文字を表示する"},  # 19文字
        {"id": "seg_002", "start": 3.0, "end": 4.5, "text": "これは一連 of 文章であり１行あたり１５文字を超過しています。"},  # 28文字
    ]
    
    corrected = pipeline._normalize_subtitles_for_quality(segments)
    
    # 1. 表示速度の検証: 表示時間が 1.0秒 から 2.18秒 以上に延長されているか
    # seg_001 の end が 2.18秒 以上に延長され、かつ次のセグメント (3.0秒開始) の手前に収まっているか
    duration_001 = corrected[0]["end"] - corrected[0]["start"]
    # 19文字 / 5.5 ≒ 3.45秒。ただし次のセグメントの開始時間（3.0 - 0.05 = 2.95秒）でクリップされるため、
    # 終了時間は 2.95秒、表示時間は 2.95秒になるはず。
    assert corrected[0]["end"] <= 2.95
    assert duration_001 >= 2.0
    
    # 2. 1行文字数制限の検証: すべての行が15文字以下であるか
    for seg in corrected:
        for line in seg["text"].split("\n"):
            assert len(line.strip()) <= 15, f"Line length exceeds 15 chars: '{line}'"

def test_normalize_subtitles_empty_and_null():
    pipeline = AntigravityPipeline()
    assert pipeline._normalize_subtitles_for_quality([]) == []
    assert pipeline._normalize_subtitles_for_quality(None) == []

def test_normalize_subtitles_missing_timestamps():
    pipeline = AntigravityPipeline()
    segments = [
        {"id": "seg_001", "text": "表示時間キーがない非常に長い字幕文章のテストです。"}
    ]
    corrected = pipeline._normalize_subtitles_for_quality(segments)
    assert len(corrected) == 1
    for line in corrected[0]["text"].split("\n"):
        assert len(line.strip()) <= 15

def test_normalize_subtitles_partial_missing_timestamps():
    pipeline = AntigravityPipeline()
    segments = [
        {"id": "seg_001", "start": 0.0, "end": 1.0, "text": "非常に短い時間で多くの文字を表示する"},
        {"id": "seg_002", "text": "タイムスタンプが欠損しているテキスト"},
        {"id": "seg_003", "start": 5.0, "end": 6.0, "text": "通常のテキスト"}
    ]
    corrected = pipeline._normalize_subtitles_for_quality(segments)
    assert len(corrected) == 3
    # クラッシュせずに処理されることを確認
    assert corrected[0]["id"] == "seg_001"


def test_normalize_subtitles_millisecond_precision():
    pipeline = AntigravityPipeline()
    # 10文字の字幕。以前のGOOD基準(5.5 CPS)だと、目標表示時間は 1.81818秒。
    # これがミリ秒に丸められて 1.818秒 になると、10 / 1.818 ≒ 5.5005 CPS になり、GOOD(5.5)を上回ってしまう。
    # 新しいロジック（目標4.2 CPS ＆ ミリ秒切り上げ）では、
    # 10 / 4.2 = 2.3809... 秒 → 切り上げて 2.381 秒。
    # 10 / 2.381 ≒ 4.199 CPS となり、4.2 CPS（EXCELLENT）以下を維持する。
    segments = [
        {"id": "seg_001", "start": 0.0, "end": 1.0, "text": "漢字十文字の字幕です。"} # 10文字
    ]
    corrected = pipeline._normalize_subtitles_for_quality(segments)
    duration = corrected[0]["end"] - corrected[0]["start"]
    # 目標 2.381 秒以上になっているか
    assert duration >= 2.381
    
    # 実際に丸めても CPS が 4.2 以下であることを確認
    rounded_duration = round(duration * 1000) / 1000.0
    cps = 10 / rounded_duration
    assert cps <= 4.2

