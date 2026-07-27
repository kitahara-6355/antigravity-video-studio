import os
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from backend.agents.orchestration.research_reporter import ResearchReporter

def test_research_reporter_metrics_filtering():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # 1. 擬似ワークスペース構造の作成
        orchestration_dir = tmp_path / "backend" / "agents" / "orchestration"
        orchestration_dir.mkdir(parents=True, exist_ok=True)
        
        # セッション開始時刻: 2026-06-12T12:00:00+00:00
        session_started = datetime.fromisoformat("2026-06-12T12:00:00+00:00")
        
        # session.json の書き込み
        session_path = orchestration_dir / "flash_session.json"
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump({
                "session_started_at": session_started.isoformat(),
                "status": "running"
            }, f)
            
        # reports.jsonl の書き込み (1件はセッション開始前、1件は開始後、空行あり)
        reports_path = orchestration_dir / "flash_reports.jsonl"
        with open(reports_path, "w", encoding="utf-8") as f:
            # 古いレポート（スキップ対象）
            old_entry = {
                "timestamp": "2026-06-12T10:00:00+00:00",
                "tasks": [
                    {
                        "id": "T-old-001",
                        "status": "fail",
                        "result": "ImportError: No module named foo"
                    }
                ]
            }
            f.write(json.dumps(old_entry) + "\n")
            f.write("\n")  # 空行のテスト
            
            # 新しいレポート（集計対象）
            new_entry = {
                "timestamp": "2026-06-12T14:00:00+00:00",
                "tasks": [
                    {
                        "id": "T-new-001",
                        "status": "pass",
                        "result": {"changed_files": ["main.py"]}
                    },
                    {
                        "id": "T-new-002",
                        "status": "fail",
                        "result": "ImportError: cannot import name bar"
                    }
                ]
            }
            f.write(json.dumps(new_entry) + "\n")
            
        # 2. ResearchReporter を実行してメトリクス確認
        reporter = ResearchReporter(workspace_path=str(tmp_path))
        metrics = reporter.calculate_metrics()
        
        # 3. アサーション
        # 古いものはスキップされたため、total_tasks は 2、failed は 1、dep_leak は 1
        assert metrics["total_tasks"] == 2
        assert metrics["effective_tasks"] == 1
        assert metrics["failed_tasks"] == 1
        assert metrics["dep_leak_fails"] == 1


def test_research_reporter_corrupted_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        orchestration_dir = tmp_path / "backend" / "agents" / "orchestration"
        orchestration_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. 壊れた JSON の session.json を書き込む
        session_path = orchestration_dir / "flash_session.json"
        with open(session_path, "w", encoding="utf-8") as f:
            f.write("{invalid json...")
            
        # 2. 壊れた JSON の reports.jsonl を書き込む
        reports_path = orchestration_dir / "flash_reports.jsonl"
        with open(reports_path, "w", encoding="utf-8") as f:
            f.write("{corrupted reports jsonl...\n")
            
        reporter = ResearchReporter(workspace_path=str(tmp_path))
        metrics = reporter.calculate_metrics()
        
        # 壊れた JSON のため、例外がキャッチされ、デフォルト値 (total_tasks=0) で計算が完了することを確認
        assert metrics["total_tasks"] == 0
        assert metrics["effective_tasks"] == 0


def test_research_reporter_invalid_timestamps():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        orchestration_dir = tmp_path / "backend" / "agents" / "orchestration"
        orchestration_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. session.json に無効な日付フォーマットを書き込む (ValueError)
        session_path = orchestration_dir / "flash_session.json"
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump({
                "session_started_at": "invalid-date-format",
                "status": "running"
            }, f)
            
        # 2. reports.jsonl に無効な日付・無効な型を書き込む
        reports_path = orchestration_dir / "flash_reports.jsonl"
        with open(reports_path, "w", encoding="utf-8") as f:
            entry = {
                "timestamp": "invalid-timestamp-format",
                "tasks": [
                    {
                        "id": "T-001",
                        "status": "pass",
                        "result": {"changed_files": ["main.py"]},
                        "started_at": 123456,  # 属性エラー (replace が呼べない) または TypeError
                        "completed_at": "invalid-completed-at"
                    }
                ]
            }
            f.write(json.dumps(entry) + "\n")
            
        reporter = ResearchReporter(workspace_path=str(tmp_path))
        metrics = reporter.calculate_metrics()
        
        # timestampパース時の例外がキャッチされて処理が続行され、
        # started_atの属性エラー時の例外もキャッチされ、リードタイム計算が安全にスキップされることを確認
        assert metrics["total_tasks"] == 1
        assert metrics["effective_tasks"] == 1
        assert metrics["avg_lead_time_min"] == 0.0


