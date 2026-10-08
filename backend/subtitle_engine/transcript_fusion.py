"""2回の文字起こしを、手元の音声認識に聞き比べて1本にする（2026-10-06）。

同じ素材を区切りを変えて起こし直すと、Gemini の聞き違いが毎回別の所に出た
（26回目の冒頭で「書家の北原」が「諸岡の北原」に、「書に出会った」が「よそに出会った」に。
25回目には無かった）。温度 0 でも区切りが変われば渡す音声が変わるので、どちらの回の字が
正しいかは運になる。

そこで区切りの位置をずらしてもう1回起こし（`gemini_transcriber.transcribe(first_chunk_sec=…)`）、
食い違った所だけを手元の音声認識（ReazonSpeech・`aligner`）に聞いて 2対1 で決める。
複数の認識結果を突き合わせて1本にする定石（NIST の ROVER・1997）と同じ考え。

- 1回目を骨組みにする。行の分け方と時刻は1回目のまま、字だけを直す
- 食い違いごとに、2回目の字（前後の字を2字まで付けて3字以上）が認識に聞こえていて、
  1回目の字が聞こえていないときだけ2回目の字にする
- 2回目だけが足した字は、全部は聞こえなくても、前の字と続けて認識に聞こえる頭の部分は足す
  （「出会いな」→「出会いなんです」。2回目は「なんですて」・認識は「なんですね」）
- 決めない所: 1回目の字を2字以上消す（認識は早口・言い直し・重なりを落とすので、聞こえない
  ことは弱い証拠）、言いよどみ（後で外す）、数字（認識は漢数字で書く）、近くに確かな
  手がかり（2回とも同じで認識とも3字以上続けて合う字）が無い所

43分の素材（25回目と26回目の起こし）で: 食い違い 1,042 か所のうち 118 か所を2回目の字にした。
冒頭の「諸岡→書家」「お人々→人々」「第一任者→第一人者」「久喜田→久木田」「よそに→書に」
「出会いな→出会いなんですね」が直り、名前・用語の聞き違いは 13→10 件。

試して捨てた案（2026-10-06）:
- 行のまとまりごとに、認識に近い方を丸ごと採る → まとまりの中に良い所と悪い所が混ざる
- 区間の中で認識に一番近い組み合わせを採る → 認識が落とした所で短い方をひいきし、
  「書ききれない」が「り切れない」に崩れた
- 校閲（AI）に認識の聞き取りを行ごとに添える → 直りと崩れが半々（「主宰→主催」など）
"""
from __future__ import annotations

import bisect
import difflib

from subtitle_engine.aligner import norm_char

# 手がかりの杭: 2回とも同じ字で、認識とこの字数以上続けて合う所
ANCHOR_BLOCK = 3
# 食い違いの前後に付けて認識の中を探す字数（の上限）と、探す長さの下限
CONTEXT = 2
MIN_PROBE = 3
# 杭の外側にも、これだけ認識の字を見る
WINDOW_PAD = 3
# 杭どうしがこれより離れている所は決めない（認識が長く落とした所）
MAX_SPAN = 80
# 1回目の字を消してよい字数
MAX_DROP = 1
# 2回目が足した字の頭だけを採るとき（`_heard_head`）: 採る字数の下限と、探す長さの下限
HEAD_MIN = 2
HEAD_MIN_PROBE = 4
# 決めない語（後で外す言いよどみ・相づち。どちらで書いても字幕に出ない）
FILLERS = frozenset({
    "あ", "あの", "え", "えっと", "ま", "まあ", "うん", "うう", "ね", "ねえ", "なんか", "その",
    "はい", "ええ", "へえ", "おお", "ああ", "ん", "う", "うんうん", "はいはい",
})
# 数字（norm_char が算用数字を漢数字にそろえる。認識は漢数字で書くので桁が食い違う）
_NUMERALS = frozenset("〇一二三四五六七八九十百千万億")
# 集計に載せる直しの例の数
MAX_EXAMPLES = 50


def _flatten(segments: list[dict]) -> list[tuple[str, int, int]]:
    """行を1字ずつに開く: (そろえた字, 行の番号, 元の文の何字目)。"""
    out = []
    for si, seg in enumerate(segments):
        for ci, ch in enumerate(str(seg.get("text") or "")):
            for c in norm_char(ch):
                out.append((c, si, ci))
    return out


def _matches(x: str, y: str, min_block: int) -> dict[int, int]:
    """x の位置 → y の位置（順序を保った対応のうち、min_block 字以上続く所）。"""
    m: dict[int, int] = {}
    for blk in difflib.SequenceMatcher(None, x, y, autojunk=False).get_matching_blocks():
        if blk.size >= min_block:
            for k in range(blk.size):
                m[blk.a + k] = blk.b + k
    return m


def _heard(window: str, left: str, word: str, right: str) -> bool:
    """word（消す側なら空）を前後の字と合わせて、認識の中に聞いたか。"""
    if not word:
        probes = [left[-CONTEXT:] + right[:CONTEXT]]
    elif left:
        # 前の字は必ず付ける（語だけで探すと、近くの別の所の同じ字に当たる:「どうぞ→どうですね」）
        probes = [left[-k:] + word + right[:m] for k in range(1, CONTEXT + 1) for m in range(CONTEXT + 1)]
    else:  # 素材の頭
        probes = [word + right[:m] for m in range(1, CONTEXT + 1)]
    return any(len(p) >= MIN_PROBE and p in window for p in probes)


