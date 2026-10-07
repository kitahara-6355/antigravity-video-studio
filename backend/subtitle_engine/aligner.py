"""字幕の文字を、音声認識（ローカル）の文字ごとの時刻に合わせる（強制アライメント）。

2026-10-06 ユーザー指摘「28〜40秒の声と字幕が合っていない」で作った。
Gemini の文字起こしは発話ごとの粗い時刻しか返さない（1発話が 12 秒あることも）。
1発話を何枚かの字幕に分けると、間の字幕の時刻は推定になり、28〜40秒では
最大 3 秒ずれていた。音の大きさ（間）だけでは、どの文字がいつ話されたかは分からない。

そこで日本語の音声認識モデル（ReazonSpeech の zipformer・sherpa-onnx・CPU・無料）で
**文字ごとの時刻**を取り、字幕の文字列と突き合わせて、字幕の出だし・終わりを決める。
文字は Gemini（校閲後）のものを使い、時刻だけを音声認識から借りる。

- 素材 1 本につき 1 回だけ認識し、結果を素材の隣にキャッシュする（43 分で約 10 分）
- モデルが無い・ライブラリが無いときは何もしない（従来の推定のまま）
- モデルは `python -m backend.subtitle_engine.aligner --setup` で取得する
  （GitHub の sherpa-onnx の配布物。約 700MB を落とし、使う int8 だけ残す）
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import subprocess
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_NAME = "sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
             f"{MODEL_NAME}.tar.bz2")
MODEL_FILES = {
    "encoder": "encoder-epoch-99-avg-1.int8.onnx",
    "decoder": "decoder-epoch-99-avg-1.onnx",
    "joiner": "joiner-epoch-99-avg-1.int8.onnx",
    "tokens": "tokens.txt",
}
CACHE_VERSION = 1
SAMPLE_RATE = 16000
# 認識に渡す1回の長さの上限。長くすると認識が落ちる（2026-10-06 実測: 20秒だと
# 20 秒ぶんの発話から十数文字しか出ないことがある。8 秒なら取りこぼさない）
CHUNK_MAX_SEC = 8.0
# これより短い間はつないで1回で認識する
CHUNK_MAX_GAP_SEC = 0.4
# 声の前後に付ける余白
CHUNK_PAD_SEC = 0.2
# 字幕1枚の推定時刻の前後、この範囲の認識結果から探す
SEARCH_BEFORE_SEC = 5.0
SEARCH_AFTER_SEC = 5.0
# 認識で拾えなかった端の文字は、1文字この秒数として外挿する
CHAR_SEC = 0.13
# 字幕の文字のうち、これだけ認識と一致すれば時刻を採る
MIN_MATCH_RATIO = 0.35
# 1文字だけの一致（「の」「は」）は数えない。続けてこれだけ一致した所だけ使う
MIN_BLOCK = 2
MIN_HITS = 3
# ひと続きに突き合った文字でも、認識の時刻がこれ以上離れていたらそこで切る。
# 突き合わせは一致を前後に伸ばすので、間の向こうの1文字がくっつく（20分08秒の
# 「なるべくね」の「な」が 2.3 秒前の「しれない」の「な」になった・2026-10-06 実測）
MAX_CHAR_GAP_SEC = 1.0
# 1枚の字幕の中で、時刻の離れた塊のうちこれより小さいもの（はぐれた 1〜2 文字）は使わない。
# 25分44秒で「偉そう」の「う」とはぐれた「書」が「もうこう書き直して」に突き合い、
# 字幕が 3.5 秒早く出て前の2枚と順番まで入れ替わった（2026-10-06 実測）
MIN_CLUSTER = 3
# 字幕の頭の小さな塊（MIN_CLUSTER 文字未満）が、残りの字からこれ以上離れて聞こえたら、隣の発話の
# 字かもしれない。同じ言葉を続けて言うと、認識は2つを1つにまとめる（2分32秒の「デビュー」・
# 「デ」「ビ」「ュー」が 0.8・0.9 秒ずつ離れた。1つの語の中の字は 0.6 秒も離れない・2026-10-07 実測）
STRAY_HEAD_GAP_SEC = 0.6
# 合った字幕どうしの継ぎ目で、聞こえなかった字を話す時間がこれ以上足りなければ、合わせ方を疑う
JOINT_TOLERANCE_SEC = 0.3
# 認識の時刻は、声の立ち上がり（音の大きさ）より約 0.2 秒早い。2026-10-06 実測:
# 0.11→0.37、10.25→10.44、28.17→28.47、35.10→35.30、39.60→39.80 秒（5 か所とも 0.19〜0.30）
LAG_SEC = 0.2
# 人が話せる速さの上限（字/秒）。43 分の素材で合った字幕の速さは中央 5.1・99% 点 9.8・
# 最大 10.9 字/秒（2026-10-07 実測）
MAX_CPS = 12.0
# 合った字幕どうしの間に、合わなかった字幕がこの秒数を超えてはみ出すなら、どちらかの合わせ方が誤り。
# 相づち（「はい」「うん」）は相手の話に重なるので、1 秒前後のはみ出しはふつうに起きる
# （同じ素材で 17 か所・最大 1.3 秒。誤って合わせた最後の字幕は 4.7 秒）
MAX_OVERRUN_SEC = 2.0

_DIGITS = str.maketrans("0123456789", "〇一二三四五六七八九")


def model_dir() -> Path:
    env = os.environ.get("AVS_ALIGN_MODEL_DIR")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "avs" / "models" / MODEL_NAME


def available() -> bool:
    """ライブラリとモデルが揃っているか。"""
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    d = model_dir()
    return all((d / f).is_file() for f in MODEL_FILES.values())


def setup(force: bool = False) -> Path:
    """モデルを取得する（GitHub の配布物）。使わない fp32 の重みは消す。"""
    d = model_dir()
    if available() and not force:
        return d
    d.parent.mkdir(parents=True, exist_ok=True)
    archive = d.parent / f"{MODEL_NAME}.tar.bz2"
    subprocess.run(["curl", "-sSL", "-o", str(archive), MODEL_URL], check=True, timeout=3600)
    subprocess.run(["tar", "xjf", str(archive), "-C", str(d.parent)], check=True, timeout=3600)
    archive.unlink(missing_ok=True)
    for f in ("encoder-epoch-99-avg-1.onnx", "joiner-epoch-99-avg-1.onnx"):
        (d / f).unlink(missing_ok=True)
    return d


_recognizer = None


def _get_recognizer():
    global _recognizer
    if _recognizer is None:
        import sherpa_onnx
        d = model_dir()
        _recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(d / MODEL_FILES["encoder"]), decoder=str(d / MODEL_FILES["decoder"]),
            joiner=str(d / MODEL_FILES["joiner"]), tokens=str(d / MODEL_FILES["tokens"]),
            num_threads=max(1, min(8, (os.cpu_count() or 2))), decoding_method="greedy_search")
    return _recognizer


def _read_pcm(media: str):
    import numpy as np
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-i", str(media), "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"], capture_output=True, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(f"音声の読み出しに失敗: {proc.stderr[-300:]!r}")
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def chunk_bounds(onsets: list[float], offsets: list[float], duration: float,
                 max_sec: float = CHUNK_MAX_SEC, max_gap: float = CHUNK_MAX_GAP_SEC,
                 pad: float = CHUNK_PAD_SEC) -> list[tuple[float, float]]:
    """認識に渡す区間。声のかたまりごとに切り、間は渡さない。

    声の切れ目をまたぐのは `max_gap` 未満の間だけ。1区間は `max_sec` まで。
    """
    bounds: list[tuple[float, float]] = []
    cur: list[float] | None = None
    for on, off in zip(onsets, offsets):
        if cur is None:
            cur = [on, off]
        elif on - cur[1] <= max_gap and off - cur[0] <= max_sec:
            cur[1] = off
        else:
            bounds.append(cur)
            cur = [on, off]
        while cur[1] - cur[0] > max_sec:  # 間の無い長い声は max_sec で割る
            bounds.append([cur[0], cur[0] + max_sec])
            cur[0] += max_sec
    if cur is not None:
        bounds.append(cur)
    return [(max(0.0, a - pad), min(duration, b + pad)) for a, b in bounds if b > a]


def recognize(media: str) -> list[tuple[str, float]]:
    """素材全体を認識し、(文字, 時刻) の列を返す。"""
    from subtitle_engine import sync
    pcm = _read_pcm(media)
    duration = len(pcm) / SAMPLE_RATE
    levels = sync.frame_levels_db((pcm * 32768).astype("int16"), SAMPLE_RATE)
    sp = sync.speech_map_from_levels(levels)
    rec = _get_recognizer()
    out: list[tuple[str, float]] = []
    for a, b in chunk_bounds(sp.onsets, sp.offsets, duration):
        st = rec.create_stream()
        st.accept_waveform(SAMPLE_RATE, pcm[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)])
        rec.decode_stream(st)
        r = st.result
        for tok, ts in zip(r.tokens, r.timestamps):
            tok = tok.strip()
            if not tok or tok.startswith("<"):
                continue
            for k, ch in enumerate(tok):  # 複数文字のトークンは同じ時刻に並べる
                out.append((ch, round(a + float(ts) + k * 0.01, 3)))
    return out


def _cache_path(media: str) -> Path:
    p = Path(media)
    st = p.stat()
    key = hashlib.sha1(f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}|{MODEL_NAME}".encode()).hexdigest()[:8]
    return p.with_name(f"_align_rz_{key}.json")


def tokens_for(media: str) -> list[tuple[str, float]] | None:
    """素材の認識結果（キャッシュがあれば読む）。使えなければ None。"""
    try:
        cache = _cache_path(media)
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("version") == CACHE_VERSION:
                return _lagged(data["tokens"])
        if not available():
            return None
        logger.info(f"🎙️ 字幕の時刻合わせ用に音声認識しています（初回のみ）: {Path(media).name}")
        tokens = recognize(media)
        cache.write_text(json.dumps({"version": CACHE_VERSION, "model": MODEL_NAME,
                                     "tokens": tokens}, ensure_ascii=False), encoding="utf-8")
        return _lagged(tokens)
    except Exception as e:  # 認識できなくても字幕は出す
        logger.warning(f"音声認識による時刻合わせをスキップ: {e}")
        return None


def _lagged(tokens) -> list[tuple[str, float]]:
    """キャッシュは認識の時刻のまま持ち、使うときに声の立ち上がりへずらす。"""
    return [(c, round(float(t) + LAG_SEC, 3)) for c, t in tokens]


# 校閲の直しを裁くとき、行の前後これだけの認識結果を聞く
REFEREE_PAD_SEC = 1.0
# 直した文の文字が、認識の文字にこれだけ含まれ、元の文より REFEREE_MARGIN 以上多ければ採る
REFEREE_MIN = 0.6
REFEREE_MARGIN = 0.2


def _heard_ratio(text: str, heard: str) -> float:
    """text の文字のうち、認識の文字に順に見つかる割合。"""
    if not text or not heard:
        return 0.0
    sm = difflib.SequenceMatcher(None, text, heard, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / len(text)


TRIM_CONTEXT = 4  # 足された字の前後で、認識と照らし合わせる文字数
# 置き換えを戻すのは、元の語がこれだけの長さ（そろえた文字数）からにする。
# 1文字の置き換え（助詞の「が」→「は」）は認識で決め切れない
SWAP_MIN_CHARS = 2
# 置き換えの前後に付けて認識と照らし合わせる文字数と、照らし合わせる長さの下限
SWAP_CONTEXT = 1
SWAP_MIN_PROBE = 3


def _is_kanji(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff" or ch in "々〇"


def _is_kana(ch: str) -> bool:
    return "\u3041" <= ch <= "\u30ff"


def _keeps_the_sound(old: str, new: str) -> bool:
    """音を変えない（かもしれない）置き換え。認識では裁かない（`_norm_text` 済みの文字で見る）。

    - 同じ長さの漢字どうし（「読」→「呼」「会」→「回」「始」→「初」）は同音の直しかもしれない。
      認識も漢字を選ぶので、同じ誤りを聞くことがある
    - かなを漢字にする（「たんじゅん」→「単純」「みれ」→「美麗」）のは変換の直し
    """
    if len(old) == len(new) and all(map(_is_kanji, old + new)):
        return True
    return all(map(_is_kana, old)) and any(map(_is_kanji, new))


def _heard_in(heard: str, left: str, word: str, right: str) -> bool:
    """word を前後の1文字と合わせて、認識の文字の中に聞いたか。"""
    probes = [p for p in (left + word, word + right) if len(p) >= SWAP_MIN_PROBE]
    return any(p in heard for p in probes)


def drop_unheard_edits(original: str, corrected: str, heard: str, keep=()) -> str:
    """校閲の直しのうち、音声認識と食い違うものを戻す。heard は `_norm_text` 済みの認識の文字。

    - 足し: 認識が「足さない形」で聞いているものを戻す（「最初に書に」→「最初にな書に」）
    - 置き換え: 認識が元の語をそのまま聞いていて、直した語を聞いていなければ戻す
      （「私が手がけた仕事」→「私がつなげた仕事」・29分00秒、「第1回め」→「初回め」・37分16秒）。
      音を変えないかもしれない直し（同音の漢字・かなを漢字に）と、辞書どおりの直し（keep の
      (誤, 正) のうち、元の文に「誤」があり、直した所が「正」に掛かるもの）は戻さない
    - 削除（フィラー）は触らない。認識が前後を聞き取れていない所も触らない
    """
    if not heard or not corrected:
        return corrected
    base = "".join(ch for ch in original or "" if ch not in " 　")
    sm = difflib.SequenceMatcher(None, base, corrected, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "insert":
            added = _norm_text(corrected[j1:j2])
            left = _norm_text(corrected[:j1])[-TRIM_CONTEXT:]
            right = _norm_text(corrected[j2:])[:TRIM_CONTEXT]
            if (added and len(left) + len(right) >= TRIM_CONTEXT
                    and left + right in heard and left + added + right not in heard):
                continue
        elif op == "replace" and _contradicted(base, corrected, i1, i2, j1, j2, heard, keep):
            out.append(base[i1:i2])
            continue
        out.append(corrected[j1:j2])
    return "".join(out)


def _contradicted(base, corrected, i1, i2, j1, j2, heard, keep) -> bool:
    """置き換え base[i1:i2] → corrected[j1:j2] を、認識が打ち消しているか。"""
    old, new = _norm_text(base[i1:i2]), _norm_text(corrected[j1:j2])
    if len(old) < SWAP_MIN_CHARS or not new or old == new or _keeps_the_sound(old, new):
        return False
    for wrong, term in keep or ():
        # 辞書どおりの直しだけ。辞書の語（「初回」）を作っただけの直し（「第1回」→「初回」）は裁く
        if not wrong or not term or wrong not in base:
            continue
        k = corrected.find(term)
        while k != -1:
            if k < j2 and j1 < k + len(term):  # 直した所が辞書の語に掛かる
                return False
            k = corrected.find(term, k + 1)
    left = _norm_text(corrected[:j1])[-SWAP_CONTEXT:]
    right = _norm_text(corrected[j2:])[:SWAP_CONTEXT]
    return _heard_in(heard, left, old, right) and not _heard_in(heard, left, new, right)


def _dictionary_terms() -> tuple:
    """辞書の (誤, 正) の組（校閲が辞書どおりに直した語は、認識が違って聞いても戻さない）。"""
    try:
        from proper_noun_dict import proper_noun_dict
        return tuple(sorted({(str(e.get("incorrect") or ""), str(e.get("correct") or ""))
                             for e in proper_noun_dict.get_all_entries()
                             if e.get("incorrect") and e.get("correct")}))
    except Exception:  # 辞書が読めなくても裁く
        return ()


class Referee:
    """校閲の直しを音声認識の文字で確かめる。segment の start/end は素材の時間軸。"""

    def __init__(self, tokens: list[tuple[str, float]], keep=None):
        self._tokens = tokens
        self._times = [t for _, t in tokens]
        self._keep = keep

    def heard(self, segment: dict) -> str:
        """その行の時刻の前後で認識した文字（`_norm_text` 済み）。"""
        import bisect

        try:
            a = float(segment["start"]) - REFEREE_PAD_SEC
            b = float(segment["end"]) + REFEREE_PAD_SEC
        except (KeyError, TypeError, ValueError):
            return ""
        lo, hi = bisect.bisect_left(self._times, a), bisect.bisect_right(self._times, b)
        return _norm_text("".join(c for c, _ in self._tokens[lo:hi]))

    def __call__(self, segment: dict, corrected: str) -> bool:
        """元の文から離れた直し（「歌詞織」→「菓子折り」）を採ってよいか。

        番号ずれか作り話かもしれないので校閲側で捨てている。認識の文字に、直した文の方が
        はっきり近いときだけ採る。
        """
        heard = self.heard(segment)
        before = _heard_ratio(_norm_text(segment.get("text")), heard)
        after = _heard_ratio(_norm_text(corrected), heard)
        return after >= REFEREE_MIN and after >= before + REFEREE_MARGIN

    def trim(self, segment: dict, corrected: str) -> str:
        """直しのうち、声と食い違うもの（誰も言っていない足し・言った語と違う語への置き換え）を戻す。"""
        if self._keep is None:
            self._keep = _dictionary_terms()
        return drop_unheard_edits(str(segment.get("text") or ""), corrected,
                                  self.heard(segment), self._keep)


def referee_from_tokens(tokens: list[tuple[str, float]], keep=None) -> Referee:
    """校閲の直しを音声認識で確かめる `Referee` を作る（judge(segment, corrected) -> bool）。

    keep は戻さない直し（辞書の (誤, 正) の組）。None なら辞書から読む。
    """
    return Referee(tokens, keep)


def referee_for(media: str):
    """素材の認識結果から裁く関数を作る。認識が使えなければ None（裁かない）。"""
    tokens = tokens_for(media) if media else None
    return referee_from_tokens(tokens) if tokens else None


def to_output(tokens: list[tuple[str, float]], ranges) -> list[tuple[str, float]]:
    """素材の時間軸の認識結果を、カット後（残した区間を順に並べた）時間軸に写す。"""
    out, offset = [], 0.0
    ranges = [(float(a), float(b)) for a, b in ranges or []]
    i = 0
    for s0, s1 in ranges:
        while i < len(tokens) and tokens[i][1] < s0:
            i += 1
        j = i
        while j < len(tokens) and tokens[j][1] < s1:
            out.append((tokens[j][0], round(offset + tokens[j][1] - s0, 3)))
            j += 1
        offset += s1 - s0
    return out


def norm_char(ch: str) -> str:
    """突き合わせ用に文字をそろえる（全角半角・数字・カタカナ→ひらがな・記号は消す）。"""
    s = unicodedata.normalize("NFKC", ch).translate(_DIGITS)
    out = []
    for c in s:
        cat = unicodedata.category(c)
        if cat[0] in "PZSC":  # 句読点・空白・記号・制御
            continue
        if "ァ" <= c <= "ヶ":
            c = chr(ord(c) - 0x60)
        out.append(c)
    return "".join(out)


def _norm_text(text: str) -> str:
    return "".join(norm_char(c) for c in str(text or ""))


def align_captions(captions: list[dict], tokens: list[tuple[str, float]]) -> int:
    """字幕（start/end は推定）を、認識結果の文字の時刻に合わせる。合わせた枚数を返す。

    **全体をいちどに**突き合わせる（字幕の全文 対 認識の全文）。1枚ずつ近くを探すと、
    認識が落とした所で別の場所に食いついて大きく外れる（2026-10-06 実測で「こんにちは」が
    4 秒ずれた）。順序を保った対応だけを採るので、落とした所は合わせずに残す。

    合わせた字幕には `_asr` を立てる。
    """
    if not tokens or not captions:
        return 0
    # 認識側: 1文字ずつに開く
    rec_chars, rec_times = [], []
    for ch, t in tokens:
        for c in norm_char(ch):
            rec_chars.append(c)
            rec_times.append(float(t))
    # 字幕側: 1文字ずつに開き、どの字幕の何文字目かを覚える
    cap_chars, owner, offset_in = [], [], []
    for i, cap in enumerate(captions):
        text = _norm_text(cap.get("text"))
        for k, c in enumerate(text):
            cap_chars.append(c)
            owner.append(i)
            offset_in.append(k)
    if not cap_chars or not rec_chars:
        return 0
    sm = difflib.SequenceMatcher(None, cap_chars, rec_chars, autojunk=False)
    hits: dict[int, list[tuple[int, float]]] = {}
    for blk in sm.get_matching_blocks():
        first = 0
        for d in range(1, blk.size + 1):
            if d < blk.size and rec_times[blk.b + d] - rec_times[blk.b + d - 1] <= MAX_CHAR_GAP_SEC:
                continue
            if d - first >= MIN_BLOCK:
                for e in range(first, d):
                    ci = blk.a + e
                    hits.setdefault(owner[ci], []).append((offset_in[ci], rec_times[blk.b + e]))
            first = d
    aligned = 0
    prev_last = None  # 前の字幕で最後に突き合った文字の時刻
    for i, cap in enumerate(captions):
        pairs = _main_pairs(hits.get(i) or [])
        if not pairs:
            continue
        # 時刻を採るには足りなくても、声の一部は聞こえている（早口の「いらっしゃいまして」の「いら」）
        cap["_asr_heard"] = len(pairs)
        length = len(_norm_text(cap.get("text")))
        if len(pairs) < max(MIN_HITS, MIN_MATCH_RATIO * length):
            continue
        (c0, t0), (c1, t1) = pairs[0], pairs[-1]
        start = t0 - c0 * CHAR_SEC
        # 外挿した頭が、前の字幕の言葉より前に戻らない（順番が入れ替わる）
        if prev_last is not None and start < prev_last + 0.05:
            start = min(t0, prev_last + 0.05)
        end = t1 + (length - 1 - c1) * CHAR_SEC + CHAR_SEC
        if end <= start:
            continue
        prev_last = t1
        cap["_est_start"], cap["_est_end"] = float(cap["start"]), float(cap["end"])
        cap["start"], cap["end"] = round(start, 3), round(end, 3)
        cap["_asr"] = True
        # 最初に拾えた文字の時刻。頭の文字を拾えなかったときは start は外挿になる
        cap["_asr_first"] = round(t0, 3)
        # 拾えた文字ごとの (字幕の何文字目か, 時刻)。短すぎる字幕の切れ目を動かすときに使う
        cap["_asr_marks"] = [(c, round(t, 3)) for c, t in pairs]
        aligned += 1
    _drop_stray_heads(captions)
    return aligned


def _drop_stray_heads(captions: list[dict]) -> int:
    """合った字幕の頭の、はぐれた小さな塊の時刻を捨てる（前の字幕を話す時間が残らないときだけ）。

    実例（2分32秒・28回目）: ゲストの「…僕のデビューなんですよ」に聞き手が「デビューですか？」と
    返す所で、認識は2つの「デビュー」を1つにまとめ、頭の「デ」「ビ」をゲスト側の時刻で出した。
    聞き手の字幕が 1.5 秒早く出て、ゲストの2行（28字）が 1.7 秒で消えた。

    前の合った字幕で最後に聞こえた字から、この字幕で最初に聞こえた字までに、聞こえなかった字
    （前の字幕の尻・間の字幕・この字幕の頭）を MAX_CPS で話せないなら、この字幕の頭の小さな塊
    （残りから STRAY_HEAD_GAP_SEC より離れたもの）を捨て、残りの最初の字から出だしを外挿し直す。
    話し始めの1文字は認識の時刻が早めに出ることが多いので（28回目で90枚）、前の字幕を話す時間が
    あるときは動かさない。捨て直した枚数を返す。
    """
    idx = [i for i, c in enumerate(captions) if c.get("_asr")]
    dropped = 0
    for a, b in zip(idx, idx[1:]):
        p, c = captions[a], captions[b]
        before, marks = p.get("_asr_marks") or [], list(c.get("_asr_marks") or [])
        if not before or not marks:
            continue
        p_last_c, p_last_t = before[-1]
        unheard = (len(_norm_text(p.get("text"))) - 1 - p_last_c
                   + sum(len(_norm_text(x.get("text"))) for x in captions[a + 1:b]))
        if (unheard + marks[0][0]) / MAX_CPS - (marks[0][1] - p_last_t) <= JOINT_TOLERANCE_SEC:
            continue
        cut = 0
        while True:
            k = cut + 1
            while k < len(marks) and marks[k][1] - marks[k - 1][1] <= STRAY_HEAD_GAP_SEC:
                k += 1
            if k - cut >= MIN_CLUSTER or len(marks) - k < MIN_HITS:
                break
            cut = k
        if not cut:
            continue
        marks = marks[cut:]
        c0, t0 = marks[0]
        start = t0 - c0 * CHAR_SEC
        if start < p_last_t + 0.05:  # 前の字幕の言葉より前に戻らない
            start = min(t0, p_last_t + 0.05)
        c["start"], c["_asr_first"], c["_asr_marks"] = round(start, 3), round(t0, 3), marks
        dropped += 1
    return dropped


def _main_pairs(pairs: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """1枚の字幕の突き合った文字を、時刻の離れ目で塊に分け、はぐれた小さな塊を除く。

    MIN_CLUSTER 文字以上の塊だけを残す（無ければいちばん大きい塊）。字幕の中の本当の間
    （言葉の塊どうし）は残る。端のはぐれた 1〜2 文字だけが落ちる。
    """
    if not pairs:
        return []
    groups = [[pairs[0]]]
    for p, q in zip(pairs, pairs[1:]):
        if q[1] - p[1] > MAX_CHAR_GAP_SEC:
            groups.append([q])
        else:
            groups[-1].append(q)
    if len(groups) == 1:
        return pairs
    big = [g for g in groups if len(g) >= MIN_CLUSTER]
    if not big:
        big = [max(groups, key=len)]
    first, last = groups.index(big[0]), groups.index(big[-1])
    return [p for g in groups[first:last + 1] for p in g]


def _chars(c: dict) -> int:
    return max(1, len(_norm_text(c.get("text"))))


def _spread(run: list[dict], t0: float, t1: float) -> None:
    """字幕を t0〜t1 に文字数で配る。"""
    total = sum(_chars(c) for c in run)
    acc = 0.0
    for c in run:
        c["start"] = round(t0 + (t1 - t0) * acc, 3)
        acc += _chars(c) / total
        c["end"] = round(t0 + (t1 - t0) * acc, 3)
        c["_asr_interp"] = True


def release_implausible(captions: list[dict], end: float | None = None) -> int:
    """合った字幕どうしの間に、合わなかった字幕が話せる速さで収まらなければ、どちらかの合わせ方を外す。

    同じ言葉が何度も出る所（締めの「ありがとうございました」が4回）では、認識が拾った1回を
    別の回の字幕に合わせてしまう（全体の突き合わせは、同じ長さの一致なら字幕の早い方を採る）。
    すると間の字幕を話す時間が残らない（2026-10-07: 動画の最後で「はい 今日はありがとう
    ございました」が 7 秒遅れ、後ろの3枚は動画の外に出て消えた）。

    外すのは、反対側の隣の合った字幕とずれ方（推定からの移動）が大きく違う方。動画の頭（0 秒）と
    終わり（end）は動かない杭として扱う。外した字幕は推定の時刻に戻し、後で
    `interpolate_unaligned` が前後の間に配り直す。外した枚数を返す。
    """
    released = 0
    while True:
        idx = [i for i, c in enumerate(captions) if c.get("_asr")]
        if not idx:
            return released
        worst = None
        for a, b in [(None, idx[0]), *zip(idx, idx[1:]), (idx[-1], None)]:
            run = captions[(0 if a is None else a + 1):(len(captions) if b is None else b)]
            if not run or (b is None and end is None):
                continue
            t0 = 0.0 if a is None else float(captions[a]["end"])
            t1 = float(end) if b is None else float(captions[b]["start"])
            overrun = sum(_chars(c) for c in run) / MAX_CPS - (t1 - t0)
            if overrun > MAX_OVERRUN_SEC and (worst is None or overrun > worst[0]):
                worst = (overrun, a, b)
        if worst is None:
            return released
        _, a, b = worst
        victim = b if a is None else a if b is None else _out_of_step(captions, idx, a, b)
        logger.info(f"話す時間が残らない合わせ方を外しました: {captions[victim].get('text')!r} "
                    f"（はみ出し {worst[0]:.1f} 秒）")
        _release(captions[victim])
        released += 1


def _out_of_step(captions: list[dict], idx: list[int], a: int, b: int) -> int:
    """隣り合う合った字幕 a・b のうち、反対側の隣とずれ方が大きく違う方。"""
    def shift(i):
        c = captions[i]
        return float(c["start"]) - float(c.get("_est_start", c["start"]))
    k = idx.index(a)
    before = shift(idx[k - 1]) if k > 0 else shift(b)
    after = shift(idx[k + 2]) if k + 2 < len(idx) else shift(a)
    return a if abs(shift(a) - before) >= abs(shift(b) - after) else b


def _release(c: dict) -> None:
    c["start"] = round(float(c.get("_est_start", c["start"])), 3)
    c["end"] = round(float(c.get("_est_end", c["end"])), 3)
    for k in ("_asr", "_asr_first", "_asr_marks", "_asr_heard"):
        c.pop(k, None)
    c["_asr_released"] = True


def interpolate_unaligned(captions: list[dict], end: float | None = None) -> int:
    """合わせられなかった字幕を、前後の「合った字幕」の間に文字数で配る。

    認識が落とした所をそのままにすると、推定の時刻（ずれたまま）が残って、
    合った字幕とぶつかる。合った字幕を杭にして、その間を配り直す。
    端（最初の杭より前・最後の杭より後ろ）は、杭と同じだけずらす。ずらすと動画の外
    （0 秒より前・end より後ろ）にはみ出すなら、杭と動画の端の間に配る。
    """
    idx = [i for i, c in enumerate(captions) if c.get("_asr")]
    if not idx:
        return 0
    moved = 0

    for a, b in zip(idx, idx[1:]):
        run = captions[a + 1:b]
        if not run:
            continue
        t0, t1 = float(captions[a]["end"]), float(captions[b]["start"])
        # 狭くても順番どおりに置く（推定の時刻のまま残すと、並べ直しで順番が入れ替わる）。
        # 出る時間が足りない字幕は、後で隣とまとめる。前後が重なっているときは次の字幕の出だしに
        # 置く（前の終わりに置くと次の字幕より後ろになる・15分26秒の「ファンが」）
        _spread(run, min(t0, t1), t1)
        moved += len(run)
    for head, side, anchor in ((True, captions[:idx[0]], idx[0]), (False, captions[idx[-1] + 1:], idx[-1])):
        if not side:
            continue
        est = float(captions[anchor].get("_est_start", captions[anchor]["start"]))
        delta = float(captions[anchor]["start"]) - est
        changed = abs(delta) >= 0.05
        if changed:
            for c in side:
                c["start"] = round(float(c["start"]) + delta, 3)
                c["end"] = round(float(c["end"]) + delta, 3)
                c["_asr_interp"] = True
        if head:
            lo, hi, spills = 0.0, float(captions[anchor]["start"]), float(side[0]["start"]) < 0.0
        else:
            lo, hi = float(captions[anchor]["end"]), end
            spills = end is not None and float(side[-1]["end"]) > end
        if spills and hi > lo:
            _spread(side, lo, hi)
            changed = True
        if changed:
            moved += len(side)
    return moved


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="字幕の時刻合わせ用の音声認識モデル")
    ap.add_argument("--setup", action="store_true", help="モデルを取得する")
    ap.add_argument("--recognize", metavar="MEDIA", help="素材を認識してキャッシュする")
    args = ap.parse_args()
    if args.setup:
        print(setup())
    if args.recognize:
        toks = tokens_for(args.recognize)
        print(f"{len(toks or [])} 文字")
