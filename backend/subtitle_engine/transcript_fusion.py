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
- 1回目の字を2〜3字消すのは、2回目にも無く、認識が前後の字を、その字数を言う間もなく
  （毎秒 MAX_CPS 字で言っても足りない間で）続けて聞いたときだけ（2分49秒「しようと
  そういう」→「しようという」。認識は「と」と「い」を 0.2 秒で聞いた）
- 1回目の行をまたぐ食い違いは、言いよどみだけの行の分を外して決める（2分46秒の「ないよね。
  ／ううん。」と2回目の「ないので。」。まとめて1つの食い違いになり、行をまたぐので決めていなかった）
- 1回目のチャンクの区切りで割れて2行にまたがった語は、割れた字の多い方の行に置いて決める
  （2026-10-15・10分16秒: 1回目「当時でん｜チーフの人たち」・2回目と認識「当時電通の人たち」。
  2回目の区切りは1回目から離してあるので、1回目の区切りで割れた語を2回目は丸ごと聞く）
- 食い違いと句読点で隔てたすぐ外側の言いよどみ（2字以上）は、前後の字から外しても探す（認識は
  言いよどみを書かない。素材の 42分05秒（43回目の 41分30秒）: 1回目「機械をねあの、足て」・2回目「絶やして」・認識
  「機会をね絶やして」。全編で変わるのはここと「なんだろう→何だろう」の2か所）
- 決めない所: 1回目の字を4字以上消す・前後に間がある所で2字以上消す（認識は早口・言い直し・
  重なりを落とすので、聞こえないことは弱い証拠。漢字は2音に数えた字数でも消える分を見る）、言いよどみ（後で外す）、数字（認識は
  漢数字で書く）、近くに確かな手がかり（2回とも同じで認識とも3字以上続けて合う字）が無い所

43分の素材（25回目と26回目の起こし）で: 食い違い 1,042 か所のうち 118 か所を2回目の字にした。
冒頭の「諸岡→書家」「お人々→人々」「第一任者→第一人者」「久喜田→久木田」「よそに→書に」
「出会いな→出会いなんですね」が直り、名前・用語の聞き違いは 13→10 件。
2〜3字を消す決め方と言いよどみだけの行を外す決め方を足したとき（2026-10-13）は、同じ素材の
いまの起こし（食い違い 837 か所）で直す所が 101→105 か所（2分46秒「ないので」・2分49秒
「という」・13分04秒「じゃない、コロナで」・19分04秒「ってのは」）。

試して捨てた案（2026-10-06）:
- 行のまとまりごとに、認識に近い方を丸ごと採る → まとまりの中に良い所と悪い所が混ざる
- 区間の中で認識に一番近い組み合わせを採る → 認識が落とした所で短い方をひいきし、
  「書ききれない」が「り切れない」に崩れた
- 校閲（AI）に認識の聞き取りを行ごとに添える → 直りと崩れが半々（「主宰→主催」など）
- 消す側を、前後の字を片側に寄せた4字（1字＋3字など）でも探す（2026-10-14）→ 2分59秒「そう何にか」
  →「何か」は直るが（認識は「そう」を「感じで」と聞いた）、「でもしょうがない→もしょうがない」
  「あまり→あま」が崩れた。このとき「高評価→高評」「奈良筆でも→奈良筆も」も崩れたと数えたが、
  後で3回目と古い起こしを並べると直す側が正しかった（審査の「講評」、「豊橋筆も、奈良筆も」）。
  1回目を正解とみなして数えていた。2対1 で決めるには根拠が弱いので、3回目の候補の見つけ方に回した

