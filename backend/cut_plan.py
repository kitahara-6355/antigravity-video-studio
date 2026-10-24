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
- 認識が聞けなかった言葉にも声はある。素材の 38分45秒「原毛の質まで悪くなっちゃって」は「で」まで
  しか聞けず、「悪くなっちゃって」の声を間として切っていた（2026-10-17 ユーザー指摘）。字幕の
  言葉のうち、最後に聞こえた字より後ろ（最初に聞こえた字より前）の字の数ぶんの声までは、その
  発話の声とみなして区間を広げる（`unheard_reach`）

区間は延ばすだけで縮めない。字幕は発話の区間（sourceStart/sourceEnd）で残す区間に割り当てる
（`smart_cut_engine.retime_segments`）ので、縮めると字幕が落ちる。

ただし映像の切り替わり（収録の継ぎ目）の向こうが少しだけ映る所は切り落とす（`trim_flashes`。
2026-10-17 ユーザー指摘「左にいる美麗さんが画面から消えているシーンが1秒未満で映りこんでいる」。
素材の 37分48秒の継ぎ目の 0.41 秒手前から残していた）。パイプラインは結合した1本を受け取るので、
継ぎ目は映像から見つける（`read_shots`）。切り落として区間からはみ出した発話の区間は、区間の中に
縮める（`fit_spans`）。

収録の段取りの声（カメラを止める前後の「ちょっと切ります」「撮った？」「止めた？」）は中身では
ないので残さない（`production_talk`）。外した発話の声は、前後の区間を延ばしても入れない（`exclude`）。

だれも話さない長い所（`scene_min_sec` 以上）は、会話の間ではなく動作の場面なので切らない
（`find_scenes`・`join_scenes`。2026-10-14）。間を詰める規則では、先生が字を書く約1分（素材の
29分54秒〜30分53秒）が書き始めと「はい」の前後の約10秒になっていた。場面の中の段取りの声
（30分49秒「はい。取ります。はい。」）は外したまま。

区間の端は映像のフレームの境目に置く（`on_frames`。2026-10-17）。映像はフレーム単位でしか切れず、
端がフレームの間にあると区間ごとに映像は最大1フレーム、音は 10ms の端数が出て別々に積み上がる。
54回目は 42 区間の端数と、素材の 29分58秒のつなぎ目で欠けていた音 65ms を詰めたのが重なり、
35〜38分で映像が音より約 0.25 秒遅れていた。切る側（`smart_cut_engine._cut_kept_ranges_exact`）は
映像をフレーム、音を1フレームぶんずつ数えて切る。

