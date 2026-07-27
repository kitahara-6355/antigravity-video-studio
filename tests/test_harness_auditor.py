import os
import sys
import pytest
import subprocess
import runpy
import importlib
from unittest.mock import patch, MagicMock

import backend.agents.orchestration.harness_auditor as harness_auditor

def test_harness_auditor_basic(tmp_path):
    test_status_path = tmp_path / "harness_audit_status.json"
    harness_auditor.STATUS_PATH = str(test_status_path)
    
    # 正常系の基本的な呼び出し確認
    res = harness_auditor.run_audit("commit")
    assert isinstance(res, dict)
    assert "status" in res

def test_run_audit_invalid_category(tmp_path):
    test_status_path = tmp_path / "harness_audit_status.json"
    harness_auditor.STATUS_PATH = str(test_status_path)
    
    # 無効なカテゴリ指定時に ValueError が発生すること
    with pytest.raises(ValueError) as excinfo:
        harness_auditor.run_audit("invalid_cat")
    assert "無効な監査カテゴリ" in str(excinfo.value)

def test_run_audit_all_and_quarterly(tmp_path):
    test_status_path = tmp_path / "harness_audit_status.json"
    harness_auditor.STATUS_PATH = str(test_status_path)
    
    # "all" を指定して全項目が対象となること
    res_all = harness_auditor.run_audit("all")
    assert res_all["status"] in ("PASS", "FAIL")
    # "quarterly" を指定して全項目が対象となること
    res_quarterly = harness_auditor.run_audit("quarterly")
    assert res_quarterly["status"] in ("PASS", "FAIL")

def test_run_all_audits(tmp_path):
    test_status_path = tmp_path / "harness_audit_status.json"
    harness_auditor.STATUS_PATH = str(test_status_path)
    
    results = harness_auditor.run_all_audits()
    assert isinstance(results, dict)
    assert "commit" in results
    assert "deploy" in results

def test_load_save_status_exceptions(tmp_path):
    # load_status で JSONDecodeError が発生した場合
    test_status_path = tmp_path / "harness_audit_status.json"
    harness_auditor.STATUS_PATH = str(test_status_path)
    test_status_path.write_text("invalid json", encoding="utf-8")
    
    status = harness_auditor.load_status()
    assert status == {}
    
    # save_status で OSError が発生した場合
    with patch("builtins.open", side_effect=OSError("Write permission denied")):
        # 警告が出力されるだけで例外は発生しない
        harness_auditor.save_status({"test": "data"})

def test_run_audit_exception_handling(tmp_path):
    test_status_path = tmp_path / "harness_audit_status.json"
    harness_auditor.STATUS_PATH = str(test_status_path)
    
    # 監査関数実行中に例外が発生した場合 (globals 辞書の代わりに __dict__ を使用)
    with patch.dict(harness_auditor.__dict__, {"check_D01": MagicMock(side_effect=RuntimeError("Test Inner Error"))}):
        mock_tdr = MagicMock()
        with patch("backend.agents.orchestration.harness_auditor.TechnicalDebtStore", return_value=mock_tdr):
            res = harness_auditor.run_audit("commit")
            assert not res["details"]["D-01"]["success"]
            assert "Test Inner Error" in res["details"]["D-01"]["message"]
            mock_tdr.register_debt.assert_called_once()
            
        # TDR 登録で例外が発生した場合
        with patch("backend.agents.orchestration.harness_auditor.TechnicalDebtStore", side_effect=Exception("TDR Fail")):
            res = harness_auditor.run_audit("commit")
            assert not res["details"]["D-01"]["success"]

def test_run_audit_fatal_error(tmp_path):
    test_status_path = tmp_path / "harness_audit_status.json"
    harness_auditor.STATUS_PATH = str(test_status_path)
    
    # run_audit 自体の try ブロック内で致命的エラーが発生した場合
    with patch.object(harness_auditor, "AUDIT_ITEMS", new_callable=MagicMock) as mock_audit_items:
        mock_audit_items.values.side_effect = RuntimeError("Fatal AUDIT_ITEMS Error")
        
        mock_tdr = MagicMock()
        with patch("backend.agents.orchestration.harness_auditor.TechnicalDebtStore", return_value=mock_tdr):
            res = harness_auditor.run_audit("all")
            assert res["status"] == "FAIL"
            assert "Fatal AUDIT_ITEMS Error" in res["error"]
            mock_tdr.register_debt.assert_called_once()

        # TDR 自体が失敗した場合もカバー
        with patch("backend.agents.orchestration.harness_auditor.TechnicalDebtStore", side_effect=Exception("Fatal TDR Fail")):
            res = harness_auditor.run_audit("all")
            assert res["status"] == "FAIL"

