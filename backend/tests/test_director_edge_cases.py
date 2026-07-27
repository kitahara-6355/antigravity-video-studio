import sys
if 'routers' in sys.modules:
    print("DEBUG: 'routers' already in sys.modules:", sys.modules['routers'], flush=True)
    if hasattr(sys.modules['routers'], '__file__'):
        print("DEBUG: 'routers' file path:", sys.modules['routers'].__file__, flush=True)
else:
    print("DEBUG: 'routers' is NOT in sys.modules before import", flush=True)

import types
import pydantic

# 🛡️ Pydantic v2 / Python 3.13 tuple.index MRO 回避パッチ
import pydantic._internal._model_construction as mc
original_import = mc.import_cached_base_model

def patched_import():
    base_model = original_import()
    frame = sys._getframe()
    while frame:
        if frame.f_code.co_name == '__new__' and 'cls' in frame.f_locals:
            cls = frame.f_locals['cls']
            mro = cls.__mro__
            if base_model not in mro:
                for item in mro:
                    if item.__name__ in ('BaseModel', 'BaseSettings', 'BaseModel_', 'Settings'):
                        return item
                if len(mro) > 1:
                    return mro[-2] if mro[-2] is not object else mro[0]
            break
        frame = frame.f_back
    return base_model

mc.import_cached_base_model = patched_import

try:
    from pydantic import RootModel
except ImportError:
    class RootModel:
        pass

if 'pydantic.root_model' not in sys.modules:
    m = types.ModuleType('pydantic.root_model')
    m.RootModel = RootModel
    sys.modules['pydantic.root_model'] = m

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from pathlib import Path
import json
import logging

# Add backend to path to allow importing routers
backend_path = Path(__file__).parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from routers.director import (
    router,
    ChatRequest,
    ImageGenRequest,
    ScriptAnalysisRequest,
    BatchGenRequest,
    QualityScoreRequest,
    StoryboardPlanRequest,
    ReportRequest,
    _register_router_debt
)

app = FastAPI()
app.include_router(router)
client = TestClient(app)

# ==========================================
# 1. _register_router_debt 内部例外テスト
# ==========================================

def test_register_router_debt_internal_error():
    # TechnicalDebtStore のイニシャライザで例外を発生させることで、内部例外を検証
    with patch("agents.memory.technical_debt.TechnicalDebtStore", side_effect=RuntimeError("Simulated TDR Error")), \
         patch("logging.Logger.error") as mock_log:
        
        # 例外を起こしてログ出力をアサート
        _register_router_debt(10, "dummy_pattern", "dummy_error")
        mock_log.assert_called_once()
        log_msg = mock_log.call_args[0][0]
        assert "Failed to register TDR debt: Simulated TDR Error" in log_msg


# ==========================================
# 2. /chat エンドポイント
# ==========================================

