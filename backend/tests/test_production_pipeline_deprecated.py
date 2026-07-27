import pytest
import sys
import json
import builtins
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

# テスト対象モジュールをインポート
import backend.agents._deprecated.production_pipeline as prod_pipeline

# ============================================================
# 1. _wrap_tool のテスト
# ============================================================

def test_wrap_tool_self_healing_disabled():
    with patch.object(prod_pipeline, '_SELF_HEALING_AVAILABLE', False):
        def dummy():
            pass
        wrapped = prod_pipeline._wrap_tool(dummy)
        assert wrapped is dummy

def test_wrap_tool_self_healing_enabled():
    mock_self_healing = MagicMock()
    
    # wrapped に __name__ や __doc__ がないケース
    class DummyWrapped:
        pass
    
    mock_self_healing.wrap.return_value = DummyWrapped()
    
    with patch.object(prod_pipeline, '_SELF_HEALING_AVAILABLE', True):
        with patch.object(prod_pipeline, 'self_healing', mock_self_healing):
            def orig_func():
                """Orig doc"""
                pass
            wrapped = prod_pipeline._wrap_tool(orig_func)
            assert wrapped.__name__ == "orig_func"
            assert wrapped.__doc__ == "Orig doc"

    # wrapped にすでに __name__ や __doc__ があり、同一のケース
    class DummyWrappedWithAttrs:
        __name__ = "orig_func"
        __doc__ = "Orig doc"

    mock_self_healing.wrap.return_value = DummyWrappedWithAttrs()
    
    with patch.object(prod_pipeline, '_SELF_HEALING_AVAILABLE', True):
        with patch.object(prod_pipeline, 'self_healing', mock_self_healing):
            def orig_func2():
                """Orig doc"""
                pass
            wrapped = prod_pipeline._wrap_tool(orig_func2)
            assert wrapped.__name__ == "orig_func2"


# ============================================================
# 2. _get_verified_facts_context のテスト
# ============================================================

def test_get_verified_facts_context_success():
    mock_store = MagicMock()
    mock_store.get_facts_for_context.return_value = "verified facts content"
    
    # sys.modules にダミーの verified_facts を登録
    dummy_facts_mod = MagicMock()
    dummy_facts_mod.verified_facts_store = mock_store
    
    with patch.dict(sys.modules, {'agents.memory.verified_facts': dummy_facts_mod}):
        res = prod_pipeline._get_verified_facts_context()
        assert res == "verified facts content"

def test_get_verified_facts_context_empty():
    mock_store = MagicMock()
    mock_store.get_facts_for_context.return_value = None
    
    dummy_facts_mod = MagicMock()
    dummy_facts_mod.verified_facts_store = mock_store
    
    with patch.dict(sys.modules, {'agents.memory.verified_facts': dummy_facts_mod}):
        res = prod_pipeline._get_verified_facts_context()
        assert res == ""

def test_get_verified_facts_context_import_error():
    # インポート時に ImportError が起きるように sys.modules から削除し、インポートを邪魔する
    with patch.dict(sys.modules, {'agents.memory.verified_facts': None}):
        res = prod_pipeline._get_verified_facts_context()
        assert res == ""

def test_get_verified_facts_context_generic_exception():
    mock_store = MagicMock()
    mock_store.get_facts_for_context.side_effect = Exception("General error")
    
    dummy_facts_mod = MagicMock()
    dummy_facts_mod.verified_facts_store = mock_store
    
    with patch.dict(sys.modules, {'agents.memory.verified_facts': dummy_facts_mod}):
        res = prod_pipeline._get_verified_facts_context()
        assert res == ""


# ============================================================
# 3. transcribe_video のテスト
# ============================================================

