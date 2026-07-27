# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from backend.agents.orchestration import OrchestrationHub

def test_generate_phase_report_with_string_result(tmp_path):
    """
    タスクの result フィールドが辞書ではなく文字列になっている場合に、
    _generate_phase_report が AttributeError を起こさずに安全に処理できるかをテストする。
    """
    orchestrator = OrchestrationHub()
    
    # 状態のモックデータ
    mock_state = {
        "current_phase": 27,
        "metrics": {
            "coverage_pct": 85.0,
            "test_count": 1000,
            "critical_debt": 0
        }
    }
    
    # タスクの result が str になっているモックレポートデータ
    mock_reports = [
        {
            "batch_id": "batch_test_123",
            "phase": 27,
            "metrics": {
                "coverage_pct": 84.5,
                "test_count": 980,
                "critical_debt": 0
            },
            "results": {"passed": 1, "failed": 1},
            "tasks": [
                {
                    "id": "T-test-001",
                    "status": "pass",
                    "target_module": "services/cross_media_service.py",
                    "instruction": "テスト指示書",
                    "result": "文字列形式の実行結果メッセージ" # ここが辞書ではなく文字列になっている！
                },
                {
                    "id": "T-test-002",
                    "status": "fail",
                    "target_module": "services/cross_media_service.py",
                    "instruction": "失敗テスト指示書",
                    "result": "文字列形式の失敗エラーメッセージ" # 失敗タスクで文字列になっている！
                }
            ]
        }
    ]
    
    # 依存関数および INBOX_DIR をモックしてテスト用の一時ディレクトリに出力させる
    with patch("backend.agents.orchestration.hub_reports._read_json", return_value=mock_state), \
         patch("backend.agents.orchestration.hub_reports._read_jsonl", return_value=mock_reports), \
         patch("backend.agents.orchestration.hub_reports.INBOX_DIR", tmp_path):
        
        # 実行。修正前はここで AttributeError: 'str' object has no attribute 'get' が発生する。
        report_path = orchestrator._generate_phase_report(27)
        
        # レポートファイルが正常に生成されたことを確認
        assert Path(report_path).exists()
        
        # レポートの中身に元の文字列が含まれていることを確認
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "文字列形式の実行結果メッセージ" in content
            assert "その他のエラー**: 1 件" in content


def test_generate_phase_report_with_malformed_results(tmp_path):
    """
    results フィールドが辞書ではなかったり、tasksに辞書型以外が混入しているなど、
    極端に破損したレポートデータがある場合でも、_generate_phase_report が安全に動作するかテストする。
    """
    orchestrator = OrchestrationHub()
    
    mock_state = {
        "current_phase": 27,
        "metrics": {
            "coverage_pct": 85.0,
            "test_count": 1000,
            "critical_debt": 0
        }
    }
    
    mock_reports = [
        {
            "batch_id": "batch_test_456",
            "phase": 27,
            "metrics": {
                "coverage_pct": 84.5,
                "test_count": 980,
                "critical_debt": 0
            },
            "results": "破損したresults文字列",  # 辞書ではない！
            "tasks": [
                "破損したタスク文字列",  # 辞書ではない！
                {
                    "id": "T-test-003",
                    "status": "pass",
                    "target_module": "services/cross_media_service.py",
                    "instruction": "テスト指示書",
                    "result": None
                }
            ]
        }
    ]
    
    with patch("backend.agents.orchestration.hub_reports._read_json", return_value=mock_state),          patch("backend.agents.orchestration.hub_reports._read_jsonl", return_value=mock_reports),          patch("backend.agents.orchestration.hub_reports.INBOX_DIR", tmp_path):
        
        report_path = orchestrator._generate_phase_report(27)
        assert Path(report_path).exists()
