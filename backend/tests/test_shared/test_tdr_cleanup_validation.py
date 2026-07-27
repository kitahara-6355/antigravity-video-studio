import json
import pytest
from unittest.mock import patch, MagicMock, mock_open
from fastapi import HTTPException

# Target imports
from agents.director import Director
from routers.dashboard_router import start_processing, ProcessStartRequest
from routers.legacy_production_router import rhythm_split, RhythmRequest, capture_step_snapshot, StepSnapshotRequest
from routers.pipeline_report import _probe_video
from decision_logger import DecisionLogger
from model_registry import ModelRegistry
from plugins.smart_cut_plugin import SmartCutPlugin

# 1. agents/director.py HTTPException propagation test
def test_director_http_exception_propagation():
    director = Director()
    if director.client is None:
        director.client = MagicMock()
    with patch('agents.director.HAS_ADK', False):
        with patch.object(director.client.models, 'generate_content', side_effect=HTTPException(status_code=400, detail="Test")):
            with pytest.raises(HTTPException):
                director.process({"text": "test"}, {})

# 2. routers/dashboard_router.py HTTPException propagation test
@pytest.mark.anyio
async def test_dashboard_router_http_exception_propagation():
    bg_tasks = MagicMock()
    req = ProcessStartRequest(video_path="test.mp4")
    with patch.object(bg_tasks, 'add_task', side_effect=HTTPException(status_code=400, detail="Test")):
        with pytest.raises(HTTPException):
            await start_processing(bg_tasks, req)

# 3. routers/legacy_production_router.py HTTPException propagation test
@pytest.mark.anyio
async def test_legacy_production_router_http_exception_propagation():
    # rhythm_split
    req = RhythmRequest(text="test")
    with patch('ai_rhythm.semantic_split', side_effect=HTTPException(status_code=400, detail="Test")):
        with pytest.raises(HTTPException):
            await rhythm_split(req)
            
    # capture_step_snapshot
    step_req = StepSnapshotRequest(session_id="test", step_name="test", before_video="b.mp4", after_video="a.mp4")
    with patch('progressive_preview.ProgressivePreview.snapshot_step', side_effect=HTTPException(status_code=400, detail="Test")):
        with pytest.raises(HTTPException):
            await capture_step_snapshot(step_req)

# 4. routers/pipeline_report.py HTTPException propagation test
def test_pipeline_report_http_exception_propagation():
    with patch('subprocess.run', side_effect=HTTPException(status_code=400, detail="Test")):
        with pytest.raises(HTTPException):
            _probe_video("test.mp4")

# decision_logger.py Exception specialization test
def test_decision_logger_exceptions():
    logger = DecisionLogger()
    # json.JSONDecodeError
    with patch("builtins.open", mock_open(read_data="invalid json")):
        with patch("pathlib.Path.exists", return_value=True):
            logger._load()  # Should handle JSONDecodeError and not raise it
            assert logger.decisions == []
            
    # FileNotFoundError
    with patch("builtins.open", side_effect=FileNotFoundError()):
        with patch("pathlib.Path.exists", return_value=True):
            logger._load()  # Should handle and not raise
            
    # PermissionError on read
    with patch("builtins.open", side_effect=PermissionError()):
        with patch("pathlib.Path.exists", return_value=True):
            logger._load()  # Should handle
            
    # PermissionError on write
    with patch("builtins.open", side_effect=PermissionError()):
        logger._save()  # Should handle

    # TypeError on write
    with patch("json.dump", side_effect=TypeError()):
        with patch("builtins.open", mock_open()):
            logger._save()  # Should handle

# model_registry.py Exception specialization test
def test_model_registry_exceptions():
    registry = ModelRegistry()
    import google.api_core.exceptions
    # GoogleAPIError
    with patch('gemini_client_factory.get_gemini_client') as mock_factory:
        mock_client = MagicMock()
        mock_factory.return_value = mock_client
        mock_client.models.list.side_effect = google.api_core.exceptions.GoogleAPIError("Test API Error")
        res = registry.check_model_availability(force_refresh=True)
        assert res == {}
        
    # ImportError
    with patch('gemini_client_factory.get_gemini_client', side_effect=ImportError("Mock Import Error")):
        res = registry.check_model_availability(force_refresh=True)
        assert res == {}

# smart_cut_plugin.py Exception specialization test
def test_smart_cut_plugin_exceptions():
    plugin = SmartCutPlugin()
    
    # FileNotFoundError on load_constraints
    with patch("builtins.open", side_effect=FileNotFoundError()):
        plugin._load_constraints()
        assert plugin.max_highlight_candidates == 50
        
    # JSONDecodeError on load_constraints
    with patch("builtins.open", mock_open(read_data="invalid json")):
        plugin._load_constraints()
        assert plugin.max_highlight_candidates == 50
        
    # PermissionError on load_constraints
    with patch("builtins.open", side_effect=PermissionError()):
        plugin._load_constraints()
        assert plugin.max_highlight_candidates == 50

    # JSONDecodeError on save_to_evolution_log
    with patch("builtins.open", mock_open(read_data="invalid json")):
        with patch("pathlib.Path.exists", return_value=True):
            plugin._save_to_evolution_log({"test": "test"})
            
    # PermissionError on save_to_evolution_log
    with patch("builtins.open", side_effect=PermissionError()):
        plugin._save_to_evolution_log({"test": "test"})