数字・冒頭・場面・段取りの言葉はテンプレートの `cut_rules` で変えられる（`cut_rules()`）。
"""
from __future__ import annotations

import bisect
import json
import logging
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
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
# 認識が聞けなかった字1つが声として続く長さの上限。伸ばしてゆっくり言っても収まる長さ
# （聞こえた字は1字 `HEARD_CHAR_SEC`）。38分45秒の「悪くなっちゃって」は8字で 1.4 秒
UNHEARD_CHAR_SEC = 0.3
# 認識が聞けなかった言葉の声の手前に置ける間（言いさしの息継ぎ）。38分45秒は「で」の後 0.57 秒
UNHEARD_GAP_SEC = 1.0
# 映像が切り替わった（収録の継ぎ目・カメラの切り替え）とみなす ffmpeg scdet の値。raw 4本（43分）を
# 見ると、継ぎ目の3か所が 7.0・19.7・20.4、手や体の動きは 2.9 以下だった。7.0 は同じ構図で人だけが
# いなくなる継ぎ目（素材の 37分48秒）
SHOT_CHANGE_SCORE = 5.0
# 映像を見るときに書き残す値の下限。キャッシュは値ごと持ち、SHOT_CHANGE_SCORE は使うときに当てる
SHOT_SCAN_FLOOR = 2.0
SHOTS_CACHE_VERSION = 1
# 映像のフレームレートとして受け取る範囲。外れた値（ffprobe の 0/0、静止画の 90000/1）は読めないとみなす
FRAME_RATE_RANGE = (1, 240)
# 切り落とすときに区間の端を切り替わりのフレームの手前に置く幅（フレームの時刻の丸めを吸収する）
SHOT_EDGE_SEC = 0.005

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
    # だれも話さない長い所は、動作の場面（字を書く・作品を見せる）なので切らない。会話の間では
    # ない。中身を全部残すときだけ（`join_scenes`）
    "keep_scenes": True,
    # 発話と発話（外した段取りの声も含む）のすき間がこれ以上なら場面。会話の間は長くても数秒で、
    # raw 4本（43分）で 6 秒以上のすき間は、字を書く場面の2つ（27 秒・23 秒）だけだった
    "scene_min_sec": 10.0,
    # 収録の段取りの声は残さない。中身を全部残すようにしたら、37分38秒〜47秒（3本目の素材の
    # 終わり）の「ちょっと切ります」「撮った？」「切、止めた？」が字幕付きで出るようになった
    "drop_production_talk": True,
    # 段取りの言葉。発話がこれと `production_ok_words` だけでできていて、これを1つでも含めば
    # 段取り。「大切に」「撮ってもらった」のように他の言葉と続く発話は中身なので外さない。
    # 「取ります」は「撮ります」の聞き違い（書いている場面の終わり 30分49秒「はい。取ります。はい。」）。
    # 「OKです」は撮り終わりの合図（2本目の対談の締めの後「はいOKです」・2026-10-24 北原さんがカットを指示）
    "production_cues": ["切ります", "切って", "切った", "切る", "切", "止めた", "止めて", "止めます",
                        "止める", "止まった", "止まってる", "撮った", "撮って", "撮ります", "撮る",
                        "撮れた", "撮れてる", "撮影", "取ります", "回して", "回ってる", "回ってます",
                        "回します", "回した", "カメラ", "録画", "録音", "本番", "スタート", "カット",
                        "よーい", "テイク", "OKです", "オッケーです"],
    # 段取りのやりとりに混ざる言葉。これだけの発話（「ちょっと待って。いい。よし。」）も、
    # 段取りの発話と続けて出てくれば段取り
    "production_ok_words": ["はい", "はーい", "うん", "ええ", "え", "あ", "あー", "えーと", "えっと",
                            "いい", "よし", "オッケー", "OK", "ちょっと", "待って", "じゃあ", "では",
                            "大丈夫", "もう一回", "お願いします"],
    # 段取りの発話とこの秒数以内に続く発話だけを、同じやりとりとみなす
    "production_gap_sec": 3.0,
    # 中身を全部残すとき、発話と発話のすき間にこの秒数以上の声があれば切らない。どの発話にも
    # 入らなかった声（文字起こしの時刻が早く終わった言葉）で、すき間として切ると言葉が消える
    # （2本目の対談 7分58秒「ナースは女神様に見えましたし」・2026-10-24 北原さんの朱入れ）
    "unclaimed_voice_sec": 0.6,
    # 区間の端で、映像の切り替わり（収録の継ぎ目）の手前（後ろ）がこれより短く、そこに言葉が無ければ
    # 切り落とす。1秒に満たない映像は、見る人には別の場面が一瞬映ったように見える
    "min_shot_sec": 1.0,
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
# だれも話さない場面（字を書く・作品を見せる）
# ------------------------------------------------------------------

def find_scenes(spans, min_sec: float) -> list[tuple[float, float]]:
    """発話の区間 spans（素材の秒）のすき間のうち、min_sec 秒以上のもの。

    spans には外した発話（段取りの声）も入れる。段取りの声が続く所（37分38〜47秒）は、
    1つ1つのすき間が短いので場面にならない。最初の発話の前・最後の発話の後ろは場面にしない。
    """
    scenes: list[tuple[float, float]] = []
    end = None
    for a, b in sorted((float(a), float(b)) for a, b in spans):
        if end is not None and a - end >= min_sec:
            scenes.append((end, a))
        end = b if end is None else max(end, b)
    return scenes


def join_scenes(ranges, scenes, gap_sec: float, before_sec: float = 0.0) -> list[tuple[float, float]]:
    """場面（`find_scenes`）を残す区間に足してつなぐ。

    場面の終わりは次の発話の始まりなので、before_sec 手前で止める（次が外した発話なら、
    その声を入れない。残す発話ならつながる）。
    """
    spans = sorted([(float(a), float(b)) for a, b in ranges]
                   + [(a, max(a, b - before_sec)) for a, b in scenes])
    merged: list[tuple[float, float]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1] + gap_sec:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


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
# 人の指示で切る・字幕だけ消す（校正台帳の cuts）
# ------------------------------------------------------------------

# 発話の区間のこの割合以上が指示の区間に入っていれば、その発話を指示の対象にする
HUMAN_CUT_SHARE = 0.5


def human_cuts(segments, cuts, heard: dict | None = None) -> tuple[set[int], set[int]]:
    """人が字幕を見て指示した区間（`review_ledger` の cuts）に入る発話の番号。

    返り値は (映像ごと切る発話, 字幕だけ消す発話)。指示の区間は画面で見た字幕の時刻（素材の秒）で、
    文字起こしの区間とは 1 秒ほどずれる。聞こえた区間（`heard_spans`）があればそれで見る。
    発話の区間の `HUMAN_CUT_SHARE` 以上が区間に入るか、区間に掛かっていて字が指示した字幕（``text`` を
    「 / 」で区切ったもの）と同じなら対象（「はい」の文字起こしの区間は 783.7〜784.9 秒で、
    指示の区間 784.37〜 に半分も入らず残った・2026-10-24 v3）。
    """
    cut, hide = set(), set()
    seen = [{_plain(t) for t in str(c.get("text") or "").split(" / ")} - {""} for c in cuts]
    for i, seg in enumerate(segments):
        lo, hi = (heard or {}).get(_span(seg)) or _span(seg)
        length = max(hi - lo, 1e-6)
        body = _plain(_field(seg, "text", ""))
        for c, texts in zip(cuts, seen):
            a, b = float(c["start"]), float(c["end"])
            inside = max(0.0, min(hi, b) - max(lo, a))
            if inside / length >= HUMAN_CUT_SHARE or (inside > 0 and body in texts):
                (cut if c.get("mode", "cut") == "cut" else hide).add(i)
                break
    return cut, hide


def add_spans(ranges, spans) -> list[tuple[float, float]]:
    """区間を足してつなぐ。"""
    merged: list[list[float]] = []
    for a, b in sorted([(float(a), float(b)) for a, b in ranges] + [(float(a), float(b)) for a, b in spans]):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def subtract_spans(ranges, spans) -> list[tuple[float, float]]:
    """区間から spans を除く。"""
    out = [(float(a), float(b)) for a, b in ranges]
    for c0, c1 in spans:
        c0, c1 = float(c0), float(c1)
        nxt = []
        for a, b in out:
            if c1 <= a or b <= c0:
                nxt.append((a, b))
                continue
            if a < c0:
                nxt.append((a, c0))
            if c1 < b:
                nxt.append((c1, b))
        out = nxt
    return out


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
    """素材の音を、映像と同じ時間軸で読む（`media_timeline.read_pcm`・ffmpeg・ローカル）。
    読めなければ None（切れ目は動かさない）。"""
    try:
        if not path or not Path(path).is_file() or Path(path).stat().st_size == 0:
            return None
        import media_timeline
        try:
            pcm = media_timeline.read_pcm(path, rate)
        except RuntimeError:
            return None
        if not isinstance(pcm, bytes) or not pcm:
            return None
        # 音が読めてから読み込む（subtitle_engine・numpy は読み込みが重く、読めない素材では要らない。
        # 字幕だけで切る経路は numpy を読まない）
        import numpy as np
        from subtitle_engine import sync
        levels = sync.frame_levels_db(np.frombuffer(pcm, dtype=np.int16), rate)
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


def heard_marks(segments, tokens, window: float = HEARD_WINDOW_SEC) -> tuple[dict, dict]:
    """発話（`_span`）ごとに、音声認識が聞いたその字幕の字と、発話の字数。

    返り値は ({発話: [(発話の言葉の何字目か, 素材の秒), ...]}, {発話: 字数})。字は突き合わせ用に
    そろえた形（`aligner.norm_char`）で数え、発話の行を順につないで数える。
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
    marks: dict = {}
    length: dict = {}
    for i, cap in zip(order, caps):
        key = _span(segments[i])
        lo, hi = key
        base = length.get(key, 0)
        length[key] = base + len(aligner._norm_text(cap["text"]))
        for c, t in cap.get("_asr_marks") or ():
            t = float(t)
            if lo - window <= t and t + HEARD_CHAR_SEC <= hi + window:
                marks.setdefault(key, []).append((base + int(c), t))
    return marks, length


