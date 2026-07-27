import pytest
from agents.orchestration.evolution_roadmap_validator import RoadmapValidator

def test_roadmap_validator_initialization():
    validator = RoadmapValidator()
    assert validator.workspace_path is not None
    assert validator.orchestration_dir.exists()

def test_roadmap_validator_evaluation():
    validator = RoadmapValidator()
    results = validator.evaluate_stages()
    
    assert "overall_progress_pct" in results
    assert "stages" in results
    
    stages = results["stages"]
    for stage_name in ["Stage 1", "Stage 2", "Stage 3", "Stage 4", "Stage 5"]:
        assert stage_name in stages
        stage_data = stages[stage_name]
        assert "score" in stage_data
        assert "details" in stage_data
        assert "status" in stage_data
        assert 0 <= stage_data["score"] <= 100

def test_roadmap_validator_markdown():
    validator = RoadmapValidator()
    md = validator.generate_report_markdown()
    
    assert "進化ロードマップ進捗状況" in md
    assert "全体進捗充足率" in md
    for stage_name in ["Stage 1", "Stage 2", "Stage 3", "Stage 4", "Stage 5"]:
        assert stage_name in md

def test_roadmap_validator_ratchet():
    """進化ロードマップの全体進捗が一定基準（退行しないこと）を満たしているかアサート"""
    validator = RoadmapValidator()
    results = validator.evaluate_stages()
    overall = results["overall_progress_pct"]
    
    # 現状の実装状況からして、Stage 1 が 90% 以上、Stage 3 に部分点があるため、
    # 全体進捗は最低でも 15% 以上であるべき（退行ガード）
    assert overall >= 15, f"進化ロードマップの進捗充足率が低下しています: {overall}%"

from unittest.mock import patch
from pathlib import Path
import json

def test_roadmap_validator_caching(tmp_path):
    # テスト用の一時ディレクトリを作成
    workspace = tmp_path / "workspace"
    orchestration = workspace / "backend" / "agents" / "orchestration"
    orchestration.mkdir(parents=True)
    
    # 正常な jsonl ファイルを作成
    reports_file = orchestration / "flash_reports.jsonl"
    reports_file.write_text('{"type": "convergence_loop_event", "result": "retry_success", "tasks": []}\n', encoding="utf-8")
    
    validator = RoadmapValidator(workspace_path=str(workspace))
    
    # 1回目の呼び出し
    with patch("builtins.open", wraps=open) as mock_file_open:
        reports1 = validator._get_flash_reports()
        assert len(reports1) == 1
        # ファイルがオープンされたことを確認
        assert mock_file_open.call_count == 1
        
    # 2回目の呼び出し（キャッシュから返るため、オープンされないはず）
    with patch("builtins.open", wraps=open) as mock_file_open:
        reports2 = validator._get_flash_reports()
        assert len(reports2) == 1
        assert mock_file_open.call_count == 0

def test_roadmap_validator_robustness_with_malformed_jsonl(tmp_path):
    workspace = tmp_path / "workspace"
    orchestration = workspace / "backend" / "agents" / "orchestration"
    orchestration.mkdir(parents=True)
    
    # 不正な JSONL (辞書ではない値、不正なJSONなど) を書き込む
    reports_file = orchestration / "flash_reports.jsonl"
    content = "\n".join([
        '{"type": "convergence_loop_event", "result": "retry_success", "tasks": []}',
        '[1, 2, 3]',  # リスト（辞書ではない） -> get() で AttributeError になるはずだが無視される
        '"just a string"', # 文字列 -> AttributeError になるはずだが無視される
        '{invalid json}', # 構文エラー -> json.JSONDecodeError
        '{"type": "convergence_loop_event", "result": "retry_success", "tasks": [{"status": "pass", "id": "T-split-1"}]}'
    ])
    reports_file.write_text(content, encoding="utf-8")
    
    validator = RoadmapValidator(workspace_path=str(workspace))
    results = validator.evaluate_stages()
    
    # クラッシュせずに評価が完了することを確認
    assert results is not None
    assert "Stage 1" in results["stages"]
    # 2番目の正しいイベントもカウントされていることを確認
    assert results["stages"]["Stage 3"]["score"] > 0

def test_roadmap_validator_robustness_with_malformed_task_queue(tmp_path):
    workspace = tmp_path / "workspace"
    orchestration = workspace / "backend" / "agents" / "orchestration"
    orchestration.mkdir(parents=True)
    
    # 不正な task_queue (辞書ではない、壊れた形式など)
    queue_file = orchestration / "task_queue.json"
    queue_file.write_text('[1, 2, 3]', encoding="utf-8")  # リスト形式 -> 辞書ではないので AttributeError になるはずだが無視される
    
    validator = RoadmapValidator(workspace_path=str(workspace))
    results = validator.evaluate_stages()
    
    # クラッシュせずに評価が完了することを確認
    assert results is not None
    assert "Stage 2" in results["stages"]

