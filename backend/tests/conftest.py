"""

テスト設定とフィクスチャ

推奨タスク N1: routersパッケージ構成
推奨タスク N2: テストFixture整備
"""

import sys
import types
# Pydantic hacks removed to avoid breaking RootModel construction in modern Pydantic v2.
import pytest
import sys
import os
import asyncio
from typing import Generator

print("DEBUG sys.path:", sys.path)

# パス設定
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.dirname(backend_dir)

def _norm(p):
    return os.path.normcase(os.path.abspath(p))

tests_dir = os.path.dirname(os.path.abspath(__file__))

# 2026-07-26: テストが本番の VERIFIED_FACTS.md を汚染するのを防ぐ。
# 記録されていた9件中8件が session-123 等のユニットテスト由来だった。
# GEMINI.md がこのファイルを「現在地を導出するソース」に指定しているため、
# 汚染は AI の状況認識を直接損なう。
# verified_facts モジュールが import される前に環境変数を設定する必要がある
# （保存先はモジュールレベル定数として解決されるため）。
if not os.environ.get("ANTIGRAVITY_VERIFIED_FACTS_DIR"):
    import tempfile
    os.environ["ANTIGRAVITY_VERIFIED_FACTS_DIR"] = tempfile.mkdtemp(
        prefix="antigravity_facts_"
    )

# 2026-07-31: テストが本番ファイルを書き換えるのを防ぐ。fs_guard の計測で、
# Git 追跡下の7ファイルが上書きされていた（backend/branding/ のブランド画像を含む）。
# 実行のたびに書き換わるファイルだけを一時ディレクトリへ振り向ける。
# path_resolver.writable_path() がこの変数を見る。
#
# `ANTIGRAVITY_BASE_DIR` ではなく専用の変数なのは、そちらを振り向けると
# model_config.json のような読み取り専用の設定まで振り向いて読めなくなるため。
#
# VERIFIED_FACTS と同様、モジュールレベルで設定する必要がある
# （保存先をモジュール定数として解決しているモジュールがあるため、import より前）。
if not os.environ.get("ANTIGRAVITY_WRITABLE_ROOT"):
    import tempfile
    os.environ["ANTIGRAVITY_WRITABLE_ROOT"] = tempfile.mkdtemp(
        prefix="antigravity_writable_"
    )

sys.path = [p for p in sys.path if _norm(p) not in (_norm(backend_dir), _norm(project_root))]
sys.path.insert(0, backend_dir)
if not os.environ.get("ISOLATE_BACKEND"):
    sys.path.insert(1, project_root)

# 2026-07-26: backend/tests/ を package 化（__init__.py 追加）したことで、
# pytest がこのディレクトリを自動で sys.path に入れなくなった。
# その結果 `from fixtures import ...` のような同ディレクトリ相対の import が
# 解決できなくなるため、明示的に追加する。
# package 化は tests/ と backend/tests/ のモジュール名衝突（94件）を
# ファイルを削除せずに解消するために必要だった。
if _norm(tests_dir) not in [_norm(p) for p in sys.path]:
    sys.path.insert(2, tests_dir)

# ─── SSL ハングアップ対策の先行モック ───
# ネットワーク経由での Gemini API クライアント初期化がインポート時に走るのを防ぐため、
# モジュールレベルでの get_gemini_client 呼び出しをあらかじめモック化する
from unittest.mock import patch, MagicMock
mock_genai_client = MagicMock()
patcher = patch("gemini_client_factory.get_gemini_client", return_value=mock_genai_client)
patcher.start()

# ValueError 回避のための Pydantic safe_import ハック
try:
    import pydantic._internal._model_construction as mc
    orig_import = mc.import_cached_base_model
    def safe_import():
        try:
            return orig_import()
        except (ValueError, KeyError, AttributeError):
            import inspect
            frame = inspect.currentframe()
            try:
                curr = frame
                while curr:
                    if curr.f_code.co_name == "__new__":
                        return object
                    curr = curr.f_back
            except Exception:
                pass
            finally:
                del frame
            return object
    
    # すでにインポートされているpydantic関連モジュール内の参照をすべて上書き
    import sys
    for name, mod in list(sys.modules.items()):
        if name.startswith('pydantic') and mod:
            if hasattr(mod, 'import_cached_base_model'):
                try:
                    setattr(mod, 'import_cached_base_model', safe_import)
                except Exception:
                    pass
    mc.import_cached_base_model = safe_import
