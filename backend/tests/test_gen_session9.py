import json
import runpy
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import pytest
import sys

# sys.path に backend とプロジェクトルートを追加してインポートを解決する
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
project_root = backend_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# あらかじめインポートして再インポートによる numpy のエラーを防ぐ
from combined_overlay import CombinedOverlay
from agents.stage_bound_agent import StageBoundAgent

from backend.scripts.gen_session9 import (
    _meta,
    _item,
    _scene,
    gen_o10,
    gen_o11,
    gen_o12,
    gen_snapshot_v6,
)

def test_helper_functions():
    meta = _meta()
    assert isinstance(meta, dict)
    assert meta["$schema_version"] == "2.0"
    
    item = _item("test-id", 1, "S1", "desc", "method")
    assert item == {
        "id": "test-id",
        "layer": 1,
        "story_scene": "S1",
        "description": "desc",
        "test_method": "method"
    }
    
    scene = _scene("sid", "text", ["link1"])
    assert scene == {
        "id": "sid",
        "text": "text",
        "linked_items": ["link1"]
    }

def test_story_generators():
    o10 = gen_o10()
    assert o10["ux_id"] == "O-10"
    assert len(o10["scenes"]) == 20
    assert len(o10["verification_items"]) == 50

    o11 = gen_o11()
    assert o11["ux_id"] == "O-11"
    assert len(o11["scenes"]) == 20
    assert len(o11["verification_items"]) == 50

    o12 = gen_o12()
    assert o12["ux_id"] == "O-12"
    assert len(o12["scenes"]) == 22
    assert len(o12["verification_items"]) == 55

def test_gen_snapshot_v6(tmp_path):
    stories_dir = tmp_path / "stories"
    snaps_dir = tmp_path / "snapshots"
    stories_dir.mkdir()
    snaps_dir.mkdir()

    # ダミーのストーリーjsonを作成
    dummy_story = {
        "ux_id": "O-TEST",
        "verification_items": [
            {
                "id": "test-item-1",
                "layer": 1,
                "description": "dummy desc",
                "story_scene": "S1",
                "test_method": "dom_exists"
            }
        ]
    }
    (stories_dir / "o_test.json").write_text(json.dumps(dummy_story), encoding="utf-8")

    with patch("backend.scripts.gen_session9.STORIES", stories_dir), \
         patch("backend.scripts.gen_session9.SNAPS", snaps_dir):
        total = gen_snapshot_v6()
        assert total == 1
        
        # スナップショットファイルが生成されたか
        snap_file = snaps_dir / "v6.0.json"
        assert snap_file.exists()
        snap_data = json.loads(snap_file.read_text(encoding="utf-8"))
        assert snap_data["version"] == "v6.0"
        assert len(snap_data["items"]) == 1
        assert snap_data["items"][0]["id"] == "test-item-1"

def test_main_execution(tmp_path):
    stories_dir = tmp_path / "stories"
    snaps_dir = tmp_path / "snapshots"
    stories_dir.mkdir()
    snaps_dir.mkdir()

    original_write_text = Path.write_text
    original_glob = Path.glob

    def mock_write_text(self, *args, **kwargs):
        path_str = str(self)
        if "ux_verification/stories" in path_str.replace("\\", "/"):
            filename = self.name
            target = stories_dir / filename
            return original_write_text(target, *args, **kwargs)
        elif "ux_verification/snapshots" in path_str.replace("\\", "/"):
            filename = self.name
            target = snaps_dir / filename
            return original_write_text(target, *args, **kwargs)
        return original_write_text(self, *args, **kwargs)

    def mock_glob(self, pattern, *args, **kwargs):
        path_str = str(self)
        if "ux_verification/stories" in path_str.replace("\\", "/"):
            return original_glob(stories_dir, pattern, *args, **kwargs)
        return original_glob(self, pattern, *args, **kwargs)

    with patch.object(Path, "write_text", mock_write_text), \
         patch.object(Path, "glob", mock_glob):
        
        module_path = str(Path(__file__).parent.parent / "scripts" / "gen_session9.py")
        with patch("sys.argv", ["gen_session9.py"]):
            runpy.run_path(module_path, run_name="__main__")

    # 一時ディレクトリにファイルが書き出されたか検証
    assert (stories_dir / "o10_theme_selector.json").exists()
    assert (stories_dir / "o11_preproduction_lab.json").exists()
    assert (stories_dir / "o12_soul_evolution.json").exists()
    assert (snaps_dir / "v6.0.json").exists()

    # 非ASCII文字のエンコード保証（エスケープされていない生の日本語が含まれているか検証）
    for filename in ["o10_theme_selector.json", "o11_preproduction_lab.json", "o12_soul_evolution.json"]:
        content_json = (stories_dir / filename).read_text(encoding="utf-8")
        assert "\\u" not in content_json
        assert "テーマ選択" in content_json or "企画ラボ" in content_json or "学習・進化" in content_json

    snap_content = (snaps_dir / "v6.0.json").read_text(encoding="utf-8")
    assert "\\u" not in snap_content

