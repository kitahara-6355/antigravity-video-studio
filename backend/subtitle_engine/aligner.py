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
# 認識の時刻は、声の立ち上がり（音の大きさ）より約 0.2 秒早い。2026-10-06 実測:
# 0.11→0.37、10.25→10.44、28.17→28.47、35.10→35.30、39.60→39.80 秒（5 か所とも 0.19〜0.30）
LAG_SEC = 0.2

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


def referee_from_tokens(tokens: list[tuple[str, float]]):
    """校閲の直しを音声認識で裁く関数 judge(segment, corrected) -> bool を作る。

    元の文から離れた直し（「歌詞織」→「菓子折り」）は、番号ずれか作り話かもしれないので
    校閲側で捨てている。認識の文字（その行の時刻の前後）に、直した文の方がはっきり近いときだけ採る。
    segment の start/end は素材の時間軸。
    """
    import bisect

    times = [t for _, t in tokens]

    def judge(segment: dict, corrected: str) -> bool:
        try:
            a = float(segment["start"]) - REFEREE_PAD_SEC
            b = float(segment["end"]) + REFEREE_PAD_SEC
        except (KeyError, TypeError, ValueError):
            return False
        lo, hi = bisect.bisect_left(times, a), bisect.bisect_right(times, b)
        heard = _norm_text("".join(c for c, _ in tokens[lo:hi]))
        before = _heard_ratio(_norm_text(segment.get("text")), heard)
        after = _heard_ratio(_norm_text(corrected), heard)
        return after >= REFEREE_MIN and after >= before + REFEREE_MARGIN

    return judge


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
    for i, cap in enumerate(captions):
        pairs = hits.get(i)
        if not pairs:
            continue
        length = len(_norm_text(cap.get("text")))
        if len(pairs) < max(MIN_HITS, MIN_MATCH_RATIO * length):
            continue
        (c0, t0), (c1, t1) = pairs[0], pairs[-1]
        start = t0 - c0 * CHAR_SEC
        end = t1 + (length - 1 - c1) * CHAR_SEC + CHAR_SEC
        if end <= start:
            continue
        cap["_est_start"] = float(cap["start"])
        cap["start"], cap["end"] = round(start, 3), round(end, 3)
        cap["_asr"] = True
        # 最初に拾えた文字の時刻。頭の文字を拾えなかったときは start は外挿になる
        cap["_asr_first"] = round(t0, 3)
        aligned += 1
    return aligned


def interpolate_unaligned(captions: list[dict]) -> int:
    """合わせられなかった字幕を、前後の「合った字幕」の間に文字数で配る。

    認識が落とした所をそのままにすると、推定の時刻（ずれたまま）が残って、
    合った字幕とぶつかる。合った字幕を杭にして、その間を配り直す。
    端（最初の杭より前・最後の杭より後ろ）は、杭と同じだけずらす。
    """
    idx = [i for i, c in enumerate(captions) if c.get("_asr")]
    if not idx:
        return 0
    moved = 0

    def chars(c):
        return max(1, len(_norm_text(c.get("text"))))

    for a, b in zip(idx, idx[1:]):
        run = captions[a + 1:b]
        if not run:
            continue
        t0, t1 = float(captions[a]["end"]), float(captions[b]["start"])
        if t1 - t0 < 0.2 * len(run):  # 詰められないほど狭いときは触らない
            continue
        total = sum(chars(c) for c in run)
        acc = 0.0
        for c in run:
            w = chars(c) / total
            c["start"] = round(t0 + (t1 - t0) * acc, 3)
            acc += w
            c["end"] = round(t0 + (t1 - t0) * acc, 3)
            c["_asr_interp"] = True
            moved += 1
    for side, anchor in ((captions[:idx[0]], idx[0]), (captions[idx[-1] + 1:], idx[-1])):
        if not side:
            continue
        est = float(captions[anchor].get("_est_start", captions[anchor]["start"]))
        delta = float(captions[anchor]["start"]) - est
        if abs(delta) < 0.05:
            continue
        for c in side:
            c["start"] = round(float(c["start"]) + delta, 3)
            c["end"] = round(float(c["end"]) + delta, 3)
            c["_asr_interp"] = True
            moved += 1
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