except Exception:
    pass

# sys.path 変更後に pydantic.root_model をインポートして登録
import pydantic.root_model


# ─── Windows asyncio IOCP ハング対策 ───
# ProactorEventLoop は大量の async テスト実行後に IOCP ハンドルが残留し、
# 後続の async テスト（特に worker_contracts CT-02）でデッドロックを起こす。
# SelectorEventLoop に切り替えることで回避。テストではネットワークIOを使わないため安全。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def app():
    """FastAPIアプリケーションフィクスチャ"""
    # 遅延インポートで循環参照回避
    from main import app as fastapi_app
    return fastapi_app


@pytest.fixture(scope="session")
def client(app):
    """テストクライアントフィクスチャ"""
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def async_client(app):
    """非同期テストクライアント"""
    from httpx import AsyncClient
    from httpx import ASGITransport
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def mock_gemini():
    """Gemini APIモック"""
    from unittest.mock import MagicMock, patch
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "モックレスポンス"
    mock_client.models.generate_content.return_value = mock_response
    
    with patch('google.genai.Client', return_value=mock_client):
        yield mock_client


@pytest.fixture
def temp_cache():
    """一時キャッシュ"""
    from cache_manager import MemoryCache
    return MemoryCache(max_size=100, default_ttl=60)


@pytest.fixture
def temp_token_manager():
    """一時トークンマネージャー"""
    from websocket_handler import TokenManager
    return TokenManager()


@pytest.fixture
def sample_philosophy():
    """サンプル哲学データ"""
    return {
        "content": "視聴者の心を動かす編集を追求する",
        "source": "test",
        "extracted_at": "2026-01-11T00:00:00"
    }


@pytest.fixture
def sample_approval_request():
    """サンプル承認リクエスト"""
    return {
        "approved": True,
        "feedback": "",
        "timestamp": "2026-01-11T00:00:00"
    }


@pytest.fixture
def sample_error_report():
    """サンプルエラーレポート"""
    return {
        "error_type": "test_error",
        "message": "Test error for unit testing",
        "stack_trace": "File test.py, line 1",
        "context": {"test": True}
    }


@pytest.fixture(autouse=True)
def reset_singletons():
    """シングルトンリセット"""
    yield
    # テスト後のクリーンアップ
    from cache_manager import dispatch_cache, api_cache
    dispatch_cache.clear()
    api_cache.clear()


# pytest設定
def pytest_addoption(parser):
    """コマンドラインオプションの追加"""
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )


def pytest_configure(config):
    """pytest設定"""
    # テストが本番ファイルへ書き込むのを検出する（記録のみ・挙動は変えない）。
    # 詳細は fs_guard.py の docstring。
    import fs_guard

    fs_guard.install()

    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "e2e: marks end-to-end tests"
    )
    config.addinivalue_line(
        "markers", "worker: marks worker unit tests"
    )
    config.addinivalue_line(
        "markers", "fv: marks functional verification tests"
    )
    config.addinivalue_line(
        "markers", "fv_auto: marks automated FV tests (Category A)"
    )
    config.addinivalue_line(
        "markers", "fv_hybrid: marks hybrid FV tests (Category B)"
    )
    config.addinivalue_line(
        "markers", "fv_visual: marks visual/auditory FV tests (Category C)"
    )


# カバレッジ除外
def pytest_collection_modifyitems(config, items):
    """テスト収集時の処理"""
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(pytest.mark.skipif(
                not config.getoption("--runslow", default=False),
                reason="need --runslow option to run"
            ))


# ─── Phase 1 M1.1: モックファクトリ Fixture ───

@pytest.fixture
def mock_ctx():
    """標準モックPipelineContext (MD-03: 10セグメント)"""
    from fixtures.mock_pipeline import create_mock_ctx
    return create_mock_ctx(segments=10)