def _spans_of(marks: dict) -> dict:
    return {key: (min(t for _, t in m), max(t for _, t in m) + HEARD_CHAR_SEC) for key, m in marks.items()}


def heard_spans(segments, tokens, window: float = HEARD_WINDOW_SEC) -> dict:
    """発話（`_span`）ごとに、その字幕の言葉を音声認識が聞いた区間（素材の秒・`heard_marks`）。"""
    return _spans_of(heard_marks(segments, tokens, window)[0])


def _reach_after(speech, t: float, budget: float, limit: float) -> float | None:
    """t（聞こえた最後の字の後ろ）から後ろに、聞けなかった言葉の声が続く所。続く声が無ければ None。

    声の区間を、間が UNHEARD_GAP_SEC 以下で続き、t からの声の長さが budget に収まり、limit
    （ほかの言葉）を越えない所までたどる。
    """
    used = 0.0
    end = t
    i = _run_at(speech, t - FRAME_SEC / 2)
    if i is not None:
        # 聞こえた字の声が t の後ろへ続いていれば、その分も聞けなかった言葉の声
        if speech.offsets[i] > limit:
            return None
        used, end = max(0.0, speech.offsets[i] - t), max(t, speech.offsets[i])
        i += 1
    else:
        i = bisect.bisect_left(speech.onsets, t)
    reach = None
    while i < len(speech.onsets):
        on, off = speech.onsets[i], speech.offsets[i]
        used += off - on
        if on - end > UNHEARD_GAP_SEC or off > limit or used > budget:
            break
        end = reach = off
        i += 1
    return reach