def _heard_head(window: str, left: str, word: str) -> int:
    """2回目が足した字 word のうち、前の字と続けて認識に聞こえる頭の字数（無ければ 0）。

    word 全部は聞こえなくても、頭の部分は2回目と認識が同じ字を聞いている（2対1）ことがある
    （1分39秒: 1回目「出会いな」・2回目「出会いなんですて」・認識「出会いなんですね」）。
    """
    for n in range(len(word) - 1, HEAD_MIN - 1, -1):
        head = word[:n]
        if _guarded("", head):
            continue
        if any(len(p) >= HEAD_MIN_PROBE and p in window
               for p in (left[-k:] + head for k in range(1, CONTEXT + 1))):
            return n
    return 0


def _guarded(a: str, b: str) -> bool:
    return (len(a) - len(b) > MAX_DROP or a.strip("ー") in FILLERS or b.strip("ー") in FILLERS
            or any(ch in _NUMERALS for ch in a + b))


def fuse(primary: list[dict], secondary: list[dict],
         tokens: list[tuple[str, float]] | None) -> tuple[list[dict], dict]:
    """primary の字を、secondary と認識（tokens: (字, 秒) の並び）の 2対1 で直す。

    返り値は (行, 集計)。行は primary の写し（渡した行は書き換えない）。
    集計は {"differences", "adopted", "examples": [{"start", "before", "after"}]}。
    """
    out = [dict(s) for s in primary]
    stats = {"differences": 0, "adopted": 0, "examples": []}
    if not tokens or not primary or not secondary:
        return out, stats
    fa, fb = _flatten(primary), _flatten(secondary)
    xa, xb = "".join(c for c, _, _ in fa), "".join(c for c, _, _ in fb)
    heard = "".join(c for ch, _ in tokens for c in norm_char(ch))
    a2r = _matches(xa, heard, ANCHOR_BLOCK)
    ops = difflib.SequenceMatcher(None, xa, xb, autojunk=False).get_opcodes()
    a2b = {i1 + k: j1 + k for op, i1, i2, j1, j2 in ops if op == "equal" for k in range(i2 - i1)}
    anchors = sorted(k for k in a2b if k in a2r)

    chosen = []
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            continue
        stats["differences"] += 1
        a, b = xa[i1:i2], xb[j1:j2]
        p = bisect.bisect_left(anchors, i1) - 1
        q = bisect.bisect_left(anchors, i2)
        if (p < 0 and q >= len(anchors)) or _guarded(a, b):
            continue
        # 杭の間の認識を見る。頭・お尻の杭が無い所（素材の最初と最後）は、反対側の杭から同じ字数ぶん
        left_k = anchors[p] if p >= 0 else -1
        right_k = anchors[q] if q < len(anchors) else len(xa)
        if right_k - left_k > MAX_SPAN:
            continue
        lo = a2r[left_k] if p >= 0 else a2r[right_k] - right_k
        hi = a2r[right_k] if q < len(anchors) else a2r[left_k] + (right_k - left_k)
        window = heard[max(0, lo - WINDOW_PAD):hi + WINDOW_PAD + 1]
        left, right = xa[max(0, i1 - CONTEXT):i1], xa[i2:i2 + CONTEXT]
        if _heard(window, left, b, right) and not _heard(window, left, a, right):
            chosen.append((i1, i2, j1, j2))
        elif not a and left and not _heard(window, left, a, right):
            # 2回目が足した字は、認識にも聞こえる頭の部分だけ足す
            n = _heard_head(window, left, b)
            if n:
                chosen.append((i1, i2, j1, j1 + n))

    texts = [list(str(s.get("text") or "")) for s in primary]
    btexts = [str(s.get("text") or "") for s in secondary]
    examples = []
    # 後ろから置き換える（前の字の位置がずれない）
    for i1, i2, j1, j2 in sorted(chosen, reverse=True):
        if j2 > j1:
            if fb[j1][1] != fb[j2 - 1][1]:  # 2回目の行をまたぐ字は使わない
                continue
            new = btexts[fb[j1][1]][fb[j1][2]:fb[j2 - 1][2] + 1]
        else:
            new = ""
        if i2 > i1:
            (_, row, c0), (_, row_end, c1) = fa[i1], fa[i2 - 1]
            if row != row_end:
                continue
            before = "".join(texts[row][c0:c1 + 1])
            texts[row][c0:c1 + 1] = list(new)
        else:  # 足す: 前の字の直後（行末の句点より前）に
            _, row, c0 = fa[i1 - 1]
            before = ""
            texts[row][c0 + 1:c0 + 1] = list(new)
        stats["adopted"] += 1
        examples.append({"start": primary[row].get("start"), "before": before, "after": new})
    for seg, chars in zip(out, texts):
        seg["text"] = "".join(chars)
    stats["examples"] = examples[::-1][:MAX_EXAMPLES]
    return out, stats