def test_gen_snapshot_v6_empty_directory(tmp_path):
    stories_dir = tmp_path / "stories"
    snaps_dir = tmp_path / "snapshots"
    stories_dir.mkdir()
    snaps_dir.mkdir()

    with patch("backend.scripts.gen_session9.STORIES", stories_dir), \
         patch("backend.scripts.gen_session9.SNAPS", snaps_dir):
        total = gen_snapshot_v6()
        assert total == 0
        
        # スナップショットファイルが生成されたか
        snap_file = snaps_dir / "v6.0.json"
        assert snap_file.exists()
        snap_data = json.loads(snap_file.read_text(encoding="utf-8"))
        assert snap_data["version"] == "v6.0"
        assert snap_data["items"] == []

def test_story_structure_details():
    import re
    valid_methods = {"dom_exists", "visual_check", "interaction", "state_transition", "e2e"}
    
    for gen_func, prefix, expected_scenes in [
        (gen_o10, "O10", 20),
        (gen_o11, "O11", 20),
        (gen_o12, "O12", 22)
    ]:
        data = gen_func()
        # シーンIDのセットを作成
        scene_ids = {scene["id"] for scene in data["scenes"]}
        assert len(scene_ids) == expected_scenes
        
        # 各検証項目のチェック
        for item in data["verification_items"]:
            # IDのフォーマットチェック (例: O10-L1-01)
            assert re.match(rf"^{prefix}-L[1-5]-\d{{2}}$", item["id"])
            assert item["layer"] in {1, 2, 3, 4, 5}
            assert item["story_scene"] in scene_ids
            assert item["test_method"] in valid_methods
            assert isinstance(item["description"], str)
            assert len(item["description"]) > 0

@pytest.mark.asyncio
async def test_validate_session9_thumbnails_success():
    mock_conn = MagicMock()
    mock_sqlite3 = MagicMock()
    mock_sqlite3.connect = MagicMock(return_value=mock_conn)
    
    mock_agent_instance = MagicMock()
    mock_agent_instance.register_task = AsyncMock()
    mock_agent_instance.start = AsyncMock()
    mock_agent_instance.get_task_status = AsyncMock(side_effect=["READY", "COMPLETED", "COMPLETED"])
    mock_agent_instance.stop = AsyncMock()
    
    mock_overlay_instance = MagicMock()
    mock_overlay_instance.validate_thumbnail = MagicMock(return_value={"status": "ok"})
    
    backend_dir = Path(__file__).resolve().parent.parent
    
    with patch.dict("sys.modules", {"sqlite3": mock_sqlite3}), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent_instance), \
         patch("combined_overlay.CombinedOverlay", return_value=mock_overlay_instance), \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "unlink") as mock_unlink, \
         patch("sys.path", [p for p in sys.path if p != str(backend_dir)]):
         
        from backend.scripts.gen_session9 import validate_session9_thumbnails
        await validate_session9_thumbnails("dummy_db_path")
        
        mock_agent_instance.register_task.assert_called_once_with(
            task_id="session9_thumb_test", initial_status="READY", max_retries=2
        )
        mock_agent_instance.start.assert_called_once()
        mock_agent_instance.stop.assert_called_once()
        mock_overlay_instance.validate_thumbnail.assert_called_once()
        mock_unlink.assert_called_once()
        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

