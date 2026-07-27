# -*- coding: utf-8 -*-
# Phase 27: サムネイル品質向上タスク (解像度 >= 1280x720, 16:9アスペクト比, < 4MB制限, Pillow破損検知, StageBoundAgent連携)
import sys
import os
import pytest
import json
import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

# パス追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.agents.stage_bound_agent import (
    StageBoundAgent,
    generate_thumbnail,
    validate_thumbnail,
    resolve_thumbnail_task
)

def test_generate_and_validate_success(tmp_path):
    """正常系: 品質基準を満たした画像が生成され、検証が通ることを確認"""
    img_path = tmp_path / "valid_thumbnail.png"
    text = "Antigravity Premium Thumbnail"
    
    generate_thumbnail(img_path, width=1280, height=720, text=text)
    
    assert img_path.exists()
    
    result = validate_thumbnail(img_path)
    assert result["path"] == str(img_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] < 4 * 1024 * 1024
    
    # ピクセルデータのデコードチェック
    with Image.open(img_path) as img:
        img.load()
        assert img.size == (1280, 720)

def test_validation_file_not_found():
    """異常系: ファイルが存在しない場合に FileNotFoundError が発生することを確認"""
    with pytest.raises(FileNotFoundError):
        validate_thumbnail("non_existent_thumbnail_file.png")

def test_generate_resolution_insufficient(tmp_path):
    """異常系: 解像度が足りない場合に ValueError が発生することを確認"""
    img_path = tmp_path / "low_res.png"
    # 1280x720 未満
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        generate_thumbnail(img_path, width=640, height=360)

def test_generate_aspect_ratio_invalid(tmp_path):
    """異常系: アスペクト比が 16:9 ではない場合に ValueError が発生することを確認"""
    img_path = tmp_path / "bad_ratio.png"
    # 1280x960 (4:3)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        generate_thumbnail(img_path, width=1280, height=960)

def test_validation_file_size_exceeded(tmp_path):
    """異常系: ファイルサイズが 4MB を超える場合に ValueError が発生することを確認"""
    img_path = tmp_path / "oversized.png"
    generate_thumbnail(img_path)
    
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_thumbnail(img_path)

def test_validation_corrupted_image(tmp_path):
    """異常系: 画像データが破損している場合に ValueError が発生することを確認"""
    img_path = tmp_path / "corrupted.png"
    with open(img_path, "wb") as f:
        f.write(b"invalid image header and pixel payload")
        
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_thumbnail(img_path)

def test_stage_bound_agent_thumbnail_integration(tmp_path):
    """StageBoundAgent / DB結果保存 / 非同期リトライフローとの連携検証"""
    db_file = tmp_path / "test_stage_bound_thumb.db"
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    # output_dir 属性などを設定
    agent.output_dir = tmp_path
    agent.width = 1920
    agent.height = 1080
    agent.text = "High Quality 1080p Thumbnail"
    
    task_id = "agent_thumb_task_001"
    
    async def run_test():
        # タスクを READY 状態で登録
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        # 非同期で解決処理を開始
        # resolve_thumbnail_task は self (agent) を第一引数に取るため、部分適用かラムダで渡す
        async def process_func(tid):
            return await resolve_thumbnail_task(agent, tid)
            
        await agent.start(process_func)
        
        # 完了または失敗まで待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 生成された画像ファイルを確認
        output_file = tmp_path / f"{task_id}.png"
        assert output_file.exists()
        
        # 画像品質の検証
        result_info = validate_thumbnail(output_file)
        assert result_info["width"] == 1920
        assert result_info["height"] == 1080
        assert result_info["size_bytes"] < 4 * 1024 * 1024
        
        # DBに書き込まれた結果を確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, result_str, retry_count = row
            assert status == "COMPLETED"
            assert retry_count == 0
            
            db_result = json.loads(result_str)
            assert db_result["width"] == 1920
            assert db_result["height"] == 1080
            assert "path" in db_result
        finally:
            conn.close()

    asyncio.run(run_test())

