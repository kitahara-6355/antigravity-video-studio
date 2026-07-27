import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
import json

# Add backend to path to allow importing routers
backend_path = Path(__file__).parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from routers.director import router, ChatRequest, BatchGenRequest, ReportRequest

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_chat_validation_limit():
    long_message = "a" * 2001
    response = client.post("/api/director/chat", json={"message": long_message})
    assert response.status_code == 400
    assert "Message exceeds maximum limit" in response.json()["detail"]


def test_batch_generate_validation_limit():
    scenes = [{"id": i} for i in range(21)]
    response = client.post("/api/director/batch-generate", json={"scenes": scenes, "style_prompt": "warm"})
    assert response.status_code == 400
    assert "Batch size exceeds maximum limit" in response.json()["detail"]


def test_image_generate_validation_limit():
    long_prompt = "a" * 1001
    response = client.post("/api/director/generate-image", json={"prompt": long_prompt})
    assert response.status_code == 400
    assert "Prompt exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.brain.route_to_agents")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_chat_exception_handling_and_tdr_registration(mock_register, mock_route):
    mock_route.side_effect = Exception("Test engine failure")
    
    response = client.post("/api/director/chat", json={"message": "hello"})
    assert response.status_code == 500
    assert "Director chat failed" in response.json()["detail"]
    
    mock_register.assert_called_once()
    args, kwargs = mock_register.call_args
    assert kwargs["category"] == "CRITICAL_ROUTER"
    assert kwargs["file_path"] == "routers/director.py"
    assert kwargs["line_number"] == 77
    assert "Test engine failure" in kwargs["notes"]


@patch("branding_manager.branding_manager.update_user_rank")
@patch("director_engine.brain.generate_production_report")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_generate_report_xp_error_handling(mock_register, mock_gen_report, mock_update_rank):
    mock_gen_report.return_value = json.dumps({"xp_grant": 100, "summary": "good job"})
    mock_update_rank.side_effect = Exception("XP file write error")
    
    response = client.post("/api/director/generate-report", json={
        "storyboard_plan": [],
        "quality_score": {},
        "biz_rank": "Novice"
    })
    
    assert response.status_code == 200
    assert response.json()["xp_grant"] == 100
    
    mock_register.assert_called_once()
    args, kwargs = mock_register.call_args
    assert kwargs["category"] == "CRITICAL_ROUTER"
    assert kwargs["line_number"] == 215
    assert "XP file write error" in kwargs["notes"]


@patch("director_engine.brain.generate_storyboard_plan")
def test_plan_storyboard_success(mock_plan):
    mock_plan.return_value = json.dumps([{"index": 0, "source_type": "AI"}])
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": "sample script",
        "scenes": [{"name": "Scene 1"}],
        "selected_style": {"name": "Style A"}
    })
    assert response.status_code == 200
    assert response.json()[0]["source_type"] == "AI"


@patch("director_engine.brain.calculate_quality_score")
def test_quality_score_success(mock_score):
    mock_score.return_value = json.dumps({"score": 90})
    response = client.post("/api/director/quality-score", json={
        "storyboard_plan": [],
        "biz_rank": "Novice"
    })
    assert response.status_code == 200
    assert response.json()["score"] == 90


@patch("director_engine.brain.generate_image")
def test_director_generate_image_success(mock_gen):
    mock_gen.return_value = {"image_url": "http://example.com/image.png"}
    response = client.post("/api/director/generate-image", json={"prompt": "beautiful sunset"})
    assert response.status_code == 200
    assert response.json()["image_url"] == "http://example.com/image.png"


@patch("director_engine.brain.generate_image")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_director_generate_image_exception(mock_register, mock_gen):
    mock_gen.side_effect = Exception("Imagen error")
    response = client.post("/api/director/generate-image", json={"prompt": "beautiful sunset"})
    assert response.status_code == 500
    assert "Image generation failed" in response.json()["detail"]
    mock_register.assert_called_once()


@patch("director_engine.task_manager.create_task")
@patch("director_engine.brain.process_image_task")
def test_director_generate_image_async_success(mock_process, mock_create):
    mock_create.return_value = "task_123"
    response = client.post("/api/director/generate-image-async", json={"prompt": "beautiful sunset"})
    assert response.status_code == 200
    assert response.json() == {"task_id": "task_123", "status": "processing"}


def test_director_generate_image_async_validation_limit():
    long_prompt = "a" * 1001
    response = client.post("/api/director/generate-image-async", json={"prompt": long_prompt})
    assert response.status_code == 400
    assert "Prompt exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.task_manager.create_task")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_director_generate_image_async_exception(mock_register, mock_create):
    mock_create.side_effect = Exception("Async creation error")
    response = client.post("/api/director/generate-image-async", json={"prompt": "beautiful sunset"})
    assert response.status_code == 500
    assert "Async image generation failed" in response.json()["detail"]
    mock_register.assert_called_once()


