"""
ルート tests ディレクトリ用テスト設定とフィクスチャ
"""
import sys
import os
import asyncio
import pytest

# パス設定: backend ディレクトリとプロジェクトルートを sys.path に追加
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
backend_dir = os.path.join(project_root, "backend")

# 2026-07-26: テストが本番の VERIFIED_FACTS.md を汚染するのを防ぐ。
# 詳細は backend/tests/conftest.py の同じ設定を参照。
if not os.environ.get("ANTIGRAVITY_VERIFIED_FACTS_DIR"):
    import tempfile
    os.environ["ANTIGRAVITY_VERIFIED_FACTS_DIR"] = tempfile.mkdtemp(
        prefix="antigravity_facts_"
    )


def _norm(p):
    return os.path.normcase(os.path.abspath(p))

# 既存の表記揺れを含む同一パスを sys.path から除外した上で先頭に挿入
sys.path = [p for p in sys.path if _norm(p) not in (_norm(backend_dir), _norm(project_root))]
sys.path.insert(0, backend_dir)
sys.path.insert(1, project_root)

# すでにインポートされている backend 関連モジュールをキャッシュから削除してローカルファイルを強制読み込み
import sys
to_delete = [name for name in list(sys.modules.keys()) if name.startswith("backend")]
for name in to_delete:
    del sys.modules[name]



# Windows asyncio IOCP ハング対策
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import backend.ux_verification.ratchet
print("DEBUG CONFTEST RATCHET PATH:", backend.ux_verification.ratchet.__file__)

from unittest.mock import MagicMock, patch

@pytest.fixture
def safe_popen_mock():
    """subprocess.Popenの安全なモック (GEMINI.md規約準拠)"""
    with patch('subprocess.Popen') as mock:
        proc = MagicMock()
        proc.poll.return_value = 0  # 即座に終了
        proc.returncode = 0
        proc.stdout.readline.return_value = ""  # 空文字列
        proc.stderr.readline.return_value = ""
        proc.communicate.return_value = ("", "")
        proc.wait.return_value = 0
        mock.return_value = proc
        yield mock


# ── テスト中の外部ネットワーク接続を遮断する（2026-07-26） ──
# 詳細は backend/tests/net_guard.py の docstring を参照。
@pytest.fixture(autouse=True)
def _block_external_network(request):
    from backend.tests.net_guard import install, uninstall

    if request.node.get_closest_marker("network"):
        yield
        return
    install()
    try:
        yield
    finally:
        uninstall()


# ---------------- 本番ファイル書き込みの検出 ----------------
# フック本体は backend/tests/fs_guard.py にある。rootdir がバッチ構成で変わるため、
# 複数の conftest から同じものを取り込む。install も報告も冪等。
#
# sys.path は触らないこと。tests/test_conftest.py がこのファイルの sys.path 操作を
# exec して検証しており、1要素でも足すと落ちる（CI で3件失敗した）。
# そのためファイルパス直接指定で読み込む。sys.modules に登録するので、
# 他の conftest から読まれても同じインスタンスを共有する（記録が分裂しない）。
import importlib.util as _ilu
import sys as _sys
from pathlib import Path as _Path

_fs_guard = _sys.modules.get("fs_guard")
if _fs_guard is None:
    _spec = _ilu.spec_from_file_location(
        "fs_guard",
        _Path(__file__).resolve().parent.parent / "backend" / "tests" / "fs_guard.py",
    )
    _fs_guard = _ilu.module_from_spec(_spec)
    _sys.modules["fs_guard"] = _fs_guard
    _spec.loader.exec_module(_fs_guard)

pytest_configure = _fs_guard.pytest_configure
pytest_runtest_setup = _fs_guard.pytest_runtest_setup
pytest_terminal_summary = _fs_guard.pytest_terminal_summary
pytest_unconfigure = _fs_guard.pytest_unconfigure