def test_transcribe_video_success():
    mock_run = MagicMock(return_value={"status": "success", "segments": [{"text": "hello"}]})
    dummy_whisper = MagicMock()
    dummy_whisper.run_whisper_subprocess = mock_run
    
    with patch.dict(sys.modules, {'subtitle_engine.whisper_subprocess': dummy_whisper}):
        res = prod_pipeline.transcribe_video("video.mp4")
        data = json.loads(res)
        assert data["status"] == "success"
        assert data["segments_count"] == 1
        assert data["segments"][0]["text"] == "hello"

def test_transcribe_video_subprocess_error():
    mock_run = MagicMock(return_value={"status": "failed", "error": "GPU error"})
    dummy_whisper = MagicMock()
    dummy_whisper.run_whisper_subprocess = mock_run
    
    with patch.dict(sys.modules, {'subtitle_engine.whisper_subprocess': dummy_whisper}):
        res = prod_pipeline.transcribe_video("video.mp4")
        data = json.loads(res)
        assert data["status"] == "error"
        assert data["error"] == "GPU error"

def test_transcribe_video_import_error():
    with patch.dict(sys.modules, {'subtitle_engine.whisper_subprocess': None}):
        res = prod_pipeline.transcribe_video("video.mp4")
        data = json.loads(res)
        assert data["status"] == "error"
        assert "Import failed" in data["error"]

def test_transcribe_video_json_decode_error():
    # transcribe_video 内の json.dumps() やその他で例外を起こすため、
    # run_whisper_subprocess が成功しつつ、その後の json 処理などでデコードエラーを起こさせる
    # ここでは、run_whisper_subprocess が json.JSONDecodeError を直接 raise するようにモックする
    mock_run = MagicMock(side_effect=json.JSONDecodeError("mock msg", "doc", 0))
    dummy_whisper = MagicMock()
    dummy_whisper.run_whisper_subprocess = mock_run
    
    with patch.dict(sys.modules, {'subtitle_engine.whisper_subprocess': dummy_whisper}):
        res = prod_pipeline.transcribe_video("video.mp4")
        data = json.loads(res)
        assert data["status"] == "error"
        assert "JSON decode failed" in data["error"]

def test_transcribe_video_generic_exception():
    mock_run = MagicMock(side_effect=Exception("Generic failure"))
    dummy_whisper = MagicMock()
    dummy_whisper.run_whisper_subprocess = mock_run
    
    with patch.dict(sys.modules, {'subtitle_engine.whisper_subprocess': dummy_whisper}):
        res = prod_pipeline.transcribe_video("video.mp4")
        data = json.loads(res)
        assert data["status"] == "error"
        assert data["error"] == "Generic failure"


# ============================================================
# 4. proofread_subtitles のテスト
# ============================================================

def test_proofread_subtitles_success_dict_input():
    mock_proof = MagicMock(return_value=[{"text": "corrected"}])
    dummy_proof = MagicMock()
    dummy_proof.proofread_segments = mock_proof
    
    with patch.dict(sys.modules, {'subtitle_engine.ai_proofreader': dummy_proof}):
        input_json = json.dumps({"segments": [{"text": "original"}]})
        res = prod_pipeline.proofread_subtitles(input_json)
        data = json.loads(res)
        assert data["status"] == "success"
        assert data["segments"][0]["text"] == "corrected"

def test_proofread_subtitles_success_list_input():
    mock_proof = MagicMock(return_value=[{"text": "corrected2"}])
    dummy_proof = MagicMock()
    dummy_proof.proofread_segments = mock_proof
    
    with patch.dict(sys.modules, {'subtitle_engine.ai_proofreader': dummy_proof}):
        input_json = json.dumps([{"text": "original"}])
        res = prod_pipeline.proofread_subtitles(input_json)
        data = json.loads(res)
        assert data["status"] == "success"
        assert data["segments"][0]["text"] == "corrected2"

def test_proofread_subtitles_import_error():
    with patch.dict(sys.modules, {'subtitle_engine.ai_proofreader': None}):
        res = prod_pipeline.proofread_subtitles("[]")
        data = json.loads(res)
        assert data["status"] == "error"
        assert "Import failed" in data["error"]