@patch("director_engine.brain.route_to_agents")
def test_chat_http_exception_propagation(mock_route):
    # route_to_agents が HTTPException(400) を投げた場合の伝播
    mock_route.side_effect = HTTPException(status_code=400, detail="Custom HTTP error")
    
    response = client.post("/api/director/chat", json={"message": "hello"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Custom HTTP error"


@patch("director_engine.brain.route_to_agents")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_chat_generic_exception(mock_register, mock_route):
    # 一般の例外が500に変換され、TDR登録されるか
    mock_route.side_effect = RuntimeError("Brain crashed")
    
    response = client.post("/api/director/chat", json={"message": "hello"})
    assert response.status_code == 500
    assert "Director chat failed: Brain crashed" in response.json()["detail"]
    mock_register.assert_called_once()
    kwargs = mock_register.call_args[1]
    assert kwargs["line_number"] == 77


# ==========================================
# 3. /generate-image エンドポイント
# ==========================================

@patch("director_engine.brain.generate_image")
def test_generate_image_success(mock_gen):
    mock_gen.return_value = {"image_url": "http://example.com/image.png"}
    response = client.post("/api/director/generate-image", json={"prompt": "beautiful sky"})
    assert response.status_code == 200
    assert response.json()["image_url"] == "http://example.com/image.png"


@patch("director_engine.brain.generate_image")
def test_generate_image_http_exception(mock_gen):
    mock_gen.side_effect = HTTPException(status_code=403, detail="Forbidden image prompt")
    response = client.post("/api/director/generate-image", json={"prompt": "forbidden"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden image prompt"


@patch("director_engine.brain.generate_image")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_generate_image_generic_exception(mock_register, mock_gen):
    mock_gen.side_effect = RuntimeError("Imagen 3 service down")
    response = client.post("/api/director/generate-image", json={"prompt": "sky"})
    assert response.status_code == 500
    assert "Image generation failed: Imagen 3 service down" in response.json()["detail"]
    mock_register.assert_called_once()
    kwargs = mock_register.call_args[1]
    assert kwargs["line_number"] == 93


# ==========================================
# 4. /generate-image-async エンドポイント
# ==========================================

@patch("director_engine.task_manager.create_task")
@patch("director_engine.brain.process_image_task")
def test_generate_image_async_success(mock_process, mock_create):
    mock_create.return_value = "task_123"
    response = client.post("/api/director/generate-image-async", json={"prompt": "dream garden"})
    assert response.status_code == 200
    assert response.json() == {"task_id": "task_123", "status": "processing"}
    mock_process.assert_called_once()


def test_generate_image_async_limit():
    # 1001 文字で制限超過
    response = client.post("/api/director/generate-image-async", json={"prompt": "a" * 1001})
    assert response.status_code == 400
    assert "Prompt exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.task_manager.create_task")
def test_generate_image_async_http_exception(mock_create):
    mock_create.side_effect = HTTPException(status_code=400, detail="Invalid status")
    response = client.post("/api/director/generate-image-async", json={"prompt": "dream garden"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid status"


@patch("director_engine.task_manager.create_task")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_generate_image_async_generic_exception(mock_register, mock_create):
    mock_create.side_effect = RuntimeError("Task manager down")
    response = client.post("/api/director/generate-image-async", json={"prompt": "dream garden"})
    assert response.status_code == 500
    assert "Async image generation failed: Task manager down" in response.json()["detail"]
    mock_register.assert_called_once()
    kwargs = mock_register.call_args[1]
    assert kwargs["line_number"] == 110


# ==========================================
# 5. /task/{task_id} エンドポイント
# ==========================================

@patch("director_engine.task_manager.get_task")
def test_get_task_status_success(mock_get):
    mock_get.return_value = {"task_id": "task_123", "status": "completed", "result": "done"}
    response = client.get("/api/director/task/task_123")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


@patch("director_engine.task_manager.get_task")
def test_get_task_status_http_exception(mock_get):
    mock_get.side_effect = HTTPException(status_code=404, detail="Task not found")
    response = client.get("/api/director/task/task_404")
    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


@patch("director_engine.task_manager.get_task")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_get_task_status_generic_exception(mock_register, mock_get):
    mock_get.side_effect = RuntimeError("Database error")
    response = client.get("/api/director/task/task_123")
    assert response.status_code == 500
    assert "Get task status failed: Database error" in response.json()["detail"]
    mock_register.assert_called_once()
    kwargs = mock_register.call_args[1]
    assert kwargs["line_number"] == 123


# ==========================================
# 6. /analyze-script エンドポイント
# ==========================================

def test_analyze_script_limit():
    response = client.post("/api/director/analyze-script", json={"full_text": "a" * 50001})
    assert response.status_code == 400
    assert "Script text exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.brain.analyze_script")
def test_analyze_script_decode_branch(mock_analyze):
    # 戻り値が非文字列（dict）の場合
    mock_analyze.return_value = {"themes": ["Warm"]}
    response = client.post("/api/director/analyze-script", json={"full_text": "script"})
    assert response.status_code == 200
    assert response.json() == {"themes": ["Warm"]}

    # 戻り値がJSON形式の文字列の場合
    mock_analyze.return_value = '{"themes": ["Cool"]}'
    response = client.post("/api/director/analyze-script", json={"full_text": "script"})
    assert response.status_code == 200
    assert response.json() == {"themes": ["Cool"]}

    # 戻り値がJSONではない文字列の場合 (JSONDecodeError 分岐)
    mock_analyze.return_value = 'plain text description'
    response = client.post("/api/director/analyze-script", json={"full_text": "script"})
    assert response.status_code == 200
    assert response.json() == {"result": "plain text description"}


@patch("director_engine.brain.analyze_script")
def test_analyze_script_http_exception(mock_analyze):
    mock_analyze.side_effect = HTTPException(status_code=400, detail="Invalid script syntax")
    response = client.post("/api/director/analyze-script", json={"full_text": "script"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid script syntax"


@patch("director_engine.brain.analyze_script")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_analyze_script_generic_exception(mock_register, mock_analyze):
    mock_analyze.side_effect = RuntimeError("Parser error")
    response = client.post("/api/director/analyze-script", json={"full_text": "script"})
    assert response.status_code == 500
    assert "Script analysis failed: Parser error" in response.json()["detail"]
    mock_register.assert_called_once()
    kwargs = mock_register.call_args[1]
    assert kwargs["line_number"] == 144


# ==========================================
# 7. /quality-score エンドポイント
# ==========================================

def test_quality_score_limit():
    # 51シーンで制限超過
    plan = [{"scene_id": i} for i in range(51)]
    response = client.post("/api/director/quality-score", json={"storyboard_plan": plan, "biz_rank": "Novice"})
    assert response.status_code == 400
    assert "Storyboard plan exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.brain.calculate_quality_score")
def test_quality_score_decode_branch(mock_score):
    # 戻り値が非文字列（dict）
    mock_score.return_value = {"score": 85}
    response = client.post("/api/director/quality-score", json={"storyboard_plan": []})
    assert response.status_code == 200
    assert response.json() == {"score": 85}

    # 戻り値がJSON文字列
    mock_score.return_value = '{"score": 95}'
    response = client.post("/api/director/quality-score", json={"storyboard_plan": []})
    assert response.status_code == 200
    assert response.json() == {"score": 95}

    # 戻り値がJSONでない文字列 (JSONDecodeError 分岐)
    mock_score.return_value = "invalid json text"
    response = client.post("/api/director/quality-score", json={"storyboard_plan": []})
    assert response.status_code == 200
    assert response.json() == {"result": "invalid json text"}


@patch("director_engine.brain.calculate_quality_score")
def test_quality_score_http_exception(mock_score):
    mock_score.side_effect = HTTPException(status_code=400, detail="Invalid plan structure")
    response = client.post("/api/director/quality-score", json={"storyboard_plan": []})
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid plan structure"


@patch("director_engine.brain.calculate_quality_score")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_quality_score_generic_exception(mock_register, mock_score):
    mock_score.side_effect = RuntimeError("Score computation failed")
    response = client.post("/api/director/quality-score", json={"storyboard_plan": []})
    assert response.status_code == 500
    assert "Quality scoring failed: Score computation failed" in response.json()["detail"]
    mock_register.assert_called_once()
    kwargs = mock_register.call_args[1]
    assert kwargs["line_number"] == 165


# ==========================================
# 8. /analyze-resources エンドポイント
# ==========================================

def test_analyze_resources_limit():
    response = client.post("/api/director/analyze-resources", json={"full_text": "a" * 50001})
    assert response.status_code == 400
    assert "Script text exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.brain.analyze_resource_needs")
def test_analyze_resources_decode_branch(mock_analyze):
    # 非文字列
    mock_analyze.return_value = {"audio": ["bgm.mp3"]}
    response = client.post("/api/director/analyze-resources", json={"full_text": "script"})
    assert response.status_code == 200
    assert response.json() == {"audio": ["bgm.mp3"]}

    # JSON文字列
    mock_analyze.return_value = '{"audio": ["bgm.mp3"]}'
    response = client.post("/api/director/analyze-resources", json={"full_text": "script"})
    assert response.status_code == 200
    assert response.json() == {"audio": ["bgm.mp3"]}

    # JSONではない文字列
    mock_analyze.return_value = "raw resources details"
    response = client.post("/api/director/analyze-resources", json={"full_text": "script"})
    assert response.status_code == 200
    assert response.json() == {"result": "raw resources details"}


@patch("director_engine.brain.analyze_resource_needs")
def test_analyze_resources_http_exception(mock_analyze):
    mock_analyze.side_effect = HTTPException(status_code=400, detail="Missing analyzer metadata")
    response = client.post("/api/director/analyze-resources", json={"full_text": "script"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Missing analyzer metadata"


@patch("director_engine.brain.analyze_resource_needs")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_analyze_resources_generic_exception(mock_register, mock_analyze):
    mock_analyze.side_effect = RuntimeError("Resource scanner crashed")
    response = client.post("/api/director/analyze-resources", json={"full_text": "script"})
    assert response.status_code == 500
    assert "Resource analysis failed: Resource scanner crashed" in response.json()["detail"]
    mock_register.assert_called_once()
    kwargs = mock_register.call_args[1]
    assert kwargs["line_number"] == 186


# ==========================================
# 9. /generate-report エンドポイント
# ==========================================

def test_generate_report_limit():
    plan = [{"scene_id": i} for i in range(51)]
    response = client.post("/api/director/generate-report", json={
        "storyboard_plan": plan,
        "quality_score": {},
        "biz_rank": "Novice"
    })
    assert response.status_code == 400
    assert "Storyboard plan exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.brain.generate_production_report")
@patch("branding_manager.branding_manager.update_user_rank")
def test_generate_report_decode_branch(mock_update, mock_gen):
    # 非文字列・XPなし
    mock_gen.return_value = {"summary": "no xp report"}
    response = client.post("/api/director/generate-report", json={"storyboard_plan": [], "quality_score": {}})
    assert response.status_code == 200
    assert response.json() == {"summary": "no xp report"}
    mock_update.assert_not_called()

    # JSON文字列・xp_earnedあり
    mock_gen.return_value = '{"xp_earned": 50, "summary": "good report"}'
    response = client.post("/api/director/generate-report", json={"storyboard_plan": [], "quality_score": {}})
    assert response.status_code == 200
    assert response.json()["summary"] == "good report"
    mock_update.assert_called_once_with("tech_rank", amount=50)
    mock_update.reset_mock()

    # JSONでない文字列・xpなしフォールバック
    mock_gen.return_value = "raw summary text"
    response = client.post("/api/director/generate-report", json={"storyboard_plan": [], "quality_score": {}})
    assert response.status_code == 200
    assert response.json() == {"summary": "raw summary text"}
    mock_update.assert_not_called()


@patch("director_engine.brain.generate_production_report")
@patch("branding_manager.branding_manager.update_user_rank")
def test_generate_report_xp_http_exception(mock_update, mock_gen):
    # update_user_rank で HTTPException(400) が発生した際の伝播
    mock_gen.return_value = {"xp_grant": 10, "summary": "xp report"}
    mock_update.side_effect = HTTPException(status_code=400, detail="Rank update failed")
    
    response = client.post("/api/director/generate-report", json={"storyboard_plan": [], "quality_score": {}})
    assert response.status_code == 400
    assert response.json()["detail"] == "Rank update failed"


@patch("director_engine.brain.generate_production_report")
def test_generate_report_http_exception(mock_gen):
    mock_gen.side_effect = HTTPException(status_code=400, detail="Invalid inputs")
    response = client.post("/api/director/generate-report", json={"storyboard_plan": [], "quality_score": {}})
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid inputs"


@patch("director_engine.brain.generate_production_report")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_generate_report_generic_exception(mock_register, mock_gen):
    mock_gen.side_effect = RuntimeError("Report compiler error")
    response = client.post("/api/director/generate-report", json={"storyboard_plan": [], "quality_score": {}})
    assert response.status_code == 500
    assert "Report generation failed: Report compiler error" in response.json()["detail"]
    mock_register.assert_called_once()
    kwargs = mock_register.call_args[1]
    assert kwargs["line_number"] == 223


# ==========================================
# 10. /plan-storyboard エンドポイント
# ==========================================

def test_plan_storyboard_limit():
    # text文字数超過
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": "a" * 50001,
        "scenes": [],
        "selected_style": {}
    })
    assert response.status_code == 400
    assert "Script text exceeds maximum limit" in response.json()["detail"]

    # scenes数超過
    scenes = [{"id": i} for i in range(51)]
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": "script",
        "scenes": scenes,
        "selected_style": {}
    })
    assert response.status_code == 400
    assert "Scenes list exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.brain.generate_storyboard_plan")