@pytest.mark.asyncio
async def test_validate_session9_thumbnails_unlink_error():
    mock_conn = MagicMock()
    mock_sqlite3 = MagicMock()
    mock_sqlite3.connect = MagicMock(return_value=mock_conn)
    
    mock_agent_instance = MagicMock()
    mock_agent_instance.register_task = AsyncMock()
    mock_agent_instance.start = AsyncMock()
    mock_agent_instance.get_task_status = AsyncMock(side_effect=["READY", "COMPLETED", "COMPLETED"])
    mock_agent_instance.stop = AsyncMock()
    
    mock_overlay_instance = MagicMock()
    mock_overlay_instance.validate_thumbnail = MagicMock(return_value={"status": "ok"})
    
    with patch.dict("sys.modules", {"sqlite3": mock_sqlite3}), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent_instance), \
         patch("combined_overlay.CombinedOverlay", return_value=mock_overlay_instance), \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "unlink", side_effect=OSError("Dummy unlink error")) as mock_unlink:
         
        from backend.scripts.gen_session9 import validate_session9_thumbnails
        await validate_session9_thumbnails("dummy_db_path")
        
        mock_unlink.assert_called_once()

@pytest.mark.asyncio
async def test_validate_session9_thumbnails_failure():
    mock_conn = MagicMock()
    mock_sqlite3 = MagicMock()
    mock_sqlite3.connect = MagicMock(return_value=mock_conn)
    
    mock_agent_instance = MagicMock()
    mock_agent_instance.register_task = AsyncMock()
    mock_agent_instance.start = AsyncMock()
    mock_agent_instance.get_task_status = AsyncMock(return_value="FAILED")
    mock_agent_instance.stop = AsyncMock()
    
    with patch.dict("sys.modules", {"sqlite3": mock_sqlite3}), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent_instance), \
         patch("combined_overlay.CombinedOverlay", return_value=MagicMock()):
         
        from backend.scripts.gen_session9 import validate_session9_thumbnails
        with pytest.raises(ValueError, match="Session9 thumbnail validation via StageBoundAgent failed."):
            await validate_session9_thumbnails("dummy_db_path")
            
        mock_agent_instance.stop.assert_called_once()

@pytest.mark.asyncio
async def test_validate_session9_thumbnails_db_delete_error():
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = Exception("Dummy SQLite Error")
    mock_sqlite3 = MagicMock()
    mock_sqlite3.connect = MagicMock(return_value=mock_conn)
    
    mock_agent_instance = MagicMock()
    mock_agent_instance.register_task = AsyncMock()
    mock_agent_instance.start = AsyncMock()
    mock_agent_instance.get_task_status = AsyncMock(side_effect=["READY", "COMPLETED", "COMPLETED"])
    mock_agent_instance.stop = AsyncMock()
    
    mock_overlay_instance = MagicMock()
    mock_overlay_instance.validate_thumbnail = MagicMock(return_value={"status": "ok"})
    
    with patch.dict("sys.modules", {"sqlite3": mock_sqlite3}), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent_instance), \
         patch("combined_overlay.CombinedOverlay", return_value=mock_overlay_instance), \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "unlink") as mock_unlink:
         
        from backend.scripts.gen_session9 import validate_session9_thumbnails
        await validate_session9_thumbnails("dummy_db_path")
        
        mock_agent_instance.register_task.assert_called_once()
        mock_agent_instance.start.assert_called_once()
        mock_agent_instance.stop.assert_called_once()
        mock_overlay_instance.validate_thumbnail.assert_called_once()
        mock_unlink.assert_called_once()
        mock_conn.execute.assert_called_once()
        mock_conn.close.assert_called_once()