def test_proofread_subtitles_json_decode_error():
    # 不正な JSON 文字列を入力する
    res = prod_pipeline.proofread_subtitles("{invalid")
    data = json.loads(res)
    assert data["status"] == "error"
    assert "Invalid JSON" in data["error"]

def test_proofread_subtitles_generic_exception():
    mock_proof = MagicMock(side_effect=Exception("Proofread API crash"))
    dummy_proof = MagicMock()
    dummy_proof.proofread_segments = mock_proof
    
    with patch.dict(sys.modules, {'subtitle_engine.ai_proofreader': dummy_proof}):
        res = prod_pipeline.proofread_subtitles("[]")
        data = json.loads(res)
        assert data["status"] == "error"
        assert data["error"] == "Proofread API crash"


# ============================================================
# 5. propose_smart_cut のテスト
# ============================================================

def test_propose_smart_cut_no_segments():
    res = prod_pipeline.propose_smart_cut(json.dumps([]), "video.mp4")
    data = json.loads(res)
    assert data["status"] == "error"
    assert data["error"] == "No segments provided"

def test_propose_smart_cut_under_target_duration():
    # 目標 2分 (120秒), セグメントの合計時間は 100秒
    segments = [
        {"sourceStart": 0, "sourceEnd": 50, "text": "seg1"},
        {"sourceStart": 50, "sourceEnd": 100, "text": "seg2"}
    ]
    res = prod_pipeline.propose_smart_cut(json.dumps(segments), "video.mp4", target_minutes=2)
    data = json.loads(res)
    assert data["status"] == "success"
    assert len(data["proposals"][0]["segments"]) == 2

def test_propose_smart_cut_over_target_duration():
    # 目標 1分 (60秒), セグメントの合計時間は 120秒 -> サンプリングされる
    segments = [
        {"sourceStart": 0, "sourceEnd": 60, "text": "seg1"},
        {"sourceStart": 60, "sourceEnd": 120, "text": "seg2"}
    ]
    res = prod_pipeline.propose_smart_cut(json.dumps(segments), "video.mp4", target_minutes=1)
    data = json.loads(res)
    assert data["status"] == "success"
    # ratio = 60 / 120 = 0.5 -> len(segments)*0.5 = 1 セグメント
    assert len(data["proposals"][0]["segments"]) == 1

def test_propose_smart_cut_json_decode_error():
    res = prod_pipeline.propose_smart_cut("{invalid", "video.mp4")
    data = json.loads(res)
    assert data["status"] == "error"
    assert "Invalid JSON" in data["error"]

def test_propose_smart_cut_key_error():
    # s.get("sourceEnd", s.get("end", 0)) は KeyError を起こしにくいが、
    # 反復処理の中で KeyError を発生させるダミーオブジェクトを渡す
    class KeyErrorThrower:
        def get(self, key, default=None):
            raise KeyError("missing crucial key")
    
    # json.loads が KeyErrorThrower を含むリストを返すようにモック
    with patch("json.loads", return_value=[KeyErrorThrower()]):
        res = prod_pipeline.propose_smart_cut("[]", "video.mp4")
        data = json.loads(res)
        assert data["status"] == "error"
        assert "Missing key" in data["error"]

def test_propose_smart_cut_generic_exception():
    with patch("json.loads", side_effect=Exception("Generic SmartCut error")):
        res = prod_pipeline.propose_smart_cut("[]", "video.mp4")
        data = json.loads(res)
        assert data["status"] == "error"
        assert data["error"] == "Generic SmartCut error"


# ============================================================
# 6. generate_preview のテスト
# ============================================================

