#!/usr/bin/env python3
"""課金を伴う操作を止める PreToolUse フック。

憲法第3条: フェーズ内であっても、**課金判断だけ**は必ず人間の承認を通す。
それ以外は Claude Code が単独で実行してよい（2026-08-02 決定）。

なぜフックなのか:
    CLAUDE.md の記述は勧告でしかなく、文脈が長くなると埋もれる。
    「必ず守る」ものはコードで止める。

fail-open にしている理由:
    このスクリプトが落ちたときに `deny` を返すと、Bash が全面的に
    使えなくなってセッションが死ぬ。誤検出の代償のほうが大きいので、
    例外は素通し（exit 0）にする。CLAUDE.md の憲法が二重の防御。
"""

from __future__ import annotations

import json
import re
import sys

# 実測より先に「金が動く形」で並べる。名前ではなく**効果**で捕まえる。
_BILLING_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bgcloud\s+billing\b", re.I), "GCP の課金設定"),
    (re.compile(r"\baws\s+(billing|ce|budgets)\b", re.I), "AWS の課金設定"),
    (re.compile(r"\bnpm\s+publish\b", re.I), "npm への公開（有料組織/名前空間の可能性）"),
    (re.compile(r"\bpip\s+.*\btwine\s+upload\b", re.I), "PyPI への公開"),
    (re.compile(r"\bstripe\b", re.I), "決済 API"),
    # GitHub: Private リポジトリのブランチ保護は GitHub Pro が要る。
    # 有料プランへの依存を生むので課金判断として扱う。
    (re.compile(r"\bgh\s+api\b.*\b(billing|marketplace|plan)\b", re.I), "GitHub の課金 API"),
    (re.compile(r"\bgh\s+api\b.*\bbranch(es)?/[^ ]+/protection\b", re.I),
     "ブランチ保護（Private では GitHub Pro が必要）"),
    (re.compile(r"\bgh\s+(billing|sponsors)\b", re.I), "GitHub の課金・スポンサー"),
    # 受け皿。**広げすぎない。**
    # 2026-08-02: 当初 `checkout` を入れていて `git checkout` を全部止めた。
    # 誤検出でセッションが止まるとフックごと外されるので、ゲートの価値がゼロになる。
    # 一般的な開発コマンドに出現しうる語（checkout / purchase / plan）は入れない。
    (re.compile(r"\bsubscriptions?\b", re.I), "サブスクリプション操作"),
    (re.compile(r"\b(paddle|paypal|braintree)\b", re.I), "決済サービス"),
)


def _decision(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"課金判断のためユーザー承認が必要です（{reason}）。"
                "憲法第3条: 課金を伴う操作だけは自律実行の対象外。"
                "何にいくらかかるかを提示して承認を取ってから実行してください。"
            ),
        }
    }, ensure_ascii=False))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # 読めないものは判断しない

    command = (payload.get("tool_input") or {}).get("command") or ""
    if not isinstance(command, str):
        return 0

    for pattern, reason in _BILLING_PATTERNS:
        if pattern.search(command):
            _decision(reason)
            return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — フックの故障でセッションを止めない
        sys.exit(0)
