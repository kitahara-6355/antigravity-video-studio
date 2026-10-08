"""Gemini 音声入力による文字起こし（R2.5-C4 の主経路）。

2026-09-26 のユーザー決定で、文字起こしの**主は Gemini 音声入力、従は Whisper**。
クラウドのコンテナは GPU が無く、Whisper のモデル置き場（Hugging Face）にも
出られないので、クラウドだけで回すにはこちらが要る。

出力は Whisper の経路（`whisper_subprocess.py`）と同じ JSONL の行
`{start, end, text, sourceStart, sourceEnd, words}`。後段は区別しない。

## 作り

1. 音声を mono 16kHz の mp3 にして、長くても `CHUNK_SEC` 秒に切る
   （短く切るほどタイムスタンプがずれにくい。Flash 系は長い音声で時刻が伸びる）。
   **区切りは話の切れ目に置く** — 前の区切りから CHUNK_SEC の 2/3〜1 倍の間で一番静かな所
   （`plan_chunks`）。長い音声を無音で区切ってから起こす定石（WhisperX の VAD 区切りと同じ考え）
2. 1チャンク1呼び出し。**課金経路は `model_governance.get_governed_client` を通る**
   （cost_guard の台帳・枠の降格が効く）。モデルは `model_policy` の
   `transcription` 工程の段から引く（直書きしない）
3. 応答の時刻を**チャンクの長さに収め**、重なりを詰めて、絶対時刻に直す
4. **欠落を自分で検知して起こし直す。** 音声の「喋っている長さ」に比べて文字が
   極端に少ないチャンクは、半分の長さに刻んでもう一度起こし、文字が増えた方を採る
   （`coverage.py`）。残った欠落は結果の `coverage` に載せ、品質ゲートが見る

2026-10-06: チャンクを 120 秒 → 30 秒にした。120 秒では Flash 系が約 30 秒の発話を
丸ごと落とし、残った1文に 54 秒分の時刻を付けた（同じ区間を 30 秒で起こすと正しく出た）。

2026-10-06: 30 秒ごとの機械的な区切りをやめた。43 分の素材で区切り 86 か所のうち 32 か所が
語の途中で、境目をまたいだ語は前の区切りで言い切りまで補われ、次の区切りの頭に壊れた語が
残った（素材の 90 秒の境目で「…スタートし」+「だったんですけど」。認識は「スタートしたんですけど」）。
静かな所で切ると語の途中は 3 か所（前後に認識した文字の間が 0.25 秒未満の区切りを数えた）。

試して捨てた案（2026-10-06）: 固有名詞辞書の人名・用語を指示に添えて先に教える
（Whisper の initial_prompt の考え）。名前の聞き違いは 13→7 件に減ったが、別の語が名前に
置き換わり（「広島の熊野も」→「広島の久木田のも」）、字を書いている無音の場面に「久木田博信」が
出た。名前の直しは校閲の辞書に任せる。

2026-10-06: 区切りをずらしてもう1回起こし、食い違いを手元の音声認識で決める
（`transcript_fusion`・文字起こしの工程が呼ぶ）。区切りを変えると聞き違いが別の所に出るため。

**1チャンクでも落ちたら全体を失敗にする。** 後段の SmartCut は字幕のある範囲だけを
残すので、黙って抜けたチャンクはそのまま動画から消える。
"""
from __future__ import annotations

import bisect
import json
import logging
import re
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

TASK = "transcription"
CHUNK_SEC = 30
PARALLEL = 4
MIN_SEG_SEC = 0.3

# 区切りは前の区切りから CHUNK_SEC × MIN_CHUNK_RATIO〜CHUNK_SEC 秒の間で一番静かな所に置く
MIN_CHUNK_RATIO = 2 / 3
# 静かさを測る幅。文の切れ目の間（0.3〜1 秒）を拾い、子音の弱い所（0.1 秒未満）は拾わない。
# 43 分の素材で 0.2〜0.8 秒を比べ、語の途中で切る数が少なかった幅（2026-10-06）
QUIET_SPAN_SEC = 0.5
QUIET_FRAME_SEC = 0.02
QUIET_RATE = 8000
# 一番静かな所と同じくらい静かな候補（この割合まで）が並ぶなら、狙いの位置に近い方を採る
QUIET_TIE = 0.05
# キャッシュ名の印。区切り方が変わったら変える（transcribe_worker._gemini_checkpoint）
CUT_TAG = "q"
# 2回目の起こし（transcript_fusion）: 最初のチャンクを半分にして、区切りを1回目の区切りの中ほどにずらす。
# 1回目の区切りの前後の語が、2回目ではチャンクの真ん中に来る
SECOND_PASS = True
SECOND_PASS_FIRST_SEC = CHUNK_SEC / 2
SECOND_PASS_TAG = "b"