def _reach_before(speech, t: float, budget: float, limit: float) -> float | None:
    """t（聞こえた最初の字）から前に、聞けなかった言葉の声が始まる所（`_reach_after` の逆向き）。"""
    used = 0.0
    start = t
    i = _run_at(speech, t)
    if i is not None:
        if speech.onsets[i] < limit:
            return None
        used, start = max(0.0, t - speech.onsets[i]), min(t, speech.onsets[i])
        i -= 1
    else:
        i = bisect.bisect_right(speech.offsets, t) - 1
    reach = None
    while i >= 0:
        on, off = speech.onsets[i], speech.offsets[i]
        used += off - on
        if start - off > UNHEARD_GAP_SEC or on < limit or used > budget:
            break
        start = reach = on
        i -= 1
    return reach


def unheard_reach(marks: dict, length: dict, audio: SourceAudio, walls=()) -> dict:
    """発話ごとに、音声認識が聞けなかった言葉の声が届く所（素材の秒）。{発話: (前, 後ろ)}。

    marks・length は `heard_marks`。字幕の言葉のうち、最後に聞こえた字より後ろの N 字は、その後に
    続けて言っている。認識が聞けなくても声はある（素材の 38分45秒「原毛の質まで悪くなっちゃって」は
    「で」までしか聞けず、「悪くなっちゃって」の声を間として切っていた）。聞こえた所の後ろの声を、
    間が UNHEARD_GAP_SEC 以下で続き、声の長さが N × UNHEARD_CHAR_SEC に収まるかぎり、その発話の
    声とみなす（`_reach_after`）。ほかの発話の聞こえた字と、外した発話の区間（walls）は越えない。
    最初に聞こえた字より前の字も同じに前へ見る（`_reach_before`）。届かない側は None。
    """
    speech = audio.speech
    owned = sorted((t, key) for key, m in marks.items() for _, t in m)
    times = [t for t, _ in owned]
    out: dict = {}
    for key, m in marks.items():
        offsets = [c for c, _ in m]
        heard = [t for _, t in m]
        head, tail = min(offsets), length.get(key, 0) - 1 - max(offsets)
        lo, hi = min(heard), max(heard) + HEARD_CHAR_SEC
        before = after = None
        if tail > 0:
            k = bisect.bisect_right(times, hi - HEARD_CHAR_SEC)
            while k < len(owned) and owned[k][1] == key:
                k += 1
            limit = min([owned[k][0] if k < len(owned) else float("inf")]
                        + [a for a, _ in walls if a >= hi - FRAME_SEC])
            after = _reach_after(speech, hi, tail * UNHEARD_CHAR_SEC, limit)
        if head > 0:
            k = bisect.bisect_left(times, lo) - 1
            while k >= 0 and owned[k][1] == key:
                k -= 1
            limit = max([owned[k][0] + HEARD_CHAR_SEC if k >= 0 else float("-inf")]
                        + [b for _, b in walls if b <= lo + FRAME_SEC])
            before = _reach_before(speech, lo, head * UNHEARD_CHAR_SEC, limit)
        if before is not None or after is not None:
            out[key] = (before, after)
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