def test_stage_bound_agent_retry_on_failure(tmp_path):
    """異常系: 画像生成で一時エラーが発生した場合に自動リトライフローが動作することを検証"""
    db_file = tmp_path / "test_stage_bound_retry.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    task_id = "agent_thumb_retry_task"
    
    # 最初の1回は失敗し、2回目で成功させる process_func
    call_count = 0
    
    async def process_func(tid):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("Simulated temporary storage failure")
        
        # 2回目は正常終了
        agent.output_dir = tmp_path
        agent.width = 1280
        agent.height = 720
        agent.text = "Retry Success"
        return await resolve_thumbnail_task(agent, tid)

    async def run_test():
        # 最大リトライ回数を 2 に設定して登録
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        await agent.start(process_func)
        
        # 完了するまで少し待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            # READY (リトライ待ち) に戻り、その後 COMPLETED になる
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        assert call_count == 2  # 2回呼び出されたことを確認
        
        # DBでリトライカウントが 1 になっていることを確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, retry_count, error FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, retry_count, error = row
            assert status == "COMPLETED"
            assert retry_count == 1
        finally:
            conn.close()

    asyncio.run(run_test())


def test_thumbnail_resolution_variations(tmp_path):
    """追加検証: 各種解像度の境界値テスト"""
    # 正常系: 1920x1080 (16:9)
    img_path = tmp_path / "1080p.png"
    generate_thumbnail(img_path, width=1920, height=1080)
    res = validate_thumbnail(img_path)
    assert res["width"] == 1920
    assert res["height"] == 1080

    # 異常系: 1280x720 未満 (1279x720)
    bad_path1 = tmp_path / "low_w.png"
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        generate_thumbnail(bad_path1, width=1279, height=720)

    # 正常系: 8K (7680x4320)
    img_path_8k = tmp_path / "8k.png"
    generate_thumbnail(img_path_8k, width=7680, height=4320)
    res_8k = validate_thumbnail(img_path_8k)
    assert res_8k["width"] == 7680
    assert res_8k["height"] == 4320

    # 異常系: 8K超過 (7681x4320)
    bad_path2 = tmp_path / "too_large.png"
    with pytest.raises(ValueError, match="Resolution exceeds maximum limit"):
        generate_thumbnail(bad_path2, width=7681, height=4320)

def test_thumbnail_aspect_ratio_variations(tmp_path):
    """追加検証: 各種アスペクト比の境界値テスト"""
    # 正常系: ほぼ16:9 (1280x720 => 1.7777...)
    img_path = tmp_path / "ratio_ok.png"
    generate_thumbnail(img_path, width=1280, height=720)
    res = validate_thumbnail(img_path)
    assert abs((res["width"] / res["height"]) - (16.0/9.0)) < 0.01

    # 異常系: 4:3 (1440x1080)
    bad_path = tmp_path / "ratio_bad.png"
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        generate_thumbnail(bad_path, width=1440, height=1080)

def test_thumbnail_file_size_limit(tmp_path):
    """追加検証: ファイルサイズ4MB未満の検証"""
    img_path = tmp_path / "size_ok.png"
    generate_thumbnail(img_path, width=1280, height=720, text="Large text outline decorator border " * 5)
    res = validate_thumbnail(img_path)
    # 最適化によって4MBよりはるかに小さいはず（通常は数百KB以下）
    assert res["size_bytes"] < 4 * 1024 * 1024
    assert res["size_bytes"] > 0

    # 異常系: 4MB以上のファイルを擬似的に作成し、検証時にエラーが出ることを確認
    large_path = tmp_path / "large_file.png"
    generate_thumbnail(large_path, width=1280, height=720)
    # パスが正常に書き込まれた後、ファイルを4.1MBにパディングする
    with open(large_path, "ab") as f:
        f.write(b"\x00" * (4 * 1024 * 1024))
    
    with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
        validate_thumbnail(large_path)

def test_thumbnail_corruption_detection(tmp_path):
    """追加検証: Pillowによる画像破損検知のテスト"""
    img_path = tmp_path / "corrupted_detection.png"
    generate_thumbnail(img_path, width=1280, height=720)
    
    # 正常ロード確認
    res = validate_thumbnail(img_path)
    assert res["width"] == 1280
    
    # 破損ファイル (ヘッダーはPNGだが中身を上書き)
    corrupt_path = tmp_path / "bad_data.png"
    with open(corrupt_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100) # PNGヘッダーだけ書いてあとはゴミデータ
        
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_thumbnail(corrupt_path)