3回目の起こし（2026-10-14）: 2回の起こしが同じ所で聞き違えると、突き合わせても直らない
（3分03秒「普通泣いて帰ったら」が、1回目「普通だったら」・2回目「普通泣いてがったら」）。
区切りが変われば聞き違える所も変わる（区切りの違う古い2回の起こしは、どちらも正しかった）。
そこで、認識が疑わしいと示す所（`look_spots`）だけを、その所が真ん中に来るように区切って
もう1回起こし（`gemini_transcriber.transcribe_windows`）、3回目が認識に沿う字を書いたときだけ
直す（`judge`・`settle`）。上の「片側4字」の案は、ここでは3回目が決めるための候補の見つけ方として使う。
3回目が前後の字を書かない・どちらでもない字を書いた所は決まらないので、区間の前後の余白を広げて
読み直す（`gemini_transcriber.LOOK_PADS`）。同じモデルでも区間の長さで聞き取りが変わる（3分03秒を
21・40・60・120 秒の区間で起こすと「普通ナイデがったら」「嫌だったら」「泣いて帰ったら」「ないてかったら」。
正しかった古い2回の起こしも同じ gemini-3.5-flash-lite）。
43分の素材で候補 12 か所（1回目と2回目の呼び出しは 104 回ずつ）。余白 8 秒の 10 区間で「奈良筆でも→
奈良筆も」「書道で→書で」「高評価→高評」「最後の最後に→最後の最後」の4か所が直り、決まらなかった
7か所を余白 18 秒の6区間・28 秒の5区間で読み直すと「何にか→何か」（2分59秒）・「普通だったら→
普通泣いて帰ったら」（3分03秒）・「明け暮れてたんですけれど→ですけど」の3か所が直った（呼び出しは
計 21 回・すべて gemini-3.5-flash-lite）。4分46秒「やっぱり」は余白 8 秒の読みが2回の起こしと同じ字を
書いたのでそのまま。残る4か所は3回読んでも決まらない。

2回とも同じ字を書き、認識だけが別の字を聞いた所（2026-10-14・`look_spots` の (c)）: 2回の起こしが
同じ聞き違いをすると、(a)(b) の見つけ方では拾えない（43回目の締め 42分03秒: 2回とも「先生、あの、
去年初めての」・認識「今日ね初めての」）。認識が正しいとは限らない（31秒「久木田博信」を認識は
「浩信」と書く）ので、3回目が認識と同じ字を書いたときだけ直す（2対2 だが、2回の起こしは同じモデルで
似た区間を聞いているので、区間を変えた3回目と別のモデルの認識がそろう方を採る）。かなと漢字の書き分け・
2字以下のかなどうし（助詞）・辞書の語は見ない。43分の素材で候補 22 か所（書き分けを除く前は 75 か所）。
44回目で直したのは3か所（「広報担当→広告担当」・「太文字→筆文字」・「え、古文字文化→え、筆文字文化」）、
13か所は3回目も2回と同じ字（42分03秒「去年」も）、6か所は決まらない。

2回が食い違い、どちらの字も認識に聞こえない所（`look_spots` の "neither"）: 突き合わせは1回目のままに
するので、1回目の聞き違いが残る（44回目の 9分18秒: 1回目「怒んないように」・2回目「怒れないように」・
認識「折れないように」、13分55秒: 1回目「今生田川で」・2回目「今バレたから」・認識「今治タオルとか」）。
"swap" と同じく、3回目が認識と同じ字を書いたときだけ直す（4つの読みのうち2つがそろい、残る2つは
それぞれ別の字）。3回目が2回目と同じ字を書いた所は決めない（認識はどの起こしとも食い違ったまま）。
43分の素材で候補 6 か所。行をまたぐ所（10分16秒: 1回目「当時でん｜チーフの人たち」・2回目「当時、デン｜
の人たち」・認識「当時電通の人たち」）は、ほかの候補と同じく直さない。

2回目の区切りを1回目から離す（2026-10-15・`gemini_transcriber.SECOND_PASS_GAP_SEC`）: 上の 10分16秒は
2回とも同じ所（624.54秒）で区切って「電通」を割っていた（9 分以降は区切りの8割が同じ所）。離した2回目は
「当時電通の人たち」と丸ごと聞き、突き合わせは区切りで割れた2行に直す（`_split_at_cut`）。