def _voiced(speech, lo: float, hi: float) -> float:
    """lo〜hi 秒の中にある声の長さの合計。"""
    total = 0.0
    i = max(0, bisect.bisect_right(speech.onsets, lo) - 1)
    while i < len(speech.onsets) and speech.onsets[i] < hi:
        total += max(0.0, min(hi, speech.offsets[i]) - max(lo, speech.onsets[i]))
        i += 1
    return total


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
        if not walled and not cut_through_voice and \
                _voiced(speech, new_end, new_start) >= rules.get("unclaimed_voice_sec", float("inf")):
            prev[1] = max(prev[1], end)
            info["joined"] += 1
            info["voice_kept"] = info.get("voice_kept", 0) + 1
            continue
        new_start = max(new_start, new_end)
        info["extended_end"] += how_end == "moved"
        info["pulled_start"] += how_start == "moved"
        info["quiet"] += (how_end == "quiet") + (how_start == "quiet")
        prev[1] = new_end
        out.append([new_start, end])
    out[-1][1], _ = end_at(out[-1][1])
    return [(a, b) for a, b in out], info


# ------------------------------------------------------------------
# 映像の切り替わり（収録の継ぎ目）
# ------------------------------------------------------------------

def _shots_cache_path(path) -> Path:
    """素材の隣の映像の切り替わりの控え。鍵は素材の中身（`video_hash.material_cache`）。"""
    from subtitle_engine.video_hash import material_cache
    return material_cache(path, "_shots_", legacy_salt="scdet")


def _parse_scdet(text: str) -> list[tuple[float, float]]:
    """ffmpeg の scdet と metadata=print の出力から (切り替わりの最初のフレームの秒, 値)。

    時刻は settb=AVTB にした pts（マイクロ秒）から読む（pts_time は有効数字6桁に丸めて書かれる）。
    """
    shots: list[tuple[float, float]] = []
    pts = None
    for line in text.splitlines():
        if line.startswith("frame:"):
            pts = next((int(w[4:]) for w in line.split() if w.startswith("pts:") and w[4:].lstrip("-").isdigit()),
                       None)
        elif line.startswith("lavfi.scd.score=") and pts is not None:
            shots.append((round(pts / 1_000_000, 6), float(line.split("=", 1)[1])))
            pts = None
    return shots


