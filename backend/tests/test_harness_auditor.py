import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# プロジェクトルートを通す
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from backend.agents.orchestration.harness_auditor import run_audit, run_all_audits, VALID_CATEGORIES


def test_input_guardrail():
    """入力ガードレール: 無効なカテゴリを指定した際に ValueError が発生することを確認"""
    with pytest.raises(ValueError) as excinfo:
        run_audit("invalid_category")
    assert "無効な監査カテゴリ" in str(excinfo.value)


def test_quantitative_mapping():
    """定量的マッピング: 正常にスコアとステータスが計算されることを確認"""
    with patch("backend.agents.orchestration.harness_auditor.check_D01", return_value=(True, "Mock PASS")), \
         patch("backend.agents.orchestration.harness_auditor.check_E01", return_value=(True, "Mock PASS")):
        
        result = run_audit("commit")
        
        assert "status" in result
        assert "success_rate" in result
        assert result["status"] == "PASS"
        assert result["success_rate"] == 100.0
        assert result["passed"] == 2
        assert result["total"] == 2
        
        details = result.get("details", {})
        assert details["D-01"]["score"] == 1.0
        assert details["E-01"]["score"] == 1.0


def test_safety_fallback_and_tdr():
    """セーフティフォールバック: 例外発生時に FAIL が返り、TDR に登録されることを確認"""
    with patch("backend.agents.orchestration.harness_auditor.check_D01", side_effect=RuntimeError("Test Exception")), \
         patch("backend.agents.orchestration.harness_auditor.check_E01", return_value=(True, "Mock PASS")), \
         patch("backend.agents.orchestration.harness_auditor.TechnicalDebtStore") as mock_tdr_store:
        
        mock_instance = MagicMock()
        mock_tdr_store.return_value = mock_instance
        
        result = run_audit("commit")
        
        assert result["status"] == "FAIL"
        assert result["success_rate"] == 50.0
        assert result["passed"] == 1
        assert result["total"] == 2
        
        assert mock_instance.register_debt.called
        call_kwargs = mock_instance.register_debt.call_args[1]
        assert "AUDIT_EXCEPTION_D-01" in call_kwargs["pattern"]
        assert "MINOR_INFRA" == call_kwargs["category"]


def test_run_all_audits():
    """全監査の実行"""
    with patch("backend.agents.orchestration.harness_auditor.run_audit") as mock_run:
        mock_run.return_value = {"status": "PASS"}
        results = run_all_audits()
        assert len(results) == len(VALID_CATEGORIES)
        for cat in VALID_CATEGORIES:
            assert cat in results


def test_check_D01_branching():
    """check_D01 の各分岐と例外処理のテスト"""
    from backend.agents.orchestration.harness_auditor import check_D01
    
    with patch("os.path.exists", return_value=False):
        success, msg = check_D01()
        assert success is True
        assert "軽量テストファイル未検出" in msg

    mock_res = MagicMock(returncode=0, stdout="OK", stderr="")
    with patch("os.path.exists", return_value=True), \
         patch("subprocess.run", return_value=mock_res):
        success, msg = check_D01()
        assert success is True
        assert "pytest 正常終了" in msg

    mock_res_fail = MagicMock(returncode=1, stdout="FAIL", stderr="Error log")
    with patch("os.path.exists", return_value=True), \
         patch("subprocess.run", return_value=mock_res_fail):
        success, msg = check_D01()
        assert success is False
        assert "pytest 失敗" in msg

    import subprocess
    with patch("os.path.exists", return_value=True), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=30)):
        success, msg = check_D01()
        assert success is False
        assert "pytest タイムアウト" in msg

    with patch("os.path.exists", return_value=True), \
         patch("subprocess.run", side_effect=RuntimeError("Unexpected error")):
        success, msg = check_D01()
        assert success is False
        assert "テスト実行エラー" in msg


