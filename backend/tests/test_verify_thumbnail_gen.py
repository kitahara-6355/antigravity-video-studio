# 出力先は実装と同じ経路で解決する。直書きすると、実装を writable_path へ
# 寄せた後もテストだけがリポジトリ内を見に行き、本番ディレクトリを掴む。
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _wp
except ImportError:
    from path_resolver import writable_path as _wp

import sys
import os
import base64
import runpy
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image
import io

# backend ディレクトリをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
services_dir = backend_dir / 'services'
if str(services_dir) not in sys.path:
    sys.path.insert(0, str(services_dir))

import verify_thumbnail_gen
from combined_overlay import CombinedOverlay
from scripts.gen_session9 import validate_session9_thumbnails

def create_valid_test_image_b64(width=1280, height=720, fmt="PNG") -> str:
    """Pillowを使用して、指定解像度の有効な画像データ(Base64)を作成する"""
    img = Image.new("RGB", (width, height), color=(73, 109, 137))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def test_thumbnail_generation_success():
    """正常系: APIレスポンスから正常にサムネイル画像が保存され、品質検証をパスするケース"""
    valid_image_b64 = create_valid_test_image_b64(1280, 720)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "count": 2,
        "thumbnails": [
            {
                "concept_name": "Concept A",
                "description": "Description A",
                "ctr_score": 5.5,
                "image_base64": valid_image_b64
            },
            {
                "concept_name": "Concept B",
                "description": "Description B",
                "ctr_score": 6.2,
                "image_base64": valid_image_b64
            }
        ]
    }
    
    with patch("requests.post", return_value=mock_response) as mock_post:
        # 実際にファイルを書き出し、検証が通ることを確認
        verify_thumbnail_gen.test_thumbnail_generation()
        
        assert mock_post.called
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["video_title"] == "書道家・北原美麗の挑戦：伝統と革新の融合"

def test_thumbnail_generation_quality_failures():
    """異常系: 画像解像度が足りない、またはアスペクト比が異なる場合に品質検証でエラーが投げられるケース"""
    overlay = CombinedOverlay()
    
    # 1. 解像度が低い画像 (例えば 640x360)
    invalid_res_b64 = create_valid_test_image_b64(640, 360)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "count": 1,
        "thumbnails": [
            {
                "concept_name": "Invalid Res Concept",
                "description": "Low resolution image",
                "ctr_score": 3.2,
                "image_base64": invalid_res_b64
            }
        ]
    }
    with patch("requests.post", return_value=mock_response):
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            verify_thumbnail_gen.test_thumbnail_generation()

    # 2. アスペクト比が正しくない画像 (4:3 解像度 1280x960)
    invalid_ratio_b64 = create_valid_test_image_b64(1280, 960)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "count": 1,
        "thumbnails": [
            {
                "concept_name": "Invalid Ratio Concept",
                "description": "4:3 aspect ratio image",
                "ctr_score": 4.1,
                "image_base64": invalid_ratio_b64
            }
        ]
    }
    with patch("requests.post", return_value=mock_response):
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            verify_thumbnail_gen.test_thumbnail_generation()

def test_thumbnail_generation_http_error():
    """異常系: HTTPErrorが発生し、レスポンス内容が出力されるケース"""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request Detail"
    from requests.exceptions import HTTPError
    mock_response.raise_for_status.side_effect = HTTPError("HTTP Error Occurred", response=mock_response)
    
    with patch("requests.post", return_value=mock_response) as mock_post:
        with pytest.raises(HTTPError):
            verify_thumbnail_gen.test_thumbnail_generation()
        assert mock_post.called

def test_thumbnail_generation_other_exception():
    """異常系: ConnectionErrorやTimeoutなどのその他の例外が発生するケース"""
    from requests.exceptions import Timeout
    
    with patch("requests.post", side_effect=Timeout("Connection Timeout")) as mock_post:
        with pytest.raises(Timeout):
            verify_thumbnail_gen.test_thumbnail_generation()
        assert mock_post.called

def test_main_block_execution():
    """__main__ブロックの実行ルートをカバーする"""
    valid_image_b64 = create_valid_test_image_b64(1280, 720)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "count": 1,
        "thumbnails": [
            {
                "concept_name": "Concept A",
                "description": "Description A",
                "ctr_score": 5.5,
                "image_base64": valid_image_b64
            }
        ]
    }
    
    with patch("requests.post", return_value=mock_response) as mock_post:
        # runpy で __main__ として実行することで if __name__ == "__main__": ブロックを通過させる
        runpy.run_path(str(backend_dir / "verify_thumbnail_gen.py"), run_name="__main__")
        assert mock_post.called

@pytest.mark.asyncio
async def test_stage_bound_agent_integration(tmp_path):
    """StageBoundAgent / CombinedOverlay との自動検証・結果保存・リトライ連携テスト"""
    db_file = tmp_path / "test_stage_bound_agent_integration.db"
    
    # gen_session9.py に追加した validate_session9_thumbnails() を実行して
    # StageBoundAgent、DB保存、マイグレーション、リトライ、画像品質検証の連携をテストする
    await validate_session9_thumbnails(db_path=str(db_file))
    
    # DBに結果が正しく書き込まれていることをアサート
    import sqlite3
    import json
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", ("session9_thumb_test",))
        row = cursor.fetchone()
        assert row is not None
        status, result_str, retry_count = row
        assert status == "COMPLETED"
        assert retry_count <= 2
        
        result_data = json.loads(result_str)
        assert "width" in result_data
        assert result_data["width"] == 1280
        assert result_data["height"] == 720
        assert "path" in result_data
    finally:
        conn.close()

