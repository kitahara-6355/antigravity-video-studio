"""Tests for QualityFeedbackTrigger class.

backend/services/quality_feedback_trigger.py のユニットテスト。
"""
import sys
import os
import math
import json
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.services.quality_feedback_trigger import (
    QualityFeedbackTrigger,
    _safe_float,
    TASK_QUEUE_PATH,
    QUALITY_SCORE_HISTORY_PATH,
)


class TestSafeFloat:
    """_safe_float 関数のテスト"""

    def test_valid_float(self):
        assert _safe_float(75.5, 60.0) == 75.5
        assert _safe_float("80.0", 60.0) == 80.0
        assert _safe_float(50, 60.0) == 50.0

    def test_none_value(self):
        assert _safe_float(None, 60.0) == 60.0

    def test_nan_or_inf(self):
        assert _safe_float(float("nan"), 60.0) == 60.0
        assert _safe_float(float("inf"), 60.0) == 60.0
        assert _safe_float(float("-inf"), 60.0) == 60.0

    def test_na_string(self):
        assert _safe_float("N/A", 60.0) == 60.0

    def test_invalid_string(self):
        assert _safe_float("invalid", 60.0) == 60.0

    def test_invalid_type(self):
        assert _safe_float([], 60.0) == 60.0

    def test_overflow_value(self):
        assert _safe_float(10**1000, 60.0) == 60.0

    def test_uncomparable_object(self):
        class Uncomparable:
            def __eq__(self, other):
                raise RuntimeError("Cannot compare")
            def __ne__(self, other):
                raise RuntimeError("Cannot compare")
        assert _safe_float(Uncomparable(), 60.0) == 60.0


