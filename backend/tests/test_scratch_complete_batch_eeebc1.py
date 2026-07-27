# -*- coding: utf-8 -*-
import os
import sys
import runpy
from unittest.mock import patch, MagicMock

# プロジェクトルートを sys.path に追加してインポートエラーを回避
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import backend.agents.orchestration

def test_complete_batch_eeebc1_execution():
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub_instance = MagicMock()
        mock_hub_class.return_value = mock_hub_instance
        runpy.run_module("backend.scratch.complete_batch_eeebc1", run_name="__main__")
        assert mock_hub_instance.mark_task_done.call_count == 6
        calls = mock_hub_instance.mark_task_done.call_args_list
        assert calls[0][0][0] == "T-batch_eeebc1-thumbnail-000"
        assert calls[0][0][1] == "pass"
        assert calls[0][0][2]["coverage_improvement"] == "100%"
        assert calls[5][0][0] == "T-batch_eeebc1-thumbnail-005"
        assert calls[5][0][1] == "pass"
        assert calls[5][0][2]["message"] == "ux_verification/quality_gates/fake_pass_detector.py: \u30ab\u30d0\u30ec\u30c3\u30b898%\u9054\u6210\u300190\u4ef6\u306e\u30c6\u30b9\u30c8PASS"
        mock_hub_instance.submit_batch_report.assert_called_once_with(
            "batch_eeebc1",
            {
                "passed": 6,
                "failed": 0,
                "total": 6
            }
        )
