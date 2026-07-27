import pytest
import sys
import json
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import os

# backend の絶対パスを追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents._deprecated.adk_bridge import (
    create_adk_tool_from_registry,
    _build_annotations,
    build_harness_pipeline,
    run_harness_pipeline
)

@pytest.mark.asyncio
async def test_build_annotations():
    # 各種型のアノテーション変換テスト
    input_schema = {
        "arg1": {"type": str},
        "arg2": int,
        "arg3": float,
        "arg4": bool,
        "arg5": list,
        "arg6": dict,
        "arg7": "unknown",  # strにマッピングされるはず
    }
    annotations = _build_annotations(input_schema)
    assert annotations["arg1"] == str
    assert annotations["arg2"] == int
    assert annotations["arg3"] == float
    assert annotations["arg4"] == bool
    assert annotations["arg5"] == list
    assert annotations["arg6"] == dict
    assert annotations["arg7"] == str
    assert annotations["return"] == str

@pytest.mark.asyncio
async def test_create_adk_tool_unregistered():
    # 未登録のツールを指定した場合に ValueError が送出されること
    with patch("harness.tool_registry.tool_registry.get_tool", return_value=None):
        with pytest.raises(ValueError, match="ToolRegistry にツール 'non_existent' が未登録"):
            create_adk_tool_from_registry("non_existent")

@pytest.mark.asyncio
async def test_create_adk_tool_flow_success():
    # 正常系フローのテスト
    mock_tool = MagicMock()
    mock_tool.description = "Test Description"
    mock_schema = {"param1": {"type": str}}
    mock_tool.input_schema = mock_schema

    with patch("harness.tool_registry.tool_registry.get_tool", return_value=mock_tool):
        wrapper = create_adk_tool_from_registry("test_tool", "test_scope")
        assert wrapper.__name__ == "test_tool"
        assert wrapper.__doc__ == "Test Description"
        assert wrapper.__annotations__["param1"] == str

        with patch("harness.hooks.hook_system.fire", new_callable=AsyncMock) as mock_hook_fire, \
             patch("harness.governance.governance_engine.check_permission", return_value=True) as mock_gov_check, \
             patch("harness.governance.governance_engine.start_span", return_value="span-123") as mock_start_span, \
             patch("harness.governance.governance_engine.end_span") as mock_end_span, \
             patch("harness.tool_registry.tool_registry.execute", new_callable=AsyncMock) as mock_exec, \
             patch("harness.session_manager.session_manager.record_tool_call") as mock_record:

            mock_result = MagicMock()
            mock_result.is_error = False
            mock_result.content = [{"text": "success_result"}]
            mock_exec.return_value = mock_result

            mock_pre_output = MagicMock()
            mock_pre_output.permission_decision = "allow"
            mock_pre_output.updated_input = None
            mock_hook_fire.return_value = mock_pre_output

            res = await wrapper(param1="val", _session_id="session-456")
            assert res == "success_result"
            mock_exec.assert_called_with("test_tool", {"param1": "val"})
            mock_record.assert_called_once_with("session-456", "test_tool", {"param1": "val"}, [{"text": "success_result"}], pytest.approx(0.1, abs=0.5))
            mock_end_span.assert_called_with("span-123", status="ok")

@pytest.mark.asyncio
async def test_create_adk_tool_flow_hook_deny():
    # Hookにより実行拒否されるケース
    mock_tool = MagicMock()
    mock_tool.description = "Test Description"
    mock_tool.input_schema = {}

    with patch("harness.tool_registry.tool_registry.get_tool", return_value=mock_tool):
        wrapper = create_adk_tool_from_registry("test_tool", "test_scope")

        with patch("harness.hooks.hook_system.fire", new_callable=AsyncMock) as mock_hook_fire:
            mock_pre_output = MagicMock()
            mock_pre_output.permission_decision = "deny"
            mock_pre_output.permission_decision_reason = "Test Deny Reason"
            mock_hook_fire.return_value = mock_pre_output

            res = await wrapper(_session_id="session-456")
            res_dict = json.loads(res)
            assert res_dict["success"] is False
            assert "Test Deny Reason" in res_dict["error"]

@pytest.mark.asyncio
async def test_create_adk_tool_flow_hook_update_input():
    # Hookにより入力が上書きされるケース
    mock_tool = MagicMock()
    mock_tool.description = "Test Description"
    mock_tool.input_schema = {}

    with patch("harness.tool_registry.tool_registry.get_tool", return_value=mock_tool):
        wrapper = create_adk_tool_from_registry("test_tool", "test_scope")

        with patch("harness.hooks.hook_system.fire", new_callable=AsyncMock) as mock_hook_fire, \
             patch("harness.governance.governance_engine.check_permission", return_value=True), \
             patch("harness.governance.governance_engine.start_span", return_value="span-123"), \
             patch("harness.governance.governance_engine.end_span"), \
             patch("harness.tool_registry.tool_registry.execute", new_callable=AsyncMock) as mock_exec:

            mock_result = MagicMock()
            mock_result.is_error = False
            mock_result.content = [{"text": "updated_result"}]
            mock_exec.return_value = mock_result

            mock_pre_output = MagicMock()
            mock_pre_output.permission_decision = "allow"
            mock_pre_output.updated_input = {"param1": "hook_overridden"}
            mock_hook_fire.return_value = mock_pre_output

            res = await wrapper(param1="original", _session_id="session-456")
            assert res == "updated_result"
            mock_exec.assert_called_with("test_tool", {"param1": "hook_overridden"})