def read_shots(path) -> list[tuple[float, float]] | None:
    """素材の映像が切り替わる所。[(切り替わりの最初のフレームの秒, scdet の値)]（ffmpeg・ローカル）。

    素材と同じフォルダにキャッシュする（43分の素材で約2分かかる）。値は SHOT_SCAN_FLOOR 以上を残す。
    読めなければ None（映り込みは切らない）。
    """
    try:
        if not path or not Path(path).is_file() or Path(path).stat().st_size == 0:
            return None
        cache = _shots_cache_path(path)
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("version") == SHOTS_CACHE_VERSION and data.get("floor") == SHOT_SCAN_FLOOR:
                return [(float(t), float(s)) for t, s in data["shots"]]
        logger.info(f"🎞️ 映像の切り替わりを調べています（初回のみ）: {Path(path).name}")
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-i", str(path), "-an", "-sn", "-dn", "-vf",
             f"settb=AVTB,scdet=threshold={SHOT_SCAN_FLOOR}:sc_pass=1,metadata=print:file=-",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=3600)
        if proc.returncode != 0:
            logger.warning(f"映像の切り替わりを読めないので、映り込みは切りません: {proc.stderr[-300:]}")
            return None
        shots = _parse_scdet(proc.stdout)
        cache.write_text(json.dumps({"version": SHOTS_CACHE_VERSION, "floor": SHOT_SCAN_FLOOR,
                                     "shots": shots}), encoding="utf-8")
        return shots
    except Exception as e:  # 映像が読めなくても切る（映り込みは切らない）
        logger.warning(f"映像の切り替わりを読めないので、映り込みは切りません: {e}")
        return None


def read_rates(path) -> tuple[Fraction | None, int | None]:
    """素材の映像のフレームレートと音声のサンプリングレート（ffprobe・ローカル）。読めない方は None。"""
    try:
        if not path or not Path(path).is_file() or Path(path).stat().st_size == 0:
            return None, None
        proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                               "stream=codec_type,r_frame_rate,avg_frame_rate,sample_rate", "-of", "json",
                               str(path)], capture_output=True, text=True, timeout=60)
        streams = json.loads(proc.stdout or "{}").get("streams", [])
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        logger.warning(f"素材のフレームレートを読めないので、区間をフレームに揃えません: {e}")
        return None, None
    rate = sample_rate = None
    for stream in streams:
        if stream.get("codec_type") == "video" and rate is None:
            for key in ("r_frame_rate", "avg_frame_rate"):
                try:
                    value = Fraction(stream.get(key) or "")
                except (ValueError, ZeroDivisionError):
                    continue
                if FRAME_RATE_RANGE[0] <= value <= FRAME_RATE_RANGE[1]:
                    rate = value
                    break
        elif stream.get("codec_type") == "audio" and sample_rate is None:
            try:
                sample_rate = int(stream.get("sample_rate") or 0) or None
            except ValueError:
                pass
    return rate, sample_rate


def on_frames(ranges, rate: Fraction) -> list[tuple[float, float]]:
    """区間の端を、一番近い映像のフレームの境目に置く。境目で触れ合った区間はつなぎ、1フレームに
    満たない区間は捨てる。

    切り替わりのフレームの手前 `SHOT_EDGE_SEC` に置いた端（`trim_flashes`）は、切り替わりのフレームの
    境目に寄るので、前の収録のフレームは入らない。端は最大で半フレーム動くので、字幕を割り当てる前に
    `fit_spans` で発話の区間を収める。
    """
    slots: list[list[int]] = []
    for a, b in sorted(ranges):
        first, end = round(a * rate), round(b * rate)
        if end <= first:
            continue
        if slots and first <= slots[-1][1]:
            slots[-1][1] = max(slots[-1][1], end)
        else:
            slots.append([first, end])
    return [(float(first / rate), float(end / rate)) for first, end in slots]


def _has_words(audio: SourceAudio, lo: float, hi: float) -> bool:
    """lo〜hi 秒に言葉があるか。音声認識の字（字の立ち上がりから HEARD_CHAR_SEC）で見る。
    認識が無ければ音量で見た声で見る。"""
    if audio.heard:
        k = bisect.bisect_right(audio.heard, lo - HEARD_CHAR_SEC)
        return k < len(audio.heard) and audio.heard[k] < hi
    i = bisect.bisect_left(audio.speech.onsets, hi) - 1
    return i >= 0 and audio.speech.offsets[i] > lo


