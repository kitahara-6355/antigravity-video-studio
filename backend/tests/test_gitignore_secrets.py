"""Google の認証情報が git に入らないこと（.gitignore の回帰防止）。

2026-10-04、`scripts/google_oauth_login.py --readonly` が作る
`token_raw_readonly.json` がどのパターンにも当たらず、`git add -A` で
コミットされうる状態だった。このリポジトリは Public なので、名前の
付け方が変わっても塞がっていることを実際に `git check-ignore` で確かめる。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (_ROOT / ".git").exists(),
    reason="git のチェックアウトでのみ確かめられる",
)


@pytest.mark.parametrize("path", [
    "backend/data/google/token.json",
    "backend/data/google/token_raw_readonly.json",
    "backend/data/google/client_secret.json",
    "backend/data/google/anything_else.json",
    "token_raw_readonly.json",
])
def test_google_credentials_are_ignored(path):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path],
        cwd=_ROOT, capture_output=True, check=False,
    )
    assert result.returncode == 0, f"{path} が .gitignore で無視されていない"
