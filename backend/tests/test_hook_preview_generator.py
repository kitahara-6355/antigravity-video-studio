import pytest
import os
import sqlite3
import json
import base64
import asyncio
from pathlib import Path
from PIL import Image

from services.hook_preview_generator import hook_preview_generator, HookPreviewResult
from agents.stage_bound_agent import StageBoundAgent

@pytest.mark.asyncio
async def test_hook_preview_quality_standards(tmp_path):
    '''デモモード (動画なし) でのプレビュー生成テストと品質要件の検証'''
    result = await hook_preview_generator.generate_screenshot_preview(
        video_path="non_existent.mp4",
        original_text="テスト前のフックテキスト",
        improved_text="改善された後の高品質なフックテキスト。16:9比率でのプレビュー表示テストです。",
        timestamp=2.5
    )
    
    assert result.success is True
    assert result.before_image is not None
    assert result.after_image is not None
    assert result.comparison_image is not None
    
    # Base64デコードして品質検証
    for img_b64 in [result.before_image, result.after_image, result.comparison_image]:
        img_data = base64.b64decode(img_b64)
        tmp_img = tmp_path / "decoded.png"
        tmp_img.write_bytes(img_data)
        
        # 品質要件の検証
        val_res = hook_preview_generator.validate_preview_image(str(tmp_img))
        assert val_res["width"] >= 1280
        assert val_res["height"] >= 720
        assert abs((val_res["width"] / val_res["height"]) - (16.0 / 9.0)) <= 0.01
        assert val_res["size_bytes"] < 4 * 1024 * 1024

@pytest.mark.asyncio
async def test_stage_bound_agent_integration(tmp_path):
    '''StageBoundAgent連携とDBマイグレーションの検証'''
    db_file = tmp_path / "test_tasks.db"
    
    # StageBoundAgentを初期化
    agent = StageBoundAgent(stage_name="hook_preview", db_path=str(db_file))
    
    # タスクIDとパラメータを登録
    task_id = "test_hook_task_001"
    
    # 登録時点では params カラムが存在しないことを検証
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
    
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    assert "params" not in columns
    conn.close()
    
    # resolve_hook_preview_task を呼び出す（内部でparamsカラムが追加される）
    result_json = await hook_preview_generator.resolve_hook_preview_task(task_id, db_path=str(db_file))
    
    # 完了後のカラム検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    assert "params" in columns
    conn.close()
    
    # 結果の検証
    res = json.loads(result_json)
    assert res["success"] is True
    assert "width" in res
    assert res["width"] >= 1280
    assert res["height"] >= 720

@pytest.mark.asyncio
async def test_stage_bound_agent_retry_on_failure(tmp_path):
    '''エラー発生時の自動リトライ連携の検証'''
    db_file = tmp_path / "test_retry.db"
    agent = StageBoundAgent(stage_name="hook_preview", db_path=str(db_file))
    
    task_id = "test_retry_task_002"
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
    
    # 不正なパラメータを仕込んで確実に失敗させる
    conn = sqlite3.connect(str(db_file))
    conn.execute("ALTER TABLE tasks ADD COLUMN params TEXT")
    # preview_type を video にし、存在しない動画ファイルを指定して ffmpeg で失敗させる
    params = {"preview_type": "video", "video_path": "non_existent_video_file_to_force_failure.mp4"}
    conn.execute("UPDATE tasks SET params = ? WHERE id = ?", (json.dumps(params), task_id))
    conn.commit()
    conn.close()
    
    # 非同期ラッパー関数を定義し、iscoroutinefunctionでTrueと判定させる
    async def fail_process(tid):
        return await hook_preview_generator.resolve_hook_preview_task(tid, db_path=str(db_file))
    
    # StageBoundAgentを起動してエラーを発生させる
    task = asyncio.create_task(agent.start(fail_process))
    
    # 短い時間待ち、処理を強制停止
    await asyncio.sleep(0.5)
    await agent.stop()
    try:
        await task
    except asyncio.CancelledError:
        pass
        
    # ステータスとリトライカウントを検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT status, retry_count FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    assert row is not None
    assert row[1] == 1  # リトライカウントがインクリメントされていること
    assert row[0] == "FAILED"  # 最大リトライに達して FAILED に遷移したこと
    conn.close()