def test_generate_preview_success_vault(tmp_path):
    mock_render = MagicMock(return_value=True)
    dummy_smart = MagicMock()
    dummy_smart.render_smart_cut = mock_render
    
    dummy_editor = MagicMock()
    dummy_io = MagicMock()
    dummy_io.VAULT_OUTPUTS_DIR = tmp_path
    
    modules_mock = {
        'video_editor_engine': dummy_editor,
        'safe_io': dummy_io,
        'smart_cut_engine': dummy_smart
    }
    
    with patch.dict(sys.modules, modules_mock):
        config = {"video_path": "video.mp4", "segments": []}
        res = prod_pipeline.generate_preview(json.dumps(config))
        data = json.loads(res)
        assert data["status"] == "success"
        assert "preview_" in data["preview_path"]

def test_generate_preview_success_fallback(tmp_path):
    mock_render = MagicMock(return_value=True)
    dummy_smart = MagicMock()
    dummy_smart.render_smart_cut = mock_render
    
    dummy_editor = MagicMock()
    
    # safe_io をインポートエラーに
    modules_mock = {
        'video_editor_engine': dummy_editor,
        'safe_io': None,
        'smart_cut_engine': dummy_smart
    }
    
    with patch.dict(sys.modules, modules_mock):
        # output_dir を config で指定しない場合、output/preview になる
        config = {"video_path": "video.mp4", "segments": []}
        res = prod_pipeline.generate_preview(json.dumps(config))
        data = json.loads(res)
        assert data["status"] == "success"
        assert "output/preview" in data["preview_path"].replace("\\", "/")

def test_generate_preview_render_failed(tmp_path):
    mock_render = MagicMock(return_value=False) # レンダリング失敗
    dummy_smart = MagicMock()
    dummy_smart.render_smart_cut = mock_render
    
    dummy_editor = MagicMock()
    dummy_io = MagicMock()
    dummy_io.VAULT_OUTPUTS_DIR = tmp_path
    
    modules_mock = {
        'video_editor_engine': dummy_editor,
        'safe_io': dummy_io,
        'smart_cut_engine': dummy_smart
    }
    
    with patch.dict(sys.modules, modules_mock):
        config = {"video_path": "video.mp4", "segments": []}
        res = prod_pipeline.generate_preview(json.dumps(config))
        data = json.loads(res)
        assert data["status"] == "error"
        assert data["error"] == "Preview generation failed"

def test_generate_preview_import_error():
    with patch.dict(sys.modules, {'video_editor_engine': None}):
        res = prod_pipeline.generate_preview("{}")
        data = json.loads(res)
        assert data["status"] == "error"
        assert "Import failed" in data["error"]

def test_generate_preview_json_decode_error():
    res = prod_pipeline.generate_preview("{invalid")
    data = json.loads(res)
    assert data["status"] == "error"
    assert "Invalid JSON" in data["error"]

def test_generate_preview_file_not_found():
    # render_smart_cut が FileNotFoundError を投げるようにする
    mock_render = MagicMock(side_effect=FileNotFoundError("Target not found"))
    dummy_smart = MagicMock()
    dummy_smart.render_smart_cut = mock_render
    dummy_editor = MagicMock()
    dummy_io = MagicMock()
    dummy_io.VAULT_OUTPUTS_DIR = Path("tmp")
    
    modules_mock = {
        'video_editor_engine': dummy_editor,
        'safe_io': dummy_io,
        'smart_cut_engine': dummy_smart
    }
    
    with patch.dict(sys.modules, modules_mock):
        res = prod_pipeline.generate_preview(json.dumps({"video_path": "a", "segments": []}))
        data = json.loads(res)
        assert data["status"] == "error"
        assert "Not found" in data["error"]