def test_main_execution():
    # builtins.open をモックして UnicodeDecodeError および本番ファイルの読み書きを防ぐ
    with patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = "{}"
        
        # 引数なしの場合 (run_all_audits が呼ばれる)
        with patch("sys.argv", ["harness_auditor.py"]):
            runpy.run_module(
                "backend.agents.orchestration.harness_auditor",
                run_name="__main__"
            )

        # 引数 "all" の場合
        with patch("sys.argv", ["harness_auditor.py", "all"]):
            runpy.run_module(
                "backend.agents.orchestration.harness_auditor",
                run_name="__main__"
            )

        # 特定のカテゴリ引数の場合
        with patch("sys.argv", ["harness_auditor.py", "commit"]):
            runpy.run_module(
                "backend.agents.orchestration.harness_auditor",
                run_name="__main__"
            )

def test_sys_path_append_coverage():
    # sys.path に追加される処理 (19, 21行目) をカバーするために reload を行う
    removed_backend = False
    removed_root = False
    if harness_auditor.BACKEND_DIR in sys.path:
        sys.path.remove(harness_auditor.BACKEND_DIR)
        removed_backend = True
    if harness_auditor.PROJECT_ROOT in sys.path:
        sys.path.remove(harness_auditor.PROJECT_ROOT)
        removed_root = True
        
    try:
        importlib.reload(harness_auditor)
    finally:
        # sys.path を確実に元に戻す
        if removed_backend and harness_auditor.BACKEND_DIR not in sys.path:
            sys.path.append(harness_auditor.BACKEND_DIR)
        if removed_root and harness_auditor.PROJECT_ROOT not in sys.path:
            sys.path.append(harness_auditor.PROJECT_ROOT)

# ── check_XXX 個別監査関数のテスト ──

def test_check_H01():
    # 正常系: legacy 参照なし
    with patch("os.walk") as mock_walk, patch("builtins.open", create=True) as mock_open:
        mock_walk.return_value = [
            ("backend/routers", [], ["router.py"])
        ]
        mock_open.return_value.__enter__.return_value = ["class ModernRouter:\n", "    pass\n"]
        success, msg = harness_auditor.check_H01()
        assert success
        assert "0件" in msg

    # 異常系: legacy 参照あり
    with patch("os.walk") as mock_walk, patch("builtins.open", create=True) as mock_open:
        mock_walk.return_value = [
            ("backend/routers", [], ["router.py"])
        ]
        mock_open.return_value.__enter__.return_value = ["import SequentialAgent\n"]
        success, msg = harness_auditor.check_H01()
        assert not success
        assert "旧アーキテクチャ参照検出" in msg

    # 例外系: OSError
    with patch("os.walk") as mock_walk, patch("builtins.open", side_effect=OSError("Read error")):
        mock_walk.return_value = [
            ("backend/routers", [], ["router.py"])
        ]
        success, msg = harness_auditor.check_H01()
        assert success

    # パスが存在しない場合 (45行目 continue のカバー)
    with patch("os.path.exists", return_value=False):
        success, msg = harness_auditor.check_H01()
        assert success

def test_check_H02():
    # 正常系
    mock_registry = MagicMock()
    mock_registry.get_tools.return_value = ["t1", "t2"]
    
    mock_module = MagicMock()
    mock_module.tool_registry = mock_registry
    with patch.dict("sys.modules", {"backend.harness.tool_registry": mock_module}):
        success, msg = harness_auditor.check_H02()
        assert success
        assert "ロード成功" in msg

    # ターゲットのみを制限したインポートモック
    original_import = __import__
    def mock_import_importerror(name, *args, **kwargs):
        if name == "backend.harness.tool_registry":
            raise ImportError("Mock ImportError")
        return original_import(name, *args, **kwargs)

    def mock_import_exception(name, *args, **kwargs):
        if name == "backend.harness.tool_registry":
            raise Exception("Mock Exception")
        return original_import(name, *args, **kwargs)

    # ImportError
    with patch("builtins.__import__", side_effect=mock_import_importerror):
        with patch.dict("sys.modules", {"backend.harness.tool_registry": None}):
            success, msg = harness_auditor.check_H02()
            assert not success
            assert "インポートエラー" in msg

    # General Exception
    with patch("builtins.__import__", side_effect=mock_import_exception):
        with patch.dict("sys.modules", {"backend.harness.tool_registry": None}):
            success, msg = harness_auditor.check_H02()
            assert not success
            assert "実行エラー" in msg

