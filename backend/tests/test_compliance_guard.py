"""
DesignComplianceGuard の単体テスト (test_compliance_guard.py)
"""

import os
import tempfile
import json
import pytest
from pathlib import Path
from backend.agents.orchestration.compliance_guard import DesignComplianceGuard

def test_compliance_guard_parse_requirements(tmp_path):
    # verifies: REQ-COMP-01
    # ダミーの設計計画書の作成
    dummy_plan = tmp_path / "dummy_plan.md"
    dummy_plan.write_text("""
# 設計書タイトル

## 要件定義
| 要件ID | 定義 |
| :--- | :--- |
| **REQ-COMP-01** | パース要件1 |
| **REQ-COMP-02** | パース要件2 |
| **REQ-OTHER-01**| その他要件 |
""", encoding="utf-8")

    guard = DesignComplianceGuard(workspace_path=str(tmp_path), plan_path=str(dummy_plan))
    reqs = guard.parse_requirements()
    
    assert "REQ-COMP-01" in reqs
    assert "REQ-COMP-02" in reqs
    assert "REQ-OTHER-01" in reqs
    assert len(reqs) == 3

def test_compliance_guard_scan_codebase(tmp_path):
    # verifies: REQ-COMP-02
    # verifies: REQ-COMP-03
    # ダミーのワークスペースとコード・テストファイルの作成
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True, exist_ok=True)
    
    # satisfiesタグを含むソースコード
    dummy_src = backend_dir / "dummy_module.py"
    dummy_src.write_text("""
# satisfies: REQ-COMP-01
# satisfies: REQ-COMP-02
def dummy_func():
    pass
""", encoding="utf-8")

    # verifiesタグを含むテストコード
    dummy_test = backend_dir / "test_dummy.py"
    dummy_test.write_text("""
# verifies: REQ-COMP-01
# verifies: REQ-COMP-02
def test_dummy():
    pass
""", encoding="utf-8")

    guard = DesignComplianceGuard(workspace_path=str(tmp_path))
    # scan_codebase 内で self.backend_dir = self.workspace_path / "backend" が使われる
    scan = guard.scan_codebase()
    
    assert "REQ-COMP-01" in scan["satisfies"]
    assert "REQ-COMP-02" in scan["satisfies"]
    assert scan["satisfies"]["REQ-COMP-01"][0]["file"] == "backend/dummy_module.py"
    
    assert "REQ-COMP-01" in scan["verifies"]
    assert "REQ-COMP-02" in scan["verifies"]
    assert scan["verifies"]["REQ-COMP-01"][0]["file"] == "backend/test_dummy.py"

def test_compliance_guard_evaluate_compliance(tmp_path):
    # verifies: REQ-COMP-04
    # ダミー設計書とコードベースを組み合わせて乖離計算をテスト
    dummy_plan = tmp_path / "dummy_plan.md"
    dummy_plan.write_text("""
| 要件ID | 定義 |
| :--- | :--- |
| **REQ-TEST-01** | 要件1（実装・検証済） |
| **REQ-TEST-02** | 要件2（実装済・未検証） |
| **REQ-TEST-03** | 要件3（未実装・検証済） |
| **REQ-TEST-04** | 要件4（未実装・未検証） |
""", encoding="utf-8")

    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True, exist_ok=True)
    
    src = backend_dir / "src.py"
    src.write_text("""
# satisfies: REQ-TEST-01
# satisfies: REQ-TEST-02
""", encoding="utf-8")

    test = backend_dir / "test_src.py"
    test.write_text("""
# verifies: REQ-TEST-01
# verifies: REQ-TEST-03
""", encoding="utf-8")

    guard = DesignComplianceGuard(workspace_path=str(tmp_path), plan_path=str(dummy_plan))
    report = guard.evaluate_compliance()
    
    assert report["total_requirements"] == 4
    
    # REQ-TEST-01: 準拠
    assert report["requirements"]["REQ-TEST-01"]["compliant"] is True
    # REQ-TEST-02: 実装あり・検証なし
    assert report["requirements"]["REQ-TEST-02"]["implemented"] is True
    assert report["requirements"]["REQ-TEST-02"]["verified"] is False
    assert report["requirements"]["REQ-TEST-02"]["compliant"] is False
    
    # メトリクス検証
    # 実装率: 2/4 = 50.0%
    assert report["metrics"]["implementation_pct"] == 50.0
    # 検証率: 2/4 = 50.0%
    assert report["metrics"]["verification_pct"] == 50.0
    # 総合準拠率: 1/4 = 25.0%
    assert report["metrics"]["compliance_pct"] == 25.0
    
    # 乖離一覧の確認
    assert "REQ-TEST-03" in report["unimplemented"]
    assert "REQ-TEST-04" in report["unimplemented"]
    assert "REQ-TEST-02" in report["unverified"]
    assert "REQ-TEST-04" in report["unverified"]
    
    # 総合合格判定
    assert report["passed"] is False

def test_compliance_guard_markdown_generation(tmp_path):
    # verifies: REQ-COMP-06
    dummy_plan = tmp_path / "dummy_plan.md"
    dummy_plan.write_text("""
| REQ-TEST-01 | テスト要件 |
""", encoding="utf-8")

    guard = DesignComplianceGuard(workspace_path=str(tmp_path), plan_path=str(dummy_plan))
    md = guard.generate_report_markdown()
    
    assert "設計乖離度分析" in md
    assert "REQ-TEST-01" in md