def test_smartcut_strategy_service_thumbnail_integration(tmp_path):
    """SmartCutStrategyService.resolve_session_thumbnail_task と StageBoundAgent の連携テスト"""
    db_file = tmp_path / "test_strategy_thumb.db"
    output_dir = tmp_path / "thumbnails"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    from services.smartcut_strategy_service import SmartCutStrategyService
    from agents.stage_bound_agent import StageBoundAgent
    import sqlite3
    import json
    import asyncio
    
    service = SmartCutStrategyService()
    service.output_dir = str(output_dir)
    service.width = 1280
    service.height = 720
    service.text = "Test Service Thumbnail"
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "strategy_thumb_test"
    
    async def run_test():
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        await agent.start(service.resolve_session_thumbnail_task)
        
        # 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 画像が存在し、破損していないか再検証
        output_path = output_dir / f"{task_id}.png"
        assert output_path.exists()
        
        from combined_overlay import CombinedOverlay
        overlay = CombinedOverlay()
        result_info = overlay.validate_thumbnail(output_path)
        assert result_info["width"] == 1280
        assert result_info["height"] == 720
        assert result_info["size_bytes"] < 4 * 1024 * 1024
        
    asyncio.run(run_test())


def test_thumbnail_quality_check_plugin(tmp_path):
    """quality_gate_plugins.py の ThumbnailQualityCheck プラグインの動作検証"""
    from quality_gate_plugins import ThumbnailQualityCheck
    
    plugin = ThumbnailQualityCheck()
    
    # ダミーのコンテキストオブジェクト
    class DummyContext:
        def __init__(self, thumbnail_path=None):
            self.thumbnail_path = thumbnail_path
            
    # 1. サムネイルパスなし
    ctx_no_path = DummyContext(None)
    result = plugin.analyze(ctx_no_path)
    assert result["deductions"] == 15
    assert any("存在しません" in f or "設定されていません" in f for f in result["feedback"])
    
    # 2. ファイルが存在しない
    ctx_missing_file = DummyContext(str(tmp_path / "non_existent.jpg"))
    result = plugin.analyze(ctx_missing_file)
    assert result["deductions"] == 15
    assert any("存在しません" in f for f in result["feedback"])
    
    # 3. 正常な画像
    valid_img_path = tmp_path / "valid.png"
    from PIL import Image
    img = Image.new("RGB", (1280, 720), color="blue")
    img.save(valid_img_path, format="PNG")
    
    ctx_valid = DummyContext(str(valid_img_path))
    result = plugin.analyze(ctx_valid)
    assert result["deductions"] == 0
    assert any("合格" in f for f in result["feedback"])
    
    # 4. 解像度不足 (640x360)
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(low_res_path, format="PNG")
    
    ctx_low_res = DummyContext(str(low_res_path))
    result = plugin.analyze(ctx_low_res)
    assert result["deductions"] > 0
    assert any("解像度" in f for f in result["feedback"])
    
    # 5. アスペクト比異常 (1280x960, 4:3)
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(bad_ratio_path, format="PNG")
    
    ctx_bad_ratio = DummyContext(str(bad_ratio_path))
    result = plugin.analyze(ctx_bad_ratio)
    assert result["deductions"] > 0
    assert any("アスペクト比" in f for f in result["feedback"])

    # 6. ファイルサイズ制限 (MagicMockで stat.st_size を 5MB に偽装)
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        result = plugin.analyze(ctx_valid)
        assert result["deductions"] > 0
        assert any("サイズ" in f or "4MB" in f for f in result["feedback"])



def test_mark_timeout_fail_fallback_integration(tmp_path):
    """mark_timeout_fail.py のタイムアウトフォールバック画像生成と品質検証、StageBoundAgent連携テスト"""
    db_file = tmp_path / "test_fallback.db"
    
    from agents.stage_bound_agent import StageBoundAgent
    from agents.orchestration.mark_timeout_fail import (
        resolve_timeout_fallback_task,
        validate_thumbnail_quality,
        generate_fallback_thumbnail
    )
    import sqlite3
    import json
    import asyncio
    
    task_id = "test_fallback_task"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    async def run_test():
        # 1. StageBoundAgent にタスクを登録 (max_retries=1)
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        # 2. Agentを起動して、mark_timeout_failのフォールバックハンドラで実行
        await agent.start(resolve_timeout_fallback_task)
        
        # 完了を待つ (タイムアウト 2.5 秒)
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        # 3. アサーション
        assert final_status == "COMPLETED"
        
        # 出力されたファイルの存在と品質を検証
        output_path = _wp("backend/temp_thumbnails") / f"{task_id}_fallback.png"
        assert output_path.exists()
        
        try:
            # 品質検証が通ることを確認
            result_info = validate_thumbnail_quality(str(output_path))
            assert result_info["width"] == 1280
            assert result_info["height"] == 720
            assert result_info["size_bytes"] < 4 * 1024 * 1024
            
            # DBに結果が正常に保存されているか確認
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
                
        finally:
            # クリーンアップ
            if output_path.exists():
                output_path.unlink()
                
    asyncio.run(run_test())