def test_generate_preview_generic_exception():
    mock_render = MagicMock(side_effect=Exception("General rendering error"))
    dummy_smart = MagicMock()
    dummy_smart.render_smart_cut = mock_render
    dummy_editor = MagicMock()
    dummy_io = MagicMock()
    dummy_io.VAULT_OUTPUTS_DIR = Path("tmp")
    
    modules_mock = {
        'video_editor_engine': dummy_editor,
        'safe_io': dummy_io,
        'smart_cut_engine': dummy_smart
    }
    
    with patch.dict(sys.modules, modules_mock):
        res = prod_pipeline.generate_preview(json.dumps({"video_path": "a", "segments": []}))
        data = json.loads(res)
        assert data["status"] == "error"
        assert data["error"] == "General rendering error"


# ============================================================
# 7. check_quality のテスト
# ============================================================

def test_check_quality_success_passed(tmp_path):
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_bytes(b"a" * 2048) # 2KB
    
    config = {"preview_path": str(preview_file)}
    res = prod_pipeline.check_quality(json.dumps(config))
    data = json.loads(res)
    assert data["status"] == "success"
    assert data["score"] == 85
    assert data["passed"] is True
    assert data["rank"] == "B"

def test_check_quality_success_failed_small_size(tmp_path):
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_bytes(b"a" * 500) # 500B < 1KB
    
    config = {"preview_path": str(preview_file)}
    res = prod_pipeline.check_quality(json.dumps(config))
    data = json.loads(res)
    assert data["status"] == "success"
    assert data["score"] == 55 # 85 - 30
    assert data["passed"] is False
    assert data["rank"] == "C"

def test_check_quality_preview_not_found():
    config = {"preview_path": "non_existent_file.mp4"}
    res = prod_pipeline.check_quality(json.dumps(config))
    data = json.loads(res)
    assert data["status"] == "error"
    assert "Preview not found" in data["error"]

def test_check_quality_json_decode_error():
    res = prod_pipeline.check_quality("{invalid")
    data = json.loads(res)
    assert data["status"] == "error"
    assert "Invalid JSON" in data["error"]

def test_check_quality_file_not_found_exception():
    # exists() は True を返すが、stat() で FileNotFoundError を投げるケース
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.stat", side_effect=FileNotFoundError("file disappeared")):
            res = prod_pipeline.check_quality(json.dumps({"preview_path": "a.mp4"}))
            data = json.loads(res)
            assert data["status"] == "error"
            assert "File not found" in data["error"]

def test_check_quality_generic_exception():
    with patch("pathlib.Path.exists", side_effect=Exception("Permission denied")):
        res = prod_pipeline.check_quality(json.dumps({"preview_path": "a.mp4"}))
        data = json.loads(res)
        assert data["status"] == "error"
        assert data["error"] == "Permission denied"


# ============================================================
# 8. render_final のテスト
# ============================================================

def test_render_final_success_vault(tmp_path):
    mock_render = MagicMock(return_value=True)
    dummy_smart = MagicMock()
    dummy_smart.render_smart_cut = mock_render
    
    dummy_editor = MagicMock()
    dummy_io = MagicMock()
    dummy_io.VAULT_OUTPUTS_DIR = tmp_path
    
    modules_mock = {
        'video_editor_engine': dummy_editor,
        'safe_io': dummy_io,
        'smart_cut_engine': dummy_smart
    }
    
    with patch.dict(sys.modules, modules_mock):
        config = {"video_path": "video.mp4", "segments": []}
        res = prod_pipeline.render_final(json.dumps(config))
        data = json.loads(res)
        assert data["status"] == "success"
        assert "final_video.mp4" in data["output_path"].replace("\\", "/")

def test_render_final_success_fallback():
    mock_render = MagicMock(return_value=True)
    dummy_smart = MagicMock()
    dummy_smart.render_smart_cut = mock_render
    dummy_editor = MagicMock()
    
    modules_mock = {
        'video_editor_engine': dummy_editor,
        'safe_io': None,
        'smart_cut_engine': dummy_smart
    }
    
    with patch.dict(sys.modules, modules_mock):
        config = {"video_path": "video.mp4", "segments": []}
        res = prod_pipeline.render_final(json.dumps(config))
        data = json.loads(res)
        assert data["status"] == "success"
        assert "output/final" in data["output_path"].replace("\\", "/")

