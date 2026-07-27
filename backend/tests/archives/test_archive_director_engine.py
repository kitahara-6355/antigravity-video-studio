import pytest
import sys
import os
import json
import base64
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from google.genai.errors import APIError

# バックエンドおよびアーカイブパスを sys.path に追加
backend_dir = Path(__file__).resolve().parents[2]
archive_dir = backend_dir / "archives" / "archive_stable_v3.0_20260118_0953"

# 強制的にメモリ上の古い director_engine モジュールを削除して再ロード
# アーカイブ版を優先させるため、sys.path の先頭に archive_dir を配置
if str(archive_dir) not in sys.path:
    sys.path.insert(0, str(archive_dir))
if str(backend_dir) not in sys.path:
    sys.path.append(str(backend_dir)) # backend_dir は末尾に追加して優先度を下げる

for mod in ["director_engine", "archives.archive_stable_v3.0_20260118_0953.director_engine", "model_registry", "branding_manager"]:
    if mod in sys.modules:
        del sys.modules[mod]

# 環境変数
os.environ["GOOGLE_API_KEY"] = "mock_api_key"

# 必要なモックの定義と登録（他の依存関係解決のため）
mock_branding_manager = MagicMock()
sys.modules["branding_manager"] = MagicMock(branding_manager=mock_branding_manager)

# mock branding_manager data
mock_branding_manager.constitution = {
    "channel_name": "Test Channel",
    "visual_identity": {
        "style_prompt": "cinematic look"
    }
}
mock_branding_manager.user_model = {
    "ranks": {
        "biz_rank": {"level": "Novice"},
        "tech_rank": {"level": "Novice"}
    },
    "automation_settings": {
        "auto_pilot_ratio": 0.8
    }
}
mock_branding_manager.get_context_block.return_value = "Mock context block"
mock_branding_manager.get_deep_context.return_value = "Mock deep context"
mock_branding_manager.ingest_report.return_value = "Mock ingest result"

# グローバルに google.genai.Client をモック（インポート時の brain = DirectorBrain() による本物呼び出しを防止）
with patch("google.genai.Client") as mock_client_cls:
    mock_client_instance = MagicMock()
    mock_client_cls.return_value = mock_client_instance
    
    # director_engine をインポート
    import director_engine
    print("RESOLVED DIRECTOR ENGINE PATH:", director_engine.__file__)

@pytest.fixture
def mock_genai_client():
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        yield mock_client


def test_task_manager():
    tm = director_engine.TaskManager()
    task_id = tm.create_task()
    assert task_id is not None
    
    task = tm.get_task(task_id)
    assert task["status"] == "pending"
    
    tm.update_task(task_id, "completed", result="success_result", error=None)
    task = tm.get_task(task_id)
    assert task["status"] == "completed"
    assert task["result"] == "success_result"
    
    task_none = tm.get_task("non-existent")
    assert task_none is None

def test_director_brain_init(mock_genai_client):
    brain = director_engine.DirectorBrain()
    assert brain.api_key == "mock_api_key"
    assert brain.chat_model == director_engine.get_model("director")

def test_semantic_dispatch_success(mock_genai_client):
    brain = director_engine.DirectorBrain()
    
    mock_response = MagicMock()
    mock_response.text = '{"intent": "test intent", "agents": ["Strategist"], "confidence": 0.9, "rationale": "reason"}'
    brain.client.models.generate_content.return_value = mock_response
    
    result = brain.semantic_dispatch("test input")
    assert result["intent"] == "test intent"
    assert "Strategist" in result["agents"]

def test_semantic_dispatch_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    brain.client.models.generate_content.side_effect = APIError(code=500, response_json={"message": "API error"})
    
    result = brain.semantic_dispatch("test input")
    assert result["intent"] == "解析失敗"
    assert "Strategist" in result["agents"]
    assert "Director" in result["agents"]
    assert "Analyst" in result["agents"]