def test_main_execution_with_validate():
    mock_conn = MagicMock()
    mock_sqlite3 = MagicMock()
    mock_sqlite3.connect = MagicMock(return_value=mock_conn)
    
    mock_agent_instance = MagicMock()
    mock_agent_instance.register_task = AsyncMock()
    mock_agent_instance.start = AsyncMock()
    mock_agent_instance.get_task_status = AsyncMock(side_effect=["READY", "COMPLETED", "COMPLETED"])
    mock_agent_instance.stop = AsyncMock()
    
    mock_overlay_instance = MagicMock()
    mock_overlay_instance.validate_thumbnail = MagicMock(return_value={"status": "ok"})
    
    with patch.dict("sys.modules", {"sqlite3": mock_sqlite3}), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent_instance), \
         patch("combined_overlay.CombinedOverlay", return_value=mock_overlay_instance), \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "unlink"), \
         patch("asyncio.run") as mock_run:
         
        import asyncio
        def run_coro(coro):
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        mock_run.side_effect = run_coro
         
        module_path = str(Path(__file__).parent.parent / "scripts" / "gen_session9.py")
        with patch("sys.argv", ["gen_session9.py", "--validate"]):
            runpy.run_path(module_path, run_name="__main__")
            
    mock_agent_instance.register_task.assert_called_once()
    mock_run.assert_called_once()

@pytest.mark.asyncio
async def test_validate_session9_thumbnails_validation_failure():
    """validate_thumbnailがエラー（例外または無効な戻り値）を返した場合に適切に処理されることを検証"""
    mock_conn = MagicMock()
    mock_sqlite3 = MagicMock()
    mock_sqlite3.connect = MagicMock(return_value=mock_conn)
    
    mock_agent_instance = MagicMock()
    mock_agent_instance.register_task = AsyncMock()
    mock_agent_instance.start = AsyncMock()
    mock_agent_instance.get_task_status = AsyncMock(return_value="COMPLETED")
    mock_agent_instance.stop = AsyncMock()
    
    mock_overlay_instance = MagicMock()
    # validate_thumbnail が例外を発生させるように設定
    mock_overlay_instance.validate_thumbnail.side_effect = ValueError("Invalid thumbnail image")
    
    with patch.dict("sys.modules", {"sqlite3": mock_sqlite3}), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent_instance), \
         patch("combined_overlay.CombinedOverlay", return_value=mock_overlay_instance), \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "unlink"):
         
        from backend.scripts.gen_session9 import validate_session9_thumbnails
        with pytest.raises(ValueError, match="Invalid thumbnail image"):
            await validate_session9_thumbnails("dummy_db_path")
            
        mock_overlay_instance.validate_thumbnail.assert_called_once()
        mock_agent_instance.stop.assert_called_once()

@pytest.mark.asyncio
async def test_sys_path_resolution():
    """validate_session9_thumbnailsの実行によりsys.pathにbackendディレクトリが追加されることを検証"""
    mock_conn = MagicMock()
    mock_sqlite3 = MagicMock()
    mock_sqlite3.connect = MagicMock(return_value=mock_conn)
    
    mock_agent_instance = MagicMock()
    mock_agent_instance.register_task = AsyncMock()
    mock_agent_instance.start = AsyncMock()
    mock_agent_instance.get_task_status = AsyncMock(return_value="COMPLETED")
    mock_agent_instance.stop = AsyncMock()
    
    mock_overlay_instance = MagicMock()
    mock_overlay_instance.validate_thumbnail = MagicMock(return_value={"status": "ok"})
    
    backend_dir = Path(__file__).resolve().parent.parent
    
    original_path = list(sys.path)
    if str(backend_dir) in sys.path:
        sys.path.remove(str(backend_dir))
        
    try:
        with patch.dict("sys.modules", {"sqlite3": mock_sqlite3}), \
             patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent_instance), \
             patch("combined_overlay.CombinedOverlay", return_value=mock_overlay_instance), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "unlink"):
             
            from backend.scripts.gen_session9 import validate_session9_thumbnails
            await validate_session9_thumbnails("dummy_db_path")
            
            assert str(backend_dir) in sys.path
    finally:
        sys.path = original_path
