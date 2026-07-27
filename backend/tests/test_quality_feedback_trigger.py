"""QualityFeedbackTrigger のユニットテスト。

TASK_QUEUE_PATH / QUALITY_SCORE_HISTORY_PATH をモンキーパッチで
tmp_path に差し替え、実ファイルを汚染しない。
"""
import json
import pytest
from pathlib import Path

from services.quality_feedback_trigger import (
    QualityFeedbackTrigger,
)
import services.quality_feedback_trigger as qft_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def _patch_paths(tmp_path, monkeypatch):
    """TASK_QUEUE_PATH と QUALITY_SCORE_HISTORY_PATH を tmp_path に差し替える。"""
    fake_queue = tmp_path / "task_queue.json"
    fake_history = tmp_path / "quality_score_history.jsonl"
    monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)
    monkeypatch.setattr(qft_module, "QUALITY_SCORE_HISTORY_PATH", fake_history)
    return fake_queue, fake_history


def _make_report(axes: list, overall_score: float = 80.0) -> dict:
    """テスト用スコアレポートを生成するヘルパー。"""
    return {
        "overall_score": overall_score,
        "overall_grade": "B" if overall_score >= 60 else "C",
        "axes": axes,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestQualityFeedbackTriggerInstantiation:
    """テスト1: インスタンス化の基本検証。"""

    def test_default_threshold(self):
        trigger = QualityFeedbackTrigger()
        assert trigger.threshold == 60.0

    def test_custom_threshold(self):
        trigger = QualityFeedbackTrigger(threshold=75.0)
        assert trigger.threshold == 75.0


class TestEvaluateNoTrigger:
    """テスト2: 全軸閾値以上 → triggered=False。"""

    @pytest.mark.usefixtures("_patch_paths")
    def test_all_axes_above_threshold(self, _patch_paths):
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"name": "字幕タイミング精度", "score": 85.0, "max_score": 100},
            {"name": "音量バランス", "score": 70.0, "max_score": 100},
        ])
        result = trigger.evaluate_and_trigger(report)

        assert result["triggered"] is False
        assert result["low_axes"] == []
        assert result["tasks_created"] == 0

    @pytest.mark.usefixtures("_patch_paths")
    def test_empty_axes(self, _patch_paths):
        """軸が空の場合も triggered=False。"""
        trigger = QualityFeedbackTrigger()
        result = trigger.evaluate_and_trigger(_make_report([]))
        assert result["triggered"] is False


class TestEvaluateWithTrigger:
    """テスト3: 閾値以下の軸あり → triggered=True + タスク生成。"""

    @pytest.mark.usefixtures("_patch_paths")
    def test_one_axis_below_threshold(self, _patch_paths):
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"name": "字幕タイミング精度", "score": 45.0, "max_score": 100,
             "suggestion": "タイミング調整が必要"},
            {"name": "音量バランス", "score": 80.0, "max_score": 100},
        ])
        result = trigger.evaluate_and_trigger(report)

        assert result["triggered"] is True
        assert result["low_axes"] == ["字幕タイミング精度"]
        assert result["tasks_created"] == 1

    @pytest.mark.usefixtures("_patch_paths")
    def test_multiple_axes_below_threshold(self, _patch_paths):
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"name": "字幕タイミング精度", "score": 30.0, "max_score": 100},
            {"name": "音量バランス", "score": 50.0, "max_score": 100},
            {"name": "テロップ可読性", "score": 90.0, "max_score": 100},
        ])
        result = trigger.evaluate_and_trigger(report)

        assert result["triggered"] is True
        assert len(result["low_axes"]) == 2
        assert result["tasks_created"] == 2

    @pytest.mark.usefixtures("_patch_paths")
    def test_axis_uses_own_threshold_field(self, _patch_paths):
        """軸に threshold フィールドがある場合、それを使う。"""
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"name": "音量バランス", "score": 75.0, "max_score": 100,
             "threshold": 80.0},  # 軸固有閾値 80 → 75 < 80 でトリガー
        ])
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is True
        assert result["tasks_created"] == 1


class TestInjectTasks:
    """テスト4: _inject_tasks が task_queue.json にタスクを追加する。"""

    def test_inject_to_empty_queue(self, tmp_path, monkeypatch):
        fake_queue = tmp_path / "task_queue.json"
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)

        trigger = QualityFeedbackTrigger()
        tasks = [
            {"group": "bug_hunter", "instruction": "test task 1"},
            {"group": "bug_hunter", "instruction": "test task 2"},
        ]
        count = trigger._inject_tasks(tasks)

        assert count == 2
        assert fake_queue.exists()
        data = json.loads(fake_queue.read_text(encoding="utf-8"))
        assert len(data["tasks"]) == 2
        # 各タスクに id, created_at が付与されている
        for t in data["tasks"]:
            assert t["id"].startswith("T-")
            assert "created_at" in t

    def test_inject_to_existing_queue(self, tmp_path, monkeypatch):
        fake_queue = tmp_path / "task_queue.json"
        existing = {"current_batch_id": "B42", "tasks": [{"id": "T-old"}]}
        fake_queue.write_text(json.dumps(existing), encoding="utf-8")
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)

        trigger = QualityFeedbackTrigger()
        count = trigger._inject_tasks([{"group": "bug_hunter", "instruction": "new"}])

        assert count == 1
        data = json.loads(fake_queue.read_text(encoding="utf-8"))
        assert len(data["tasks"]) == 2  # 既存1 + 新規1
        assert data["tasks"][-1]["id"].startswith("T-B42-qf-")


