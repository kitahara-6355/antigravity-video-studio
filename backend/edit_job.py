"""1本の自動編集を、手順どおりに頭から通す（スキル `interview-edit` の本体・フェーズ1・2026-10-18）。

手順はコマンドとファイルだけで書く。動かす AI（Claude Code・Antigravity・Gemini）が何であっても、
同じ job ファイルから同じ手順で同じ動画を作れるようにするため（北原さんの追加要望①）。
人への知らせ（チャットなど）はここに入れない。動かしている AI が自分の道具で行う。

    python -m backend.edit_job check  <job>           始める前の確かめだけ（AI を呼ばない）
    python -m backend.edit_job run    <job>           頭から通す。済んだ手順は飛ばすので、落ちたら続きから
    python -m backend.edit_job status <job>           いまどこまで進んだか
    python -m backend.edit_job note   <job> "理由"    工程ライブに判断を書き足す

`<job>` は job ファイル（`backend/config/jobs/<名前>.json`）か、その名前。中身:

    name       作業の名前（作業場と置き場のフォルダ名になる）
    label      人が読む名前
    raw        {"folder": raw のフォルダの中の素材のフォルダ名（null なら raw のフォルダそのもの）,
                "parts": [つなぐ順のファイル名]}
    material   つないだ素材のファイル名
    versions   [{"key", "label", "review": 校正台帳（無ければ台帳なし）}]。この順に書き出す
    approved   物差しにする書き出しの字幕（`*.subtitles.json`）。あれば各版と比べる
    out        置き場（共有フォルダ）

置き場（`out`）:

    live/status.json     工程ライブの画面が読む全体のいま（手順・工程・AI の呼び出し・枠・判断）
    live/journal.jsonl   起きたことを1行ずつ（手順の始まりと終わり・判断）
    <版>/                確認用ファイル（3分版・全編360p版・一覧画像・レビュー画面の控え・比べた結果）
    assets/              残す資産（AI の出力・字幕データ・記録）と assets.json（役目と sha256）

作業場（git の外）は `pipeline_work/jobs/<name>/`（raw・素材・確認用ファイルの下書き・ログ・state.json）。

**課金**: `run` は書き出しの手順（`edit:*`）で Gemini API を呼ぶ（無料枠の段）。その手前で毎回、
無料枠の残り・予算の残り・空きを確かめ、足りなければ1回も呼ばずに止まる。`check`・`status`・`note` は呼ばない。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
JOBS_DIR = REPO_ROOT / "backend" / "config" / "jobs"
WORK_ROOT = REPO_ROOT / "pipeline_work" / "jobs"
RUNS_DIR = REPO_ROOT / "output" / "runs"
MODEL_CONFIG = REPO_ROOT / "backend" / "model_config.json"

# 書き出しが書き換えるファイル。走らせる前に手つかずか確かめ、走った後に戻す。
# 辞書は AI の指示文に入るので、戻さないと次の書き出しで校閲の控えが外れる
RUNTIME_FILES = ("backend/branding/proper_nouns.json",
                 "backend/usage_tracker/usage_data.json",
                 "backend/usage_tracker/daily_usage.json")

# 43分の素材を最初から書き出すと約410回（2026-10-18 の実測: 起こし 400・校閲 12・説明文 1）。ゆとりを足す
CACHELESS_CALLS = 450
CACHED_CALLS = 10
# 予算の残りの下限（見積もりは上限側で、無料枠に収まれば実費は 0 円。キャッシュ無しの通しは上限見積もりで約 ¥25）
CACHELESS_JPY = 60.0
CACHED_JPY = 5.0
# 書き出しが始まらない空き（1GB）に、プレビュー（約200MB）と途中のファイルの分を足す
MIN_FREE_BYTES = 3 * 1024 ** 3
# 書き出しが使う段。文字起こし・校閲・説明文は standard で、枠が尽きると batch に落ちて動く
QUOTA_TIERS = ("standard", "batch")
PACIFIC = ZoneInfo("America/Los_Angeles")  # 無料枠の1日は米国太平洋時間の0時に切り替わる（実測）
JST = ZoneInfo("Asia/Tokyo")
POLL_SEC = 15.0
# AI（と手元の音声認識）の出力。消すと作り直しに API が要る。映像の切り替わり（_shots_）と音声は毎回同じに作れる
AI_OUTPUTS = ("_gemini_*", "_proofread_*", "_align_rz_*")

STAGE_LABELS = {"transcribe": "文字起こし", "proofread": "校閲", "smart_cut": "カット",
                "preview": "プレビューの書き出し", "youtube_opt": "タイトルと説明文",
                "quality_gate": "品質の確かめ"}


class JobError(RuntimeError):
    """前提が満たされない（job ファイルが壊れている・枠や予算や空きが足りない・書き出しが失敗した）。"""


# --- job ファイル -----------------------------------------------------------------------


def job_path(name_or_path: str) -> Path:
    p = Path(name_or_path)
    if p.suffix == ".json" or p.exists():
        return p
    return JOBS_DIR / f"{name_or_path}.json"


def load_job(path: str | Path) -> dict:
    """job ファイルを読んで確かめる。壊れていれば何も始めずに JobError。"""
    path = Path(path)
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise JobError(f"job ファイルを読めません: {path}（{e}）") from e
    for key in ("name", "material", "out"):
        if not str(job.get(key) or "").strip():
            raise JobError(f"job ファイルに {key} がありません: {path}")
    if not re.fullmatch(r"[\w.-]+", job["name"]) or job["name"] in (".", ".."):
        raise JobError(f"name は英数字と _ - . だけにします（フォルダ名になる）: {job['name']!r}")
    parts = (job.get("raw") or {}).get("parts") or []
    if not parts or len(set(parts)) != len(parts):
        raise JobError("raw.parts に、つなぐ順のファイル名を重ならずに並べます")
    keys = [v.get("key") for v in job.get("versions") or []]
    if not keys or not all(keys) or len(set(keys)) != len(keys):
        raise JobError("versions に、重ならない key を持つ版を1つ以上並べます")
    return job


def plan_steps(job: dict) -> list[dict]:
    """手順の並び。版ごとに「書き出す → 確認用ファイル →（物差しがあれば）比べる」を繰り返す。"""
    steps = [{"key": "check", "label": "始める前の確かめ", "place": "作業場"},
             {"key": "fetch", "label": "raw を Drive から取ってくる", "place": "Google Drive → 作業場"},
             {"key": "join", "label": "raw をつないで素材にする", "place": "作業場（ffmpeg）"}]
    for v in job["versions"]:
        key, label = v["key"], v.get("label") or v["key"]
        steps.append({"key": f"edit:{key}", "label": f"{label}を書き出す",
                      "place": "作業場 ＋ Gemini API", "version": key})
        steps.append({"key": f"review:{key}", "label": f"{label}の確認用ファイルを置く",
                      "place": "作業場 → 共有フォルダ", "version": key})
        if job.get("approved"):
            steps.append({"key": f"compare:{key}", "label": f"{label}を物差しと比べる",
                          "place": "作業場", "version": key})
    steps.append({"key": "keep", "label": "過程の資産を残す", "place": "作業場 → 共有フォルダ"})
    return steps


# --- 無料枠と予算 -----------------------------------------------------------------------


def _parse_at(value: Any) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def day_start(now: dt.datetime) -> dt.datetime:
    """無料枠の今日の始まり（米国太平洋時間の0時）。夏時間は 07:00 UTC、冬時間は 08:00 UTC。"""
    local = now.astimezone(PACIFIC).date()
    return dt.datetime.combine(local, dt.time(0), tzinfo=PACIFIC).astimezone(dt.timezone.utc)


def next_reset(now: dt.datetime) -> dt.datetime:
    local = now.astimezone(PACIFIC).date() + dt.timedelta(days=1)
    return dt.datetime.combine(local, dt.time(0), tzinfo=PACIFIC).astimezone(dt.timezone.utc)


def read_ledger(path: str | Path) -> list[dict]:
    """費用の台帳（1行1件）。書きかけの行は飛ばす。"""
    path = Path(path)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def calls_today(rows: list[dict], now: dt.datetime) -> Counter:
    """今日（太平洋時間）の呼び出しをモデルごとに数える。降格・要約の行は数えない。"""
    start = day_start(now)
    used: Counter = Counter()
    for r in rows:
        if r.get("kind") or not r.get("model"):
            continue
        t = _parse_at(r.get("at"))
        if t and start <= t <= now:
            used[r["model"]] += 1
    return used


def free_capacity(rows: list[dict], now: dt.datetime, tiers: dict) -> tuple[int, list[dict]]:
    """書き出しが使う段（standard → batch）の、今日の残りの回数の合計と内訳。"""
    used = calls_today(rows, now)
    detail = []
    for tier in QUOTA_TIERS:
        model = (tiers.get(tier) or {}).get("model")
        if not model:
            continue
        limit = int((tiers.get(tier) or {}).get("rpd") or 0)
        detail.append({"tier": tier, "model": model, "limit": limit, "used": used.get(model, 0),
                       "left": max(0, limit - used.get(model, 0))})
    return sum(d["left"] for d in detail), detail


def load_tiers(path: str | Path = MODEL_CONFIG) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    return (config.get("text_generation") or {}).get("tiers") or {}


def active_budget(path: str | Path, rows: list[dict]) -> tuple[dict | None, float]:
    """有効な予算と残り（円）。使った額は budget.json と台帳の最後の記録の大きいほう。"""
    path = Path(path)
    if not path.is_file():
        return None, 0.0
    budget = next((b for b in json.loads(path.read_text(encoding="utf-8")).get("budgets", [])
                   if b.get("status") == "active"), None)
    if budget is None:
        return None, 0.0
    spent = float(budget.get("spent_jpy") or 0)
    for r in rows:
        if r.get("budget_id") == budget.get("id") and r.get("spent_jpy") is not None:
            spent = max(spent, float(r["spent_jpy"]))
    return budget, float(budget.get("limit_jpy") or 0) - spent


# --- 本線の実行記録とログ ---------------------------------------------------------------


def find_run(runs_dir: str | Path, material: str | Path, since: dt.datetime,
             repo: Path = REPO_ROOT) -> Path | None:
    """この素材で `since` 以後に始まった実行の記録のフォルダ（いちばん新しいもの）。"""
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return None
    want = Path(material).resolve()
    # 実行の名前は始めた時刻（UTC）で始まる。新しいほうから少しだけ読む
    names = sorted((p for p in runs_dir.iterdir() if p.is_dir() and p.name[:1].isdigit()), reverse=True)
    for d in names[:30]:
        try:
            run = json.loads((d / "run.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        started = _parse_at(run.get("started_at"))
        video = (run.get("inputs") or {}).get("video_path")
        if not started or started < since or not video:
            continue
        path = Path(video) if Path(video).is_absolute() else repo / video
        if path.resolve() == want:
            return d
    return None


def run_view(run: dict) -> dict:
    """工程ライブに出す実行の姿（工程ごとの状態・モデル・回数・時刻）。"""
    stages = [{"name": s.get("name"), "label": STAGE_LABELS.get(s.get("name"), s.get("name")),
               "status": s.get("status"), "model": s.get("model"), "tier": s.get("tier"),
               "reason": s.get("model_reason"), "calls": s.get("calls", 0),
               "fallbacks": len(s.get("fallbacks") or []),
               "started_at": s.get("started_at"), "finished_at": s.get("finished_at"),
               **({"quality": s["quality"]} if s.get("quality") else {})}
              for s in run.get("stages") or []]
    return {"run_id": run.get("run_id"), "status": run.get("status"),
            "started_at": run.get("started_at"), "finished_at": run.get("finished_at") or None,
            "calls": run.get("calls", 0), "cost_jpy": run.get("cost_jpy", 0),
            "models_used": run.get("models_used") or [], "stages": stages}


_RESULT_LINE = re.compile(r"^\s+(状態|所要|成果物|プレビュー|品質)\s*:\s*(.*?)\s*$")


def parse_result(text: str) -> dict:
    """本線（pipeline_coordinator）が最後に出す結果の行を読む。"""
    found: dict[str, str] = {}
    warnings = []
    for line in text.splitlines():
        m = _RESULT_LINE.match(line)
        if m:
            found[m.group(1)] = m.group(2)
        elif line.strip().startswith("⚠"):
            warnings.append(line.strip().lstrip("⚠").strip())

    def value(label: str) -> str | None:
        v = found.get(label)
        return None if v in (None, "", "(無し)", "None") else v

    duration = value("所要")
    quality = value("品質")
    try:
        quality_value: float | int | None = float(quality) if quality is not None else None
        if quality_value is not None and float(quality_value).is_integer():
            quality_value = int(quality_value)
    except ValueError:
        quality_value = None
    return {"status": value("状態"),
            "duration_sec": float(duration.split()[0]) if duration else None,
            "final": value("成果物"), "preview": value("プレビュー"),
            "quality": quality_value, "warnings": warnings}


_PROGRESS = re.compile(r"チャンク\s*\d+/\d+|起こし|校閲|カット|書き出し|プレビュー|品質|字幕|説明文|区切り")
_LOG_PREFIX = re.compile(r"^(?:DEBUG|INFO|WARNING|ERROR|CRITICAL):[\w.]+:")


def progress_line(text: str) -> str:
    """ログの終わりから、いまの進み具合を表す行を1つ選ぶ（無ければ最後の行）。"""
    lines = [_LOG_PREFIX.sub("", line).strip() for line in text.splitlines()[-300:]]
    lines = [line for line in lines if line]
    for line in reversed(lines):
        if _PROGRESS.search(line) and not line.startswith("HTTP"):
            return line[:200]
    return lines[-1][:200] if lines else ""


def _tail(path: Path, size: int = 32_000) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(max(0, path.stat().st_size - size))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def chunk_journals(material: Path) -> list[dict]:
    """起こしの途中の控え（チャンクごとに1行）の行数。ログに頼らない進み具合。"""
    out = []
    for path in sorted(Path(material).parent.glob("_gemini_*.chunks.journal")):
        try:
            lines = sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
        except OSError:
            continue
        out.append({"name": path.name, "chunks": lines})
    return out


def run_mainline(argv: list[str]) -> int:
    """本線を動かす。処理は `python -m backend.agents.pipeline_coordinator` と同じで、
    進み具合（INFO の記録）もログに出す（本線は記録の設定を持たず、警告しか出ない）。"""
    import logging

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout, force=True)
    for noisy in ("httpx", "httpcore", "urllib3", "google_genai", "google.auth", "asyncio",
                  "matplotlib", "PIL", "numba", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    from backend.agents import pipeline_coordinator

    return pipeline_coordinator.main(argv)


# --- 残す資産 -----------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _keep(src: Path, dest_root: Path, rel: str, role: str) -> dict:
    dst = dest_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    digest = _sha256(src)
    shutil.copyfile(src, dst)
    if _sha256(dst) != digest:
        raise JobError(f"写した資産が元と合いません: {rel}")
    return {"path": rel, "role": role, "keep": "asset", "sha256": digest,
            "size": src.stat().st_size, "from": str(src)}


def collect_assets(material: Path, dest: Path, *, captions: dict[str, Path],
                   records: dict[str, Path]) -> list[dict]:
    """素材の隣の AI の出力・各版の字幕データ・記録を `dest` に写す（役目と sha256 つき）。

    素材そのもの（raw をつなげば同じ物ができる）・映像の切り替わり・音声は写さない。
    """
    files = []
    for pattern in AI_OUTPUTS:
        for src in sorted(Path(material).parent.glob(pattern)):
            if src.is_file():
                files.append(_keep(src, dest, f"ai/{src.name}", "ai_output"))
    for key, src in captions.items():
        files.append(_keep(Path(src), dest, f"captions/{key}.subtitles.json", "caption_data"))
    for name, src in records.items():
        files.append(_keep(Path(src), dest, f"records/{name}", "record"))
    return files


# --- 確認用ファイル -----------------------------------------------------------------------


def _ffmpeg(args: list[Any]) -> None:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *map(str, args)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise JobError(f"ffmpeg が失敗しました: {proc.stderr.strip()[-300:]}")


def _streamhash(path: Path) -> str:
    proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0", "-c", "copy",
                           "-f", "streamhash", "-hash", "sha256", "-"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise JobError(f"中身を照合できません: {path.name}（{proc.stderr.strip()[-200:]}）")
    return proc.stdout


def build_review_files(preview: Path, dest: Path) -> None:
    """3分版・全編360p版・一覧画像（6コマ）を作る。中身は手で作ってきたもの（10-06〜）と同じ。"""
    from backend import media_concat

    dest.mkdir(parents=True, exist_ok=True)
    _ffmpeg(["-i", preview, "-t", "180", "-c", "copy", "-movflags", "+faststart", dest / "first3.mp4"])
    _ffmpeg(["-i", preview, "-vf", "scale=-2:360", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "28", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
             "-movflags", "+faststart", dest / "full360.mp4"])
    duration = media_concat.probe(preview)["duration"]
    frames = [dest / f"_frame{i}.jpg" for i in range(6)]
    try:
        for i, frame in enumerate(frames):
            _ffmpeg(["-ss", f"{duration * (2 * i + 1) / 12:.2f}", "-i", preview,
                     "-frames:v", "1", "-vf", "scale=640:-1", frame])
        inputs = [a for f in frames for a in ("-i", f)]
        _ffmpeg([*inputs, "-filter_complex",
                 "[0][1][2][3][4][5]xstack=inputs=6:layout=0_0|w0_0|0_h0|w0_h0|0_h0+h1|w0_h0+h1",
                 dest / "contact.jpg"])
    finally:
        for frame in frames:
            frame.unlink(missing_ok=True)


def place(src: Path, dst: Path) -> None:
    """置き場（共有フォルダ）へ写して照合する。動画は中身（streamhash）で比べる（入れ物の頭が書き換わることがある）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    shutil.copyfile(src, tmp)
    tmp.replace(dst)
    same = (_streamhash(src) == _streamhash(dst)) if src.suffix == ".mp4" else (_sha256(src) == _sha256(dst))
    if not same:
        raise JobError(f"置いたファイルが元と合いません: {dst}")