def test_route_to_agents(mock_genai_client):
    brain = director_engine.DirectorBrain()
    
    # Mock semantic dispatch response
    mock_response_dispatch = MagicMock()
    mock_response_dispatch.text = '{"intent": "test", "agents": ["Strategist", "Director", "Analyst"], "confidence": 0.8}'
    
    # Mock generic content response
    mock_response_generic = MagicMock()
    mock_response_generic.text = "Mocked Response"
    
    # Side effects for generate_content
    # Call 1: Dispatch
    # Call 2: consult
    # Call 3: chat_session
    # Call 4: Analyst response
    brain.client.models.generate_content.side_effect = [
        mock_response_dispatch,
        mock_response_generic,
        mock_response_generic,
        mock_response_generic
    ]
    
    # Mock chats.create for chats API used in consult & chat_session
    mock_chat = MagicMock()
    mock_chat.send_message.return_value = mock_response_generic
    brain.client.chats.create.return_value = mock_chat
    
    result = brain.route_to_agents("test input")
    assert "dispatch" in result
    assert "responses" in result
    assert "Strategist" in result["responses"]
    assert "Director" in result["responses"]
    assert "Analyst" in result["responses"]

def test_get_analyst_response_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    brain.client.models.generate_content.side_effect = APIError(code=500, response_json={"message": "API Error"})
    
    res = brain._get_analyst_response("test")
    assert "分析エラー" in res

def test_system_instruction_novice(mock_genai_client):
    brain = director_engine.DirectorBrain()
    
    # Test novice mode
    mock_branding_manager.user_model["ranks"]["biz_rank"]["level"] = "Novice"
    mock_branding_manager.user_model["ranks"]["tech_rank"]["level"] = "Novice"
    
    inst = brain._get_system_instruction(mode="consult")
    assert "初心者" in inst
    assert "左脳" in inst
    
    inst_dir = brain._get_system_instruction(mode="director")
    assert "初心者" in inst_dir
    assert "右脳" in inst_dir

def test_system_instruction_pro(mock_genai_client):
    brain = director_engine.DirectorBrain()
    
    # Test expert mode
    mock_branding_manager.user_model["ranks"]["biz_rank"]["level"] = "Expert"
    mock_branding_manager.user_model["ranks"]["tech_rank"]["level"] = "Expert"
    
    inst = brain._get_system_instruction(mode="consult")
    assert "プロ同士" in inst
    
    inst_dir = brain._get_system_instruction(mode="director")
    assert "上級者" in inst_dir

def test_consult_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    brain.client.chats.create.side_effect = APIError(code=500, response_json={"message": "Chat creation error"})
    
    res = brain.consult([], "test")
    assert "Strategic Context Error" in res

def test_chat_session_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    brain.client.chats.create.side_effect = APIError(code=500, response_json={"message": "Chat creation error"})
    
    res = brain.chat_session([], "test")
    assert "Creative Context Error" in res

def test_generate_image_success(mock_genai_client):
    brain = director_engine.DirectorBrain()
    
    mock_img_result = MagicMock()
    mock_generated_image = MagicMock()
    mock_generated_image.image.image_bytes = b"image_data_bytes"
    mock_img_result.generated_images = [mock_generated_image]
    
    brain.client.models.generate_images.return_value = mock_img_result
    
    res = brain.generate_image("test prompt")
    assert len(res) == 1
    assert res[0] == b"image_data_bytes"

def test_generate_image_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    brain.client.models.generate_images.side_effect = APIError(code=500, response_json={"message": "API error"})
    
    import pytest
    with pytest.raises(APIError):
        brain.generate_image("test prompt")

def test_process_image_task_success(mock_genai_client):
    brain = director_engine.DirectorBrain()
    task_id = director_engine.task_manager.create_task()
    
    mock_img_result = MagicMock()
    mock_generated_image = MagicMock()
    mock_generated_image.image.image_bytes = b"image_bytes"
    mock_img_result.generated_images = [mock_generated_image]
    brain.client.models.generate_images.return_value = mock_img_result
    
    brain.process_image_task(task_id, "test prompt")
    task = director_engine.task_manager.get_task(task_id)
    assert task["status"] == "completed"
    assert len(task["result"]) == 1

