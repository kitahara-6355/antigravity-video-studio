import pytest
import uuid
from unittest.mock import MagicMock, patch, AsyncMock
import json
from pathlib import Path

from agents.pipeline_types import Segment, PipelineContext, StageResult
from harness.tool_registry import tool_registry
from harness.pipeline_tools import register_pipeline_tools
from harness.session_manager import session_manager, SessionState

@pytest.fixture(autouse=True)
def clean_registry():
    """テストごとにレジストリをクリアして pipeline_tools の登録を行う"""
    original_tools = tool_registry._tools.copy()
    tool_registry._tools.clear()
    
    # 登録実行
    register_pipeline_tools()
    
    yield
    tool_registry._tools = original_tools

@pytest.fixture
def mock_sessions(tmp_path, monkeypatch):
    """セッションの保存先を一時ディレクトリに変更し、アクティブセッションをリセット"""
    import sys
    # 最新の session_manager インスタンスを sys.modules から取得
    sm_module = sys.modules.get("harness.session_manager")
    if sm_module is not None:
        sm = sm_module.session_manager
    else:
        from harness.session_manager import session_manager as sm
    
    monkeypatch.setattr(sm, "_session_dir", tmp_path)
    monkeypatch.setattr(sm, "_active_sessions", {})
    return sm

@pytest.fixture
def mock_workers():
    """pipeline_coordinator の各 Worker をモック化"""
    with patch("agents.pipeline_coordinator.TranscribeWorker") as m_transcribe, \
         patch("agents.pipeline_coordinator.ProofreadWorker") as m_proofread, \
         patch("agents.pipeline_coordinator.SmartCutWorker") as m_smartcut, \
         patch("agents.pipeline_coordinator.PreviewWorker") as m_preview, \
         patch("agents.pipeline_coordinator.YouTubeOptWorker") as m_youtube, \
         patch("agents.pipeline_coordinator.QualityGateWorker") as m_quality, \
         patch("agents.pipeline_coordinator.RenderWorker") as m_render:
         
         # 各モックインスタンスの execute メソッドを AsyncMock に設定する
         m_transcribe.return_value.execute = AsyncMock()
         m_proofread.return_value.execute = AsyncMock()
         m_smartcut.return_value.execute = AsyncMock()
         m_preview.return_value.execute = AsyncMock()
         m_youtube.return_value.execute = AsyncMock()
         m_quality.return_value.execute = AsyncMock()
         m_render.return_value.execute = AsyncMock()
         
         yield {
             "transcribe": m_transcribe,
             "proofread": m_proofread,
             "smartcut": m_smartcut,
             "preview": m_preview,
             "youtube": m_youtube,
             "quality": m_quality,
             "render": m_render,
         }


# ===========================================================================
# Test 1: ツール登録の検証
# ===========================================================================
def test_tools_registered():
    """全8ツールが正しく tool_registry に登録されていることを検証"""
    expected_tools = {
        "transcribe_video",
        "proofread_subtitles",
        "propose_smart_cut",
        "generate_preview",
        "optimize_youtube",
        "check_quality",
        "render_final",
        "cleanup_intermediates",
    }
    registered_tools = set(tool_registry._tools.keys())
    assert expected_tools.issubset(registered_tools)


# ===========================================================================
# Test 2: _get_or_create_context / _save_context の各種分岐検証
# ===========================================================================
@pytest.mark.asyncio
async def test_session_resume_and_fallback(mock_sessions, mock_workers):
    """session_id が指定されてセッションを再開するケースを検証"""
    # 既存セッションをダミーで作成
    session_id = "test-session-123"
    video_path = str(Path(f"/dummy/path/video_{uuid.uuid4()}.mp4").resolve())
    session = mock_sessions.create_session(video_path=video_path, session_id=session_id)
    
    # transcribe_video ツールを呼び出して、セッションレジューム処理を通す
    mock_workers["transcribe"].return_value.execute.return_value = StageResult(
        stage_name="transcribe", success=True, detail="success", data={"segment_count": 0}, duration_seconds=1.0
    )
    
    res = await tool_registry.execute("transcribe_video", {"video_path": video_path, "session_id": session_id})
    assert res.is_error is False
    
    # セッションレジュームが機能したことを確認する
    assert session_id in mock_sessions._active_sessions