def sidecar_of(preview: str | Path) -> Path:
    return Path(preview).with_suffix(".subtitles.json")


def format_compare(diff: list[dict]) -> list[str]:
    from subtitle_engine import review_sheet

    return review_sheet.format_compare(diff)


# --- 実行 ---------------------------------------------------------------------------------


def _summary(key: str, result: dict) -> str:
    kind = key.split(":")[0]
    if kind == "check":
        return (f"空き {result.get('disk_free_gb')} GB・無料枠の残り {result.get('free_calls_left')} 回・"
                f"予算の残り ¥{result.get('budget_left_jpy')}")
    if kind == "fetch":
        return f"{len(result.get('parts') or [])} 本（{result.get('mb')} MB）・md5 一致"
    if kind == "join":
        return f"{result.get('mode')}・{result.get('clock')}・素材の鍵 {result.get('key')}"
    if kind == "edit":
        minutes = round((result.get("duration_sec") or 0) / 60)
        return (f"{result.get('status')}・品質 {result.get('quality')}・AI {result.get('calls')} 回・"
                f"{minutes} 分")
    if kind == "review":
        return f"字幕 {result.get('captions')} 枚・機械の要確認 {result.get('flags')} 枚"
    if kind == "compare":
        return f"違い {result.get('diffs')} か所"
    if kind == "keep":
        return f"{result.get('files')} ファイル（{result.get('mb')} MB）"
    return ""