def test_check_E01_branching():
    """check_E01 の各分岐と例外処理のテスト"""
    from backend.agents.orchestration.harness_auditor import check_E01
    from unittest.mock import mock_open
    
    mock_file_content = "AIzaSy12345678901234567890123456789012345"
    with patch("os.walk") as mock_walk, \
         patch("builtins.open", mock_open(read_data=mock_file_content)):
        mock_walk.return_value = [
            ("backend/__pycache__", [], ["cache_file.py"]),
            ("backend/some_dir", [], ["not_python.txt", "key_file.py"])
        ]
        success, msg = check_E01()
        assert success is False
        assert "APIキー検出" in msg

    with patch("os.walk") as mock_walk, \
         patch("builtins.open", side_effect=PermissionError("Permission denied")):
        mock_walk.return_value = [
            ("backend/some_dir", [], ["key_file.py"])
        ]
        success, msg = check_E01()
        assert success is True
        assert "APIキーのハードコードなし" in msg


def test_check_H02_branching():
    """check_H02 の各分岐と例外処理のテスト"""
    from backend.agents.orchestration.harness_auditor import check_H02

    mock_registry = MagicMock()
    mock_registry.get_tools.return_value = ["tool1", "tool2"]
    with patch.dict("sys.modules", {"backend.harness.tool_registry": MagicMock(tool_registry=mock_registry)}):
        success, msg = check_H02()
        assert success is True
        assert "ToolRegistry ロード成功" in msg

    mock_registry_no_method = MagicMock(spec=[])
    with patch.dict("sys.modules", {"backend.harness.tool_registry": MagicMock(tool_registry=mock_registry_no_method)}):
        success, msg = check_H02()
        assert success is True
        assert "ToolRegistry ロード成功 (0 登録済み)" in msg

    with patch.dict("sys.modules", {"backend.harness.tool_registry": None}):
        success, msg = check_H02()
        assert success is False
        assert "ToolRegistry インポートエラー" in msg


def test_check_C03_branching():
    """check_C03 の各分岐と例外処理のテスト"""
    from backend.agents.orchestration.harness_auditor import check_C03

    with patch.dict("sys.modules", {"backend.harness.evaluator_optimizer": MagicMock()}):
        success, msg = check_C03()
        assert success is True
        assert "品質ゲートモジュール ロード成功" in msg

    with patch.dict("sys.modules", {"backend.harness.evaluator_optimizer": None}):
        success, msg = check_C03()
        assert success is True
        assert "品質ゲートモジュール 未実装のためPASS" in msg

    # 予期せぬ例外（ImportError以外）のテストを追加するために sys.modules に不正なオブジェクトを設定
    # （インポート時に ImportError 以外の例外を投げることは、組み込みインポートフックを介する必要があるため、
    #  ここではモジュール自体はモックを置き、ロード自体を失敗させるケースとして
    #  harness_auditorの check_C03 内でのインポート動作を直接 patch することで検証する）
    with patch("builtins.__import__", side_effect=RuntimeError("Unexpected load error")):
        success, msg = check_C03()
        assert success is False
        assert "品質ゲートモジュール ロード失敗" in msg


def test_check_C07():
    """check_C07 のテスト"""
    from backend.agents.orchestration.harness_auditor import check_C07
    success, msg = check_C07()
    assert success is True


def test_check_D03_branching():
    """check_D03 の各分岐と例外処理のテスト"""
    from backend.agents.orchestration.harness_auditor import check_D03

    with patch.dict("sys.modules", {"backend.agents.pipeline_coordinator": MagicMock()}):
        success, msg = check_D03()
        assert success is True
        assert "PipelineCoordinator ロード成功" in msg

    with patch.dict("sys.modules", {"backend.agents.pipeline_coordinator": None}):
        success, msg = check_D03()
        assert success is False
        assert "PipelineCoordinator 未ロード (ImportError)" in msg


def test_check_D05_branching():
    """check_D05 の各分岐と例外処理のテスト"""
    from backend.agents.orchestration.harness_auditor import check_D05

    with patch.dict("sys.modules", {"pytest_asyncio": MagicMock()}):
        success, msg = check_D05()
        assert success is True
        assert "pytest_asyncio 導入済み" in msg

    with patch.dict("sys.modules", {"pytest_asyncio": None}):
        success, msg = check_D05()
        assert success is True
        assert "pytest_asyncio 未導入" in msg


