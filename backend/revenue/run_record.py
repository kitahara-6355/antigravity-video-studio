"""実行記録の書き手（R1）。**成果物ゲートが読む run.json を書く。**

`artifact_gate` は `output/runs/<run_id>/run.json` を読んで
「動いたか・どこで落ちたか・どのモデルで出たか」を判定する。
**その run.json を書くものが無かった**ので、ここで書く。

## 設計の3点

1. **工程ごとに書き出す。** 最後にまとめて書くと、いちばん知りたい
   「途中で落ちた実行」の記録が残らない。書き込みは原子的に置き換える
2. **モデルは宣言と実測の両方を残す。** 宣言（`model_policy` の段）だけでは
   `model_governance` のフォールバックで別のモデルに落ちたことが見えない。
   実測は `cost_guard` の台帳から、工程の開始時点の末尾以降を読む
3. **例外は握り潰さない。** 記録は残すが、そのまま送出する

## 使い方

    rec = RunRecorder(inputs={"source": "vault/raw/a.mp4"})
    with rec.stage("transcribe", model="local:whisper"):
        ...
    with rec.stage("script", task="script_generation", stage_input={...}):
        ...
        rec.artifact("output/final/demo.mp4")
    rec.finish()

    python -m backend.revenue.run_record --list
    python -m backend.revenue.run_record --resume <run_id>
"""
from __future__ import annotations

import argparse
import itertools
import hashlib
import json
import logging
import os
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from backend import cost_guard, model_policy
from backend.revenue.artifact_gate import RUNS_DIR

logger = logging.getLogger(__name__)

_SEQ = itertools.count()

# 台帳に出ないローカル処理は、この接頭辞で宣言する（ffmpeg・Whisper など）。
# **「モデルを使っていない」ことも宣言事項**にしておく。宣言し忘れと
# 区別がつかないと、見える化が抜けていても気づけない。
LOCAL_PREFIX = "local:"

# JSON にできなかった値に付ける印。**再開の可否をここで判定する。**
UNSERIALIZABLE_MARK = "<記録できない値:"


def _sha256(path: str | Path) -> str | None:
    """成果物の指紋。**読めなければ `None`。**

    「確かめられなかった」を「一致した」にしない。
    """
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unserializable(value: Any) -> str:
    """JSON にできない値の置き換え。**記録全体を落とさない。**

    2026-08-19 の実走で `TranscriptResult` が工程の入力に混ざり、
    `json.dump` が TypeError を上げて **transcribe 以降の書き出しが
    すべて失敗した。** 10/10 完走した実行の記録が「4工程・running」で
    残り、完走したことも、どこまで進んだかも読めなくなった。

    **黙って消さない。** 何が入っていたのかは残す（再開の手掛かりになる）。

    印を決め打ちにしてあるのは、**再開のときに「この値は復元できない」と
    機械的に判定する**ため。型名だけだと本物の文字列と区別がつかない。
    """
    text = repr(value)
    if len(text) > 200:
        text = text[:197] + "..."
    return f"{UNSERIALIZABLE_MARK} {type(value).__name__} {text}>"


def is_unserializable(value: Any) -> bool:
    """記録できずに印だけ残った値か。**再開の可否を分ける。**"""
    return isinstance(value, str) and value.startswith(UNSERIALIZABLE_MARK)