@pytest.fixture
def mock_ctx_empty():
    """空モックPipelineContext (MD-01: 0セグメント)"""
    from fixtures.mock_pipeline import create_mock_ctx
    return create_mock_ctx(segments=0)


@pytest.fixture
def mock_ctx_minimal():
    """最小モックPipelineContext (MD-02: 1セグメント)"""
    from fixtures.mock_pipeline import create_mock_ctx
    return create_mock_ctx(segments=1)


@pytest.fixture
def mock_ctx_large():
    """大量セグメント PipelineContext (MD-04: 50セグメント)"""
    from fixtures.mock_pipeline import create_mock_ctx
    return create_mock_ctx(segments=50)


@pytest.fixture
def mock_ctx_corrupt():
    """破損データ PipelineContext (MD-05)"""
    from fixtures.mock_pipeline import create_mock_ctx
    return create_mock_ctx(corrupt=True)


@pytest.fixture
def mock_ctx_type_error():
    """型不正データ PipelineContext (MD-06)"""
    from fixtures.mock_pipeline import create_mock_ctx
    return create_mock_ctx(type_error=True)


@pytest.fixture
def mock_ctx_long():
    """長尺データ PipelineContext (MD-07: 100セグメント)"""
    from fixtures.mock_pipeline import create_mock_ctx
    return create_mock_ctx(segments=100, duration_each=18.0)


@pytest.fixture
def tv01_path():
    """TV-01テスト動画パス（実ファイルが必要）"""
    from pathlib import Path as _Path
    p = _Path(__file__).parent.parent.parent / "test_videos" / "tv01_real_clip.mp4"
    if not p.exists():
        pytest.skip("TV-01テスト動画が未配置")
    return str(p)


# ─── Popen安全モックファクトリ ───
# 背景: subprocess.Popenをモックする際、poll()がNoneを返し続けると
# 内部のparse_progressスレッド（while process.poll() is None）が
# CPU 100%の無限ループに陥る。
# このファクトリは poll() が即座に終了コードを返す安全なモックを生成する。

@pytest.fixture
def safe_popen_mock():
    """
    subprocess.Popen の安全なモックファクトリ。

    使い方:
        def test_something(self, safe_popen_mock):
            proc = safe_popen_mock(returncode=0)
            with patch("module.subprocess.Popen", return_value=proc):
                ...

        # 失敗ケース:
            proc = safe_popen_mock(returncode=1, stderr_text="error msg")

    poll() は即座に returncode を返すため、
    parse_progress スレッド等の while process.poll() is None ループに入らない。
    """
    from unittest.mock import MagicMock

    def _factory(returncode=0, stderr_text="", stdout_text=""):
        proc = MagicMock()
        proc.poll.return_value = returncode      # ← 即座に終了（Noneを返さない）
        proc.returncode = returncode
        proc.wait.return_value = None
        proc.stderr.readline.return_value = stderr_text
        proc.stderr.read.return_value = stderr_text
        proc.stdout.readline.return_value = stdout_text
        proc.stdout.read.return_value = stdout_text
        proc.kill.return_value = None
        proc.terminate.return_value = None
        return proc

    return _factory


# ── テスト中の外部ネットワーク接続を遮断する（2026-07-26） ──
# モックが外れたテストが実ネットワークへ出ると接続待ちで止まり、
# pytest-timeout（Windows は thread 方式）が発動してプロセスごと落ちる。
# 1件のハングでテスト結果もカバレッジも失われるため、接続自体を禁止して
# 即座の失敗に変える。詳細は backend/tests/net_guard.py を参照。
@pytest.fixture(autouse=True)
def _block_external_network(request):
    from net_guard import install, uninstall

    if request.node.get_closest_marker("network"):
        yield
        return
    install()
    try:
        yield
    finally:
        uninstall()


# ---------------- 本番ファイル書き込みの検出 ----------------
# フック本体は fs_guard.py にある。rootdir がバッチ構成で変わるため、
# 複数の conftest から同じものを取り込む。install も報告も冪等。
from fs_guard import (  # noqa: E402, F401
    pytest_runtest_setup,
    pytest_terminal_summary,
    pytest_unconfigure,
)