def test_thumbnail_empty_and_none_text(tmp_path):
    """検証: テキストが空またはNoneの場合に正常に生成されること"""
    img_path1 = tmp_path / "empty_text.png"
    generate_thumbnail(img_path1, width=1280, height=720, text="")
    res1 = validate_thumbnail(img_path1)
    assert res1["width"] == 1280

    img_path2 = tmp_path / "none_text.png"
    from backend.services.thumbnail_analyzer import thumbnail_analyzer
    thumbnail_analyzer.generate_thumbnail(img_path2, width=1280, height=720, text=None)
    res2 = validate_thumbnail(img_path2)
    assert res2["width"] == 1280

def test_thumbnail_long_text_wrapping(tmp_path):
    """検証: 非常に長いテキストが指定された場合でも、はみ出さずに安全に描画されること"""
    img_path = tmp_path / "long_text.png"
    long_text = "これは非常に長いテキストのテストケースです。このテキストは複数行に折り返される必要があります。バナー内にはみ出さず、画像が破損することなく、最後までクラッシュせずに生成されることをテストします。" * 3
    generate_thumbnail(img_path, width=1280, height=720, text=long_text)
    res = validate_thumbnail(img_path)
    assert res["width"] == 1280
    assert img_path.exists()

def test_thumbnail_invalid_resolution_types(tmp_path):
    """検証: 解像度に無効な型や無効な値を指定した場合のエラーハンドリング"""
    img_path = tmp_path / "invalid_type.png"
    # 文字列の数値(正常)
    generate_thumbnail(img_path, width="1280", height="720")
    assert validate_thumbnail(img_path)["width"] == 1280

    # 数値変換できない文字列
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_thumbnail(img_path, width="not_an_int", height=720)

    # 負の解像度
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_thumbnail(img_path, width=-1280, height=720)

    # ゼロの解像度
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_thumbnail(img_path, width=1280, height=0)

def test_thumbnail_unsupported_format(tmp_path):
    """検証: サポートされていない画像フォーマットが指定された場合のエラーハンドリング"""
    img_path = tmp_path / "invalid_format.gif"
    with pytest.raises(ValueError, match="Unsupported file format"):
        generate_thumbnail(img_path, width=1280, height=720)

def test_thumbnail_invalid_output_path_directory(tmp_path):
    """検証: 出力パスにファイル名ではなくディレクトリを指定した場合のエラーハンドリング"""
    with pytest.raises(ValueError, match="Output path must be a file path, not a directory"):
        generate_thumbnail(tmp_path, width=1280, height=720)

def test_thumbnail_aspect_ratio_boundary(tmp_path):
    """検証: アスペクト比 16:9 の境界値検証"""
    img_path = tmp_path / "aspect_boundary.png"
    # ほぼ 16:9 (許容誤差 0.01 内)
    # 1281 / 720 = 1.77916... (1.7777... との差は 0.0014 < 0.01)
    generate_thumbnail(img_path, width=1281, height=720)
    assert validate_thumbnail(img_path)["width"] == 1281

    # 許容誤差を超えるアスペクト比
    # 1290 / 720 = 1.7916... (1.7777... との差は 0.0139 > 0.01)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        generate_thumbnail(img_path, width=1290, height=720)