def test_compliance_guard_init_and_no_plan(tmp_path):
    # plan_pathを渡さず、workspace_path直下に implementation_plan.md を配置して初期化
    dummy_plan = tmp_path / "implementation_plan.md"
    dummy_plan.write_text("REQ-AUTO-DETECT", encoding="utf-8")

    guard = DesignComplianceGuard(workspace_path=str(tmp_path))
    assert guard.plan_path == dummy_plan
    
    # 存在しない計画書パスを設定して初期化
    non_existent_plan = tmp_path / "non_existent_plan.md"
    guard_none = DesignComplianceGuard(workspace_path=str(tmp_path), plan_path=str(non_existent_plan))
    reqs = guard_none.parse_requirements()
    assert len(reqs) == 0

    # ルートディレクトリで初期化し、ループ内の親フォルダ判定でのbreakをカバーする
    import platform
    root_path = "C:\\" if platform.system() == "Windows" else "/"
    guard_root = DesignComplianceGuard(workspace_path=root_path)
    assert guard_root.workspace_path == Path(root_path)

def test_compliance_guard_parse_requirements_edge_cases(tmp_path):
    # "REQ-ID" の除外確認
    dummy_plan = tmp_path / "dummy_plan.md"
    dummy_plan.write_text("""
| REQ-TEST-01 |
| REQ-ID |
""", encoding="utf-8")
    
    guard = DesignComplianceGuard(workspace_path=str(tmp_path), plan_path=str(dummy_plan))
    reqs = guard.parse_requirements()
    assert "REQ-TEST-01" in reqs
    assert "REQ-ID" not in reqs

    # OSError のハンドリングテスト
    from unittest.mock import patch
    with patch("builtins.open", side_effect=OSError("Fake IO Error")):
        reqs_err = guard.parse_requirements()
        assert len(reqs_err) == 0

def test_compliance_guard_scan_codebase_edge_cases(tmp_path):
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True, exist_ok=True)
    
    # .py 以外のファイルを配置して無視されることを確認する
    dummy_txt = backend_dir / "readme.txt"
    dummy_txt.write_text("# satisfies: REQ-COMP-01", encoding="utf-8")
    
    guard = DesignComplianceGuard(workspace_path=str(tmp_path))
    scan = guard.scan_codebase()
    assert "REQ-COMP-01" not in scan["satisfies"]

    # OSError のハンドリングテスト
    # satisfiesタグを含むファイルを配置
    dummy_src = backend_dir / "dummy_module.py"
    dummy_src.write_text("# satisfies: REQ-COMP-01", encoding="utf-8")
    
    from unittest.mock import patch
    # dummy_module.pyのオープン時に例外を発生させる
    original_open = open
    def mock_open(file, *args, **kwargs):
        if "dummy_module.py" in str(file):
            raise OSError("Fake Read Error")
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", mock_open):
        scan_err = guard.scan_codebase()
        assert "REQ-COMP-01" not in scan_err["satisfies"]

def test_compliance_guard_evaluate_compliance_empty(tmp_path):
    dummy_plan = tmp_path / "dummy_plan.md"
    dummy_plan.write_text("No requirements here", encoding="utf-8")
    
    guard = DesignComplianceGuard(workspace_path=str(tmp_path), plan_path=str(dummy_plan))
    report = guard.evaluate_compliance()
    assert report["total_requirements"] == 0
    assert report["metrics"]["compliance_pct"] == 100.0
    assert report["passed"] is True

def test_compliance_guard_markdown_generation_passed(tmp_path):
    dummy_plan = tmp_path / "dummy_plan.md"
    dummy_plan.write_text("""
| REQ-TEST-01 | テスト要件 |
""", encoding="utf-8")

    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True, exist_ok=True)
    
    src = backend_dir / "src.py"
    src.write_text("# satisfies: REQ-TEST-01", encoding="utf-8")

    test = backend_dir / "test_src.py"
    test.write_text("# verifies: REQ-TEST-01", encoding="utf-8")

    guard = DesignComplianceGuard(workspace_path=str(tmp_path), plan_path=str(dummy_plan))
    md = guard.generate_report_markdown()
    
    assert "設計乖離度分析" in md
    assert "REQ-TEST-01" in md
    assert "すべての設計要件に対する実装およびテストによる検証が完了" in md
    assert "`src.py`" in md
    assert "`test_src.py` (T)" in md

def test_compliance_guard_main_execution(tmp_path):
    import runpy
    from unittest.mock import patch, MagicMock

    dummy_plan = tmp_path / "dummy_plan.md"
    dummy_plan.write_text("""
| REQ-TEST-01 | テスト要件 |
""", encoding="utf-8")

    guard = DesignComplianceGuard(workspace_path=str(tmp_path), plan_path=str(dummy_plan))
    mock_class = MagicMock(return_value=guard)
    
    with patch("backend.agents.orchestration.compliance_guard.DesignComplianceGuard", mock_class), \
         patch("builtins.print") as mock_print:
        # run_name="__main__" でモジュールを実行する
        runpy.run_module("backend.agents.orchestration.compliance_guard", run_name="__main__")
        
        # printが呼ばれたことを確認
        assert mock_print.called



