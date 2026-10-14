"""残す区間（素材の秒）を決める — どこで切るか。

2026-10-13 ユーザー指摘で作った。

- 「26秒『まいります』の発話フレーズの最後の言葉が切れている」
- 「冒頭1分10秒までの『あいさつ・ゲスト紹介』までのフレーズは、ノーカットの方が感じが良い。
  テーマトーク開始後は、カットが有効だと感じる」

それまでは、文字起こし（Gemini）の発話の区間をそのまま残し、発話と発話のすき間を切っていた。
文字起こしの時刻は 0.1〜0.5 秒刻みの推定で、発話の終わりが声より早いことがある。26秒は
「ます」の 0.3 秒手前で切れていた。37回目の書き出しを素材の音量で数えると、切れ目 146 か所の
うち 90 か所が声の途中で終わり、54 か所が声の途中から始まっていた。

決め方（`plan`）:

1. 発話の区間を並べ、すき間が `min_cut_sec` 未満ならつなぐ（従来の 0.3 秒）
2. 冒頭（あいさつ・紹介）は切らない。最初の質問の文が始まるまでのすき間を全部つなぐ
   （`opening_end`・`join_opening`）。中身を全部残すときだけ（`keep_all`）
3. 切る所を声の切れ目に寄せる（`snap_to_pauses`）。素材の音量で見た声が切れ目をまたいで
   続いていれば切らない。区間の終わりが声の中なら声が終わるまで延ばし、話し終わりの後ろに
   `pad_after_sec` を残す。始まりも同じく、話し始めの前に `pad_before_sec` を残す。延ばして
   残ったすき間が `min_cut_sec` 未満なら切らない。中身を全部残すときは、区間の端から続く声は
   どれだけ長くても（文字起こしに無い笑い声・起こし漏れでも）終わるまで残す

声は素材の音量と音声認識（`subtitle_engine.aligner`・ローカル）の両方で見る（2026-10-14）。
38回目の書き出しを認識で数えると、残した区間のすき間に認識の字が 91 字あった。

- 音量だけでは弱い語尾を声とみなさない。「書くんですよ」の「よ」、「あるんでしょうか」の「うか」、
  締めの「ありがとうございました」の「た」が、声の区間の終わりの 0.1〜0.3 秒後に聞こえていて
  切れていた。認識が続けて聞いた字（字の手前の間が切れる長さ未満）も声とみなす
  （`_speech_end`・`_speech_start`）
- 文字起こしの発話の区間は、言葉の後ろを落としていることがある。素材の 17分52秒の「その数字って
  日本の人口の2%だよね」は区間が手前の「言われている」で終わり、「日本の人口の2%だよね」の
  4 秒を切って字幕だけ出ていた。字幕の文字を認識の字と突き合わせ、その発話の言葉が聞こえた所
  まで区間を広げる（`heard_spans`）

区間は延ばすだけで縮めない。字幕は発話の区間（sourceStart/sourceEnd）で残す区間に割り当てる
（`smart_cut_engine.retime_segments`）ので、縮めると字幕が落ちる。

収録の段取りの声（カメラを止める前後の「ちょっと切ります」「撮った？」「止めた？」）は中身では
ないので残さない（`production_talk`）。外した発話の声は、前後の区間を延ばしても入れない（`exclude`）。

数字・冒頭・段取りの言葉はテンプレートの `cut_rules` で変えられる（`cut_rules()`）。
"""
from __future__ import annotations

import bisect
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

FRAME_SEC = 0.01
# 音声認識の字1つが声として続く長さ。字の時刻はその字の立ち上がり（`aligner.CHAR_SEC` と同じ）
HEARD_CHAR_SEC = 0.13
# 発話の区間からこれより離れて聞こえた字は、その発話の言葉とみなさない（別の所の同じ言葉）。
# 字幕の時刻合わせが認識の字を探す範囲（`aligner.SEARCH_AFTER_SEC`）と同じ
HEARD_WINDOW_SEC = 5.0