前の区切り方の2回目も聞き取りの1つとして使う（2026-10-15・`TranscribeWorker._second_pass`）: 2回目を
起こし直すと、前の2回目が正しかった所（締めの「絶やして」「増やしていく」・「豊橋筆」「書道家」）が
1回目の字に戻った。いまの2回目と突き合わせた後に、前の2回目とも同じ決め方で突き合わせる（44 か所を直し、
変わった 39 行のうち 36 行が認識に近づいた）。3回目の候補も起こしごとに探してまとめる。
"""
from __future__ import annotations

import bisect
import difflib
import re

from subtitle_engine.aligner import MAX_CPS, norm_char

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
# 認識が前後の字を言う間もなく続けて聞いていれば（`_no_time_for`）、ここまで消してよい
MAX_UNSAID_DROP = 3
# 2回目が足した字の頭だけを採るとき（`_heard_head`）: 採る字数の下限と、探す長さの下限
HEAD_MIN = 2
HEAD_MIN_PROBE = 4
# 決めない語（後で外す言いよどみ・相づち。どちらで書いても字幕に出ない）
FILLERS = frozenset({
    "あ", "あの", "え", "えっと", "ま", "まあ", "うん", "うう", "ね", "ねえ", "なんか", "その",
    "はい", "ええ", "へえ", "おお", "ああ", "ん", "う", "うんうん", "はいはい",
})
# 食い違いのすぐ外側にあれば外して前後の字を取る言いよどみ（2字以上。1字の「え」「う」は
# 「考え」「そう」の尻と見分けられない）と、そのために外側に余分に見る字数
_SKIPPABLE = sorted((w for w in FILLERS if len(w) >= 2), key=lambda w: (-len(w), w))
FILLER_SKIP = len(_SKIPPABLE[0])
# 数字（norm_char が算用数字を漢数字にそろえる。認識は漢数字で書くので桁が食い違う）
_NUMERALS = frozenset("〇一二三四五六七八九十百千万億")
# 集計に載せる直しの例の数
MAX_EXAMPLES = 50
# 行の頭の時刻がチャンクの区切りからこれ以内なら、区切りで始まる行とみなす
# （`gemini_transcriber.drop_boundary_echoes` と同じ幅）
CUT_SLACK_SEC = 0.3


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


def _breaks(flat: list[tuple[str, int, int]]) -> set[int]:
    """そろえた字の位置 k のうち、元の文で k-1 字目と k 字目の間に句読点・空白（そろえると消える字）か
    行の切れ目がある所。"""
    return {k for k in range(1, len(flat))
            if flat[k - 1][1] != flat[k][1] or flat[k][2] - flat[k - 1][2] > 1}


def _contexts(x: str, i1: int, i2: int, breaks: set[int]) -> list[tuple[str, str]]:
    """食い違い x[i1:i2] の前後の字（CONTEXT 字ずつ）。

    食い違いと句読点で隔てたすぐ外側に言いよどみの語があれば、それを外した前後の字も返す。認識は
    言いよどみを書かないので、前後の字に言いよどみが入ると、どちらの字も聞こえなくなる（42分05秒:
    1回目「機械をねあの、足て」・2回目「絶やして」・認識「機会をね絶やして」）。句読点で隔てていない
    語は外さない（「僕があの駄菓子屋」の「が」を、言いよどみの向こうの字だけで消してしまう）。
    """
    left, right = x[max(0, i1 - CONTEXT - FILLER_SKIP):i1], x[i2:i2 + CONTEXT + FILLER_SKIP]
    out = [(left[-CONTEXT:], right[:CONTEXT])]
    lw = next((w for w in _SKIPPABLE if left.endswith(w)), "") if i1 in breaks else ""
    rw = next((w for w in _SKIPPABLE if right.startswith(w)), "") if i2 in breaks else ""
    if lw or rw:
        out.append((left[:len(left) - len(lw)][-CONTEXT:], right[len(rw):][:CONTEXT]))
    return out


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


def _guarded(a: str, b: str, max_drop: int = MAX_DROP) -> bool:
    # 減る字数は、漢字を1字と数えた差と2音と数えた差の小さい方（漢字は1字で2音以上のことが多い。
    # 区切りで割れた「でんちーふ」を2回目が「電通」と書くと、字数では3字減るが音では1字）
    return (min(len(a) - len(b), _sounds(a) - _sounds(b)) > max_drop
            or a.strip("ー") in FILLERS or b.strip("ー") in FILLERS
            or any(ch in _NUMERALS for ch in a + b))


def _sounds(s: str) -> int:
    return len(s) + sum(1 for ch in s if _KANJI.fullmatch(ch))


def _no_time_for(heard: str, times: list[float], lo: int, hi: int, left: str, right: str, n: int) -> bool:
    """1回目だけにある n 字の前後の字（left・right）を、認識がその n 字を言う間もなく続けて聞いたか。

    n 字を言ったなら、前後の字の間は毎秒 MAX_CPS 字の早口でも (n + 1) / MAX_CPS 秒はあく。
    探すのは heard[lo:hi]（食い違いの両側の杭の間）。
    """
    probe = left[-CONTEXT:] + right[:CONTEXT]
    if len(probe) < MIN_PROBE or not right:
        return False
    k = heard.find(probe, lo, hi)
    if k < 0:
        return False
    j = k + len(left[-CONTEXT:]) - 1
    return times[j + 1] - times[j] < (n + 1) / MAX_CPS


def _only_fillers(s: str) -> bool:
    words = sorted(FILLERS, key=len, reverse=True)
    i, s = 0, s.replace("ー", "")
    while i < len(s):
        w = next((w for w in words if s.startswith(w, i)), None)
        if w is None:
            return False
        i += len(w)
    return bool(s)


def _drop_filler_rows(ops: list[tuple], fa: list[tuple[str, int, int]]) -> list[tuple]:
    """1回目の行をまたぐ食い違いから、言いよどみだけの行の分を外す（残りが1行に収まるときだけ）。

    相づちだけの行（「ううん。」）は2回目にも認識にも無いことが多く、隣の行の食い違いと1つに
    まとまる（2分46秒「ないよね。／ううん。」と2回目「ないので。」）。行をまたぐ食い違いは
    直せないので、そのままでは決めずに終わっていた。言いよどみは後で外すので、残しておく。
    """
    out = []
    for op, i1, i2, j1, j2 in ops:
        if op != "equal" and i2 > i1 and fa[i1][1] != fa[i2 - 1][1]:
            parts, k = [], i1
            while k < i2:
                e = k
                while e < i2 and fa[e][1] == fa[k][1]:
                    e += 1
                parts.append((k, e))
                k = e
            kept = [(p, q) for p, q in parts if not _only_fillers("".join(c for c, _, _ in fa[p:q]))]
            if len(kept) == 1:
                (i1, i2), = kept
                op = "replace" if j2 > j1 else "delete"
        out.append((op, i1, i2, j1, j2))
    return out


def fuse(primary: list[dict], secondary: list[dict],
         tokens: list[tuple[str, float]] | None,
         cuts: list[float] | tuple = ()) -> tuple[list[dict], dict]:
    """primary の字を、secondary と認識（tokens: (字, 秒) の並び）の 2対1 で直す。

    cuts は primary を起こしたときのチャンクの区切り（素材の秒）。区切りで割れて隣り合う2行に
    またがった語は、割れた字の多い方の行に直した字を置く（`_split_at_cut`）。ほかの行をまたぐ
    食い違いは決めない（どちらの行の字か分からない）。
    返り値は (行, 集計)。行は primary の写し（渡した行は書き換えない）。
    集計は {"differences", "adopted", "examples": [{"start", "before", "after"}]}。
    """
    out = [dict(s) for s in primary]
    stats = {"differences": 0, "adopted": 0, "examples": []}
    if not tokens or not primary or not secondary:
        return out, stats
    fa, fb = _flatten(primary), _flatten(secondary)
    xa, xb = "".join(c for c, _, _ in fa), "".join(c for c, _, _ in fb)
    rec = [(c, float(t)) for ch, t in tokens for c in norm_char(ch)]
    heard, times = "".join(c for c, _ in rec), [t for _, t in rec]
    a2r = _matches(xa, heard, ANCHOR_BLOCK)
    ops = difflib.SequenceMatcher(None, xa, xb, autojunk=False).get_opcodes()
    a2b = {i1 + k: j1 + k for op, i1, i2, j1, j2 in ops if op == "equal" for k in range(i2 - i1)}
    ops = _drop_filler_rows(ops, fa)
    anchors = sorted(k for k in a2b if k in a2r)
    breaks = _breaks(fa)

    chosen = []
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            continue
        stats["differences"] += 1
        a, b = xa[i1:i2], xb[j1:j2]
        p = bisect.bisect_left(anchors, i1) - 1
        q = bisect.bisect_left(anchors, i2)
        # 2回目に無い2〜3字は、認識の前後の字の間で決める（下）
        unsaid = not b and MAX_DROP < len(a) <= MAX_UNSAID_DROP
        if (p < 0 and q >= len(anchors)) or _guarded(a, b, MAX_UNSAID_DROP if unsaid else MAX_DROP):
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
        if unsaid:
            if (_no_time_for(heard, times, max(0, lo - WINDOW_PAD), hi + WINDOW_PAD + 1, left, right, len(a))
                    and not _heard(window, left, a, right)):
                chosen.append((i1, i2, j1, j2))
            continue
        ctxs = _contexts(xa, i1, i2, breaks)
        if (any(_heard(window, lc, b, rc) for lc, rc in ctxs)
                and not any(_heard(window, lc, a, rc) for lc, rc in ctxs)):
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
                split = _split_at_cut(fa, i1, i2, primary, texts, cuts)
                if split is None:
                    continue
                (a0, a1), (b0, b1), into = split
                before = "".join(texts[row][a0:a1 + 1] + texts[row_end][b0:b1 + 1])
                texts[row_end][b0:b1 + 1] = list(new) if into == row_end else []
                texts[row][a0:a1 + 1] = list(new) if into == row else []
                stats["adopted"] += 1
                examples.append({"start": primary[row].get("start"), "before": before, "after": new})
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


def _split_at_cut(fa: list[tuple[str, int, int]], i1: int, i2: int, primary: list[dict],
                  texts: list[list[str]],
                  cuts: list[float] | tuple) -> tuple[tuple[int, int], tuple[int, int], int] | None:
    """そろえた字の i1〜i2 が、チャンクの区切りで割れて隣り合う2行にまたがっていれば
    ((前の行の頭, 尻), (後ろの行の頭, 尻), 直した字を置く行)。そうでなければ None。

    区切りで割れた語は、前の行の尻と後ろの行の頭に分かれる（10分16秒: 区切り 624.54秒で
    「当時でん｜チーフの人たち」）。区切りは後ろの行の頭の時刻で見る（CUT_SLACK_SEC 秒まで）。
    直した字は割れた字の多い方の行に置き、もう片方の行に字が残らなくなるなら、その行に置く
    （どちらの行にも字が残らなければ None）。
    """
    row, row_end = fa[i1][1], fa[i2 - 1][1]
    if row_end != row + 1:
        return None
    try:
        at = float(primary[row_end].get("start"))
    except (TypeError, ValueError):
        return None
    if not any(abs(at - float(c)) < CUT_SLACK_SEC for c in cuts):
        return None
    head = [k for k in range(i1, i2) if fa[k][1] == row]
    tail = [k for k in range(i1, i2) if fa[k][1] == row_end]
    span = {row: (fa[head[0]][2], fa[head[-1]][2]), row_end: (fa[tail[0]][2], fa[tail[-1]][2])}

    def bare_without(r: int) -> bool:  # 割れた字を除くと、その行に字が残らない
        lo, hi = span[r]
        return not "".join(norm_char(ch) for ch in texts[r][:lo] + texts[r][hi + 1:])

    into, other = (row_end, row) if len(tail) >= len(head) else (row, row_end)
    if bare_without(other):
        into, other = other, into
        if bare_without(other):
            return None
    return span[row], span[row_end], into


# ─────────────────────────── 3回目の起こし ───────────────────────────

# (a) 突き合わせた後の文より、認識がこの字数以上多く聞いた所を「2回とも落とした」とみなす
LOOK_EXTRA = 3
# (a)(c) その食い違いの前後で、文と認識が続けて合う字数の下限（確かな所に挟まれていること）
LOOK_ANCHOR = 4
# (c) 認識だけが別の字を聞いた所の字数の上限（文と認識のどちらも）
SWAP_MAX = 8
# (c) かなと漢字の書き分け（norm_char でカタカナはひらがなにそろう）
_KANA = re.compile(r"[ぁ-ゖー]+")
_KANJI = re.compile(r"[一-鿿々〆]+")
# 候補の前後に付けて覚えておく字数。3回目の文の中でこの字を探し、間の字を比べる
SETTLE_CONTEXT = 3
# 3回目の文で前後の字を探すとき、間がこの字数より長ければ別の所とみなす（直す字数への上乗せ）
SETTLE_SLACK = 6
# 3回目の文のうち、候補の行の前後この秒数に起こされた行だけを見る
SETTLE_MARGIN_SEC = 5.0
# 行の頭・尻に置く3回目の字から外す句読点と空白
_EDGE_PUNCT = "、。，．,.!?！？ 　"


def _span(flat: list[tuple[str, int, int]], i1: int, i2: int) -> tuple[int, int, int] | None:
    """そろえた字の i1〜i2（前後の字 i1-1・i2 は含まない）の元の文の範囲: (行, 頭, 尻)。

    前の字のすぐ後ろから後ろの字の手前まで（間の句読点も含む）。前の字か後ろの字が隣の行に
    あれば、そちら側は間の字の端まで（行の頭の「で、」・4分46秒）。間の字が2つの行に
    またがる・足す所（間の字が無い）の前後が別の行なら None（直さない）。
    """
    if i1 <= 0 or i2 >= len(flat):
        return None
    inner = {flat[k][1] for k in range(i1, i2)}
    lrow, rrow = flat[i1 - 1][1], flat[i2][1]
    if not inner:
        return (lrow, flat[i1 - 1][2] + 1, flat[i2][2]) if lrow == rrow else None
    if len(inner) > 1:
        return None
    row = inner.pop()
    return (row, flat[i1 - 1][2] + 1 if lrow == row else flat[i1][2],
            flat[i2][2] if rrow == row else flat[i2 - 1][2] + 1)


def _local_window(a2r: dict[int, int], anchors: list[int], i1: int, i2: int, heard: str) -> str:
    """xa の i1〜i2 の食い違いの周りの認識（両側の杭の間＋余白）。杭が無ければ空。"""
    p = bisect.bisect_left(anchors, i1) - 1
    q = bisect.bisect_left(anchors, i2)
    if p < 0 or q >= len(anchors) or anchors[q] - anchors[p] > MAX_SPAN:
        return ""
    return heard[max(0, a2r[anchors[p]] - WINDOW_PAD):a2r[anchors[q]] + WINDOW_PAD + 1]


def _spelling_only(cur: str, want: str) -> bool:
    """かなと漢字の書き分け（「いただき」と「頂き」）か、2字以下のかなどうし（助詞の違い）だけか。"""
    kana, kanji = (_KANA.fullmatch(cur), _KANA.fullmatch(want)), (_KANJI.fullmatch(cur), _KANJI.fullmatch(want))
    return bool((kana[0] and kanji[1]) or (kanji[0] and kana[1])
                or (all(kana) and max(len(cur), len(want)) <= 2))


def _covered(x: str, words) -> set[int]:
    """x の中で words（そろえる前の語）のどれかが占める位置。"""
    out: set[int] = set()
    for w in {"".join(norm_char(c) for c in str(w)) for w in words}:
        k = x.find(w) if w else -1
        while k >= 0:
            out.update(range(k, k + len(w)))
            k = x.find(w, k + 1)
    return out


def look_spots(fused: list[dict], secondary: list[dict],
               tokens: list[tuple[str, float]] | None, protect=()) -> list[dict]:
    """3回目を起こしたい所。2回の突き合わせ（`fuse`）の後の行 fused で見る。

    (a) "omit": fused より認識が LOOK_EXTRA 字以上多く聞いた所。前後 LOOK_ANCHOR 字以上が
        fused と認識で続けて合う所に挟まれ、言いよどみ・数字・英字ではないこと
        （3分03秒: fused「普通だったら」・認識「普通泣いて帰ったら」）
    (b) "drop": 2回目が1字消し、認識にもその字が無いのに、前後2字ずつでは確かめられなかった所。
        前1字＋後ろ3字か前3字＋後ろ1字となら続けて聞こえていること
        （2分59秒: fused「そう何にか」・2回目「そう何か」・認識「感じで何か」）
    (c) "swap": 2回とも同じ字を書き、認識だけが別の字（SWAP_MAX 字まで）を聞いた所。挟まれ方と
        言いよどみ・数字・英字は (a) と同じ。かなと漢字の書き分けや2字以下のかなどうし（助詞）
        だけの違いと、辞書の語（protect。名前は認識が別の字を書きやすい）の中は見ない
        （42分03秒: 2回とも「先生、あの、去年初めての」・認識「今日ね初めての」）。
        2回が食い違い、突き合わせでどちらの字も認識に聞こえなかった所は "neither"（見る所は "swap"
        と同じ。9分18秒: 1回目「怒んないように」・2回目「怒れないように」・認識「折れないように」）

    返り値は {"kind", "row", "c0", "c1", "cur", "want", "left", "right"} の並び。
    row・c0・c1 は fused の行と、その文の直す範囲（`_span`）。cur・want・left・right は
    そろえた字（`norm_char`）で、いまの字・認識に沿う字（(b) は空）・前後の字。
    """
    if not tokens or not fused:
        return []
    ff = _flatten(fused)
    xf = "".join(c for c, _, _ in ff)
    rec = [(c, float(t)) for ch, t in tokens for c in norm_char(ch)]
    heard = "".join(c for c, _ in rec)
    spots: list[dict] = []
    taken: set[tuple[int, int, int]] = set()

    def add(kind: str, i1: int, i2: int, want: str) -> None:
        span = _span(ff, i1, i2)
        if span is None or span in taken:
            return
        taken.add(span)
        row, c0, c1 = span
        spots.append({"kind": kind, "row": row, "c0": c0, "c1": c1, "cur": xf[i1:i2], "want": want,
                      "left": xf[max(0, i1 - SETTLE_CONTEXT):i1], "right": xf[i2:i2 + SETTLE_CONTEXT]})

    # (a) 2回とも落とした所・(c) 認識だけが別の字を聞いた所（2回とも同じ字か、2回が食い違ったか）
    xs = "".join(c for c, _, _ in _flatten(secondary)) if secondary else ""
    same = {i1 + k for op, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, xf, xs, autojunk=False).get_opcodes()
            if op == "equal" for k in range(i2 - i1)}
    protected = _covered(xf, protect)
    ops = difflib.SequenceMatcher(None, xf, heard, autojunk=False).get_opcodes()
    for k in range(1, len(ops) - 1):
        op, i1, i2, j1, j2 = ops[k]
        # 食い違いの両隣は一致の塊（SequenceMatcher は食い違いを続けて出さない）
        if op == "equal" or min(ops[k - 1][2] - ops[k - 1][1], ops[k + 1][2] - ops[k + 1][1]) < LOOK_ANCHOR:
            continue
        cur, extra = xf[i1:i2], heard[j1:j2]
        if _only_fillers(extra) or any(ch in _NUMERALS or ch.isascii() for ch in cur + extra):
            continue
        if len(extra) - len(cur) >= LOOK_EXTRA:
            add("omit", i1, i2, extra)
        elif (op == "replace" and len(cur) <= SWAP_MAX and len(extra) <= SWAP_MAX
              and not _only_fillers(cur) and not _spelling_only(cur, extra)
              and not any(i in protected for i in range(i1, i2))):
            add("swap" if all(i in same for i in range(i1, i2)) else "neither", i1, i2, extra)

    # (b) 2回目が1字消し、認識が片側でだけ消した側に寄る所
    if secondary:
        a2r = _matches(xf, heard, ANCHOR_BLOCK)
        anchors = sorted(a2r)
        for op, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, xf, xs, autojunk=False).get_opcodes():
            if op != "delete" or i2 - i1 != 1:
                continue
            cur = xf[i1:i2]
            left, right = xf[max(0, i1 - SETTLE_CONTEXT):i1], xf[i2:i2 + SETTLE_CONTEXT]
            if (len(left) < SETTLE_CONTEXT or len(right) < SETTLE_CONTEXT or not cur.strip("ー")
                    or _guarded(cur, "")):
                continue
            window = _local_window(a2r, anchors, i1, i2, heard)
            if not window or _heard(window, left, cur, right):
                continue
            if any(p in window for p in (left[-1:] + right, left + right[:1])):
                add("drop", i1, i2, "")
    return sorted(spots, key=lambda s: (s["row"], s["c0"]))


def judge(fused: list[dict], third: list[dict], spot: dict) -> tuple[str, str]:
    """3回目の起こし third で、候補 spot（`look_spots`）の1か所を裁く。返り値は (裁き, 置く字)。

    3回目の文（候補の行の前後 SETTLE_MARGIN_SEC 秒に起こされた行）の中で候補の前後の字を探し、
    間の字を比べる。
    - "adopt": 3回目が認識に沿う字を書いた。(a) 間の字に認識が多く聞いた字（want）が入っていれば、
      その字と、その前後で2回の起こしも書いた字を置く（元の文の字と、間の句読点。2回とも行の頭に
      「で、」、3回目が「で、やっぱり」なら「で、」も残す）。3回目だけが足した字は置かない（3分03秒の
      3回目「普通に泣いて帰ったら」の「に」は、認識も2回の起こしも書いていない）。(b) 間に字が無ければ
      （3回目も消した: 2回目・3回目・認識の3つがそろう）、その字を消す。(c) 間の字が、いまの字の頭と
      尻の間を認識の字（want）に入れ替えた形なら、間の字を置く。いまの字を（入れ替えた字数より）
      2字以上減らす形は決めない（42分03秒: 3回目「先生、あの、今日ね、」は置き、「今日ね、」だけなら
      「先生、あの、」を落とすので置かない）。"neither" も (c) と同じ
    - "keep": 3回目も2回の起こしと同じ字（いまのまま。"neither" は1回目と同じ字）
    - "open": 前後の字が見つからない・どちらでもない字・置く所が2行にまたがる（決まらない）
    """
    row = fused[spot["row"]]
    lo = float(row.get("start") or 0) - SETTLE_MARGIN_SEC
    hi = float(row.get("end") or row.get("start") or 0) + SETTLE_MARGIN_SEC
    near = [s for s in sorted(third, key=lambda s: float(s.get("start") or 0))
            if float(s.get("end") or s.get("start") or 0) >= lo and float(s.get("start") or 0) <= hi]
    f3 = _flatten(near)
    x3 = "".join(c for c, _, _ in f3)
    left, right, cur, want = spot["left"], spot["right"], spot["cur"], spot["want"]
    limit = max(len(cur), len(want)) + SETTLE_SLACK
    p = x3.find(left)
    while p >= 0:
        a = p + len(left)
        q = x3.find(right, a, a + limit + len(right))
        if q >= 0:
            gap = x3[a:q]
            if gap == cur:
                return "keep", ""
            if spot["kind"] == "omit" and want in gap:
                k, rest = gap.find(want), len(gap) - gap.find(want) - len(want)
                pre = next(n for n in range(k, -1, -1) if gap[k - n:k] in cur)
                post = next(n for n in range(rest, -1, -1) if gap[k + len(want):k + len(want) + n] in cur)
                a, q = a + k - pre, a + k + len(want) + post
            elif spot["kind"] in ("swap", "neither") and want in gap:
                head, tail = gap[:gap.find(want)], gap[gap.find(want) + len(want):]
                if (not cur.startswith(head) or not cur.endswith(tail) or len(head) + len(tail) > len(cur)
                        or len(cur) - len(head) - len(tail) - len(want) > MAX_DROP):
                    return "open", ""
            elif spot["kind"] != "drop" or gap:
                return "open", ""
            span = _span(f3, a, q)
            if span is None:
                return "open", ""
            r3, d0, d1 = span
            return "adopt", str(near[r3].get("text") or "")[d0:d1]
        p = x3.find(left, p + 1)
    return "open", ""


def settle(fused: list[dict], spots: list[dict], verdicts: list[tuple[str, str]]) -> tuple[list[dict], dict]:
    """裁き verdicts（spots と同じ並び・`judge`）のうち "adopt" の字を fused に置く。返り値は (行, 集計)。

    時刻と行の分け方は変えない。集計は {"adopted", "kept", "open", "examples": [{"start", "before", "after"}]}。
    """
    out = [dict(s) for s in fused]
    stats: dict = {"adopted": 0, "kept": sum(v == "keep" for v, _ in verdicts),
                   "open": sum(v == "open" for v, _ in verdicts), "examples": []}
    edits = [(spot["row"], spot["c0"], spot["c1"], new)
             for spot, (verdict, new) in zip(spots, verdicts) if verdict == "adopt"]
    texts = [str(s.get("text") or "") for s in out]
    examples = []
    last: tuple[int, int] | None = None
    for row, c0, c1, new in sorted(edits, reverse=True):
        if last is not None and last[0] == row and c1 > last[1]:
            continue  # 後ろの直しと重なる（同じ所を2回直さない）
        # 行の頭・尻に置くときは、3回目の文の前の文・次の文との間の句読点を持ち込まない
        if c0 == 0:
            new = new.lstrip(_EDGE_PUNCT)
        if c1 >= len(texts[row]):
            new = new.rstrip(_EDGE_PUNCT)
        before = texts[row][c0:c1]
        texts[row] = texts[row][:c0] + new + texts[row][c1:]
        last = (row, c0)
        stats["adopted"] += 1
        examples.append({"start": out[row].get("start"), "before": before, "after": new})
    for seg, text in zip(out, texts):
        seg["text"] = text
    stats["examples"] = examples[::-1][:MAX_EXAMPLES]
    return out, stats