def test_process_image_task_no_images(mock_genai_client):
    brain = director_engine.DirectorBrain()
    task_id = director_engine.task_manager.create_task()
    
    brain.client.models.generate_images.return_value = MagicMock(generated_images=[])
    
    brain.process_image_task(task_id, "test prompt")
    task = director_engine.task_manager.get_task(task_id)
    assert task["status"] == "failed"
    assert task["error"] == "No images generated"

def test_process_image_task_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    task_id = director_engine.task_manager.create_task()
    
    brain.client.models.generate_images.side_effect = Exception("Process Error")
    
    brain.process_image_task(task_id, "test prompt")
    task = director_engine.task_manager.get_task(task_id)
    assert task["status"] == "failed"
    assert "Process Error" in task["error"]

def test_analyze_script_success(mock_genai_client):
    brain = director_engine.DirectorBrain()
    mock_response = MagicMock()
    mock_response.text = '{"concepts": []}'
    brain.client.models.generate_content.return_value = mock_response
    
    res = brain.analyze_script("test text")
    assert res == '{"concepts": []}'

def test_analyze_script_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    brain.client.models.generate_content.side_effect = APIError(code=500, response_json={"message": "Analysis Error"})
    
    res = brain.analyze_script("test text")
    # Verify fallback is returned
    parsed = json.loads(res)
    assert len(parsed) == 3
    assert parsed[0]["id"] == "style_a"

def test_generate_storyboard_plan_success(mock_genai_client):
    brain = director_engine.DirectorBrain()
    mock_response = MagicMock()
    mock_response.text = '{"storyboard": []}'
    brain.client.models.generate_content.return_value = mock_response
    
    res = brain.generate_storyboard_plan("text", [{"name": "s1", "description": "d1"}], {"name": "style", "visual_prompt": "style prompt", "description": "style desc"})
    assert res == '{"storyboard": []}'

def test_generate_storyboard_plan_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    brain.client.models.generate_content.side_effect = APIError(code=500, response_json={"message": "Storyboard Plan Error"})
    
    res = brain.generate_storyboard_plan("text", [{"name": "s1", "description": "d1"}], {"name": "style", "visual_prompt": "style prompt", "description": "style desc"})
    parsed = json.loads(res)
    assert len(parsed) == 1
    assert parsed[0]["index"] == 0

def test_analyze_resource_needs_success(mock_genai_client):
    brain = director_engine.DirectorBrain()
    mock_response = MagicMock()
    mock_response.text = '{"resources": []}'
    brain.client.models.generate_content.return_value = mock_response
    
    res = brain.analyze_resource_needs("text")
    assert res == '{"resources": []}'

def test_analyze_resource_needs_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    brain.client.models.generate_content.side_effect = APIError(code=500, response_json={"message": "Audit Error"})
    
    res = brain.analyze_resource_needs("text")
    assert res == "[]"

def test_calculate_quality_score_success(mock_genai_client):
    brain = director_engine.DirectorBrain()
    mock_response = MagicMock()
    mock_response.text = '{"score": 90}'
    brain.client.models.generate_content.return_value = mock_response
    
    res = brain.calculate_quality_score("plan")
    assert res == '{"score": 90}'

def test_calculate_quality_score_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    brain.client.models.generate_content.side_effect = APIError(code=500, response_json={"message": "Score Error"})
    
    res = brain.calculate_quality_score("plan")
    parsed = json.loads(res)
    assert parsed["score"] == 50

def test_process_batch_image_task_success(mock_genai_client):
    brain = director_engine.DirectorBrain()
    task_id = director_engine.task_manager.create_task()
    
    mock_img_result = MagicMock()
    mock_generated_image = MagicMock()
    mock_generated_image.image.image_bytes = b"batch_image_bytes"
    mock_img_result.generated_images = [mock_generated_image]
    brain.client.models.generate_images.return_value = mock_img_result
    
    scenes = [{"name": "s1", "description": "d1"}]
    
    with patch("time.sleep"):
        brain.process_batch_image_task(task_id, scenes, "style")
    
    task = director_engine.task_manager.get_task(task_id)
    assert task["status"] == "completed"
    assert "0" in task["result"]