DEFAULT_CUT_RULES = {
    # 話し終わりの後ろに残す余白。文末の「す」は声が弱く、音量で見た話し終わりより少し続く
    # （26秒の「ます」は 30.33 秒で声の区間が終わり、30.45 秒で背景の音に戻った）。
    # 素材の 134 か所で測ると、声の区間の終わりから背景 +6dB まで下がるのに p95 で 0.12 秒
    "pad_after_sec": 0.15,
    # 話し始めの前に残す余白（息・子音の立ち上がり。背景 +3dB からの立ち上がりは p90 で 0.08 秒）
    "pad_before_sec": 0.10,
    # 余白を残して切れる間がこれより短ければ切らない（従来の結合の許容 0.3 秒と同じ）。
    # 余白と合わせて、0.55 秒以上の間を 0.25 秒に詰める
    "min_cut_sec": 0.3,
    # 中身を選んで削るとき、声がこれより長く続くなら延ばしきらず、この範囲で一番静かな所で
    # 切る（削った発話まで残さないため）。中身を全部残すときは声の中では切らない
    "max_shift_sec": 2.0,
    # 冒頭（あいさつ・ゲスト紹介）は切らない。最初の質問の文が始まるまで
    "keep_opening": True,
    # 最初の質問がこの秒数までに無ければ冒頭は守らない（見つけ損ねて本題まで守らないように）
    "opening_max_sec": 180.0,
    # 収録の段取りの声は残さない。中身を全部残すようにしたら、37分38秒〜47秒（3本目の素材の
    # 終わり）の「ちょっと切ります」「撮った？」「切、止めた？」が字幕付きで出るようになった
    "drop_production_talk": True,
    # 段取りの言葉。発話がこれと `production_ok_words` だけでできていて、これを1つでも含めば
    # 段取り。「大切に」「撮ってもらった」のように他の言葉と続く発話は中身なので外さない。
    # 「取ります」は「撮ります」の聞き違い（書いている場面の終わり 30分49秒「はい。取ります。はい。」）
    "production_cues": ["切ります", "切って", "切った", "切る", "切", "止めた", "止めて", "止めます",
                        "止める", "止まった", "止まってる", "撮った", "撮って", "撮ります", "撮る",
                        "撮れた", "撮れてる", "撮影", "取ります", "回して", "回ってる", "回ってます",
                        "回します", "回した", "カメラ", "録画", "録音", "本番", "スタート", "カット",
                        "よーい", "テイク"],
    # 段取りのやりとりに混ざる言葉。これだけの発話（「ちょっと待って。いい。よし。」）も、
    # 段取りの発話と続けて出てくれば段取り
    "production_ok_words": ["はい", "はーい", "うん", "ええ", "え", "あ", "あー", "えーと", "えっと",
                            "いい", "よし", "オッケー", "OK", "ちょっと", "待って", "じゃあ", "では",
                            "大丈夫", "もう一回", "お願いします"],
    # 段取りの発話とこの秒数以内に続く発話だけを、同じやりとりとみなす
    "production_gap_sec": 3.0,
}

SENTENCE_END = "。！？!?"
QUESTION_MARKS = "？?"
# 言葉の並びを比べる前に外す字（text_formatter._STANDALONE_STRIP と同じ。伸ばし棒も外す）
_PLAIN_STRIP = "、。，．,.！？!?…ー〜～ 　\n"


