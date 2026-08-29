"""
M2.5: Director Engine テスト — 12テスト

director_engine.py (382 stmts, 180 missed → 18%) のカバレッジ改善。
TaskManager + DirectorBrain の非API依存メソッドを網羅。

外部依存: Gemini API → MagicMock で代替。
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Gemini APIをモック化してインポート
with patch("director_engine.get_gemini_client", return_value=MagicMock()), \
     patch("director_engine.branding_manager") as mock_bm:
    mock_bm.constitution = {
        "channel_name": "テストチャンネル",
        "visual_identity": {"style_prompt": "modern"},
    }
    mock_bm.user_model = {
        "ranks": {
            "biz_rank": {"level": "Novice"},
            "tech_rank": {"level": "Novice"},
        },
        "automation_settings": {"auto_pilot_ratio": 0.9},
    }
    mock_bm.get_context_block.return_value = "テストコンテキスト"
    mock_bm.get_deep_context.return_value = "テストディープコンテキスト"

    from director_engine import TaskManager, DirectorBrain, task_manager


# ============================================================
# TaskManager テスト
# ============================================================

class TestTaskManager:
    """TaskManager: タスク管理"""

    def test_create_task(self):
        """create_task: タスクID生成"""
        tm = TaskManager()
        task_id = tm.create_task()
        assert isinstance(task_id, str)
        assert len(task_id) == 36  # UUID形式

    def test_create_task_initial_state(self):
        """create_task: 初期状態"""
        tm = TaskManager()
        task_id = tm.create_task()
        task = tm.get_task(task_id)
        assert task["status"] == "pending"
        assert task["result"] is None
        assert task["error"] is None

    def test_update_task_status(self):
        """update_task: ステータス更新"""
        tm = TaskManager()
        task_id = tm.create_task()
        tm.update_task(task_id, "processing")
        assert tm.get_task(task_id)["status"] == "processing"

    def test_update_task_with_result(self):
        """update_task: 結果付き更新"""
        tm = TaskManager()
        task_id = tm.create_task()
        tm.update_task(task_id, "completed", result={"images": ["img1"]})
        task = tm.get_task(task_id)
        assert task["status"] == "completed"
        assert task["result"]["images"] == ["img1"]

    def test_update_task_with_error(self):
        """update_task: エラー付き更新"""
        tm = TaskManager()
        task_id = tm.create_task()
        tm.update_task(task_id, "failed", error="Test error")
        task = tm.get_task(task_id)
        assert task["error"] == "Test error"

    def test_update_task_nonexistent(self):
        """update_task: 存在しないタスク → エラーなし"""
        tm = TaskManager()
        tm.update_task("nonexistent", "processing")  # 例外なし

    def test_get_task_not_found(self):
        """get_task: 存在しないタスク → None"""
        tm = TaskManager()
        assert tm.get_task("nonexistent") is None


# ============================================================
# DirectorBrain テスト (非API依存メソッド)
# ============================================================

class TestDirectorBrain:
    """DirectorBrain: 非API依存機能"""

    def test_semantic_dispatch_fallback(self):
        """semantic_dispatch: API失敗 → フォールバック"""
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_api.models.generate_content.side_effect = Exception("API Error")
            mock_client.return_value = mock_api
            brain = DirectorBrain()
            result = brain.semantic_dispatch("テスト入力")
        assert result["intent"] == "解析失敗"
        assert "Strategist" in result["agents"]
        assert result["confidence"] == 0.5

    def test_analyst_response_fallback(self):
        """_get_analyst_response: API失敗 → エラーメッセージ"""
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_api.models.generate_content.side_effect = Exception("API Error")
            mock_client.return_value = mock_api
            brain = DirectorBrain()
            result = brain._get_analyst_response("テスト質問")
        assert "分析エラー" in result

    def test_analyze_script_fallback(self):
        """analyze_script: API失敗 → フォールバックJSON"""
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_api.models.generate_content.side_effect = Exception("API Error")
            mock_client.return_value = mock_api
            brain = DirectorBrain()
            result = brain.analyze_script("テスト脚本")
        parsed = json.loads(result)
        assert len(parsed) == 3
        assert parsed[0]["id"] == "style_a"

    def test_calculate_quality_score_fallback(self):
        """calculate_quality_score: API失敗 → フォールバック"""
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_api.models.generate_content.side_effect = Exception("API Error")
            mock_client.return_value = mock_api
            brain = DirectorBrain()
            result = brain.calculate_quality_score([], "Novice")
        parsed = json.loads(result)
        # **採点が落ちたら点も合格も名乗らない**（R1.5-C4）。
        # 旧 `score: 50 / rank: "C"` は「合格」を意味する `is_acceptable: True`
        # と一緒に返っていた。
        assert parsed["score"] is None
        assert parsed["rank"] is None
        assert parsed["is_acceptable"] is False

    def test_generate_production_report_fallback(self):
        """generate_production_report: API失敗 → フォールバック"""
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_api.models.generate_content.side_effect = Exception("API Error")
            mock_client.return_value = mock_api
            brain = DirectorBrain()
            result = brain.generate_production_report([], {}, "Novice")
        parsed = json.loads(result)
        assert parsed["xp_grant"] == 50

    def test_semantic_dispatch_success(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = '{"intent": "テスト", "agents": ["Strategist"], "confidence": 0.9, "rationale": "ok"}'
            mock_api.models.generate_content.return_value = mock_resp
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.semantic_dispatch("テスト入力")
            assert res["intent"] == "テスト"
            assert res["agents"] == ["Strategist"]

    def test_route_to_agents(self):
        brain = DirectorBrain()
        with patch.object(brain, "semantic_dispatch") as mock_disp, \
             patch.object(brain, "consult") as mock_cons, \
             patch.object(brain, "chat_session") as mock_chat, \
             patch.object(brain, "_get_analyst_response") as mock_ana:
             
            mock_disp.return_value = {"agents": ["Strategist", "Director", "Analyst"]}
            mock_cons.return_value = "consult_resp"
            mock_chat.return_value = "chat_resp"
            mock_ana.return_value = "analyst_resp"
            
            res = brain.route_to_agents("入力")
            assert res["responses"]["Strategist"] == "consult_resp"
            assert res["responses"]["Director"] == "chat_resp"
            assert res["responses"]["Analyst"] == "analyst_resp"

    def test_get_analyst_response_success(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = "分析結果テキスト"
            mock_api.models.generate_content.return_value = mock_resp
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain._get_analyst_response("質問")
            assert res == "分析結果テキスト"

    def test_system_instruction(self):
        brain = DirectorBrain()
        with patch("director_engine.branding_manager") as mock_bm:
            mock_bm.constitution = {"channel_name": "チャンネル"}
            mock_bm.user_model = {
                "ranks": {
                    "biz_rank": {"level": "Expert"},
                    "tech_rank": {"level": "Expert"}
                },
                "automation_settings": {"auto_pilot_ratio": 0.5}
            }
            mock_bm.get_context_block.return_value = "C_BLOCK"
            mock_bm.get_deep_context.return_value = "D_BLOCK"
            
            inst = brain._get_system_instruction(mode="consult")
            assert "チャンネル" in inst
            assert "Expert" in inst
            assert "C_BLOCK" in inst
            
            inst_dir = brain._get_system_instruction(mode="director")
            assert "D_BLOCK" in inst_dir

    def test_generate_image_success(self):
        with patch("director_engine.get_gemini_client") as mock_client, \
             patch("director_engine.branding_manager") as mock_bm:
             
            mock_bm.constitution = {"visual_identity": {"style_prompt": "cyberpunk"}}
            mock_api = MagicMock()
            mock_img_resp = MagicMock()
            mock_gen_img = MagicMock()
            mock_gen_img.image.image_bytes = b"image_data"
            mock_img_resp.generated_images = [mock_gen_img]
            mock_api.models.generate_images.return_value = mock_img_resp
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            imgs = brain.generate_image("thumbnail")
            assert len(imgs) == 1
            assert imgs[0] == b"image_data"

    def test_generate_image_error(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_api.models.generate_images.side_effect = Exception("Gen Error")
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            imgs = brain.generate_image("thumbnail")
            assert imgs == []

    def test_process_image_task(self):
        brain = DirectorBrain()
        from director_engine import task_manager
        task_id = task_manager.create_task()
        
        with patch.object(brain, "generate_image") as mock_gen:
            mock_gen.return_value = [b"img_bytes"]
            brain.process_image_task(task_id, "prompt")
            
        task = task_manager.get_task(task_id)
        assert task["status"] == "completed"
        assert len(task["result"]) == 1

    def test_process_image_task_fail(self):
        brain = DirectorBrain()
        from director_engine import task_manager
        task_id = task_manager.create_task()
        
        with patch.object(brain, "generate_image") as mock_gen:
            mock_gen.return_value = []
            brain.process_image_task(task_id, "prompt")
            
        task = task_manager.get_task(task_id)
        assert task["status"] == "failed"

    def test_analyze_script_success(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = '[{"id": "a"}]'
            mock_api.models.generate_content.return_value = mock_resp
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.analyze_script("text")
            assert res == '[{"id": "a"}]'

    def test_generate_storyboard_plan_success(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = '[{"index": 0}]'
            mock_api.models.generate_content.return_value = mock_resp
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.generate_storyboard_plan("text", [{"name": "s1", "description": "d1"}], {"name": "style", "description": "desc", "visual_prompt": "prompt"})
            assert res == '[{"index": 0}]'

    def test_analyze_resource_needs_success(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = '[{"id": "asset_1"}]'
            mock_api.models.generate_content.return_value = mock_resp
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.analyze_resource_needs("text")
            assert res == '[{"id": "asset_1"}]'

    def test_calculate_quality_score_success(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = '{"score": 90}'
            mock_api.models.generate_content.return_value = mock_resp
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.calculate_quality_score([])
            assert res == '{"score": 90}'

    def test_process_batch_image_task(self):
        brain = DirectorBrain()
        from director_engine import task_manager
        task_id = task_manager.create_task()
        
        with patch.object(brain, "generate_image") as mock_gen:
            mock_gen.return_value = [b"img_bytes"]
            brain.process_batch_image_task(task_id, [{"name": "s1", "description": "d1"}], "style_prompt")
            
        task = task_manager.get_task(task_id)
        assert task["status"] == "completed"

    def test_process_batch_image_task_error(self):
        brain = DirectorBrain()
        from director_engine import task_manager
        task_id = task_manager.create_task()
        
        with patch.object(brain, "generate_image", side_effect=Exception("Gen Error")):
            brain.process_batch_image_task(task_id, [{"name": "s1", "description": "d1"}], "style_prompt")
            
        task = task_manager.get_task(task_id)
        assert task["status"] == "failed"

    def test_generate_production_report_success(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = '{"summary": "ok"}'
            mock_api.models.generate_content.return_value = mock_resp
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.generate_production_report([], {})
            assert res == '{"summary": "ok"}'

    def test_verify_production_quality_success(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = '{"is_ready": true}'
            mock_api.models.generate_content.return_value = mock_resp
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.verify_production_quality("text", [{"name": "s1"}], [{"text": "seg"}])
            assert res == '{"is_ready": true}'

    def test_verify_production_quality_fallback(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_api.models.generate_content.side_effect = Exception("API Error")
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.verify_production_quality("text", [], [])
        parsed = json.loads(res)
        assert parsed["is_ready"] is True
        assert "QAエンジンエラー" in parsed["final_verdict"]

    def test_consult_error(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_api.chats.create.side_effect = Exception("Consult Fail")
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.consult([], "hello")
            assert "Strategic Context Error: Consult Fail" in res

    def test_chat_session_error(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_api.chats.create.side_effect = Exception("Director Fail")
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.chat_session([], "hello")
            assert "Creative Context Error: Director Fail" in res

    def test_process_image_task_exception(self):
        brain = DirectorBrain()
        from director_engine import task_manager
        task_id = task_manager.create_task()
        
        with patch.object(brain, "generate_image", side_effect=Exception("Task Process Error")):
            brain.process_image_task(task_id, "prompt")
            
        task = task_manager.get_task(task_id)
        assert task["status"] == "failed"
        assert task["error"] == "Task Process Error"

    def test_generate_storyboard_plan_error(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_api.models.generate_content.side_effect = Exception("Storyboard Fail")
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            scenes = [{"name": "Scene 1", "description": "Desc 1"}]
            res = brain.generate_storyboard_plan("text", scenes, {"name": "style"})
            parsed = json.loads(res)
            assert len(parsed) == 1
            assert parsed[0]["index"] == 0
            assert parsed[0]["source_type"] == "AI"

    def test_analyze_resource_needs_error(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_api.models.generate_content.side_effect = Exception("Resource Fail")
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.analyze_resource_needs("text")
            assert res == "[]"

    def test_consult_success(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_chat = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = "Strategic Answer"
            mock_chat.send_message.return_value = mock_resp
            mock_api.chats.create.return_value = mock_chat
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.consult([], "hello")
            assert res == "Strategic Answer"

    def test_chat_session_success(self):
        with patch("director_engine.get_gemini_client") as mock_client:
            mock_api = MagicMock()
            mock_chat = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = "Creative Answer"
            mock_chat.send_message.return_value = mock_resp
            mock_api.chats.create.return_value = mock_chat
            mock_client.return_value = mock_api
            
            brain = DirectorBrain()
            res = brain.chat_session([], "hello")
            assert res == "Creative Answer"
