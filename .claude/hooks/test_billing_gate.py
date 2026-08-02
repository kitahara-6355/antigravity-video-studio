#!/usr/bin/env python3
"""billing_gate.py の判定テスト。`python .claude/hooks/test_billing_gate.py` で走る。

pytest ではなく単体スクリプトにしてある。pytest.ini の testpaths に入れると
CI の対象になるが、このフックは開発機の Claude Code セッションでしか動かないので、
CI で回す意味がない。パターンを触ったときに手で走らせる。

**誤検出の側を重点的に見る。** 2026-08-02 に汎用パターンへ `checkout` を入れて
`git checkout` を全部止めた。誤検出でセッションが止まるとフックごと外され、
ゲートの価値がゼロになる。止め漏れより誤検出のほうが致命的。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).with_name("billing_gate.py")

# (コマンド, 止めるべきか)
CASES: tuple[tuple[str, bool], ...] = (
    # 素通しすべきもの — 日常的に使う開発コマンド
    ("git checkout -b cc/foo origin/main", False),
    ("git status --short", False),
    ("gh pr merge 36 --merge --auto", False),
    ("python -m pytest backend/tests -q", False),
    ("npm run build", False),
    ("npm run lint -- --fix", False),
    ("gh run download 123 -D /tmp/x", False),
    # 文言が紛らわしいだけのもの。コミットメッセージやコード中の語で止めない
    ("git commit -m 'checkout flow purchase plan'", False),
    # テスト実行は無料。net_guard が外部接続を遮断し、キーもダミー
    ("PYTHONPATH=./backend GOOGLE_API_KEY=dummy_key_for_ci python -m pytest -q", False),
    ("GEMINI_API_KEY=test-key python -m pytest backend/tests -q", False),
    # 読み取りだけの API 呼び出しは課金しない
    ("curl http://127.0.0.1:8000/health", False),
    ("curl http://127.0.0.1:8000/api/pipeline/status", False),
    # コマンドが**運んでいるデータ**で止めない。課金の話を書いただけのコミット・PR
    ("git commit -m 'fix: npm publish と gcloud billing をゲートで止める'", False),
    ('git commit -m "GOOGLE_API_KEY=realkey の実行を止める"', False),
    ("git commit -F - <<'EOF'\nnpm publish を止める\nstripe charges も\nEOF", False),
    ("gh pr create --body-file - <<'BODY'\ngcloud billing を deny する\nBODY", False),
    # 止めるべきもの — 実際に金が動く / 有料プランへの依存を生む
    ("gcloud billing accounts list", True),
    ("npm publish", True),
    ("gh api /user/subscriptions", True),
    ("gh billing actions", True),
    ("stripe charges create", True),
    ("gh api repos/o/r/branches/main/protection -X PUT", True),
    # 従量課金の API に実際に到達するもの（2026-08-02 追加）
    ("GOOGLE_API_KEY=AIzaSyRealLookingKey123 python backend/main.py", True),
    ("GEMINI_API_KEY=$MY_REAL_KEY python scripts/run_pipeline.py", True),
    ('curl -X POST http://127.0.0.1:8000/api/pipeline/start -d "{}"', True),
    ("Invoke-RestMethod -Uri http://localhost:8000/api/youtube/pre-plan -Method POST", True),
    ("curl http://127.0.0.1:8000/api/pipeline/start --json '{}'", True),
)


def _run(cmd: str) -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
    return subprocess.run(
        [sys.executable, str(HOOK)], input=payload,
        capture_output=True, text=True, encoding="utf-8",
    )


def _budget_cases() -> list[str]:
    """予算があるときは有料 API を通すこと。

    憲法第3条: 予算の範囲内は都度確認しない。ここが deny のままだと
    「計画段階で予算を取る」という運用が成立せず、実行のたびに止まる。
    """
    fails = []
    budget_path = HOOK.resolve().parents[1] / "budget.json"
    original = budget_path.read_text(encoding="utf-8")
    paid_cmd = 'curl -X POST http://127.0.0.1:8000/api/pipeline/start -d "{}"'

    try:
        data = json.loads(original)
        data["budgets"] = [{
            "id": "TEST", "purpose": "テスト", "approved_at": "2026-08-02",
            "limit_jpy": 500, "spent_jpy": 100, "status": "active",
        }]
        budget_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        out = _run(paid_cmd).stdout or ""
        ok = "permissionDecision" not in out and "残 400 円" in out
        print(f"{'ok  ' if ok else 'FAIL'} 予算内は通す（残額を提示する）")
        if not ok:
            fails.append("予算内")

        # 使い切った枠は無いのと同じ
        data["budgets"][0]["spent_jpy"] = 500
        budget_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        out = _run(paid_cmd).stdout or ""
        ok = "permissionDecision" in out
        print(f"{'ok  ' if ok else 'FAIL'} 使い切った予算は止める")
        if not ok:
            fails.append("予算超過")
    finally:
        budget_path.write_text(original, encoding="utf-8")
    return fails


def main() -> int:
    fails: list[str] = []
    for cmd, should_block in CASES:
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
        proc = subprocess.run(
            [sys.executable, str(HOOK)], input=payload,
            capture_output=True, text=True, encoding="utf-8",
        )
        blocked = "permissionDecision" in (proc.stdout or "")
        ok = blocked == should_block
        print(f"{'ok  ' if ok else 'FAIL'} block={blocked!s:<5} want={should_block!s:<5} {cmd}")
        if not ok:
            fails.append(cmd)

    # 壊れた入力は素通し（fail-open）。ここが deny だと Bash が全面的に死ぬ。
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input="not json",
        capture_output=True, text=True, encoding="utf-8",
    )
    open_ok = proc.returncode == 0 and not (proc.stdout or "").strip()
    print(f"{'ok  ' if open_ok else 'FAIL'} 壊れた入力は素通し")
    if not open_ok:
        fails.append("(壊れた入力)")

    fails += _budget_cases()

    print("\n判定:", "全件一致" if not fails else f"{len(fails)} 件不一致")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