def cut_rules() -> dict:
    """テンプレートの cut_rules で上書きした値。読めない値・負の値は既定値のまま。"""
    rules = {k: list(v) if isinstance(v, list) else v for k, v in DEFAULT_CUT_RULES.items()}
    try:
        from template_config import template_config
        custom = template_config.get_cut_rules() or {}
    except Exception:  # テンプレートが無い・壊れていても切る
        custom = {}
    for key, default in DEFAULT_CUT_RULES.items():
        value = custom.get(key)
        if isinstance(default, bool):
            if isinstance(value, bool):
                rules[key] = value
        elif isinstance(default, list):
            if isinstance(value, list) and all(isinstance(w, str) and w.strip() for w in value):
                rules[key] = list(value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            rules[key] = float(value)
    return rules


def _field(seg, name, default=None):
    if isinstance(seg, dict):
        return seg.get(name, default)
    return getattr(seg, name, default)


def _span(seg) -> tuple[float, float]:
    start = _field(seg, "sourceStart")
    end = _field(seg, "sourceEnd")
    return (float(start if start is not None else _field(seg, "start", 0) or 0),
            float(end if end is not None else _field(seg, "end", 0) or 0))


def _widened(span: tuple[float, float], heard: dict | None) -> tuple[float, float]:
    h = (heard or {}).get(span)
    return (min(span[0], h[0]), max(span[1], h[1])) if h else span


def merge_ranges(segments, gap_sec: float, heard: dict | None = None) -> list[tuple[float, float]]:
    """発話の区間を並べ、すき間が gap_sec 以下ならつなぐ（従来のレンダリングの規則）。

    heard（`heard_spans`）があれば、発話の区間をその言葉が聞こえた所まで広げてから並べる。
    """
    spans = sorted(_widened(_span(s), heard) for s in segments)
    merged: list[tuple[float, float]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1] + gap_sec:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


# ------------------------------------------------------------------
# 冒頭（あいさつ・紹介）
# ------------------------------------------------------------------

def _ends_sentence(seg) -> bool:
    """字幕が文末で終わるか。句読点を外した字幕は、整形が残した印（`_ends_sentence`）で見る。"""
    if _field(seg, "_ends_sentence"):
        return True
    text = str(_field(seg, "text", "") or "").rstrip(" 　\n")
    return bool(text) and text[-1] in SENTENCE_END


def opening_end(segments, max_sec: float) -> float | None:
    """冒頭（あいさつ・ゲスト紹介）が終わる所＝最初の質問の文の始まり（素材の秒）。

    対談は「あいさつ → ゲストの紹介 → 最初の質問」で本題に入る（2026-10-13 の素材では
    1分15秒の「まず先生が、最初に書に出会ったきっかけっていうのは何かありますでしょうか？」）。
    「？」を含む最初の字幕から、前の字幕が文末で終わる所まで戻った字幕の発話の始まりを返す。
    最初の発話から max_sec 秒までに質問が無ければ None（冒頭は守らない）。
    """
    order = sorted(range(len(segments)), key=lambda i: (_span(segments[i])[0], i))
    if not order:
        return None
    first = _span(segments[order[0]])[0]
    for k, i in enumerate(order):
        if _span(segments[i])[0] - first > max_sec:
            return None
        text = str(_field(segments[i], "text", "") or "")
        if not any(q in text for q in QUESTION_MARKS):
            continue
        j = k
        while j > 0 and not _ends_sentence(segments[order[j - 1]]):
            j -= 1
        return _span(segments[order[j]])[0]
    return None


def _walled(end: float, start: float, walls) -> bool:
    """end〜start のすき間に、外した発話（walls）があるか。"""
    return any(end < b and a < start for a, b in walls)


def join_opening(ranges, until: float, walls=()) -> list[tuple[float, float]]:
    """until より前に始まる区間を全部つないで1つにする（冒頭のすき間は切らない）。
    外した発話（walls）があるすき間はつながない。"""
    out: list[tuple[float, float]] = []
    for start, end in ranges:
        if out and start <= until + 1e-6 and not _walled(out[-1][1], start, walls):
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


# ------------------------------------------------------------------
# 収録の段取りの声
# ------------------------------------------------------------------

def _plain(text) -> str:
    return "".join(ch for ch in str(text or "") if ch not in _PLAIN_STRIP)


def _made_of(body: str, cues: list[str], oks: list[str]) -> str | None:
    """body が言葉の並びだけでできているか。段取りの言葉を含めば "cue"、混ざる言葉だけなら "ok"、
    他の言葉が入っていれば None。"""
    if not body:
        return None
    # reach[i]: 0=届かない 1=混ざる言葉だけで届く 2=段取りの言葉を含んで届く
    reach = [0] * (len(body) + 1)
    reach[0] = 1
    for i in range(len(body)):
        if not reach[i]:
            continue
        for w in cues:
            if body.startswith(w, i):
                reach[i + len(w)] = 2
        for w in oks:
            if body.startswith(w, i):
                reach[i + len(w)] = max(reach[i + len(w)], reach[i])
    return {0: None, 1: "ok", 2: "cue"}[reach[-1]]


def production_talk(segments, rules: dict) -> set[int]:
    """収録の段取りの声（カメラを止める前後のやりとり）の字幕の番号。

    発話（同じ sourceStart/sourceEnd の字幕の行）ごとに見る。段取りの言葉と混ざる言葉だけで
    できていて段取りの言葉を含む発話（「ちょっと切ります」「撮った？」「切、止めた？」）と、
    それと `production_gap_sec` 以内に続く、混ざる言葉だけの発話（「はい」「ちょっと待って。
    いい。よし。」）。他の言葉が入る発話（「大切にしていること」）は中身なので外さない。
    """
    groups: dict[tuple[float, float], list[int]] = {}
    for i, seg in enumerate(segments):
        groups.setdefault(_span(seg), []).append(i)
    spans = sorted(groups)
    cues = [w for w in (_plain(w) for w in rules["production_cues"]) if w]
    oks = [w for w in (_plain(w) for w in rules["production_ok_words"]) if w]
    kinds = []
    for span in spans:
        lines = sorted(groups[span], key=lambda i: (float(_field(segments[i], "start", 0) or 0), i))
        kinds.append(_made_of("".join(_plain(_field(segments[i], "text", "")) for i in lines),
                              cues, oks))
    gap = rules["production_gap_sec"]
    drop = [kind == "cue" for kind in kinds]
    for k, kind in enumerate(kinds):
        if kind != "cue":
            continue
        j = k - 1
        while j >= 0 and kinds[j] and spans[j + 1][0] - spans[j][1] <= gap:
            drop[j] = True
            j -= 1
        j = k + 1
        while j < len(spans) and kinds[j] and spans[j][0] - spans[j - 1][1] <= gap:
            drop[j] = True
            j += 1
    return {i for k, span in enumerate(spans) if drop[k] for i in groups[span]}


# ------------------------------------------------------------------
# 声の切れ目
# ------------------------------------------------------------------

@dataclass
class SourceAudio:
    """素材の音。10ms ごとの音量（dBFS）と、声の区間（`sync.SpeechMap`）。

    heard は音声認識が字を聞いた時刻（素材の秒・昇順）。無ければ音量だけで声を見る。
    """
    levels: np.ndarray
    speech: object
    heard: list = field(default_factory=list)


def read_audio(path, rate: int = 16000) -> SourceAudio | None:
    """素材の音を読む（ffmpeg・ローカル）。読めなければ None（切れ目は動かさない）。"""
    try:
        if not path or not Path(path).is_file() or Path(path).stat().st_size == 0:
            return None
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
             "-ar", str(rate), "-f", "s16le", "-"],
            capture_output=True, timeout=1800)
        if proc.returncode != 0 or not isinstance(proc.stdout, bytes) or not proc.stdout:
            return None
        # 音が読めてから読み込む（subtitle_engine・numpy は読み込みが重く、読めない素材では要らない。
        # 字幕だけで切る経路は numpy を読まない）
        import numpy as np
        from subtitle_engine import sync
        levels = sync.frame_levels_db(np.frombuffer(proc.stdout, dtype=np.int16), rate)
        if len(levels) == 0:
            return None
        return SourceAudio(levels=levels, speech=sync.speech_map_from_levels(levels))
    except Exception as e:  # 音が読めなくても切る（切れ目は従来どおり）
        logger.warning(f"素材の音を読めないので切れ目を声に合わせません: {e}")
        return None


