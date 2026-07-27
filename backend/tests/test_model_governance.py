import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from backend.model_governance import ModelGovernanceEngine
from google.genai.errors import APIError

def test_model_governance_singleton():
    engine1 = ModelGovernanceEngine()
    engine2 = ModelGovernanceEngine()
    assert engine1 is engine2

def test_validate_and_correct():
    engine = ModelGovernanceEngine()
    engine._deprecation_map = {
        "old-model-1": "new-model-1",
        "old-model-2": "new-model-2"
    }
    assert engine.validate_and_correct("old-model-1") == "new-model-1"
    assert engine.validate_and_correct("new-model-1") == "new-model-1"

def test_validate_and_correct_chain_and_cycle():
    engine = ModelGovernanceEngine()
    engine._deprecation_map = {
        "a": "b",
        "b": "c",
        "cycle-a": "cycle-b",
        "cycle-b": "cycle-a"
    }
    assert engine.validate_and_correct("a") == "c"
    assert engine.validate_and_correct("cycle-a") in ["cycle-a", "cycle-b"]

def test_get_fallback():
    engine = ModelGovernanceEngine()
    engine._fallback_chain = {"a": "b"}
    assert engine.get_fallback("a") == "b"
    assert engine.get_fallback("b") is None

def test_is_fallback_error():
    engine = ModelGovernanceEngine()
    assert engine.is_fallback_error("RESOURCE_EXHAUSTED") is True
    assert engine.is_fallback_error("UNAVAILABLE") is True
    assert engine.is_fallback_error("some error quota limit") is True
    assert engine.is_fallback_error("generic error") is False

def test_build_fallback_sequence():
    engine = ModelGovernanceEngine()
    engine._fallback_chain = {"a": "b", "b": "c", "cycle": "cycle"}
    assert engine.build_fallback_sequence("a") == ["a", "b", "c"]
    assert engine.build_fallback_sequence("cycle") == ["cycle"]

def test_reload():
    engine = ModelGovernanceEngine()
    with patch.object(engine, '_load_config') as mock_load:
        engine.reload()
        mock_load.assert_called_once()
        assert len(engine._deprecation_map) == 0
        assert len(engine._fallback_chain) == 0
        assert engine._task_mapping == {}

def test_resolve_model():
    engine = ModelGovernanceEngine()
    engine._task_mapping = {"test_task": "task_model"}
    engine._default_model = "default_model"
    engine._deprecation_map = {}
    engine._fallback_chain = {}
    
    assert engine._resolve_model("test_task") == "task_model"
    assert engine._resolve_model("other_task") == "default_model"
    assert engine._resolve_model("test_task", "explicit_model") == "explicit_model"

@patch("usage_tracker.tracker.usage_tracker")
def test_resolve_model_with_usage_tracker(mock_ut):
    engine = ModelGovernanceEngine()
    engine._task_mapping = {"test_task": "model-a"}
    engine._fallback_chain = {"model-a": "model-b"}
    
    # model-a はリクエスト不可、model-b は可能
    mock_ut.can_make_request.side_effect = lambda m: m == "model-b"
    mock_ut.get_usage_ratio.return_value = 1.0
    
    assert engine._resolve_model("test_task") == "model-b"

@pytest.mark.asyncio
async def test_call_success():
    engine = ModelGovernanceEngine()
    engine._task_mapping = {"test_task": "model-a"}
    engine._deprecation_map = {}
    engine._fallback_chain = {}
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "generated response"
    
    # Client has aio.models.generate_content
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        res = await engine.call(task="test_task", prompt="hello")
        assert res == "generated response"

@pytest.mark.asyncio
async def test_call_with_config():
    engine = ModelGovernanceEngine()
    engine._task_mapping = {"test_task": "model-a"}
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "response"
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        await engine.call(task="test_task", prompt="hello", config={"temperature": 0.5})
        mock_client.aio.models.generate_content.assert_called_once_with(
            model="model-a", contents="hello", temperature=0.5
        )

@pytest.mark.asyncio
async def test_call_fallback_success():
    engine = ModelGovernanceEngine()
    engine._task_mapping = {"test_task": "model-a"}
    engine._fallback_chain = {"model-a": "model-b"}
    engine.RETRY_DELAY_SECONDS = 0.01
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "fallback success"
    
    async def side_effect(*args, **kwargs):
        if kwargs.get("model") == "model-a":
            raise APIError(429, "RESOURCE_EXHAUSTED")
        return mock_response
        
    mock_client.aio.models.generate_content.side_effect = side_effect
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        res = await engine.call(task="test_task", prompt="hello")
        assert res == "fallback success"