@pytest.mark.asyncio
async def test_session_resume_by_video_path(mock_sessions, mock_workers):
    """session_id は指定しないが、video_path が一致するアクティブセッションから再利用するケースを検証"""
    video_path = str(Path(f"/dummy/path/video_{uuid.uuid4()}.mp4").resolve())
    # セッションを作成しておく
    session = mock_sessions.create_session(video_path=video_path, session_id="session-path-matching")
    
    mock_workers["transcribe"].return_value.execute.return_value = StageResult(
        stage_name="transcribe", success=True, detail="success", data={"segment_count": 0}, duration_seconds=1.0
    )
    
    # session_id を空のまま呼び出す
    res = await tool_registry.execute("transcribe_video", {"video_path": video_path, "session_id": ""})
    assert res.is_error is False
    
    # session-path-matching が再利用され、新規セッションが作成されていないことを確認
    # _active_sessions には1つしかセッションがないはず
    assert len(mock_sessions._active_sessions) == 1

@pytest.mark.asyncio
async def test_session_creation_when_not_found(mock_sessions, mock_workers):
    """セッションが見つからない場合に、新規セッションが自動生成されるケースを検証"""
    video_path = str(Path("/dummy/path/new_video.mp4").resolve())
    
    mock_workers["transcribe"].return_value.execute.return_value = StageResult(
        stage_name="transcribe", success=True, detail="success", data={"segment_count": 0}, duration_seconds=1.0
    )
    
    res = await tool_registry.execute("transcribe_video", {"video_path": video_path})
    assert res.is_error is False
    
    # 新規セッションが作られていることを確認
    assert len(mock_sessions._active_sessions) == 1

@pytest.mark.asyncio
async def test_metadata_deserialization_and_args_override(mock_sessions, mock_workers):
    """session.metadata から状態が復元され、args の引数で正しく上書きされるケースを検証"""
    video_path = str(Path(f"/dummy/path/video_{uuid.uuid4()}.mp4").resolve())
    
    # 既存セッションのメタデータに情報を追加
    metadata = {
        "segments": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
        "selected_segments": [{"start": 0.0, "end": 1.0, "text": "Hello Selected"}],
        "preview_path": "/dummy/preview.mp4",
        "final_path": "/dummy/final.mp4",
        "quality_score": 85,
        "metadata": {"title": "Test Title"}
    }
    session = mock_sessions.create_session(video_path=video_path, session_id="override-session", metadata=metadata)
    
    # Worker の挙動設定
    mock_workers["proofread"].return_value.execute.return_value = StageResult(
        stage_name="proofread", success=True, detail="success", data={}, duration_seconds=0.5
    )
    
    # args を用いて segments / selected_segments / preview_path / metadata を上書き・マージするテスト
    # args["segments"] / args["selected_segments"] に dict と Segment の混合、args["metadata"] に差分を設定
    test_segments = [
        {"start": 1.0, "end": 2.0, "text": "World (dict)"},
        Segment(start=2.0, end=3.0, text="Segment (object)")
    ]
    test_selected = [
        {"start": 1.0, "end": 2.0, "text": "Selected (dict)"},
        Segment(start=2.0, end=3.0, text="Selected (object)")
    ]
    
    res = await tool_registry.execute("proofread_subtitles", {
        "video_path": video_path,
        "session_id": "override-session",
        "segments": test_segments,
        "selected_segments": test_selected,
        "preview_path": "/dummy/new_preview.mp4",
        "metadata": {"tags": ["new-tag"]}
    })
    
    assert res.is_error is False
    
    # 保存されたセッションの metadata を確認
    updated_session = mock_sessions.get_session("override-session")
    
    # segments が正しくマージされ、serialize_segment を経て dict 保存されていること
    saved_segments = updated_session.metadata["segments"]
    assert len(saved_segments) == 2
    assert saved_segments[0]["text"] == "World (dict)"
    assert saved_segments[1]["text"] == "Segment (object)"
    
    saved_selected = updated_session.metadata["selected_segments"]
    assert len(saved_selected) == 2
    assert saved_selected[0]["text"] == "Selected (dict)"
    assert saved_selected[1]["text"] == "Selected (object)"
    
    # preview_path は上書きされていること
    assert updated_session.metadata["preview_path"] == "/dummy/new_preview.mp4"
    # metadata がマージ (update) されていること
    assert updated_session.metadata["metadata"]["title"] == "Test Title"
    assert updated_session.metadata["metadata"]["tags"] == ["new-tag"]