def read_heard(path) -> list[tuple[str, float]] | None:
    """素材の音声認識の字と時刻（`aligner.tokens_for`・ローカル・キャッシュあり）。使えなければ None。

    字幕の時刻合わせ（`smart_cut_engine._align_to_speech`）と同じ結果を使う。
    """
    try:
        if not path or not Path(path).is_file():
            return None
        from subtitle_engine import aligner
        return aligner.tokens_for(str(path)) or None
    except Exception as e:  # 認識が無くても切る（声は音量だけで見る）
        logger.warning(f"素材の音声認識を読めないので、声は音量だけで見ます: {e}")
        return None


def heard_spans(segments, tokens, window: float = HEARD_WINDOW_SEC) -> dict:
    """発話（`_span`）ごとに、その字幕の言葉を音声認識が聞いた区間（素材の秒）。

    字幕の文字を認識の字と突き合わせる（`aligner.align_captions`。字幕の時刻合わせと同じ全体の
    突き合わせ）。発話の区間から window 秒より離れた字（別の所の同じ言葉）は使わない。
    """
    from subtitle_engine import aligner
    order = sorted(range(len(segments)), key=lambda i: (_span(segments[i])[0], i))
    caps = []
    for i in order:
        lo, hi = _span(segments[i])
        start, end = _field(segments[i], "start"), _field(segments[i], "end")
        caps.append({"text": str(_field(segments[i], "text", "") or ""),
                     "start": float(lo if start is None else start),
                     "end": float(hi if end is None else end)})
    aligner.align_captions(caps, tokens)
    out: dict = {}
    for i, cap in zip(order, caps):
        key = _span(segments[i])
        lo, hi = key
        for _, t in cap.get("_asr_marks") or ():
            t = float(t)
            if lo - window <= t and t + HEARD_CHAR_SEC <= hi + window:
                a, b = out.get(key, (t, t + HEARD_CHAR_SEC))
                out[key] = (min(a, t), max(b, t + HEARD_CHAR_SEC))
    return out


