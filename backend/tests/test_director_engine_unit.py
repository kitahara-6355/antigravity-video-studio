import pytest
from unittest.mock import MagicMock, patch
import json
import base64
import time
import sys
import importlib
from pathlib import Path

# Add backend directory to sys.path
backend_path = Path(__file__).parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from director_engine import DirectorBrain
import director_engine

# -------------------------------------------------------------
# Module Import Fallback Test
# -------------------------------------------------------------
def test_import_error_fallback():
    # Force ImportError for model_registry on reload
    with patch.dict(sys.modules, {"model_registry": None}):
        importlib.reload(director_engine)
        # **直書きの既定値に逃げない**（R1.5-C6）。2026-08-28 まで
        # gemini-2.5-flash を直書きしており、2026-10-16 に提供終了する
        # **この経路が返すのは工程別のモデルではなく既定モデル**
        from model_policy import default_model
        assert director_engine.get_model("director") == default_model()
        assert not director_engine.get_model("director").startswith("gemini-2.5")
    
    # Restore original state
    importlib.reload(director_engine)


# -------------------------------------------------------------
# TaskManager Tests
# -------------------------------------------------------------
def test_task_manager_lifecycle():
    tm = director_engine.TaskManager()
    task_id = tm.create_task()
    
    # Check creation
    task = tm.get_task(task_id)
    assert task is not None
    assert task["status"] == "pending"
    assert task["result"] is None
    assert task["error"] is None
    
    # Update to processing
    tm.update_task(task_id, "processing")
    task = tm.get_task(task_id)
    assert task["status"] == "processing"
    
    # Update to completed with result
    tm.update_task(task_id, "completed", result="success_data")
    task = tm.get_task(task_id)
    assert task["status"] == "completed"
    assert task["result"] == "success_data"
    
    # Update to failed with error
    tm.update_task(task_id, "failed", error="some_error")
    task = tm.get_task(task_id)
    assert task["status"] == "failed"
    assert task["error"] == "some_error"
    
    # Non-existent task update should not crash
    tm.update_task("non-existent-id", "processing")
    assert tm.get_task("non-existent-id") is None