def test_fallback_thumbnail_quality_failures(tmp_path):
    """異常系: フォールバック画像検証で不適切なサイズやアスペクト比に対して例外が起きることを確認"""
    from agents.orchestration.mark_timeout_fail import validate_thumbnail_quality, generate_fallback_thumbnail
    import pytest
    from PIL import Image
    
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        validate_thumbnail_quality(tmp_path / "missing.png")
        
    # 2. 解像度不足の画像生成
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="red")
    img.save(low_res_path, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_thumbnail_quality(low_res_path)
        
    # 3. アスペクト比が異なる画像
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="red")
    img.save(bad_ratio_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_thumbnail_quality(bad_ratio_path)
        
    # 4. ファイルサイズ制限
    valid_img_path = tmp_path / "valid.png"
    generate_fallback_thumbnail(valid_img_path)
    from unittest.mock import patch
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_thumbnail_quality(valid_img_path)


def test_gcp_cost_monitor_thumbnail_integration(tmp_path):
    """gcp_cost_monitor.py のレポート画像生成、品質検証、および StageBoundAgent 連携の結合テスト"""
    db_file = tmp_path / "gcp_cost_test.db"
    output_dir = tmp_path / "gcp_thumbnails"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    import gcp_cost_monitor
    from agents.stage_bound_agent import StageBoundAgent
    import sqlite3
    import json
    import asyncio
    
    task_id = "gcp_cost_report_task"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    mock_gcloud_stdout = json.dumps([
        {"projectId": "test-project-1", "name": "Test Project 1"},
        {"projectId": "test-project-2", "name": "Test Project 2"}
    ])
    
    mock_run = MagicMock()
    mock_run.return_value = MagicMock(stdout=mock_gcloud_stdout, returncode=0)
    
    with patch("subprocess.run", mock_run):
        async def run_test():
            await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
            
            gcp_cost_monitor.OUTPUT_DIR = str(output_dir)
            
            await agent.start(gcp_cost_monitor.resolve_gcp_cost_monitor_task)
            
            for _ in range(50):
                status = await agent.get_task_status(task_id)
                if status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.05)
                
            final_status = await agent.get_task_status(task_id)
            await agent.stop()
            
            assert final_status == "COMPLETED"
            
            output_path = output_dir / f"{task_id}.png"
            assert output_path.exists()
            
            result_info = gcp_cost_monitor.validate_thumbnail(output_path)
            assert result_info["width"] == 1280
            assert result_info["height"] == 720
            assert result_info["size_bytes"] < 4 * 1024 * 1024
            
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


def test_websocket_handler_thumbnail_integration(tmp_path):
    """websocket_handler.py で WebSocket 経由のサムネイル生成と品質検証・ブロードキャストの統合テスト"""
    import asyncio
    import json
    from unittest.mock import AsyncMock, patch
    from websocket_handler import _process_client_command, broadcaster
    
    output_file = tmp_path / "ws_thumb_test.png"
    
    mock_websocket = AsyncMock()
    
    # generate_thumbnail の要求コマンド
    command = {
        "action": "generate_thumbnail",
        "output_path": str(output_file),
        "width": 1280,
        "height": 720,
        "text": "WebSocket Thumbnail Test"
    }
    
    async def run_test():
        # broadcast_progress などをパッチする
        with patch.object(broadcaster.manager, "broadcast_progress", new_callable=AsyncMock) as mock_broadcast:
            await _process_client_command(mock_websocket, json.dumps(command))
            
            # send_jsonが呼び出されたかチェック
            mock_websocket.send_json.assert_awaited()
            # 送信されたメッセージの検証
            sent_message = mock_websocket.send_json.await_args[0][0]
            assert sent_message["type"] == "thumbnail_result"
            assert sent_message["status"] == "success"
            assert "width" in sent_message["data"]
            assert sent_message["data"]["width"] == 1280
            assert sent_message["data"]["height"] == 720
            
            # 進捗がブロードキャストされたか検証
            mock_broadcast.assert_awaited()
            broadcast_msg = mock_broadcast.await_args[0][0]
            assert broadcast_msg["type"] == "progress_update"
            assert broadcast_msg["phase"] == "thumbnail"
            assert broadcast_msg["progress"] == 100
            
            # 実際にファイルが生成されているか検証
            assert output_file.exists()
            
            # Pillow等で正常にロード可能か確認
            from PIL import Image
            with Image.open(output_file) as img:
                img.verify()
                
        # 異常系テスト: 解像度不足
        bad_command = {
            "action": "generate_thumbnail",
            "output_path": str(output_file),
            "width": 640,
            "height": 360,
            "text": "Bad WebSocket Thumbnail"
        }
        
        mock_websocket.reset_mock()
        with patch.object(broadcaster.manager, "broadcast_progress", new_callable=AsyncMock) as mock_broadcast:
            await _process_client_command(mock_websocket, json.dumps(bad_command))
            
            sent_message = mock_websocket.send_json.await_args[0][0]
            assert sent_message["type"] == "thumbnail_result"
            assert sent_message["status"] == "failed"
            assert "Resolution must be at least 1280x720" in sent_message["error"]
            
            # エラーブロードキャストの検証
            mock_broadcast.assert_awaited()
            broadcast_msg = mock_broadcast.await_args[0][0]
            assert broadcast_msg["type"] == "error"
            assert broadcast_msg["code"] == "THUMB_GEN_ERR"
            
    asyncio.run(run_test())