def test_thumbnail_plugin_success(tmp_path):
    """正常系: ThumbnailPlugin が正常に実行され、結果が context に設定されること"""
    from backend.plugins.thumbnail_plugin import ThumbnailPlugin
    from backend.core import ProductionContext
    
    # context のモック
    context = MagicMock(spec=ProductionContext)
    context.get_extension.side_effect = lambda key, default=None: {
        "video_title": "Test Title",
        "video_description": "Test Description"
    }.get(key, default)
    context.segments = []
    context.db_path = str(tmp_path / "test_thumb.db")
    
    # 候補のモック
    class DummyCandidate:
        def __init__(self, cid, path):
            self.id = cid
            self.concept = "Concept"
            self.target_emotion = "Joy"
            self.text_overlay = "Overlay Text"
            self.predicted_ctr = 0.8
            self.path = path
            
    # 正しいダミー画像を一時的に作成
    valid_path = tmp_path / "candidate_001.png"
    generate_thumbnail(valid_path, width=1280, height=720, text="Plugin Test")
    
    candidate = DummyCandidate("c1", valid_path)
    
    # youtube_optimizer のモック
    mock_yt_opt = MagicMock()
    
    # optimize_context は async なので Future / Coroutine を返すようにする
    async def dummy_optimize(*args, **kwargs):
        res = MagicMock()
        res.thumbnail_candidates = [candidate]
        return res
        
    mock_yt_opt.optimize_context = dummy_optimize
    
    # service_container のモック
    with patch("service_container.container") as mock_container, \
         patch("service_container.setup_services"):
        mock_container.has.return_value = True
        mock_container.get.return_value = mock_yt_opt
        
        plugin = ThumbnailPlugin(num_candidates=1)
        result_ctx = plugin.execute(context)
        
        # 期待通り context に候補が設定されているか
        assert result_ctx is not None
        assert len(result_ctx.thumbnail_candidates) == 1
        assert result_ctx.thumbnail_candidates[0]["id"] == "c1"
        assert result_ctx.thumbnail_candidates[0]["path"] == valid_path
        
        # 保存先DBの中身確認
        conn = sqlite3.connect(context.db_path)
        try:
            cursor = conn.execute("SELECT status FROM tasks")
            rows = cursor.fetchall()
            assert len(rows) > 0
            assert rows[0][0] == "COMPLETED"
        finally:
            conn.close()


def test_thumbnail_plugin_import_failure():
    """異常系: plugins.youtube_optimizer_plugin がインポート失敗した場合に ThumbnailPluginError を送出すること"""
    from backend.plugins.thumbnail_plugin import ThumbnailPlugin, ThumbnailPluginError
    from backend.core import ProductionContext
    
    context = MagicMock(spec=ProductionContext)
    context.get_extension.return_value = "Test Title"
    
    # インポート失敗をシミュレートするため、sys.modules にダミーを設定
    with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": None}), \
         pytest.raises(ThumbnailPluginError) as exc_info:
        plugin = ThumbnailPlugin()
        plugin.execute(context)
        
    assert "Import failed" in str(exc_info.value)


def test_thumbnail_plugin_validation_failure(tmp_path):
    """異常系: サムネイル生成で検証エラー（解像度不足）が起き、ThumbnailPluginError となること"""
    from backend.plugins.thumbnail_plugin import ThumbnailPlugin, ThumbnailPluginError
    from backend.core import ProductionContext
    
    context = MagicMock(spec=ProductionContext)
    context.get_extension.side_effect = lambda key, default=None: {
        "video_title": "Test Title"
    }.get(key, default)
    context.db_path = str(tmp_path / "test_thumb_fail.db")
    
    class DummyCandidate:
        def __init__(self, cid, path):
            self.id = cid
            self.path = path
            
    # 破損した画像を生成して設定
    invalid_path = tmp_path / "corrupted.png"
    with open(invalid_path, "wb") as f:
        f.write(b"corrupted raw data")
    
    candidate = DummyCandidate("c_invalid", invalid_path)
    
    mock_yt_opt = MagicMock()
    async def dummy_optimize(*args, **kwargs):
        res = MagicMock()
        res.thumbnail_candidates = [candidate]
        return res
    mock_yt_opt.optimize_context = dummy_optimize
    
    with patch("service_container.container") as mock_container, \
         patch("service_container.setup_services"), \
         pytest.raises(ThumbnailPluginError) as exc_info:
        mock_container.has.return_value = True
        mock_container.get.return_value = mock_yt_opt
        
        plugin = ThumbnailPlugin(num_candidates=1)
        plugin.execute(context)
        
    assert "Validation failure" in str(exc_info.value)


def test_stage_bound_agent_call_llm_api_error(tmp_path):
    """call_llm の実行時に google.genai.errors.APIError が発生した場合、RuntimeError として正しく送出されること"""
    db_file = tmp_path / "test_stage_bound_llm.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    from google.genai.errors import APIError
    
    mock_api_error = APIError(code=500, response_json={"error": {"message": "Simulated API Error"}})
    
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_api_error
    
    with patch("google.genai.Client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Default client call failed: 500 None. .*Simulated API Error"):
            asyncio.run(agent.call_llm(prompt="test prompt", model="gemini-2.5-flash"))