# -------------------------------------------------------------
# DirectorBrain Mock Fixtures
# -------------------------------------------------------------
@pytest.fixture
def mock_gemini():
    with patch("director_engine.get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        # models.generate_content mock response
        mock_response = MagicMock()
        mock_response.text = '{"intent": "test intent", "agents": ["Strategist", "Director"], "confidence": 0.9, "rationale": "test rationale"}'
        mock_client.models.generate_content.return_value = mock_response
        
        # models.generate_images mock response
        mock_image_response = MagicMock()
        mock_gen_img_1 = MagicMock()
        mock_gen_img_1.image.image_bytes = b"img_bytes_1"
        mock_gen_img_2 = MagicMock()
        mock_gen_img_2.image.image_bytes = b"img_bytes_2"
        mock_image_response.generated_images = [mock_gen_img_1, mock_gen_img_2]
        mock_client.models.generate_images.return_value = mock_image_response
        
        # chats.create mock response
        mock_chat = MagicMock()
        mock_chat_response = MagicMock()
        mock_chat_response.text = "Chat Response Text"
        mock_chat.send_message.return_value = mock_chat_response
        mock_client.chats.create.return_value = mock_chat
        
        yield mock_client


@pytest.fixture
def mock_branding():
    with patch("director_engine.branding_manager") as mock_bm:
        # Mock constitution
        mock_bm.constitution = {
            "channel_name": "TestChannel",
            "visual_identity": {
                "style_prompt": "neon style"
            }
        }
        
        # Mock user_model
        # **実体と同じ形にする**（R1.5-C4・18周目）。
        # ここは以前 `{"ranks": {...}, "automation_settings": {...}}` という
        # **`backend/branding/user_model.json` に存在しない形**を作っていた。
        # そのせいで「存在しない鍵を読んで常に定数に落ちる」実装のバグが
        # テストでは見えず、むしろ固定されていた。実体は次の4つで裏取り済み:
        #   1. `backend/branding/user_model.json` の実キー（profiles / collaborative_settings）
        #   2. `branding_manager.update_user_rank()` の書き込み先
        #      （`user_model["profiles"][役割]["ranks"][段位]`）
        #   3. `branding_manager.set_auto_pilot()` の書き込み先（`collaborative_settings`）
        #   4. 画面側の読み口（`Boardroom.jsx` / `SoulPassport.jsx`）
        mock_bm.user_model = {
            "profiles": {
                "owner": {"ranks": {"biz_rank": {"level": "Novice", "xp": 0}}},
                "admin": {"ranks": {"tech_rank": {"level": "Novice", "xp": 0}}},
            },
            "collaborative_settings": {
                "auto_pilot_ratio": 0.9
            }
        }
        
        # Mock methods
        mock_bm.get_context_block.return_value = "Mocked Context Block"
        mock_bm.get_deep_context.return_value = "Mocked Deep Context"
        
        yield mock_bm


# -------------------------------------------------------------
# DirectorBrain Init Test
# -------------------------------------------------------------
def test_director_brain_init_stub():
    with patch("director_engine.get_gemini_client") as mock_get_client:
        mock_get_client.return_value = None
        # Initialize when client is None (Stub mode warning printed)
        brain = DirectorBrain()
        assert brain.client is None


# -------------------------------------------------------------
# semantic_dispatch Tests
# -------------------------------------------------------------
def test_semantic_dispatch_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    res = brain.semantic_dispatch("test input")
    assert res["intent"] == "test intent"
    assert "Strategist" in res["agents"]


def test_semantic_dispatch_fallback(mock_gemini, mock_branding):
    mock_gemini.models.generate_content.side_effect = RuntimeError("API Error")
    brain = DirectorBrain()
    res = brain.semantic_dispatch("test input")
    assert res["intent"] == "解析失敗"
    assert "Director" in res["agents"]
    assert "Analyst" in res["agents"]


# -------------------------------------------------------------
# route_to_agents Tests
# -------------------------------------------------------------
def test_route_to_agents(mock_gemini, mock_branding):
    brain = DirectorBrain()
    
    # Mock semantic_dispatch to return all agents
    dispatch_mock = {
        "agents": ["Strategist", "Director", "Analyst"],
        "confidence": 0.9
    }
    
    with patch.object(brain, "semantic_dispatch", return_value=dispatch_mock):
        with patch.object(brain, "consult", return_value="strat_res") as mock_consult, \
             patch.object(brain, "chat_session", return_value="dir_res") as mock_dir, \
             patch.object(brain, "_get_analyst_response", return_value="analyst_res") as mock_analyst:
                 
            res = brain.route_to_agents("input_text", history=[{"role": "user", "parts": ["hi"]}])
            
            assert res["responses"]["Strategist"] == "strat_res"
            assert res["responses"]["Director"] == "dir_res"
            assert res["responses"]["Analyst"] == "analyst_res"
            
            mock_consult.assert_called_once_with([{"role": "user", "parts": ["hi"]}], "input_text")
            mock_dir.assert_called_once_with([{"role": "user", "parts": ["hi"]}], "input_text")
            mock_analyst.assert_called_once_with("input_text")


# -------------------------------------------------------------
# _get_analyst_response Tests
# -------------------------------------------------------------
def test_get_analyst_response_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    mock_response = MagicMock()
    mock_response.text = "Analyst Analysis"
    mock_gemini.models.generate_content.return_value = mock_response
    
    res = brain._get_analyst_response("input")
    assert res == "Analyst Analysis"


def test_get_analyst_response_error(mock_gemini, mock_branding):
    brain = DirectorBrain()
    mock_gemini.models.generate_content.side_effect = RuntimeError("Analyst Error")
    res = brain._get_analyst_response("input")
    assert "分析エラー" in res


# -------------------------------------------------------------
# _get_system_instruction Tests
# -------------------------------------------------------------
def test_get_system_instruction_novice(mock_gemini, mock_branding):
    brain = DirectorBrain()
    
    # Novice mode
    inst_consult = brain._get_system_instruction(mode="consult")
    assert "初心者なので" in inst_consult
    assert "右脳" in inst_consult
    
    inst_director = brain._get_system_instruction(mode="director")
    assert "初心者なので" in inst_director
    assert "左脳" in inst_director


def test_get_system_instruction_pro(mock_gemini, mock_branding):
    # Professional mode
    mock_branding.user_model["profiles"]["owner"]["ranks"]["biz_rank"]["level"] = "Professional"
    mock_branding.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["level"] = "Professional"
    
    brain = DirectorBrain()
    inst_consult = brain._get_system_instruction(mode="consult")
    assert "プロ同士として" in inst_consult
    
    inst_director = brain._get_system_instruction(mode="director")
    assert "上級者なので" in inst_director


# -------------------------------------------------------------
# consult / chat_session Tests
# -------------------------------------------------------------
def test_consult_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    res = brain.consult([], "hello")
    assert res == "Chat Response Text"


def test_consult_error(mock_gemini, mock_branding):
    brain = DirectorBrain()
    mock_gemini.chats.create.side_effect = RuntimeError("Chat creation error")
    res = brain.consult([], "hello")
    assert "Strategic Context Error" in res


def test_chat_session_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    res = brain.chat_session([], "hello")
    assert res == "Chat Response Text"


def test_chat_session_error(mock_gemini, mock_branding):
    brain = DirectorBrain()
    mock_gemini.chats.create.side_effect = RuntimeError("Chat creation error")
    res = brain.chat_session([], "hello")
    assert "Creative Context Error" in res


# -------------------------------------------------------------
# generate_image Tests
# -------------------------------------------------------------
def test_generate_image_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    res = brain.generate_image("cool thumbnail")
    assert len(res) == 2
    assert res[0] == b"img_bytes_1"
    assert res[1] == b"img_bytes_2"
    
    # check that style was prepended
    mock_gemini.models.generate_images.assert_called_once()
    args, kwargs = mock_gemini.models.generate_images.call_args
    assert "neon style, cool thumbnail" in kwargs["prompt"]


def test_generate_image_error(mock_gemini, mock_branding):
    brain = DirectorBrain()
    mock_gemini.models.generate_images.side_effect = RuntimeError("Image Gen Error")
    res = brain.generate_image("cool thumbnail")
    assert res == []


# -------------------------------------------------------------
# process_image_task Tests
# -------------------------------------------------------------
def test_process_image_task_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    task_id = "test-task-1"
    director_engine.task_manager.tasks[task_id] = {
        "id": task_id,
        "status": "pending",
        "result": None,
        "error": None,
        "created_at": time.time()
    }
    
    dummy_bytes = [b"data1", b"data2"]
    with patch.object(brain, "generate_image", return_value=dummy_bytes):
        brain.process_image_task(task_id, "test prompt")
        
        task = director_engine.task_manager.get_task(task_id)
        assert task["status"] == "completed"
        assert len(task["result"]) == 2
        assert base64.b64decode(task["result"][0]) == b"data1"


def test_process_image_task_failed_no_images(mock_gemini, mock_branding):
    brain = DirectorBrain()
    task_id = "test-task-2"
    director_engine.task_manager.tasks[task_id] = {
        "id": task_id,
        "status": "pending",
        "result": None,
        "error": None,
        "created_at": time.time()
    }
    
    with patch.object(brain, "generate_image", return_value=[]):
        brain.process_image_task(task_id, "test prompt")
        task = director_engine.task_manager.get_task(task_id)
        assert task["status"] == "failed"
        assert task["error"] == "No images generated"


def test_process_image_task_exception(mock_gemini, mock_branding):
    brain = DirectorBrain()
    task_id = "test-task-3"
    director_engine.task_manager.tasks[task_id] = {
        "id": task_id,
        "status": "pending",
        "result": None,
        "error": None,
        "created_at": time.time()
    }
    
    with patch.object(brain, "generate_image", side_effect=RuntimeError("Task Failure")):
        brain.process_image_task(task_id, "test prompt")
        task = director_engine.task_manager.get_task(task_id)
        assert task["status"] == "failed"
        assert "Task Failure" in task["error"]


# -------------------------------------------------------------
# analyze_script Tests
# -------------------------------------------------------------
def test_analyze_script_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    res = brain.analyze_script("script text")
    assert "test intent" in res


def test_analyze_script_fallback(mock_gemini, mock_branding):
    brain = DirectorBrain()
    mock_gemini.models.generate_content.side_effect = RuntimeError("API Error")
    res = brain.analyze_script("script text")
    parsed = json.loads(res)
    assert len(parsed) == 3
    assert parsed[0]["id"] == "style_a"


# -------------------------------------------------------------
# generate_storyboard_plan Tests
# -------------------------------------------------------------
def test_generate_storyboard_plan_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    scenes = [{"name": "Scene 1", "description": "scene description"}]
    selected_style = {"name": "Style A", "visual_prompt": "prompt", "description": "style description"}
    res = brain.generate_storyboard_plan("full text", scenes, selected_style)
    assert "test intent" in res


def test_generate_storyboard_plan_fallback(mock_gemini, mock_branding):
    brain = DirectorBrain()
    scenes = [{"name": "Scene 1", "description": "scene description"}]
    selected_style = {"name": "Style A", "visual_prompt": "prompt", "description": "style description"}
    mock_gemini.models.generate_content.side_effect = RuntimeError("API Error")
    res = brain.generate_storyboard_plan("full text", scenes, selected_style)
    parsed = json.loads(res)
    assert len(parsed) == 1
    assert parsed[0]["index"] == 0
    assert parsed[0]["source_type"] == "AI"


def test_generate_storyboard_plan_fallback_invalid_scenes(mock_gemini, mock_branding):
    brain = DirectorBrain()
    selected_style = {"name": "Style A", "visual_prompt": "prompt", "description": "style description"}
    mock_gemini.models.generate_content.side_effect = RuntimeError("API Error")
    
    # case 1: scenes is None
    res_none = brain.generate_storyboard_plan("full text", None, selected_style)
    parsed_none = json.loads(res_none)
    assert parsed_none == []
    
    # case 2: scenes contains non-dict object and None
    class DummyScene:
        def __init__(self, name):
            self.name = name
            
    scenes_invalid = [DummyScene("Custom Scene Object"), None]
    res_invalid = brain.generate_storyboard_plan("full text", scenes_invalid, selected_style)
    parsed_invalid = json.loads(res_invalid)
    assert len(parsed_invalid) == 2
    assert parsed_invalid[0]["visual_prompt"] == "Scene context: Custom Scene Object"
    assert parsed_invalid[1]["visual_prompt"] == "Scene context: Scene 1"


# -------------------------------------------------------------
# analyze_resource_needs Tests
# -------------------------------------------------------------
def test_analyze_resource_needs_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    res = brain.analyze_resource_needs("script text")
    assert "test intent" in res


def test_analyze_resource_needs_fallback(mock_gemini, mock_branding):
    brain = DirectorBrain()
    mock_gemini.models.generate_content.side_effect = RuntimeError("API Error")
    res = brain.analyze_resource_needs("script text")
    assert res == "[]"


# -------------------------------------------------------------
# calculate_quality_score Tests
# -------------------------------------------------------------
def test_calculate_quality_score_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    res = brain.calculate_quality_score([], "Novice")
    assert "test intent" in res


def test_calculate_quality_score_fallback(mock_gemini, mock_branding):
    brain = DirectorBrain()
    mock_gemini.models.generate_content.side_effect = RuntimeError("API Error")
    res = brain.calculate_quality_score([], "Novice")
    parsed = json.loads(res)
    # **採点が落ちたら点も合格も名乗らない**（R1.5-C4）。
    # ここは以前 `score: 50 / rank: "C" / is_acceptable: True` を期待していたが、
    # UI（`DirectorBriefing.jsx:531,552`）が `is_acceptable` で緑の
    # 「制作開始 (Go)」を出すので、**採点が一度も走っていないのに合格に見えていた。**
    assert parsed["score"] is None
    assert parsed["rank"] is None
    assert parsed["is_acceptable"] is False
    assert parsed["is_real"] is False


# -------------------------------------------------------------
# process_batch_image_task Tests
# -------------------------------------------------------------
def test_process_batch_image_task_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    task_id = "batch-task-1"
    director_engine.task_manager.tasks[task_id] = {
        "id": task_id,
        "status": "pending",
        "result": None,
        "error": None,
        "created_at": time.time()
    }
    
    scenes = [
        {"name": "Scene 1", "description": "desc 1"},
        {"name": "Scene 2", "description": "desc 2"}
    ]
    
    dummy_bytes_1 = [b"img_bytes_1"]
    dummy_bytes_2 = [b"img_bytes_2"]
    
    with patch.object(brain, "generate_image", side_effect=[dummy_bytes_1, dummy_bytes_2]):
        brain.process_batch_image_task(task_id, scenes, "warm style")
        
        task = director_engine.task_manager.get_task(task_id)
        assert task["status"] == "completed"
        res_dict = task["result"]
        assert base64.b64decode(res_dict["0"]) == b"img_bytes_1"
        assert base64.b64decode(res_dict["1"]) == b"img_bytes_2"


def test_process_batch_image_task_failed(mock_gemini, mock_branding):
    brain = DirectorBrain()
    task_id = "batch-task-2"
    director_engine.task_manager.tasks[task_id] = {
        "id": task_id,
        "status": "pending",
        "result": None,
        "error": None,
        "created_at": time.time()
    }
    
    scenes = [{"name": "Scene 1", "description": "desc 1"}]
    
    with patch.object(brain, "generate_image", side_effect=RuntimeError("Batch gen failure")):
        brain.process_batch_image_task(task_id, scenes, "style")
        task = director_engine.task_manager.get_task(task_id)
        assert task["status"] == "failed"
        assert "Batch gen failure" in task["error"]


# -------------------------------------------------------------
# generate_production_report Tests
# -------------------------------------------------------------
def test_generate_production_report_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    res = brain.generate_production_report([], {}, "Novice")
    assert "test intent" in res


def test_generate_production_report_fallback(mock_gemini, mock_branding):
    brain = DirectorBrain()
    mock_gemini.models.generate_content.side_effect = RuntimeError("API Error")
    res = brain.generate_production_report([], {}, "Novice")
    parsed = json.loads(res)
    # **分析が落ちたら「問題なし」も「実績 XP」も名乗らない**（R1.5-C4・18周目 反例1）。
    # ここは以前 `summary == "セッション完了"` / `xp_grant == 50` を期待していた。
    # その 50 XP は `routers/director.py` の `if xp > 0:` を通って
    # `user_model.json` の `tech_rank` に**恒久保存**されていた。
    assert parsed["xp_grant"] == 0
    assert parsed["is_real"] is False
    assert parsed["data_source"] == "unavailable"
    assert parsed["issue_detected"] is None
    assert "分析は行われていません" in parsed["summary"]


# -------------------------------------------------------------
# verify_production_quality Tests
# -------------------------------------------------------------
def test_verify_production_quality_success(mock_gemini, mock_branding):
    brain = DirectorBrain()
    res = brain.verify_production_quality("script", [], [])
    assert "test intent" in res


def test_verify_production_quality_fallback(mock_gemini, mock_branding):
    brain = DirectorBrain()
    mock_gemini.models.generate_content.side_effect = RuntimeError("API Error")
    res = brain.verify_production_quality("script", [], [])
    parsed = json.loads(res)
    # **検査が落ちたら「進行可能」と言わない**（R1.5-C4）。ここは以前
    # `is_ready: True / score: 80` を期待していたので、**QA エンジンが
    # 一度も走っていなくてもレンダリングへ進めた。**
    assert parsed["is_ready"] is False
    assert parsed["score"] is None
    assert parsed["is_real"] is False
    assert "QAエンジンエラー" in parsed["final_verdict"]