PROMPT = """この音声は日本語の会話（{duration:.0f}秒）です。発話をすべて文字起こししてください。

出力は JSON 配列だけ。各要素は {{"start": 秒, "end": 秒, "text": "発話"}}。
- start / end はこの音声の先頭からの秒（小数第1位まで）。{duration:.0f} を超えない
- 1要素は1〜2文、長くても8秒程度で区切る。話者が替わったら区切る
- 聞こえたとおりに書く。要約しない・言い換えない。相づち（はい・うん）も書く
- 無音や音楽だけの区間は出力しない"""


class TranscriptionError(RuntimeError):
    """文字起こしが全体として成り立たなかった（チャンクの欠け・応答の解析失敗）。"""


@dataclass
class TranscribeResult:
    segments: list[dict]
    model: str
    chunks: int
    models_used: list[str] = field(default_factory=list)
    # 起こし直したチャンク（開始秒・元の文字数・起こし直し後の文字数）
    rechecked: list[dict] = field(default_factory=list)
    # 起こし終えた後の欠落の測定（coverage.CoverageReport.to_dict()）。測れなければ None
    coverage: dict | None = None
    # 起こし直しても文字が薄いままだった区間（素材の秒）。発話ではないとみなし、人の確認に回す
    quiet: list[tuple[float, float]] = field(default_factory=list)
    # チャンクの区切り（素材の秒・先頭の 0 は含まない）。境目の繰り返しを探す所
    cuts: list[float] = field(default_factory=list)


def _extract_json_array(text: str) -> list:
    """応答から JSON 配列を取り出す（コードブロックや前置きが付いても読む）。"""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            raise
        data = json.loads(text[start:end + 1])
    if isinstance(data, dict):
        for key in ("segments", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    if not isinstance(data, list):
        raise ValueError(f"JSON 配列ではありません: {type(data).__name__}")
    return data


def parse_segments(text: str, offset: float, duration: float) -> list[dict]:
    """1チャンクの応答を、絶対時刻のセグメントに直す。

    - 時刻は `[0, duration]` に収める（Flash 系は時刻がはみ出すことがある）
    - 開始順に並べ、前の終わりが次の始まりを越えていたら詰める
    - 空の発話・壊れた要素は捨てる。**時刻が読めない要素は捨てる**（推測で置かない）
    """
    items = _extract_json_array(text)
    rows: list[tuple[float, float, str]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        body = str(it.get("text") or "").strip()
        if not body:
            continue
        try:
            s = float(it.get("start"))
            e = float(it.get("end"))
        except (TypeError, ValueError):
            continue
        s = min(max(s, 0.0), duration)
        e = min(max(e, 0.0), duration)
        if e < s:
            s, e = e, s
        rows.append((s, e, body))
    rows.sort(key=lambda r: r[0])

    out: list[dict] = []
    for i, (s, e, body) in enumerate(rows):
        if i + 1 < len(rows):
            e = min(e, rows[i + 1][0])
        if e - s < MIN_SEG_SEC:
            e = min(s + MIN_SEG_SEC, duration)
        if e <= s:
            continue
        a, b = round(offset + s, 2), round(offset + e, 2)
        out.append({"start": a, "end": b, "text": body,
                    "sourceStart": a, "sourceEnd": b, "words": []})
    return out


def _probe_duration(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True, timeout=60).stdout
    return float(out.strip())


class QuietMap:
    """音の大きさの地図（フレームごとのエネルギー）。区切りを一番静かな所に置くために使う。"""

    def __init__(self, energy, frame_sec: float = QUIET_FRAME_SEC,
                 span_sec: float = QUIET_SPAN_SEC):
        import numpy as np

        e = np.asarray(energy, dtype=np.float64)
        k = max(1, int(round(span_sec / frame_sec)))
        # i 番目の値は、i 番目のフレームを中心にした span_sec 秒の平均
        self._smooth = np.convolve(e, np.ones(k) / k, mode="same") if len(e) else e
        self.frame_sec = frame_sec

    @classmethod
    def from_media(cls, media: str | Path) -> "QuietMap | None":
        """音声を読んで地図を作る。読めなければ None（呼び出し側は機械的な区切りに戻る）。"""
        try:
            import numpy as np

            pcm = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(media), "-vn", "-ac", "1",
                 "-ar", str(QUIET_RATE), "-f", "s16le", "-"],
                capture_output=True, check=True, timeout=600).stdout
        except (ImportError, OSError, subprocess.SubprocessError) as e:
            logger.warning(f"音の大きさを測れないので {CHUNK_SEC} 秒ごとに区切ります: {e}")
            return None
        hop = int(QUIET_RATE * QUIET_FRAME_SEC)
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        n = len(x) // hop
        if n == 0:
            return None
        return cls((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1))

    def quietest(self, lo: float, hi: float, target: float) -> float:
        """lo〜hi 秒で一番静かな所。同じくらい静かな所が並ぶなら target に近い方。"""
        import numpy as np

        f = self.frame_sec
        i0 = max(0, int(np.ceil(lo / f - 1e-9)))
        i1 = min(len(self._smooth), int(np.floor(hi / f + 1e-9)) + 1)
        if i1 <= i0:  # 地図の外（音声が映像より短いなど）
            return target
        window = self._smooth[i0:i1]
        floor = float(window.min())
        near = np.flatnonzero(window <= floor * (1 + QUIET_TIE) + 1e-12) + i0
        best = int(near[np.argmin(np.abs(near * f - target))])
        return min(max(round(best * f, 3), lo), hi)