def test_render_final_render_failed(tmp_path):
    mock_render = MagicMock(return_value=False)
    dummy_smart = MagicMock()
    dummy_smart.render_smart_cut = mock_render
    dummy_editor = MagicMock()
    dummy_io = MagicMock()
    dummy_io.VAULT_OUTPUTS_DIR = tmp_path
    
    modules_mock = {
        'video_editor_engine': dummy_editor,
        'safe_io': dummy_io,
        'smart_cut_engine': dummy_smart
    }
    
    with patch.dict(sys.modules, modules_mock):
        config = {"video_path": "video.mp4", "segments": []}
        res = prod_pipeline.render_final(json.dumps(config))
        data = json.loads(res)
        assert data["status"] == "error"
        assert data["error"] == "Final render failed"

def test_render_final_import_error():
    with patch.dict(sys.modules, {'video_editor_engine': None}):
        res = prod_pipeline.render_final("{}")
        data = json.loads(res)
        assert data["status"] == "error"
        assert "Import failed" in data["error"]

def test_render_final_json_decode_error():
    res = prod_pipeline.render_final("{invalid")
    data = json.loads(res)
    assert data["status"] == "error"
    assert "Invalid JSON" in data["error"]

def test_render_final_file_not_found():
    mock_render = MagicMock(side_effect=FileNotFoundError("Final target path invalid"))
    dummy_smart = MagicMock()
    dummy_smart.render_smart_cut = mock_render
    dummy_editor = MagicMock()
    dummy_io = MagicMock()
    dummy_io.VAULT_OUTPUTS_DIR = Path("tmp")
    
    modules_mock = {
        'video_editor_engine': dummy_editor,
        'safe_io': dummy_io,
        'smart_cut_engine': dummy_smart
    }
    
    with patch.dict(sys.modules, modules_mock):
        res = prod_pipeline.render_final(json.dumps({"video_path": "a", "segments": []}))
        data = json.loads(res)
        assert data["status"] == "error"
        assert "Not found" in data["error"]

def test_render_final_generic_exception():
    mock_render = MagicMock(side_effect=Exception("Final render generic error"))
    dummy_smart = MagicMock()
    dummy_smart.render_smart_cut = mock_render
    dummy_editor = MagicMock()
    dummy_io = MagicMock()
    dummy_io.VAULT_OUTPUTS_DIR = Path("tmp")
    
    modules_mock = {
        'video_editor_engine': dummy_editor,
        'safe_io': dummy_io,
        'smart_cut_engine': dummy_smart
    }
    
    with patch.dict(sys.modules, modules_mock):
        res = prod_pipeline.render_final(json.dumps({"video_path": "a", "segments": []}))
        data = json.loads(res)
        assert data["status"] == "error"
        assert data["error"] == "Final render generic error"


# ============================================================
# 9. generate_youtube_metadata のテスト
# ============================================================

def test_generate_youtube_metadata_success():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "titles": ["title1"],
        "description": "desc",
        "tags": ["tag1"],
        "chapters": []
    })
    mock_client.models.generate_content.return_value = mock_response
    
    dummy_factory = MagicMock()
    dummy_factory.get_gemini_client.return_value = mock_client
    
    dummy_genai = MagicMock()
    
    modules_mock = {
        'gemini_client_factory': dummy_factory,
        'google.genai': dummy_genai
    }
    
    with patch.dict(sys.modules, modules_mock):
        res = prod_pipeline.generate_youtube_metadata("some subtitles")
        data = json.loads(res)
        assert data["status"] == "success"
        assert data["metadata"]["titles"] == ["title1"]

