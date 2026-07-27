"""
tests/conftest.py のユニットテスト
"""
import sys
import os
import asyncio
from unittest.mock import patch, MagicMock

# conftest.py の絶対パス
CONFTEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests",
    "conftest.py"
)

def run_conftest_code(globals_dict=None):
    """conftest.py を exec で実行する。

    conftest.py は起動時に sys.modules から backend.* を削除する。そのまま exec すると
    他テストが既に import / monkeypatch 済みのモジュールまで巻き添えで消え、
    後続テストのパッチが効かなくなる（2026-07-25 実測で87件が連鎖失敗）。
    テスト間の汚染を防ぐため、backend.* の登録状態を退避して復元する。
    """
    if globals_dict is None:
        globals_dict = {}

    globals_dict.update({
        "__file__": CONFTEST_PATH,
        "__name__": "tests.conftest",
    })

    with open(CONFTEST_PATH, "r", encoding="utf-8") as f:
        code = f.read()

    saved_modules = {k: v for k, v in sys.modules.items() if k.startswith("backend")}
    try:
        exec(code, globals_dict)
    finally:
        # exec 中に再 import されたものを取り除き、元のモジュールオブジェクトを戻す。
        # 同一オブジェクトを復元することで、既存の monkeypatch が生き続ける。
        for name in [k for k in sys.modules if k.startswith("backend")]:
            if name not in saved_modules:
                del sys.modules[name]
        sys.modules.update(saved_modules)

def test_conftest_path_injection_when_not_in_path():
    # project_root と backend_dir を特定
    tests_dir = os.path.dirname(CONFTEST_PATH)
    project_root = os.path.dirname(tests_dir)
    backend_dir = os.path.join(project_root, "backend")
    
    # 既存の sys.path からこれらを除外した状態の sys.path をモックする
    mock_path = [p for p in sys.path if os.path.normcase(p) not in (os.path.normcase(backend_dir), os.path.normcase(project_root))]
    
    with patch.object(sys, "path", mock_path):
        run_conftest_code()
        
        # 挿入されたことを確認
        assert os.path.normcase(sys.path[0]) == os.path.normcase(backend_dir)
        assert os.path.normcase(sys.path[1]) == os.path.normcase(project_root)

def test_conftest_path_injection_when_already_in_path():
    tests_dir = os.path.dirname(CONFTEST_PATH)
    project_root = os.path.dirname(tests_dir)
    backend_dir = os.path.join(project_root, "backend")
    
    # 既に sys.path に入っている状態の sys.path をモックする
    mock_path = [backend_dir, project_root]
    
    with patch.object(sys, "path", mock_path):
        initial_len = len(sys.path)
        run_conftest_code()
        
        # 重複して追加されていないことを確認
        assert len(sys.path) == initial_len
        assert sys.path == [backend_dir, project_root]

def test_conftest_win32_policy():
    # WindowsSelectorEventLoopPolicy は Windows にしか存在しないため、
    # create=True で非 Windows でも patch できるようにする。
    # これによりロジック自体は全プラットフォームで検証できる。
    with patch("sys.platform", "win32"), \
         patch("asyncio.set_event_loop_policy") as mock_set_policy, \
         patch("asyncio.WindowsSelectorEventLoopPolicy", create=True) as mock_policy_class:
        
        run_conftest_code()
        
        mock_policy_class.assert_called_once()
        mock_set_policy.assert_called_once_with(mock_policy_class.return_value)

def test_conftest_non_win32_policy():
    with patch("sys.platform", "linux"), \
         patch("asyncio.set_event_loop_policy") as mock_set_policy:
        
        run_conftest_code()
        
        mock_set_policy.assert_not_called()

def test_conftest_path_injection_with_casing_and_separator_variation():
    tests_dir = os.path.dirname(CONFTEST_PATH)
    project_root = os.path.dirname(tests_dir)
    backend_dir = os.path.join(project_root, "backend")
    
    # 大文字小文字やスラッシュ・バックスラッシュが異なる表記を作成
    var_backend_dir = backend_dir.lower().replace("\\", "/")
    var_project_root = project_root.lower().replace("\\", "/")
    
    # 表記の異なるパスがすでに入っている状態の sys.path をモックする
    mock_path = [var_backend_dir, var_project_root]
    
    with patch.object(sys, "path", mock_path):
        initial_len = len(sys.path)
        run_conftest_code()
        
        # 表記が異なっていても実質的に同一であるため、重複して追加されないことを確認
        assert len(sys.path) == initial_len
        # 正規化された綺麗なパス表記に置き換わっていることを確認
        assert [os.path.normcase(p) for p in sys.path] == [os.path.normcase(backend_dir), os.path.normcase(project_root)]



def test_run_conftest_code_does_not_evict_backend_modules():
    """conftest.py の exec 実行が sys.modules の backend.* を巻き添えにしないこと。

    回帰防止: conftest.py は起動時に backend.* を sys.modules から削除する。
    それを exec で再実行すると、既に他テストが import / monkeypatch 済みの
    モジュールが消え、後続テストのパッチが効かなくなる（2026-07-25 実測で87件失敗）。

    検証には conftest 自身が再 import しないモジュールを使う。
    conftest 末尾の `import backend.ux_verification.ratchet` は復活するため不適。
    """
    import backend.harness.governance  # noqa: F401

    before = {k for k in sys.modules if k.startswith("backend")}
    assert "backend.harness.governance" in before, "前提: 対象モジュールが読み込まれていること"

    run_conftest_code()

    after = {k for k in sys.modules if k.startswith("backend")}
    evicted = before - after
    assert not evicted, f"conftest 実行で backend モジュールが消えた: {sorted(evicted)[:5]}"