def plan_chunks(total: float, chunk_sec: float = CHUNK_SEC,
                quiet: QuietMap | None = None, first: float | None = None) -> list[tuple[float, float]]:
    """チャンクの (開始, 長さ) の並び。

    区切りは前の区切りから chunk_sec の 2/3〜1 倍の間で一番静かな所（同じくらい静かなら
    長い方）。音の地図が無ければ chunk_sec 秒ごと（従来どおり）。
    first は最初のチャンクの長さ（2回目の起こしで区切りをずらす: `SECOND_PASS_FIRST_SEC`）。
    """
    out: list[tuple[float, float]] = []
    offset = 0.0
    length = first or chunk_sec
    while offset < total - 0.05:
        end = offset + length
        if end >= total - 0.05:
            out.append((offset, total - offset))
            break
        cut = (quiet.quietest(offset + length * MIN_CHUNK_RATIO, end, target=end)
               if quiet is not None else end)
        out.append((offset, cut - offset))
        offset = cut
        length = chunk_sec
    return out


def split_audio(video_path: str | Path, work_dir: str | Path,
                chunk_sec: int = CHUNK_SEC,
                plan: list[tuple[float, float]] | None = None) -> list[tuple[Path, float, float]]:
    """音声を mono 16kHz の mp3 にして切る。(path, offset, duration)。

    plan（`plan_chunks` の (開始, 長さ)）が無ければ `chunk_sec` 秒ずつ。
    """
    if plan is None:
        plan = plan_chunks(_probe_duration(video_path), chunk_sec, None)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    chunks = []
    for idx, (offset, dur) in enumerate(plan):
        path = work_dir / f"chunk_{idx:03d}.mp3"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{offset:.3f}", "-t", f"{dur:.3f}",
             "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
             str(path)],
            capture_output=True, text=True, check=True, timeout=300)
        chunks.append((path, offset, dur))
    return chunks


def _resolve_model() -> str:
    try:
        from backend import model_policy
    except ImportError:  # backend/ を直接 sys.path に載せている経路
        import model_policy  # type: ignore[no-redef]
    return model_policy.resolve(TASK).model


def _default_client() -> Any:
    from model_governance import get_governed_client

    client = get_governed_client("gemini_transcriber")
    if client is None:
        raise TranscriptionError("Gemini のクライアントを作れません（GOOGLE_API_KEY が未設定）")
    return client


def _retryable() -> tuple[type[BaseException], ...]:
    """1チャンクの試行で再試行してよい失敗（応答の解析失敗・通信・API の一時エラー）。

    `cost_guard.CostLimitExceeded` は含めない — 予算切れは再試行しても通らない。
    """
    kinds: list[type[BaseException]] = [ValueError, OSError, TimeoutError, ConnectionError]
    try:
        from google.genai.errors import APIError
        kinds.append(APIError)
    except ImportError:
        pass
    return tuple(kinds)