def test_check_H03():
    with patch("os.path.exists", return_value=True):
        success, msg = harness_auditor.check_H03()
        assert success
        assert "記録を確認" in msg

    with patch("os.path.exists", return_value=False):
        success, msg = harness_auditor.check_H03()
        assert success
        assert "ログなし" in msg

def test_check_H04():
    # check_permission あり
    with patch("os.path.exists", return_value=True), patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = "def check_permission(): pass"
        success, msg = harness_auditor.check_H04()
        assert success
        assert "実装を確認" in msg

    # check_permission なし
    with patch("os.path.exists", return_value=True), patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = "class GovernanceEngine: pass"
        success, msg = harness_auditor.check_H04()
        assert success

    # OSError
    with patch("os.path.exists", return_value=True), patch("builtins.open", side_effect=OSError("Read error")):
        success, msg = harness_auditor.check_H04()
        assert success

def test_check_H05():
    # 正常系: 正しいJSON
    with patch("os.path.exists", return_value=True), patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = '{"session_id": "123"}'
        success, msg = harness_auditor.check_H05()
        assert success
        assert "読み込み成功" in msg

    # JSONDecodeError
    with patch("os.path.exists", return_value=True), patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = "invalid json"
        success, msg = harness_auditor.check_H05()
        assert not success
        assert "破損" in msg

    # OSError
    with patch("os.path.exists", return_value=True), patch("builtins.open", side_effect=OSError("Read error")):
        success, msg = harness_auditor.check_H05()
        assert not success
        assert "読み込み失敗" in msg

    # 一般例外
    with patch("os.path.exists", return_value=True), patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.side_effect = Exception("Unknown")
        success, msg = harness_auditor.check_H05()
        assert not success
        assert "予期せぬエラー" in msg

    # 未生成
    with patch("os.path.exists", return_value=False):
        success, msg = harness_auditor.check_H05()
        assert success
        assert "未生成" in msg

def test_check_M01():
    # 直接指定なし
    with patch("os.walk") as mock_walk, patch("builtins.open", create=True) as mock_open:
        mock_walk.return_value = [
            ("backend", [], ["helper.py"])
        ]
        mock_open.return_value.__enter__.return_value.read.return_value = "class MyModel: pass"
        success, msg = harness_auditor.check_M01()
        assert success
        assert "モデル直接指定なし" in msg

    # 直接指定あり (警告付きPASS)
    with patch("os.walk") as mock_walk, patch("builtins.open", create=True) as mock_open:
        mock_walk.return_value = [
            ("backend", [], ["helper.py"])
        ]
        mock_open.return_value.__enter__.return_value.read.return_value = "model = 'gemini-1.5-pro'"
        success, msg = harness_auditor.check_M01()
        assert success
        assert "モデル直接記述あり" in msg

    # OSError
    with patch("os.walk") as mock_walk, patch("builtins.open", side_effect=OSError("Read error")):
        mock_walk.return_value = [
            ("backend", [], ["helper.py"])
        ]
        success, msg = harness_auditor.check_M01()
        assert success

def test_check_M02():
    # _deprecation_map あり
    with patch("os.path.exists", return_value=True), patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = '{"_deprecation_map": {}}'
        success, msg = harness_auditor.check_M02()
        assert success
        assert "deprecation_map" in msg

    # 例外発生
    with patch("os.path.exists", return_value=True), patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = 'invalid json'
        success, msg = harness_auditor.check_M02()
        assert success
        assert "自動差替機構確認" in msg

def test_check_M03():
    with patch("os.path.exists", return_value=True):
        success, msg = harness_auditor.check_M03()
        assert success
        assert "存在を確認" in msg

    with patch("os.path.exists", return_value=False):
        success, msg = harness_auditor.check_M03()
        assert success