@pytest.mark.asyncio
async def test_serialize_segment_edge_cases(mock_sessions, mock_workers):
    """serialize_segment で dict や、to_dictを持たないオブジェクトが渡されたケースを検証"""
    video_path = str(Path(f"/dummy/path/video_{uuid.uuid4()}.mp4").resolve())
    session_id = "edge-case-session"
    
    # Worker.execute 内で ctx.segments に直接 dict や文字列を混入させる
    async def custom_execute(ctx):
        ctx.segments.append({"start": 5.0, "end": 6.0, "text": "raw dict"}) # 111行目を通す
        ctx.segments.append("raw string") # 114行目を通す
        return StageResult(stage_name="transcribe", success=True, detail="success", data={}, duration_seconds=1.0)
        
    mock_workers["transcribe"].return_value.execute = custom_execute
    
    res = await tool_registry.execute("transcribe_video", {"video_path": video_path, "session_id": session_id})
    assert res.is_error is False
    
    # 保存されたセッションの metadata を確認
    updated_session = mock_sessions.get_session(session_id)
    saved_segments = updated_session.metadata["segments"]
    assert len(saved_segments) == 2
    assert saved_segments[0] == {"start": 5.0, "end": 6.0, "text": "raw dict"}
    assert saved_segments[1] == "raw string"


# ===========================================================================
# Test 3: 各ツールの実行処理と結果処理の検証 (成功/失敗)
# ===========================================================================
@pytest.mark.asyncio
async def test_transcribe_video_tool(mock_sessions, mock_workers):
    """transcribe_video ツールの成功および失敗のケースを検証"""
    video_path = str(Path(f"/dummy/path/video_{uuid.uuid4()}.mp4").resolve())
    
    # 1. 成功ケース
    mock_workers["transcribe"].return_value.execute.return_value = StageResult(
        stage_name="transcribe", success=True, detail="success", data={"segment_count": 5}, duration_seconds=1.2
    )
    
    res = await tool_registry.execute("transcribe_video", {"video_path": video_path, "target_minutes": 15})
    assert res.is_error is False
    data = json.loads(res.content[0]["text"])
    assert data["success"] is True
    assert data["segment_count"] == 5
    assert data["duration_seconds"] == 1.2

    # 2. 失敗ケース
    mock_workers["transcribe"].return_value.execute.return_value = StageResult(
        stage_name="transcribe", success=False, detail="failed parsing", data={}, duration_seconds=0.8
    )
    
    res_fail = await tool_registry.execute("transcribe_video", {"video_path": video_path})
    assert res_fail.is_error is True
    data_fail = json.loads(res_fail.content[0]["text"])
    assert data_fail["success"] is False
    assert data_fail["detail"] == "failed parsing"


@pytest.mark.asyncio
async def test_proofread_subtitles_tool(mock_sessions, mock_workers):
    """proofread_subtitles ツールの成功および失敗のケースを検証"""
    video_path = str(Path(f"/dummy/path/video_{uuid.uuid4()}.mp4").resolve())
    
    # 成功ケース
    mock_workers["proofread"].return_value.execute.return_value = StageResult(
        stage_name="proofread", success=True, detail="proofread success", data={"corrections_count": 3}, duration_seconds=0.9
    )
    res = await tool_registry.execute("proofread_subtitles", {"video_path": video_path})
    assert res.is_error is False
    data = json.loads(res.content[0]["text"])
    assert data["success"] is True
    assert data["corrections"] == {"corrections_count": 3}

    # 失敗ケース
    mock_workers["proofread"].return_value.execute.return_value = StageResult(
        stage_name="proofread", success=False, detail="api error", data={}, duration_seconds=0.5
    )
    res_fail = await tool_registry.execute("proofread_subtitles", {"video_path": video_path})
    assert res_fail.is_error is True