def _call(client: Any, model: str, audio: Path, duration: float) -> tuple[str, str]:
    """1チャンクを送って (応答の本文, 応答したモデル) を返す。"""
    from google.genai import types

    response = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=audio.read_bytes(), mime_type="audio/mp3"),
                  PROMPT.format(duration=duration)],
        config=types.GenerateContentConfig(response_mime_type="application/json",
                                           temperature=0),
    )
    return response.text or "", getattr(response, "model_version", None) or model


# 区切りの頭に残る、前の区切りの語の尻尾（「まいります」の後の「います」）の長さの上限
ECHO_MAX_CHARS = 8


# 日本語どうしの間の半角空白（と、日本語の後ろの「?」「!」の前の空白）
# 数字の両側の空白も詰める（「小学校 3 年生」・2026-10-06 実測）。英字の語との間（「YouTube の」）は残す
_SPACED = re.compile(r"(?<=[^\x00-\x7f]) +(?=(?:[^\x00-\x7f]|[?!0-9]))|(?<=[0-9]) +(?=[^\x00-\x7f])")


def join_spaced_words(segments: list[dict]) -> list[dict]:
    """語ごとに空白で区切って起こされた文（「久田 先生 って 普段」）を詰める。

    起こし直した区切りがこの形で返ることがある（2026-10-06 実測）。校閲が詰めなかった回は
    字幕に「人 な\nん だろ うっ て」と出た。英字の語の間の空白は残す。
    """
    out = []
    for seg in segments:
        text = seg.get("text") if isinstance(seg, dict) else None
        if isinstance(text, str) and " " in text:
            joined = _SPACED.sub("", text)
            if joined != text:
                seg = {**seg, "text": joined}
        out.append(seg)
    return out


def drop_boundary_echoes(segments: list[dict], chunk_sec: float = CHUNK_SEC,
                         cuts: list[float] | None = None) -> list[dict]:
    """区切りの頭のセグメントが、直前のセグメントの尻尾の繰り返しなら除く。

    区切りは cuts（素材の秒）。無ければ chunk_sec 秒ごと（区切りを記録していない古いキャッシュ）。

    境目をまたいだ語は、前の区切りで言い切りまで起こされ、次の区切りの頭に尻尾だけが
    もう一度出る（2026-10-06 実測: 30 秒で「…まいります。」の後に「います。」が残り、
    「では」を言っている所に字幕が出た）。
    """
    def norm(t):
        return "".join(ch for ch in str(t) if ch not in "、。，．,. 　\n「」『』！？!?")

    marks = sorted(float(c) for c in cuts) if cuts is not None else None

    def at_cut(start: float) -> bool:
        if marks is None:
            return start > 0 and abs(start - round(start / chunk_sec) * chunk_sec) < 0.3
        i = bisect.bisect_left(marks, start)
        return any(abs(start - marks[j]) < 0.3 for j in (i - 1, i) if 0 <= j < len(marks))

    out: list[dict] = []
    for seg in segments:
        try:
            start = float(seg.get("start", 0))
        except (TypeError, ValueError, AttributeError):
            out.append(seg)
            continue
        at_boundary = at_cut(start)
        text = norm(seg.get("text", ""))
        prev = norm(out[-1].get("text", "")) if out else ""
        if at_boundary and _is_echo(text, prev):
            logger.info(f"区切りの境目の繰り返しを除きました: {start:.1f}秒 {seg.get('text')!r}")
            continue
        out.append(seg)
    return out


def _is_echo(text: str, prev: str) -> bool:
    """text が prev の尻尾の繰り返しか。尻尾の音だけを起こすので字が少し変わる
    （「まいります」の尻尾が「います」）。尻尾の数文字に順に含まれ、終わり2文字が同じなら繰り返し。"""
    if not text or not prev or len(text) > ECHO_MAX_CHARS:
        return False
    if prev.endswith(text):
        return True
    rest = iter(prev[-(len(text) + 2):])
    in_tail = all(ch in rest for ch in text)
    return in_tail and len(text) >= 2 and text[-2:] == prev[-2:]


