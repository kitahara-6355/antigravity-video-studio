"""Tests for OrchestrationHub.trigger_quality_fix() method.

Task 3 で追加した trigger_quality_fix() API のテスト。
QualityFeedbackTrigger をモックして、orchestrator 内のロジックのみ検証。
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import backend.services.quality_feedback_trigger
import backend.agents.orchestration.orchestrator

import pytest
from unittest.mock import patch, MagicMock


class TestTriggerQualityFix:
    """OrchestrationHub.trigger_quality_fix() のテスト"""

    def _make_hub(self):
        """OrchestrationHub を最小限の依存で生成"""
        with patch("backend.agents.orchestration.orchestrator._read_json", return_value={}):
            from backend.agents.orchestration.orchestrator import OrchestrationHub
            hub = OrchestrationHub.__new__(OrchestrationHub)
        return hub

    @patch("backend.services.quality_feedback_trigger.QualityFeedbackTrigger")
    def test_triggered_returns_details(self, MockTrigger):
        mock_instance = MockTrigger.return_value
        mock_instance.evaluate_and_trigger.return_value = {
            "triggered": True,
            "low_axes": ["audio_balance", "cut_rhythm"],
            "tasks_created": 2,
            "details": "2軸が閾値以下: audio_balance, cut_rhythm → bug_hunterタスク2件生成",
        }
        hub = self._make_hub()
        score_report = {"overall_score": 55.0, "axes": []}

        result = hub.trigger_quality_fix(score_report)

        assert result is not None
        assert "2軸" in result
        mock_instance.evaluate_and_trigger.assert_called_once_with(score_report)

    @patch("backend.services.quality_feedback_trigger.QualityFeedbackTrigger")
    def test_not_triggered_returns_none(self, MockTrigger):
        mock_instance = MockTrigger.return_value
        mock_instance.evaluate_and_trigger.return_value = {
            "triggered": False,
            "low_axes": [],
            "tasks_created": 0,
            "details": "",
        }
        hub = self._make_hub()
        score_report = {"overall_score": 90.0, "axes": []}

        result = hub.trigger_quality_fix(score_report)

        assert result is None

    @patch("backend.services.quality_feedback_trigger.QualityFeedbackTrigger")
    def test_logger_called_on_trigger(self, MockTrigger):
        mock_instance = MockTrigger.return_value
        mock_instance.evaluate_and_trigger.return_value = {
            "triggered": True,
            "low_axes": ["timing_accuracy"],
            "tasks_created": 1,
            "details": "1軸が閾値以下",
        }
        hub = self._make_hub()

        with patch("backend.agents.orchestration.hub_batch.logger") as mock_logger:
            hub.trigger_quality_fix({"overall_score": 40.0, "axes": []})
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert "Quality fix triggered" in call_args[0][0]