def test_generate_youtube_metadata_import_error():
    with patch.dict(sys.modules, {'gemini_client_factory': None}):
        res = prod_pipeline.generate_youtube_metadata("subtitles")
        data = json.loads(res)
        assert data["status"] == "error"
        assert "Import failed" in data["error"]

def test_generate_youtube_metadata_json_decode_error():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "{invalid json response from gemini"
    mock_client.models.generate_content.return_value = mock_response
    
    dummy_factory = MagicMock()
    dummy_factory.get_gemini_client.return_value = mock_client
    dummy_genai = MagicMock()
    
    modules_mock = {
        'gemini_client_factory': dummy_factory,
        'google.genai': dummy_genai
    }
    
    with patch.dict(sys.modules, modules_mock):
        res = prod_pipeline.generate_youtube_metadata("subtitles")
        data = json.loads(res)
        assert data["status"] == "error"
        assert "Invalid JSON response" in data["error"]

def test_generate_youtube_metadata_generic_exception():
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("API Quota Limit")
    
    dummy_factory = MagicMock()
    dummy_factory.get_gemini_client.return_value = mock_client
    dummy_genai = MagicMock()
    
    modules_mock = {
        'gemini_client_factory': dummy_factory,
        'google.genai': dummy_genai
    }
    
    with patch.dict(sys.modules, modules_mock):
        res = prod_pipeline.generate_youtube_metadata("subtitles")
        data = json.loads(res)
        assert data["status"] == "error"
        assert data["error"] == "API Quota Limit"


# ============================================================
# 10. build_production_pipeline のテスト
# ============================================================

def test_build_production_pipeline_success():
    # adk.agents から必要なエージェントをモック
    dummy_seq = MagicMock()
    dummy_loop = MagicMock()
    
    dummy_adk_agents = MagicMock()
    dummy_adk_agents.SequentialAgent = dummy_seq
    dummy_adk_agents.LoopAgent = dummy_loop
    
    # agents.adk_agent_template.create_agent
    dummy_template = MagicMock()
    dummy_template.create_agent = MagicMock(side_effect=lambda **kwargs: f"Agent_{kwargs.get('name')}")
    
    modules_mock = {
        'google.adk.agents': dummy_adk_agents,
        'agents.adk_agent_template': dummy_template
    }
    
    with patch.dict(sys.modules, modules_mock):
        # _get_verified_facts_context() が何か返すケース
        with patch.object(prod_pipeline, '_get_verified_facts_context', return_value="some verified facts"):
            prod_pipeline.build_production_pipeline()
            dummy_seq.assert_called_once()
            dummy_loop.assert_called_once()

        # _get_verified_facts_context() が空を返すケース
        dummy_seq.reset_mock()
        dummy_loop.reset_mock()
        with patch.object(prod_pipeline, '_get_verified_facts_context', return_value=""):
            prod_pipeline.build_production_pipeline()
            dummy_seq.assert_called_once()
            dummy_loop.assert_called_once()

def test_build_production_pipeline_import_error():
    with patch.dict(sys.modules, {'google.adk.agents': None}):
        with pytest.raises(ImportError):
            prod_pipeline.build_production_pipeline()


# ============================================================
# 11. run_production_pipeline のテスト
# ============================================================

