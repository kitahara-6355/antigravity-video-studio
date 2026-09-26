"""承認工程（R2）— 承認していない動画は書き出せない。

設計 `docs/specs/2026-09-19-r2-approval-design.md`。

本線（agents の coordinator）は書き出さずに**提案**を残し、`awaiting_approval` で止まる。
人がプレビューを見て承認し、承認があるときだけ書き出す。

    python -m backend.agents.pipeline_coordinator <素材>   # 提案で止まる
    （人がプレビューを見る。直すなら working/ の YouTube メタデータを直す）

置き場は実行記録と同じ `output/runs/<run_id>/`:

- `proposal.json` — 承認と書き出しに要るもの（プレビュー・品質・書き出しのモード・AI の出力・使ったモデル）
- `proposal/` — AI の出力の写し（**人が直す前の姿**）
- `working/` — 人が直す現物。承認のときに `proposal/` との差分を取る
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROPOSAL = "proposal.json"
APPROVAL = "approval.json"
APPROVAL_HISTORY = "approval_history"
EXPORT = "export.json"
PROPOSAL_DIR = "proposal"
WORKING_DIR = "working"
STATUS_AWAITING_APPROVAL = "awaiting_approval"

# 品質ゲートの合格線。書き出しのモードはこれで決まる（T-031 と同じ線）。
QUALITY_THRESHOLD = 90


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: str | Path | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def write_proposal(run_dir: str | Path, ctx: Any, *, run_id: str,
                   models_used: list[str],
                   degraded_stages: list[str] | None = None,
                   quality_detail: dict | None = None) -> dict:
    """提案を残す — **書き出しの前に、人が見て決めるための材料**。

    品質と書き出しのモードは、品質改善ループの**後**の値（D-41）。以前はループが
    書き出しの後に回っていて、ループで合格しても書き出しは safe のまま残っていた。

    `degraded_stages`（前半で落ちた工程）は、書き出した後の状態を決めるのに要る —
    前半で落ちた工程があれば、書き出しても完走（completed）とは呼ばない（R1.5-C1b）。
    `quality_detail`（講評など）は、書き出しの時点で品質のサイドカーを書くのに要る。
    """
    run_dir = Path(run_dir)
    ai_outputs = []
    metadata = getattr(ctx, "metadata", None) or {}
    if metadata:
        text = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
        for sub in (PROPOSAL_DIR, WORKING_DIR):
            (run_dir / sub).mkdir(parents=True, exist_ok=True)
            (run_dir / sub / "youtube_metadata.json").write_text(
                text, encoding="utf-8", newline="\n")
        ai_outputs.append({
            "name": "youtube_metadata",
            "proposal": f"{PROPOSAL_DIR}/youtube_metadata.json",
            "working": f"{WORKING_DIR}/youtube_metadata.json",
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })

    preview_path = getattr(ctx, "preview_path", None)
    preview_sha = _sha256_file(preview_path)
    score = getattr(ctx, "quality_score", 0)
    passed = score >= QUALITY_THRESHOLD
    proposal = {
        "run_id": run_id,
        "status": STATUS_AWAITING_APPROVAL,
        "created_at": _now(),
        "video_path": ctx.video_path,
        # **素材の指紋**（4周目の反例B）。承認の後に素材を差し替えられても気づけるように
        "source": {"path": str(ctx.video_path), "sha256": _sha256_file(ctx.video_path)},
        "session_id": getattr(ctx, "session_id", ""),
        "preview": ({"path": str(preview_path), "sha256": preview_sha}
                    if preview_sha else None),
        "quality": {"score": score,
                    "scored": bool(getattr(ctx, "quality_scored", False)),
                    "passed": passed},
        "render_mode": "production" if passed else "safe",
        "skipped_features": list(getattr(ctx, "skipped_features", None) or []),
        "degraded_stages": list(degraded_stages or []),
        "warnings": list(getattr(ctx, "warnings", None) or []),
        "quality_detail": dict(quality_detail or {}),
        "ai_outputs": ai_outputs,
        "models_used": list(models_used),
    }
    _write_json(run_dir / PROPOSAL, proposal)
    return proposal


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _ai_used_for(run_dir: Path) -> list[dict]:
    """**AI を使った工程**を実行記録から機械的に作る（開示の材料・R2-C3）。

    ローカルの道具（`local:*`）は AI 生成ではないので入れない。
    """
    path = run_dir / "run.json"
    if not path.is_file():
        return []
    seen: list[dict] = []
    for stage in _read_json(path).get("stages") or []:
        model = stage.get("model") or ""
        if not model or model.startswith("local:"):
            continue
        row = {"stage": stage.get("name"), "model": model}
        if row not in seen:
            seen.append(row)
    return seen


def approve(run_dir: str | Path, *, synthetic: bool | None, by: str,
            note: str = "") -> dict:
    """提案を承認する — **人が見て決めたこと**を残す（R2-C2・C3）。

    - 提案の指紋（`proposal.json` の sha256）。承認の後に提案が変わったら書き出さない
    - 人が手を入れた差分: AI の出力の写し（`proposal/`）と、人が直す現物（`working/`）の差。
      **差分が空でも「直さずに承認した」ことが残る**
    - 開示の判断: 合成メディアを含むか（**人が決める。省けない**）と、AI を使った工程

    **承認し直せるのは、前の承認が古くなったときだけ**（承認の後に提案・プレビュー・
    直す現物のどれかが変わった）。前の承認は `approval_history/` に移して残す —
    上書きで証跡を消さない。書き出した後は承認し直せない。
    """
    run_dir = Path(run_dir)
    proposal_path = run_dir / PROPOSAL
    if not proposal_path.is_file():
        raise FileNotFoundError(f"提案がありません: {proposal_path}")
    if synthetic is None:
        raise ValueError("合成メディアを含むかを人が決めてください（--synthetic yes|no）。"
                         "開示ラベルの要否はコンテンツによるので、機械は決めません")
    if not isinstance(synthetic, bool):
        raise TypeError(f"合成メディアの判断は真偽値で渡してください: {synthetic!r}")
    _preview = _read_json(proposal_path).get("preview") or {}
    if (not _preview.get("path")
            or _sha256_file(_preview.get("path")) != _preview.get("sha256")):
        # **見ていないものは承認できない**（2026-09-25 ユーザー決定・4周目の反例B）。
        # プレビュー生成は致命的な工程ではないので、落ちても提案はできる。そのまま承認できると
        # 書き出しは素材から直接レンダリングし（T-022）、誰も見ていない動画が出る
        raise ValueError("プレビューが無いか、提案の後に変わっています（見ていないものは承認できない）。"
                         "プレビュー生成が落ちたか差し替わっています。原因を直して走り直してください")
    approval_path = run_dir / APPROVAL
    if approval_path.exists():
        if (run_dir / EXPORT).exists():
            raise ValueError(f"書き出し済みの実走は承認し直せません: {run_dir / EXPORT}")
        if export_allowed(run_dir)[0]:
            raise ValueError(f"すでに承認されています（まだ有効です）: {approval_path}")
        # 古くなった承認は履歴へ移す（消さない）
        history = run_dir / APPROVAL_HISTORY
        history.mkdir(exist_ok=True)
        stamp = str(_read_json(approval_path).get("approved_at") or _now())
        approval_path.replace(history / (stamp.replace(":", "-") + ".json"))

    proposal = _read_json(proposal_path)
    edits = []
    for out in proposal.get("ai_outputs") or []:
        before = (run_dir / out["proposal"]).read_text(encoding="utf-8")
        after_path = run_dir / out["working"]
        after = after_path.read_text(encoding="utf-8")
        diff = "".join(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=out["proposal"], tofile=out["working"]))
        edits.append({"name": out["name"], "changed": before != after, "diff": diff,
                      "working_sha256": _sha256_file(after_path)})

    now = _now()
    approval = {
        "run_id": proposal.get("run_id"),
        "approved_at": now,
        "approved_by": by,
        "note": note,
        "proposal_sha256": _sha256_file(proposal_path),
        "edits": edits,
        "ai_disclosure": {
            "contains_synthetic_media": synthetic,
            "decided_by": by,
            "decided_at": now,
            "ai_used_for": _ai_used_for(run_dir),
        },
    }
    _write_json(run_dir / APPROVAL, approval)
    return approval


# 開示の中身（設計 docs/specs/2026-09-19-r2-approval-design.md §5）。
# **bool 1個は開示ではない** — 誰が・いつ決めたか、AI をどの工程に使ったかまで揃って開示。
DISCLOSURE_FIELDS = ("contains_synthetic_media", "decided_by", "decided_at", "ai_used_for")


def disclosure_problem(disclosure: dict | None) -> str | None:
    """開示として成り立っていなければ理由を返す。成り立っていれば None。

    **`ai_used_for` は空でよい**（AI を1工程も使わなかった実走がある）。無いのと空は違う。
    """
    d = disclosure or {}
    if not isinstance(d.get("contains_synthetic_media"), bool):
        return "開示の判断がありません（合成メディアを含むかを承認のときに決めてください）"
    欠け = [f for f in ("decided_by", "decided_at")
            if not isinstance(d.get(f), str) or not d[f].strip()]
    if not isinstance(d.get("ai_used_for"), list):
        欠け.append("ai_used_for")
    if 欠け:
        return f"開示の中身が欠けています（{'、'.join(欠け)}）"
    return None


def export_allowed(run_dir: str | Path) -> tuple[bool, str]:
    """**書き出してよいか**（R2-C1 の門）。通さない理由を必ず言う。

    承認が無い・承認の後に提案やプレビューや直す現物が変わった・開示の判断が無い、
    のどれでも通さない。書き出しの工程の直前で呼ぶ（画面経由でも同じ門を通る）。
    """
    run_dir = Path(run_dir)
    proposal_path = run_dir / PROPOSAL
    if not proposal_path.is_file():
        return False, f"提案がありません: {proposal_path}"
    approval_path = run_dir / APPROVAL
    if not approval_path.is_file():
        return False, ("承認されていません。プレビューを見てから "
                       f"`python -m backend.revenue.approval_gate --approve {run_dir.name}` で承認してください")
    approval = _read_json(approval_path)
    if approval.get("proposal_sha256") != _sha256_file(proposal_path):
        return False, "提案が承認の後に変わっています。承認し直してください"
    proposal = _read_json(proposal_path)
    preview = proposal.get("preview") or {}
    if not preview.get("path"):
        return False, "プレビューが無い提案です（見ていないものは書き出さない）"
    if _sha256_file(preview.get("path")) != preview.get("sha256"):
        return False, f"プレビューが承認の後に変わっています: {preview.get('path')}"
    source = proposal.get("source")
    if not isinstance(source, dict):
        return False, "提案に素材の指紋がありません（確かめられないので書き出さない）。走り直してください"
    if _sha256_file(source.get("path")) != source.get("sha256"):
        return False, f"素材が承認の後に変わっています: {source.get('path')}"
    working = {o["name"]: o["working"] for o in proposal.get("ai_outputs") or []}
    for edit in approval.get("edits") or []:
        path = run_dir / working.get(edit["name"], "")
        if _sha256_file(path) != edit.get("working_sha256"):
            return False, f"承認の後に直しています（{edit['name']}）。承認し直してください"
    問題 = disclosure_problem(approval.get("ai_disclosure"))
    if 問題:
        return False, 問題
    return True, ""


def write_export(run_dir: str | Path, *, final_path: str | None,
                 metadata_sidecar: str | None, quality_sidecar: str | None,
                 render_mode: str) -> dict:
    """書き出した記録を残す — **どの承認で、何を書き出したか**（R2-C2 の証跡の最後の段）。"""
    run_dir = Path(run_dir)
    data = {
        "run_id": run_dir.name,
        "exported_at": _now(),
        "final": ({"path": str(final_path), "sha256": _sha256_file(final_path)}
                  if final_path else None),
        "approval_sha256": _sha256_file(run_dir / APPROVAL),
        "metadata_sidecar": str(metadata_sidecar) if metadata_sidecar else None,
        "quality_sidecar": str(quality_sidecar) if quality_sidecar else None,
        "render_mode": render_mode,
    }
    _write_json(run_dir / EXPORT, data)
    return data


# --- 検査と証跡（R2-C1〜C3 の verify） -----------------------------------------

# --- 完成品の置き場の監査（R2-C1・2026-09-25） --------------------------------

# 正典（vision_backlog.json の R2-C1）の定義でいう「書き出し」の置き場。
# **プレビュー・中間物（preview / edited / merged）は含まない** — 承認の材料そのもの
PUBLISH_DIRS = ("final", "shorts")
# **置き場に置けるのは「承認済みの完成品」と「その付属物」だけ**（5周目の反証・2026-09-25）。
# 入れ物（拡張子）を列挙していた頃は、許可リストに無い `.wmv`・`.mpg`・`.flv`・`.3gp` の
# 未承認動画が素通りした（4周目は直下の `*.mp4` しか見ずに `.webm`・`.mov` を見逃した）。
# **列挙する限り次の入れ物が出る**ので裏返す — 付属物の名前の形だけを知っていて、
# それ以外のファイルはすべて「承認に辿れるか」を問う
COMPANION_SUFFIXES = (".youtube.json", ".quality.json")
# safe_io を読めないときの書き手の退避先（`Path("output/final")` 等）。ここも置き場
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PUBLISH_BASELINE = Path(__file__).resolve().parent.parent / "config" / "publish_baseline.json"
# 承認の記録は書き換えない（指紋が変わる）。**実際には誰が承認したか**をここに添える
APPROVAL_ANNOTATIONS = Path(__file__).resolve().parent.parent / "config" / "approval_annotations.json"


def _default_vault_dir() -> Path:
    try:
        from safe_io import VAULT_OUTPUTS_DIR
    except ImportError:  # backend/ が import の起点に無いとき
        from backend.safe_io import VAULT_OUTPUTS_DIR
    return Path(VAULT_OUTPUTS_DIR)


def load_publish_baseline(path: str | Path | None = None) -> dict[str, str]:
    """承認の仕組みができる前からあった完成品（**名前 → 指紋**）。無ければ空。"""
    path = Path(path or PUBLISH_BASELINE)
    if not path.is_file():
        return {}
    data = _read_json(path)
    return {e["path"]: e["sha256"] for e in data.get("files", [])}


def _付属物の持ち主(f: Path) -> str | None:
    """付属物（`<名前>.youtube.json` など）なら、持ち主の名前（拡張子の前まで）を返す。"""
    for suf in COMPANION_SUFFIXES:
        if f.name.endswith(suf):
            return f.name[: -len(suf)]
    return None


def _持ち主の名前(f: Path) -> str:
    """動画の名前から最後の拡張子を外したもの（`final_A.mp4` → `final_A`）。"""
    return f.name.rsplit(".", 1)[0] if "." in f.name else f.name


def _approval_holds(run_dir: Path, export: dict) -> bool:
    """その実走の承認が**その提案の承認として成り立ち、書き出しの後も変わっていない**か。

    4周目の反例C: 中身が `{}` の承認と、それを指す書き出しの記録を手で置くと「辿れる」扱い
    になっていた。docstring は「承認がいまも有効」と書いていたのに確かめていなかった。
    **全部を手で作り込んだ記録**（提案・承認・書き出しの偽造）はここでは見えない（limits）。
    """
    approval_path, proposal_path = run_dir / APPROVAL, run_dir / PROPOSAL
    if not approval_path.is_file() or not proposal_path.is_file():
        return False
    if export.get("approval_sha256") != _sha256_file(approval_path):
        return False                      # 承認が書き出しの後に差し替わった
    approval = _read_json(approval_path)
    if approval.get("proposal_sha256") != _sha256_file(proposal_path):
        return False                      # 別の提案の承認（提案が承認の後に変わった）
    return disclosure_problem(approval.get("ai_disclosure")) is None


def disclosure_output_problem(final: Path, sidecar: str | None) -> str | None:
    """**完成品の隣に開示つきの手動投稿用サイドカーがあるか**（R2-C3・2026-09-26）。無ければ理由。

    9周目の C3-1: サイドカーの書き込みが I/O で落ちても書き出しは completed で終わり、
    開示の無い完成品が置き場に残った。`--gate` は最新の1本しか見ないので、次の実走を
    書き出すと緑に戻った。置き場の監査は全部を見るので、**結果の側でも**開示を問う。
    """
    if not sidecar:
        return "書き出しの記録に手動投稿用サイドカーがありません（開示が出力に含まれていない）"
    sc = Path(sidecar)
    if not sc.is_file():
        return f"書き出しの記録が指す手動投稿用サイドカーがありません: {sidecar}"
    if (os.path.normcase(os.path.abspath(sc.parent)) != os.path.normcase(os.path.abspath(final.parent))
            or _付属物の持ち主(sc) is None
            or _付属物の持ち主(sc).casefold() not in (final.name.casefold(),
                                                   _持ち主の名前(final).casefold())):
        return f"手動投稿用サイドカーが完成品の隣にありません: {sidecar}"
    try:
        disclosure = json.loads(sc.read_text(encoding="utf-8")).get("ai_disclosure")
    except (UnicodeDecodeError, ValueError, AttributeError):
        return f"手動投稿用サイドカーが JSON として読めません: {sidecar}"
    問題 = disclosure_problem(disclosure)
    return f"サイドカーの開示が不十分です（{問題}）" if 問題 else None


def publish_audit(runs_dir: str | Path, vault_dir: str | Path | None = None,
                  baseline: dict[str, str] | None = None,
                  output_root: str | Path | None = None) -> list[str]:
    """**完成品の置き場にある動画が、1本残らず承認に辿れるか**（R2-C1）。

    書き方ではなく結果を見る。3周の gate-verifier は、いずれも「承認を通さずに書ける
    場所」で C1 を崩した（経路 → 経路 → 走査の検出漏れ）。書き方を列挙する限り次の
    書き方が出るが、**完成品はどんな書き方でも置き場に出る。**

    見るもの（正典の定義）:
    - 置き場（`final/`・`shorts/`）と退避先（`<output_root>/final`・`<output_root>/shorts`）の
      **すべてのファイル** — 深さも入れ物も問わない。**置けるのは承認済みの完成品と、その付属物
      （`<名前>.youtube.json`・`<名前>.quality.json`）だけ**。入れ物は列挙しない（5周目の反証）
    - **手動投稿用サイドカー（`*.youtube.json`）があるフォルダ**は置き場として扱い、直下の中身を
      同じ規則で全部問う — 名前で結ばない（7周目の反証）。vault と output_root の下を探す
      （それ以外の場所は見えない — limits）

    承認に辿れる = どれかの実走の `export.json` がその動画を指し、指紋（sha256）が一致し、
    その実走の承認が**その提案の承認として成り立ち**、書き出しの後も変わっていない
    （`_approval_holds`）。基準線（門ができる前からあった動画）は**名前と指紋の両方**が
    一致したときだけ通す — 同じ名前で中身を替えたら新しい完成品。
    """
    runs_dir = Path(runs_dir)
    vault = Path(vault_dir) if vault_dir is not None else _default_vault_dir()
    out = Path(output_root) if output_root is not None else _PROJECT_ROOT / "output"
    baseline = load_publish_baseline() if baseline is None else baseline

    承認済み: dict[str, str] = {}
    開示の欠け: dict[str, str] = {}
    for export_path in sorted(runs_dir.glob("*/" + EXPORT)):
        e = _read_json(export_path)
        final = e.get("final") or {}
        if final.get("path") and _approval_holds(export_path.parent, e):
            key = os.path.normcase(os.path.abspath(final["path"]))
            承認済み[key] = final.get("sha256")
            欠け = disclosure_output_problem(Path(final["path"]), e.get("metadata_sidecar"))
            if 欠け:
                開示の欠け[key] = 欠け

    def 名前(f: Path) -> str:
        """基準線と報告に使う名前。vault の下は `final/…`、退避先は `output/…`。"""
        for root, 頭 in ((vault, ""), (out, "output/")):
            try:
                return 頭 + f.relative_to(root).as_posix()
            except ValueError:
                continue
        return f.as_posix()

    def 判定(f: Path) -> str | None:
        """承認に辿れる（か基準線にある）なら None、辿れなければ理由。"""
        rel = 名前(f)
        sha = _sha256_file(f)
        if rel in baseline:
            if baseline[rel] == sha:
                return None
            return f"{rel}: 基準線の名前だが中身が違います（門ができた後に置き換わった）"
        key = os.path.normcase(os.path.abspath(f))
        if key not in 承認済み:
            return (f"{rel}: **承認に辿れないファイル**です（置き場に置けるのは"
                    "承認済みの完成品と、その付属物だけ）")
        if 承認済み[key] != sha:
            return f"{rel}: 書き出した後に差し替わっています（記録の指紋と違う）"
        if key in 開示の欠け:
            return f"{rel}: **開示の出力が欠けた完成品**です — {開示の欠け[key]}"
        return None

    problems: list[str] = []
    見た: set[str] = set()

    def 付属物が結びつく(owner: str, 動画: Path) -> bool:
        """付属物の持ち主の名前が、動画の名前（拡張子込み・抜き）と大文字小文字を問わず一致するか。

        `<名前>.youtube.json` と `<名前>.mp4.youtube.json` のどちらの付け方もある
        （アップローダの案内は「`<動画名>.youtube.json`」）。6周目の U2 で拡張子抜きの完全一致しか
        見ていなかったのを直した。
        """
        o = owner.casefold()
        return o in (動画.name.casefold(), _持ち主の名前(動画).casefold())

    def 置けない形(f: Path) -> str | None:
        """中身を見る前に断る形（6周目の I2・I4）。"""
        if f.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(f)):
            return f"{名前(f)}: 置き場にリンクは置けません（リンクの先は監査しない）"
        if f.name.endswith((".", " ")):
            return f"{名前(f)}: 末尾がドットや空白の名前は置けません（Windows が正規化して別のファイルと取り違える）"
        return None

    def フォルダを問う(d: Path, entries: list[Path]) -> None:
        """置き場と同じ規則で、フォルダの中身を全部問う — 承認済みの完成品と付属物だけが置ける。"""
        for f in entries:
            形 = 置けない形(f)
            if 形:
                problems.append(形)
                見た.add(os.path.normcase(os.path.abspath(f)))
        files = [f for f in entries if f.is_file() and not 置けない形(f)]
        通った: list[Path] = []
        for f in files:
            見た.add(os.path.normcase(os.path.abspath(f)))
            if _付属物の持ち主(f) is not None:
                continue
            理由 = 判定(f)
            if 理由:
                problems.append(理由)
            else:
                通った.append(f)
        for f in files:
            owner = _付属物の持ち主(f)
            if owner is None:
                continue
            if not any(v.parent == f.parent and 付属物が結びつく(owner, v) for v in 通った):
                problems.append(f"{名前(f)}: 承認済みの完成品に結びつかない付属物です（動画が無いか、承認に辿れない）")
                continue
            try:
                json.loads(f.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, ValueError):
                # 付属物は名前だけで見ない（6周目の I1: 付属物の名前をかぶせた動画）
                problems.append(f"{名前(f)}: 付属物の名前だが中身が JSON ではありません")

    # 1. 置き場（final / shorts と退避先）: **すべてのファイル**を問う（深さも問わない）
    置き場 = [root / sub for root in (vault, out) for sub in PUBLISH_DIRS if (root / sub).is_dir()]
    for d in 置き場:
        フォルダを問う(d, sorted(d.rglob("*")))

    # 2. **手動投稿用サイドカーがあるフォルダは置き場として扱う**（2026-09-26・7周目の F1）。
    #    以前はサイドカーと名前が一致する動画だけを問うていたので、名前の違う未承認の動画
    #    （`edit_X.mp4` と `upload.youtube.json`）を見逃した。**名前で結ばない** —
    #    サイドカーがあれば、そのフォルダ（直下）から投稿されうる
    置き場の根 = [os.path.normcase(os.path.abspath(d)) for d in 置き場]

    def 置き場の中(d: Path) -> bool:
        k = os.path.normcase(os.path.abspath(d))
        return any(k == r or k.startswith(r + os.sep) for r in 置き場の根)

    サイドカーのフォルダ = sorted({sc.parent for root in (vault, out) if root.is_dir()
                           for sc in root.rglob("*.youtube.json")
                           if not 置き場の中(sc.parent)})
    for d in サイドカーのフォルダ:
        フォルダを問う(d, sorted(d.iterdir()))

    # 3. **置き場の取り違えで緑に倒れない**（6周目の U1）。書き出しの記録が指す完成品が、
    #    監査した場所の外にあるなら、監査は書き出し先を見ていない（`ANTIGRAVITY_VAULT_OUTPUTS` の
    #    取り違え・`.env` の差・別の置き場への書き出し）
    根 = [os.path.normcase(os.path.abspath(r)) for r in 置き場 + サイドカーのフォルダ] or [
        os.path.normcase(os.path.abspath(root / sub)) for root in (vault, out) for sub in PUBLISH_DIRS]
    for export_path in sorted(runs_dir.glob("*/" + EXPORT)):
        final = (_read_json(export_path).get("final") or {}).get("path")
        if not final:
            continue
        key = os.path.normcase(os.path.abspath(final))
        if not any(key == r or key.startswith(r + os.sep) for r in 根):
            problems.append(f"{export_path.parent.name}: 書き出した完成品（{final}）の場所を監査していません"
                            "（置き場の取り違え — `ANTIGRAVITY_VAULT_OUTPUTS` や `--vault-dir` を確かめる）")
    return problems


def audited_roots(vault_dir: str | Path | None = None, output_root: str | Path | None = None) -> list[str]:
    """`--gate` が監査する置き場（表示用）。**どこを見たのかを名乗る**（6周目の U1）。"""
    vault = Path(vault_dir) if vault_dir is not None else _default_vault_dir()
    out = Path(output_root) if output_root is not None else _PROJECT_ROOT / "output"
    return [f"{root / sub}{'' if (root / sub).is_dir() else '（無い）'}"
            for root in (vault, out) for sub in PUBLISH_DIRS]


def gate(runs_dir: str | Path) -> tuple[bool, list[str]]:
    """**最新の実走が「承認して、承認したものを、開示つきで書き出した」か**（R2-C1・C3）。

    承認待ち・承認なしの書き出し・書き出した動画が記録と違う・開示が無い、のどれでも FAIL。
    判定は最新の1本で行う（成果物ゲートと同じ）。
    """
    runs = sorted(Path(runs_dir).glob("*/run.json"))
    if not runs:
        return False, [f"実行記録がありません: {runs_dir}"]
    run_dir = runs[-1].parent
    status = _read_json(runs[-1]).get("status")
    if status == STATUS_AWAITING_APPROVAL:
        return False, [(f"{run_dir.name}: 承認待ちです（書き出していません）。"
                        "プレビューを見て --approve、それから --export")]
    if status not in ("completed", "degraded"):
        return False, [f"{run_dir.name}: 状態が {status} です（書き出していません）"]
    export_path = run_dir / EXPORT
    if not export_path.is_file():
        return False, [(f"{run_dir.name}: 書き出しの記録（export.json）がありません — "
                        "承認の門を通らずに書き出しています")]
    export = _read_json(export_path)
    problems = []
    approval_path = run_dir / APPROVAL
    if not approval_path.is_file():
        problems.append("承認の記録（approval.json）が無いまま書き出しています")
    elif export.get("approval_sha256") != _sha256_file(approval_path):
        problems.append("書き出しの記録が指す承認と、いまの承認が食い違っています")
    final = export.get("final") or {}
    if not final or _sha256_file(final.get("path")) != final.get("sha256"):
        problems.append("書き出した動画が記録と違います（無いか、書き出しの後に変わった）: "
                        f"{final.get('path')}")
    sidecar = export.get("metadata_sidecar")
    if not sidecar or not Path(sidecar).is_file():
        # **原因を取り違えない**（9周目の M3）。承認に開示はあっても、出力に載っていなければ欠け
        problems.append("手動投稿用のメタデータ（開示を載せるサイドカー）が出力にありません: "
                        f"{sidecar or '(書き出しの記録に無い)'}")
    else:
        問題 = disclosure_problem(_read_json(Path(sidecar)).get("ai_disclosure"))
        if 問題:
            problems.append(f"手動投稿用のメタデータの AI 生成の開示が不十分です — {問題}")
    return (not problems), [f"{run_dir.name}: {p}" for p in problems]


def trace(run_dir: str | Path) -> tuple[bool, str]:
    """**承認の証跡**（R2-C2）— 提案 → 承認（いつ・誰が・人が直した差分・開示の判断）→ 書き出し。"""
    run_dir = Path(run_dir)
    proposal_path = run_dir / PROPOSAL
    if not proposal_path.is_file():
        return False, f"提案がありません: {proposal_path}"
    p = _read_json(proposal_path)
    q = p.get("quality") or {}
    合否 = "合格" if q.get("passed") else "不合格"
    lines = [f"承認の証跡: {run_dir.name}", "",
             "■ 提案",
             f"  作った時刻  : {p.get('created_at')}",
             f"  プレビュー  : {(p.get('preview') or {}).get('path')}",
             f"  品質        : {q.get('score')} 点（{合否}）→ 書き出しのモード {p.get('render_mode')}",
             f"  使ったモデル: {', '.join(p.get('models_used') or []) or '(記録なし)'}"]
    # **工程ごとに、なぜそのモデルになったか**（D-39・R2-C5）。実行記録から読む
    run_path = run_dir / "run.json"
    if run_path.is_file():
        for st in (_read_json(run_path).get("stages") or []):
            model = st.get("model") or "(記録なし)"
            if str(model).startswith("local:"):
                continue
            段 = f"・段 {st['tier']}" if st.get("tier") else ""
            reason = st.get("model_reason") or ""
            if reason == "fallback":
                降格 = "、".join(f"{f.get('from')} → {f.get('to')}（{f.get('reason')}）"
                               for f in st.get("fallbacks") or [])
                理由 = f"**降格**: {降格}"
            elif reason == "declared":
                理由 = "宣言どおり"
            elif reason == "mismatch":
                理由 = (f"**実測が宣言と違う**（実際に動いた: {', '.join(st.get('models_observed') or []) or '?'}。"
                        "理由の記録なし）")
            elif reason == "observed":
                理由 = "宣言なし（実測だけ）"
            elif reason == "unverified" or st.get("model_unverified"):
                理由 = "**未検証**（一度も呼ばれていない — 提案はこのモデルが出したものではない）"
            else:
                理由 = "（理由の記録なし — D-39 より前の実走）"
            lines.append(f"    {st.get('name')}: {model}{段} — {理由}")

    history_dir = run_dir / APPROVAL_HISTORY
    for h in sorted(history_dir.glob("*.json")) if history_dir.is_dir() else []:
        old = _read_json(h)
        lines.append(f"  （古くなった承認: {old.get('approved_at')} {old.get('approved_by')}）")

    approval_path = run_dir / APPROVAL
    lines += ["", "■ 承認"]
    if not approval_path.is_file():
        lines.append("  承認されていません")
        return False, "\n".join(lines)
    a = _read_json(approval_path)
    d = a.get("ai_disclosure") or {}
    lines += [f"  承認した時刻: {a.get('approved_at')}",
              f"  承認した人  : {a.get('approved_by')}"]
    注記 = (_read_json(APPROVAL_ANNOTATIONS).get("runs", {})
            if APPROVAL_ANNOTATIONS.is_file() else {}).get(run_dir.name)
    if 注記:
        lines.append(f"  ⚠ 記録上の承認者は {注記.get('recorded_as')} だが、"
                     f"実際に承認したのは {注記.get('actual_approver')}（{注記.get('note', '')}）")
    if a.get("note"):
        lines.append(f"  メモ        : {a['note']}")
    for e in a.get("edits") or []:
        if e.get("changed"):
            lines.append(f"  人が直したもの: {e['name']}")
            lines += ["    " + ln for ln in e.get("diff", "").splitlines()]
        else:
            lines.append(f"  人が直したもの: {e['name']} — 直さずに承認")
    used = ", ".join(f"{u.get('stage')}（{u.get('model')}）" for u in d.get("ai_used_for") or [])
    合成 = "はい" if d.get("contains_synthetic_media") else "いいえ"
    lines += [f"  開示        : 合成メディアを含む = {合成}（{d.get('decided_by')} が決めた）",
              f"  AI を使った工程: {used or 'なし'}"]

    lines += ["", "■ 書き出し"]
    export_path = run_dir / EXPORT
    if export_path.is_file():
        ex = _read_json(export_path)
        lines += [f"  書き出した時刻: {ex.get('exported_at')}",
                  f"  動画          : {(ex.get('final') or {}).get('path')}",
                  f"  モード        : {ex.get('render_mode')}"]
    else:
        lines.append("  まだ書き出していません")
    return True, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    from backend.revenue.run_record import RUNS_DIR

    parser = argparse.ArgumentParser(
        description="承認工程（R2）— 承認していない動画は書き出せない")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--approve", metavar="RUN_ID", help="提案を承認する")
    what.add_argument("--export", metavar="RUN_ID",
                      help="承認した提案を書き出す（**課金経路**: 書き出しの後の学習が API を呼ぶことがある）")
    what.add_argument("--gate", action="store_true",
                      help="最新の実走が承認して開示つきで書き出したか（R2-C1・C3）")
    what.add_argument("--trace", metavar="RUN_ID", help="承認の証跡を出す（R2-C2）")
    parser.add_argument("--synthetic", choices=("yes", "no"),
                        help="合成メディアを含むか（--approve で必須。人が決める）")
    parser.add_argument("--by", default=None,
                        help="承認する人（--approve で必須。**既定値で埋めない**。エージェントが試すなら claude-code）")
    parser.add_argument("--note", default="", help="承認のメモ")
    parser.add_argument("--runs-dir", default=None, help="実行記録の置き場（既定 output/runs）")
    parser.add_argument("--no-ledger", action="store_true",
                        help="--export で台帳に1本ぶんの要約を書かない（試し撃ち用）")
    parser.add_argument("--vault-dir", default=None,
                        help="完成品の置き場の親（既定は safe_io の VAULT_OUTPUTS_DIR）")
    parser.add_argument("--baseline", default=None,
                        help="門ができる前からあった完成品の台帳（既定 backend/config/publish_baseline.json）")
    parser.add_argument("--output-dir", default=None,
                        help="退避先の置き場の親（既定はリポジトリ直下の output/）")
    args = parser.parse_args(argv)
    runs_dir = Path(args.runs_dir or os.getenv("AVS_RUNS_DIR") or RUNS_DIR)

    if args.gate:
        ok, problems = gate(runs_dir)
        置き場 = publish_audit(runs_dir, args.vault_dir,
                            load_publish_baseline(args.baseline) if args.baseline else None,
                            args.output_dir)
        print("承認工程の門（R2）— 承認して、承認したものを、開示つきで書き出したか")
        print()
        if ok:
            print("  ✅ 最新の実走は承認を通って書き出され、開示があります")
        for p in problems:
            print(f"  🚫 {p}")
        print()
        print("完成品の置き場（final / shorts）— 置いてあるものが1つ残らず承認に辿れるか")
        for r in audited_roots(args.vault_dir, args.output_dir):
            print(f"  見た場所: {r}")
        if not 置き場:
            print("  ✅ 置き場のファイルはすべて、承認済みの完成品か、その付属物です")
        for p in 置き場:
            print(f"  🚫 {p}")
        return 0 if ok and not 置き場 else 1

    if args.trace:
        ok, text = trace(runs_dir / args.trace)
        print(text)
        return 0 if ok else 1

    if args.approve:
        if not (args.by or "").strip():
            print("🚫 誰が承認するのかを --by で書いてください。承認者は**既定値で埋めません**"
                  "（以前は git の user.name を入れていたので、エージェントが試しに承認した記録が"
                  "ユーザーの承認に見えていた）。エージェントが試すときは --by claude-code")
            return 1
        if args.synthetic is None:
            print("🚫 合成メディアを含むかを決めてください（--synthetic yes|no）。"
                  "開示ラベルの要否はコンテンツによるので、機械は決めません")
            return 1
        try:
            a = approve(runs_dir / args.approve, synthetic=(args.synthetic == "yes"),
                        by=args.by.strip(), note=args.note)
        except (FileNotFoundError, ValueError) as e:
            print(f"🚫 {e}")
            return 1
        直した = [e["name"] for e in a["edits"] if e["changed"]]
        合成 = "はい" if args.synthetic == "yes" else "いいえ"
        print(f"✅ 承認しました: {args.approve}（{a['approved_by']}）")
        print(f"   人が直したもの: {', '.join(直した) or 'なし（直さずに承認）'}")
        print(f"   開示: 合成メディアを含む = {合成}")
        print(f"   書き出す: python -m backend.revenue.approval_gate --export {args.approve}")
        return 0

    # --export: 本線の coordinator は backend/ を import の起点にしている
    import asyncio
    import sys
    backend_dir = str(Path(__file__).resolve().parent.parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from backend import cost_guard
    cost_guard.load_env()
    from agents.pipeline_coordinator import PipelineCoordinator

    coordinator = PipelineCoordinator()
    coordinator.runs_dir = runs_dir
    if not args.no_ledger:
        coordinator.ledger_path = Path(cost_guard.LEDGER_PATH)
    result = asyncio.run(coordinator.export(args.export))
    print(f"  状態  : {result['status']}")
    print(f"  成果物: {result.get('final_path') or '(無し)'}")
    if result.get("error"):
        print(f"  🚫 {result['error']}")
    return 0 if result["status"] in ("completed", "degraded") else 1


if __name__ == "__main__":
    raise SystemExit(main())
