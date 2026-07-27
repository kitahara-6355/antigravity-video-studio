# -*- coding: utf-8 -*-
import sys
import pytest
from pathlib import Path
from PIL import Image
import sqlite3
import json
import asyncio

backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from graded_previews.youtuber_grade_scorer import (
    generate_youtuber_preview,
    validate_preview_image,
    resolve_youtuber_preview_task,
    score_against_youtuber_standard
)
from agents.stage_bound_agent import StageBoundAgent

def test_score_against_youtuber_standard():
    res = score_against_youtuber_standard()
    assert res["total_score"] == 100
    assert res["grade"] == "S"

def test_generate_youtuber_preview_success(tmp_path):
    output_file = tmp_path / "valid_preview.png"
    
    # 1280x720 以上の正常解像度で生成
    generate_youtuber_preview(output_file, width=1280, height=720, text="Test Preview Success")
    
    # ファイル存在チェック
    assert output_file.exists()
    
    # 品質検証
    info = validate_preview_image(output_file)
    assert info["width"] == 1280
    assert info["height"] == 720
    assert info["size_bytes"] > 0
    assert info["size_bytes"] < 4 * 1024 * 1024
    
    # Pillowで破損がないか完全ロード確認
    with Image.open(output_file) as img:
        img.verify()
    with Image.open(output_file) as img:
        img.load()

def test_preview_quality_failures(tmp_path):
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        validate_preview_image(tmp_path / "non_existent.png")
        
    # 2. 解像度不足の画像
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(low_res_path, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_preview_image(low_res_path)
        
    # 3. アスペクト比異常
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(bad_ratio_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_preview_image(bad_ratio_path)

    # 4. ファイルサイズ制限
    valid_path = tmp_path / "valid.png"
    generate_youtuber_preview(valid_path, width=1280, height=720)
    from unittest.mock import patch
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_preview_image(valid_path)

def test_stage_bound_agent_integration(tmp_path):
    """
    StageBoundAgent等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作することを検証
    """
    db_file = tmp_path / "test_stage_bound_agent_youtuber.db"
    output_dir = tmp_path / "youtuber_previews"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    # 動的属性の設定
    agent.output_dir = str(output_dir)
    agent.width = 1280
    agent.height = 720
    agent.text = "StageBoundAgent integration for Youtuber Preview"
    
    task_id = "youtuber_preview_task_001"
    
    async def run_integration():
        # タスクを登録して READY 状態にする
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        # エージェントを起動
        await agent.start(resolve_youtuber_preview_task.__get__(agent, StageBoundAgent))
        
        # 完了を待つ (タイムアウト付き)
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        # アサーション
        assert final_status == "COMPLETED"
        
        # 出力されたファイルの存在と品質を検証
        output_path = output_dir / f"{task_id}_youtuber_preview.png"
        assert output_path.exists()
        
        result_info = validate_preview_image(output_path)
        assert result_info["width"] == 1280
        assert result_info["height"] == 720
        assert result_info["size_bytes"] < 4 * 1024 * 1024
        
        # DBに結果が正常に保存されているか確認 (結果保存、マイグレーション機能の連携)
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, result_str, retry_count = row
            assert status == "COMPLETED"
            assert retry_count == 0
            
            db_result = json.loads(result_str)
            assert db_result["width"] == 1280
            assert db_result["height"] == 720
            assert "path" in db_result
        finally:
            conn.close()
            
    asyncio.run(run_integration())
