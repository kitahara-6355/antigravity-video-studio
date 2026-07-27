import json
import pytest
import sys
from unittest.mock import patch, MagicMock, AsyncMock
from agents._deprecated.production_pipeline import (
    transcribe_video,
    proofread_subtitles,
    propose_smart_cut,
    generate_preview,
    check_quality,
    render_final,
    generate_youtube_metadata,
    run_production_pipeline,
    build_production_pipeline,
)

def test_transcribe_video_import_error():
    # ImportErrorをシミュレート
    with patch("subtitle_engine.whisper_subprocess.run_whisper_subprocess", side_effect=ImportError("Mocked import error"), create=True):
        res_json = transcribe_video("dummy_path.mp4")
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "Import failed" in res["error"]

def test_transcribe_video_json_decode_error():
    # JSONDecodeErrorをシミュレート
    with patch("subtitle_engine.whisper_subprocess.run_whisper_subprocess", side_effect=json.JSONDecodeError("msg", "doc", 0), create=True):
        res_json = transcribe_video("dummy_path.mp4")
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "JSON decode failed" in res["error"]

def test_transcribe_video_general_exception():
    # 一般のException
    with patch("subtitle_engine.whisper_subprocess.run_whisper_subprocess", side_effect=RuntimeError("Runtime fail"), create=True):
        res_json = transcribe_video("dummy_path.mp4")
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "Runtime fail" in res["error"]


def test_proofread_subtitles_import_error():
    with patch("subtitle_engine.ai_proofreader.proofread_segments", side_effect=ImportError("Mocked proofreader import error"), create=True):
        res_json = proofread_subtitles('[{"text": "hello"}]')
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "Import failed" in res["error"]

def test_proofread_subtitles_json_decode_error():
    res_json = proofread_subtitles('invalid { json')
    res = json.loads(res_json)
    assert res["status"] == "error"
    assert "Invalid JSON" in res["error"]

def test_proofread_subtitles_general_exception():
    with patch("subtitle_engine.ai_proofreader.proofread_segments", side_effect=RuntimeError("Proofread fail"), create=True):
        res_json = proofread_subtitles('[{"text": "hello"}]')
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "Proofread fail" in res["error"]


def test_propose_smart_cut_json_decode_error():
    res_json = propose_smart_cut('invalid { json', "dummy.mp4")
    res = json.loads(res_json)
    assert res["status"] == "error"
    assert "Invalid JSON" in res["error"]

def test_propose_smart_cut_key_error():
    # KeyErrorをシミュレートするため、json.loadsがKeyErrorを投げるように設定
    with patch("json.loads", side_effect=KeyError("Missing key")):
        res_json = propose_smart_cut("[]", "dummy.mp4")
    res = json.loads(res_json)
    assert res["status"] == "error"
    assert "Missing key" in res["error"]

def test_propose_smart_cut_general_exception():
    with patch("json.loads", side_effect=RuntimeError("Unexpected JSON parsing error")):
        res_json = propose_smart_cut("[]", "dummy.mp4")
    res = json.loads(res_json)
    assert res["status"] == "error"
    assert "Unexpected JSON parsing error" in res["error"]


def test_generate_preview_import_error():
    with patch("smart_cut_engine.render_smart_cut", side_effect=ImportError("Mocked render import error"), create=True):
        config = {"video_path": "dummy.mp4", "segments": []}
        res_json = generate_preview(json.dumps(config))
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "Import failed" in res["error"]

def test_generate_preview_json_decode_error():
    res_json = generate_preview("invalid { json")
    res = json.loads(res_json)
    assert res["status"] == "error"
    assert "Invalid JSON" in res["error"]

def test_generate_preview_file_not_found():
    # Path.mkdir で FileNotFoundError を発生させる
    with patch("pathlib.Path.mkdir", side_effect=FileNotFoundError("Directory path is invalid")):
        config = {"video_path": "dummy.mp4", "segments": []}
        res_json = generate_preview(json.dumps(config))
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "Not found" in res["error"]


def test_check_quality_json_decode_error():
    res_json = check_quality("invalid { json")
    res = json.loads(res_json)
    assert res["status"] == "error"
    assert "Invalid JSON" in res["error"]

def test_check_quality_file_not_found():
    # 存在しないプレビューファイルのパスを渡す
    config = {"preview_path": "non_existent_file_path_12345.mp4"}
    res_json = check_quality(json.dumps(config))
    res = json.loads(res_json)
    assert res["status"] == "error"
    assert "Preview not found" in res["error"]

def test_check_quality_general_exception():
    with patch("pathlib.Path.exists", side_effect=RuntimeError("System disk error")):
        config = {"preview_path": "dummy.mp4"}
        res_json = check_quality(json.dumps(config))
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "System disk error" in res["error"]