class TestAxisToModule:
    """テスト5: _axis_to_module が正しいモジュールを返す。"""

    @pytest.mark.parametrize("axis_name,expected", [
        ("字幕タイミング精度", "antigravity_pipeline.py"),
        ("字幕表示時間", "antigravity_pipeline.py"),
        ("テロップ可読性", "services/gen_telops.py"),
        ("音量バランス", "services/audio_master.py"),
        ("カット割りリズム", "services/video_editor_engine.py"),
        ("未知の軸", None),
    ])
    def test_mapping(self, axis_name: str, expected):
        assert QualityFeedbackTrigger._axis_to_module(axis_name) == expected


class TestRecordScore:
    """テスト6: _record_score が quality_score_history.jsonl に記録する。"""

    def test_record_appends_jsonl(self, tmp_path, monkeypatch):
        fake_history = tmp_path / "quality_score_history.jsonl"
        monkeypatch.setattr(qft_module, "QUALITY_SCORE_HISTORY_PATH", fake_history)

        trigger = QualityFeedbackTrigger()
        report = _make_report([], overall_score=72.5)

        trigger._record_score(report, triggered=False)
        trigger._record_score(report, triggered=True, tasks_count=3)

        lines = fake_history.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

        rec1 = json.loads(lines[0])
        assert rec1["overall_score"] == 72.5
        assert rec1["triggered"] is False
        assert rec1["tasks_created"] == 0

        rec2 = json.loads(lines[1])
        assert rec2["triggered"] is True
        assert rec2["tasks_created"] == 3

    def test_record_creates_parent_dir(self, tmp_path, monkeypatch):
        """親ディレクトリが存在しない場合でも自動作成される。"""
        fake_history = tmp_path / "subdir" / "deep" / "history.jsonl"
        monkeypatch.setattr(qft_module, "QUALITY_SCORE_HISTORY_PATH", fake_history)

        trigger = QualityFeedbackTrigger()
        trigger._record_score(_make_report([]), triggered=False)

        assert fake_history.exists()


class TestInjectTasksException:
    """テスト7: _inject_tasks で例外が発生した場合の検証。"""

    def test_inject_tasks_exception_raises(self, monkeypatch):
        trigger = QualityFeedbackTrigger()

        def mock_open(*args, **kwargs):
            raise RuntimeError("Mocked I/O error")

        import builtins
        monkeypatch.setattr(builtins, "open", mock_open)

        with pytest.raises(RuntimeError):
            trigger._inject_tasks([{"group": "bug_hunter"}])

    def test_inject_tasks_os_error_raises(self, monkeypatch):
        trigger = QualityFeedbackTrigger()

        def mock_open(*args, **kwargs):
            raise OSError("Mocked OS error")

        import builtins
        monkeypatch.setattr(builtins, "open", mock_open)

        with pytest.raises(OSError):
            trigger._inject_tasks([{"group": "bug_hunter"}])

    def test_inject_tasks_json_decode_error_empty_file(self, tmp_path, monkeypatch):
        """空ファイル（サイズ0）の場合は、JSONパースエラーになっても新規ファイルとして扱い、
        例外を発生させずにタスクを注入できること。"""
        fake_queue = tmp_path / "task_queue.json"
        fake_queue.write_text("", encoding="utf-8")  # 空ファイル
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)

        trigger = QualityFeedbackTrigger()
        count = trigger._inject_tasks([{"group": "bug_hunter", "instruction": "new"}])

        assert count == 1
        data = json.loads(fake_queue.read_text(encoding="utf-8"))
        assert len(data["tasks"]) == 1


class TestRecordScoreOSError:
    """テスト8: _record_score で OSError が発生した場合の検証。"""

    def test_record_score_oserror_suppressed(self, monkeypatch):
        trigger = QualityFeedbackTrigger()

        def mock_open(*args, **kwargs):
            raise OSError("Mocked OS error")

        import builtins
        monkeypatch.setattr(builtins, "open", mock_open)

        report = _make_report([], overall_score=50.0)
        # OSError は pass されるため、クラッシュせずに正常終了する
        trigger._record_score(report, triggered=False)