def trim_flashes(ranges, cuts, audio: SourceAudio, min_sec: float) -> tuple[list, dict]:
    """区間の端の、映像の切り替わりの向こうが少しだけ映る所を切り落とす。

    区間が切り替わり（cuts: 切り替わりの最初のフレームの秒）の min_sec 秒より短い手前から始まると、
    前の映像（前の収録の終わり）が一瞬映る。素材の 37分48秒の継ぎ目の 0.41 秒手前から残していて、
    左にいた美麗さんが画面から消えた所が出ていた（2026-10-17 ユーザー指摘）。そこに言葉が無ければ
    区間を切り替わりから始める。終わりも同じ（切り替わりの後が min_sec 秒より短ければ、切り替わりで
    終える）。言葉があるときは言葉を切らないので残す。
    返り値は (区間, {"trimmed": [(元の端, 新しい端)], "kept": [(切り替わりの秒, 映る秒数)]})。
    """
    found: dict = {"trimmed": [], "kept": []}
    out = []
    cuts = sorted(cuts)
    for a, b in ranges:
        inside = [s for s in cuts if a + FRAME_SEC < s < b - FRAME_SEC]
        if inside and inside[0] - a < min_sec:
            s = inside[0]
            if _has_words(audio, a, s):
                found["kept"].append((s, round(s - a, 3)))
            else:
                found["trimmed"].append((a, s - SHOT_EDGE_SEC))
                a = s - SHOT_EDGE_SEC
        inside = [s for s in inside if s > a + SHOT_EDGE_SEC]
        if inside and b - inside[-1] < min_sec:
            s = inside[-1]
            if _has_words(audio, s, b):
                found["kept"].append((s, round(b - s, 3)))
            else:
                found["trimmed"].append((b, s - SHOT_EDGE_SEC))
                b = s - SHOT_EDGE_SEC
        out.append((a, b))
    return out, found


def fit_spans(segments, ranges, overhang: float = 0.5) -> int:
    """残す区間に収まらない発話の区間を、一番重なる区間の中に縮める（その場で書き換える）。

    字幕は、発話の区間（sourceStart/sourceEnd）が残す区間の中にあるとき、その区間に割り当てる
    （`smart_cut_engine.retime_segments`。終わりは overhang 秒まではみ出してよい）。映り込みを
    切り落とすと区間が発話の区間より短くなり、そのままでは字幕が落ちる。行の表示の時刻
    （start/end）も新しい発話の区間の中に入れる。返り値は直した行の数。
    """
    fixed = 0
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        a, b = _span(seg)
        if not ranges or any(lo <= a and b <= hi + overhang for lo, hi in ranges):
            continue
        lo, hi = max(ranges, key=lambda r: min(b, r[1]) - max(a, r[0]))
        if min(b, hi) <= max(a, lo):
            continue
        new_a, new_b = max(a, lo), min(b, hi)
        seg["sourceStart"], seg["sourceEnd"] = new_a, new_b
        start, end = seg.get("start"), seg.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            # はみ出した側だけを詰める。行がまるごと外にあれば、長さを保って中へ入れる
            length = max(float(end) - float(start), 0.0)
            start, end = min(max(float(start), new_a), new_b), min(float(end), new_b)
            if end <= start:
                start, end = max(new_a, min(start, new_b - length)), min(start + length, new_b)
            seg["start"], seg["end"] = start, end
        fixed += 1
    return fixed


