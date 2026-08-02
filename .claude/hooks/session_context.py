#!/usr/bin/env python3
"""セッション開始時に「いまロードマップのどこにいるか」を注入する。

なぜ必要か:
    human-on-the-loop の停止条件は「フェーズの終了条件を満たしたか」。
    毎回セッションの頭で現在地を読み直すのは手間だし、読み忘れると
    前のフェーズの続きを勝手に始める。起動時に機械的に入れる。

正典は `antigravity-video-studio/backend/branding/vision_backlog.json`
（2026-08-02 決定）。ここが読めない・食い違うときは**それ自体を報告する** —
黙って進むと現在地の取り違えが積み上がる。

出力は stdout。exit 0 なら additionalContext としてモデルに渡る。
"""

from __future__ import annotations

import json
import os
import sys

_REPO = "antigravity-video-studio"
_LEDGER = os.path.join("backend", "branding", "vision_backlog.json")


def _find_repo(start: str) -> str | None:
    """cwd から上下に `antigravity-video-studio` を探す。"""
    cur = os.path.abspath(start)
    if os.path.basename(cur) == _REPO:
        return cur
    candidate = os.path.join(cur, _REPO)
    if os.path.isdir(candidate):
        return candidate
    parent = os.path.dirname(cur)
    return _find_repo(parent) if parent != cur else None


def main() -> int:
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except (json.JSONDecodeError, ValueError):
        payload = {}

    # payload の cwd が解決できないことがある（区切り文字の差など）。
    # 実プロセスの cwd も試す — 片方に頼ると現在地が黙って出なくなる。
    repo = None
    for start in (payload.get("cwd"), os.getcwd()):
        if start:
            repo = _find_repo(start)
            if repo:
                break
    if not repo:
        return 0  # 別プロジェクトのセッション。何も足さない。

    path = os.path.join(repo, _LEDGER)
    try:
        with open(path, encoding="utf-8") as fh:
            ledger = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ロードマップ正典] {_LEDGER} を読めません: {e}\n"
              "現在地が不明です。作業を始める前にこれを報告してください。")
        return 0

    score = ledger.get("vision_realization_score")
    history = ledger.get("score_history") or []
    latest = history[-1] if history else {}
    lines = [
        "[ロードマップ現在地] 正典: backend/branding/vision_backlog.json",
        f"  ビジョン実現度: {score}%（最終監査 {ledger.get('last_audit_date')}）",
    ]

    # サマリー欄と履歴の食い違いは現在地の取り違えに直結する。黙らせない。
    if latest and latest.get("score") != score:
        lines.append(
            f"  ⚠️ 不整合: score_history の最新は {latest.get('score')}%"
            f"（{latest.get('date')}）。正典を直すのが最優先。"
        )

    phase = ledger.get("current_phase")
    if phase:
        lines.append(f"  現フェーズ: {phase.get('id')} {phase.get('title')}")
        for c in phase.get("exit_criteria") or []:
            mark = "✅" if c.get("met") else "⬜"
            lines.append(f"    {mark} {c.get('id')}: {c.get('condition')}")
    else:
        lines.append("  ⚠️ current_phase が未定義。フェーズを定義しないと停止条件が決まらない。")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — 現在地が取れなくてもセッションは始める
        sys.exit(0)