class TestEvaluateInvalidScores:
    """テスト9: score が None や "N/A" などの非数値型である場合の安全性の検証。"""

    @pytest.mark.usefixtures("_patch_paths")
    def test_score_is_none(self, _patch_paths):
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"name": "字幕タイミング精度", "score": None, "max_score": 100},
        ])
        # This will crash without fix
        result = trigger.evaluate_and_trigger(report)
        assert "triggered" in result

    @pytest.mark.usefixtures("_patch_paths")
    def test_score_is_na_string(self, _patch_paths):
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"name": "字幕タイミング精度", "score": "N/A", "max_score": 100},
        ])
        result = trigger.evaluate_and_trigger(report)
        assert "triggered" in result

    @pytest.mark.usefixtures("_patch_paths")
    def test_score_missing_field(self, _patch_paths):
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"name": "字幕タイミング精度", "max_score": 100},
        ])
        result = trigger.evaluate_and_trigger(report)
        assert "triggered" in result

    @pytest.mark.usefixtures("_patch_paths")
    def test_score_is_castable_string(self, _patch_paths):
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"name": "字幕タイミング精度", "score": "45.5", "max_score": 100},
        ])
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is True
        assert result["tasks_created"] == 1

    @pytest.mark.usefixtures("_patch_paths")
    def test_grade_is_na_string(self, _patch_paths):
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"name": "字幕タイミング精度", "score": 30.0, "max_score": 100, "grade": "N/A"},
        ])
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is False
        assert result["tasks_created"] == 0

    @pytest.mark.usefixtures("_patch_paths")
    def test_axes_is_none_or_missing(self, _patch_paths):
        trigger = QualityFeedbackTrigger(threshold=60.0)
        result = trigger.evaluate_and_trigger({"overall_score": 50.0})
        assert result["triggered"] is False
        assert result["tasks_created"] == 0

    @pytest.mark.usefixtures("_patch_paths")
    def test_axis_missing_name_field(self, _patch_paths):
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"score": 30.0, "max_score": 100}
        ])
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is False
        assert result["tasks_created"] == 0

    def test_overflow_value_safe_float(self):
        from services.quality_feedback_trigger import _safe_float
        assert _safe_float(10**1000, 60.0) == 60.0

    def test_uncomparable_object_safe_float(self):
        from services.quality_feedback_trigger import _safe_float
        class Uncomparable:
            def __eq__(self, other):
                raise RuntimeError("Cannot compare")
            def __ne__(self, other):
                raise RuntimeError("Cannot compare")
        assert _safe_float(Uncomparable(), 60.0) == 60.0