def test_render_final_import_error():
    with patch("smart_cut_engine.render_smart_cut", side_effect=ImportError("Mocked render import error"), create=True):
        config = {"video_path": "dummy.mp4", "segments": []}
        res_json = render_final(json.dumps(config))
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "Import failed" in res["error"]

def test_render_final_json_decode_error():
    res_json = render_final("invalid { json")
    res = json.loads(res_json)
    assert res["status"] == "error"
    assert "Invalid JSON" in res["error"]

def test_render_final_file_not_found():
    with patch("pathlib.Path.mkdir", side_effect=FileNotFoundError("Final render dir error")):
        config = {"video_path": "dummy.mp4", "segments": []}
        res_json = render_final(json.dumps(config))
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "Not found" in res["error"]


def test_generate_youtube_metadata_import_error():
    with patch("gemini_client_factory.get_gemini_client", side_effect=ImportError("Factory not found"), create=True):
        res_json = generate_youtube_metadata("dummy subtitle text")
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "Import failed" in res["error"]

def test_generate_youtube_metadata_json_decode_error():
    # gemini_client の戻り値が不正な JSON を返すケースをシミュレート
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "invalid json response"
    mock_client.models.generate_content.return_value = mock_response
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client, create=True):
        res_json = generate_youtube_metadata("dummy subtitle text")
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "Invalid JSON response" in res["error"]


@pytest.mark.asyncio
async def test_run_production_pipeline_value_error():
    with patch("agents._deprecated.production_pipeline.build_production_pipeline", side_effect=ValueError("Invalid config parameter")):
        res = await run_production_pipeline("dummy.mp4", target_minutes=-10)
        assert res["status"] == "error"
        assert "Invalid argument" in res["error"]

@pytest.mark.asyncio
async def test_run_production_pipeline_general_exception():
    with patch("agents._deprecated.production_pipeline.build_production_pipeline", side_effect=RuntimeError("Pipeline build crash")):
        res = await run_production_pipeline("dummy.mp4")
        assert res["status"] == "error"
        assert "Pipeline build crash" in res["error"]

def test_build_production_pipeline_success():
    try:
        pipeline = build_production_pipeline()
        assert pipeline is not None
        assert pipeline.name == "ProductionPipeline"
    except Exception as e:
        # 環境によって ADK のロードに失敗した場合はスキップするか、または失敗にする。
        # ここでは環境が整っているはずなので、エラーが起きないことを確認する。
        import pytest
        pytest.fail(f"build_production_pipeline failed: {e}")

# ============================================================
# 新規カバレッジ100%達成用テストケース
# ============================================================

def test_transcribe_video_success():
    mock_result = {
        "status": "success",
        "segments": [{"text": "こんにちは", "start": 0.0, "end": 1.0}]
    }
    with patch("subtitle_engine.whisper_subprocess.run_whisper_subprocess", return_value=mock_result, create=True):
        res_json = transcribe_video("dummy_path.mp4")
        res = json.loads(res_json)
        assert res["status"] == "success"
        assert res["segments_count"] == 1
        assert res["segments"][0]["text"] == "こんにちは"

def test_transcribe_video_status_error():
    mock_result = {
        "status": "failed",
        "error": "Whisper execution failed"
    }
    with patch("subtitle_engine.whisper_subprocess.run_whisper_subprocess", return_value=mock_result, create=True):
        res_json = transcribe_video("dummy_path.mp4")
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "Whisper execution failed" in res["error"]

def test_proofread_subtitles_success():
    mock_corrected = [{"text": "こんにちは（修正済）"}]
    with patch("subtitle_engine.ai_proofreader.proofread_segments", return_value=mock_corrected, create=True):
        res_json = proofread_subtitles(json.dumps({"segments": [{"text": "こんにちは"}]}))
        res = json.loads(res_json)
        assert res["status"] == "success"
        assert res["segments"][0]["text"] == "こんにちは（修正済）"

def test_propose_smart_cut_within_limit():
    segments = [{"start": 0, "end": 10, "sourceStart": 0, "sourceEnd": 10}]
    res_json = propose_smart_cut(json.dumps(segments), "dummy.mp4", target_minutes=1)
    res = json.loads(res_json)
    assert res["status"] == "success"
    assert len(res["proposals"]) == 1
    assert len(res["proposals"][0]["segments"]) == 1

def test_propose_smart_cut_exceeds_limit():
    segments = [
        {"start": 0, "end": 60, "sourceStart": 0, "sourceEnd": 60},
        {"start": 60, "end": 120, "sourceStart": 60, "sourceEnd": 120},
    ]
    res_json = propose_smart_cut(json.dumps(segments), "dummy.mp4", target_minutes=1)
    res = json.loads(res_json)
    assert res["status"] == "success"
    assert len(res["proposals"][0]["segments"]) == 1