@pytest.mark.asyncio
async def test_propose_smart_cut_tool(mock_sessions, mock_workers):
    """propose_smart_cut ツールの成功および失敗のケースを検証"""
    video_path = str(Path(f"/dummy/path/video_{uuid.uuid4()}.mp4").resolve())
    
    # 成功ケース
    mock_workers["smartcut"].return_value.execute.return_value = StageResult(
        stage_name="smartcut", success=True, detail="smartcut success", data={"estimated_duration": 600}, duration_seconds=1.5
    )
    res = await tool_registry.execute("propose_smart_cut", {"video_path": video_path, "target_minutes": 10})
    assert res.is_error is False
    data = json.loads(res.content[0]["text"])
    assert data["success"] is True
    assert data["data"] == {"estimated_duration": 600}

    # 失敗ケース
    mock_workers["smartcut"].return_value.execute.return_value = StageResult(
        stage_name="smartcut", success=False, detail="smartcut failed", data={}, duration_seconds=0.4
    )
    res_fail = await tool_registry.execute("propose_smart_cut", {"video_path": video_path})
    assert res_fail.is_error is True


@pytest.mark.asyncio
async def test_generate_preview_tool(mock_sessions, mock_workers):
    """generate_preview ツールの成功および失敗のケースを検証"""
    video_path = str(Path(f"/dummy/path/video_{uuid.uuid4()}.mp4").resolve())
    
    # 成功ケース
    mock_workers["preview"].return_value.execute.return_value = StageResult(
        stage_name="preview", success=True, detail="preview generated", data={"size_mb": 15.5}, duration_seconds=4.5
    )
    res = await tool_registry.execute("generate_preview", {"video_path": video_path})
    assert res.is_error is False
    data = json.loads(res.content[0]["text"])
    assert data["success"] is True
    assert data["data"] == {"size_mb": 15.5}

    # 失敗ケース
    mock_workers["preview"].return_value.execute.return_value = StageResult(
        stage_name="preview", success=False, detail="ffmpeg failure", data={}, duration_seconds=1.0
    )
    res_fail = await tool_registry.execute("generate_preview", {"video_path": video_path})
    assert res_fail.is_error is True


@pytest.mark.asyncio
async def test_optimize_youtube_tool(mock_sessions, mock_workers):
    """optimize_youtube ツールの成功および失敗のケースを検証"""
    video_path = str(Path(f"/dummy/path/video_{uuid.uuid4()}.mp4").resolve())
    
    # 成功ケース
    mock_workers["youtube"].return_value.execute.return_value = StageResult(
        stage_name="youtube", success=True, detail="optimized", data={}, duration_seconds=0.8
    )
    res = await tool_registry.execute("optimize_youtube", {"video_path": video_path})
    assert res.is_error is False
    data = json.loads(res.content[0]["text"])
    assert data["success"] is True

    # 失敗ケース
    mock_workers["youtube"].return_value.execute.return_value = StageResult(
        stage_name="youtube", success=False, detail="api quota error", data={}, duration_seconds=0.3
    )
    res_fail = await tool_registry.execute("optimize_youtube", {"video_path": video_path})
    assert res_fail.is_error is True