def test_plan_storyboard_decode_branch(mock_plan):
    # 非文字列
    mock_plan.return_value = {"scenes": []}
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": "script",
        "scenes": [],
        "selected_style": {}
    })
    assert response.status_code == 200
    assert response.json() == {"scenes": []}

    # JSON文字列
    mock_plan.return_value = '{"scenes": [{"id": 1}]}'
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": "script",
        "scenes": [],
        "selected_style": {}
    })
    assert response.status_code == 200
    assert response.json() == {"scenes": [{"id": 1}]}

    # JSONでない文字列
    mock_plan.return_value = "invalid json return"
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": "script",
        "scenes": [],
        "selected_style": {}
    })
    assert response.status_code == 200
    assert response.json() == {"result": "invalid json return"}


@patch("director_engine.brain.generate_storyboard_plan")
def test_plan_storyboard_http_exception(mock_plan):
    mock_plan.side_effect = HTTPException(status_code=400, detail="Invalid design settings")
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": "script",
        "scenes": [],
        "selected_style": {}
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid design settings"


@patch("director_engine.brain.generate_storyboard_plan")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_plan_storyboard_generic_exception(mock_register, mock_plan):
    mock_plan.side_effect = RuntimeError("Storyboard engine crashed")
    response = client.post("/api/director/plan-storyboard", json={
        "full_text": "script",
        "scenes": [],
        "selected_style": {}
    })
    assert response.status_code == 500
    assert "Storyboard planning failed: Storyboard engine crashed" in response.json()["detail"]
    mock_register.assert_called_once()
    kwargs = mock_register.call_args[1]
    assert kwargs["line_number"] == 246


