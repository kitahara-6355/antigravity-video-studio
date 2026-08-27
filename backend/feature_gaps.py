"""実装不足項目の台帳と点検（2026-08-27 ユーザー決定）。

**実装が足りていない機能を1箇所に集め、新しい漏れと片付け忘れを機械が見つける。**

分かっていた7件のうち3件は正典 `vision_backlog.json` の条件文に散らばって書かれ、
残り4件は**どこにも書かれていなかった**（実走ログと品質ゲートの出力にしか出ない）。

証拠は**実行記録**に取る。ソース走査だと「書いてあるが動かない」を実装済みと
誤認する（`placeholder_video_id` がその実例）。

    python -m backend.feature_gaps --show                 # 一覧
    python -m backend.feature_gaps --audit                # 点検（実行記録も見る）
    python -m backend.feature_gaps --audit --static-only  # CI 用（実走できないので）

設計: `docs/specs/2026-08-27-feature-gaps-design.md`
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GAPS_PATH = REPO_ROOT / "backend" / "config" / "feature_gaps.json"

REQUIRED = ("id", "title", "kind", "why", "done_when")
VALID_KINDS = ("gap", "intentional")


def load_gaps(path: Path | None = None) -> list[dict]:
    p = Path(path or GAPS_PATH)
    if not p.is_file():
        raise FileNotFoundError(f"台帳がありません: {p}")
    return json.loads(p.read_text(encoding="utf-8"))["gaps"]


def check_entries(gaps: list[dict]) -> list[str]:
    """**記載不備。**「あとで書く」を許さない。理由の無い項目は思い出せない。"""
    出た: list[str] = []
    見た: set[str] = set()
    for g in gaps:
        rid = g.get("id") or "(id なし)"
        欠け = [k for k in REQUIRED if not g.get(k)]
        # **`gap` はどこで直すかが要る。** `intentional` は直さないので要らない
        if g.get("kind") == "gap" and not g.get("handled_in"):
            欠け.append("handled_in")
        if 欠け:
            出た.append(f"{rid}: 項目が欠けています: {', '.join(欠け)}")
        if g.get("kind") and g["kind"] not in VALID_KINDS:
            出た.append(f"{rid}: kind は {' / '.join(VALID_KINDS)} のどちらか"
                        f"（いまは {g['kind']}）")
        if rid in 見た:
            出た.append(f"{rid}: id が重複しています")
        見た.add(rid)
    return 出た


def _mainline_stage_names() -> set[str]:
    """**本線の工程名は実装不足ではない。** 落ちたのは工程であって機能ではない。

    実行記録には3種類が同じ顔で出る — 工程が落ちた（`quality_gate`）／
    意図して止めている（`dream_learning`）／実装が足りていない
    （`BGMミキシング(ファイルなし)`）。**区別しないと点検が誤検知する。**
    """
    try:
        from agents.pipeline_coordinator import STAGE_RECORD
    except ImportError:  # PYTHONPATH=./backend が無いとき
        from backend.agents.pipeline_coordinator import STAGE_RECORD
    return {v[0] for v in STAGE_RECORD.values()}


def surfaced_in(run: dict) -> list[str]:
    """実行記録に「やっていない」として出たものを重複なく並べる。"""
    health = run.get("health") or {}
    出たもの = (list(health.get("skipped_features") or [])
                + list(health.get("failed_stages") or []))
    return list(dict.fromkeys(出たもの))


def unknown_from_record(run: dict, gaps: list[dict]) -> list[str]:
    """**台帳にも本線の工程名にも無いもの。** 新しい実装漏れがこれで出る。"""
    既知 = _mainline_stage_names()
    印 = [g.get("surfaces_as") for g in gaps if g.get("surfaces_as")]
    return [名 for 名 in surfaced_in(run)
            if 名 not in 既知 and not any(s and s in 名 for s in 印)]


def is_done(gap: dict, run: dict | None) -> bool | None:
    """実装済みか。**`None` は「この実行では確かめていない」。**

    `False` と `None` を混ぜない。混ぜると「確かめられなかった」が
    「問題なし」に化ける（`model_policy --audit` がダミーキーで exit 0 を
    返す問題と同じ形）。
    """
    dw = gap.get("done_when") or {}
    kind = dw.get("kind")

    if kind == "marker_gone":
        # **弱い証拠。** 印が残っていることは「未実装」の確かな証拠だが、
        # 印が消えたことは「実装された」の証拠にならない
        # （`placeholder_video_id` が「書いてあるが動かない」の実例）。
        p = Path(dw.get("path", ""))
        if not p.is_absolute():
            p = REPO_ROOT / p
        if not p.is_file():
            return None
        return dw.get("marker", "") not in p.read_text(encoding="utf-8", errors="ignore")

    if run is None:
        return None

    if kind == "run_record_clean":
        印 = gap.get("surfaces_as") or gap.get("id") or ""
        return not any(印 in 名 for 名 in surfaced_in(run))

    if kind == "artifact_present":
        suffixes = tuple(dw.get("suffixes") or [])
        if not suffixes:
            return None
        return any(str(a).lower().endswith(suffixes)
                   for a in (run.get("artifacts") or []))

    return None


def latest_run() -> dict | None:
    """最新の実行記録。**無ければ `None`。**"""
    try:
        from backend.revenue.artifact_gate import load_runs
    except ImportError:
        from revenue.artifact_gate import load_runs
    runs = load_runs()
    return runs[-1] if runs else None


def audit(run: dict | None, gaps: list[dict],
          static_only: bool = False) -> tuple[list[str], list[str]]:
    """**違反**と、**この実行では確かめていないもの**を返す。

    分けて返すのが要。混ぜると「確かめられなかった」が「問題なし」に化ける。
    """
    違反 = list(check_entries(gaps))
    未確認: list[str] = []

    # 条件1: 記録に出たのに台帳にも本線の工程名にも無い＝新しい実装漏れ
    if static_only or run is None:
        未確認.append("実行記録との突き合わせ（新しい実装漏れの検出）"
                      "— 実行記録が無いので確かめていません"
                      if run is None else
                      "実行記録との突き合わせ（新しい実装漏れの検出）"
                      "— --static-only なので確かめていません")
    else:
        for 名 in unknown_from_record(run, gaps):
            違反.append(f"{名}: 実行記録に出ましたが、台帳にも本線の工程名にも"
                        "ありません。**新しい実装漏れです** — "
                        "台帳に足すか、意図して止めているなら "
                        "kind: intentional で宣言してください")

    # 条件2: 実装済みなのに台帳に残っている＝片付け忘れ
    for g in gaps:
        if static_only and (g.get("done_when") or {}).get("kind") != "marker_gone":
            未確認.append(f"{g.get('id')}: 実装済みかどうか"
                          "（実行記録が要る検査なので --static-only では見ていません）")
            continue
        済み = is_done(g, run)
        if 済み is None:
            未確認.append(f"{g.get('id')}: 実装済みかどうかを確かめられませんでした")
        elif 済み:
            違反.append(f"{g.get('id')}: **実装されているのに台帳に残っています。**"
                        "消してください（残すと『まだ無い』という嘘になり、"
                        "品質ゲートもこの機能を見なくなります）")
    return 違反, 未確認


def _format(gaps: list[dict], run: dict | None) -> str:
    lines = ["実装不足項目の台帳 — **一覧は台帳、期限は正典**", ""]
    if run:
        lines.append(f"  最新の実行記録: {run.get('run_id', '(id なし)')} / "
                     f"{run.get('finished_at') or run.get('started_at') or '(日時なし)'}")
    else:
        lines.append("  最新の実行記録: **ありません**（実走していないので"
                     "実行記録で見る検査は確かめられません）")
    lines.append("")
    for kind, 見出し in (("gap", "実装が足りていないもの"),
                         ("intentional", "意図して止めているもの（実装漏れではない）")):
        並び = [g for g in gaps if g.get("kind") == kind]
        if not 並び:
            continue
        lines.append(f"  【{見出し}】{len(並び)} 件")
        for g in 並び:
            行先 = g.get("handled_in") or "—"
            済み = is_done(g, run)
            印 = {True: "✅ 実装済み", False: "⬜ 未実装", None: "❔ 未確認"}[済み]
            lines.append(f"    {印}  {g['id']:<22} {g.get('title', '')}（行先: {行先}）")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="実装不足項目の台帳と点検")
    parser.add_argument("--show", action="store_true", help="一覧を出す")
    parser.add_argument("--audit", action="store_true",
                        help="点検する（違反があれば exit 1）")
    parser.add_argument("--static-only", action="store_true",
                        help="実行記録を使わない検査だけ（CI 用）")
    args = parser.parse_args(argv)

    gaps = load_gaps()
    run = None if args.static_only else latest_run()

    if args.show or not args.audit:
        print(_format(gaps, run))
        if not args.audit:
            return 0

    違反, 未確認 = audit(run, gaps, static_only=args.static_only)
    if 未確認:
        print(f"  ℹ この実行で**確かめていない**検査が {len(未確認)} 件あります"
              "（黙って飛ばさないために列挙します）:")
        for m in 未確認:
            print(f"      - {m}")
    if 違反:
        print(f"\n🚫 実装不足項目の点検で {len(違反)} 件:")
        for m in 違反:
            print(f"    - {m}")
        return 1
    print("\n✅ 台帳と実態は食い違っていません。")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