@patch("director_engine.task_manager.get_task")
def test_get_task_status_success(mock_get):
    mock_get.return_value = {"task_id": "task_123", "status": "done"}
    response = client.get("/api/director/task/task_123")
    assert response.status_code == 200
    assert response.json() == {"task_id": "task_123", "status": "done"}


@patch("director_engine.task_manager.get_task")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_get_task_status_exception(mock_register, mock_get):
    mock_get.side_effect = Exception("Get task status error")
    response = client.get("/api/director/task/task_123")
    assert response.status_code == 500
    assert "Get task status failed" in response.json()["detail"]
    mock_register.assert_called_once()


def test_analyze_script_validation_limit():
    long_text = "a" * 50001
    response = client.post("/api/director/analyze-script", json={"full_text": long_text})
    assert response.status_code == 400
    assert "Script text exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.brain.analyze_script")
def test_analyze_script_success_dict(mock_analyze):
    mock_analyze.return_value = {"themes": ["sci-fi"]}
    response = client.post("/api/director/analyze-script", json={"full_text": "short script"})
    assert response.status_code == 200
    assert response.json() == {"themes": ["sci-fi"]}


@patch("director_engine.brain.analyze_script")
def test_analyze_script_success_json_str(mock_analyze):
    mock_analyze.return_value = '{"themes": ["sci-fi"]}'
    response = client.post("/api/director/analyze-script", json={"full_text": "short script"})
    assert response.status_code == 200
    assert response.json() == {"themes": ["sci-fi"]}


@patch("director_engine.brain.analyze_script")
def test_analyze_script_success_invalid_json_str(mock_analyze):
    mock_analyze.return_value = "invalid json string"
    response = client.post("/api/director/analyze-script", json={"full_text": "short script"})
    assert response.status_code == 200
    assert response.json() == {"result": "invalid json string"}


@patch("director_engine.brain.analyze_script")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_analyze_script_exception(mock_register, mock_analyze):
    mock_analyze.side_effect = Exception("Script engine failure")
    response = client.post("/api/director/analyze-script", json={"full_text": "short script"})
    assert response.status_code == 500
    assert "Script analysis failed" in response.json()["detail"]
    mock_register.assert_called_once()


def test_quality_score_validation_limit():
    scenes = [{"id": i} for i in range(51)]
    response = client.post("/api/director/quality-score", json={"storyboard_plan": scenes})
    assert response.status_code == 400
    assert "Storyboard plan exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.brain.calculate_quality_score")
def test_quality_score_success_invalid_json_str(mock_score):
    mock_score.return_value = "invalid json string"
    response = client.post("/api/director/quality-score", json={"storyboard_plan": []})
    assert response.status_code == 200
    assert response.json() == {"result": "invalid json string"}


@patch("director_engine.brain.calculate_quality_score")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_quality_score_exception(mock_register, mock_score):
    mock_score.side_effect = Exception("Score engine failure")
    response = client.post("/api/director/quality-score", json={"storyboard_plan": []})
    assert response.status_code == 500
    assert "Quality scoring failed" in response.json()["detail"]
    mock_register.assert_called_once()


def test_analyze_resources_validation_limit():
    long_text = "a" * 50001
    response = client.post("/api/director/analyze-resources", json={"full_text": long_text})
    assert response.status_code == 400
    assert "Script text exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.brain.analyze_resource_needs")
def test_analyze_resources_success_dict(mock_analyze):
    mock_analyze.return_value = {"resources": ["video1"]}
    response = client.post("/api/director/analyze-resources", json={"full_text": "short script"})
    assert response.status_code == 200
    assert response.json() == {"resources": ["video1"]}


@patch("director_engine.brain.analyze_resource_needs")
def test_analyze_resources_success_json_str(mock_analyze):
    mock_analyze.return_value = '{"resources": ["video1"]}'
    response = client.post("/api/director/analyze-resources", json={"full_text": "short script"})
    assert response.status_code == 200
    assert response.json() == {"resources": ["video1"]}


@patch("director_engine.brain.analyze_resource_needs")
def test_analyze_resources_success_invalid_json_str(mock_analyze):
    mock_analyze.return_value = "invalid json string"
    response = client.post("/api/director/analyze-resources", json={"full_text": "short script"})
    assert response.status_code == 200
    assert response.json() == {"result": "invalid json string"}


@patch("director_engine.brain.analyze_resource_needs")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_analyze_resources_exception(mock_register, mock_analyze):
    mock_analyze.side_effect = Exception("Resource engine failure")
    response = client.post("/api/director/analyze-resources", json={"full_text": "short script"})
    assert response.status_code == 500
    assert "Resource analysis failed" in response.json()["detail"]
    mock_register.assert_called_once()