# ==========================================
# 11. /batch-generate エンドポイント
# ==========================================

@patch("director_engine.task_manager.create_task")
@patch("director_engine.brain.process_batch_image_task")
def test_batch_generate_success(mock_process, mock_create):
    mock_create.return_value = "task_999"
    response = client.post("/api/director/batch-generate", json={
        "scenes": [{"name": "Scene A"}],
        "style_prompt": "cinematic"
    })
    assert response.status_code == 200
    assert response.json() == {"task_id": "task_999", "status": "processing"}
    mock_process.assert_called_once()


def test_batch_generate_limit():
    # style_prompt文字数制限
    response = client.post("/api/director/batch-generate", json={
        "scenes": [],
        "style_prompt": "a" * 1001
    })
    assert response.status_code == 400
    assert "Style prompt exceeds maximum limit" in response.json()["detail"]


@patch("director_engine.task_manager.create_task")
def test_batch_generate_http_exception(mock_create):
    mock_create.side_effect = HTTPException(status_code=400, detail="Tasks full")
    response = client.post("/api/director/batch-generate", json={
        "scenes": [],
        "style_prompt": "cool"
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "Tasks full"


@patch("director_engine.task_manager.create_task")
@patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
def test_batch_generate_generic_exception(mock_register, mock_create):
    mock_create.side_effect = RuntimeError("Manager offline")
    response = client.post("/api/director/batch-generate", json={
        "scenes": [],
        "style_prompt": "cool"
    })
    assert response.status_code == 500
    assert "Batch generation failed: Manager offline" in response.json()["detail"]
    mock_register.assert_called_once()
    kwargs = mock_register.call_args[1]
    assert kwargs["line_number"] == 265