class TestQualityFeedbackTriggerEnhancedErrorHandling:
    """強化されたエラーハンドリングの検証テスト。"""

    @pytest.mark.usefixtures("_patch_paths")
    def test_evaluate_and_trigger_invalid_report_type(self, _patch_paths):
        """score_report が辞書型でない場合、安全にスキップされ、タスクが生成されないこと。"""
        trigger = QualityFeedbackTrigger()
        
        # 文字列が渡された場合
        result = trigger.evaluate_and_trigger("not a dict")
        assert result["triggered"] is False
        assert result["tasks_created"] == 0
        assert "無効なスコアレポート形式" in result["details"]
        
        # None が渡された場合
        result = trigger.evaluate_and_trigger(None)
        assert result["triggered"] is False
        assert result["tasks_created"] == 0

    def test_safe_float_warning_on_invalid_conversion(self, monkeypatch):
        """数値変換できない無効な値が渡された際、警告ログが出力されること。"""
        from services.quality_feedback_trigger import _safe_float

        warnings = []
        monkeypatch.setattr(qft_module.logger, "warning", lambda *args: warnings.append(args))

        # 数値変換不可の文字列
        val = "invalid_value"
        res = _safe_float(val, default=10.0)
        assert res == 10.0
        assert len(warnings) == 1
        assert "数値変換に失敗しました" in warnings[0][0]
        assert warnings[0][1] == "invalid_value"

        # "N/A" は警告を出さない
        warnings.clear()
        res = _safe_float("N/A", default=10.0)
        assert res == 10.0
        assert len(warnings) == 0

    def test_inject_tasks_type_error_raises(self, monkeypatch):
        """_inject_tasks で TypeError が発生した場合に例外を発生させること。"""
        trigger = QualityFeedbackTrigger()
        
        # tasks がリストでない場合、TypeError になる
        with pytest.raises(TypeError):
            trigger._inject_tasks("not a list")

    def test_record_score_attribute_error_suppressed(self, monkeypatch):
        """_record_score で AttributeError 等が発生した場合にもクラッシュせず正常終了すること。"""
        trigger = QualityFeedbackTrigger()
        
        # score_report に None を渡すと AttributeError が発生するが、安全にキャッチされること
        trigger._record_score(None, triggered=False)

    def test_inject_tasks_key_error_raises(self):
        """_inject_tasks で KeyError が発生した場合に例外を発生させること。"""
        trigger = QualityFeedbackTrigger()

        # __setitem__ で KeyError をスローし、copy時も自身と同等の型を維持するダミー辞書を使用
        class BadDict(dict):
            def copy(self):
                return BadDict(super().copy())
            def __setitem__(self, key, value):
                raise KeyError("Dummy KeyError")

        bad_task = BadDict({"group": "bug_hunter"})
        with pytest.raises(KeyError):
            trigger._inject_tasks([bad_task])

    def test_inject_tasks_attribute_error_raises(self, tmp_path, monkeypatch):
        """_inject_tasks で AttributeError が発生した場合に例外を発生させること（queueがdict型でない場合など）。"""
        fake_queue = tmp_path / "task_queue.json"
        # リスト型を書き込んでおき、.get() 呼び出しで AttributeError を誘発させる
        fake_queue.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)

        trigger = QualityFeedbackTrigger()
        with pytest.raises(AttributeError):
            trigger._inject_tasks([{"group": "bug_hunter"}])

    def test_inject_tasks_invalid_tasks_type_reinitialized(self, tmp_path, monkeypatch):
        """queue内の 'tasks' がリスト型でない場合、空のリストとして再初期化されてタスクが追加されること。"""
        fake_queue = tmp_path / "task_queue.json"
        # tasks に辞書を指定して無効な状態にする
        invalid_queue = {"current_batch_id": "test_batch", "tasks": {"not": "a list"}}
        fake_queue.write_text(json.dumps(invalid_queue), encoding="utf-8")
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)

        trigger = QualityFeedbackTrigger()
        count = trigger._inject_tasks([{"group": "bug_hunter", "instruction": "new task"}])

        assert count == 1
        data = json.loads(fake_queue.read_text(encoding="utf-8"))
        assert isinstance(data["tasks"], list)
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["instruction"] == "new task"

    @pytest.mark.usefixtures("_patch_paths")
    def test_evaluate_and_trigger_axes_is_not_list(self, _patch_paths):
        """axes フィールドがリスト型でない場合、安全に処理がスキップされ、タスクが生成されないこと。"""
        trigger = QualityFeedbackTrigger()
        report = {"overall_score": 80.0, "axes": "not a list"}
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is False
        assert result["tasks_created"] == 0
        assert "axesがリスト形式ではない" in result["details"]

    @pytest.mark.usefixtures("_patch_paths")
    def test_evaluate_and_trigger_invalid_axis_element_type(self, _patch_paths):
        """axes 内に辞書型でない要素が含まれている場合、それらを安全にスキップして他の要素の処理を続行すること。"""
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            None,                      # 不正な要素 (None)
            "invalid_axis_string",     # 不正な要素 (文字列)
            {"name": "音量バランス", "score": 30.0, "max_score": 100} # 正常な要素 (閾値以下)
        ])
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is True
        assert result["low_axes"] == ["音量バランス"]
        assert result["tasks_created"] == 1

    @pytest.mark.usefixtures("_patch_paths")
    def test_evaluate_and_trigger_nan_infinity_scores(self, _patch_paths):
        """スコアに NaN や Infinity などの無効な数値が渡された際、デフォルト値（100.0）にフォールバックされ、トリガーされないこと。"""
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"name": "字幕タイミング精度", "score": float("nan"), "max_score": 100},
            {"name": "音量バランス", "score": float("inf"), "max_score": 100},
        ])
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is False
        assert result["tasks_created"] == 0

    @pytest.mark.usefixtures("_patch_paths")
    def test_evaluate_and_trigger_unexpected_exception(self, _patch_paths, monkeypatch):
        """evaluate_and_trigger 内部で予期せぬ例外が発生した際、クラッシュせずに安全なレスポンスが返されること。"""
        trigger = QualityFeedbackTrigger()
        
        # evaluation 中に例外を発生させるために、_safe_float をモック化して意図的に例外をスローさせる
        def mock_safe_float(*args, **kwargs):
            raise RuntimeError("Unexpected evaluate error")
        
        monkeypatch.setattr(qft_module, "_safe_float", mock_safe_float)
        
        report = _make_report([
            {"name": "音量バランス", "score": 30.0, "max_score": 100}
        ])
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is False
        assert result["tasks_created"] == 0
        assert "評価中にエラーが発生しました" in result["details"]


    def test_inject_tasks_value_error_raises(self, monkeypatch):
        """_inject_tasks 内で ValueError が発生した場合に例外を発生させること。"""
        trigger = QualityFeedbackTrigger()

        def mock_open(*args, **kwargs):
            raise ValueError("Mocked ValueError")

        import builtins
        monkeypatch.setattr(builtins, "open", mock_open)

        with pytest.raises(ValueError):
            trigger._inject_tasks([{"group": "bug_hunter"}])

    def test_record_score_value_error_suppressed(self, monkeypatch):
        """_record_score 内で ValueError が発生した場合にもクラッシュせず正常終了すること。"""
        trigger = QualityFeedbackTrigger()

        def mock_open(*args, **kwargs):
            raise ValueError("Mocked ValueError")

        import builtins
        monkeypatch.setattr(builtins, "open", mock_open)

        report = _make_report([], overall_score=50.0)
        # ValueError は安全にキャッチされるため、クラッシュしない
        trigger._record_score(report, triggered=False)

    @pytest.mark.usefixtures("_patch_paths")
    def test_evaluate_and_trigger_value_error_caught(self, _patch_paths, monkeypatch):
        """evaluate_and_trigger 内部で ValueError が発生した際、想定内エラーとしてキャッチされて安全なレスポンスが返されること。"""
        trigger = QualityFeedbackTrigger()
        
        def mock_safe_float(*args, **kwargs):
            raise ValueError("Expected value error")
        
        monkeypatch.setattr(qft_module, "_safe_float", mock_safe_float)
        
        report = _make_report([
            {"name": "音量バランス", "score": 30.0, "max_score": 100}
        ])
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is False
        assert result["tasks_created"] == 0
        assert "評価中にエラーが発生しました" in result["details"]

    def test_inject_tasks_atomic_write_failure_cleanup_raises(self, tmp_path, monkeypatch):
        """_inject_tasks 内のアトミック書き込み中に例外が発生した際、一時ファイルが作成されていれば削除され、
        例外が発生すること。"""
        import os
        fake_queue = tmp_path / "task_queue.json"
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)

        trigger = QualityFeedbackTrigger()

        # os.replace で例外を発生させる
        def mock_replace(src, dst):
            # src (temp_path) が存在することを確認
            assert Path(src).exists()
            raise OSError("Mocked replace error")

        monkeypatch.setattr(os, "replace", mock_replace)

        with pytest.raises(OSError):
            trigger._inject_tasks([{"group": "bug_hunter", "instruction": "test"}])
        
        # 一時ファイル (.tmp) が削除されていること
        temp_path = fake_queue.with_suffix(".tmp")
        assert not temp_path.exists()

    def test_record_score_unexpected_exception_suppressed(self, monkeypatch):
        """_record_score 内で想定外の例外(Exception)が発生した場合にもクラッシュせず正常終了すること。"""
        import os
        trigger = QualityFeedbackTrigger()

        # os.makedirs で RuntimeError を発生させる
        def mock_makedirs(*args, **kwargs):
            raise RuntimeError("Mocked unexpected runtime error")

        monkeypatch.setattr(os, "makedirs", mock_makedirs)

        report = _make_report([], overall_score=50.0)
        # 予期せぬ例外は安全にキャッチされるため、クラッシュしない
        trigger._record_score(report, triggered=False)

    def test_inject_tasks_json_decode_error_with_data_raises_exception(self, tmp_path, monkeypatch):
        """ファイルが存在し、サイズが0より大きい状態で json.JSONDecodeError が起きた際、
        リトライを行った上で最終的に JSONDecodeError が発生すること。"""
        fake_queue = tmp_path / "task_queue.json"
        fake_queue.write_text("invalid json {", encoding="utf-8")
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)

        # sleepをモック化してテストを高速化
        sleep_called = []
        monkeypatch.setattr("time.sleep", lambda s: sleep_called.append(s))

        trigger = QualityFeedbackTrigger()
        with pytest.raises(json.JSONDecodeError):
            trigger._inject_tasks([{"group": "bug_hunter", "instruction": "test"}])

        # リトライが4回行われたことを確認 (初回 + 4回リトライ = 5回トライ)
        assert len(sleep_called) == 4

    def test_evaluate_and_trigger_catches_injected_tasks_exception(self, tmp_path, monkeypatch):
        """_inject_tasks で例外が発生した際、evaluate_and_trigger がそれを適切にキャッチして
        details にエラー詳細を含め、triggered=False を返すこと。"""
        fake_queue = tmp_path / "task_queue.json"
        fake_queue.write_text("invalid json {", encoding="utf-8")
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)
        monkeypatch.setattr("time.sleep", lambda s: None)

        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"name": "音量バランス", "score": 30.0, "max_score": 100}
        ])
        
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is False
        assert result["tasks_created"] == 0
        assert "評価中にエラーが発生しました" in result["details"]
        assert "Expecting" in result["details"] or "JSON" in result["details"]

    def test_inject_tasks_retry_success(self, tmp_path, monkeypatch):
        """最初はJSONパースエラーになるが、リトライ中に正しいJSONが書き込まれた場合、
        リトライが成功してタスクが正常に注入されること。"""
        fake_queue = tmp_path / "task_queue.json"
        fake_queue.write_text("invalid json {", encoding="utf-8")
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)

        # リトライのsleep中に、ファイルを正しいJSONに書き換える
        call_count = 0
        def mock_sleep(s):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                fake_queue.write_text(json.dumps({"current_batch_id": "test_retry", "tasks": []}), encoding="utf-8")

        monkeypatch.setattr("time.sleep", mock_sleep)

        trigger = QualityFeedbackTrigger()
        count = trigger._inject_tasks([{"group": "bug_hunter", "instruction": "test"}])

        assert count == 1
        assert call_count == 1  # 1回のリトライで成功したこと
        data = json.loads(fake_queue.read_text(encoding="utf-8"))
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["instruction"] == "test"

    @pytest.mark.usefixtures("_patch_paths")
    def test_non_string_axis_name(self, _patch_paths):
        trigger = QualityFeedbackTrigger()
        report = _make_report([
            {"name": ["not", "a", "string"], "score": 50.0},
            {"name": 12345, "score": 50.0},
            {"name": "字幕タイミング精度", "score": 50.0},
        ])
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is True
        assert result["tasks_created"] == 1
        assert result["low_axes"] == ["字幕タイミング精度"]

    def test_axis_to_module_non_string(self):
        assert QualityFeedbackTrigger._axis_to_module(["not", "a", "string"]) is None
        assert QualityFeedbackTrigger._axis_to_module(12345) is None