def _is_span(item) -> bool:
    return (isinstance(item, (tuple, list)) and len(item) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in item))


def _walls_and_widening(segments, exclude, heard: dict) -> tuple[list, dict]:
    """外した発話の区間（walls）と、残す発話を広げる区間。

    外した発話が字幕で渡されたら、その言葉が聞こえた区間を walls にする（文字起こしの区間は粗く、
    素材の 37分47秒で段取りの声の区間が次の質問の「先生が」の「先」まで掛かっていた）。聞こえた字が
    無ければ文字起こしの区間のまま。残す発話は、walls の向こうまでは広げない。
    """
    walls = [(float(a), float(b)) for a, b in (x for x in exclude if _is_span(x))]
    walls += [heard.get(_span(x)) or _span(x) for x in exclude if not _is_span(x)]
    walls.sort()
    widen: dict = {}
    for key in {_span(s) for s in segments}:
        h = heard.get(key)
        if not h:
            continue
        lo, hi = key
        floor = max([h[0]] + [b for a, b in walls if b <= lo + 1e-6])
        ceil = min([h[1]] + [a for a, b in walls if a >= hi - 1e-6])
        if floor < ceil:
            widen[key] = (floor, ceil)
    return walls, widen


def _run_at(speech, t: float) -> int | None:
    """t を含む声の区間の番号（onset <= t < offset）。"""
    i = bisect.bisect_right(speech.onsets, t) - 1
    if i >= 0 and t < speech.offsets[i]:
        return i
    return None


def _voice_end(speech, t: float) -> float | None:
    """t の直前までの声が終わる時刻（t が声の中ならその声の終わり、間なら前の声の終わり）。"""
    i = _run_at(speech, t - FRAME_SEC / 2)
    if i is not None:
        return speech.offsets[i]
    i = bisect.bisect_right(speech.offsets, t) - 1
    return speech.offsets[i] if i >= 0 else None


def _voice_start(speech, t: float) -> float | None:
    """t からの声が始まる時刻（t が声の中ならその声の始まり、間なら次の声の始まり）。"""
    i = _run_at(speech, t)
    if i is not None:
        return speech.onsets[i]
    i = bisect.bisect_left(speech.onsets, t)
    return speech.onsets[i] if i < len(speech.onsets) else None


