"""校閲の後に、前の発話の尻尾と同じ字だけの発話が続いたら、前の発話に含める（2026-10-24 上野さんの回）。

2本目の対談の締め（素材 18分39秒〜）で、字幕に「もう優しくって　全然怖くないですから」の下に
「くって　全然怖くないですから」がもう一度出た（北原さんの朱入れ）。文字起こしは「…もう優しい」|
「作って、あの、全然怖くないですから。」と語の途中で割れていて、校閲（AI）が1つ目を
「もう優しくって、全然怖くないですから。」と言い切りまで補い、2つ目も「くって、あの、…」に直した。
同じ声が2つの発話に書かれている。区切りの境目の繰り返し（`gemini_transcriber.drop_boundary_echoes`）
と同じ形だが、校閲の後に起きるので、校閲の後に見る。

2つ目の字（句読点・空白と、字幕で消える言いよどみを外した形）が `MIN_CHARS` 字以上あって、
1つ目の尻尾と同じで、1つ目の終わりから `GAP_SEC` 秒以内に始まれば、2つ目を外して、その終わりの
時刻を1つ目に渡す（声の区間は残る・字幕は1つ目の字で出る）。短い相づちの繰り返し（「そうですね」）は
相手の言葉をなぞる返事でありうるので見ない。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# これより短い繰り返しは見ない（相手の言葉をなぞる返事でありうる）
MIN_CHARS = 8
# 1つ目の終わりからこの秒数以内に始まる発話だけを見る
GAP_SEC = 1.0
_IGNORE = frozenset("、。，．,.!?！？ 　\n「」『』")


def _bare(text: str, fillers: list[str]) -> str:
    body = "".join(ch for ch in str(text or "") if ch not in _IGNORE)
    for w in fillers:
        body = body.replace(w, "")
    return body


def _fillers() -> list[str]:
    try:
        from subtitle_engine import text_formatter
        return text_formatter.spoken_only_words()
    except Exception:  # noqa: BLE001 — 言いよどみが分からなくても、字そのままで比べる
        return []


def _times(seg: dict) -> tuple[float, float] | None:
    try:
        return float(seg["start"]), float(seg["end"])
    except (KeyError, TypeError, ValueError):
        return None


def absorb(segments: list[dict], fillers: list[str] | None = None) -> list[dict]:
    """前の発話の尻尾を繰り返すだけの発話を前の発話に含める（その場で書き換える）。返り値は外した発話。"""
    words = _fillers() if fillers is None else fillers
    gone: list[dict] = []
    keep: list[dict] = []
    for seg in segments:
        prev = keep[-1] if keep else None
        here, there = _times(seg), _times(prev) if prev else None
        if prev is not None and here and there and here[0] - there[1] <= GAP_SEC:
            body = _bare(seg.get("text", ""), words)
            if len(body) >= MIN_CHARS and _bare(prev.get("text", ""), words).endswith(body):
                prev["end"] = max(there[1], here[1])
                if seg.get("sourceEnd") is not None and prev.get("sourceEnd") is not None:
                    prev["sourceEnd"] = max(float(prev["sourceEnd"]), float(seg["sourceEnd"]))
                logger.info(f"前の発話の繰り返しを含めました: {here[0]:.1f}秒 {seg.get('text')!r}")
                gone.append(seg)
                continue
        keep.append(seg)
    segments[:] = keep
    return gone