class TestQualityFeedbackTriggerBugHunterFixes:
    """bug_hunterタスク#6で追加された修正項目的の検証テスト。"""

    @pytest.mark.usefixtures("_patch_paths")
    def test_suggestion_is_none_fallback(self, _patch_paths):
        """suggestionキーがNoneの場合、指示書内に'改善提案: N/A'と正しく設定されること。"""
        trigger = QualityFeedbackTrigger(threshold=60.0)
        report = _make_report([
            {"name": "音量バランス", "score": 30.0, "max_score": 100, "suggestion": None}
        ])
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is True
        assert result["tasks_created"] == 1

        # キューから書き込まれた内容を取り出して確認
        fake_queue = _patch_paths[0]
        data = json.loads(fake_queue.read_text(encoding="utf-8"))
        instruction = data["tasks"][0]["instruction"]
        assert "改善提案: N/A" in instruction
        assert "改善提案: None" not in instruction

    def test_inject_tasks_uses_unique_temp_file(self, tmp_path, monkeypatch):
        """_inject_tasksが一時ファイルを作成する際、固定の.tmpではなく、
        UUID等を含んだユニークなファイル名を使用すること。"""
        fake_queue = tmp_path / "task_queue.json"
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)

        # os.replace をフックして一時ファイルのパスを確認
        replaced_srcs = []
        import os
        original_replace = os.replace
        def mock_replace(src, dst):
            replaced_srcs.append(src)
            return original_replace(src, dst)
        monkeypatch.setattr(os, "replace", mock_replace)

        trigger = QualityFeedbackTrigger()
        trigger._inject_tasks([{"group": "bug_hunter", "instruction": "test"}])

        assert len(replaced_srcs) == 1
        temp_file_name = Path(replaced_srcs[0]).name
        # 一時ファイル名が単なる task_queue.tmp ではなく、UUIDなどのユニークな文字を含んでいること
        assert temp_file_name != "task_queue.tmp"
        assert ".tmp" in temp_file_name
        assert len(temp_file_name) > len("task_queue.tmp")

    def test_inject_tasks_retries_on_permission_error(self, tmp_path, monkeypatch):
        """タスク注入時、PermissionError（ファイルロック競合）が発生した際にリトライされること。"""
        fake_queue = tmp_path / "task_queue.json"
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)

        # 読み込み時に PermissionError を3回発生させ、4回目で成功させる
        call_count = 0
        original_open = open
        def mock_open(file, mode="r", *args, **kwargs):
            nonlocal call_count
            # TASK_QUEUE_PATH の読み込み時のみモックする
            if Path(file) == fake_queue and "r" in mode:
                call_count += 1
                if call_count <= 3:
                    raise PermissionError("Mocked file lock conflict")
            return original_open(file, mode, *args, **kwargs)

        import builtins
        monkeypatch.setattr(builtins, "open", mock_open)
        
        sleep_called = []
        monkeypatch.setattr("time.sleep", lambda s: sleep_called.append(s))

        trigger = QualityFeedbackTrigger()
        # 初回ファイル作成は書き込みモードなので PermissionError は起きない。
        # そのため、あらかじめファイルを作っておく
        fake_queue.write_text(json.dumps({"tasks": []}), encoding="utf-8")

        count = trigger._inject_tasks([{"group": "bug_hunter", "instruction": "test"}])
        assert count == 1
        assert call_count == 4  # 3回失敗、4回目で成功
        assert len(sleep_called) == 3


