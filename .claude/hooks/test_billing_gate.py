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
    # 止めるべきもの — 実際に金が動く / 有料プランへの依存を生む
    ("gcloud billing accounts list", True),
    ("npm publish", True),
    ("gh api /user/subscriptions", True),
    ("gh billing actions", True),
    ("stripe charges create", True),
    ("gh api repos/o/r/branches/main/protection -X PUT", True),
)


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

    print("\n判定:", "全件一致" if not fails else f"{len(fails)} 件不一致")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