def test_check_H03_branching():
    """check_H03 のテスト"""
    from backend.agents.orchestration.harness_auditor import check_H03

    with patch("os.path.exists", return_value=True):
        success, msg = check_H03()
        assert success is True
        assert "Hookログの記録を確認" in msg

    with patch("os.path.exists", return_value=False):
        success, msg = check_H03()
        assert success is True
        assert "Hookログなし" in msg


def test_check_H04():
    """check_H04 のテスト"""
    from backend.agents.orchestration.harness_auditor import check_H04
    success, msg = check_H04()
    assert success is True


def test_check_H05_branching():
    """check_H05 の各分岐と例外処理のテスト"""
    from backend.agents.orchestration.harness_auditor import check_H05

    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", MagicMock()), \
         patch("json.load", return_value={"status": "OK"}):
        success, msg = check_H05()
        assert success is True
        assert "flash_session.json 読み込み成功" in msg

    import json
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", MagicMock()), \
         patch("json.load", side_effect=json.JSONDecodeError("Invalid JSON", "{}", 0)):
        success, msg = check_H05()
        assert success is False
        assert "flash_session.json 破損 (JSONDecodeError)" in msg

    # OSError のテストを追加
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=PermissionError("Permission Denied")):
        success, msg = check_H05()
        assert success is False
        assert "flash_session.json 読み込み失敗" in msg

    with patch("os.path.exists", return_value=False):
        success, msg = check_H05()
        assert success is True
        assert "flash_session.json 未生成" in msg


def test_check_H06():
    """check_H06 のテスト"""
    from backend.agents.orchestration.harness_auditor import check_H06
    success, msg = check_H06()
    assert success is True


def test_load_save_status_exceptions():
    """load_status / save_status 内の例外処理テスト"""
    from backend.agents.orchestration.harness_auditor import load_status, save_status

    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=PermissionError("No permission")):
        res = load_status()
        assert res == {}

    with patch("builtins.open", side_effect=PermissionError("No permission")):
        save_status({"test": "data"})


def test_run_audit_tdr_exception():
    """run_audit 内での TDR 登録エラー時の例外処理テスト"""
    from backend.agents.orchestration.harness_auditor import run_audit

    with patch("backend.agents.orchestration.harness_auditor.check_D01", side_effect=RuntimeError("Audit Error")), \
         patch("backend.agents.orchestration.harness_auditor.check_E01", return_value=(True, "Mock PASS")), \
         patch("backend.agents.orchestration.harness_auditor.TechnicalDebtStore", side_effect=RuntimeError("TDR Error")):
        
        result = run_audit("commit")
        assert result["status"] == "FAIL"


def test_run_audit_fatal_fallback():
    """run_audit 全体で例外が発生した場合のセーフティフォールバック処理テスト"""
    from backend.agents.orchestration.harness_auditor import run_audit

    # TRIGGER_MAPPING の key チェックで例外を発生させるために dict をモック
    mock_trigger_mapping = MagicMock()
    mock_trigger_mapping.__contains__.side_effect = RuntimeError("Fatal Trigger Mapping Error")

    with patch("backend.agents.orchestration.harness_auditor.TRIGGER_MAPPING", mock_trigger_mapping), \
         patch("backend.agents.orchestration.harness_auditor.TechnicalDebtStore") as mock_tdr_store:
        
        mock_instance = MagicMock()
        mock_tdr_store.return_value = mock_instance
        
        result = run_audit("commit")
        assert result["status"] == "FAIL"
        assert "Fatal Trigger Mapping Error" in result["error"]
        assert mock_instance.register_debt.called

    # TDR登録自体も失敗するケース
    mock_trigger_mapping_2 = MagicMock()
    mock_trigger_mapping_2.__contains__.side_effect = RuntimeError("Fatal Trigger Mapping Error")
    with patch("backend.agents.orchestration.harness_auditor.TRIGGER_MAPPING", mock_trigger_mapping_2), \
         patch("backend.agents.orchestration.harness_auditor.TechnicalDebtStore", side_effect=RuntimeError("TDR Fatal Error")):
        
        result = run_audit("commit")
        assert result["status"] == "FAIL"
        assert "Fatal Trigger Mapping Error" in result["error"]