@pytest.mark.asyncio
async def test_call_fallback_exhausted():
    engine = ModelGovernanceEngine()
    engine._task_mapping = {"test_task": "model-a"}
    engine._fallback_chain = {"model-a": "model-b"}
    engine.RETRY_DELAY_SECONDS = 0.01
    
    mock_client = MagicMock()
    mock_client.aio.models.generate_content.side_effect = APIError(
        429, "RESOURCE_EXHAUSTED"
    )
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="全フォールバック枯渇"):
            await engine.call(task="test_task", prompt="hello")

@pytest.mark.asyncio
async def test_call_non_fallback_error():
    engine = ModelGovernanceEngine()
    engine._task_mapping = {"test_task": "model-a"}
    
    mock_client = MagicMock()
    mock_client.aio.models.generate_content.side_effect = APIError(
        400, "INVALID_ARGUMENT"
    )
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        with pytest.raises(APIError):
            await engine.call(task="test_task", prompt="hello")

@pytest.mark.asyncio
async def test_call_no_client():
    engine = ModelGovernanceEngine()
    with patch("gemini_client_factory._get_raw_client", return_value=None):
        with pytest.raises(ValueError, match="GOOGLE_API_KEY が未設定です"):
            await engine.call(task="test_task", prompt="hello")

def test_get_stats_and_event_log():
    engine = ModelGovernanceEngine()
    engine._event_log = [{"timestamp": "2026-06-27"}] * 205
    engine._record_event("test", "orig", "resolved", "caller")
    assert len(engine._event_log) == 100
    
    stats = engine.get_stats()
    assert "deprecation_corrections" in stats
    assert "deprecation_map" in stats


# ============================================================
# 追加されたカバレッジ向上テスト
# ============================================================

def test_load_config_exceptions():
    engine = ModelGovernanceEngine()
    
    # FileNotFoundError
    with patch("builtins.open", side_effect=FileNotFoundError("Mocked file not found")):
        engine.reload()
        
    # json.JSONDecodeError
    import json
    with patch("builtins.open", side_effect=json.JSONDecodeError("msg", "doc", 0)):
        engine.reload()
        
    # PermissionError
    with patch("builtins.open", side_effect=PermissionError("Mocked permission error")):
        engine.reload()


@patch("usage_tracker.tracker.usage_tracker")
def test_resolve_model_fallback_break(mock_ut):
    engine = ModelGovernanceEngine()
    engine._task_mapping = {"test_task": "model-a"}
    engine._fallback_chain = {"model-a": "model-b"}
    
    mock_ut.can_make_request.side_effect = lambda m: False
    mock_ut.get_usage_ratio.return_value = 1.0
    
    assert engine._resolve_model("test_task") == "model-b"


def test_resolve_model_exceptions():
    engine = ModelGovernanceEngine()
    engine._task_mapping = {"test_task": "model-a"}
    
    with patch.dict("sys.modules", {"usage_tracker.tracker": None}):
        assert engine._resolve_model("test_task") == "model-a"
        
    with patch("usage_tracker.tracker.usage_tracker") as mock_ut:
        mock_ut.can_make_request.side_effect = RuntimeError("mocked runtime error")
        assert engine._resolve_model("test_task") == "model-a"


@pytest.mark.asyncio
async def test_call_sync_client_thread():
    engine = ModelGovernanceEngine()
    engine._task_mapping = {"test_task": "model-a"}
    
    mock_client = MagicMock()
    if hasattr(mock_client, "aio"):
        del mock_client.aio
    
    mock_response = MagicMock()
    mock_response.text = "generated response sync"
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        res = await engine.call(task="test_task", prompt="hello")
        assert res == "generated response sync"
        mock_client.models.generate_content.assert_called_once()


@patch("usage_tracker.tracker.usage_tracker")
def test_track_usage_alert_and_exception(mock_ut):
    engine = ModelGovernanceEngine()
    engine._event_log.clear()
    
    mock_ut.track_request.return_value = {"alert_level": "warning", "usage_ratio": 0.8}
    engine._track_usage("model-a", "caller-a")
    assert any(ev.get("type") == "quota_alert" for ev in engine._event_log)
    
    mock_ut.track_request.side_effect = OSError("mocked OS error")
    engine._track_usage("model-a", "caller-a")


from backend.model_governance import (
    model_governance,
    GovernedModelsProxy,
    GovernedAsyncModelsProxy,
    get_governed_client,
    _model_governance_hook,
    _model_usage_tracking_hook,
    register_governance_hook,
)

