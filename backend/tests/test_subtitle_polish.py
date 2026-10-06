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
    ("。", "。"),
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
