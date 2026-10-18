"""テストの一時フォルダが、テストの終わりに片付くこと（2026-10-18）。

3つの conftest（リポジトリ直下・`tests/`・`backend/tests/`）は、本番の置き場を汚さない
ように一時フォルダを作って環境変数で振り向ける。そのフォルダが片付かず、10-05〜10-18 の
2週間で `antigravity_writable_*` などが各 2,922 個・計約20GB たまって、クラウドの作業場の
空きが 2.5GB まで減った（撮影データを取り込めなくなった）。

conftest を別の process で読み込み、その process が終わった後にフォルダが残っていないことを見る。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
KEYS = ("ANTIGRAVITY_VAULT_OUTPUTS", "ANTIGRAVITY_VERIFIED_FACTS_DIR", "ANTIGRAVITY_WRITABLE_ROOT")


def _made_dir(key: str, value: str) -> Path:
    """環境変数の値から、conftest が mkdtemp で作ったフォルダを返す（置き場は1段下の `vault-outputs`）。"""
    path = Path(value)
    return path.parent if key == "ANTIGRAVITY_VAULT_OUTPUTS" else path


@pytest.mark.parametrize("conftest, keys", [
    ("conftest.py", ("ANTIGRAVITY_VAULT_OUTPUTS",)),
    ("tests/conftest.py", KEYS),
    ("backend/tests/conftest.py", KEYS),
])
def test_conftest_removes_its_tempdirs_at_exit(conftest, keys, tmp_path):
    out = tmp_path / "paths.json"
    code = (
        "import json, os, runpy\n"
        f"runpy.run_path({str(REPO / conftest)!r})\n"
        f"paths = {{k: os.environ[k] for k in {keys!r}}}\n"
        "assert all(os.path.isdir(p) for p in paths.values()), paths\n"
        f"json.dump(paths, open({str(out)!r}, 'w'))\n"
    )
    env = {k: v for k, v in os.environ.items() if k not in KEYS}
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-3000:]
    paths = json.loads(out.read_text(encoding="utf-8"))
    assert set(paths) == set(keys)
    for key, value in paths.items():
        made = _made_dir(key, value)
        assert made.name.startswith("antigravity_"), value
        assert not made.exists(), f"{conftest}: {key} の一時フォルダ {made} が残った"


def test_conftest_keeps_tempdirs_it_did_not_make(tmp_path):
    """親の process が作って渡したフォルダは、子の process が終わっても消さない。"""
    given = {key: tmp_path / key.lower() for key in KEYS}
    for path in given.values():
        path.mkdir()
    code = f"import runpy\nrunpy.run_path({str(REPO / 'backend' / 'tests' / 'conftest.py')!r})\n"
    env = {**os.environ, **{k: str(v) for k, v in given.items()}}
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert all(path.is_dir() for path in given.values())


def test_mock_run_goes_inside_the_writable_root():
    """`create_approved_run` の偽の実行記録は、conftest が片付ける一時フォルダの中に作る。"""
    from tests.fixtures.mock_pipeline import create_approved_run

    run_dir = Path(create_approved_run())
    assert run_dir.is_dir()
    assert run_dir.parent == Path(os.environ["ANTIGRAVITY_WRITABLE_ROOT"])