def test_governed_models_proxy():
    real_models = MagicMock()
    proxy = GovernedModelsProxy(real_models, "caller-a")
    
    real_models.some_attr = "value"
    assert proxy.some_attr == "value"
    
    real_models.generate_content.return_value = "result"
    assert proxy.generate_content(model="gemini-2.5-flash", prompt="hi") == "result"
    
    model_governance._fallback_chain = {"model-x": "model-y"}
    model_governance.RETRY_DELAY_SECONDS = 0.01
    
    call_count = 0
    def side_effect(model, **kwargs):
        nonlocal call_count
        call_count += 1
        if model == "model-x":
            raise APIError(429, "RESOURCE_EXHAUSTED")
        return "fallback_result"
    real_models.generate_content.side_effect = side_effect
    
    assert proxy.generate_content(model="model-x", prompt="hi") == "fallback_result"
    
    real_models.generate_content.side_effect = APIError(400, "BAD_REQUEST")
    with pytest.raises(APIError):
        proxy.generate_content(model="model-x", prompt="hi")
        
    real_models.generate_content.side_effect = APIError(429, "RESOURCE_EXHAUSTED")
    with pytest.raises(APIError):
        proxy.generate_content(model="model-x", prompt="hi")
        
    real_models.embed_content.side_effect = side_effect
    assert proxy.embed_content(model="model-x", contents="hi") == "fallback_result"
    
    real_models.embed_content.side_effect = APIError(400, "BAD_REQUEST")
    with pytest.raises(APIError):
        proxy.embed_content(model="model-x", contents="hi")
        
    real_models.embed_content.side_effect = APIError(429, "RESOURCE_EXHAUSTED")
    with pytest.raises(APIError):
        proxy.embed_content(model="model-x", contents="hi")


@pytest.mark.asyncio
async def test_governed_async_models_proxy():
    real_models = MagicMock()
    real_models.some_attr = "async_value"
    proxy = GovernedAsyncModelsProxy(real_models, "caller-b")
    assert proxy.some_attr == "async_value"
    
    real_models.generate_content = AsyncMock(return_value="async_res")
    assert await proxy.generate_content(model="gemini-2.5-flash", prompt="hi") == "async_res"
    
    model_governance._fallback_chain = {"model-x": "model-y"}
    model_governance.RETRY_DELAY_SECONDS = 0.01
    
    call_count = 0
    async def side_effect(model, **kwargs):
        nonlocal call_count
        call_count += 1
        if model == "model-x":
            raise APIError(429, "RESOURCE_EXHAUSTED")
        return "async_fallback_res"
    real_models.generate_content.side_effect = side_effect
    
    assert await proxy.generate_content(model="model-x", prompt="hi") == "async_fallback_res"
    
    real_models.generate_content.side_effect = APIError(400, "BAD_REQUEST")
    with pytest.raises(APIError):
        await proxy.generate_content(model="model-x", prompt="hi")
        
    real_models.generate_content.side_effect = APIError(429, "RESOURCE_EXHAUSTED")
    with pytest.raises(APIError):
        await proxy.generate_content(model="model-x", prompt="hi")
        
    real_models.embed_content = AsyncMock(side_effect=side_effect)
    assert await proxy.embed_content(model="model-x", contents="hi") == "async_fallback_res"
    
    real_models.embed_content.side_effect = APIError(400, "BAD_REQUEST")
    with pytest.raises(APIError):
        await proxy.embed_content(model="model-x", contents="hi")
        
    real_models.embed_content.side_effect = APIError(429, "RESOURCE_EXHAUSTED")
    with pytest.raises(APIError):
        await proxy.embed_content(model="model-x", contents="hi")


def test_get_governed_client_fn():
    with patch("gemini_client_factory._get_raw_client", return_value=None):
        assert get_governed_client() is None
        
    mock_raw_client = MagicMock()
    mock_raw_client.some_attr = "raw_val"
    with patch("gemini_client_factory._get_raw_client", return_value=mock_raw_client):
        client = get_governed_client("caller-c")
        assert client is not None
        assert client.some_attr == "raw_val"
        assert isinstance(client.models, GovernedModelsProxy)


@pytest.mark.asyncio
async def test_governance_hooks():
    class HookInputMock:
        def __init__(self, tool_input, tool_name="test_tool"):
            self.tool_input = tool_input
            self.tool_name = tool_name
            
    model_governance._deprecation_map = {"old-model": "new-model"}
    hook_input = HookInputMock({"model": "old-model"})
    
    res = await _model_governance_hook(hook_input)
    assert res is not None
    assert res.updated_input == {"model": "new-model"}
    
    hook_input = HookInputMock({"model": "gemini-2.5-flash"})
    assert await _model_governance_hook(hook_input) is None
    
    hook_input_none = HookInputMock(None)
    assert await _model_governance_hook(hook_input_none) is None