def transcribe(video_path: str | Path, *, client: Any = None, model: str | None = None,
               chunk_sec: int = CHUNK_SEC, parallel: int = PARALLEL,
               call: Callable[..., tuple[str, str]] | None = None,
               attempts: int = 4, backoff: float = 3.0,
               first_chunk_sec: float | None = None,
               journal: str | Path | None = None) -> TranscribeResult:
    """動画の音声を Gemini で起こす。1チャンクでも起こせなければ `TranscriptionError`。

    first_chunk_sec は最初のチャンクの長さ（2回目の起こしで区切りをずらす）。
    journal はチャンクごとの控え（`journal_path`）。起こせたチャンクから書き足し、次の実行では
    控えにあるチャンク（頭と長さが同じもの）を呼び直さない。無料枠の1日の上限で途中で落ちても、
    枠が戻った後は続きから起こせる（2026-10-07: 104 本中 71 本目で落ち、70 本分が消えた）。
    """
    model = model or _resolve_model()
    client = client if client is not None else _default_client()
    call = call or _call

    with tempfile.TemporaryDirectory(prefix="gemini_tx_") as tmp:
        quiet_map = QuietMap.from_media(video_path)
        plan = plan_chunks(_probe_duration(video_path), chunk_sec, quiet_map, first=first_chunk_sec)
        chunks = split_audio(video_path, tmp, plan=plan)
        logger.info(f"🎤 Gemini 文字起こし: {len(chunks)} チャンク（長くても{chunk_sec}秒・"
                    f"{'話の切れ目' if quiet_map is not None else '機械的'}に区切る）model={model}")

        done = read_journal(journal)
        lock = threading.Lock()

        def one(args: tuple[int, tuple[Path, float, float]]) -> tuple[list[dict], str]:
            i, (path, offset, dur) = args
            if _journal_key(offset, dur) in done:
                segs, used = done[_journal_key(offset, dur)]
                logger.info(f"  ♻️ チャンク {i + 1}/{len(chunks)}: 前回起こした分を使います ({used})")
                return segs, used
            last: BaseException | None = None
            for attempt in range(attempts):
                try:
                    text, used = call(client, model, path, dur)
                    segs = parse_segments(text, offset, dur)
                    logger.info(f"  ✅ チャンク {i + 1}/{len(chunks)}: {len(segs)} セグメント ({used})")
                    _append_journal(journal, lock, offset, dur, segs, used)
                    return segs, used
                except _retryable() as e:
                    last = e
                    logger.warning(f"  ⚠️ チャンク {i + 1}/{len(chunks)} 試行 {attempt + 1}: {e}")
                    # 502/503（上流の混雑）は数秒で戻ることが多い。チャンクが 87 本あると
                    # 2回だけでは1本は当たって全体が落ちる（2026-10-06 実測）
                    if attempt + 1 < attempts and backoff > 0:
                        time.sleep(backoff * (2 ** attempt))
            raise TranscriptionError(f"チャンク {i + 1}/{len(chunks)}（{offset:.0f}秒〜）を起こせません: {last}")

        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            results = list(pool.map(one, enumerate(chunks)))

        speech = _speech_or_none(video_path)
        rechecked: list[dict] = []
        quiet: list[tuple[float, float]] = []
        if speech is not None:
            for i, (path, offset, dur) in enumerate(chunks):
                if not _is_sparse(results[i][0], speech, offset, dur):
                    continue
                before = _chars(results[i][0])
                # 半分に刻む所も、真ん中あたりで一番静かな所
                mid = (quiet_map.quietest(offset + dur * 0.3, offset + dur * 0.7, offset + dur / 2) - offset
                       if quiet_map is not None else dur / 2)
                try:
                    redo = _retranscribe_halves(path, offset, dur, Path(tmp), i,
                                                lambda p, o, d: call(client, model, p, d), mid=mid)
                except _retryable() as e:
                    logger.warning(f"  ⚠️ チャンク {i + 1} の起こし直しに失敗: {e}")
                    continue
                after = _chars(redo[0])
                rechecked.append({"start": round(offset, 1), "chars_before": before,
                                  "chars_after": after, "adopted": after > before})
                logger.warning(f"  🔁 チャンク {i + 1}（{offset:.0f}秒〜）は文字が薄いので起こし直し: "
                               f"{before} → {after} 文字")
                if after > before:
                    results[i] = redo
                # 刻み方を変えた2回目でも薄い → 書いている場面や BGM。欠落ではなく静かな区間
                if _is_sparse(results[i][0], speech, offset, dur):
                    quiet.append((round(offset, 2), round(offset + dur, 2)))

    cuts = [round(offset, 3) for _, offset, _ in chunks[1:]]
    segments = drop_boundary_echoes(join_spaced_words([s for segs, _ in results for s in segs]),
                                    chunk_sec, cuts=cuts)
    if not segments:
        raise TranscriptionError("発話が1件も起こせませんでした")
    used = sorted({u for _, u in results})
    report = None
    if speech is not None:
        from subtitle_engine import coverage
        report = coverage.measure(segments, speech[0], speech[1], exclude=quiet).to_dict()
        if report["has_gaps"]:
            logger.warning(f"⚠️ 文字起こしに欠落が残っています: {report['uncovered_sec']}秒・"
                           f"薄い区間 {len(report['sparse'])}件")
    return TranscribeResult(segments=segments, model=model, chunks=len(chunks), models_used=used,
                            rechecked=rechecked, coverage=report,
                            quiet=quiet if speech is not None else [], cuts=cuts)