def test_series_planner_thumbnail_integration(tmp_path):
    """services.series_planner.SeriesPlanner.resolve_series_thumbnail_task と StageBoundAgent の連携テスト"""
    db_file = tmp_path / "test_series_planner_thumb.db"
    output_dir = tmp_path / "series_thumbnails"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    from services.series_planner import SeriesPlanner
    from agents.stage_bound_agent import StageBoundAgent
    import sqlite3
    import json
    import asyncio
    
    planner = SeriesPlanner()
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "series_planner_thumb_test"
    
    async def run_test():
        # StageBoundAgent.output_dir にテスト用の出力先を設定
        planner.output_dir = str(output_dir)
        planner.width = 1280
        planner.height = 720
        planner.text = "Series Planner Integration Test Thumbnail"
        
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        await agent.start(planner.resolve_series_thumbnail_task)
        
        # 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 画像が存在し、破損していないか再検証
        output_path = output_dir / f"{task_id}.png"
        assert output_path.exists()
        
        result_info = planner.validate_thumbnail_quality(output_path)
        assert result_info["width"] == 1280
        assert result_info["height"] == 720
        assert result_info["size_bytes"] < 4 * 1024 * 1024
        
        # DBに結果が正常に保存されているか確認
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
            
        # クリーンアップ
        if output_path.exists():
            output_path.unlink()
            
    asyncio.run(run_test())


def test_sdk_checker_thumbnail_integration(tmp_path):
    """sdk_checker.py のサムネイル画像生成・品質検証・StageBoundAgent連携テスト"""
    db_file = tmp_path / "sdk_checker_thumb_test.db"
    output_dir = tmp_path / "sdk_thumbnails"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    from usage_tracker.sdk_checker import resolve_sdk_checker_task, validate_thumbnail
    from agents.stage_bound_agent import StageBoundAgent
    import sqlite3
    import json
    import asyncio
    import sys
    
    # 読み込まれているすべての sdk_checker モジュールの OUTPUT_DIR を書き換える
    for mod_name in list(sys.modules.keys()):
        if "sdk_checker" in mod_name:
            mod = sys.modules[mod_name]
            if hasattr(mod, "OUTPUT_DIR"):
                setattr(mod, "OUTPUT_DIR", str(output_dir))
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "sdk_checker_thumb_task"
    
    async def run_test():
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        # モックを使ってSDK compatibility checkが正常に行われるようにする
        dummy_result = {
            "timestamp": "2026-05-30T12:00:00",
            "compatible": [{"model": "gemini-1.5-flash", "tier": "standard"}],
            "incompatible": [],
            "warnings": [],
            "sdk_version": "1.0.0"
        }
        
        with patch("usage_tracker.sdk_checker.SDKCompatibilityChecker.check_compatibility", return_value=dummy_result):
            # もし sys.modules に別のモジュール名で登録されている場合も考慮して、すべての compatibility check をパッチする
            patches = []
            for mod_name in list(sys.modules.keys()):
                if "sdk_checker" in mod_name:
                    try:
                        p = patch(f"{mod_name}.SDKCompatibilityChecker.check_compatibility", return_value=dummy_result)
                        p.start()
                        patches.append(p)
                    except Exception:
                        pass
                        
            try:
                await agent.start(resolve_sdk_checker_task)
                
                # 完了を待つ
                for _ in range(50):
                    status = await agent.get_task_status(task_id)
                    if status in ("COMPLETED", "FAILED"):
                        break
                    await asyncio.sleep(0.05)
                    
                final_status = await agent.get_task_status(task_id)
                await agent.stop()
                
                assert final_status == "COMPLETED"
                
                # 画像が存在し、破損していないか再検証
                output_path = output_dir / f"{task_id}.png"
                
                # デバッグ用のプリント
                print(f"DEBUG: Checking for output file at: {output_path}")
                print(f"DEBUG: File exists: {output_path.exists()}")
                
                assert output_path.exists()
                
                result_info = validate_thumbnail(output_path)
                assert result_info["width"] == 1280
                assert result_info["height"] == 720
                assert result_info["size_bytes"] < 4 * 1024 * 1024
                
                # DBに結果が正常に保存されているか確認
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
            finally:
                for p in patches:
                    p.stop()
                
    try:
        asyncio.run(run_test())
    finally:
        pass


def test_sdk_checker_thumbnail_quality_failures(tmp_path):
    """異常系: sdk_checker.py の画像検証で不適切なサイズやアスペクト比に対して例外が起きることを確認"""
    from usage_tracker.sdk_checker import validate_thumbnail, generate_sdk_checker_thumbnail
    import pytest
    from PIL import Image
    
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        validate_thumbnail(tmp_path / "missing.png")
        
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
    generate_sdk_checker_thumbnail(valid_img_path)
    from unittest.mock import patch
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_thumbnail(valid_img_path)