@pytest.mark.asyncio
async def test_check_quality_tool(mock_sessions, mock_workers):
    """check_quality ツールの成功および失敗のケースを検証"""
    video_path = str(Path(f"/dummy/path/video_{uuid.uuid4()}.mp4").resolve())
    preview_path = str(Path(f"/dummy/path/preview_{uuid.uuid4()}.mp4").resolve())
    
    # 成功ケース
    mock_workers["quality"].return_value.execute.return_value = StageResult(
        stage_name="quality", success=True, detail="checked", data={
            "score": 95,
            "rank": "S",
            "feedback": ["Great quality"],
            "category_scores": {"audio": 95}
        }, duration_seconds=0.9
    )
    res = await tool_registry.execute("check_quality", {"video_path": video_path, "preview_path": preview_path})
    assert res.is_error is False
    data = json.loads(res.content[0]["text"])
    assert data["success"] is True
    assert data["score"] == 95
    assert data["rank"] == "S"
    assert data["feedback"] == ["Great quality"]

    # 失敗ケース
    mock_workers["quality"].return_value.execute.return_value = StageResult(
        stage_name="quality", success=False, detail="quality gate error", data={}, duration_seconds=0.3
    )
    res_fail = await tool_registry.execute("check_quality", {"video_path": video_path, "preview_path": preview_path})
    assert res_fail.is_error is True


@pytest.mark.asyncio
async def test_render_final_tool(mock_sessions, mock_workers):
    """render_final ツールの成功および失敗のケースを検証"""
    video_path = str(Path(f"/dummy/path/video_{uuid.uuid4()}.mp4").resolve())
    preview_path = str(Path(f"/dummy/path/preview_{uuid.uuid4()}.mp4").resolve())
    
    # 成功ケース
    mock_workers["render"].return_value.execute.return_value = StageResult(
        stage_name="render", success=True, detail="rendered", data={"size_mb": 150.0}, duration_seconds=10.0
    )
    res = await tool_registry.execute("render_final", {"video_path": video_path, "preview_path": preview_path})
    assert res.is_error is False
    data = json.loads(res.content[0]["text"])
    assert data["success"] is True
    assert data["duration_seconds"] == 10.0

    # 失敗ケース
    mock_workers["render"].return_value.execute.return_value = StageResult(
        stage_name="render", success=False, detail="render failed", data={}, duration_seconds=2.0
    )
    res_fail = await tool_registry.execute("render_final", {"video_path": video_path, "preview_path": preview_path})
    assert res_fail.is_error is True


# ===========================================================================
# Test 4: cleanup_intermediates ツールの検証
# ===========================================================================
@pytest.mark.asyncio
async def test_cleanup_intermediates_tool():
    """cleanup_intermediates ツールの呼び出しと出力を検証"""
    with patch("disk_manager.cleanup_intermediates", return_value=12.5) as mock_cleanup, \
         patch("disk_manager.get_free_gb", return_value=150.0) as mock_free:
         
         res = await tool_registry.execute("cleanup_intermediates", {"keep_latest": 3, "dry_run": True})
         assert res.is_error is False
         
         mock_cleanup.assert_called_once_with(keep_latest=3, dry_run=True)
         mock_free.assert_called_once()
         
         data = json.loads(res.content[0]["text"])
         assert data["action"] == "削除予定"
         assert data["freed_gb"] == 12.5
         assert data["free_gb"] == 150.0
         
         # dry_run = False の場合の挙動検証
         mock_cleanup.reset_mock()
         res_run = await tool_registry.execute("cleanup_intermediates", {"keep_latest": 1, "dry_run": False})
         assert res_run.is_error is False
         data_run = json.loads(res_run.content[0]["text"])
         assert data_run["action"] == "削除済み"


@pytest.mark.asyncio
async def test_transcribe_video_tool_failure_does_not_save_context(mock_sessions, mock_workers):
    """transcribe_video ツールが失敗したとき、_save_context が呼ばれないことを検証"""
    video_path = str(Path(f"/dummy/path/video_{uuid.uuid4()}.mp4").resolve())
    session_id = "fail-no-save-session"
    
    session = mock_sessions.create_session(video_path=video_path, session_id=session_id)
    assert "segments" not in session.metadata

    mock_workers["transcribe"].return_value.execute.return_value = StageResult(
        stage_name="transcribe", success=False, detail="failed parsing", data={}, duration_seconds=0.8
    )
    
    res = await tool_registry.execute("transcribe_video", {
        "video_path": video_path, 
        "session_id": session_id,
        "segments": [{"start": 0.0, "end": 1.0, "text": "Dummy"}]
    })
    assert res.is_error is True
    
    updated_session = mock_sessions.get_session(session_id)
    assert "segments" not in updated_session.metadata
