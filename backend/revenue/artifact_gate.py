"""成果物ゲート（R1）。**「動いた」を成果物で判定する。**

P1〜P5 のゲートは「ソースがこう書かれている」を判定していた。上限は
`scoring_policy` の 50% で、**動くことの証拠にはならない**。ここは逆で、
**実際に出てきた物**（mp4・実行記録・実費）だけを見る。

## 判定するもの

1. **動画が本物か** — ffprobe で尺・映像トラック・音声トラックを見る。
   拡張子やファイルサイズでは判定しない（`.png` の中身が JPEG だった前例）
2. **実行の記録があるか** — どの工程が動き、どのモデルを使い、どこで失敗し、
   そこから再開できるか
3. **実費が measured か** — 台帳に残り、単価不明・未計測の件数まで見える

## 確かめないこと

- **良い動画かどうか。** 尺と音声トラックの有無しか見ない
- **収益化に適格か。** 量産型判定は R2、視聴実績は R3 の担当
- **再現性。** 1本通ったことは、次も通ることを意味しない

## fail-closed

`ffprobe` が無い環境では**判定できないので FAIL にする**。
「確かめられなかった」を緑にすると、ゲートが存在しないのと同じになる。

    python -m backend.revenue.artifact_gate --video output/final/x.mp4
    python -m backend.revenue.artifact_gate --gate
    python -m backend.revenue.artifact_gate --resume-check
    python -m backend.revenue.artifact_gate --semantics
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "output" / "runs"

# 動画として認める最低条件。**ここを緩めるとゲートが意味を失う。**
MIN_DURATION_SEC = 1.0

ARTIFACT_SEMANTICS = {
    "確かめること": [
        ("**成果物の mp4 が本物であること** — ffprobe が読め、尺が1秒以上あり、"
         "映像トラックと音声トラックの**両方**がある"),
        "**実行の記録があること** — run.json に工程・使ったモデル・成果物のパスが残る",
        ("**失敗した工程が特定でき、そこから再開できること**"
         "（工程名・原因・入力が残っている）"),
        ("**実費が計測されていること** — cost_ledger に1行1呼び出しで残り、"
         "単価不明・未計測の件数が出る"),
        ("**工程ごとに、どのモデルで動いたかが残ること**"
         "（見える化。不満があったときに上げる先を決めるために要る。"
         "実行全体の `models_used` だけでは足りない）"),
        "**使ったモデル名が残ること**（2026-10-16 に終了する 2.5 系への依存を見るため）",
    ],
    "確かめないこと": [
        ("**良い動画かどうか。** 尺と音声トラックの有無しか見ていない。"
         "内容・画質・音量・テロップの正しさは判定しない"),
        "**収益化に適格かどうか。** 量産型判定は R2、視聴実績は R3 の担当",
        "**再現性。** 1本通ったことは次も通ることを意味しない",
        "**原価の代表性。** 実測は1本ぶんで、テーマや尺が変われば変わる",
        "**動画が実際に投稿されたか**（R3 の担当）",
    ],
    "判定の性質": "成果物だけを見る。ソースの書かれ方は一切見ない。"
                  "ffprobe が無ければ『確かめられない』ので FAIL にする（fail-closed）",
}


@dataclass
class Finding:
    kind: str
    what: str
    why: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.what}\n      — {self.why}"


@dataclass
class ArtifactReport:
    findings: list[Finding] = field(default_factory=list)
    video: dict | None = None
    runs: list[dict] = field(default_factory=list)
    # **過去の実行にあった欠陥。判定はしない**（直せないので）。
    # 黙って消すと「前も同じ所で駄目だった」が見えなくなるので残す。
    history: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


# --- 動画 ---------------------------------------------------------------------


def probe(path: Path) -> tuple[dict | None, Finding | None]:
    """ffprobe で中身を見る。**読めなければ FAIL**（無いことを緑にしない）。"""
    if shutil.which("ffprobe") is None:
        return None, Finding(
            "no_prober", "ffprobe",
            "ffprobe がないので動画の中身を確かめられません。"
            "**確かめられないことを緑にしない**（判定できる環境で実行してください）")
    if not path.is_file():
        return None, Finding("missing", str(path), "動画ファイルがありません")
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=120, check=True).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return None, Finding("unreadable", str(path),
                             f"ffprobe が読めませんでした: {e}")
    try:
        return json.loads(out), None
    except json.JSONDecodeError as e:
        return None, Finding("unreadable", str(path), f"ffprobe の出力が壊れています: {e}")


def check_video(path: Path) -> tuple[dict | None, list[Finding]]:
    """**再生可能な動画であること。** 拡張子でもサイズでも判定しない。"""
    info, failure = probe(path)
    if failure is not None:
        return None, [failure]
    streams = info.get("streams") or []
    kinds = [s.get("codec_type") for s in streams]
    duration = float((info.get("format") or {}).get("duration") or 0)
    findings: list[Finding] = []
    if duration < MIN_DURATION_SEC:
        findings.append(Finding(
            "too_short", str(path),
            f"尺が {duration:.2f} 秒しかありません（{MIN_DURATION_SEC} 秒未満は"
            "完走とみなしません）"))
    if "video" not in kinds:
        findings.append(Finding("no_video_stream", str(path),
                                "映像トラックがありません"))
    if "audio" not in kinds:
        findings.append(Finding(
            "no_audio_stream", str(path),
            "音声トラックがありません（無音の動画は完走とみなしません）"))
    summary = {
        "path": str(path),
        "duration_sec": round(duration, 2),
        "streams": kinds,
        "size_bytes": path.stat().st_size,
    }
    return summary, findings


# --- 実行記録 -----------------------------------------------------------------

REQUIRED_RUN_KEYS = ("run_id", "started_at", "stages", "models_used")

# **緑と呼べる状態はこの2つだけ**（R1.5-C1c）。
# `degraded` を落とさないのは 2026-08-27 のユーザー決定 — 動画は出来ている。
# ここに無いもの（`failed` / `error` / 途中で死んで `running` のまま / 見知らぬ値）は
# すべて赤に倒す。**「確かめられなかった」を「問題なし」にしない。**
GREEN_RUN_STATUSES = ("completed", "degraded")


def load_runs(runs_dir: Path = RUNS_DIR) -> list[dict]:
    if not runs_dir.is_dir():
        return []
    runs = []
    for path in sorted(runs_dir.glob("*/run.json")):
        try:
            runs.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            runs.append({"run_id": path.parent.name, "_broken": True})
    return runs


def check_runs(runs: list[dict]) -> list[Finding]:
    """実行記録が**再開できるだけの情報**を持っているか。

    **見るのは最新の1本。** 過去の記録は書庫であって、直せない。
    「2026-08-26 のあの実行は宣言だけで API を呼んでいなかった」は
    **その日の事実**で、あとから実装を直しても消えない。全件を判定対象に
    すると、一度でも駄目な実行をするとゲートが**永久に落ち続ける**。
    それでは「いまパイプラインが動くか」を答えられない。

    過去のぶんは `history_findings()` が別枠で出す（判定はしない）。
    """
    findings: list[Finding] = []
    if not runs:
        findings.append(Finding(
            "no_run", str(RUNS_DIR),
            "実行の記録が1件もありません。**0件を緑にしない** — "
            "記録が無ければ、動いたかどうかも、どこで落ちたかも分かりません"))
        return findings
    for run in [runs[-1]]:
        rid = run.get("run_id", "(不明)")
        if run.get("_broken"):
            findings.append(Finding("broken_run", rid, "run.json が壊れています"))
            continue
        missing = [k for k in REQUIRED_RUN_KEYS if k not in run]
        if missing:
            findings.append(Finding(
                "incomplete_run", rid,
                f"実行記録に必要な項目がありません: {', '.join(missing)}"))
            continue
        for stage in run.get("stages") or []:
            # **見える化はここで担保する（ユーザー要件・2026-08-15）。**
            # 「どの結果がどのモデルで出たか」が残っていなければ、不満が
            # あっても**どこを上げればいいか分からない**。記録が無いことを
            # 緑にしない。
            if not stage.get("model"):
                findings.append(Finding(
                    "model_not_recorded",
                    f"{rid} / {stage.get('name', '(名前なし)')}",
                    "この工程が**どのモデルで動いたか**が記録されていません。"
                    "結果に不満があったときに上げる先を決められません"
                    "（`python -m backend.model_policy --why <工程>`）"))
            # **宣言だけで一度も動いていないモデルを緑にしない。**
            # 記録が「gemini-3.7-flash」でも、API が1回も成功していなければ
            # 結果を出したのはスタブ。見える化が嘘になる。
            if stage.get("model_unverified"):
                findings.append(Finding(
                    "model_unverified",
                    f"{rid} / {stage.get('name', '(名前なし)')}",
                    f"記録上のモデルは **{stage.get('model')}** ですが、"
                    "**API 呼び出しが1回も成功していません**"
                    "（台帳に実測がない）。結果を出したのは"
                    "スタブか既定値である可能性があります"))
            if stage.get("status") != "failed":
                continue
            # **失敗を記録するだけでは足りない。** 再開できる情報が要る。
            lacking = [k for k in ("name", "error", "input") if not stage.get(k)]
            if lacking:
                findings.append(Finding(
                    "not_resumable", f"{rid} / {stage.get('name', '(名前なし)')}",
                    f"失敗した工程から再開できません（欠けている: "
                    f"{', '.join(lacking)}）"))
    return findings


def check_run_status(runs: list[dict]) -> list[Finding]:
    """**赤い実走を緑にしない**（R1.5-C1c）。見るのは最新の1本。

    これが無かったので、**きちんと書式の整った全滅の記録**に対して
    `--gate` が exit 0 を返した。「ゲートが PASS すること」を終了条件に
    すると、**ゲートを弱くするのが最短の達成手段**になる。

    `check_runs` と分けてあるのは `--resume-check` のため。あちらは
    **落ちた実行から再開できるか**を見る道具で、落ちていること自体は
    違反ではない。ここは逆に、落ちた実行を成果物の証拠にしないための検査。
    """
    if not runs:
        return []
    run = runs[-1]
    if run.get("_broken"):
        return []          # 壊れた記録は `check_runs` が既に落としている
    rid = run.get("run_id", "(不明)")
    status = run.get("status")
    if not status:
        return [Finding(
            "run_status_missing", rid,
            "実行の状態が記録されていません。**動いたかどうかを判定できない**"
            "ので緑にはしません")]
    if status not in GREEN_RUN_STATUSES:
        return [Finding(
            "run_failed", rid,
            f"最新の実走が **{status}** で終わっています。"
            "**動かなかった実行を成果物の証拠にしない**"
            f"（緑と呼べるのは {'、'.join(GREEN_RUN_STATUSES)} だけ）")]
    return []


def history_findings(runs: list[dict]) -> list[Finding]:
    """**過去の実行にあった欠陥。判定材料にはしない。**

    最新より前の記録は書庫で、あとから直せない。判定に混ぜると一度の失敗で
    永久に落ちる。**ただし黙って捨てない** — 同じ所で繰り返し駄目になって
    いるなら、それは次を疑う手がかりになる。
    """
    out: list[Finding] = []
    for run in runs[:-1]:
        out += check_runs([run])
    return out


def check_cost(runs: list[dict]) -> list[Finding]:
    """実費が計測されているか。**「無料だった」を疑う。**"""
    from backend import cost_guard

    findings: list[Finding] = []
    ledger = cost_guard.LEDGER_PATH
    if not ledger.is_file():
        findings.append(Finding(
            "no_cost_ledger", str(ledger),
            "実費の台帳がありません。1本あたりの原価が分からないと、"
            "必要本数を掛けた総額も見積もれません"))
        return findings
    rows = [json.loads(line) for line in
            ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    # **1本ぶんの要約は課金の行ではない。** metered / known_price を持たない
    # ので、数に入れると「トークンを読めなかった呼び出し」として誤検知する
    # （実際に 40 / 47 件と出た）。
    rows = [r for r in rows if r.get("kind") != "run_summary"]
    if not rows:
        findings.append(Finding("no_cost_ledger", str(ledger),
                                "台帳が空です（1回も課金経路を通っていません）"))
        return findings
    unmetered = [r for r in rows if not r.get("metered")]
    if unmetered:
        findings.append(Finding(
            "unmetered_calls", f"{len(unmetered)} / {len(rows)} 件",
            "トークンを読めなかった呼び出しがあります。**無料ではなく不明**なので、"
            "実費はここに出ている額より大きい可能性があります"))
    unknown = [r for r in rows if not r.get("known_price")]
    if unknown:
        findings.append(Finding(
            "unknown_price_models", f"{len(unknown)} 件",
            "単価が未登録のモデルが使われています（最高単価で見積もっています）。"
            "backend/config/gemini_pricing.json に足してください"))
    return findings


def check_models(runs: list[dict]) -> list[Finding]:
    """**2026-10-16 に終了する 2.5 系への依存**を見えるようにする。"""
    used = {m for run in runs for m in (run.get("models_used") or [])}
    if not used:
        return [Finding("no_models_recorded", "models_used",
                        "使ったモデルが記録されていません（2.5 系の終了に"
                        "備えるには、実走で何を使ったかが要ります）")]
    return []


# --- 実行 ---------------------------------------------------------------------


def run_gate(video: Path | None = None,
             runs_dir: Path = RUNS_DIR) -> ArtifactReport:
    report = ArtifactReport()
    report.runs = load_runs(runs_dir)
    report.findings += check_runs(report.runs)
    report.findings += check_run_status(report.runs)
    report.history = history_findings(report.runs)
    report.findings += check_cost(report.runs)
    report.findings += check_models(report.runs)
    if video is not None:
        summary, findings = check_video(video)
        report.video = summary
        report.findings += findings
    else:
        # **最新の1本の成果物だけを見る**（R1.5-C1c）。全 run から集めていた
        # ので、**1本前の実走が残した mp4 が永久に緑を作っていた** —
        # 今日の実行が動画を1本も作らなくてもゲートが通った。
        latest = report.runs[-1] if report.runs else {}
        produced = [Path(p) for p in (latest.get("artifacts") or [])
                    if str(p).endswith(".mp4")]
        if not produced:
            report.findings.append(Finding(
                "no_video", "artifacts",
                "完成した mp4 が実行記録にありません。**R1 の終了条件は"
                "『再生可能な動画が1本ある』こと**で、それ以外では代替できません"))
        for path in produced:
            summary, findings = check_video(
                path if path.is_absolute() else REPO_ROOT / path)
            report.video = summary or report.video
            report.findings += findings
    return report


def _format(report: ArtifactReport) -> str:
    lines = ["成果物ゲート（R1）— 動いた証拠だけを見る", ""]
    lines.append(f"  実行記録: {len(report.runs)} 件")
    if report.runs:
        latest = report.runs[-1]
        lines.append(f"  最新の実走: {latest.get('run_id', '(id なし)')} / "
                     f"{latest.get('status') or '(状態の記録なし)'}")
    if report.video:
        v = report.video
        lines.append(f"  動画: {v['path']} / {v['duration_sec']} 秒 / "
                     f"{'+'.join(v['streams'])} / {v['size_bytes']:,} bytes")
    lines.append("")
    if report.ok:
        lines.append("  ✅ 成果物を確認しました"
                     "（--semantics に確かめていないことを列挙してあります）")
    else:
        for finding in report.findings:
            lines.append(f"    {finding}")
    if report.history:
        kinds = ", ".join(sorted({f.kind for f in report.history}))
        lines.append("")
        lines.append(f"  ℹ 過去の実行に {len(report.history)} 件の欠陥があります"
                     f"（{kinds}）。**判定には使っていません** — "
                     "直せない過去で永久に落ちないよう、判定は最新の1本で行います")
    return "\n".join(lines)


def _format_semantics() -> str:
    lines = ["成果物ゲート — 確かめること／確かめないこと", ""]
    for label in ("確かめること", "確かめないこと"):
        lines.append(f"  {label}:")
        lines += [f"    - {item}" for item in ARTIFACT_SEMANTICS[label]]
        lines.append("")
    lines.append(f"  判定の性質: {ARTIFACT_SEMANTICS['判定の性質']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="成果物ゲート（R1）")
    parser.add_argument("--video", type=Path, help="この mp4 を検査する")
    parser.add_argument("--gate", action="store_true",
                        help="成果物が揃っていなければ exit 1")
    parser.add_argument("--resume-check", action="store_true",
                        help="失敗した工程から再開できるかだけを見る")
    parser.add_argument("--semantics", action="store_true")
    args = parser.parse_args(argv)

    if args.semantics:
        print(_format_semantics())
        return 0

    if args.resume_check:
        runs = load_runs()
        findings = check_runs(runs)
        if findings:
            print(f"🚫 再開できない実行記録があります（{len(findings)} 件）")
            for f in findings:
                print(f"    {f}")
            return 1
        # **不在を成功にしない。** 失敗が1件も無い記録に対して
        # 「再開できます」と言うと、確かめていないことを確かめたと
        # 報告することになる。件数を出して区別する。
        #
        # **数えるのは検査した範囲だけ。** `check_runs` は最新の1本しか見ないので、
        # 全件ぶんの件数を出すと「6件ぜんぶ再開できます」と読める嘘になる
        # （2026-08-26 に gate-verifier の指摘で判明）。
        検査した = runs[-1:]
        failed = sum(1 for r in 検査した for s in (r.get("stages") or [])
                     if s.get("status") == "failed")
        置き去り = len(runs) - len(検査した)
        あと = f"（過去 {置き去り} 件は検査していません）" if 置き去り else ""
        if failed:
            print(f"✅ 最新の実行記録 {検査した[0].get('run_id', '(id なし)')} / "
                  f"失敗した工程 {failed} 件。"
                  f"いずれも工程名・原因・入力が残っており再開できます{あと}。")
        else:
            print(f"✅ 最新の実行記録 {検査した[0].get('run_id', '(id なし)')}。"
                  "**失敗した工程はありません**"
                  f"（再開できるかどうかはこの記録では確かめられません）{あと}。")
        return 0

    report = run_gate(args.video)
    print(_format(report))
    return 1 if (args.gate or args.video) and not report.ok else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