def test_propose_smart_cut_empty_segments():
    res_json = propose_smart_cut("[]", "dummy.mp4")
    res = json.loads(res_json)
    assert res["status"] == "error"
    assert "No segments provided" in res["error"]

def test_generate_preview_success():
    with patch("smart_cut_engine.render_smart_cut", return_value=True, create=True):
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            config = {"video_path": "dummy.mp4", "segments": [], "output_dir": "test_output"}
            res_json = generate_preview(json.dumps(config))
            res = json.loads(res_json)
            assert res["status"] == "success"
            assert "preview_" in res["preview_path"]

def test_generate_preview_failed():
    with patch("smart_cut_engine.render_smart_cut", return_value=False, create=True):
        with patch("pathlib.Path.mkdir"):
            config = {"video_path": "dummy.mp4", "segments": []}
            res_json = generate_preview(json.dumps(config))
            res = json.loads(res_json)
            assert res["status"] == "error"
            assert "failed" in res["error"]

def test_generate_preview_general_exception():
    with patch("pathlib.Path.mkdir", side_effect=RuntimeError("System disk error")):
        config = {"video_path": "dummy.mp4", "segments": []}
        res_json = generate_preview(json.dumps(config))
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "System disk error" in res["error"]

def test_check_quality_success_ranks():
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 2048
            config = {"preview_path": "dummy.mp4"}
            res_json = check_quality(json.dumps(config))
            res = json.loads(res_json)
            assert res["status"] == "success"
            assert res["score"] == 85
            assert res["rank"] == "B"
            assert res["passed"] is True

def test_check_quality_low_size():
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 500
            config = {"preview_path": "dummy.mp4"}
            res_json = check_quality(json.dumps(config))
            res = json.loads(res_json)
            assert res["status"] == "success"
            assert res["score"] == 55
            assert res["rank"] == "C"
            assert res["passed"] is False
            assert "ファイルサイズが異常に小さい" in res["feedback"][0]

def test_check_quality_file_not_found_exception():
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.stat", side_effect=FileNotFoundError("Mocked file not found")):
            config = {"preview_path": "dummy.mp4"}
            res_json = check_quality(json.dumps(config))
            res = json.loads(res_json)
            assert res["status"] == "error"
            assert "File not found" in res["error"]

def test_render_final_success():
    with patch("smart_cut_engine.render_smart_cut", return_value=True, create=True):
        with patch("pathlib.Path.mkdir"):
            config = {"video_path": "dummy.mp4", "segments": []}
            res_json = render_final(json.dumps(config))
            res = json.loads(res_json)
            assert res["status"] == "success"
            assert "final_video.mp4" in res["output_path"]
            assert res["requires_approval"] is True

def test_render_final_failed():
    with patch("smart_cut_engine.render_smart_cut", return_value=False, create=True):
        with patch("pathlib.Path.mkdir"):
            config = {"video_path": "dummy.mp4", "segments": []}
            res_json = render_final(json.dumps(config))
            res = json.loads(res_json)
            assert res["status"] == "error"
            assert "failed" in res["error"]

def test_render_final_general_exception():
    with patch("pathlib.Path.mkdir", side_effect=RuntimeError("System disk error")):
        config = {"video_path": "dummy.mp4", "segments": []}
        res_json = render_final(json.dumps(config))
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "System disk error" in res["error"]

def test_generate_youtube_metadata_success():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "titles": ["Title 1", "Title 2"],
        "description": "Desc #tag",
        "tags": ["Tag A", "Tag B"],
        "chapters": [{"time": "0:00", "title": "Intro"}]
    })
    mock_client.models.generate_content.return_value = mock_response
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client, create=True):
        res_json = generate_youtube_metadata("dummy text")
        res = json.loads(res_json)
        assert res["status"] == "success"
        metadata = res["metadata"]
        assert len(metadata["titles"]) == 2
        assert metadata["description"] == "Desc #tag"

def test_generate_youtube_metadata_general_exception():
    with patch("gemini_client_factory.get_gemini_client", side_effect=RuntimeError("Gemini client creation error"), create=True):
        res_json = generate_youtube_metadata("dummy text")
        res = json.loads(res_json)
        assert res["status"] == "error"
        assert "Gemini client creation error" in res["error"]

def test_wrap_tool_no_self_healing():
    with patch("agents._deprecated.production_pipeline._SELF_HEALING_AVAILABLE", False):
        def dummy(): pass
        from agents._deprecated.production_pipeline import _wrap_tool
        assert _wrap_tool(dummy) == dummy

