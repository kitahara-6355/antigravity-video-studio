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

# 2026-07-31: backend/tests/conftest.py にはあったが、こちら側には無かった。
# その結果このツリーのテストは path_resolver.writable_path() の振り向けを
# 受けず、本番ファイルをそのまま書き換えていた（実測: archives/council_logs、
# backend/branding）。設定の意図と注意点は backend/tests/conftest.py の
# 同じブロックに書いてある。
#
# 両方のツリーを続けて走らせたときに向き先が食い違わないよう、
# すでに設定されていれば尊重する（`if not ...` はそのための条件）。
if not os.environ.get("ANTIGRAVITY_WRITABLE_ROOT"):
    import tempfile
    _writable_root = tempfile.mkdtemp(prefix="antigravity_writable_")
    os.environ["ANTIGRAVITY_WRITABLE_ROOT"] = _writable_root
    # 書き込み先の親ディレクトリはここで作る。本番コード側で mkdir すると、
    # Path.stat を差し替えているテストで exist_ok の内部判定が壊れる。
    # `Human01_Official Artifact/` の配下も作る。orchestration のレポート出力は
    # `os.makedirs` を差し替えているテストから呼ばれることがあり、そこでは
    # 本番コード側の mkdir が効かない。従来はリポジトリ直下の同名ディレクトリが
    # 他のテストの汚染で既に存在していたため通っていた（＝汚染に依存していた）。
    for _sub in ("backend/usage_tracker", "backend/branding", "backend/data",
                 "backend/agents/orchestration",
                 "Human01_Official Artifact/受信トレイ",
                 "Human01_Official Artifact/サブエージェント体制報告",
                 "Human01_Official Artifact/サブエージェント体制報告/改善提案"):
        os.makedirs(os.path.join(_writable_root, *_sub.split("/")), exist_ok=True)
    # constitution / strategy / user_model は**設定でもある**ので、空のまま
    # にすると中身を読むテストが壊れる。本番の内容を複製して起点にする。
    # 書き込みは複製側に落ちるので、本番ファイルは汚れない。
    # ログ類（evolution_log など）は空から始めてよいので複製しない。
    import shutil as _shutil
    for _seed in ("constitution.json", "strategy.json", "user_model.json"):
        _src = os.path.join(project_root, "backend", "branding", _seed)
        if os.path.exists(_src):
            _shutil.copyfile(_src, os.path.join(_writable_root, "backend", "branding", _seed))
    # orchestration の状態ファイルも同じ理由で複製する。task_queue.json は
    # schema_version と tasks を持つ実データで、空だと読む側が壊れる。
    for _seed in ("task_queue.json", "flash_session.json", "resource_state.json",
                  "opus_session.json", "message_box.jsonl", "module_index.json",
                  "task_learning_cache.json", "harness_audit_status.json",
                  "harness_audit_log.jsonl"):
        _src = os.path.join(project_root, "backend", "agents", "orchestration", _seed)
        if os.path.exists(_src):
            _shutil.copyfile(
                _src,
                os.path.join(_writable_root, "backend", "agents", "orchestration", _seed),
            )
    # README.md は generate_subagent_reports がダッシュボード統計を
    # DASHBOARD_START/END の間へ同期する対象。実行するとリポジトリの
    # README が書き換わっていた。複製しておけば同期処理はそのまま動く。
    _readme = os.path.join(project_root, "README.md")
    if os.path.exists(_readme):
        _shutil.copyfile(_readme, os.path.join(_writable_root, "README.md"))


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