class Runner:
    """job を1つ、手順どおりに通す。状態は作業場の state.json、見える化は置き場の live/。"""

    def __init__(self, job: dict, *, repo: Path = REPO_ROOT, work: Path | None = None,
                 ledger: Path | None = None, budget: Path | None = None, runs_dir: Path | None = None,
                 coordinator: list[str] | None = None, tiers: dict | None = None,
                 now: Callable[[], dt.datetime] | None = None, poll_sec: float = POLL_SEC,
                 free_bytes: Callable[[Path], int] | None = None):
        self.job = job
        self.repo = Path(repo)
        self.work = Path(work) if work else WORK_ROOT / job["name"]
        self.out = Path(job["out"])
        self.live = self.out / "live"
        self.material = self.work / "material" / job["material"]
        self.ledger = Path(ledger) if ledger else self.repo / ".claude" / "cost_ledger.jsonl"
        self.budget = Path(budget) if budget else self.repo / ".claude" / "budget.json"
        self.runs_dir = Path(runs_dir) if runs_dir else RUNS_DIR
        self.coordinator = coordinator or [sys.executable, "-m", "backend.edit_job", "mainline"]
        self._tiers = tiers
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))
        self.poll_sec = poll_sec
        self.free_bytes = free_bytes or (lambda p: shutil.disk_usage(p).free)
        self.steps = plan_steps(job)
        self.state_path = self.work / "state.json"
        self.state = self._load_state()
        self.progress: dict = {}
        self.handlers: dict[str, Callable[[dict], dict]] = {
            "check": self.step_check, "fetch": self.step_fetch, "join": self.step_join,
            "edit": self.step_edit, "review": self.step_review, "compare": self.step_compare,
            "keep": self.step_keep}

    # --- 状態 ---------------------------------------------------------------------------

    @property
    def tiers(self) -> dict:
        if self._tiers is None:
            self._tiers = load_tiers()
        return self._tiers

    def _load_state(self) -> dict:
        if self.state_path.is_file():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {"job": self.job["name"], "steps": {}}

    def _save_state(self) -> None:
        self.work.mkdir(parents=True, exist_ok=True)
        _write_json(self.state_path, self.state)

    def _event(self, kind: str, **data: Any) -> None:
        self.live.mkdir(parents=True, exist_ok=True)
        with open(self.live / "journal.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": _iso(self.now()), "kind": kind, **data}, ensure_ascii=False) + "\n")

    def _journal(self) -> list[dict]:
        return read_ledger(self.live / "journal.jsonl")

    def result_of(self, key: str) -> dict:
        rec = self.state["steps"].get(key) or {}
        if rec.get("state") != "done":
            raise JobError(f"先に「{key}」を済ませます")
        return rec.get("result") or {}

    def note(self, text: str) -> None:
        """判断の理由を工程ライブに残す（動かしている AI か人が書く）。"""
        self._event("note", text=text)
        self.write_status()

    def write_status(self) -> None:
        """工程ライブの画面が読む status.json を書き直す（全体のいま）。"""
        now = self.now()
        rows = read_ledger(self.ledger)
        since = _parse_at(self.state.get("started_at")) or day_start(now)
        calls = []
        for r in rows:
            t = _parse_at(r.get("at"))
            if not t or t < since:
                continue
            if r.get("kind") == "fallback":
                calls.append({"at": r["at"], "kind": "fallback", "model": r.get("model"),
                              "from": r.get("requested"), "reason": r.get("reason"),
                              "caller": r.get("caller")})
            elif not r.get("kind") and r.get("model"):
                calls.append({"at": r["at"], "kind": "call", "model": r["model"], "caller": r.get("caller")})
        left, detail = free_capacity(rows, now, self.tiers)
        budget, budget_left = active_budget(self.budget, rows)
        steps = [{**s, **(self.state["steps"].get(s["key"]) or {"state": "waiting"})} for s in self.steps]
        states = {s["state"] for s in steps}
        overall = ("running" if "running" in states else "failed" if "failed" in states
                   else "done" if states == {"done"} else "waiting")
        try:
            disk = round(self.free_bytes(_existing(self.work)) / 1024 ** 3, 1)
        except OSError:
            disk = None
        status = {
            "job": {"name": self.job["name"], "label": self.job.get("label", "")},
            "updated_at": _iso(now), "started_at": self.state.get("started_at"),
            "finished_at": self.state.get("finished_at"), "state": overall, "steps": steps,
            "progress": self.progress, "calls": calls,
            "quota": {"day_start": _iso(day_start(now)), "reset_at": _iso(next_reset(now)),
                      "left": left, "tiers": detail},
            "budget": ({"id": budget.get("id"), "limit_jpy": budget.get("limit_jpy"),
                        "left_jpy": round(budget_left, 1)} if budget else None),
            "disk_free_gb": disk,
            "notes": [e for e in self._journal() if e.get("kind") == "note"],
        }
        self.live.mkdir(parents=True, exist_ok=True)
        _write_json(self.live / "status.json", status)

    # --- 通し ---------------------------------------------------------------------------

    def run(self) -> int:
        """頭から通す。済んだ手順は飛ばす（確かめだけは毎回やり直す）。落ちたら記録して 1 を返す。"""
        self.state.setdefault("started_at", _iso(self.now()))
        self.state["finished_at"] = None
        self._save_state()
        self._event("run", text="通しを始めます（済んだ手順は飛ばします）")
        for step in self.steps:
            key = step["key"]
            if (self.state["steps"].get(key) or {}).get("state") == "done" and key != "check":
                continue
            rec = {"state": "running", "started_at": _iso(self.now())}
            self.state["steps"][key] = rec
            self._save_state()
            self._event("start", step=key)
            self.write_status()
            print(f"▶ {step['label']}（{step['place']}）", flush=True)
            try:
                result = self.handlers[key.split(":")[0]](step) or {}
            except Exception as e:  # noqa: BLE001 — 手順の失敗は記録して止める（`run` で続きから）
                rec.update(state="failed", finished_at=_iso(self.now()), error=f"{type(e).__name__}: {e}")
                self.progress = {}
                self._save_state()
                self._event("fail", step=key, error=rec["error"])
                self.write_status()
                print(f"🚫 {step['label']}: {e}", file=sys.stderr, flush=True)
                return 1
            rec.update(state="done", finished_at=_iso(self.now()), result=result,
                       summary=_summary(key, result))
            self.progress = {}
            self._save_state()
            self._event("done", step=key, summary=rec["summary"])
            self.write_status()
            print(f"✓ {step['label']}: {rec['summary']}", flush=True)
        self.state["finished_at"] = _iso(self.now())
        self._save_state()
        self._event("finish", text="通しが終わりました")
        self.write_status()
        return 0

    # --- 確かめ ---------------------------------------------------------------------------

    def check_quota(self, *, cacheless: bool) -> dict:
        now = self.now()
        left, detail = free_capacity(read_ledger(self.ledger), now, self.tiers)
        need = CACHELESS_CALLS if cacheless else CACHED_CALLS
        if left < need:
            reset = next_reset(now).astimezone(JST)
            raise JobError(
                f"今日の無料枠の残りが足りません（残り {left} 回・見込み {need} 回）。"
                f"枠が戻る {reset:%m-%d %H:%M}（日本時間）の後に `run` で続きから進めます")
        return {"free_calls_left": left, "free_calls_needed": need, "tiers": detail}

    def check_budget(self, *, cacheless: bool) -> dict:
        budget, left = active_budget(self.budget, read_ledger(self.ledger))
        need = CACHELESS_JPY if cacheless else CACHED_JPY
        if budget is None:
            raise JobError("有効な予算がありません（.claude/budget.json）。課金経路は予算なしに動かしません")
        if left < need:
            raise JobError(f"予算 {budget.get('id')} の残りが足りません（残り ¥{left:.1f}・見込みの上限 ¥{need:.0f}）")
        return {"budget_id": budget.get("id"), "budget_left_jpy": round(left, 1)}

    def check_disk(self, extra: int = 0) -> float:
        free = self.free_bytes(_existing(self.work))
        if free < MIN_FREE_BYTES + extra:
            raise JobError(f"作業場の空きが足りません（空き {free / 1024 ** 3:.1f} GB・"
                           f"要る {(MIN_FREE_BYTES + extra) / 1024 ** 3:.1f} GB）")
        return round(free / 1024 ** 3, 1)

    def check_runtime_clean(self) -> None:
        """書き出しが書き換えるファイルに、人や別の作業の変更が残っていないか（残っていれば止める）。"""
        proc = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain", "--", *RUNTIME_FILES],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise JobError(f"git で確かめられません: {proc.stderr.strip()[:200]}")
        dirty = [line[3:] for line in proc.stdout.splitlines() if line.strip()]
        if dirty:
            raise JobError("書き出しが書き換えるファイルに変更が残っています（戻すと消えるので止めます）: "
                           + "、".join(dirty))

    def restore_runtime(self) -> list[str]:
        """書き出しが書き換えたファイルを戻す（走らせる前は手つかずだったと確かめてある）。"""
        proc = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain", "--", *RUNTIME_FILES],
                              capture_output=True, text=True)
        changed = [line[3:] for line in proc.stdout.splitlines() if line.strip()]
        if changed:
            subprocess.run(["git", "-C", str(self.repo), "checkout", "--", *changed],
                           capture_output=True, text=True, check=True)
        return changed

    def _cacheless(self) -> bool:
        folder = self.material.parent
        return not (folder.is_dir() and any(folder.glob("_gemini_*")))

    def step_check(self, step: dict) -> dict:
        problems, result = [], {}
        for tool in ("ffmpeg", "ffprobe", "git"):
            if shutil.which(tool) is None:
                problems.append(f"{tool} がありません")
        for v in self.job["versions"]:
            if v.get("review") and not (self.repo / v["review"]).is_file():
                problems.append(f"校正台帳がありません: {v['review']}")
        if self.job.get("approved") and not Path(self.job["approved"]).is_file():
            problems.append(f"物差しの字幕がありません: {self.job['approved']}")
        from backend import cost_guard

        cost_guard.load_env()
        if not os.environ.get("GOOGLE_API_KEY") or cost_guard.is_dummy_key():
            problems.append("GOOGLE_API_KEY が無いか、テスト用のダミーです")
        for check in (self.check_runtime_clean,
                      lambda: result.update(disk_free_gb=self.check_disk()),
                      lambda: result.update(self.check_budget(cacheless=self._cacheless())),
                      lambda: result.update(self.check_quota(cacheless=self._cacheless()))):
            try:
                check()
            except JobError as e:
                problems.append(str(e))
        if problems:
            raise JobError(" ／ ".join(problems))
        result.pop("tiers", None)
        return result

    # --- 取得とつなぎ ----------------------------------------------------------------------

    def step_fetch(self, step: dict) -> dict:
        from backend import raw_source
        from backend.services.google_oauth import read_token_info

        folder_id = os.environ.get(raw_source.FOLDER_ENV, "")
        if not folder_id:
            raise JobError(f"{raw_source.FOLDER_ENV} が未設定です")
        info, _, _ = read_token_info()
        raw_source.check_read_only(info)
        service = raw_source._build_drive()
        folder = (self.job.get("raw") or {}).get("folder")
        source = raw_source.find_folder(service, folder_id, folder) if folder else folder_id
        listed = {f.get("name"): f for f in raw_source.list_videos(service, source)}
        parts = self.job["raw"]["parts"]
        missing = [p for p in parts if p not in listed]
        if missing:
            raise JobError("Drive の raw のフォルダに見つかりません: " + "、".join(missing))
        chosen = [listed[p] for p in parts]
        raw_source.fetch_videos(service, chosen, self.work / "raw")
        size = sum(int(f.get("size") or 0) for f in chosen)
        return {"from": folder or f"raw のフォルダ（ID 末尾 {folder_id[-4:]}）",
                "parts": [{"name": f["name"], "size": int(f.get("size") or 0),
                           "md5": f.get("md5Checksum")} for f in chosen],
                "mb": round(size / 1024 ** 2, 1)}

    def step_join(self, step: dict) -> dict:
        from backend import media_concat
        from subtitle_engine.video_hash import content_digest

        names = list(self.job["raw"]["parts"])
        manifest_file = media_concat.manifest_path(self.material)
        manifest = None
        if self.material.is_file() and manifest_file.is_file():
            saved = json.loads(manifest_file.read_text(encoding="utf-8"))
            if ([p["name"] for p in saved.get("parts") or []] == names
                    and saved.get("size") == self.material.stat().st_size):
                manifest = saved  # 前の通しでつないだ物（同じ並び・同じ大きさ）
        if manifest is None:
            manifest = media_concat.join([self.work / "raw" / n for n in names], self.material)
        seconds = float(manifest["duration"])
        return {"mode": manifest["mode"], "duration": seconds,
                "clock": f"{int(seconds) // 60}:{int(seconds) % 60:02d}",
                "size": manifest["size"], "key": content_digest(self.material)[:8],
                "parts": [{"name": p["name"], "start": p["start"]} for p in manifest["parts"]]}

    # --- 書き出し ---------------------------------------------------------------------------

    def export_command(self, step: dict) -> list[str]:
        version = next(v for v in self.job["versions"] if v["key"] == step["version"])
        command = [*self.coordinator, str(self.material.resolve()), "--transcriber", "gemini"]
        if version.get("review"):
            command += ["--review", version["review"]]
        return command

    def _refresh(self, step: dict, log: Path, since: dt.datetime) -> None:
        run_dir = find_run(self.runs_dir, self.material, since, self.repo)
        run = None
        if run_dir:
            try:
                run = run_view(json.loads((run_dir / "run.json").read_text(encoding="utf-8")))
            except (OSError, ValueError):
                run = None
        self.progress = {"step": step["key"], "line": progress_line(_tail(log)),
                         "journals": chunk_journals(self.material), "log": str(log), "run": run}
        self.write_status()

    def step_edit(self, step: dict) -> dict:
        cacheless = self._cacheless()
        self.check_runtime_clean()
        self.check_disk()
        self.check_budget(cacheless=cacheless)
        quota = self.check_quota(cacheless=cacheless)
        if not self.material.is_file():
            raise JobError(f"素材がありません: {self.material}")
        log = self.work / "logs" / f"{step['version']}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(self.repo / "backend"), str(self.repo)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        env["AVS_RUNS_DIR"] = str(self.runs_dir)
        env["PYTHONUNBUFFERED"] = "1"  # 進み具合の行をすぐログに出す（工程ライブが読む）
        since = self.now() - dt.timedelta(seconds=5)
        self._event("export", step=step["key"], cacheless=cacheless, free_calls_left=quota["free_calls_left"])
        try:
            with open(log, "w", encoding="utf-8") as out:
                proc = subprocess.Popen(self.export_command(step), cwd=self.repo, env=env,
                                        stdout=out, stderr=subprocess.STDOUT)
                while proc.poll() is None:
                    time.sleep(self.poll_sec)
                    self._refresh(step, log, since)
        finally:
            restored = self.restore_runtime()
        self._refresh(step, log, since)
        text = log.read_text(encoding="utf-8", errors="replace")
        result = parse_result(text)
        run = self.progress.get("run")
        if proc.returncode != 0 or not result.get("preview"):
            raise JobError(f"書き出しが終わりませんでした（終了コード {proc.returncode}・状態 {result.get('status')}）。"
                           f"ログ: {log}")
        run_dir = find_run(self.runs_dir, self.material, since, self.repo)
        return {**result, "run_id": run.get("run_id") if run else None,
                "run_dir": str(run_dir) if run_dir else None, "run": run,
                "calls": run.get("calls") if run else None, "cost_jpy": run.get("cost_jpy") if run else None,
                "cacheless": cacheless, "log": str(log), "restored": restored}

    # --- 確認用ファイル・比べる・残す ----------------------------------------------------------

    def step_review(self, step: dict) -> dict:
        from subtitle_engine import aligner, review_sheet
        from subtitle_engine.video_hash import material_cache

        key = step["version"]
        edit = self.result_of(f"edit:{key}")
        preview = Path(edit["preview"])
        local = self.work / "review" / key
        build_review_files(preview, local)
        asr = material_cache(self.material, "_align_rz_")
        version = next(v for v in self.job["versions"] if v["key"] == key)
        sheet = review_sheet.export(json.loads(sidecar_of(preview).read_text(encoding="utf-8")),
                                    f"{self.job['name']}-{key}", version.get("label") or key, "full360.mp4",
                                    aligner.cached_tokens(str(asr)) if asr.is_file() else None)
        (local / "review_captions.json").write_text(
            json.dumps(sheet, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        placed = []
        for name in ("first3.mp4", "full360.mp4", "contact.jpg", "review_captions.json"):
            place(local / name, self.out / key / name)
            placed.append(f"{key}/{name}")
        return {"files": placed, "captions": len(sheet["captions"]), "flags": len(sheet.get("flags") or [])}

    def step_compare(self, step: dict) -> dict:
        from subtitle_engine import review_sheet

        key = step["version"]
        again = sidecar_of(self.result_of(f"edit:{key}")["preview"])
        diff = review_sheet.compare(json.loads(Path(self.job["approved"]).read_text(encoding="utf-8")),
                                    json.loads(again.read_text(encoding="utf-8")))
        dest = self.out / key
        dest.mkdir(parents=True, exist_ok=True)
        _write_json(dest / "compare.json", {"approved": self.job["approved"], "again": str(again), "diff": diff})
        (dest / "compare.txt").write_text("\n".join(format_compare(diff)) + "\n", encoding="utf-8")
        return {"diffs": len(diff), "files": [f"{key}/compare.json", f"{key}/compare.txt"]}

    def step_keep(self, step: dict) -> dict:
        from backend import media_concat

        captions, records = {}, {}
        for v in self.job["versions"]:
            edit = self.result_of(f"edit:{v['key']}")
            captions[v["key"]] = sidecar_of(edit["preview"])
            if edit.get("run_dir"):
                records[f"{v['key']}.run.json"] = Path(edit["run_dir"]) / "run.json"
        records["parts.json"] = media_concat.manifest_path(self.material)
        records["state.json"] = self.state_path
        dest = self.out / "assets"
        files = collect_assets(self.material, dest, captions=captions, records=records)
        review = [{"path": f, "role": "review", "keep": "temp"}
                  for v in self.job["versions"]
                  for f in (self.state["steps"].get(f"review:{v['key']}") or {}).get("result", {}).get("files", [])]
        join = self.result_of("join")
        _write_json(dest / "assets.json", {
            "job": self.job["name"], "label": self.job.get("label", ""), "made_at": _iso(self.now()),
            "material": {"name": self.job["material"], "key": join.get("key"), "size": join.get("size"),
                         "raw": (self.state["steps"].get("fetch") or {}).get("result", {}).get("parts")},
            "keep": {"asset": "作り直しや番組化に使う（Drive の過程資産へ）",
                     "temp": "完成したら消してよい（確認用）"},
            "files": files, "review": review})
        size = sum(f["size"] for f in files)
        return {"files": len(files), "mb": round(size / 1024 ** 2, 1), "path": str(dest)}


def _existing(path: Path) -> Path:
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def _print_status(runner: Runner) -> None:
    print(f"{runner.job.get('label') or runner.job['name']}")
    for step in runner.steps:
        rec = runner.state["steps"].get(step["key"]) or {}
        mark = {"done": "✓", "running": "✱", "failed": "🚫"}.get(rec.get("state"), "○")
        tail = rec.get("summary") or rec.get("error") or ""
        print(f"  {mark} {step['label']}" + (f" — {tail}" if tail else ""))
    print(f"  工程ライブ: {runner.live / 'status.json'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="1本の自動編集を手順どおりに通す（スキル interview-edit）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, text in (("check", "始める前の確かめだけ（AI を呼ばない）"),
                       ("run", "頭から通す。済んだ手順は飛ばす（**課金経路**・無料枠の段）"),
                       ("status", "いまどこまで進んだか")):
        sub.add_parser(name, help=text).add_argument("job")
    note = sub.add_parser("note", help="工程ライブに判断を書き足す")
    note.add_argument("job")
    note.add_argument("text")
    mainline = sub.add_parser("mainline", help="本線を進み具合つきで動かす（run が使う。引数は本線と同じ）")
    mainline.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.cmd == "mainline":
        return run_mainline(args.args)
    try:
        runner = Runner(load_job(job_path(args.job)))
    except JobError as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 2
    if args.cmd == "run":
        return runner.run()
    if args.cmd == "note":
        runner.note(args.text)
        return 0
    if args.cmd == "status":
        _print_status(runner)
        return 0
    try:
        result = runner.step_check({"key": "check"})
    except JobError as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    print(f"✓ 始められます: {_summary('check', result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