@pytest.mark.asyncio
async def test_create_adk_tool_flow_governance_deny():
    # Governance権限チェックにより拒否されるケース
    mock_tool = MagicMock()
    mock_tool.description = "Test Description"
    mock_tool.input_schema = {}

    with patch("harness.tool_registry.tool_registry.get_tool", return_value=mock_tool):
        wrapper = create_adk_tool_from_registry("test_tool", "test_scope")

        with patch("harness.hooks.hook_system.fire", new_callable=AsyncMock) as mock_hook_fire, \
             patch("harness.governance.governance_engine.check_permission", return_value=False) as mock_gov_check:

            mock_pre_output = MagicMock()
            mock_pre_output.permission_decision = "allow"
            mock_pre_output.updated_input = None
            mock_hook_fire.return_value = mock_pre_output

            res = await wrapper(_session_id="session-456")
            res_dict = json.loads(res)
            assert res_dict["success"] is False
            assert "権限不足" in res_dict["error"]

@pytest.mark.asyncio
async def test_create_adk_tool_flow_execute_error():
    # ツール実行結果がエラーを返すケース
    mock_tool = MagicMock()
    mock_tool.description = "Test Description"
    mock_tool.input_schema = {}

    with patch("harness.tool_registry.tool_registry.get_tool", return_value=mock_tool):
        wrapper = create_adk_tool_from_registry("test_tool", "test_scope")

        with patch("harness.hooks.hook_system.fire", new_callable=AsyncMock) as mock_hook_fire, \
             patch("harness.governance.governance_engine.check_permission", return_value=True), \
             patch("harness.governance.governance_engine.start_span", return_value="span-123"), \
             patch("harness.governance.governance_engine.end_span") as mock_end_span, \
             patch("harness.tool_registry.tool_registry.execute", new_callable=AsyncMock) as mock_exec:

            mock_result = MagicMock()
            mock_result.is_error = True
            mock_result.content = [{"text": "some error"}]
            mock_exec.return_value = mock_result

            mock_pre_output = MagicMock()
            mock_pre_output.permission_decision = "allow"
            mock_pre_output.updated_input = None
            mock_hook_fire.return_value = mock_pre_output

            res = await wrapper(_session_id="session-456")
            assert res == "some error"
            mock_end_span.assert_called_with("span-123", status="error")

@pytest.mark.asyncio
async def test_create_adk_tool_flow_execute_exception():
    # ツール実行中に例外が発生するケース
    mock_tool = MagicMock()
    mock_tool.description = "Test Description"
    mock_tool.input_schema = {}

    with patch("harness.tool_registry.tool_registry.get_tool", return_value=mock_tool):
        wrapper = create_adk_tool_from_registry("test_tool", "test_scope")

        with patch("harness.hooks.hook_system.fire", new_callable=AsyncMock) as mock_hook_fire, \
             patch("harness.governance.governance_engine.check_permission", return_value=True), \
             patch("harness.governance.governance_engine.start_span", return_value="span-123"), \
             patch("harness.governance.governance_engine.end_span") as mock_end_span, \
             patch("harness.tool_registry.tool_registry.execute", side_effect=RuntimeError("fatal error")) as mock_exec:

            mock_pre_output = MagicMock()
            mock_pre_output.permission_decision = "allow"
            mock_pre_output.updated_input = None
            mock_hook_fire.return_value = mock_pre_output

            res = await wrapper(_session_id="session-456")
            res_dict = json.loads(res)
            assert res_dict["success"] is False
            assert "fatal error" in res_dict["error"]
            mock_end_span.assert_called_with("span-123", status="error")

@pytest.mark.asyncio
async def test_build_harness_pipeline():
    # build_harness_pipeline のインポート正常系/例外系
    with patch("agents.memory.verified_facts.verified_facts_store.get_facts_for_context", return_value="Verified context data"), \
         patch("model_registry.get_model", return_value="mock-supervisor-model"):
        
        pipeline = build_harness_pipeline()
        assert pipeline is not None
        assert pipeline.name == "HarnessProductionPipeline"
        assert len(pipeline.sub_agents) == 6

    # model_override を指定した場合
    with patch("agents.memory.verified_facts.verified_facts_store.get_facts_for_context", return_value=None):
        pipeline_overridden = build_harness_pipeline(model_override="override-model")
        assert pipeline_overridden is not None

    # インポートエラーなどでフォールバックする場合
    with patch("agents.memory.verified_facts.verified_facts_store.get_facts_for_context", side_effect=ImportError("mock import error")), \
         patch("model_registry.get_model", side_effect=ImportError("mock import error")):
        pipeline_fallback = build_harness_pipeline()
        assert pipeline_fallback is not None

# run_harness_pipeline テスト用のモッククラス群
class MockPart:
    def __init__(self, text):
        self.text = text

class MockContent:
    def __init__(self, text):
        self.parts = [MockPart(text)]

class MockEvent:
    def __init__(self, author=None, content=None):
        self.author = author
        self.content = content

    def is_final_response(self):
        return self.content is not None

class MockSessionService:
    async def create_session(self, **kwargs):
        return MagicMock()

class MockRunner:
    def __init__(self, agent, app_name):
        self.agent = agent
        self.app_name = app_name
        self.session_service = MockSessionService()

    async def run_async(self, **kwargs):
        # 進捗更新イベントと最終結果イベントを流す
        yield MockEvent(author="TranscribeAgent")
        yield MockEvent(content=MockContent("Completed Pipeline Output"))