def test_thumbnail_quality_standard_validation(tmp_path):
    """
    最優先ルール: サムネイル品質検証自動化テスト
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    - StageBoundAgent 等に登録され、自動リトライや結果保存、DBマイグレーション of 各機能と連携して動作すること
    """
    from PIL import Image
    from agents.stage_bound_agent import StageBoundAgent, generate_thumbnail, validate_thumbnail
    import sqlite3
    import json
    import asyncio

    output_file = tmp_path / "quality_test_thumb.png"
    
    # 1. 画像生成
    generate_thumbnail(output_file, width=1280, height=720, text="Quality Standard Test")
    
    # 2. ファイル存在確認
    assert output_file.exists()
    
    # 3. Pillowによるロードと検証 (破損チェック)
    with Image.open(output_file) as img:
        img.verify()
    
    with Image.open(output_file) as img:
        img.load()  # 完全にピクセルデータをロードして破損チェック
        width, height = img.size
    
    # 4. 解像度、アスペクト比、ファイルサイズのアサーション
    assert width >= 1280
    assert height >= 720
    
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    assert abs(aspect_ratio - target_ratio) < 0.01
    
    size_bytes = output_file.stat().st_size
    assert size_bytes < 4 * 1024 * 1024  # 4MB未満
    
    # validate_thumbnail 関数の結果アサーション
    result_info = validate_thumbnail(output_file)
    assert result_info["width"] == width
    assert result_info["height"] == height
    assert result_info["size_bytes"] == size_bytes

    # 5. DBマイグレーション検証
    # カラムが無い初期テーブルを作成
    db_file = tmp_path / "migration_test.db"
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute("""
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                stage TEXT,
                status TEXT,
                error TEXT,
                created_at REAL,
                updated_at REAL
            )
        """)
        conn.commit()
    finally:
        conn.close()

    # StageBoundAgentを初期化（ここで _init_db が走り、足りないカラムが追加される）
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    # 追加カラムが存在することを確認
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("PRAGMA table_info(tasks)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "result" in columns
        assert "retry_count" in columns
        assert "max_retries" in columns
    finally:
        conn.close()

    # 6. StageBoundAgent 連携 (タスク登録、結果保存、リトライ)
    task_id = "test_quality_task"
    
    # 元の resolve_thumbnail_task を模ックまたはラッパーで動作検証
    # 1回目の実行でわざと失敗させてリトライさせるためのカウンタ
    call_count = 0
    
    async def process_with_retry_mock(tid: str):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Temporary failure for retry test")
        
        # 2回目は正常処理
        from combined_overlay import CombinedOverlay
        overlay = CombinedOverlay()
        overlay.output_dir = str(tmp_path)
        overlay.width = 1280
        overlay.height = 720
        overlay.text = "Retry Success"
        return await overlay.resolve_thumbnail_task(tid)

    # max_retries=1 で登録
    async def run_agent_test():
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        await agent.start(process_with_retry_mock)
        
        # 実行完了を待機
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        assert call_count == 2  # 1回失敗して、2回目に成功したこと

        # 結果が保存されていることを確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, result_str, retry_count = row
            assert status == "COMPLETED"
            assert retry_count == 1  # 1回リトライした
            
            result_data = json.loads(result_str)
            assert result_data["width"] == 1280
            assert result_data["height"] == 720
            assert "path" in result_data
        finally:
            conn.close()

    asyncio.run(run_agent_test())


def test_mark_timeout_fail_fallback_unexpected_exceptions(tmp_path):
    """
    PIL.Image.open などで予期せぬ例外（AttributeError, TypeError等）が投げられた場合の、
    validate_thumbnail_quality の ValueError への適切な変換、および generate_fallback_thumbnail の
    アトミックな一時ファイルのクリーンアップ動作を検証する。
    """
    from agents.orchestration.mark_timeout_fail import (
        validate_thumbnail_quality,
        generate_fallback_thumbnail
    )
    import pytest
    from PIL import Image

    # 1. validate_thumbnail_quality における AttributeError/TypeError キャッチ検証
    # Image.open をモックして予期せぬ例外をスローさせる
    low_res_path = tmp_path / "low_res_mock.png"
    # 空ファイルを作成
    low_res_path.touch()

    with patch("PIL.Image.open", side_effect=AttributeError("Mocked AttributeError for verify")):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_thumbnail_quality(str(low_res_path))

    with patch("PIL.Image.open", side_effect=TypeError("Mocked TypeError for load")):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_thumbnail_quality(str(low_res_path))

    # 2. verify() は正常終了するが、load() で例外が発生する場合の検証 (カバレッジ向上のため)
    mock_image = MagicMock()
    mock_image.verify.return_value = None
    mock_image.load.side_effect = OSError("Mocked OSError for load")
    mock_image.size = (1280, 720)
    with patch("PIL.Image.open", return_value=mock_image):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format \\(load\\)"):
            validate_thumbnail_quality(str(low_res_path))

    # 3. generate_fallback_thumbnail での例外発生時、一時ファイルが確実に削除されることの検証
    out_path = tmp_path / "fallback_except.png"

    with patch("PIL.Image.new", side_effect=RuntimeError("Mocked Image creation error")):
        with pytest.raises(RuntimeError, match="Failed to generate fallback thumbnail atomically"):
            generate_fallback_thumbnail(str(out_path))

    # 一時ファイルが存在していた状態で image.save が失敗した場合、unlink が呼ばれる検証
    # save をモックして、save 呼び出し時にダミーの一時ファイルを作成し、その後例外を投げる
    def mock_save(temp_p, format_type):
        Path(temp_p).touch()
        raise OSError("Mocked OSError for save")

    mock_img_obj = MagicMock()
    mock_img_obj.save.side_effect = mock_save
    with patch("PIL.Image.new", return_value=mock_img_obj):
        with pytest.raises(RuntimeError, match="Failed to generate fallback thumbnail atomically"):
            generate_fallback_thumbnail(str(out_path))

    # 一時ファイル (.*.tmp) が残っていないことを検証
    remaining_files = list(tmp_path.glob("*.tmp"))
    assert len(remaining_files) == 0, f"Temporary files were not cleaned up: {remaining_files}"

    # 4. generate_fallback_thumbnail に不正な引数や境界値が渡された場合の検証
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_fallback_thumbnail(str(out_path), width="invalid_width")

    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_fallback_thumbnail(str(out_path), width=-100)

    # 5. すでにファイルが存在する状態で generate_fallback_thumbnail を実行した場合の検証
    out_path.touch()
    assert out_path.exists()
    generate_fallback_thumbnail(str(out_path), width=1280, height=720, text="Overwrite Test")
    assert out_path.exists()


def test_resolve_timeout_fallback_task_failure(tmp_path):
    """
    resolve_timeout_fallback_task が generate_fallback_thumbnail や validate_thumbnail_quality の
    失敗時に、適切に例外を送出し、ログが記録され、かつ途中まで生成されたファイルが削除されることを検証する。
    """
    from agents.orchestration.mark_timeout_fail import resolve_timeout_fallback_task
    import logging
    import asyncio

    task_id = "test_fail_task_123"
    expected_output_path = _wp("backend/temp_thumbnails") / f"{task_id}_fallback.png"

    # 確実に削除されていることを確認するための初期状態
    if expected_output_path.exists():
        expected_output_path.unlink()

    # generate_fallback_thumbnail をモックして失敗させる
    with patch("agents.orchestration.mark_timeout_fail.generate_fallback_thumbnail", side_effect=RuntimeError("Thumbnail generation failed")):
        with pytest.raises(RuntimeError, match="Thumbnail generation failed"):
            asyncio.run(resolve_timeout_fallback_task(task_id))

    # 出力ファイルが存在しないことを確認
    assert not expected_output_path.exists()

    # 2. ファイルが一旦生成された後に validate_thumbnail_quality が失敗し、unlink される検証 (カバレッジ向上のため)
    expected_output_path.parent.mkdir(parents=True, exist_ok=True)
    expected_output_path.touch()
    
    with patch("agents.orchestration.mark_timeout_fail.validate_thumbnail_quality", side_effect=ValueError("Quality check failed")):
        with pytest.raises(ValueError, match="Quality check failed"):
            asyncio.run(resolve_timeout_fallback_task(task_id))
            
    # 例外時にファイルが unlink されていることの検証
    assert not expected_output_path.exists()

def test_thumbnail_validator_strict_quality_checks(tmp_path):
    """
    ThumbnailValidator の各検証機能（解像度、アスペクト比、ファイルサイズ、破損チェック）を
    境界値を含めて厳密に検証するユニットテスト
    """
    from branding.history_manager import ThumbnailValidator, ImageValidationError
    import pytest
    from PIL import Image
    import io
    
    # 有効な 1280x720 の画像を作成
    img = Image.new("RGB", (1280, 720), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    valid_bytes = buf.getvalue()
    
    # 1. 正常系テスト
    assert ThumbnailValidator.validate_image(valid_bytes) is True
    
    # 2. ファイルサイズ上限（4MB = 4,194,304 バイト）境界値テスト
    # 4MB以上のダミーバイトを作成（validate_image の最初のサイズチェックで引っかかるはず）
    large_bytes = b"x" * (4 * 1024 * 1024)
    with pytest.raises(ImageValidationError) as excinfo:
        ThumbnailValidator.validate_image(large_bytes)
    assert "exceeds limit" in str(excinfo.value)
    
    # 3. 解像度境界値テスト (1280x720 未満)
    # 幅不足 (1279x720)
    img_low_w = Image.new("RGB", (1279, 720), color="blue")
    buf_low_w = io.BytesIO()
    img_low_w.save(buf_low_w, format="PNG")
    with pytest.raises(ImageValidationError) as excinfo:
        ThumbnailValidator.validate_image(buf_low_w.getvalue())
    assert "is below minimum requirement" in str(excinfo.value)
    
    # 高さ不足 (1280x719)
    img_low_h = Image.new("RGB", (1280, 719), color="blue")
    buf_low_h = io.BytesIO()
    img_low_h.save(buf_low_h, format="PNG")
    with pytest.raises(ImageValidationError) as excinfo:
        ThumbnailValidator.validate_image(buf_low_h.getvalue())
    assert "is below minimum requirement" in str(excinfo.value)
    
    # 4. アスペクト比境界値テスト (16:9 = 1.777... から外れるケース)
    # 4:3 画像 (1280x960) -> 比率 1.333
    img_43 = Image.new("RGB", (1280, 960), color="blue")
    buf_43 = io.BytesIO()
    img_43.save(buf_43, format="PNG")
    with pytest.raises(ImageValidationError) as excinfo:
        ThumbnailValidator.validate_image(buf_43.getvalue())
    assert "does not match expected 16:9" in str(excinfo.value)
    
    # 5. 破損・不正画像バイナリテスト
    bad_bytes = b"this is not a valid image format at all"
    with pytest.raises(ImageValidationError) as excinfo:
        ThumbnailValidator.validate_image(bad_bytes)
    assert "unsupported image format" in str(excinfo.value) or "failed to parse" in str(excinfo.value) or "corrupted or invalid format" in str(excinfo.value)


def test_premium_thumbnail_generator_autoscale(tmp_path):
    """
    PremiumThumbnailGenerator が長文テキストでもはみ出さずに画像を自動生成し、
    その画像が品質要件を満たしていることを検証するテスト
    """
    from branding.history_manager import PremiumThumbnailGenerator, ThumbnailValidator
    from PIL import Image
    
    output_file = tmp_path / "long_text_premium.png"
    long_text = "This is a super long premium thumbnail title designed to trigger font size autoscaling and neon glassmorphism box resizing logic!"
    
    # 画像生成実行
    generated_path = PremiumThumbnailGenerator.generate(
        output_file,
        width=1280,
        height=720,
        text=long_text
    )
    
    # 1. ファイルの存在確認
    assert generated_path.exists()
    assert generated_path == output_file
    
    # 2. Pillowでのロードと検証 (破損チェック)
    with Image.open(output_file) as img:
        img.verify()
        
    with Image.open(output_file) as img:
        img.load()
        width, height = img.size
        
    # 3. 解像度、アスペクト比、ファイルサイズ要件の確認
    assert width >= 1280
    assert height >= 720
    
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    assert abs(aspect_ratio - target_ratio) < 0.05
    
    size_bytes = output_file.stat().st_size
    assert size_bytes < 4 * 1024 * 1024  # 4MB未満
    
    # validatorでの検証
    with open(output_file, "rb") as f:
        img_bytes = f.read()
    assert ThumbnailValidator.validate_image(img_bytes) is True


def test_verify_thumbnail_gen_strict_quality_checks(tmp_path):
    """
    verify_thumbnail_gen.py の verify_image_quality 関数の動作検証テスト。
    解像度、アスペクト比、ファイルサイズ制限、および破損チェックの境界値をテストする。
    """
    from PIL import Image
    import io
    import pytest
    from unittest.mock import patch
    import verify_thumbnail_gen

    # 1. 正常系: 有効な 1280x720 画像
    valid_path = tmp_path / "valid_test.png"
    img = Image.new("RGB", (1280, 720), color="blue")
    img.save(valid_path, format="PNG")
    
    result = verify_thumbnail_gen.verify_image_quality(str(valid_path))
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] > 0
    assert result["size_bytes"] < 4 * 1024 * 1024

    # 2. 異常系: 解像度不足 (1279x720)
    invalid_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (1279, 720), color="red")
    img.save(invalid_res_path, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_thumbnail_gen.verify_image_quality(str(invalid_res_path))

    # 3. 異常系: アスペクト比異常 (1280x960, 4:3)
    invalid_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="red")
    img.save(invalid_ratio_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_thumbnail_gen.verify_image_quality(str(invalid_ratio_path))

    # 4. 異常系: ファイルサイズ超過 (4MB制限)
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 4 * 1024 * 1024 + 10  # 4MB超
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            verify_thumbnail_gen.verify_image_quality(str(valid_path))

    # 5. 異常系: ファイルサイズ0 (空ファイル)
    empty_path = tmp_path / "empty.png"
    empty_path.touch()
    with pytest.raises(ValueError, match="File size is 0 bytes"):
        verify_thumbnail_gen.verify_image_quality(str(empty_path))

    # 6. 異常系: 破損ファイル (不正データ)
    corrupt_path = tmp_path / "corrupt.png"
    with open(corrupt_path, "wb") as f:
        f.write(b"invalid image data header")
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        verify_thumbnail_gen.verify_image_quality(str(corrupt_path))

    # 7. 新規追加: 引数バリデーション (None, 型エラー, 空文字)
    with pytest.raises(TypeError, match="file_path cannot be None"):
        verify_thumbnail_gen.verify_image_quality(None)
    with pytest.raises(TypeError, match="file_path must be a string"):
        verify_thumbnail_gen.verify_image_quality(123)
    with pytest.raises(ValueError, match="file_path cannot be empty"):
        verify_thumbnail_gen.verify_image_quality("   ")

    # 8. 新規追加: サポート外の画像フォーマット (GIF)
    gif_path = tmp_path / "test.gif"
    img_gif = Image.new("RGB", (1280, 720), color="blue")
    img_gif.save(gif_path, format="GIF")
    with pytest.raises(ValueError, match="Unsupported image format"):
        verify_thumbnail_gen.verify_image_quality(str(gif_path))

    # 9. 新規追加: サポート外のカラーモード (L - グレースケール)
    gray_path = tmp_path / "test_gray.png"
    img_gray = Image.new("L", (1280, 720), color=128)
    img_gray.save(gray_path, format="PNG")
    with pytest.raises(ValueError, match="Unsupported image mode"):
        verify_thumbnail_gen.verify_image_quality(str(gray_path))

    # 10. 新規追加: 例外ハンドリングの強化 (PIL内部での TypeError/AttributeError キャッチ)
    # verify() 時に TypeError が発生するケースのシミュレーション
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.verify.side_effect = TypeError("Simulated PIL error during verify")
        mock_open.return_value.__enter__.return_value = mock_img
        with pytest.raises(ValueError, match=r"Image is corrupted or invalid format \(verify failed\)"):
            verify_thumbnail_gen.verify_image_quality(str(valid_path))

    # load() 時に AttributeError が発生するケースのシミュレーション
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.verify.return_value = None
        mock_img.load.side_effect = AttributeError("Simulated PIL error during load")
        mock_open.return_value.__enter__.return_value = mock_img
        with pytest.raises(ValueError, match=r"Image is corrupted or invalid format \(load failed\)"):
            verify_thumbnail_gen.verify_image_quality(str(valid_path))


def test_verify_thumbnail_gen_additional_edge_cases(tmp_path):
    """
    verify_thumbnail_gen.py の verify_image_quality 関数および test_thumbnail_generation 関数に対する
    さらなるエッジケース（境界値、不正なカラーモード、巨大入力、デコード失敗など）の追加検証。
    """
    from PIL import Image
    import pytest
    from unittest.mock import patch, MagicMock
    import verify_thumbnail_gen

    # 1. 不正な画像カラーモード (CMYK, Palette)
    cmyk_path = tmp_path / "test_cmyk.png"
    img_cmyk = Image.new("CMYK", (1280, 720), color=(0, 0, 0, 0))
    img_cmyk.save(cmyk_path, format="JPEG")
    with pytest.raises(ValueError, match="Unsupported image mode"):
        verify_thumbnail_gen.verify_image_quality(str(cmyk_path))

    p_path = tmp_path / "test_p.png"
    img_p = Image.new("P", (1280, 720))
    img_p.save(p_path, format="PNG")
    with pytest.raises(ValueError, match="Unsupported image mode"):
        verify_thumbnail_gen.verify_image_quality(str(p_path))

    # 2. アスペクト比の境界値テスト
    # 誤差 0.01 の境界: 16/9 = 1.77777...
    # 幅1287, 高さ720: 比率 1.7875 (差分 0.0097) -> 許容される (正常終了)
    border_ok_high = tmp_path / "border_ok_high.png"
    img = Image.new("RGB", (1287, 720), color="blue")
    img.save(border_ok_high, format="PNG")
    result = verify_thumbnail_gen.verify_image_quality(str(border_ok_high))
    assert result["width"] == 1287
    assert result["height"] == 720

    # 幅1289, 高さ720: 比率 1.7903 (差分 0.0125) -> アスペクト比エラー
    border_ng_high = tmp_path / "border_ng_high.png"
    img = Image.new("RGB", (1289, 720), color="blue")
    img.save(border_ng_high, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_thumbnail_gen.verify_image_quality(str(border_ng_high))

    # 幅1280, ... 高さ724: 比率 1.7679 (差分 0.0098) -> 許容される (正常終了)
    border_ok_low = tmp_path / "border_ok_low.png"
    img = Image.new("RGB", (1280, 724), color="blue")
    img.save(border_ok_low, format="PNG")
    result = verify_thumbnail_gen.verify_image_quality(str(border_ok_low))
    assert result["width"] == 1280
    assert result["height"] == 724

    # 幅1280, 高さ725: 比率 1.7655 (差分 0.0122) -> アスペクト比エラー
    border_ng_low = tmp_path / "border_ng_low.png"
    img = Image.new("RGB", (1280, 725), color="blue")
    img.save(border_ng_low, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_thumbnail_gen.verify_image_quality(str(border_ng_low))

    # 3. 巨大な解像度 (10000 x 5625) -> アスペクト比 16:9。正常に検証パスするはず
    huge_path = tmp_path / "huge_resolution.png"
    img_huge = Image.new("RGB", (10000, 5625), color="black")
    img_huge.save(huge_path, format="PNG")
    result = verify_thumbnail_gen.verify_image_quality(str(huge_path))
    assert result["width"] == 10000
    assert result["height"] == 5625

    # 4. 不正なデータ型 (引数型)
    with pytest.raises(TypeError, match="file_path must be a string"):
        verify_thumbnail_gen.verify_image_quality([])
    with pytest.raises(TypeError, match="file_path must be a string"):
        verify_thumbnail_gen.verify_image_quality({})

    # 5. test_thumbnail_generation の Base64 デコードエラーエッジケース
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "count": 1,
        "thumbnails": [
            {
                "concept_name": "Concept A",
                "description": "Description A",
                "ctr_score": 5.5,
                "image_base64": "invalid_base64_string_&^%$#"
            }
        ]
    }
    with patch("requests.post", return_value=mock_response):
        with pytest.raises(ValueError, match="Failed to decode base64 image data"):
            verify_thumbnail_gen.test_thumbnail_generation()


def test_generate_fallback_thumbnail_unlink_oserror(tmp_path):
    """
    generate_fallback_thumbnail で例外が発生し、さらにクリーンアップの unlink() で
    OSError が発生した場合に、クリーンアップ時の例外が無視されることを検証する。
    """
    from agents.orchestration.mark_timeout_fail import generate_fallback_thumbnail
    from unittest.mock import patch, MagicMock
    import pytest
    from pathlib import Path

    out_path = tmp_path / "fallback_unlink_oserror.png"

    # save 時に一時ファイルを作成して OSError をスローさせる
    def mock_save(temp_p, format_type):
        Path(temp_p).touch()
        raise OSError("Mocked OSError for save")

    mock_img_obj = MagicMock()
    mock_img_obj.save.side_effect = mock_save

    with patch("PIL.Image.new", return_value=mock_img_obj):
        with patch("pathlib.Path.unlink", side_effect=OSError("Mocked unlink failure")):
            with pytest.raises(RuntimeError, match="Failed to generate fallback thumbnail atomically"):
                generate_fallback_thumbnail(str(out_path))


def test_resolve_timeout_fallback_task_unlink_oserror():
    """
    resolve_timeout_fallback_task で品質検証が失敗してクリーンアップを行う際、
    output_path.unlink() で OSError が発生しても、元の例外が正しく伝播し、
    クリーンアップの OSError 自体は無視されることを検証する。
    """
    from agents.orchestration.mark_timeout_fail import resolve_timeout_fallback_task
    from unittest.mock import patch
    import asyncio
    from pathlib import Path
    import pytest

    task_id = "test_task_unlink_oserror"
    expected_output_path = _wp("backend/temp_thumbnails") / f"{task_id}_fallback.png"

    # 初期状態でファイルが存在しないようにする
    if expected_output_path.exists():
        expected_output_path.unlink()

    original_unlink = Path.unlink

    def mock_unlink(self, *args, **kwargs):
        # ターゲットのファイルが expected_output_path のときだけ OSError を投げる
        if self.resolve() == expected_output_path.resolve():
            raise OSError("Mocked unlink failure for expected output path")
        return original_unlink(self, *args, **kwargs)

    with patch("pathlib.Path.unlink", new=mock_unlink):
        # validate_thumbnail_quality が失敗するようにモックする
        with patch("agents.orchestration.mark_timeout_fail.validate_thumbnail_quality", side_effect=ValueError("Quality check failed")):
            with pytest.raises(ValueError, match="Quality check failed"):
                asyncio.run(resolve_timeout_fallback_task(task_id))

    # テスト後にファイルが残っているはずなのでクリーンアップ
    if expected_output_path.exists():
        expected_output_path.unlink()