def _chars(segs: list[dict]) -> int:
    return sum(len(s.get("text", "")) for s in segs)


def _speech_or_none(video_path: str | Path):
    """(音がある区間, 全体の長さ)。測れなければ None（起こし直しと測定を飛ばす）。"""
    try:
        from subtitle_engine import coverage
        return coverage.speech_intervals(video_path)
    except Exception as e:  # ffmpeg が無い・テストの差し替え音源など
        logger.warning(f"発話区間を測れないので欠落の検知を飛ばします: {e}")
        return None


def _is_sparse(segs: list[dict], speech, offset: float, dur: float) -> bool:
    from subtitle_engine import coverage
    talk = sum(coverage._overlap(a, b, offset, offset + dur) for a, b in speech[0])
    if talk < coverage.MIN_SPEECH_IN_WINDOW:
        return False
    return _chars(segs) / talk < coverage.SPARSE_CPS


def _retranscribe_halves(path: Path, offset: float, dur: float, work: Path, idx: int,
                         call_one, mid: float | None = None) -> tuple[list[dict], str]:
    """1チャンクを2つに刻んで起こし直す。刻む所はチャンクの頭から mid 秒（既定は真ん中）。"""
    mid = dur / 2 if mid is None else mid
    segs: list[dict] = []
    used = ""
    for j, (a, b) in enumerate(((0.0, mid), (mid, dur))):
        sub = work / f"chunk_{idx:03d}_{j}.mp3"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}",
             "-i", str(path), "-c", "copy", str(sub)],
            capture_output=True, text=True, check=True, timeout=120)
        text, used = call_one(sub, offset + a, b - a)
        segs.extend(parse_segments(text, offset + a, b - a))
    return segs, used


def journal_path(checkpoint: str | Path) -> Path:
    """チャンクごとの控えの置き場所（キャッシュの隣）。キャッシュを書いたら消してよい。"""
    p = Path(checkpoint)
    return p.with_name(p.stem + ".chunks.journal")


def _journal_key(offset: float, dur: float) -> tuple[float, float]:
    return round(float(offset), 3), round(float(dur), 3)


def read_journal(journal: str | Path | None) -> dict[tuple[float, float], tuple[list[dict], str]]:
    """控えを読む: (チャンクの頭, 長さ) → (行, モデル)。

    読めない行は飛ばす（書き込み中に止められると、最後の行が途中で切れる）。
    """
    done: dict[tuple[float, float], tuple[list[dict], str]] = {}
    if journal is None:
        return done
    try:
        lines = Path(journal).read_text(encoding="utf-8").splitlines()
    except OSError:
        return done
    for line in lines:
        try:
            rec = json.loads(line)
            done[_journal_key(rec["offset"], rec["duration"])] = (list(rec["segments"]),
                                                                  str(rec.get("model") or ""))
        except (ValueError, KeyError, TypeError):
            continue
    return done


def _append_journal(journal: str | Path | None, lock: threading.Lock, offset: float, dur: float,
                    segs: list[dict], used: str) -> None:
    if journal is None:
        return
    line = json.dumps({"offset": round(offset, 3), "duration": round(dur, 3), "model": used,
                       "segments": segs}, ensure_ascii=False)
    try:
        with lock, open(journal, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:  # 控えが書けなくても起こしは続ける（落ちたときに続きから起こせないだけ）
        logger.warning(f"チャンクの控えを書けません: {e}")


def write_checkpoint(segments: list[dict], path: str | Path,
                     meta: dict | None = None) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
    if meta is not None:
        meta_path(path).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def meta_path(checkpoint: str | Path) -> Path:
    """起こしの付帯情報（静かな区間・欠落の測定）の置き場所。キャッシュと一緒に使い回す。"""
    p = Path(checkpoint)
    return p.with_name(p.stem + ".meta.json")


def read_meta(checkpoint: str | Path) -> dict:
    try:
        return json.loads(meta_path(checkpoint).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