@pytest.mark.asyncio
async def test_run_harness_pipeline_success():
    with patch("google.adk.runners.InMemoryRunner", MockRunner), \
         patch("harness.hooks.hook_system.fire", new_callable=AsyncMock) as mock_hook, \
         patch("harness.session_manager.session_manager.create_session") as mock_create_sess, \
         patch("harness.session_manager.session_manager.update_stage") as mock_update_stage, \
         patch("harness.session_manager.session_manager.complete_session") as mock_complete_sess, \
         patch("harness.governance.governance_engine.start_span", return_value="trace-123"), \
         patch("harness.governance.governance_engine.end_span") as mock_end_span:

        mock_sess = MagicMock()
        mock_sess.session_id = "harness-session-id"
        mock_create_sess.return_value = mock_sess

        res = await run_harness_pipeline(video_path="/path/to/video.mp4")
        assert res["status"] == "success"
        assert res["result"] == "Completed Pipeline Output"
        mock_complete_sess.assert_called_with("harness-session-id")
        mock_end_span.assert_called_with("trace-123", status="ok")

@pytest.mark.asyncio
async def test_run_harness_pipeline_503_retry():
    # 503エラーが発生し、同じモデルでリトライするケース
    call_count = 0

    class MockRunnerWithError:
        def __init__(self, agent, app_name):
            self.agent = agent
            self.app_name = app_name
            self.session_service = MockSessionService()

        async def run_async(self, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 1回目は503エラーを送出 (RuntimeErrorに変更)
                raise RuntimeError("503 SERVICE_UNAVAILABLE")
            else:
                # 2回目は成功
                yield MockEvent(content=MockContent("Retry Success"))

    with patch("google.adk.runners.InMemoryRunner", MockRunnerWithError), \
         patch("harness.hooks.hook_system.fire", new_callable=AsyncMock), \
         patch("harness.session_manager.session_manager.create_session") as mock_create_sess, \
         patch("harness.session_manager.session_manager.update_stage"), \
         patch("harness.session_manager.session_manager.complete_session"), \
         patch("harness.governance.governance_engine.start_span", return_value="trace-123"), \
         patch("harness.governance.governance_engine.end_span"), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

        mock_sess = MagicMock()
        mock_sess.session_id = "harness-session-id"
        mock_create_sess.return_value = mock_sess

        res = await run_harness_pipeline(video_path="/path/to/video.mp4")
        assert res["status"] == "success"
        assert res["result"] == "Retry Success"
        assert call_count == 2
        mock_sleep.assert_called_once_with(10)

@pytest.mark.asyncio
async def test_run_harness_pipeline_503_exhausted():
    # 503エラーが最大リトライ回数を超えて枯渇するケース
    class MockRunnerAlways503:
        def __init__(self, agent, app_name):
            self.agent = agent
            self.app_name = app_name
            self.session_service = MockSessionService()

        async def run_async(self, **kwargs):
            if False:
                yield
            # RuntimeErrorに変更
            raise RuntimeError("503 SERVICE_UNAVAILABLE")

    with patch("google.adk.runners.InMemoryRunner", MockRunnerAlways503), \
         patch("harness.hooks.hook_system.fire", new_callable=AsyncMock), \
         patch("harness.session_manager.session_manager.create_session") as mock_create_sess, \
         patch("harness.session_manager.session_manager.update_stage"), \
         patch("harness.session_manager.session_manager.complete_session"), \
         patch("harness.governance.governance_engine.start_span", return_value="trace-123"), \
         patch("harness.governance.governance_engine.end_span"), \
         patch("asyncio.sleep", new_callable=AsyncMock):

        mock_sess = MagicMock()
        mock_sess.session_id = "harness-session-id"
        mock_create_sess.return_value = mock_sess

        # 3回目の試行 (_fallback_attempt=2) で枯渇例外が送出されるはず
        with pytest.raises(RuntimeError, match="API Error: 全フォールバック枯渇"):
            await run_harness_pipeline(video_path="/path/to/video.mp4", _fallback_attempt=2)

@pytest.mark.asyncio
async def test_run_harness_pipeline_model_fallback():
    # 429などでフォールバックチェーンが走り、次のモデルに移行するケース
    call_count = 0
    passed_models = []

    class MockRunnerWithFallback:
        def __init__(self, agent, app_name):
            self.agent = agent
            self.app_name = app_name
            self.session_service = MockSessionService()
            passed_models.append(agent.model if hasattr(agent, 'model') else None)

        async def run_async(self, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 1回目は429リソース枯渇エラー (RuntimeErrorに変更)
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            else:
                yield MockEvent(content=MockContent("Fallback Model Success"))

    with patch("google.adk.runners.InMemoryRunner", MockRunnerWithFallback), \
         patch("harness.hooks.hook_system.fire", new_callable=AsyncMock), \
         patch("harness.session_manager.session_manager.create_session") as mock_create_sess, \
         patch("harness.session_manager.session_manager.update_stage"), \
         patch("harness.session_manager.session_manager.complete_session"), \
         patch("harness.governance.governance_engine.start_span", return_value="trace-123"), \
         patch("harness.governance.governance_engine.end_span"), \
         patch("model_governance.model_governance.build_fallback_sequence", return_value=["gemini-2.5-flash", "gemini-2.5-pro"]), \
         patch("asyncio.sleep", new_callable=AsyncMock):

        mock_sess = MagicMock()
        mock_sess.session_id = "harness-session-id"
        mock_create_sess.return_value = mock_sess

        # build_harness_pipeline の model_override 時に model 属性を付与するようにパッチ
        original_build = build_harness_pipeline
        def mock_build(model_override=None):
            p = original_build(model_override)
            object.__setattr__(p, 'model', model_override or "gemini-2.5-flash")
            return p

        with patch("agents._deprecated.adk_bridge.build_harness_pipeline", mock_build):
            res = await run_harness_pipeline(video_path="/path/to/video.mp4")
            assert res["status"] == "success"
            assert res["result"] == "Fallback Model Success"
            assert call_count == 2
            # 最初のモデル (gemini-2.5-flash) から次のモデル (gemini-2.5-pro) にフォールバックされていることを確認
            assert "gemini-2.5-pro" in passed_models

@pytest.mark.asyncio
async def test_run_harness_pipeline_fallback_exhausted():
    # フォールバックチェーンが最後まで枯渇するケース
    class MockRunnerAlways429:
        def __init__(self, agent, app_name):
            self.agent = agent
            self.app_name = app_name
            self.session_service = MockSessionService()

        async def run_async(self, **kwargs):
            if False:
                yield
            # RuntimeErrorに変更
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

    with patch("google.adk.runners.InMemoryRunner", MockRunnerAlways429), \
         patch("harness.hooks.hook_system.fire", new_callable=AsyncMock), \
         patch("harness.session_manager.session_manager.create_session") as mock_create_sess, \
         patch("harness.session_manager.session_manager.update_stage"), \
         patch("harness.session_manager.session_manager.complete_session"), \
         patch("harness.governance.governance_engine.start_span", return_value="trace-123"), \
         patch("harness.governance.governance_engine.end_span"), \
         patch("model_governance.model_governance.build_fallback_sequence", return_value=["gemini-2.5-flash"]), \
         patch("asyncio.sleep", new_callable=AsyncMock):

        mock_sess = MagicMock()
        mock_sess.session_id = "harness-session-id"
        mock_create_sess.return_value = mock_sess

        original_build = build_harness_pipeline
        def mock_build(model_override=None):
            p = original_build(model_override)
            object.__setattr__(p, 'model', model_override or "gemini-2.5-flash")
            return p

        with patch("agents._deprecated.adk_bridge.build_harness_pipeline", mock_build):
            with pytest.raises(RuntimeError, match="API Error: フォールバックチェーン枯渇"):
                await run_harness_pipeline(video_path="/path/to/video.mp4")

@pytest.mark.asyncio
async def test_run_harness_pipeline_other_exception():
    # フォールバック対象外の一般的な例外が発生するケース
    class MockRunnerFatal:
        def __init__(self, agent, app_name):
            self.agent = agent
            self.app_name = app_name
            self.session_service = MockSessionService()

        async def run_async(self, **kwargs):
            if False:
                yield
            raise ValueError("some fatal non-fallback error")

    with patch("google.adk.runners.InMemoryRunner", MockRunnerFatal), \
         patch("harness.hooks.hook_system.fire", new_callable=AsyncMock) as mock_hook, \
         patch("harness.session_manager.session_manager.create_session") as mock_create_sess, \
         patch("harness.session_manager.session_manager.update_stage"), \
         patch("harness.session_manager.session_manager.error_session") as mock_error_sess, \
         patch("harness.governance.governance_engine.start_span", return_value="trace-123"), \
         patch("harness.governance.governance_engine.end_span") as mock_end_span:

        mock_sess = MagicMock()
        mock_sess.session_id = "harness-session-id"
        mock_create_sess.return_value = mock_sess

        res = await run_harness_pipeline(video_path="/path/to/video.mp4")
        assert res["status"] == "error"
        assert "some fatal non-fallback error" in res["error"]
        mock_error_sess.assert_called_with("harness-session-id", "some fatal non-fallback error")
        mock_end_span.assert_called_with("trace-123", status="error")


@pytest.mark.asyncio
async def test_run_harness_pipeline_model_registry_import_error():
    # model_registry インポート時に ImportError が発生するケースの検証
    with patch("google.adk.runners.InMemoryRunner", MockRunner), \
         patch("harness.hooks.hook_system.fire", new_callable=AsyncMock), \
         patch("harness.session_manager.session_manager.create_session") as mock_create_sess, \
         patch("harness.session_manager.session_manager.update_stage"), \
         patch("harness.session_manager.session_manager.complete_session"), \
         patch("harness.governance.governance_engine.start_span", return_value="trace-123"), \
         patch("harness.governance.governance_engine.end_span"), \
         patch.dict("sys.modules", {"model_registry": None}):

        mock_sess = MagicMock()
        mock_sess.session_id = "harness-session-id"
        mock_create_sess.return_value = mock_sess

        res = await run_harness_pipeline(video_path="/path/to/video.mp4")
        assert res["status"] == "success"
        assert res["result"] == "Completed Pipeline Output"


@pytest.mark.asyncio
async def test_run_harness_pipeline_model_governance_import_error():
    # model_governance インポート時に ImportError が発生するケースの検証
    with patch("google.adk.runners.InMemoryRunner", MockRunner), \
         patch("harness.hooks.hook_system.fire", new_callable=AsyncMock), \
         patch("harness.session_manager.session_manager.create_session") as mock_create_sess, \
         patch("harness.session_manager.session_manager.update_stage"), \
         patch("harness.session_manager.session_manager.complete_session"), \
         patch("harness.governance.governance_engine.start_span", return_value="trace-123"), \
         patch("harness.governance.governance_engine.end_span"), \
         patch.dict("sys.modules", {"model_governance": None}):

        mock_sess = MagicMock()
        mock_sess.session_id = "harness-session-id"
        mock_create_sess.return_value = mock_sess

        res = await run_harness_pipeline(video_path="/path/to/video.mp4")
        assert res["status"] == "success"
        assert res["result"] == "Completed Pipeline Output"


@pytest.mark.asyncio
async def test_create_adk_tool_flow_execute_various_exceptions():
    # ツール実行中に様々な例外が発生するケース
    exceptions_to_test = [
        asyncio.TimeoutError("timeout occurred"),
        OSError("disk full"),
        KeyError("missing key"),
        TypeError("invalid type"),
    ]
    mock_tool = MagicMock()
    mock_tool.description = "Test Description"
    mock_tool.input_schema = {}

    with patch("harness.tool_registry.tool_registry.get_tool", return_value=mock_tool):
        wrapper = create_adk_tool_from_registry("test_tool", "test_scope")

        for exc in exceptions_to_test:
            with patch("harness.hooks.hook_system.fire", new_callable=AsyncMock) as mock_hook_fire, \
                 patch("harness.governance.governance_engine.check_permission", return_value=True), \
                 patch("harness.governance.governance_engine.start_span", return_value="span-123"), \
                 patch("harness.governance.governance_engine.end_span") as mock_end_span, \
                 patch("harness.tool_registry.tool_registry.execute", side_effect=exc):

                mock_pre_output = MagicMock()
                mock_pre_output.permission_decision = "allow"
                mock_pre_output.updated_input = None
                mock_hook_fire.return_value = mock_pre_output

                res = await wrapper(_session_id="session-456")
                res_dict = json.loads(res)
                assert res_dict["success"] is False
                assert str(exc)[:10] in res_dict["error"]
                mock_end_span.assert_called_with("span-123", status="error")


@pytest.mark.asyncio
async def test_build_annotations_edge_cases():
    # 空のスキーマ、または特殊な型（typeではないもの）
    input_schema = {
        "arg1": {},  # 空の辞書 -> デフォルト str
        "arg2": "not_a_type",  # typeやdictではない -> デフォルト str
        "arg3": {"type": "unknown_type_str"},  # 未知の型文字列 -> type_mapになく、デフォルト str
    }
    annotations = _build_annotations(input_schema)
    assert annotations["arg1"] == str
    assert annotations["arg2"] == str
    assert annotations["arg3"] == str


@pytest.mark.asyncio
async def test_run_harness_pipeline_503_max_retries_bounds():
    # _max_fallback_attempts が極端な値（0や1）の境界テスト
    class MockRunnerAlways503:
        def __init__(self, agent, app_name):
            self.agent = agent
            self.app_name = app_name
            self.session_service = MockSessionService()

        async def run_async(self, **kwargs):
            if False:
                yield
            raise RuntimeError("503 SERVICE_UNAVAILABLE")

    with patch("google.adk.runners.InMemoryRunner", MockRunnerAlways503), \
         patch("harness.hooks.hook_system.fire", new_callable=AsyncMock), \
         patch("harness.session_manager.session_manager.create_session") as mock_create_sess, \
         patch("harness.session_manager.session_manager.update_stage"), \
         patch("harness.session_manager.session_manager.complete_session"), \
         patch("harness.governance.governance_engine.start_span", return_value="trace-123"), \
         patch("harness.governance.governance_engine.end_span"), \
         patch("asyncio.sleep", new_callable=AsyncMock):

        mock_sess = MagicMock()
        mock_sess.session_id = "harness-session-id"
        mock_create_sess.return_value = mock_sess

        # _max_fallback_attempts=0 の場合、最初の試行で即座に枯渇例外が送出されるはず
        with pytest.raises(RuntimeError, match="API Error: 全フォールバック枯渇"):
            await run_harness_pipeline(video_path="/path/to/video.mp4", _max_fallback_attempts=0)

        # _max_fallback_attempts=1 の場合、1回のリトライ後に枯渇例外が送出されるはず
        # _fallback_attemptが1以上になると枯渇
        with pytest.raises(RuntimeError, match="API Error: 全フォールバック枯渇"):
            await run_harness_pipeline(video_path="/path/to/video.mp4", _fallback_attempt=1, _max_fallback_attempts=1)


@pytest.mark.asyncio
async def test_run_harness_pipeline_unknown_model_fallback():
    # 現在のモデルがフォールバックチェーンに存在しない場合の挙動
    call_count = 0
    passed_models = []

    class MockRunnerWithFallback:
        def __init__(self, agent, app_name):
            self.agent = agent
            self.app_name = app_name
            self.session_service = MockSessionService()
            passed_models.append(agent.model if hasattr(agent, 'model') else None)

        async def run_async(self, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            else:
                yield MockEvent(content=MockContent("Success Unknown Fallback"))

    with patch("google.adk.runners.InMemoryRunner", MockRunnerWithFallback), \
         patch("harness.hooks.hook_system.fire", new_callable=AsyncMock), \
         patch("harness.session_manager.session_manager.create_session") as mock_create_sess, \
         patch("harness.session_manager.session_manager.update_stage"), \
         patch("harness.session_manager.session_manager.complete_session"), \
         patch("harness.governance.governance_engine.start_span", return_value="trace-123"), \
         patch("harness.governance.governance_engine.end_span"), \
         patch("model_governance.model_governance.build_fallback_sequence", return_value=["gemini-2.5-flash", "gemini-2.5-pro"]), \
         patch("asyncio.sleep", new_callable=AsyncMock):

        mock_sess = MagicMock()
        mock_sess.session_id = "harness-session-id"
        mock_create_sess.return_value = mock_sess

        original_build = build_harness_pipeline
        # model_override に未知のモデル "unknown-model" を設定
        def mock_build(model_override=None):
            p = original_build(model_override)
            object.__setattr__(p, 'model', model_override or "unknown-model")
            return p

        with patch("agents._deprecated.adk_bridge.build_harness_pipeline", mock_build):
            res = await run_harness_pipeline(video_path="/path/to/video.mp4", _fallback_model="unknown-model")
            assert res["status"] == "success"
            assert res["result"] == "Success Unknown Fallback"
            assert call_count == 2
            # 未知のモデルが fallback_chain に見つからないため、next_idx = 0 + 1 = 1 となり、
            # チェーンの次のモデル "gemini-2.5-pro" にフォールバックされることを確認
            assert "gemini-2.5-pro" in passed_models


@pytest.mark.asyncio
async def test_run_harness_pipeline_initial_state_verification():
    # run_harness_pipeline 実行時の initial_state のアサーション
    created_session_kwargs = {}

    class MockSessionServiceLocal:
        async def create_session(self, **kwargs):
            nonlocal created_session_kwargs
            created_session_kwargs = kwargs
            return MagicMock()

    class MockRunnerLocal:
        def __init__(self, agent, app_name):
            self.agent = agent
            self.app_name = app_name
            self.session_service = MockSessionServiceLocal()

        async def run_async(self, **kwargs):
            yield MockEvent(content=MockContent("Success Initial State Test"))

    with patch("google.adk.runners.InMemoryRunner", MockRunnerLocal),          patch("harness.hooks.hook_system.fire", new_callable=AsyncMock),          patch("harness.session_manager.session_manager.create_session") as mock_create_sess,          patch("harness.session_manager.session_manager.update_stage"),          patch("harness.session_manager.session_manager.complete_session"),          patch("harness.governance.governance_engine.start_span", return_value="trace-123"),          patch("harness.governance.governance_engine.end_span"):

        mock_sess = MagicMock()
        mock_sess.session_id = "test-harness-sid-999"
        mock_create_sess.return_value = mock_sess

        res = await run_harness_pipeline(
            video_path="/path/to/my_test_video.mp4",
            target_minutes=15,
            session_id="test-adk-sid-111"
        )
        assert res["status"] == "success"
        
        # create_session への引数の検証
        assert created_session_kwargs.get("app_name") == "antigravity_harness"
        assert created_session_kwargs.get("user_id") == "pipeline_user"
        assert created_session_kwargs.get("session_id") == "test-adk-sid-111"
        
        state = created_session_kwargs.get("state", {})
        assert state.get("video_path") == "/path/to/my_test_video.mp4"
        assert state.get("target_minutes") == 15
        assert state.get("harness_session_id") == "test-harness-sid-999"
        assert "pipeline_started_at" in state


@pytest.mark.asyncio
async def test_run_harness_pipeline_hook_inputs_verification():
    # Hook 発火時に正しい HookInput が渡されているかの検証
    fired_hooks = []

    async def mock_fire(event, hook_input):
        fired_hooks.append((event, hook_input))
        mock_out = MagicMock()
        mock_out.permission_decision = "allow"
        mock_out.updated_input = None
        return mock_out

    with patch("google.adk.runners.InMemoryRunner", MockRunner),          patch("harness.hooks.hook_system.fire", side_effect=mock_fire),          patch("harness.session_manager.session_manager.create_session") as mock_create_sess,          patch("harness.session_manager.session_manager.update_stage"),          patch("harness.session_manager.session_manager.complete_session"),          patch("harness.governance.governance_engine.start_span", return_value="trace-123"),          patch("harness.governance.governance_engine.end_span"):

        mock_sess = MagicMock()
        mock_sess.session_id = "test-harness-sid-888"
        mock_create_sess.return_value = mock_sess

        await run_harness_pipeline(
            video_path="/path/to/my_test_video.mp4",
            target_minutes=15,
            session_id="test-adk-sid-222"
        )

        from harness.hooks import HookEvent
        # SESSION_START と SESSION_END が発火したか検証
        events = [fh[0] for fh in fired_hooks]
        assert HookEvent.SESSION_START in events
        assert HookEvent.SESSION_END in events

        # SESSION_START の検証
        start_event, start_input = next(fh for fh in fired_hooks if fh[0] == HookEvent.SESSION_START)
        assert start_input.tool_name == "HarnessProductionPipeline"
        assert start_input.session_id == "test-harness-sid-888"
        assert start_input.metadata["video_path"] == "/path/to/my_test_video.mp4"
        assert start_input.metadata["target_minutes"] == 15

        # SESSION_END の検証
        end_event, end_input = next(fh for fh in fired_hooks if fh[0] == HookEvent.SESSION_END)
        assert end_input.tool_name == "HarnessProductionPipeline"
        assert end_input.session_id == "test-harness-sid-888"
        assert end_input.metadata["status"] == "success"
        assert "duration_seconds" in end_input.metadata


@pytest.mark.asyncio
async def test_generate_adk_bridge_thumbnail(tmp_path):
    from agents._deprecated.adk_bridge import generate_adk_bridge_thumbnail
    out_path = tmp_path / "test_thumb.png"
    res_path = generate_adk_bridge_thumbnail(out_path)
    assert res_path == out_path
    assert out_path.exists()
    
    from PIL import Image
    with Image.open(out_path) as img:
        assert img.size == (1280, 720)

@pytest.mark.asyncio
async def test_validate_adk_bridge_thumbnail_success(tmp_path):
    from agents._deprecated.adk_bridge import validate_adk_bridge_thumbnail
    from PIL import Image
    out_path = tmp_path / "valid.png"
    img = Image.new("RGB", (1280, 720), color=(73, 109, 137))
    img.save(out_path, format="PNG")
    
    result = validate_adk_bridge_thumbnail(out_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["path"] == str(out_path)
    assert result["size_bytes"] > 0

@pytest.mark.asyncio
async def test_validate_adk_bridge_thumbnail_failures(tmp_path):
    from agents._deprecated.adk_bridge import validate_adk_bridge_thumbnail
    from PIL import Image
    
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        validate_adk_bridge_thumbnail(tmp_path / "missing.png")
        
    # 2. 解像度不足の画像
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color=(73, 109, 137))
    img.save(low_res_path, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_adk_bridge_thumbnail(low_res_path)
        
    # 3. アスペクト比が異なる画像
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color=(73, 109, 137))
    img.save(bad_ratio_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_adk_bridge_thumbnail(bad_ratio_path)
        
    # 4. ファイルサイズ制限 (4MB)
    valid_path = tmp_path / "valid.png"
    img = Image.new("RGB", (1280, 720), color=(73, 109, 137))
    img.save(valid_path, format="PNG")
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_adk_bridge_thumbnail(valid_path)

    # 5. 破損画像 (verify / load 失敗)
    corrupt_path = tmp_path / "corrupt.png"
    with open(corrupt_path, "wb") as f:
        f.write(b"corrupted data")
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_adk_bridge_thumbnail(corrupt_path)

@pytest.mark.asyncio
async def test_resolve_adk_bridge_thumbnail_task_stage_bound(tmp_path):
    from agents._deprecated.adk_bridge import resolve_adk_bridge_thumbnail_task
    from agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "test_adk_bridge_thumb.db"
    task_id = "adk_bridge_thumb_test"
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
    
    # adk_bridge.THUMBNAIL_OUTPUT_DIR を tmp_path にパッチ
    import agents._deprecated.adk_bridge
    with patch.object(agents._deprecated.adk_bridge, "THUMBNAIL_OUTPUT_DIR", tmp_path):
        output_file = tmp_path / f"{task_id}.png"
        
        await agent.start(resolve_adk_bridge_thumbnail_task)
        
        # 完了を待つ (タイムアウト 5秒)
        for _ in range(100):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        assert output_file.exists()
        
        # DBに保存された結果の検証
        import sqlite3
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, result_str, retry_count = row
            assert status == "COMPLETED"
            
            result_data = json.loads(result_str)
            assert result_data["width"] == 1280
            assert result_data["height"] == 720
        finally:
            conn.close()


@pytest.mark.asyncio
async def test_resolve_adk_bridge_thumbnail_task_uses_to_thread(tmp_path):
    from agents._deprecated.adk_bridge import resolve_adk_bridge_thumbnail_task
    import agents._deprecated.adk_bridge
    
    call_args = []
    original_to_thread = asyncio.to_thread
    
    async def mock_to_thread(func, *args, **kwargs):
        call_args.append(func)
        return await original_to_thread(func, *args, **kwargs)
        
    with patch("asyncio.to_thread", side_effect=mock_to_thread):
        with patch.object(agents._deprecated.adk_bridge, "THUMBNAIL_OUTPUT_DIR", tmp_path):
            result_str = await resolve_adk_bridge_thumbnail_task("to_thread_test")
            result = json.loads(result_str)
            assert result["width"] == 1280
            assert result["height"] == 720
            
            from agents._deprecated.adk_bridge import generate_adk_bridge_thumbnail, validate_adk_bridge_thumbnail
            assert generate_adk_bridge_thumbnail in call_args
            assert validate_adk_bridge_thumbnail in call_args

@pytest.mark.asyncio
async def test_validate_adk_bridge_thumbnail_corrupt_unidentified_image_error(tmp_path):
    from agents._deprecated.adk_bridge import validate_adk_bridge_thumbnail
    
    corrupt_file = tmp_path / "empty_image.png"
    corrupt_file.touch()
    
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_adk_bridge_thumbnail(corrupt_file)

@pytest.mark.asyncio
async def test_create_adk_tool_flow_no_scope_no_session():
    # agent_scopeが空かつ_session_idがない場合のカバー
    mock_tool = MagicMock()
    mock_tool.description = "Test Description"
    mock_tool.input_schema = {}
    with patch("harness.tool_registry.tool_registry.get_tool", return_value=mock_tool):
        wrapper = create_adk_tool_from_registry("test_tool", agent_scope="")
        with patch("harness.hooks.hook_system.fire", new_callable=AsyncMock) as mock_hook_fire, \
             patch("harness.governance.governance_engine.start_span", return_value="span-123"), \
             patch("harness.governance.governance_engine.end_span"), \
             patch("harness.tool_registry.tool_registry.execute", new_callable=AsyncMock) as mock_exec, \
             patch("harness.session_manager.session_manager.record_tool_call") as mock_record:
            mock_result = MagicMock()
            mock_result.is_error = False
            mock_result.content = [{"text": "no_scope_result"}]
            mock_exec.return_value = mock_result
            mock_pre_output = MagicMock()
            mock_pre_output.permission_decision = "allow"
            mock_pre_output.updated_input = None
            mock_hook_fire.return_value = mock_pre_output

            res = await wrapper()  # _session_id なし
            assert res == "no_scope_result"
            mock_record.assert_not_called()

@pytest.mark.asyncio
async def test_run_harness_pipeline_empty_part_text():
    # part.text が None または "" の場合に結合処理が避けることを検証
    class MockRunnerWithEmptyPart:
        def __init__(self, agent, app_name):
            self.agent = agent
            self.app_name = app_name
            self.session_service = MockSessionService()

        async def run_async(self, **kwargs):
            mock_content = MagicMock()
            part_none = MagicMock()
            part_none.text = None
            part_empty = MagicMock()
            part_empty.text = ""
            part_valid = MagicMock()
            part_valid.text = "Valid Output"
            mock_content.parts = [part_none, part_empty, part_valid]
            yield MockEvent(content=mock_content)

    with patch("google.adk.runners.InMemoryRunner", MockRunnerWithEmptyPart), \
         patch("harness.hooks.hook_system.fire", new_callable=AsyncMock), \
         patch("harness.session_manager.session_manager.create_session") as mock_create_sess, \
         patch("harness.session_manager.session_manager.update_stage"), \
         patch("harness.session_manager.session_manager.complete_session"), \
         patch("harness.governance.governance_engine.start_span", return_value="trace-123"), \
         patch("harness.governance.governance_engine.end_span"):

        mock_sess = MagicMock()
        mock_sess.session_id = "harness-session-id"
        mock_create_sess.return_value = mock_sess

        res = await run_harness_pipeline(video_path="/path/to/video.mp4")
        assert res["status"] == "success"
        assert res["result"] == "Valid Output"

@pytest.mark.asyncio
async def test_generate_adk_bridge_thumbnail_invalid_dimensions(tmp_path):
    from agents._deprecated.adk_bridge import generate_adk_bridge_thumbnail
    out_path = tmp_path / "thumb_err.png"
    
    # 761-762: TypeError/ValueError
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_adk_bridge_thumbnail(out_path, width="not_an_int")
        
    # 765: width <= 0 or height <= 0
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_adk_bridge_thumbnail(out_path, width=0, height=720)
        
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_adk_bridge_thumbnail(out_path, width=1280, height=-10)

@pytest.mark.asyncio
async def test_generate_adk_bridge_thumbnail_existing_unlink(tmp_path):
    from agents._deprecated.adk_bridge import generate_adk_bridge_thumbnail
    out_path = tmp_path / "already_exists.png"
    
    out_path.write_text("dummy data")
    assert out_path.exists()
    
    res_path = generate_adk_bridge_thumbnail(out_path, text="Overwritten Thumbnail")
    assert res_path == out_path
    assert out_path.exists()
    
    from PIL import Image
    with Image.open(out_path) as img:
        assert img.size == (1280, 720)

@pytest.mark.asyncio
async def test_generate_adk_bridge_thumbnail_write_exception(tmp_path):
    from agents._deprecated.adk_bridge import generate_adk_bridge_thumbnail
    out_path = tmp_path / "fail_write.png"
    
    # 781-788: PIL.Image.save exception 時に unlink が成功するケース
    with patch("PIL.Image.Image.save", side_effect=OSError("Save failed")):
        with pytest.raises(OSError, match="Save failed"):
            generate_adk_bridge_thumbnail(out_path)
            
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0

    # 783-786: unlink が OSError を投げるケース
    # temp_path.exists() が True を返し、かつ unlink() が OSError を投げるようにモックする
    with patch("PIL.Image.Image.save", side_effect=OSError("Save failed")), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.unlink", side_effect=OSError("Mocked unlink failure")):
        with pytest.raises(OSError, match="Save failed"):
            generate_adk_bridge_thumbnail(out_path)

@pytest.mark.asyncio
async def test_validate_adk_bridge_thumbnail_load_exception(tmp_path):
    from agents._deprecated.adk_bridge import validate_adk_bridge_thumbnail
    from PIL import Image
    
    out_path = tmp_path / "mock_load_fail.png"
    img = Image.new("RGB", (1280, 720), color=(73, 109, 137))
    img.save(out_path, format="PNG")
    
    original_open = Image.open
    
    def mock_open(*args, **kwargs):
        img_obj = original_open(*args, **kwargs)
        img_obj.load = MagicMock(side_effect=OSError("Mocked load error"))
        return img_obj
        
    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_adk_bridge_thumbnail(out_path)

@pytest.mark.asyncio
async def test_run_harness_pipeline_sets_event_loop(tmp_path):
    from agents._deprecated.adk_bridge import run_harness_pipeline
    import asyncio
    
    with patch("google.genai.Client") as mock_client, \
         patch("harness.hooks.hook_system.fire", new_callable=AsyncMock) as mock_hook, \
         patch("harness.session_manager.session_manager.create_session") as mock_create_session, \
         patch("harness.governance.governance_engine.start_span") as mock_span, \
         patch("google.adk.runners.InMemoryRunner", side_effect=RuntimeError("Interrupt to inspect loop")):
         
         mock_session = MagicMock()
         mock_session.session_id = "test-session"
         mock_create_session.return_value = mock_session
         mock_span.return_value = "span-id"
         
         res = await run_harness_pipeline(video_path=str(tmp_path / "dummy.mp4"))
         
         assert res["status"] == "error"
         assert "Interrupt to inspect loop" in res["error"]
         
         current_loop = asyncio.get_event_loop()
         assert current_loop is not None