@pytest.mark.asyncio
async def test_run_production_pipeline_success_with_session_id():
    # google.adk.runners, google.adk.agents.run_config, google.genai
    dummy_runners = MagicMock()
    mock_runner_inst = MagicMock()
    
    # Async iterator for runner.run_async
    async def mock_run_async(*args, **kwargs):
        # Yield mock events
        mock_event1 = MagicMock()
        mock_event1.is_final_response.return_value = False
        yield mock_event1
        
        mock_event2 = MagicMock()
        mock_event2.is_final_response.return_value = True
        mock_part = MagicMock()
        mock_part.text = "Pipeline Output Result"
        mock_event2.content.parts = [mock_part]
        yield mock_event2

    mock_runner_inst.run_async = mock_run_async
    dummy_runners.InMemoryRunner.return_value = mock_runner_inst
    
    dummy_run_config = MagicMock()
    dummy_genai_types = MagicMock()
    
    # build_production_pipeline のモック
    mock_pipeline = MagicMock()
    
    modules_mock = {
        'google.adk.runners': dummy_runners,
        'google.adk.agents.run_config': dummy_run_config,
        'google.genai': dummy_genai_types
    }
    
    with patch.dict(sys.modules, modules_mock):
        with patch.object(prod_pipeline, 'build_production_pipeline', return_value=mock_pipeline):
            res = await prod_pipeline.run_production_pipeline("raw_video.mp4", target_minutes=15, session_id="test-session-id")
            assert res["status"] == "success"
            assert res["session_id"] == "test-session-id"
            assert res["result"] == "Pipeline Output Result"

@pytest.mark.asyncio
async def test_run_production_pipeline_success_auto_session_id():
    dummy_runners = MagicMock()
    mock_runner_inst = MagicMock()
    
    async def mock_run_async(*args, **kwargs):
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_part = MagicMock()
        mock_part.text = "Output"
        mock_event.content.parts = [mock_part]
        yield mock_event

    mock_runner_inst.run_async = mock_run_async
    dummy_runners.InMemoryRunner.return_value = mock_runner_inst
    dummy_run_config = MagicMock()
    dummy_genai_types = MagicMock()
    mock_pipeline = MagicMock()
    
    modules_mock = {
        'google.adk.runners': dummy_runners,
        'google.adk.agents.run_config': dummy_run_config,
        'google.genai': dummy_genai_types
    }
    
    with patch.dict(sys.modules, modules_mock):
        with patch.object(prod_pipeline, 'build_production_pipeline', return_value=mock_pipeline):
            res = await prod_pipeline.run_production_pipeline("raw_video.mp4", target_minutes=15)
            assert res["status"] == "success"
            assert res["session_id"] is not None # 自動生成されること

@pytest.mark.asyncio
async def test_run_production_pipeline_import_error():
    with patch.dict(sys.modules, {'google.adk.runners': None}):
        res = await prod_pipeline.run_production_pipeline("video.mp4")
        assert res["status"] == "error"
        assert "google-adk" in res["error"]

@pytest.mark.asyncio
async def test_run_production_pipeline_value_error():
    dummy_runners = MagicMock()
    dummy_runners.InMemoryRunner.side_effect = ValueError("Invalid app_name")
    dummy_run_config = MagicMock()
    dummy_genai_types = MagicMock()
    mock_pipeline = MagicMock()
    
    modules_mock = {
        'google.adk.runners': dummy_runners,
        'google.adk.agents.run_config': dummy_run_config,
        'google.genai': dummy_genai_types
    }
    
    with patch.dict(sys.modules, modules_mock):
        with patch.object(prod_pipeline, 'build_production_pipeline', return_value=mock_pipeline):
            res = await prod_pipeline.run_production_pipeline("video.mp4")
            assert res["status"] == "error"
            assert "Invalid argument" in res["error"]

@pytest.mark.asyncio
async def test_run_production_pipeline_generic_exception():
    dummy_runners = MagicMock()
    dummy_runners.InMemoryRunner.side_effect = Exception("System Crash")
    dummy_run_config = MagicMock()
    dummy_genai_types = MagicMock()
    mock_pipeline = MagicMock()
    
    modules_mock = {
        'google.adk.runners': dummy_runners,
        'google.adk.agents.run_config': dummy_run_config,
        'google.genai': dummy_genai_types
    }
    
    with patch.dict(sys.modules, modules_mock):
        with patch.object(prod_pipeline, 'build_production_pipeline', return_value=mock_pipeline):
            res = await prod_pipeline.run_production_pipeline("video.mp4")
            assert res["status"] == "error"
            assert res["error"] == "System Crash"
