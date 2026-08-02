#!/usr/bin/env python3
"""課金を伴う操作を止める PreToolUse フック。

憲法第3条: フェーズ内であっても、**課金判断だけ**は必ず人間の承認を通す。
それ以外は Claude Code が単独で実行してよい（2026-08-02 決定）。

**1円でも請求されるものはすべて対象**（2026-08-02 追加）。外部サービスの
アカウント操作だけでなく、**従量課金の API を実際に叩く実行**を含む。

このリポジトリで金がかかるのは主に Gemini API（本番38モジュールが使用、
`gemini-2.5-flash` ほか）と `text-embedding-004`。
Whisper / faster_whisper / pyannote はローカル実行なので無料。

    テスト実行は無料。net_guard が外部接続を遮断し、キーも
    `dummy_key_for_ci` なので API に到達しない。**有料になるのは
    実 API キーでの実行と、パイプラインを起動する API 呼び出し。**

なぜフックなのか:
    CLAUDE.md の記述は勧告でしかなく、文脈が長くなると埋もれる。
    「必ず守る」ものはコードで止める。

何を止められないか:
    `python backend/foo.py` の中で Gemini を呼ぶような経路は静的には
    見えない。フックは網ではなく**最後の一枚**で、一次的な防御は憲法。

fail-open にしている理由:
    このスクリプトが落ちたときに `deny` を返すと、Bash が全面的に
    使えなくなってセッションが死ぬ。誤検出の代償のほうが大きいので、
    例外は素通し（exit 0）にする。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# キーがダミーだと分かる値。これらに一致するときは API に到達しないので通す。
_DUMMY_KEY = re.compile(r"^[\"']?(dummy|test|fake|placeholder|xxx+|none|changeme)", re.I)

# 実 API キーを環境変数で渡す形。値がダミーでなければ従量課金に届く。
_API_KEY_ASSIGN = re.compile(
    r"\b(GOOGLE_API_KEY|GEMINI_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|"
    r"ELEVENLABS_API_KEY|DEEPL_API_KEY)\s*=\s*(\S+)",
    re.I,
)

# アプリの API を **書き込み側**で叩く形。パイプライン起動や生成系は
# その先で Gemini を呼ぶので課金に直結する。GET（status/health）は通す。
_HTTP_CLIENTS = r"(curl|wget|http|https|Invoke-WebRequest|Invoke-RestMethod|iwr|irm)"
_WRITE_TO_APP_API = re.compile(
    rf"\b{_HTTP_CLIENTS}\b(?=.*\b/api/)(?=.*(-X\s*(POST|PUT|PATCH)|--data|-d\s|"
    r"-Method\s*(POST|PUT|PATCH)|--json))",
    re.I,
)

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
    # 従量課金の API を叩く CLI。
    (re.compile(r"\b(gemini|openai|anthropic|llm)\s+(chat|complete|generate|embed|run)\b", re.I),
     "生成 API の CLI 実行（従量課金）"),
    # 受け皿。**広げすぎない。**
    # 2026-08-02: 当初 `checkout` を入れていて `git checkout` を全部止めた。
    # 誤検出でセッションが止まるとフックごと外されるので、ゲートの価値がゼロになる。
    # 一般的な開発コマンドに出現しうる語（checkout / purchase / plan）は入れない。
    (re.compile(r"\bsubscriptions?\b", re.I), "サブスクリプション操作"),
    (re.compile(r"\b(paddle|paypal|braintree)\b", re.I), "決済サービス"),
)


def _paid_api_reason(command: str) -> str | None:
    """従量課金の API に到達する実行かどうか。到達するなら理由を返す。"""
    match = _API_KEY_ASSIGN.search(command)
    if match and not _DUMMY_KEY.match(match.group(2)):
        return f"実 API キーでの実行（{match.group(1)}）。Gemini は従量課金"
    if _WRITE_TO_APP_API.search(command):
        return "アプリ API への書き込み要求。パイプラインが Gemini を呼ぶ"
    return None


def _active_budget() -> dict | None:
    """残額のある承認済み予算を返す。

    憲法第3条: **予算の範囲内は都度確認しない。** 相談が要るのは
    「予算を組んでいない有料利用」で、それは実行の直前ではなく
    **計画段階で**洗い出して取る。だから実行時のゲートが見るのは
    「承認済みの枠があるか」だけでよい。
    """
    path = Path(__file__).resolve().parents[1] / "budget.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for entry in data.get("budgets") or []:
        if entry.get("status") != "active":
            continue
        try:
            remaining = float(entry.get("limit_jpy", 0)) - float(entry.get("spent_jpy", 0))
        except (TypeError, ValueError):
            continue
        if remaining > 0:
            return {**entry, "remaining_jpy": remaining}
    return None


# ヒアドキュメントの中身と `-m` のメッセージ本文。**コマンドではなくデータ。**
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1.*?^\2\s*$", re.S | re.M)
_MESSAGE_ARG = re.compile(r"(?:-m|--message)\s+(['\"])(?:\\.|(?!\1).)*\1", re.S)


def _strip_payloads(command: str) -> str:
    """コマンドが**運んでいるデータ**を落とす。

    2026-08-02: コミットメッセージに `npm publish` と書いただけで
    `git commit` が止まった。`git checkout` を止めた件と同じ型の誤検出で、
    原因も同じ — 判定対象がコマンドではなくデータになっている。

    ヒアドキュメントの本文と `-m` のメッセージは、どんな文字列でも
    入りうる（PR 本文・コミットメッセージ・テストデータ）。ここを見ると
    「課金の話を書いた」だけで止まる。落としてから判定する。
    """
    return _MESSAGE_ARG.sub(" ", _HEREDOC.sub(" ", command))


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
    command = _strip_payloads(command)

    for pattern, reason in _BILLING_PATTERNS:
        if pattern.search(command):
            _decision(reason)
            return 0

    paid = _paid_api_reason(command)
    if not paid:
        return 0

    budget = _active_budget()
    if budget is None:
        _decision(
            f"{paid}。**予算が組まれていません。**"
            "計画段階で有料利用を洗い出して予算を取ってから実行してください"
        )
        return 0

    # 予算内なので通す。ただし実績の記録を忘れると枠が意味を失う。
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"[予算] {budget.get('id')}「{budget.get('purpose')}」"
                f"の残 {budget['remaining_jpy']:.0f} 円の範囲内なので実行してよい。"
                "実行後に .claude/budget.json の spent_jpy を実績で更新すること。"
            ),
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — フックの故障でセッションを止めない
        sys.exit(0)
