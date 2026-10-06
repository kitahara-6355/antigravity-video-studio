"""Gemini 音声入力による文字起こし（R2.5-C4 の主経路）。

2026-09-26 のユーザー決定で、文字起こしの**主は Gemini 音声入力、従は Whisper**。
クラウドのコンテナは GPU が無く、Whisper のモデル置き場（Hugging Face）にも
出られないので、クラウドだけで回すにはこちらが要る。

出力は Whisper の経路（`whisper_subprocess.py`）と同じ JSONL の行
`{start, end, text, sourceStart, sourceEnd, words}`。後段は区別しない。

## 作り

1. 音声を mono 16kHz の mp3 にして `CHUNK_SEC` 秒ずつに切る
   （短く切るほどタイムスタンプがずれにくい。Flash 系は長い音声で時刻が伸びる）
2. 1チャンク1呼び出し。**課金経路は `model_governance.get_governed_client` を通る**
   （cost_guard の台帳・枠の降格が効く）。モデルは `model_policy` の
   `transcription` 工程の段から引く（直書きしない）
3. 応答の時刻を**チャンクの長さに収め**、重なりを詰めて、絶対時刻に直す
4. **欠落を自分で検知して起こし直す。** 音声の「喋っている長さ」に比べて文字が
   極端に少ないチャンクは、半分の長さに刻んでもう一度起こし、文字が増えた方を採る
   （`coverage.py`）。残った欠落は結果の `coverage` に載せ、品質ゲートが見る

2026-10-06: チャンクを 120 秒 → 30 秒にした。120 秒では Flash 系が約 30 秒の発話を
丸ごと落とし、残った1文に 54 秒分の時刻を付けた（同じ区間を 30 秒で起こすと正しく出た）。

**1チャンクでも落ちたら全体を失敗にする。** 後段の SmartCut は字幕のある範囲だけを
残すので、黙って抜けたチャンクはそのまま動画から消える。
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

TASK = "transcription"
CHUNK_SEC = 30
PARALLEL = 4
MIN_SEG_SEC = 0.3

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


def split_audio(video_path: str | Path, work_dir: str | Path,
                chunk_sec: int = CHUNK_SEC) -> list[tuple[Path, float, float]]:
    """音声を mono 16kHz の mp3 にして `chunk_sec` 秒ずつに切る。(path, offset, duration)。"""
    total = _probe_duration(video_path)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    chunks = []
    offset, idx = 0.0, 0
    while offset < total - 0.05:
        dur = min(chunk_sec, total - offset)
        path = work_dir / f"chunk_{idx:03d}.mp3"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{offset:.3f}", "-t", f"{dur:.3f}",
             "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
             str(path)],
            capture_output=True, text=True, check=True, timeout=300)
        chunks.append((path, offset, dur))
        offset += dur
        idx += 1
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


def transcribe(video_path: str | Path, *, client: Any = None, model: str | None = None,
               chunk_sec: int = CHUNK_SEC, parallel: int = PARALLEL,
               call: Callable[..., tuple[str, str]] | None = None,
               attempts: int = 2) -> TranscribeResult:
    """動画の音声を Gemini で起こす。1チャンクでも起こせなければ `TranscriptionError`。"""
    model = model or _resolve_model()
    client = client if client is not None else _default_client()
    call = call or _call

    with tempfile.TemporaryDirectory(prefix="gemini_tx_") as tmp:
        chunks = split_audio(video_path, tmp, chunk_sec)
        logger.info(f"🎤 Gemini 文字起こし: {len(chunks)} チャンク（{chunk_sec}秒ずつ）model={model}")

        def one(args: tuple[int, tuple[Path, float, float]]) -> tuple[list[dict], str]:
            i, (path, offset, dur) = args
            last: BaseException | None = None
            for attempt in range(attempts):
                try:
                    text, used = call(client, model, path, dur)
                    segs = parse_segments(text, offset, dur)
                    logger.info(f"  ✅ チャンク {i + 1}/{len(chunks)}: {len(segs)} セグメント ({used})")
                    return segs, used
                except _retryable() as e:
                    last = e
                    logger.warning(f"  ⚠️ チャンク {i + 1}/{len(chunks)} 試行 {attempt + 1}: {e}")
            raise TranscriptionError(f"チャンク {i + 1}/{len(chunks)}（{offset:.0f}秒〜）を起こせません: {last}")

        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            results = list(pool.map(one, enumerate(chunks)))

        speech = _speech_or_none(video_path)
        rechecked: list[dict] = []
        if speech is not None:
            for i, (path, offset, dur) in enumerate(chunks):
                if not _is_sparse(results[i][0], speech, offset, dur):
                    continue
                before = _chars(results[i][0])
                try:
                    redo = _retranscribe_halves(path, offset, dur, Path(tmp), i,
                                                lambda p, o, d: call(client, model, p, d))
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

    segments = [s for segs, _ in results for s in segs]
    if not segments:
        raise TranscriptionError("発話が1件も起こせませんでした")
    used = sorted({u for _, u in results})
    report = None
    if speech is not None:
        from subtitle_engine import coverage
        report = coverage.measure(segments, speech[0], speech[1]).to_dict()
        if report["has_gaps"]:
            logger.warning(f"⚠️ 文字起こしに欠落が残っています: {report['uncovered_sec']}秒・"
                           f"薄い区間 {len(report['sparse'])}件")
    return TranscribeResult(segments=segments, model=model, chunks=len(chunks), models_used=used,
                            rechecked=rechecked, coverage=report)


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
                         call_one) -> tuple[list[dict], str]:
    """1チャンクを半分ずつに刻んで起こし直す。"""
    half = dur / 2
    segs: list[dict] = []
    used = ""
    for j in range(2):
        sub = work / f"chunk_{idx:03d}_{j}.mp3"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{j * half:.3f}", "-t", f"{half:.3f}",
             "-i", str(path), "-c", "copy", str(sub)],
            capture_output=True, text=True, check=True, timeout=120)
        text, used = call_one(sub, offset + j * half, half)
        segs.extend(parse_segments(text, offset + j * half, half))
    return segs, used


def write_checkpoint(segments: list[dict], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