def _speech_end(audio: SourceAudio, t: float, chain_gap: float) -> float | None:
    """t の直前までの声が終わる時刻（`_voice_end`）に、音声認識が続けて聞いた字を足したもの。

    音量で見た声の区間は、弱い語尾で早く終わる（「書くんですよ」の「よ」が声の区間の終わりの
    0.21 秒後に聞こえていた）。字の手前の間が chain_gap 未満なら声が続いているとみなし、その字の
    後ろ（字を含む声の区間があればその終わり）まで延ばす。
    """
    speech, heard = audio.speech, audio.heard
    end = _voice_end(speech, t)
    if end is None or not heard:
        return end
    k = bisect.bisect_right(heard, end - HEARD_CHAR_SEC)
    while k < len(heard) and heard[k] - end < chain_gap:
        end = max(end, heard[k] + HEARD_CHAR_SEC)
        i = _run_at(speech, heard[k])
        if i is not None:
            end = max(end, speech.offsets[i])
        k += 1
    return end


def _speech_start(audio: SourceAudio, t: float, chain_gap: float) -> float | None:
    """t からの声が始まる時刻（`_voice_start`）を、音声認識が続けて聞いた字の所まで戻したもの。"""
    speech, heard = audio.speech, audio.heard
    start = _voice_start(speech, t)
    if start is None or not heard:
        return start
    k = bisect.bisect_left(heard, start) - 1
    while k >= 0 and start - (heard[k] + HEARD_CHAR_SEC) < chain_gap:
        start = min(start, heard[k])
        i = _run_at(speech, heard[k])
        if i is not None:
            start = min(start, speech.onsets[i])
        k -= 1
    return start


def _quietest(levels: np.ndarray, lo: float, hi: float) -> float:
    """lo〜hi 秒で一番静かな所（0.1 秒の平均で見る）。"""
    import numpy as np
    a = max(0, int(round(lo / FRAME_SEC)))
    b = min(len(levels), int(round(hi / FRAME_SEC)))
    if b - a <= 0:
        return lo
    window = levels[a:b]
    k = min(10, len(window))
    smooth = np.convolve(window, np.ones(k) / k, mode="same")
    return (a + int(np.argmin(smooth))) * FRAME_SEC