def test_generate_report_validation_limit():
    scenes = [{"id": i} for i in range(51)]
    response = client.post("/api/director/generate-report", json={
        "storyboard_plan": scenes,
        "quality_score": {}
    })
    assert response.status_code == 400
    assert "Storyboard plan exceeds maximum limit" in response.json()["detail"]


@patch("branding_manager.branding_manager.update_user_rank")
@patch("director_engine.brain.generate_production_report")
def test_generate_report_success_json_str_with_xp(mock_gen_report, mock_update_rank):
    mock_gen_report.return_value = '{"xp_grant": 100, "summary": "good job"}'
    response = client.post("/api/director/generate-report", json={
        "storyboard_plan": [],
        "quality_score": {},
        "biz_rank": "Novice"
    })
    assert response.status_code == 200
    assert response.json()["xp_grant"] == 100
    mock_update_rank.assert_called_once_with("tech_rank", amount=100)


@patch("director_engine.brain.generate_production_report")
def test_generate_report_success_invalid_json_str(mock_gen_report):
    mock_gen_report.return_value = "invalid json string"
    response = client.post("/api/director/generate-report", json={
        "storyboard_plan": [],
        "quality_score": {},
        "biz_rank": "Novice"
    })
    assert response.status_code == 200
    assert response.json() == {"summary": "invalid json string"}


@patch("director_engine.brain.generate_production_report")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_generate_report_exception(mock_register, mock_gen_report):
    mock_gen_report.side_effect = Exception("Report engine failure")
    response = client.post("/api/director/generate-report", json={
        "storyboard_plan": [],
        "quality_score": {},
        "biz_rank": "Novice"
    })
    assert response.status_code == 500
    assert "Report generation failed" in response.json()["detail"]
    mock_register.assert_called_once()


def test_plan_storyboard_validation_limit_text():
    long_text = "a" * 50001
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": long_text,
        "scenes": [],
        "selected_style": {}
    })
    assert response.status_code == 400
    assert "Script text exceeds maximum limit" in response.json()["detail"]


def test_plan_storyboard_validation_limit_scenes():
    scenes = [{"id": i} for i in range(51)]
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": "short script",
        "scenes": scenes,
        "selected_style": {}
    })
    assert response.status_code == 400
    assert "Scenes list exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.brain.generate_storyboard_plan")
def test_plan_storyboard_success_invalid_json_str(mock_plan):
    mock_plan.return_value = "invalid json string"
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": "short script",
        "scenes": [],
        "selected_style": {}
    })
    assert response.status_code == 200
    assert response.json() == {"result": "invalid json string"}


@patch("director_engine.brain.generate_storyboard_plan")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_plan_storyboard_exception(mock_register, mock_plan):
    mock_plan.side_effect = Exception("Storyboard engine failure")
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": "short script",
        "scenes": [],
        "selected_style": {}
    })
    assert response.status_code == 500
    assert "Storyboard planning failed" in response.json()["detail"]
    mock_register.assert_called_once()


def test_batch_generate_validation_limit_style():
    long_style = "a" * 1001
    response = client.post("/api/director/batch-generate", json={
        "scenes": [],
        "style_prompt": long_style
    })
    assert response.status_code == 400
    assert "Style prompt exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.task_manager.create_task")
@patch("director_engine.brain.process_batch_image_task")
def test_batch_generate_success(mock_process, mock_create):
    mock_create.return_value = "task_123"
    response = client.post("/api/director/batch-generate", json={
        "scenes": [],
        "style_prompt": "warm"
    })
    assert response.status_code == 200
    assert response.json() == {"task_id": "task_123", "status": "processing"}


@patch("director_engine.task_manager.create_task")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_batch_generate_exception(mock_register, mock_create):
    mock_create.side_effect = Exception("Batch creation error")
    response = client.post("/api/director/batch-generate", json={
        "scenes": [],
        "style_prompt": "warm"
    })
    assert response.status_code == 500
    assert "Batch generation failed" in response.json()["detail"]
    mock_register.assert_called_once()


@patch("logging.Logger.error")
@patch("agents.memory.technical_debt.TechnicalDebtStore.__init__")
def test_register_router_debt_exception_logged(mock_store_init, mock_log_error):
    mock_store_init.side_effect = Exception("Disk error")
    with patch("director_engine.brain.route_to_agents") as mock_route:
        mock_route.side_effect = Exception("Trigger exception")
        response = client.post("/api/director/chat", json={"message": "hello"})
    assert response.status_code == 500
    mock_log_error.assert_called_once()
    assert "Failed to register TDR debt: Disk error" in mock_log_error.call_args[0][0]


@patch("director_engine.brain.route_to_agents")
def test_chat_http_exception_passed_through(mock_route):
    mock_route.side_effect = HTTPException(status_code=403, detail="Forbidden action")
    response = client.post("/api/director/chat", json={"message": "hello"})
    assert response.status_code == 403
    assert "Forbidden action" in response.json()["detail"]