def new_run_id() -> str:
    """時刻順に並ぶ一意な ID。同じマイクロ秒でも衝突しない。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return f"{stamp}-{next(_SEQ):04d}"


def load_run(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def failed_stage(run: dict) -> dict | None:
    """**どこから再開すればいいか。** 落ちた工程を返す（無ければ None）。"""
    for stage in run.get("stages") or []:
        if stage.get("status") == "failed":
            return stage
    return None


class RunRecorder:
    """1回の実行を記録する。**工程が終わるたびに書き出す。**"""

    def __init__(self, run_id: str | None = None,
                 runs_dir: Path = RUNS_DIR,
                 ledger_path: Path | None = None,
                 inputs: dict | None = None):
        self.run_id = run_id or new_run_id()
        self.dir = Path(runs_dir) / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = Path(
            ledger_path if ledger_path is not None else cost_guard.LEDGER_PATH)
        # **明示的に渡されたときだけ台帳へ要約を書く。**
        # 台帳は「工程ごとの原価」を引くために常に読むが、書くのは別。
        # 既定で書くと、`runs_dir` だけ差し替えたテストが本番の
        # `.claude/cost_ledger.jsonl` を汚す（実際に 40 行混ざった）。
        self._summary_to_ledger = ledger_path is not None
        self._started = time.monotonic()
        self._ledger_start = self._ledger_offset()
        self._record: dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": _now(),
            "finished_at": "",
            "status": "running",
            "inputs": inputs or {},
            "stages": [],
            "models_used": [],
            "artifacts": [],
            "artifact_digests": {},
            "duration_sec": 0.0,
            "cost_jpy": 0.0,
            "calls": 0,
        }
        self._write()

    @property
    def path(self) -> Path:
        return self.dir / "run.json"

    # --- 台帳（実測） -------------------------------------------------------

    def _ledger_offset(self) -> int:
        try:
            return self.ledger_path.stat().st_size
        except OSError:
            return 0

    def _ledger_rows(self, offset: int) -> list[dict]:
        """`offset` バイト以降に追記された行を読む。

        **読めなかった行は捨てる**（記録の書き出しが実行を落とさないため）。
        捨てた事実は `calls` の食い違いとして台帳側に残る。
        """
        try:
            with open(self.ledger_path, encoding="utf-8") as fh:
                fh.seek(offset)
                raw = fh.read()
        except OSError:
            return []
        rows = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _calls_since(self, offset: int) -> list[dict]:
        """`offset` 以降の**課金の行だけ**を返す。

        要約の行（`kind == "run_summary"`）は呼び出しではない。数えると
        「呼び出していないのに呼び出したことになる」。除外はここ1箇所。
        """
        return [r for r in self._ledger_rows(offset)
                if r.get("kind") != "run_summary"]

    # --- 工程 ---------------------------------------------------------------

    @contextmanager
    def stage(self, name: str, task: str | None = None,
              model: str | None = None,
              stage_input: dict | None = None) -> Iterator[dict]:
        """1工程を記録する。

        Args:
            name: 工程名（再開時にここを指す）
            task: `model_policy` の工程名。渡すと段からモデルを引く
            model: モデルを直接宣言する。ローカル処理は `local:ffmpeg` の形
            stage_input: **再開に要る入力。** 失敗時にこれが無いと再開できない
        """
        entry: dict[str, Any] = {
            "name": name,
            "status": "running",
            "started_at": _now(),
            "model": "",
            "tier": "",
            "model_source": "",
            "models_observed": [],
            "model_mismatch": False,
            "calls": 0,
            "cost_jpy": 0.0,
            "duration_sec": 0.0,
        }
        if stage_input is not None:
            entry["input"] = stage_input
        if model:
            entry["model"] = model
            entry["model_source"] = "declared"
        elif task:
            # **段から引く。** モデル名の直書きは入替のたびに全工程を触ることに
            # なり、実際それで `gemini-3-flash-preview` が居座って腐った。
            decision = model_policy.resolve(task)
            entry.update(model=decision.model, tier=decision.tier,
                         model_source=decision.source, task=task)
        # task も model も無ければ `model` は空のまま残す。
        # **宣言し忘れを緑にしない** — 成果物ゲートが FAIL する。

        self._record["stages"].append(entry)
        offset = self._ledger_offset()
        started = time.monotonic()
        self._write()
        try:
            yield entry
        except BaseException as exc:
            entry["status"] = "failed"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["traceback"] = traceback.format_exc()
            self._close_stage(entry, offset, started)
            raise
        entry["status"] = "success"
        self._close_stage(entry, offset, started)

    def _close_stage(self, entry: dict, offset: int, started: float) -> None:
        rows = self._calls_since(offset)
        observed = sorted({r.get("model", "") for r in rows if r.get("model")})
        entry["models_observed"] = observed
        entry["calls"] = len(rows)
        entry["cost_jpy"] = round(sum(float(r.get("jpy") or 0) for r in rows), 4)
        entry["finished_at"] = _now()
        entry["duration_sec"] = round(time.monotonic() - started, 3)
        declared = entry.get("model")
        if not declared and observed:
            # 宣言が無くても、実際に呼ばれたものは分かる。**それを記録する。**
            entry["model"] = observed[0]
            entry["model_source"] = "observed"
        # 宣言と実測の食い違いは**黙って上書きしない**。フォールバックで
        # 別の段に落ちたことが、ここでだけ見える。
        entry["model_mismatch"] = bool(
            observed and declared and observed != [declared])
        # **宣言しただけで一度も動いていないモデルに印を付ける。**
        # 2026-08-20 の実走で 503 を踏み、soul_feedback は2回再試行して
        # 諦め、スタブにフォールバックして success を返した。記録には
        # `model: gemini-3.7-flash` が残り、読み手は「提案はこのモデルが
        # 出した」と読む。**誰も出していない。** `local:` は台帳に出ない
        # のが正常なので対象外。
        entry["model_unverified"] = bool(
            declared and not declared.startswith(LOCAL_PREFIX)
            and not observed)
        self._write()

    # --- 成果物 -------------------------------------------------------------

    def artifact(self, path: str | Path) -> None:
        value = str(path)
        if value not in self._record["artifacts"]:
            self._record["artifacts"].append(value)
        # **成果物の指紋を残す**（R1.5-C3）。AI を効かせた場合と効かせない場合で
        # 成果物が違うことを、あとから機械で確かめられるようにする。
        # 実測（2026-08-27）: 同じ入力で走らせた実走どうしは最終 mp4 の
        # SHA256 が完全一致する（エンコーダは決定的）。**リポジトリ内の
        # 記録で裏が取れるのは `20260827T133041787764` と
        # `20260827T135054796267` の組**（final / preview とも一致）。
        # だから AI あり／なしの差は **AI に起因すると言い切れる。**
        self._record.setdefault("artifact_digests", {})[value] = _sha256(value)
        self._write()

    def intermediates(self, rows: list) -> None:
        """**中間成果物が下流で使われたか**（R1.5-C3）。

        作られたのに誰にも読まれていないものを、あとから件数で出せるようにする。
        """
        self._record["intermediates"] = list(rows)
        self._write()

    # --- 締め ---------------------------------------------------------------

    def finish(self, status: str | None = None,
               health: dict | None = None) -> dict:
        # **要約の行は呼び出しではない。** `_close_stage` では除外していたのに
        # ここだけ除外し忘れていた（2026-08-21 の指摘）。除外を1箇所に寄せる。
        rows = self._calls_since(self._ledger_start)
        used: set[str] = set()
        for stage in self._record["stages"]:
            if stage.get("model"):
                used.add(stage["model"])
            used.update(stage.get("models_observed") or [])
        self._record["models_used"] = sorted(used)
        self._record["calls"] = len(rows)
        self._record["cost_jpy"] = round(
            sum(float(r.get("jpy") or 0) for r in rows), 4)
        self._record["duration_sec"] = round(time.monotonic() - self._started, 3)
        self._record["finished_at"] = _now()
        self._record["status"] = status or (
            "failed" if failed_stage(self._record) else "completed")
        # **「何が落ちたか」を記録に残す**（R1.5-C1b）。状態の一言だけでは
        # 記録から追えない。
        if health is not None:
            self._record["health"] = health
        self._write()
        if self._summary_to_ledger:
            self._append_ledger_summary()
        return self._record

    def _append_ledger_summary(self) -> None:
        """**1本ぶんの所要時間と原価を台帳に1行だけ残す。**

        所要時間は run.json にはあったが、R1-C2 が名指ししている
        `.claude/cost_ledger.jsonl` には無く、しかも台帳の行に run_id が
        無いので**「1本あたり」に切り出せなかった**（2026-08-21 の指摘）。

        `jpy` は持たせない。呼び出しの行と足し合わせると二重計上になり、
        `reconcile_ledger` が budget.json に倍の額を書く。実額は
        `cost_jpy` に別名で持つ。

        **書けなくても実行記録は捨てない**（要約は付帯物）。
        """
        row = {
            "at": _now(),
            "kind": "run_summary",
            "run_id": self.run_id,
            "status": self._record["status"],
            "duration_sec": self._record["duration_sec"],
            "calls": self._record["calls"],
            "cost_jpy": self._record["cost_jpy"],
            "models_used": self._record["models_used"],
        }
        try:
            from backend.cost_guard import load_active_budget
            budget = load_active_budget()
            if budget:
                row["budget_id"] = budget.get("id", "")
        except Exception as e:  # noqa: BLE001 — 要約は付帯物
            logger.debug("予算 ID を引けませんでした: %s", e)
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ledger_path, "a", encoding="utf-8",
                      newline="\n") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("台帳に要約を書けませんでした: %s", e)

    def _write(self) -> None:
        """**壊れた JSON を置かない。** 一時ファイルに書いてから置き換える。"""
        tmp = self.dir / "run.json.tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self._record, fh, ensure_ascii=False, indent=2,
                      default=_unserializable)
            fh.write("\n")
        os.replace(tmp, self.path)


# --- CLI ----------------------------------------------------------------------


def _format_list(runs_dir: Path) -> str:
    from backend.revenue.artifact_gate import load_runs

    runs = load_runs(runs_dir)
    if not runs:
        return f"実行記録がありません（{runs_dir}）"
    lines = [f"実行記録 {len(runs)} 件", ""]
    for run in runs:
        mark = {"completed": "✅", "failed": "🚫"}.get(run.get("status"), "…")
        lines.append(
            f"  {mark} {run.get('run_id')}  "
            f"{len(run.get('stages') or [])} 工程 / "
            f"{run.get('duration_sec', 0)} 秒 / "
            f"{run.get('cost_jpy', 0)} 円 / "
            f"{', '.join(run.get('models_used') or []) or '(モデル記録なし)'}")
    return "\n".join(lines)


def _再実行の案内(run: dict) -> list[str]:
    """**記録を書いたパイプラインの入口を案内する**（R1.5-C1d）。

    旧実装の `--resume` を決め打ちで出していたが、本線（agents）の記録に
    対しては**工程名の体系が違うので実際には再開できない**案内だった。

    **本線に再開は無い。** 無いものを案内しないで、やり直しの入口を出す
    （偽の success を返さないのと同じ理由）。
    """
    if (run.get("inputs") or {}).get("mainline") == "agents":
        video = (run.get("inputs") or {}).get("video_path") or "<入力の動画>"
        return [
            "    # 本線（agents）に再開はありません。入力からやり直します",
            "    PYTHONPATH=./backend python -m backend.agents"
            f".pipeline_coordinator {video}",
        ]
    return ["    python -m backend.video_pipeline.pipeline_coordinator "
            f"--resume {run['run_id']}"]


def _format_resume(runs_dir: Path, run_id: str) -> tuple[str, int]:
    path = Path(runs_dir) / run_id / "run.json"
    if not path.is_file():
        return f"🚫 実行記録がありません: {path}", 1
    try:
        run = load_run(path)
    except (OSError, ValueError) as e:
        return f"🚫 実行記録を読めません: {path}（{e}）", 1
    stage = failed_stage(run)
    if stage is None:
        return f"✅ {run_id} に失敗した工程はありません（status={run.get('status')}）", 0
    done = [s["name"] for s in run["stages"] if s.get("status") == "success"]
    lines = [
        f"🚫 {run_id} は工程 '{stage.get('name')}' で失敗しています", "",
        f"  原因: {stage.get('error') or '(記録なし)'}",
        f"  モデル: {stage.get('model') or '(記録なし)'}"
        f"（実測: {', '.join(stage.get('models_observed') or []) or 'なし'}）",
        f"  完了済み: {', '.join(done) or 'なし'}", "",
        "  再開に使う入力:",
        json.dumps(stage.get("input", {}), ensure_ascii=False, indent=4),
        "",
        "  ここから再実行する:",
        *_再実行の案内(run),
    ]
    return "\n".join(lines), 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="実行記録（R1）")
    parser.add_argument("--list", action="store_true", help="実行記録の一覧")
    parser.add_argument("--resume", metavar="RUN_ID",
                        help="この実行のどこから再開すればいいかを出す")
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args(argv)

    if args.resume:
        text, code = _format_resume(args.runs_dir, args.resume)
        print(text)
        return code
    print(_format_list(args.runs_dir))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