class TestQualityFeedbackTriggerEvaluation:
    """evaluate_and_trigger メソッドのテスト"""

    def test_invalid_report_format(self):
        trigger = QualityFeedbackTrigger()
        result = trigger.evaluate_and_trigger("not a dict")
        assert result["triggered"] is False
        assert "無効なスコアレポート形式" in result["details"]

    def test_invalid_axes_format(self):
        trigger = QualityFeedbackTrigger()
        result = trigger.evaluate_and_trigger({"axes": "not a list"})
        assert result["triggered"] is False
        assert "axesがリスト形式ではない" in result["details"]

    def test_invalid_axis_elements(self):
        trigger = QualityFeedbackTrigger()
        report = {
            "axes": [
                "not a dict",
                {"name": "字幕タイミング精度", "score": 50.0},
            ]
        }
        with patch.object(trigger, "_inject_tasks", return_value=1) as mock_inject, \
             patch.object(trigger, "_record_score") as mock_record:
            result = trigger.evaluate_and_trigger(report)
            assert result["triggered"] is True
            assert result["tasks_created"] == 1
            assert result["low_axes"] == ["字幕タイミング精度"]

    def test_axis_without_name(self):
        trigger = QualityFeedbackTrigger()
        report = {
            "axes": [
                {"score": 50.0},  # name なし
            ]
        }
        with patch.object(trigger, "_record_score") as mock_record:
            result = trigger.evaluate_and_trigger(report)
            assert result["triggered"] is False
            assert "全軸閾値以上" in result["details"]

    def test_axis_grade_na(self):
        trigger = QualityFeedbackTrigger()
        report = {
            "axes": [
                {"name": "字幕タイミング精度", "score": 50.0, "grade": "N/A"},
            ]
        }
        with patch.object(trigger, "_record_score") as mock_record:
            result = trigger.evaluate_and_trigger(report)
            assert result["triggered"] is False
            assert "全軸閾値以上" in result["details"]

    def test_all_axes_above_threshold(self):
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = {
            "axes": [
                {"name": "字幕タイミング精度", "score": 75.0, "threshold": 60.0},
                {"name": "音量バランス", "score": 80.0},
            ]
        }
        with patch.object(trigger, "_record_score") as mock_record:
            result = trigger.evaluate_and_trigger(report)
            assert result["triggered"] is False
            assert result["tasks_created"] == 0
            mock_record.assert_called_once_with(report, triggered=False)

    def test_axes_below_threshold(self):
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = {
            "axes": [
                {"name": "字幕タイミング精度", "score": 55.0, "threshold": 60.0, "suggestion": "タイミング調整"},
                {"name": "音量バランス", "score": 80.0},
            ]
        }
        with patch.object(trigger, "_inject_tasks", return_value=1) as mock_inject, \
             patch.object(trigger, "_record_score") as mock_record:
            result = trigger.evaluate_and_trigger(report)
            assert result["triggered"] is True
            assert result["low_axes"] == ["字幕タイミング精度"]
            assert result["tasks_created"] == 1
            mock_inject.assert_called_once()
            mock_record.assert_called_once_with(report, triggered=True, tasks_count=1)

            # 注入されたタスクの構造を検証
            injected_tasks = mock_inject.call_args[0][0]
            assert len(injected_tasks) == 1
            task = injected_tasks[0]
            assert task["group"] == "bug_hunter"
            assert task["level"] == "L2"
            assert "字幕タイミング精度" in task["instruction"]
            assert "55.0/100.0" in task["instruction"]
            assert "改善提案: タイミング調整" in task["instruction"]
            assert task["target_module"] == "antigravity_pipeline.py"
            assert task["status"] == "pending"
            assert task["source"] == "quality_feedback_trigger"
            assert task["axis_name"] == "字幕タイミング精度"
            assert task["axis_score"] == 55.0

    def test_unexpected_exception_handling(self):
        class BadDict(dict):
            def get(self, key, default=None):
                raise RuntimeError("Mocked unexpected error")

        trigger = QualityFeedbackTrigger()
        report = BadDict()

        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is False
        assert "評価中にエラーが発生しました" in result["details"]

    def test_non_string_axis_name(self):
        trigger = QualityFeedbackTrigger()
        report = {
            "axes": [
                {"name": ["not", "a", "string"], "score": 50.0},
                {"name": 12345, "score": 50.0},
                {"name": "字幕タイミング精度", "score": 50.0},
            ]
        }
        with patch.object(trigger, "_inject_tasks", return_value=1) as mock_inject, \
             patch.object(trigger, "_record_score") as mock_record:
            result = trigger.evaluate_and_trigger(report)
            assert result["triggered"] is True
            assert result["tasks_created"] == 1
            assert result["low_axes"] == ["字幕タイミング精度"]

    def test_axis_to_module_non_string(self):
        assert QualityFeedbackTrigger._axis_to_module(["not", "a", "string"]) is None
        assert QualityFeedbackTrigger._axis_to_module(12345) is None