class TestQualityFeedbackTriggerRobustnessEnhanced:
    """エラーハンドリングおよびクリーンアップ強化の追加テスト"""

    def test_inject_tasks_guarantees_temp_file_cleanup_on_base_exception(self, tmp_path, monkeypatch):
        """_inject_tasks で BaseException が発生した際、一時ファイルが確実に削除されること。"""
        import os
        fake_queue = tmp_path / "task_queue.json"
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)

        # os.replace が BaseException を投げるようにモックする
        temp_paths = []
        def mock_replace(src, dst):
            temp_paths.append(Path(src))
            raise BaseException("System Exit Simulated")

        monkeypatch.setattr(os, "replace", mock_replace)

        trigger = QualityFeedbackTrigger()
        with pytest.raises(BaseException) as excinfo:
            trigger._inject_tasks([{"group": "bug_hunter", "instruction": "cleanup test"}])

        assert "System Exit Simulated" in str(excinfo.value)
        assert len(temp_paths) == 1
        # 一時ファイルが存在しない（確実に削除された）ことを検証
        assert not temp_paths[0].exists()

    def test_evaluate_and_trigger_unexpected_exception_detailed_logging(self, caplog, monkeypatch):
        """evaluate_and_trigger で予期せぬ例外が発生した際、詳細なログ（例外名、メタ情報）が出力されること。"""
        trigger = QualityFeedbackTrigger()

        def mock_safe_float(*args, **kwargs):
            raise RuntimeError("unexpected error for logging test")

        monkeypatch.setattr(qft_module, "_safe_float", mock_safe_float)

        import logging
        with caplog.at_level(logging.ERROR):
            report = {"overall_score": 55.5, "overall_grade": "C", "axes": [{"name": "テスト軸", "score": 30.0}]}
            trigger.evaluate_and_trigger(report)
            
            log_records = [r for r in caplog.records if "評価中にエラーが発生しました" in r.message]
            assert len(log_records) == 1
            log_msg = log_records[0].message
            assert "RuntimeError" in log_msg
            assert "overall_score" in log_msg
            assert "55.5" in log_msg
            assert "overall_grade" in log_msg
            assert "C" in log_msg

    def test_record_score_unexpected_exception_detailed_logging(self, caplog, monkeypatch):
        """_record_score で予期せぬ例外が発生した際、詳細な警告ログが出力されること。"""
        trigger = QualityFeedbackTrigger()

        def mock_makedirs(*args, **kwargs):
            raise RuntimeError("unexpected writing error")

        import os
        monkeypatch.setattr(os, "makedirs", mock_makedirs)

        import logging
        with caplog.at_level(logging.WARNING):
            report = {"overall_score": 77.7, "overall_grade": "B"}
            trigger._record_score(report, triggered=True, tasks_count=5)
            
            log_records = [r for r in caplog.records if "品質スコア履歴の記録に失敗しました" in r.message]
            assert len(log_records) == 1
            log_msg = log_records[0].message
            assert "RuntimeError" in log_msg
            assert "77.7" in log_msg
            assert "tasks_created': 5" in log_msg or "tasks_created" in log_msg or "5" in log_msg