def test_wrap_tool_with_self_healing_meta_handling():
    class MockWrapped:
        pass
    mock_wrapped = MockWrapped()
    with patch("agents._deprecated.production_pipeline._SELF_HEALING_AVAILABLE", True), \
         patch("agents.self_healing_tool.self_healing.wrap", return_value=mock_wrapped):
        def dummy_func():
            """Some doc"""
            pass
        from agents._deprecated.production_pipeline import _wrap_tool
        wrapped = _wrap_tool(dummy_func)
        assert wrapped.__name__ == "dummy_func"
        assert wrapped.__doc__ == "Some doc"

def test_get_verified_facts_context_exception():
    with patch("agents.memory.verified_facts.verified_facts_store.get_facts_for_context", side_effect=Exception("Facts error")):
        from agents._deprecated.production_pipeline import _get_verified_facts_context
        assert _get_verified_facts_context() == ""

def test_build_production_pipeline_no_facts():
    with patch("agents._deprecated.production_pipeline._get_verified_facts_context", return_value=""):
        pipeline = build_production_pipeline()
        assert pipeline is not None

def test_build_production_pipeline_import_error():
    import sys
    with patch.dict(sys.modules, {'google.adk.agents': None}):
        with pytest.raises(ImportError):
            build_production_pipeline()

def test_generate_preview_import_error_vault_outputs():
    import sys
    with patch.dict(sys.modules, {'safe_io': None}):
        with patch("smart_cut_engine.render_smart_cut", return_value=True, create=True):
            config = {"video_path": "dummy.mp4", "segments": []}
            with patch("pathlib.Path.mkdir"):
                res_json = generate_preview(json.dumps(config))
                res = json.loads(res_json)
                assert res["status"] == "success"
                assert "output/preview" in res["preview_path"] or "output\\preview" in res["preview_path"]

def test_render_final_import_error_vault_outputs():
    import sys
    with patch.dict(sys.modules, {'safe_io': None}):
        with patch("smart_cut_engine.render_smart_cut", return_value=True, create=True):
            config = {"video_path": "dummy.mp4", "segments": []}
            with patch("pathlib.Path.mkdir"):
                res_json = render_final(json.dumps(config))
                res = json.loads(res_json)
                assert res["status"] == "success"
                assert "output/final/final_video.mp4" in res["output_path"] or "output\\final\\final_video.mp4" in res["output_path"]

def test_import_production_pipeline_without_self_healing():
    orig_self_healing = sys.modules.get('agents.self_healing_tool')
    orig_pipeline = sys.modules.get('agents._deprecated.production_pipeline')
    try:
        sys.modules['agents.self_healing_tool'] = None
        if 'agents._deprecated.production_pipeline' in sys.modules:
            del sys.modules['agents._deprecated.production_pipeline']
        import agents._deprecated.production_pipeline as pp
        assert pp._SELF_HEALING_AVAILABLE is False
    finally:
        if orig_self_healing is not None:
            sys.modules['agents.self_healing_tool'] = orig_self_healing
        elif 'agents.self_healing_tool' in sys.modules:
            del sys.modules['agents.self_healing_tool']
            
        if orig_pipeline is not None:
            sys.modules['agents._deprecated.production_pipeline'] = orig_pipeline
        elif 'agents._deprecated.production_pipeline' in sys.modules:
            del sys.modules['agents._deprecated.production_pipeline']

@pytest.mark.asyncio
async def test_run_production_pipeline_success():
    mock_runner = MagicMock()
    mock_session = MagicMock()
    mock_runner.session_service.create_session = AsyncMock()
    
    async def mock_run_async(*args, **kwargs):
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_event.content.parts = [MagicMock(text="Pipeline output result text")]
        yield mock_event
        
    mock_runner.run_async = mock_run_async
    
    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner, create=True), \
         patch("google.adk.agents.run_config.RunConfig", create=True), \
         patch("google.genai.types", create=True), \
         patch("agents._deprecated.production_pipeline.build_production_pipeline") as mock_build:
        
        mock_build.return_value = MagicMock()
        
        res = await run_production_pipeline("dummy.mp4", target_minutes=20, session_id="test-session")
        assert res["status"] == "success"
        assert res["session_id"] == "test-session"
        assert "Pipeline output result text" in res["result"]

@pytest.mark.asyncio
async def test_run_production_pipeline_import_error():
    import sys
    with patch.dict(sys.modules, {'google.adk.runners': None}):
        res = await run_production_pipeline("dummy.mp4")
        assert res["status"] == "error"
        assert "NoneType" in res["error"] or "google" in res["error"] or "import" in res["error"]