def test_process_batch_image_task_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    task_id = director_engine.task_manager.create_task()
    
    brain.client.models.generate_images.side_effect = APIError(code=500, response_json={"message": "Batch Gen Error"})
    scenes = [{"name": "s1", "description": "d1"}]
    
    brain.process_batch_image_task(task_id, scenes, "style")
    task = director_engine.task_manager.get_task(task_id)
    assert task["status"] == "failed"
    assert "Batch Gen Error" in task["error"]

def test_generate_production_report_success(mock_genai_client):
    brain = director_engine.DirectorBrain()
    mock_response = MagicMock()
    mock_response.text = '{"summary": "report"}'
    brain.client.models.generate_content.return_value = mock_response
    
    res = brain.generate_production_report("plan", "score")
    assert res == '{"summary": "report"}'

def test_generate_production_report_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    brain.client.models.generate_content.side_effect = APIError(code=500, response_json={"message": "Report Error"})
    
    res = brain.generate_production_report("plan", "score")
    parsed = json.loads(res)
    assert parsed["summary"] == "セッション完了"

def test_verify_production_quality_success(mock_genai_client):
    brain = director_engine.DirectorBrain()
    mock_response = MagicMock()
    mock_response.text = '{"is_ready": true}'
    brain.client.models.generate_content.return_value = mock_response
    
    res = brain.verify_production_quality("text", [{"name": "s1", "source_type": "AI"}], [{"text": "segment"}])
    assert res == '{"is_ready": true}'

def test_verify_production_quality_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    brain.client.models.generate_content.side_effect = APIError(code=500, response_json={"message": "QA Error"})
    
    res = brain.verify_production_quality("text", [{"name": "s1", "source_type": "AI"}], [{"text": "segment"}])
    parsed = json.loads(res)
    assert parsed["is_ready"] is True


def test_semantic_dispatch_generic_exception(mock_genai_client):
    brain = director_engine.DirectorBrain()
    # APIError 以外の一般的な例外をモックで投げるように設定
    brain.client.models.generate_content.side_effect = RuntimeError("Generic connection error")
    
    result = brain.semantic_dispatch("test input")
    # フォールバックにより全エージェントがアサインされることを検証
    assert result["intent"] == "解析失敗"
    assert "Strategist" in result["agents"]
    assert "Director" in result["agents"]
    assert "Analyst" in result["agents"]


def test_process_batch_image_task_no_images_generated(mock_genai_client):
    brain = director_engine.DirectorBrain()
    task_id = director_engine.task_manager.create_task()
    
    # 画像生成が空リスト（生成なし）を返すようにモックを設定
    brain.client.models.generate_images.return_value = MagicMock(generated_images=[])
    scenes = [{"name": "s1", "description": "d1"}]
    
    brain.process_batch_image_task(task_id, scenes, "style")
    task = director_engine.task_manager.get_task(task_id)
    # 画像が生成されなかったためタスクが failed になることを検証
    assert task["status"] == "failed"
    assert task["error"] == "No images generated"


def test_director_brain_stub_mode(mock_genai_client):
    # 環境変数を退避
    old_key = os.environ.get("GOOGLE_API_KEY")
    if "GOOGLE_API_KEY" in os.environ:
        del os.environ["GOOGLE_API_KEY"]
    
    # Client が初期化時に例外を投げるようにモック
    with patch("google.genai.Client", side_effect=ValueError("API key is required")):
        brain = director_engine.DirectorBrain()
        
    # スタブモードであることを検証
    assert brain.client is None
    
    # consult, chat_session がクラッシュせずにフォールバック応答を返すこと
    res_consult = brain.consult([], "test text")
    assert "Strategic Context Error" in res_consult
    
    res_chat = brain.chat_session([], "test text")
    assert "Creative Context Error" in res_chat
    
    # generate_image が例外（AttributeError等）を投げること
    with pytest.raises(Exception):
        brain.generate_image("test prompt")
        
    # 環境変数を復元
    if old_key is not None:
        os.environ["GOOGLE_API_KEY"] = old_key