class TestQualityFeedbackTriggerAdditionalCoverage:
    """新規追加：具体的な例外（json.JSONDecodeError, TypeError/AttributeErrorなど）のキャッチを検証するテスト"""

    @pytest.mark.usefixtures("_patch_paths")
    def test_evaluate_and_trigger_json_decode_error_caught(self, _patch_paths, monkeypatch):
        """evaluate_and_trigger 内部で json.JSONDecodeError が発生した際、適切にキャッチされて details に含まれること。"""
        trigger = QualityFeedbackTrigger()

        def mock_safe_float(*args, **kwargs):
            raise json.JSONDecodeError("Mocked JSON error", "doc", 0)

        monkeypatch.setattr(qft_module, "_safe_float", mock_safe_float)

        report = _make_report([
            {"name": "音量バランス", "score": 30.0, "max_score": 100}
        ])
        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is False
        assert result["tasks_created"] == 0
        assert "評価中にエラーが発生しました" in result["details"]
        assert "Mocked JSON error" in result["details"]

    @pytest.mark.usefixtures("_patch_paths")
    def test_evaluate_and_trigger_metadata_extraction_error_caught(self, _patch_paths, monkeypatch):
        """メタデータ抽出処理中に TypeError や AttributeError が発生した際、全体がクラッシュせず meta_error にフォールバックされること。"""
        trigger = QualityFeedbackTrigger()

        # _safe_float で RuntimeError を発生させて、外側の except 節のメタデータ抽出ロジックに入らせる
        def mock_safe_float(*args, **kwargs):
            raise RuntimeError("Force triggers metadata extraction error path")

        monkeypatch.setattr(qft_module, "_safe_float", mock_safe_float)

        # score_report.get() 呼び出し時に TypeError を発生させるカスタム辞書を使用する
        class BadDict(dict):
            def get(self, key, default=None):
                raise TypeError("Forced get error")

        report = BadDict({
            "overall_score": 50.0,
            "overall_grade": "C",
            "axes": [{"name": "音量バランス", "score": 30.0}]
        })

        # ログメッセージを検証するため、logger の呼び出しをキャプチャする
        errors = []
        monkeypatch.setattr(qft_module.logger, "error", lambda msg, *args, **kwargs: errors.append(msg % args if args else msg))

        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is False
        assert result["tasks_created"] == 0
        
        # エラーログ内にメタデータ抽出失敗のフォールバック情報（meta_error）が含まれていることを確認
        assert any("Failed to extract score_report meta fields" in err for err in errors)

    @pytest.mark.usefixtures("_patch_paths")
    def test_evaluate_and_trigger_metadata_extraction_error_caught_attribute_error(self, _patch_paths, monkeypatch):
        """メタデータ抽出処理中に AttributeError が発生した際、全体がクラッシュせず meta_error にフォールバックされること。"""
        trigger = QualityFeedbackTrigger()

        # _safe_float で RuntimeError を発生させて、外側の except 節のメタデータ抽出ロジックに入らせる
        def mock_safe_float(*args, **kwargs):
            raise RuntimeError("Force triggers metadata extraction error path")

        monkeypatch.setattr(qft_module, "_safe_float", mock_safe_float)

        # score_report.get() 呼び出し時に AttributeError を発生させるカスタム辞書を使用する
        class BadDictAttributeError(dict):
            def get(self, key, default=None):
                raise AttributeError("Forced get AttributeError")

        report = BadDictAttributeError({
            "overall_score": 50.0,
            "overall_grade": "C",
            "axes": [{"name": "音量バランス", "score": 30.0}]
        })

        # ログメッセージを検証するため、logger の呼び出しをキャプチャする
        errors = []
        monkeypatch.setattr(qft_module.logger, "error", lambda msg, *args, **kwargs: errors.append(msg % args if args else msg))

        result = trigger.evaluate_and_trigger(report)
        assert result["triggered"] is False
        assert result["tasks_created"] == 0
        
        # エラーログ内にメタデータ抽出失敗のフォールバック情報（meta_error）が含まれていることを確認
        assert any("Failed to extract score_report meta fields" in err for err in errors)