def test_check_C03():
    # ロード成功
    mock_optimizer = MagicMock()
    mock_module = MagicMock()
    mock_module.EvaluatorOptimizer = mock_optimizer
    with patch.dict("sys.modules", {"backend.harness.evaluator_optimizer": mock_module}):
        success, msg = harness_auditor.check_C03()
        assert success
        assert "ロード成功" in msg

    # ターゲット制限付きインポートモック
    original_import = __import__
    def mock_import_importerror(name, *args, **kwargs):
        if name == "backend.harness.evaluator_optimizer":
            raise ImportError("Mock ImportError")
        return original_import(name, *args, **kwargs)

    def mock_import_exception(name, *args, **kwargs):
        if name == "backend.harness.evaluator_optimizer":
            raise Exception("Mock Exception")
        return original_import(name, *args, **kwargs)

    # ImportError
    with patch("builtins.__import__", side_effect=mock_import_importerror):
        with patch.dict("sys.modules", {"backend.harness.evaluator_optimizer": None}):
            success, msg = harness_auditor.check_C03()
            assert success
            assert "未実装のためPASS" in msg

    # 一般例外
    with patch("builtins.__import__", side_effect=mock_import_exception):
        with patch.dict("sys.modules", {"backend.harness.evaluator_optimizer": None}):
            success, msg = harness_auditor.check_C03()
            assert not success
            assert "ロード失敗" in msg

def test_check_C04():
    with patch("os.path.exists", return_value=True):
        success, msg = harness_auditor.check_C04()
        assert success
        assert "RAW素材" in msg

    with patch("os.path.exists", return_value=False):
        success, msg = harness_auditor.check_C04()
        assert success

def test_check_C06():
    with patch("os.path.exists", return_value=True):
        success, msg = harness_auditor.check_C06()
        assert success
        assert "PROJECT_CONSTITUTION.md" in msg

    with patch("os.path.exists", return_value=False):
        success, msg = harness_auditor.check_C06()
        assert success

def test_check_D01():
    # テストファイルなし
    with patch("os.path.exists", return_value=False):
        success, msg = harness_auditor.check_D01()
        assert success
        assert "デフォルトPASS" in msg

    # pytest 正常終了
    mock_run = MagicMock()
    mock_run.returncode = 0
    with patch("os.path.exists", return_value=True), patch("subprocess.run", return_value=mock_run):
        success, msg = harness_auditor.check_D01()
        assert success
        assert "pytest 正常終了" in msg

    # pytest 失敗
    mock_run.returncode = 1
    mock_run.stdout = "Failed test"
    mock_run.stderr = ""
    with patch("os.path.exists", return_value=True), patch("subprocess.run", return_value=mock_run):
        success, msg = harness_auditor.check_D01()
        assert not success
        assert "pytest 失敗" in msg

    # TimeoutExpired
    with patch("os.path.exists", return_value=True), patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pytest", 30)):
        success, msg = harness_auditor.check_D01()
        assert not success
        assert "タイムアウト" in msg

    # 一般例外
    with patch("os.path.exists", return_value=True), patch("subprocess.run", side_effect=Exception("Unknown error")):
        success, msg = harness_auditor.check_D01()
        assert not success
        assert "テスト実行エラー" in msg

def test_check_D02():
    with patch("os.path.exists", return_value=True):
        success, msg = harness_auditor.check_D02()
        assert success
        assert "カバレッジデータ" in msg

    with patch("os.path.exists", return_value=False):
        success, msg = harness_auditor.check_D02()
        assert success

def test_check_D03():
    # ロード成功
    mock_coord = MagicMock()
    mock_module = MagicMock()
    mock_module.PipelineCoordinator = mock_coord
    with patch.dict("sys.modules", {"backend.agents.pipeline_coordinator": mock_module}):
        success, msg = harness_auditor.check_D03()
        assert success
        assert "ロード成功" in msg

    # ターゲット制限付きインポートモック
    original_import = __import__
    def mock_import_importerror(name, *args, **kwargs):
        if name == "backend.agents.pipeline_coordinator":
            raise ImportError("Mock ImportError")
        return original_import(name, *args, **kwargs)

    def mock_import_exception(name, *args, **kwargs):
        if name == "backend.agents.pipeline_coordinator":
            raise Exception("Mock Exception")
        return original_import(name, *args, **kwargs)

    # ImportError
    with patch("builtins.__import__", side_effect=mock_import_importerror):
        with patch.dict("sys.modules", {"backend.agents.pipeline_coordinator": None}):
            success, msg = harness_auditor.check_D03()
            assert not success
            assert "未ロード" in msg

    # 一般例外
    with patch("builtins.__import__", side_effect=mock_import_exception):
        with patch.dict("sys.modules", {"backend.agents.pipeline_coordinator": None}):
            success, msg = harness_auditor.check_D03()
            assert not success
            assert "ロードエラー" in msg