@pytest.mark.asyncio
async def test_hook_preview_explicit_quality_checks(tmp_path):
    """
    生成画像の解像度 (1280x720以上)、アスペクト比 (16:9)、ファイルサイズ (4MB未満)、
    および破損していないことの明示的な品質検証テスト。
    """
    output_img = tmp_path / "quality_check.png"
    
    # 1. Pillow で画像生成
    text = "高品質サムネイルテストのための非常に明確なテキスト"
    hook_preview_generator._generate_image_pillow(text, str(output_img), label="BEFORE")
    
    # ファイル存在確認
    assert output_img.exists()
    
    # 2. 画像の品質検証 (解像度, アスペクト比, サイズ, 破損なし)
    val_res = hook_preview_generator.validate_preview_image(str(output_img))
    assert val_res["width"] >= 1280
    assert val_res["height"] >= 720
    assert abs((val_res["width"] / val_res["height"]) - (16.0 / 9.0)) <= 0.01
    assert val_res["size_bytes"] < 4 * 1024 * 1024
    
    # Pillowで再度開いてロード確認 (破損していないことの確認)
    with Image.open(output_img) as img:
        img.verify()
    with Image.open(output_img) as img:
        img.load()  # 実際にピクセルデータを読み込むことで破損していないことを確認


@pytest.mark.asyncio
async def test_hook_preview_edge_cases(tmp_path):
    """
    極端な入力値に対するエラーハンドリングとクランプ処理の検証テスト。
    """
    # 1. 非常に長いテキスト
    long_text = "あ" * 1000
    output_img_long = tmp_path / "long_text.png"
    hook_preview_generator._generate_image_pillow(long_text, str(output_img_long), label="AFTER")
    assert output_img_long.exists()
    
    val_res_long = hook_preview_generator.validate_preview_image(str(output_img_long))
    assert val_res_long["width"] >= 1280
    assert val_res_long["height"] >= 720
    
    # 2. 空文字列
    output_img_empty = tmp_path / "empty_text.png"
    hook_preview_generator._generate_image_pillow("", str(output_img_empty), label="BEFORE")
    assert output_img_empty.exists()
    val_res_empty = hook_preview_generator.validate_preview_image(str(output_img_empty))
    assert val_res_empty["width"] >= 1280
    
    # 3. 負のタイムスタンプや None に対する generate_screenshot_preview の堅牢性
    result = await hook_preview_generator.generate_screenshot_preview(
        video_path="non_existent.mp4",
        original_text=None,
        improved_text=None,
        timestamp=-10.0
    )
    assert result.success is True
    assert result.before_image is not None
    assert result.after_image is not None


@pytest.mark.asyncio
async def test_hook_preview_video_corruption_fallback(tmp_path):
    """
    破損した動画ファイルが指定された場合でも、FFmpegのエラーを安全に処理し、
    高品質なPillowプレースホルダー画像にフォールバックして正常な画像を生成すること。
    品質要件（解像度 1280x720 以上、アスペクト比 16:9、4MB未満、破損なし）をすべて満たすこと。
    """
    corrupt_video = tmp_path / "corrupt_video.mp4"
    corrupt_video.write_text("This is not a valid video file content. Force FFmpeg to fail.")
    
    # プレビュー生成を実行
    result = await hook_preview_generator.generate_screenshot_preview(
        video_path=str(corrupt_video),
        original_text="破損動画テスト元",
        improved_text="改善されたテキストでフォールバック確認",
        timestamp=1.0
    )
    
    # フォールバックにより成功するはず
    assert result.success is True
    assert result.comparison_image is not None
    
    # 生成された画像の品質を検証
    comparison_data = base64.b64decode(result.comparison_image)
    comparison_file = tmp_path / "corrupt_fallback_comparison.png"
    comparison_file.write_bytes(comparison_data)
    
    val_res = hook_preview_generator.validate_preview_image(str(comparison_file))
    assert val_res["width"] >= 1280
    assert val_res["height"] >= 720
    assert abs((val_res["width"] / val_res["height"]) - (16.0 / 9.0)) <= 0.01
    assert val_res["size_bytes"] < 4 * 1024 * 1024
    
    # Pillowによる破損なしチェック
    with Image.open(comparison_file) as img:
        img.verify()
    with Image.open(comparison_file) as img:
        img.load()