@pytest.mark.asyncio
@patch("usage_tracker.tracker.usage_tracker")
async def test_usage_tracking_hook(mock_ut):
    class HookInputMock:
        def __init__(self, tool_input, tool_name="test_tool"):
            self.tool_input = tool_input
            self.tool_name = tool_name
            
    hook_input = HookInputMock({})
    assert await _model_usage_tracking_hook(hook_input) is None
    
    mock_ut.track_request.return_value = {"alert_level": "normal"}
    hook_input = HookInputMock({"model_name": "model-a"})
    assert await _model_usage_tracking_hook(hook_input) is None
    mock_ut.track_request.assert_called_with("model-a")
    
    mock_ut.track_request.return_value = {"alert_level": "critical", "usage_ratio": 1.0}
    hook_input = HookInputMock({"MODEL_NAME": "model-b"})
    assert await _model_usage_tracking_hook(hook_input) is None
    
    mock_ut.track_request.side_effect = OSError("OS error")
    hook_input = HookInputMock({"model": "model-c"})
    assert await _model_usage_tracking_hook(hook_input) is None


def test_register_governance_hook_fn():
    with patch("harness.hooks.hook_system") as mock_hs:
        register_governance_hook()
        assert mock_hs.register.call_count == 2
        
    with patch.dict("sys.modules", {"harness.hooks": None}):
        register_governance_hook()


def test_classify_error():
    proxy = GovernedModelsProxy(MagicMock(), "caller")
    
    # 429
    assert proxy._classify_error("429 error") == "429:枠枯渇"
    assert proxy._classify_error("RESOURCE_EXHAUSTED") == "429:枠枯渇"
    
    # 503
    assert proxy._classify_error("503 error") == "503:サーバー混雑"
    assert proxy._classify_error("UNAVAILABLE") == "503:サーバー混雑"
    
    # 404
    assert proxy._classify_error("404 error") == "404:モデル不在"
    assert proxy._classify_error("NOT_FOUND") == "404:モデル不在"
    
    # quota
    assert proxy._classify_error("limit: 0") == "quota=0:利用不可"
    assert proxy._classify_error("quota exceeded") == "quota=0:利用不可"
    
    # unknown
    assert proxy._classify_error("some random error") == "unknown:some random error"


def test_main_execution():
    import runpy
    import sys
    
    # 1. APIキーなしの場合
    with patch("gemini_client_factory._get_raw_client", return_value=None):
        orig_argv = sys.argv
        sys.argv = ["model_governance.py"]
        try:
            runpy.run_module("backend.model_governance", run_name="__main__")
        finally:
            sys.argv = orig_argv
            
    # 2. APIキーあり（成功）の場合
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Say OK response"
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        orig_argv = sys.argv
        sys.argv = ["model_governance.py"]
        try:
            runpy.run_module("backend.model_governance", run_name="__main__")
        finally:
            sys.argv = orig_argv
            
    # 3. APIキーあり（エラー）の場合
    mock_client_err = MagicMock()
    mock_client_err.models.generate_content.side_effect = RuntimeError("Mocked Live Error")
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client_err):
        orig_argv = sys.argv
        sys.argv = ["model_governance.py"]
        try:
            runpy.run_module("backend.model_governance", run_name="__main__")
        finally:
            sys.argv = orig_argv


@pytest.mark.asyncio
async def test_call_empty_fallback_sequence():
    from backend.model_governance import ModelGovernanceEngine
    engine = ModelGovernanceEngine()
    engine._task_mapping = {"test_task": "model-a"}
    engine._deprecation_map = {}
    engine._fallback_chain = {}
    
    with patch.object(engine, 'build_fallback_sequence', return_value=[]):
        with pytest.raises(TypeError):
            await engine.call(task="test_task", prompt="hello")


def test_governed_models_proxy_empty_fallback_sequence():
    from backend.model_governance import model_governance, GovernedModelsProxy
    mock_real_models = MagicMock()
    proxy = GovernedModelsProxy(mock_real_models, "caller")
    
    with patch.object(model_governance, 'build_fallback_sequence', return_value=[]):
        with pytest.raises(TypeError):
            proxy.generate_content(model="some-model")
            
        with pytest.raises(TypeError):
            proxy.embed_content(model="some-model", contents="hello")


@pytest.mark.asyncio
async def test_governed_async_models_proxy_empty_fallback_sequence():
    from backend.model_governance import model_governance, GovernedAsyncModelsProxy
    mock_real_models = AsyncMock()
    proxy = GovernedAsyncModelsProxy(mock_real_models, "caller")
    
    with patch.object(model_governance, 'build_fallback_sequence', return_value=[]):
        with pytest.raises(TypeError):
            await proxy.generate_content(model="some-model")
            
        with pytest.raises(TypeError):
            await proxy.embed_content(model="some-model", contents="hello")