def test_check_D05():
    # 導入済み
    mock_module = MagicMock()
    with patch.dict("sys.modules", {"pytest_asyncio": mock_module}):
        success, msg = harness_auditor.check_D05()
        assert success
        assert "導入済み" in msg

    # ターゲット制限付きインポートモック
    original_import = __import__
    def mock_import_importerror(name, *args, **kwargs):
        if name == "pytest_asyncio":
            raise ImportError("Mock ImportError")
        return original_import(name, *args, **kwargs)

    # 未導入
    with patch("builtins.__import__", side_effect=mock_import_importerror):
        with patch.dict("sys.modules", {"pytest_asyncio": None}):
            success, msg = harness_auditor.check_D05()
            assert success

def test_check_E01():
    # APIキーなし
    with patch("os.walk") as mock_walk, patch("builtins.open", create=True) as mock_open:
        mock_walk.return_value = [
            ("backend", [], ["file.py"])
        ]
        mock_open.return_value.__enter__.return_value.read.return_value = "API_KEY = os.getenv('KEY')"
        success, msg = harness_auditor.check_E01()
        assert success
        assert "ハードコードなし" in msg

    # APIキーあり (長さ35文字を満たすように修正: AIzaSy + 35文字 = 41文字)
    with patch("os.walk") as mock_walk, patch("builtins.open", create=True) as mock_open:
        mock_walk.return_value = [
            ("backend", [], ["file.py"])
        ]
        mock_open.return_value.__enter__.return_value.read.return_value = "KEY = 'AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7R'"
        success, msg = harness_auditor.check_E01()
        assert not success
        assert "APIキー検出" in msg

    # OSError
    with patch("os.walk") as mock_walk, patch("builtins.open", side_effect=OSError("Read error")):
        mock_walk.return_value = [
            ("backend", [], ["file.py"])
        ]
        success, msg = harness_auditor.check_E01()
        assert success

def test_check_F02():
    with patch("os.path.exists", return_value=True):
        success, msg = harness_auditor.check_F02()
        assert success
        assert "model_config.json" in msg

    with patch("os.path.exists", return_value=False):
        success, msg = harness_auditor.check_F02()
        assert success

def test_check_P01():
    # format_segments あり
    with patch("os.path.exists", return_value=True), patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = "def format_segments(): pass"
        success, msg = harness_auditor.check_P01()
        assert success
        assert "format_segments 実装確認" in msg

    # format_segments なし
    with patch("os.path.exists", return_value=True), patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = "class Formatter: pass"
        success, msg = harness_auditor.check_P01()
        assert success

    # OSError
    with patch("os.path.exists", return_value=True), patch("builtins.open", side_effect=OSError("Read error")):
        success, msg = harness_auditor.check_P01()
        assert success

def test_check_P02():
    # retry あり
    with patch("os.path.exists", return_value=True), patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = "def retry_proofread(): pass"
        success, msg = harness_auditor.check_P02()
        assert success
        assert "retry 実装確認" in msg

    # retry なし
    with patch("os.path.exists", return_value=True), patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = "class Proofreader: pass"
        success, msg = harness_auditor.check_P02()
        assert success

    # OSError
    with patch("os.path.exists", return_value=True), patch("builtins.open", side_effect=OSError("Read error")):
        success, msg = harness_auditor.check_P02()
        assert success

def test_check_P06():
    with patch("os.path.exists", return_value=True):
        success, msg = harness_auditor.check_P06()
        assert success
        assert "audio_master.py" in msg

    with patch("os.path.exists", return_value=False):
        success, msg = harness_auditor.check_P06()
        assert success

def test_check_P08():
    # moviepy 参照なし
    with patch("os.walk") as mock_walk, patch("builtins.open", create=True) as mock_open:
        mock_walk.return_value = [
            ("backend", [], ["helper.py"])
        ]
        mock_open.return_value.__enter__.return_value = ["class Helper:\n", "    pass\n"]
        success, msg = harness_auditor.check_P08()
        assert success
        assert "0件" in msg

    # moviepy 参照あり
    with patch("os.walk") as mock_walk, patch("builtins.open", create=True) as mock_open:
        mock_walk.return_value = [
            ("backend", [], ["helper.py"])
        ]
        mock_open.return_value.__enter__.return_value = ["import moviepy\n"]
        success, msg = harness_auditor.check_P08()
        assert success
        assert "MoviePy実行コード参照あり" in msg

    # OSError
    with patch("os.walk") as mock_walk, patch("builtins.open", side_effect=OSError("Read error")):
        mock_walk.return_value = [
            ("backend", [], ["helper.py"])
        ]
        success, msg = harness_auditor.check_P08()
        assert success
