"""backend/subtitle_engine/retold.py — 前の発話の尻尾の繰り返しを1つにする（2026-10-24 上野さんの回）。"""
from __future__ import annotations

from subtitle_engine import retold


def _seg(a, b, text):
    return {"start": a, "end": b, "sourceStart": a, "sourceEnd": b, "text": text}


def test_a_repeat_of_the_tail_goes_into_the_utterance_before():
    segs = [_seg(1113.18, 1119.18, "富上野先生はもうすごくハートがあったかくって、もう優しくって、全然怖くないですから。"),
            _seg(1119.28, 1123.38, "くって、あの、全然怖くないですから。"),
            _seg(1124.08, 1134.58, "近寄りがたくもないですから")]
    gone = retold.absorb(segs, fillers=["あの"])
    assert [s["text"] for s in gone] == ["くって、あの、全然怖くないですから。"]
    assert len(segs) == 2 and segs[0]["end"] == 1123.38 and segs[0]["sourceEnd"] == 1123.38


def test_a_short_echoing_reply_is_kept():
    segs = [_seg(0.0, 3.0, "大切なのは続けることですね"), _seg(3.2, 4.0, "そうですね")]
    assert retold.absorb(segs, fillers=[]) == [] and len(segs) == 2


def test_the_same_words_said_again_later_are_kept():
    segs = [_seg(0.0, 3.0, "全然怖くないですから本当に"), _seg(10.0, 13.0, "全然怖くないですから本当に")]
    assert retold.absorb(segs, fillers=[]) == [] and len(segs) == 2


def test_different_words_are_kept():
    segs = [_seg(0.0, 3.0, "もう優しくって全然怖くないですから"), _seg(3.1, 6.0, "近寄りがたくもないですから")]
    assert retold.absorb(segs, fillers=[]) == [] and len(segs) == 2
