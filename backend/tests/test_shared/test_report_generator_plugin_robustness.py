import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from core import ProductionContext
from plugins.report_generator_plugin import ReportGeneratorPlugin
import logging

def test_report_generator_execute_write_failure_fallback(tmp_path):
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(
        task_id="task_fail_test",
        video_paths=["test_video.mp4"],
        mood="elegant",
        output_name="test_output",
        output_dir=tmp_path,
    )
    
    # mkdir をモック化して OSError を発生させる
    with patch.object(Path, "mkdir", side_effect=OSError("Disk full")):
        with patch("plugins.report_generator_plugin.logger.error") as mock_log_error:
            res = plugin.execute(context)
            assert res == context
            # 例外フォールバックにより、report_path は None になるべき
            assert context.get_extension("report_path") is None
            # エラーログが出力されていること
            mock_log_error.assert_called_once()
            args, _ = mock_log_error.call_args
            assert "Failed to write production report" in args[0]

def test_report_generator_execute_with_mocked_io():
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(
        task_id="task_mock_test",
        video_paths=["test_video.mp4"],
        mood="elegant",
        output_name="test_output",
        output_dir=Path("/dummy/path"),
    )
    
    # 実際のファイルシステムに書き込まず、モックで挙動確認
    with patch.object(Path, "mkdir") as mock_mkdir:
        with patch.object(Path, "write_text") as mock_write_text:
            res = plugin.execute(context)
            assert res == context
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
            mock_write_text.assert_called_once()
            # report_path が期待通り設定されていること
            assert context.get_extension("report_path") == str(Path("/dummy/path") / "generation_report.md")

def test_report_generator_various_null_bounds(tmp_path):
    plugin = ReportGeneratorPlugin()
    
    # 最小限の context
    context = ProductionContext(
        task_id="task_min_test",
        output_dir=tmp_path,
    )
    
    res = plugin.execute(context)
    assert res == context
    
    report_file = tmp_path / "generation_report.md"
    assert report_file.exists()
    
    content = report_file.read_text(encoding="utf-8")
    assert "# 🎬 生成物レポート" in content
    # 各項目がNone/未設定時のデフォルトフォールバックが機能していること
    assert "0枚" in content
    assert "❌" in content
    # **未計測を「0.0/100」という測定結果に見せない**（R1.5-C4）。
    # `backend/core/context.py:67` の quality_score は dataclass の既定値 0.0 で、
    # この経路に品質ゲートは繋がっていない
    assert "品質スコア | **未計測**" in content
    assert "品質スコア | 0.0/100" not in content


def test_report_generator_execute_exception_safety(tmp_path):
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(
        task_id="task_exception_safety",
        output_dir=tmp_path,
    )
    
    # _generate_report 内で例外が発生するようにモック化する
    with patch.object(plugin, "_generate_report", side_effect=TypeError("Simulation of malformed context data")):
        with patch("plugins.report_generator_plugin.logger.error") as mock_log_error:
            res = plugin.execute(context)
            assert res == context
            # _generate_report の例外が execute で安全にキャッチされ、report_path は None になるべき
            assert context.get_extension("report_path") is None
            # エラーログが出力されていること
            mock_log_error.assert_called_once()
            args, _ = mock_log_error.call_args
            assert "Failed to write" in args[0] or "Failed to generate" in args[0]


def test_report_generator_plugin_priority_and_phase():
    plugin = ReportGeneratorPlugin()
    # 属性の検証
    assert plugin.name == "report_generator"
    from core import PluginPhase
    assert plugin.phase == PluginPhase.FINALIZATION
    assert plugin.priority == 100


def test_report_generator_plugin_datetime_formatting(tmp_path):
    from datetime import datetime
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(
        task_id="task_dt_test",
        output_dir=tmp_path,
        mood="chill",
    )
    
    # datetime.now をモック化して固定の日時を返すように設定
    fixed_now = datetime(2026, 6, 3, 12, 34, 56)
    with patch("plugins.report_generator_plugin.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        
        report = plugin._generate_report(context)
        assert "生成日時: 2026-06-03 12:34:56" in report