class TestQualityFeedbackTriggerBugHunterTask1:
    """Phase 33 bug_hunter タスク #1 のための追加テスト"""

    def test_safe_float_with_special_objects(self):
        """_safe_float に比較不可能なオブジェクトや特殊な値が渡されても安全にデフォルト値が返されること。"""
        from services.quality_feedback_trigger import _safe_float

        class CustomUncomparable:
            def __eq__(self, other):
                raise TypeError("Cannot compare")

        assert _safe_float(CustomUncomparable(), 50.0) == 50.0
        assert _safe_float("N/A", 50.0) == 50.0
        assert _safe_float("invalid", 50.0) == 50.0

    def test_inject_tasks_does_not_retry_on_logical_errors(self, monkeypatch):
        """_inject_tasks 内で TypeError/KeyError/AttributeError などの論理エラーが発生した際、
        リトライ（time.sleep）されることなく即座に例外が発生すること。"""
        trigger = QualityFeedbackTrigger()

        sleep_called = []
        monkeypatch.setattr("time.sleep", lambda s: sleep_called.append(s))

        # TypeErrorを誘発させる（tasksに無効なデータ型を渡す）
        with pytest.raises(TypeError):
            trigger._inject_tasks("not a list")
        
        # 1度もsleepが呼ばれず、即座に例外がスローされたことを検証
        assert len(sleep_called) == 0

    def test_record_score_retry_success(self, tmp_path, monkeypatch):
        """_record_score 内のファイル書き込みにおいて、一時的な PermissionError が発生しても、
        リトライされて最終的に書き込みが成功すること。"""
        fake_history = tmp_path / "quality_score_history.jsonl"
        monkeypatch.setattr(qft_module, "QUALITY_SCORE_HISTORY_PATH", fake_history)

        sleep_called = []
        monkeypatch.setattr("time.sleep", lambda s: sleep_called.append(s))

        # 1回目は PermissionError を発生させ、2回目で成功させる
        write_count = 0
        original_open = open
        def mock_open(file, mode="r", *args, **kwargs):
            nonlocal write_count
            if str(file) == str(fake_history) and "a" in mode:
                write_count += 1
                if write_count == 1:
                    raise PermissionError("Mocked Permission Error")
            return original_open(file, mode, *args, **kwargs)

        # builtins.openをモック化
        import builtins
        monkeypatch.setattr(builtins, "open", mock_open)

        trigger = QualityFeedbackTrigger()
        report = {"overall_score": 85.0, "overall_grade": "A"}
        trigger._record_score(report, triggered=False, tasks_count=0)

        # sleepが1回呼ばれ、最終的にファイルが書き込まれていることを確認
        assert len(sleep_called) == 1
        assert write_count == 2
        assert fake_history.exists()
        content = fake_history.read_text(encoding="utf-8")
        assert "85.0" in content

    def test_record_score_retry_exhausted_suppressed(self, tmp_path, monkeypatch):
        """_record_score のリトライがすべて失敗した場合でも、
        例外がキャッチされ、呼び出し元がクラッシュしないこと。"""
        fake_history = tmp_path / "quality_score_history.jsonl"
        monkeypatch.setattr(qft_module, "QUALITY_SCORE_HISTORY_PATH", fake_history)

        sleep_called = []
        monkeypatch.setattr("time.sleep", lambda s: sleep_called.append(s))

        # 常に PermissionError を発生させる
        def mock_open(file, mode="r", *args, **kwargs):
            if str(file) == str(fake_history) and "a" in mode:
                raise PermissionError("Mocked Persistent Permission Error")
            return open(file, mode, *args, **kwargs)

        import builtins
        monkeypatch.setattr(builtins, "open", mock_open)

        trigger = QualityFeedbackTrigger()
        report = {"overall_score": 85.0, "overall_grade": "A"}

        # 例外が伝播せずに正常終了すること
        trigger._record_score(report, triggered=False, tasks_count=0)

        # リトライが2回（初回+2回リトライ = 3回トライ）行われ、sleepが2回呼ばれていること
        assert len(sleep_called) == 2

    def test_inject_tasks_temp_file_cleanup_in_loop(self, tmp_path, monkeypatch):
        """_inject_tasks 内で PermissionError などによるリトライが発生した際、
        作成された一時ファイル（temp_path）がリトライループ内で確実にクリーンアップされること。"""
        import os
        from pathlib import Path
        fake_queue = tmp_path / "task_queue.json"
        fake_queue.write_text(json.dumps({"current_batch_id": "test_cleanup", "tasks": []}), encoding="utf-8")
        monkeypatch.setattr(qft_module, "TASK_QUEUE_PATH", fake_queue)

        sleep_called = []
        monkeypatch.setattr("time.sleep", lambda s: sleep_called.append(s))

        # os.replace で PermissionError を発生させることで、一時ファイルが生成された後の例外をシミュレート
        replace_count = 0
        original_replace = os.replace
        created_temp_files = []

        def mock_replace(src, dst):
            nonlocal replace_count
            replace_count += 1
            # 一時ファイルへのパスを記録
            created_temp_files.append(Path(src))
            if replace_count < 3:
                raise PermissionError("Mocked replace collision")
            original_replace(src, dst)

        monkeypatch.setattr(os, "replace", mock_replace)

        trigger = QualityFeedbackTrigger()
        trigger._inject_tasks([{"group": "bug_hunter", "instruction": "test"}])

        # 3回目（1回目、2回目がPermissionError、3回目が成功）で成功し、sleepは2回呼ばれていること
        assert len(sleep_called) == 2
        assert replace_count == 3
        assert len(created_temp_files) == 3

        # 1回目、2回目に作成された一時ファイルがすでに削除されていることを確認
        assert not created_temp_files[0].exists()
        assert not created_temp_files[1].exists()
        # 3回目のファイルは replace されたため存在しない
        assert not created_temp_files[2].exists()