def test_research_reporter_generate_daily_report():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        orchestration_dir = tmp_path / "backend" / "agents" / "orchestration"
        orchestration_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. session.json と reports.jsonl を書き込み
        session_path = orchestration_dir / "flash_session.json"
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump({
                "session_started_at": "2026-06-12T12:00:00Z",
                "status": "running"
            }, f)
            
        reports_path = orchestration_dir / "flash_reports.jsonl"
        with open(reports_path, "w", encoding="utf-8") as f:
            entry = {
                "timestamp": "2026-06-12T14:00:00Z",
                "tasks": [
                    {
                        "id": "T-001",
                        "status": "pass",
                        "result": {"changed_files": ["main.py"]},
                        "started_at": "2026-06-12T13:00:00Z",
                        "completed_at": "2026-06-12T13:05:00Z"
                    }
                ]
            }
            f.write(json.dumps(entry) + "\n")
            
        reporter = ResearchReporter(workspace_path=str(tmp_path))
        report_path_str = reporter.generate_daily_report()
        
        # ファイルが作成されたことの確認
        report_path = Path(report_path_str)
        assert report_path.exists()
        assert report_path.name.startswith("research_report_")
        
        # レポート内容の確認
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "# 分解・生成エンジン研究 日次レポート" in content
            assert "タスク空振り率 (Wasted Rate)" in content
            assert "0.0%" in content  # wasted_rate は 0/1 なので 0.0%
            assert "5.0分/タスク" in content  # 5分リードタイム


def test_research_reporter_timezone_mix():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        orchestration_dir = tmp_path / "backend" / "agents" / "orchestration"
        orchestration_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. session.json にタイムゾーンなし (Naive) を書き込む
        session_path = orchestration_dir / "flash_session.json"
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump({
                "session_started_at": "2026-06-12T12:00:00",
                "status": "running"
            }, f)
            
        # 2. reports.jsonl にタイムゾーンあり (Aware) となし (Naive) が混在するデータを書き込む
        reports_path = orchestration_dir / "flash_reports.jsonl"
        with open(reports_path, "w", encoding="utf-8") as f:
            # セッション開始前 (Aware: 10:00 UTC) -> スキップされるべき
            entry1 = {
                "timestamp": "2026-06-12T10:00:00+00:00",
                "tasks": [
                    {
                        "id": "T-skip",
                        "status": "pass",
                        "result": {"changed_files": ["main.py"]}
                    }
                ]
            }
            # セッション開始後 (Naive: 14:00) -> 集計されるべき
            entry2 = {
                "timestamp": "2026-06-12T14:00:00",
                "tasks": [
                    {
                        "id": "T-keep",
                        "status": "pass",
                        "result": {"changed_files": ["main.py"]},
                        "started_at": "2026-06-12T13:00:00+00:00",  # 処理時間計算でも Aware/Naive 混在
                        "completed_at": "2026-06-12T13:10:00"      # Naive
                    }
                ]
            }
            f.write(json.dumps(entry1) + "\n")
            f.write(json.dumps(entry2) + "\n")
            
        reporter = ResearchReporter(workspace_path=str(tmp_path))
        metrics = reporter.calculate_metrics()
        
        # entry1 はスキップされ、entry2 のみが集計されていること
        assert metrics["total_tasks"] == 1
        assert metrics["effective_tasks"] == 1
        # 10分のリードタイムが正しく計算されていること
        assert metrics["avg_lead_time_min"] == 10.0


def test_research_reporter_missing_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        reporter = ResearchReporter(workspace_path=str(tmp_path))
        metrics = reporter.calculate_metrics()
        assert metrics["total_tasks"] == 0


def test_research_reporter_empty_timestamp():
    import pytest
    reporter = ResearchReporter()
    with pytest.raises(ValueError):
        reporter._parse_utc_datetime("")


def test_research_reporter_os_error(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        orchestration_dir = tmp_path / "backend" / "agents" / "orchestration"
        orchestration_dir.mkdir(parents=True, exist_ok=True)
        
        reports_path = orchestration_dir / "flash_reports.jsonl"
        with open(reports_path, "w", encoding="utf-8") as f:
            f.write("{}\n")
            
        reporter = ResearchReporter(workspace_path=str(tmp_path))
        
        def mock_open(*args, **kwargs):
            raise OSError("mocked os error")
            
        import builtins
        monkeypatch.setattr(builtins, "open", mock_open)
        
        metrics = reporter.calculate_metrics()
        assert metrics["total_tasks"] == 0


