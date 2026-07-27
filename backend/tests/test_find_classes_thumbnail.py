# -*- coding: utf-8 -*-
import pytest
from pathlib import Path
from PIL import Image
import os
import sys
import json
import asyncio
import sqlite3

# backend ディレクトリをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from tests.scratch.find_classes import (
    generate_find_classes_thumbnail,
    validate_thumbnail,
    resolve_find_classes_task,
    OUTPUT_DIR
)
from agents.stage_bound_agent import StageBoundAgent

def test_generate_thumbnail_success(tmp_path):
    """正常系: サムネイル画像が正常に生成され、品質検証をパスすること"""
    output_file = tmp_path / "test_thumb.png"
    text = "Unit Test Find Classes"
    
    res_path = generate_find_classes_thumbnail(output_file, width=1280, height=720, text=text)
    assert res_path.exists()
    
    result_info = validate_thumbnail(res_path)
    assert result_info["width"] == 1280
    assert result_info["height"] == 720
    assert result_info["size_bytes"] < 4 * 1024 * 1024
    
    # Pillowで正常にロード可能であることを確認
    with Image.open(res_path) as img:
        img.verify()
        
def test_thumbnail_quality_failures(tmp_path):
    """異常系: 画像の解像度不足、アスペクト比異常、サイズ超過に対する品質検証失敗をテスト"""
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        validate_thumbnail(tmp_path / "non_existent.png")
        
    # 2. 解像度不足の画像生成
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(low_res_path, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_thumbnail(low_res_path)
        
    # 3. アスペクト比が異なる画像
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(bad_ratio_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_thumbnail(bad_ratio_path)
        
    # 4. ファイルサイズ制限
    valid_img_path = tmp_path / "valid.png"
    generate_find_classes_thumbnail(valid_img_path)
    from unittest.mock import patch
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_thumbnail(valid_img_path)

def test_stage_bound_agent_integration(tmp_path):
    """StageBoundAgentとの連携テスト (DBマイグレーション、自動リトライ、結果保存)"""
    db_file = tmp_path / "test_find_classes_agent.db"
    
    # OUTPUT_DIRを一時ディレクトリに書き換える (テストによるゴミファイル作成防止)
    test_output_dir = tmp_path / "temp_thumbnails"
    test_output_dir.mkdir(parents=True, exist_ok=True)
    
    # モジュールのグローバル変数を差し替える
    import sys
    for mod_name in list(sys.modules.keys()):
        if "find_classes" in mod_name:
            mod = sys.modules[mod_name]
            if hasattr(mod, "OUTPUT_DIR"):
                setattr(mod, "OUTPUT_DIR", str(test_output_dir))
                
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "test_find_classes_task"
    
    async def run_test():
        # タスクをREADYで登録
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        # Agentを起動し、resolve_find_classes_taskを実行
        await agent.start(resolve_find_classes_task)
        
        # 完了を待つ (最大2.5秒)
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 画像が存在し、破損していないか再検証
        output_path = test_output_dir / f"{task_id}.png"
        assert output_path.exists()
        
        result_info = validate_thumbnail(output_path)
        assert result_info["width"] == 1280
        assert result_info["height"] == 720
        assert result_info["size_bytes"] < 4 * 1024 * 1024
        
        # DBに結果が正常に保存されているか確認 (マイグレーションと結果保存の検証)
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
            
    asyncio.run(run_test())
