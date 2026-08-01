# -*- coding: utf-8 -*-
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _wp
except ImportError:
    from path_resolver import writable_path as _wp

import os
import sqlite3
import pytest
import asyncio
from pathlib import Path
from PIL import Image

from branding.history_manager import (
    PremiumThumbnailGenerator,
    ThumbnailValidator,
    resolve_thumbnail_task,
    ImageValidationError
)
from agents.stage_bound_agent import StageBoundAgent

@pytest.mark.asyncio
async def test_thumbnail_quality_standards():
    """
    サムネイル生成の必須品質基準をテスト：
    1. 解像度が 1280x720 以上であること
    2. アスペクト比が 16:9 であること
    3. ファイルサイズが 4MB 未満であること
    4. 出力ファイルが正常に存在し、破損していないこと（Pillowでロード可能）
    """
    output_dir = _wp("backend/temp_thumbnails_test")
    output_path = output_dir / "test_quality.png"
    if output_path.exists():
        output_path.unlink()
        
    try:
        # 画像生成 (長い日本語テキストの折り返しも同時にテスト)
        text = "本日は晴天なり。素晴らしい動画スタジオの自動化プロジェクト27を検証しています。"
        PremiumThumbnailGenerator.generate(output_path, text=text)
        
        # 検証
        assert output_path.exists()
        
        # Pillowでロードして破損がないこと
        with Image.open(output_path) as img:
            img.load()
            width, height = img.size
            
        assert width >= 1280
        assert height >= 720
        
        aspect_ratio = width / height
        assert abs(aspect_ratio - (16.0 / 9.0)) < 0.05
        
        file_size = output_path.stat().st_size
        assert file_size < 4 * 1024 * 1024 # 4MB未満
        
        # Validatorでも検証
        with open(output_path, "rb") as f:
            img_bytes = f.read()
        ThumbnailValidator.validate_image(img_bytes)
        
    finally:
        if output_path.exists():
            output_path.unlink()
        if output_dir.exists():
            try:
                output_dir.rmdir()
            except OSError:
                pass

@pytest.mark.asyncio
async def test_stage_bound_agent_integration():
    """
    StageBoundAgent 等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作することを検証
    """
    db_path = str(_wp("backend/temp_thumbnails_test_agent.db"))
    if os.path.exists(db_path):
        os.unlink(db_path)
        
    # テスト用の出力ディレクトリ
    output_dir = _wp("backend/temp_thumbnails_test_agent_out")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Agentの初期化
        agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path)
        
        # タスクIDの作成
        task_id = "test_task_001"
        
        # タスクを登録 (READY状態で登録し、自動実行対象にする)
        await agent.register_task(task_id, initial_status="READY", max_retries=2)
        
        # process_func として resolve_thumbnail_task をラップ
        async def mock_process(t_id):
            return await resolve_thumbnail_task(t_id, db_path=db_path, output_dir=output_dir)
            
        # Agentスタート
        await agent.start(mock_process)
        
        # タスクがCOMPLETEDになるまで待機 (最大5秒)
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.1)
            
        # 停止
        await agent.stop()
        
        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"
        
        # SQLite DBに結果が保存されているか、マイグレーションが効いているか確認
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        
        # カラム構造検証: task_id, path, width, height, size_bytes, verified_at
        saved_task_id, saved_path, saved_width, saved_height, saved_size, verified_at = row
        assert saved_task_id == task_id
        assert Path(saved_path).exists()
        assert saved_width >= 1280
        assert saved_height >= 720
        assert saved_size < 4 * 1024 * 1024
        
        conn.close()
        
    finally:
        # クリーンアップ
        if os.path.exists(db_path):
            os.unlink(db_path)
        # WALやSHMファイルのクリーンアップ
        for ext in ["-wal", "-shm"]:
            p = db_path + ext
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass
        import shutil
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