def snap_to_pauses(ranges, audio: SourceAudio | None, rules: dict,
                   cut_through_voice: bool = False, walls=()) -> tuple[list, dict]:
    """切る所を声の切れ目に寄せる。返り値は (残す区間, 何を動かしたか)。

    音が無ければ区間はそのまま返す。区間は延ばすだけで縮めない。
    cut_through_voice: 声が max_shift_sec より長く続くとき、一番静かな所で切る（中身を選んで
    削るとき）。False なら声が終わるまで延ばす（すき間の声も残す）。
    walls: 外した発話の区間（収録の段取りの声）。声が続いていても、そこまでは延ばさない
    （手前の一番静かな所で切る）。
    """
    spans = [[float(a), float(b)] for a, b in ranges]
    if not spans or audio is None:
        return [tuple(s) for s in spans], {}
    speech = audio.speech
    pad_before = rules["pad_before_sec"]
    pad_after = rules["pad_after_sec"]
    max_shift = rules["max_shift_sec"] if cut_through_voice else float("inf")
    # 認識の字の手前の間がこれ未満なら、声が続いている（余白を残して切れる長さに足りない）
    chain_gap = pad_after + rules["min_cut_sec"] + pad_before
    duration = len(audio.levels) * FRAME_SEC
    walls = sorted((float(a), float(b)) for a, b in walls)
    info = {"gaps": 0, "extended_end": 0, "pulled_start": 0, "joined": 0, "quiet": 0}

    def end_at(t: float) -> tuple[float, str]:
        voice = _speech_end(audio, t, chain_gap)
        if voice is None or voice + pad_after <= t:
            return t, ""
        reach = max_shift
        wall = min((a for a, b in walls if b > t), default=None)
        if wall is not None:
            if wall <= t:
                return t, ""
            reach = min(reach, wall - t)
        if voice + pad_after - t > reach:
            return max(t, _quietest(audio.levels, t, t + reach)), "quiet"
        return min(voice + pad_after, duration), "moved"

    def start_at(t: float) -> tuple[float, str]:
        voice = _speech_start(audio, t, chain_gap)
        if voice is None or voice - pad_before >= t:
            return t, ""
        reach = max_shift
        wall = max((b for a, b in walls if a < t), default=None)
        if wall is not None:
            if wall >= t:
                return t, ""
            reach = min(reach, t - wall)
        if t - (voice - pad_before) > reach:
            return min(t, _quietest(audio.levels, t - reach, t)), "quiet"
        return max(0.0, voice - pad_before), "moved"

    spans[0][0], _ = start_at(spans[0][0])
    out = [spans[0]]
    for start, end in spans[1:]:
        prev = out[-1]
        info["gaps"] += 1
        # すき間に外した発話があれば、声が続いていても間が短くても切る
        walled = _walled(prev[1], start, walls)
        # 声が切れ目をまたいで続いている（間が無い）なら切らない
        i = _run_at(speech, prev[1] - FRAME_SEC / 2)
        if not walled and i is not None and i == _run_at(speech, start):
            prev[1] = max(prev[1], end)
            info["joined"] += 1
            continue
        new_end, how_end = end_at(prev[1])
        new_start, how_start = start_at(start)
        if not walled and new_start - new_end < rules["min_cut_sec"]:
            prev[1] = max(prev[1], end)
            info["joined"] += 1
            continue
        new_start = max(new_start, new_end)
        info["extended_end"] += how_end == "moved"
        info["pulled_start"] += how_start == "moved"
        info["quiet"] += (how_end == "quiet") + (how_start == "quiet")
        prev[1] = new_end
        out.append([new_start, end])
    out[-1][1], _ = end_at(out[-1][1])
    return [(a, b) for a, b in out], info


def plan(segments, source_path=None, *, keep_all: bool = False,
         rules: dict | None = None, exclude=()) -> tuple[list[tuple[float, float]], dict]:
    """残す区間（素材の秒）と、決め方の記録を返す。

    keep_all: 中身（発話）を全部残すとき True。冒頭（最初の質問の文の前まで）は切らず、
    声の中でも切らない。中身を選んで削るときは False（冒頭も選ばれない発話があり、つなぐと
    その声が字幕無しで入る。長く続く声は一番静かな所で切る）。
    exclude: 外した発話（収録の段取りの声）。字幕か区間（素材の秒）で渡す。前後の区間を
    延ばしても入れない。
    素材の音声認識が読めれば、発話の言葉が聞こえた所まで区間を広げ（`heard_spans`）、
    認識が続けて聞いた字も声とみなす（`_speech_end`・`_speech_start`）。
    """
    rules = rules or cut_rules()
    info: dict = {}
    exclude = list(exclude)
    tokens = read_heard(source_path)
    dropped = [x for x in exclude if not _is_span(x)]
    heard = heard_spans(list(segments) + dropped, tokens) if tokens else {}
    walls, widen = _walls_and_widening(segments, exclude, heard)
    if widen:
        info["heard_widened"] = sum(1 for span, w in widen.items() if _widened(span, widen) != span)
    ranges = merge_ranges(segments, rules["min_cut_sec"], widen)
    if keep_all and rules["keep_opening"]:
        until = opening_end(segments, rules["opening_max_sec"])
        if until is not None:
            ranges = join_opening(ranges, until, walls)
            info["opening_until"] = until
    audio = read_audio(source_path)
    if audio is not None and tokens:
        audio.heard = sorted(float(t) for _, t in tokens)
    snapped, moved = snap_to_pauses(ranges, audio, rules,
                                    cut_through_voice=not keep_all, walls=walls)
    info.update(moved)
    return snapped, info