@patch("director_engine.brain.generate_image")
def test_generate_image_http_exception_passed_through(mock_gen):
    mock_gen.side_effect = HTTPException(status_code=403, detail="Forbidden action")
    response = client.post("/api/director/generate-image", json={"prompt": "hello"})
    assert response.status_code == 403


@patch("director_engine.task_manager.create_task")
def test_generate_image_async_http_exception_passed_through(mock_create):
    mock_create.side_effect = HTTPException(status_code=403, detail="Forbidden action")
    response = client.post("/api/director/generate-image-async", json={"prompt": "hello"})
    assert response.status_code == 403


@patch("director_engine.task_manager.get_task")
def test_get_task_status_http_exception_passed_through(mock_get):
    mock_get.side_effect = HTTPException(status_code=403, detail="Forbidden action")
    response = client.get("/api/director/task/task_123")
    assert response.status_code == 403


@patch("director_engine.brain.analyze_script")
def test_analyze_script_http_exception_passed_through(mock_analyze):
    mock_analyze.side_effect = HTTPException(status_code=403, detail="Forbidden action")
    response = client.post("/api/director/analyze-script", json={"full_text": "hello"})
    assert response.status_code == 403


@patch("director_engine.brain.calculate_quality_score")
def test_quality_score_http_exception_passed_through(mock_score):
    mock_score.side_effect = HTTPException(status_code=403, detail="Forbidden action")
    response = client.post("/api/director/quality-score", json={"storyboard_plan": []})
    assert response.status_code == 403


@patch("director_engine.brain.analyze_resource_needs")
def test_analyze_resources_http_exception_passed_through(mock_analyze):
    mock_analyze.side_effect = HTTPException(status_code=403, detail="Forbidden action")
    response = client.post("/api/director/analyze-resources", json={"full_text": "hello"})
    assert response.status_code == 403


@patch("director_engine.brain.generate_production_report")
def test_generate_report_http_exception_passed_through(mock_gen_report):
    mock_gen_report.side_effect = HTTPException(status_code=403, detail="Forbidden action")
    response = client.post("/api/director/generate-report", json={"storyboard_plan": [], "quality_score": {}})
    assert response.status_code == 403


@patch("branding_manager.branding_manager.update_user_rank")
@patch("director_engine.brain.generate_production_report")
def test_generate_report_branding_http_exception_passed_through(mock_gen_report, mock_update_rank):
    mock_gen_report.return_value = '{"xp_grant": 100, "summary": "good job"}'
    mock_update_rank.side_effect = HTTPException(status_code=403, detail="Forbidden rank update")
    response = client.post("/api/director/generate-report", json={"storyboard_plan": [], "quality_score": {}})
    assert response.status_code == 403
    assert "Forbidden rank update" in response.json()["detail"]


@patch("director_engine.brain.generate_storyboard_plan")
def test_plan_storyboard_http_exception_passed_through(mock_plan):
    mock_plan.side_effect = HTTPException(status_code=403, detail="Forbidden action")
    response = client.post("/api/director/plan-storyboard", json={"full_text": "hello", "scenes": [], "selected_style": {}})
    assert response.status_code == 403


@patch("director_engine.task_manager.create_task")
def test_batch_generate_http_exception_passed_through(mock_create):
    mock_create.side_effect = HTTPException(status_code=403, detail="Forbidden action")
    response = client.post("/api/director/batch-generate", json={"scenes": [], "style_prompt": "warm"})
    assert response.status_code == 403


@patch("director_engine.brain.calculate_quality_score")
def test_quality_score_success_dict(mock_score):
    mock_score.return_value = {"score": 90}
    response = client.post("/api/director/quality-score", json={
        "storyboard_plan": [],
        "biz_rank": "Novice"
    })
    assert response.status_code == 200
    assert response.json() == {"score": 90}


@patch("director_engine.brain.generate_production_report")
def test_generate_report_success_dict(mock_gen_report):
    mock_gen_report.return_value = {"xp_grant": 0, "summary": "good job"}
    response = client.post("/api/director/generate-report", json={
        "storyboard_plan": [],
        "quality_score": {},
        "biz_rank": "Novice"
    })
    assert response.status_code == 200
    assert response.json() == {"xp_grant": 0, "summary": "good job"}


@patch("director_engine.brain.generate_storyboard_plan")
def test_plan_storyboard_success_dict(mock_plan):
    mock_plan.return_value = [{"index": 0, "source_type": "AI"}]
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": "sample script",
        "scenes": [{"name": "Scene 1"}],
        "selected_style": {"name": "Style A"}
    })
    assert response.status_code == 200
    assert response.json()[0]["source_type"] == "AI"