def plan(segments, source_path=None, *, keep_all: bool = False,
         rules: dict | None = None, exclude=(), cuts=(), keep=()) -> tuple[list[tuple[float, float]], dict]:
    """残す区間（素材の秒）と、決め方の記録を返す。

    keep_all: 中身（発話）を全部残すとき True。冒頭（最初の質問の文の前まで）とだれも話さない
    場面は切らず、声の中でも切らない。中身を選んで削るときは False（冒頭も選ばれない発話があり、
    つなぐとその声が字幕無しで入る。選ばなかった発話の所も長いすき間になる。長く続く声は一番
    静かな所で切る）。
    exclude: 外した発話（収録の段取りの声）。字幕か区間（素材の秒）で渡す。前後の区間を
    延ばしても入れない。
    素材の音声認識が読めれば、発話の言葉が聞こえた所まで区間を広げ（`heard_spans`）、
    聞けなかった言葉の声まで広げ（`unheard_reach`）、認識が続けて聞いた字も声とみなす
    （`_speech_end`・`_speech_start`）。
    映像の切り替わりが読めれば、区間の端の短い映り込みを切り落とす（`trim_flashes`）。区間が発話の
    区間より短くなることがあるので、字幕を割り当てる前に `fit_spans` で発話の区間を収める。
    映像のフレームレートが読めれば、区間の端をフレームの境目に置く（`on_frames`）。
    cuts・keep: 人が指示した、映像ごと切る区間と、字幕なしで残す区間（素材の秒・`human_cuts`）。
    最後に keep を足し、cuts を除く。
    """
    rules = rules or cut_rules()
    info: dict = {}
    exclude = list(exclude)
    tokens = read_heard(source_path)
    dropped = [x for x in exclude if not _is_span(x)]
    marks, length = heard_marks(list(segments) + dropped, tokens) if tokens else ({}, {})
    heard = _spans_of(marks)
    walls, widen = _walls_and_widening(segments, exclude, heard)
    if widen:
        info["heard_widened"] = sum(1 for span, w in widen.items() if _widened(span, widen) != span)
    audio = read_audio(source_path)
    if audio is not None and tokens:
        audio.heard = sorted(float(t) for _, t in tokens)
    if audio is not None and marks:
        kept = {_span(s) for s in segments}
        reached = 0
        for key, (before, after) in unheard_reach(marks, length, audio, walls).items():
            if key not in kept:
                continue
            lo, hi = widen.get(key, key)
            widen[key] = (min(lo, before) if before is not None else lo,
                          max(hi, after) if after is not None else hi)
            reached += _widened(key, widen) != _widened(key, {key: (lo, hi)})
        if reached:
            info["unheard_widened"] = reached
    ranges = merge_ranges(segments, rules["min_cut_sec"], widen)
    if keep_all and rules["keep_opening"]:
        until = opening_end(segments, rules["opening_max_sec"])
        if until is not None:
            ranges = join_opening(ranges, until, walls)
            info["opening_until"] = until
    if keep_all and rules.get("keep_scenes"):
        spans = [_widened(_span(s), widen) for s in segments] + walls
        scenes = find_scenes(spans, rules.get("scene_min_sec", DEFAULT_CUT_RULES["scene_min_sec"]))
        if scenes:
            ranges = join_scenes(ranges, scenes, rules["min_cut_sec"], rules["pad_before_sec"])
            info["scenes"] = scenes
    snapped, moved = snap_to_pauses(ranges, audio, rules,
                                    cut_through_voice=not keep_all, walls=walls)
    info.update(moved)
    shots = read_shots(source_path) if audio is not None else None
    if shots:
        changes = [t for t, score in shots if score >= SHOT_CHANGE_SCORE]
        snapped, flashes = trim_flashes(snapped, changes, audio,
                                        rules.get("min_shot_sec", DEFAULT_CUT_RULES["min_shot_sec"]))
        info["shot_changes"] = len(changes)
        if flashes["trimmed"]:
            info["flashes_trimmed"] = flashes["trimmed"]
        if flashes["kept"]:
            info["flashes_kept"] = flashes["kept"]
    if keep or cuts:
        snapped = subtract_spans(add_spans(snapped, keep), cuts)
        info["human_cuts"] = len(list(cuts))
    rate, _ = read_rates(source_path)
    if rate is not None:
        snapped = on_frames(snapped, rate)
    return snapped, info