def test_main_block():
    """__main__ ブロックの実行および引数分岐テスト"""
    import runpy
    import backend.agents.orchestration.harness_auditor as auditor
    auditor_path = auditor.__file__
    
    mock_res = MagicMock(returncode=0, stdout="OK", stderr="")
    
    mock_modules = {
        "backend.harness.tool_registry": MagicMock(),
        "backend.harness.evaluator_optimizer": MagicMock(),
        "pytest_asyncio": MagicMock(),
        "backend.agents.pipeline_coordinator": MagicMock(),
    }
    
    with patch("subprocess.run", return_value=mock_res), \
         patch("os.walk", return_value=[]), \
         patch("backend.agents.orchestration.harness_auditor.TechnicalDebtStore"), \
         patch("os.path.exists", return_value=False), \
         patch.dict("sys.modules", mock_modules):
        
        with patch("sys.argv", [auditor_path, "all"]):
            runpy.run_path(auditor_path, run_name="__main__")

        with patch("sys.argv", [auditor_path, "commit"]):
            runpy.run_path(auditor_path, run_name="__main__")

        with patch("sys.argv", [auditor_path]):
            runpy.run_path(auditor_path, run_name="__main__")


def test_new_categories_and_scans():
    """追加されたカテゴリ、およびチェック関数の動作検証"""
    from backend.agents.orchestration.harness_auditor import (
        check_H01, check_M01, check_P08, run_audit
    )

    # 1. check_H01 で旧アーキテクチャ参照が検出されるかテスト
    mock_file_content = "HARNESS_MODE = 'True'\nSequentialAgent"
    with patch("os.walk") as mock_walk, \
         patch("builtins.open", mock_open(read_data=mock_file_content)):
        mock_walk.return_value = [
            ("backend/routers", [], ["test_router.py"])
        ]
        success, msg = check_H01()
        assert success is False
        assert "旧アーキテクチャ参照検出" in msg

    # 2. check_M01 でモデル直接記述が検出されるかテスト
    mock_file_content_m01 = "model_name = 'gemini-1.5-pro'"
    with patch("os.walk") as mock_walk, \
         patch("builtins.open", mock_open(read_data=mock_file_content_m01)):
        mock_walk.return_value = [
            ("backend/agents", [], ["agent.py"])
        ]
        success, msg = check_M01()
        # 警告付きPASSのはず
        assert success is True
        assert "モデル直接記述あり" in msg

    # 3. check_P08 で MoviePy の残存参照が検出されるかテスト
    mock_file_content_p08 = "from moviepy.editor import *"
    with patch("os.walk") as mock_walk, \
         patch("builtins.open", mock_open(read_data=mock_file_content_p08)):
        mock_walk.return_value = [
            ("backend/engine", [], ["video.py"])
        ]
        success, msg = check_P08()
        # 警告付きPASS
        assert success is True
        assert "MoviePy実行コード参照あり" in msg

    # 4. 'all' カテゴリによる全57項目実行の確認
    # 各check関数はデフォルトでTrueを返すものが多いため、全チェックでエラーなく完了することを確認
    # pytest などの外部コマンド実行部分はモック
    with patch("backend.agents.orchestration.harness_auditor.check_D01", return_value=(True, "Mock PASS")), \
         patch("backend.agents.orchestration.harness_auditor.check_E01", return_value=(True, "Mock PASS")), \
         patch("backend.agents.orchestration.harness_auditor.check_H02", return_value=(True, "Mock PASS")), \
         patch("backend.agents.orchestration.harness_auditor.check_D03", return_value=(True, "Mock PASS")):
        
        res = run_audit("all")
        assert res["status"] == "PASS"
        assert res["total"] == 57
        assert res["passed"] == 57


from unittest.mock import mock_open