class TestQualityFeedbackTriggerInjectTasks:
    """_inject_tasks メソッドのテスト"""

    def test_invalid_tasks_type(self):
        trigger = QualityFeedbackTrigger()
        with pytest.raises(TypeError):
            trigger._inject_tasks("not a list")

    def test_invalid_task_elements(self):
        trigger = QualityFeedbackTrigger()
        with pytest.raises(TypeError):
            trigger._inject_tasks(["not a dict"])

    def test_successful_injection(self, tmp_path):
        queue_file = tmp_path / "task_queue.json"
        trigger = QualityFeedbackTrigger()

        # パスを一時ファイルに変更
        with patch("backend.services.quality_feedback_trigger.TASK_QUEUE_PATH", queue_file):
            tasks = [
                {
                    "group": "bug_hunter",
                    "instruction": "Test instruction",
                    "target_module": "test.py",
                    "status": "pending",
                }
            ]
            count = trigger._inject_tasks(tasks)
            assert count == 1

            # ファイルが正しく作成されたか確認
            assert queue_file.exists()
            with open(queue_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            assert "tasks" in data
            assert len(data["tasks"]) == 1
            injected_task = data["tasks"][0]
            assert injected_task["instruction"] == "Test instruction"
            assert injected_task["id"].startswith("T-")
            assert "created_at" in injected_task

    def test_injection_with_existing_queue(self, tmp_path):
        queue_file = tmp_path / "task_queue.json"
        initial_data = {
            "current_batch_id": "batch_123",
            "tasks": [
                {
                    "id": "T-batch_123-qf-existing",
                    "group": "bug_hunter",
                    "instruction": "Existing task",
                    "status": "pending",
                }
            ]
        }
        queue_file.write_text(json.dumps(initial_data, ensure_ascii=False), encoding="utf-8")

        trigger = QualityFeedbackTrigger()
        with patch("backend.services.quality_feedback_trigger.TASK_QUEUE_PATH", queue_file):
            tasks = [
                {
                    "group": "bug_hunter",
                    "instruction": "New task",
                    "status": "pending",
                }
            ]
            count = trigger._inject_tasks(tasks)
            assert count == 1

            with open(queue_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            assert len(data["tasks"]) == 2
            assert data["tasks"][0]["instruction"] == "Existing task"
            assert data["tasks"][1]["instruction"] == "New task"
            assert "batch_123" in data["tasks"][1]["id"]

    def test_injection_retry_on_json_decode_error(self, tmp_path):
        queue_file = tmp_path / "task_queue.json"
        # 最初は壊れたJSON、次は空ファイル
        queue_file.write_text("{broken json", encoding="utf-8")

        trigger = QualityFeedbackTrigger()
        with patch("backend.services.quality_feedback_trigger.TASK_QUEUE_PATH", queue_file):
            # ファイルサイズが0より大きいとリトライに入って、そのまま失敗すると例外を投げる
            # ここではリトライされることを確認するため、openのモックなどを使ってテストする
            
            # json.loadが最初の2回 JSONDecodeError を投げ、3回目に成功するシナリオをモック
            mock_open = MagicMock()
            
            # モックされたファイルデータ
            file_data_sequence = [
                "{invalid json",
                "{invalid json",
                '{"tasks": []}'
            ]
            
            # json.load をモックする
            original_load = json.load
            call_count = 0
            
            def mock_json_load(fp):
                nonlocal call_count
                call_count += 1
                if call_count <= 2:
                    raise json.JSONDecodeError("Expecting value", "", 0)
                return {"tasks": []}

            with patch("backend.services.quality_feedback_trigger.json.load", side_effect=mock_json_load), \
                 patch("backend.services.quality_feedback_trigger.time.sleep") as mock_sleep:
                
                # 最初は壊れたJSONファイルを存在させる
                queue_file.write_text("{broken json", encoding="utf-8")
                
                tasks = [{"group": "bug_hunter", "instruction": "Test"}]
                count = trigger._inject_tasks(tasks)
                assert count == 1
                assert call_count == 3
                assert mock_sleep.call_count == 2


class TestQualityFeedbackTriggerRecordScore:
    """_record_score メソッドのテスト"""

    def test_invalid_report_type(self):
        trigger = QualityFeedbackTrigger()
        # 例外が発生するが、内部でキャッチされて処理は続行する
        with patch("backend.services.quality_feedback_trigger.logger") as mock_logger:
            trigger._record_score("not a dict", triggered=False)
            mock_logger.warning.assert_called_once()

    def test_successful_record(self, tmp_path):
        history_file = tmp_path / "quality_score_history.jsonl"
        trigger = QualityFeedbackTrigger()

        with patch("backend.services.quality_feedback_trigger.QUALITY_SCORE_HISTORY_PATH", history_file):
            report = {"overall_score": 85.0, "overall_grade": "A"}
            trigger._record_score(report, triggered=False)

            assert history_file.exists()
            lines = history_file.read_text(encoding="utf-8").splitlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["overall_score"] == 85.0
            assert data["overall_grade"] == "A"
            assert data["triggered"] is False
            assert "timestamp" in data
