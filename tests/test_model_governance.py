import sys
import os
import json
import pytest
import asyncio
import runpy
from types import ModuleType
from pathlib import Path
from unittest.mock import patch, MagicMock
from google.genai.errors import APIError
from google.api_core.exceptions import GoogleAPICallError

# Path setup to include workspace root and backend directory
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from backend.model_governance import (
    ModelGovernanceEngine,
    GovernedModelsProxy,
    GovernedAsyncModelsProxy,
    get_governed_client,
    _model_governance_hook,
    _model_usage_tracking_hook,
    register_governance_hook,
    model_governance,
)


def test_load_config_errors():
    """model_config.json 読込時の例外ハンドリングテスト"""
    # 1. FileNotFoundError
    with patch("builtins.open", side_effect=FileNotFoundError("Config file not found")), \
         patch("backend.model_governance.logger") as mock_logger:
        engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
        engine._initialized = False
        engine.__init__()
        mock_logger.warning.assert_any_call("ModelGovernance: config file not found: Config file not found")

    # 2. JSONDecodeError
    with patch("builtins.open", side_effect=json.JSONDecodeError("Expecting value", "", 0)), \
         patch("backend.model_governance.logger") as mock_logger:
        engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
        engine._initialized = False
        engine.__init__()
        mock_logger.warning.assert_any_call(
            "ModelGovernance: config JSON decode failed: Expecting value: line 1 column 1 (char 0)"
        )

    # 3. PermissionError
    with patch("builtins.open", side_effect=PermissionError("Permission denied")), \
         patch("backend.model_governance.logger") as mock_logger:
        engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
        engine._initialized = False
        engine.__init__()
        mock_logger.warning.assert_any_call("ModelGovernance: config permission error: Permission denied")


def test_init_already_initialized():
    """すでに初期化済みの時の __init__ 早期 return (71行目カバー)"""
    engine = ModelGovernanceEngine()
    # 初期化済みフラグが真の状態で __init__ を呼び出す
    assert engine._initialized is True
    engine.__init__()  # 例外を出さずに早期リターンすること


def test_validate_and_correct():
    """deprecatedモデル差替ロジック of ModelGovernanceEngine"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    
    # テスト用deprecationマッピング設定
    engine._deprecation_map = {
        "gemini-2.0-flash": "gemini-3-flash-preview",
        "gemini-2.5-pro": "gemini-2.5-flash",
        "model-a": "model-b",
        "model-b": "model-c",
        "loop-a": "loop-b",
        "loop-b": "loop-a",  # 循環参照
    }
    
    # 正常系: 置換なし
    assert engine.validate_and_correct("gemini-2.5-flash") == "gemini-2.5-flash"
    
    # 正常系: 置換あり
    assert engine.validate_and_correct("gemini-2.0-flash") == "gemini-3-flash-preview"
    
    # チェーン置換
    assert engine.validate_and_correct("model-a") == "model-c"
    
    # 循環参照時の安全停止
    assert engine.validate_and_correct("loop-a") == "loop-a"


def test_fallback_chain_logic():
    """フォールバックチェーン構築とエラー判定のテスト"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    engine._fallback_chain = {
        "gemini-3-flash-preview": "gemini-2.5-flash",
        "gemini-2.5-flash": "gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite": None,
        "loop-a": "loop-b",
        "loop-b": "loop-a",  # 循環参照
    }

    # get_fallback
    assert engine.get_fallback("gemini-3-flash-preview") == "gemini-2.5-flash"
    assert engine.get_fallback("gemini-2.5-flash-lite") is None

    # is_fallback_error
    assert engine.is_fallback_error(Exception("RESOURCE_EXHAUSTED: Quota exceeded")) is True
    assert engine.is_fallback_error(Exception("UNAVAILABLE")) is True
    assert engine.is_fallback_error(Exception("Some other error")) is False

    # build_fallback_sequence
    assert engine.build_fallback_sequence("gemini-3-flash-preview") == [
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite"
    ]
    # 循環参照
    assert engine.build_fallback_sequence("loop-a") == ["loop-a", "loop-b"]


def test_event_log_and_stats():
    """監査ログトリムおよび統計取得テスト"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    
    # 200件を超えるログを追加してトリムされるか検証
    for i in range(250):
        engine._record_event("test", "orig", "res", "caller", f"error_{i}")
        
    assert len(engine._event_log) == 149
    assert engine._event_log[0]["error"] == "error_101"
    
    # get_stats
    stats = engine.get_stats()
    assert "deprecation_corrections" in stats
    assert len(stats["recent_events"]) == 10  # 最新10件のみ

    # reload
    with patch.object(engine, "_load_config") as mock_load:
        engine.reload()
        mock_load.assert_called_once()
        assert len(engine._deprecation_map) == 0
        assert len(engine._fallback_chain) == 0


def test_resolve_model():
    """_resolve_model の解決ロジックおよび枠枯渇自動降格のテスト"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    engine._task_mapping = {"test_task": "gemini-3-flash-preview"}
    engine._fallback_chain = {
        "gemini-3-flash-preview": "gemini-2.5-flash",
        "gemini-2.5-flash": "gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite": None
    }
    engine._default_model = "gemini-2.5-flash"
    # **差替表を空にする**（R1.5-C6）。ここで見たいのは枠枯渇による降格で
    # あって deprecated 差替ではない。実設定に gemini-2.5-* の差替行が
    # 入ったので、モデル名を素通しの目印に使えなくなった
    engine._deprecation_map = {}

    # usage_tracker モックモジュールの定義
    mock_tracker = MagicMock()
    mock_tracker.get_usage_ratio.return_value = 0.5  # format string バグの解消用
    mock_module = ModuleType("usage_tracker.tracker")
    mock_module.usage_tracker = mock_tracker

    sys_modules_patch = {
        "usage_tracker.tracker": mock_module,
        "backend.usage_tracker.tracker": mock_module
    }

    # usage_tracker 枠チェック正常系
    mock_tracker.can_make_request.side_effect = None
    mock_tracker.can_make_request.return_value = True
    with patch.dict("sys.modules", sys_modules_patch):
        assert engine._resolve_model("test_task", "gemini-2.5-flash-lite") == "gemini-2.5-flash-lite"
        assert engine._resolve_model("test_task") == "gemini-3-flash-preview"

    # 枠枯渇によるプロアクティブ自動降格 (254-258行目カバー)
    def mock_can_make_request(model_name):
        return model_name == "gemini-2.5-flash-lite"
    
    mock_tracker.can_make_request.side_effect = mock_can_make_request
    with patch.dict("sys.modules", sys_modules_patch):
        assert engine._resolve_model("test_task") == "gemini-2.5-flash-lite"
        
    # チェーン末端まで枯渇して break するケース (246行目カバー)
    mock_tracker.can_make_request.side_effect = None
    mock_tracker.can_make_request.return_value = False
    with patch.dict("sys.modules", sys_modules_patch):
        assert engine._resolve_model("test_task") == "gemini-2.5-flash-lite"

    # usage_tracker 未導入 (ImportError) のケース (260行目カバー)
    with patch.dict("sys.modules", {"usage_tracker": None, "usage_tracker.tracker": None, "backend.usage_tracker.tracker": None}):
        assert engine._resolve_model("test_task") == "gemini-3-flash-preview"

    # 例外発生時のセーフティガード
    mock_tracker.can_make_request.side_effect = AttributeError("Simulated tracking error")
    with patch.dict("sys.modules", sys_modules_patch):
        assert engine._resolve_model("test_task") == "gemini-3-flash-preview"


@pytest.mark.asyncio
async def test_call_gateway():
    """call() 統一APIゲートウェイの動作テスト"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    engine._fallback_chain = {
        "gemini-3-flash-preview": "gemini-2.5-flash",
        "gemini-2.5-flash": "gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite": None
    }
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Success OK"
    
    # 1回目は失敗、2回目で成功するフォールバック
    call_count = 0
    async def mock_generate_content(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise APIError(429, {"message": "RESOURCE_EXHAUSTED"})
        return mock_response

    mock_client.aio.models.generate_content.side_effect = mock_generate_content
    
    # config 引数指定あり
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client), \
         patch("asyncio.sleep", return_value=None):
        result = await engine.call(
            task="quality_gate", prompt="Hello", model="gemini-3-flash-preview", config={"temperature": 0.5}
        )
        assert result == "Success OK"
        assert call_count == 2
        
    # APIキー未設定 (client is None)
    with patch("gemini_client_factory._get_raw_client", return_value=None):
        with pytest.raises(ValueError, match="GOOGLE_API_KEY が未設定です"):
            await engine.call(task="quality_gate", prompt="Hello")

    # フォールバック対象外エラーの場合 (359行目カバー)
    mock_client.aio.models.generate_content.side_effect = RuntimeError("Fatal syntax error")
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Fatal syntax error"):
            await engine.call(task="quality_gate", prompt="Hello", model="gemini-3-flash-preview")

    # 全フォールバック枯渇
    async def mock_generate_content_all_fail(*args, **kwargs):
        raise APIError(503, {"message": "UNAVAILABLE"})
        
    mock_client.aio.models.generate_content.side_effect = mock_generate_content_all_fail
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client), \
         patch("asyncio.sleep", return_value=None):
        with pytest.raises(RuntimeError, match="全フォールバック枯渇"):
            await engine.call(task="quality_gate", prompt="Hello", model="gemini-3-flash-preview")

    # 同期クライアント呼び出し (aio 属性なし)
    mock_client_sync = MagicMock()
    del mock_client_sync.aio
    mock_client_sync.models.generate_content.return_value = mock_response
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client_sync):
        result = await engine.call(task="quality_gate", prompt="Hello", model="gemini-2.5-flash")
        assert result == "Success OK"

    # raise last_error 到達不能部分のカバー (393行目カバー)
    with patch.object(engine, "build_fallback_sequence", return_value=[]), \
         patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        with pytest.raises(TypeError, match="exceptions must derive from BaseException"):
            await engine.call(task="quality_gate", prompt="Hello")


def test_track_usage():
    """_track_usage 内部動作および例外ハンドリングテスト (397-408行目カバー)"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()

    mock_tracker = MagicMock()
    # 警告閾値到達時のイベント記録カバー
    mock_tracker.track_request.return_value = {"alert_level": "warning", "usage_ratio": 0.85}
    
    mock_module = ModuleType("usage_tracker.tracker")
    mock_module.usage_tracker = mock_tracker
    sys_modules_patch = {
        "usage_tracker.tracker": mock_module,
        "backend.usage_tracker.tracker": mock_module
    }

    with patch.dict("sys.modules", sys_modules_patch):
        engine._track_usage("gemini-2.5-flash", "test_caller")
        # イベントログに記録されたか検証
        assert engine._event_log[-1]["type"] == "quota_alert"

    # tracker での例外発生ハンドリング
    mock_tracker.track_request.side_effect = AttributeError("Simulated tracking error")
    with patch.dict("sys.modules", sys_modules_patch):
        # 例外を投げずに安全にスルーされること
        engine._track_usage("gemini-2.5-flash", "test_caller")


def test_governed_models_proxy():
    """同期プロキシのフォールバック動作および例外判定テスト"""
    real_models = MagicMock()
    proxy = GovernedModelsProxy(real_models, caller="test_sync")
    
    call_count = 0
    def mock_generate_content(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise APIError(429, {"message": "RESOURCE_EXHAUSTED"})
        return "OK"
        
    real_models.generate_content.side_effect = mock_generate_content
    with patch("backend.model_governance.time.sleep", return_value=None):
        res = proxy.generate_content(model="gemini-3-flash-preview")
        assert res == "OK"
        assert call_count == 2

    # フォールバック対象外エラー
    real_models.generate_content.side_effect = ValueError("Format error")
    with pytest.raises(ValueError):
        proxy.generate_content(model="gemini-3-flash-preview")

    # 全フォールバック枯渇
    real_models.generate_content.side_effect = APIError(503, {"message": "UNAVAILABLE"})
    with patch("backend.model_governance.time.sleep", return_value=None):
        with pytest.raises(APIError):
            proxy.generate_content(model="gemini-3-flash-preview")

    # __getattr__ 委譲確認
    real_models.custom_method.return_value = "custom"
    assert proxy.custom_method() == "custom"

    # classify_error 各分岐確認 (504-508行目カバー)
    assert proxy._classify_error(Exception("NOT_FOUND")) == "404:モデル不在"
    assert proxy._classify_error(Exception("quota exceeded")) == "quota=0:利用不可"
    assert proxy._classify_error(Exception("Some other unknown error")) == "unknown:Some other unknown error"

    # raise last_error 到達不能部分のカバー (495行目カバー)
    with patch.object(model_governance, "build_fallback_sequence", return_value=[]):
        with pytest.raises(TypeError, match="exceptions must derive from BaseException"):
            proxy.generate_content(model="gemini-3-flash-preview")


@pytest.mark.asyncio
async def test_governed_async_models_proxy():
    """非同期プロキシのフォールバック動作テスト"""
    real_models = MagicMock()
    proxy = GovernedAsyncModelsProxy(real_models, caller="test_async")
    
    call_count = 0
    async def mock_generate_content(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise APIError(429, {"message": "RESOURCE_EXHAUSTED"})
        return "OK"
        
    real_models.generate_content.side_effect = mock_generate_content
    with patch("asyncio.sleep", return_value=None):
        res = await proxy.generate_content(model="gemini-3-flash-preview")
        assert res == "OK"
        assert call_count == 2

    # フォールバック対象外エラー
    real_models.generate_content.side_effect = ValueError("Format error")
    with pytest.raises(ValueError):
        await proxy.generate_content(model="gemini-3-flash-preview")

    # 全フォールバック枯渇
    real_models.generate_content.side_effect = APIError(503, {"message": "UNAVAILABLE"})
    with patch("asyncio.sleep", return_value=None):
        with pytest.raises(APIError):
            await proxy.generate_content(model="gemini-3-flash-preview")

    # raise last_error 到達不能部分のカバー (579行目カバー)
    with patch.object(model_governance, "build_fallback_sequence", return_value=[]):
        with pytest.raises(TypeError, match="exceptions must derive from BaseException"):
            await proxy.generate_content(model="gemini-3-flash-preview")


def test_get_governed_client():
    """get_governed_client 動作テスト"""
    mock_raw = MagicMock()
    with patch("gemini_client_factory._get_raw_client", return_value=mock_raw):
        client = get_governed_client("test_client")
        assert client is not None
        assert isinstance(client.models, GovernedModelsProxy)
        
        # 属性アクセスの委譲
        mock_raw.test_attr = "val"
        assert client.test_attr == "val"
        
    with patch("gemini_client_factory._get_raw_client", return_value=None):
        assert get_governed_client("test_client") is None


@pytest.mark.asyncio
async def test_harness_hooks():
    """ハーネスフックとの統合テスト"""
    # PRE_TOOL_USE フック
    mock_input = MagicMock()
    mock_input.tool_name = "test_tool"
    mock_input.tool_input = {"model": "gemini-2.0-flash"}
    
    mock_hook_output = MagicMock()
    with patch.dict("sys.modules", {"harness.hooks": MagicMock(HookOutput=mock_hook_output)}):
        await _model_governance_hook(mock_input)
        # **行き先は現行の段**（R1.5-C6）。2026-08-28 まで
        # gemini-2.0-flash -> gemini-3-flash-preview と書かれていたが、
        # 3-flash-preview は preview のまま取り残されていた
        mock_hook_output.assert_called_once_with(updated_input={"model": "gemini-3.6-flash"})
        
    # 置換不要時（**差替表に載っていないモデルを使う**。gemini-2.5-flash は
    # 2026-08-28 に差替対象へ入ったので、もう「置換不要」の目印にならない）
    mock_input.tool_input = {"model": "gemini-3.6-flash"}
    res = await _model_governance_hook(mock_input)
    assert res is None

    # POST_TOOL_USE フック
    mock_tracker = MagicMock()
    mock_tracker.track_request.return_value = {"alert_level": "warning", "usage_ratio": 0.85}
    mock_input.tool_input = {"model": "gemini-2.5-flash"}
    
    mock_module = ModuleType("usage_tracker.tracker")
    mock_module.usage_tracker = mock_tracker
    sys_modules_patch = {
        "usage_tracker.tracker": mock_module,
        "backend.usage_tracker.tracker": mock_module
    }

    with patch.dict("sys.modules", sys_modules_patch):
        await _model_usage_tracking_hook(mock_input)
        mock_tracker.track_request.assert_called_once_with("gemini-2.5-flash")
        
    # POST_TOOL_USE モデル名関連キーなし (659行目カバー)
    mock_input.tool_input = {"other_param": "val"}
    res = await _model_usage_tracking_hook(mock_input)
    assert res is None

    # POST_TOOL_USE trackerでのエラーハンドリング (674-675行目カバー)
    mock_input.tool_input = {"model": "gemini-2.5-flash"}
    with patch.dict("sys.modules", {"usage_tracker.tracker": None, "backend.usage_tracker.tracker": None}):
        res = await _model_usage_tracking_hook(mock_input)
        assert res is None

    # 登録フック
    mock_hook_system = MagicMock()
    mock_hook_event = MagicMock()
    with patch.dict("sys.modules", {"harness.hooks": MagicMock(hook_system=mock_hook_system, HookEvent=mock_hook_event)}):
        register_governance_hook()
        assert mock_hook_system.register.call_count == 2

    # register_governance_hook Harness未定義 (703-704行目カバー)
    with patch.dict("sys.modules", {"harness.hooks": None}):
        register_governance_hook()  # エラーにならずにスルーされること


def test_main_execution():
    """main ブロックの実行カバー (712-762行目カバー)"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Success OK"
    mock_client.models.generate_content.return_value = mock_response
    
    # 1. 正常系
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client), \
         patch("builtins.print") as mock_print:
        # runpy で直接実行時と同様に __main__ 実行をシミュレート
        runpy.run_module("backend.model_governance", run_name="__main__")
        
    # 2. 呼び出し例外発生系 (753行目カバー)
    mock_client.models.generate_content.side_effect = RuntimeError("API Call Failed")
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client), \
         patch("builtins.print") as mock_print:
        runpy.run_module("backend.model_governance", run_name="__main__")
        
    # 3. APIキーなし系 (755-756行目カバー)
    with patch("gemini_client_factory._get_raw_client", return_value=None), \
         patch("builtins.print") as mock_print:
        runpy.run_module("backend.model_governance", run_name="__main__")


def test_call_gateway_non_fallback_error():
    """ModelGovernanceEngine.call で is_fallback_error が False のエラーが発生した場合"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    engine._fallback_chain = {
        "gemini-3-flash-preview": "gemini-2.5-flash",
    }
    
    mock_client = MagicMock()
    # 400 Bad Request を模した APIError
    non_fallback_error = APIError(400, {"message": "INVALID_ARGUMENT"})
    
    async def mock_generate_content(*args, **kwargs):
        raise non_fallback_error

    mock_client.aio.models.generate_content.side_effect = mock_generate_content
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        with pytest.raises(APIError) as excinfo:
            asyncio.run(engine.call(
                task="quality_gate", prompt="Hello", model="gemini-3-flash-preview"
            ))
        assert excinfo.value.code == 400
        # イベントログに api_error が記録されていることを確認
        assert any(e["type"] == "api_error" for e in engine._event_log)


def test_governed_models_proxy_non_fallback_error():
    """GovernedModelsProxy.generate_content で is_fallback_error が False のエラーが発生した場合"""
    real_models = MagicMock()
    proxy = GovernedModelsProxy(real_models, caller="test_sync")
    
    non_fallback_error = APIError(400, {"message": "INVALID_ARGUMENT"})
    real_models.generate_content.side_effect = non_fallback_error
    
    with pytest.raises(APIError) as excinfo:
        proxy.generate_content(model="gemini-3-flash-preview")
    assert excinfo.value.code == 400


def test_governed_models_proxy_embed_content():
    """GovernedModelsProxy.embed_content の各ブランチ（正常系、非対象エラー、フォールバック成功、枯渇）"""
    real_models = MagicMock()
    proxy = GovernedModelsProxy(real_models, caller="test_sync_embed")
    
    # 1. 正常系
    real_models.embed_content.return_value = "EmbedResult"
    res = proxy.embed_content(model="gemini-3-flash-preview", contents="text")
    assert res == "EmbedResult"
    real_models.embed_content.assert_called_with(model="gemini-3-flash-preview", contents="text")
    
    # 2. 非対象エラー (is_fallback_error == False)
    non_fallback_error = APIError(400, {"message": "INVALID_ARGUMENT"})
    real_models.embed_content.side_effect = non_fallback_error
    with pytest.raises(APIError):
        proxy.embed_content(model="gemini-3-flash-preview", contents="text")
        
    # 3. フォールバック成功
    call_count = 0
    def mock_embed_content(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise APIError(429, {"message": "RESOURCE_EXHAUSTED"})
        return "EmbedResult2"
    real_models.embed_content.side_effect = mock_embed_content
    with patch("backend.model_governance.time.sleep", return_value=None):
        res = proxy.embed_content(model="gemini-3-flash-preview", contents="text")
        assert res == "EmbedResult2"
        assert call_count == 2

    # 4. 全フォールバック枯渇
    real_models.embed_content.side_effect = APIError(503, {"message": "UNAVAILABLE"})
    with patch("backend.model_governance.time.sleep", return_value=None):
        with pytest.raises(APIError):
            proxy.embed_content(model="gemini-3-flash-preview", contents="text")


@pytest.mark.asyncio
async def test_governed_async_models_proxy_non_fallback_error():
    """GovernedAsyncModelsProxy.generate_content で is_fallback_error が False のエラーが発生した場合"""
    real_models = MagicMock()
    proxy = GovernedAsyncModelsProxy(real_models, caller="test_async")
    
    non_fallback_error = APIError(400, {"message": "INVALID_ARGUMENT"})
    async def mock_generate_content(*args, **kwargs):
        raise non_fallback_error
    real_models.generate_content.side_effect = mock_generate_content
    
    with pytest.raises(APIError) as excinfo:
        await proxy.generate_content(model="gemini-3-flash-preview")
    assert excinfo.value.code == 400


@pytest.mark.asyncio
async def test_governed_async_models_proxy_embed_content():
    """GovernedAsyncModelsProxy.embed_content の各ブランチ（正常系、非対象エラー、フォールバック成功、枯渇）"""
    real_models = MagicMock()
    proxy = GovernedAsyncModelsProxy(real_models, caller="test_async_embed")
    
    # 1. 正常系
    async def mock_embed_content_success(*args, **kwargs):
        return "EmbedResultAsync"
    real_models.embed_content.side_effect = mock_embed_content_success
    res = await proxy.embed_content(model="gemini-3-flash-preview", contents="text")
    assert res == "EmbedResultAsync"
    
    # 2. 非対象エラー
    non_fallback_error = APIError(400, {"message": "INVALID_ARGUMENT"})
    async def mock_embed_content_error(*args, **kwargs):
        raise non_fallback_error
    real_models.embed_content.side_effect = mock_embed_content_error
    with pytest.raises(APIError):
        await proxy.embed_content(model="gemini-3-flash-preview", contents="text")
        
    # 3. フォールバック成功
    call_count = 0
    async def mock_embed_content_fallback(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise APIError(429, {"message": "RESOURCE_EXHAUSTED"})
        return "EmbedResultAsync2"
    real_models.embed_content.side_effect = mock_embed_content_fallback
    with patch("asyncio.sleep", return_value=None):
        res = await proxy.embed_content(model="gemini-3-flash-preview", contents="text")
        assert res == "EmbedResultAsync2"
        assert call_count == 2

    # 4. 全フォールバック枯渇
    async def mock_embed_content_exhausted(*args, **kwargs):
        raise APIError(503, {"message": "UNAVAILABLE"})
    real_models.embed_content.side_effect = mock_embed_content_exhausted
    with patch("asyncio.sleep", return_value=None):
        with pytest.raises(APIError):
            await proxy.embed_content(model="gemini-3-flash-preview", contents="text")


def test_governed_async_models_proxy_getattr():
    """GovernedAsyncModelsProxy.__getattr__ の挙動確認"""
    real_models = MagicMock()
    real_models.some_custom_attribute = "CustomVal"
    proxy = GovernedAsyncModelsProxy(real_models, caller="test_async")
    assert proxy.some_custom_attribute == "CustomVal"


def test_governed_models_proxy_embed_content_unreachable_raise():
    """GovernedModelsProxy.embed_content の raise last_error 部分のカバー (563行目カバー)"""
    real_models = MagicMock()
    proxy = GovernedModelsProxy(real_models, caller="test_sync")
    with patch.object(model_governance, "build_fallback_sequence", return_value=[]):
        with pytest.raises(TypeError, match="exceptions must derive from BaseException"):
            proxy.embed_content(model="gemini-3-flash-preview", contents="text")


@pytest.mark.asyncio
async def test_governed_async_models_proxy_embed_content_unreachable_raise():
    """GovernedAsyncModelsProxy.embed_content の raise last_error 部分のカバー (707行目カバー)"""
    real_models = MagicMock()
    proxy = GovernedAsyncModelsProxy(real_models, caller="test_async")
    with patch.object(model_governance, "build_fallback_sequence", return_value=[]):
        with pytest.raises(TypeError, match="exceptions must derive from BaseException"):
            await proxy.embed_content(model="gemini-3-flash-preview", contents="text")


def test_validate_correct_edge_cases():
    """validate_and_correct に None や不正な型、巨大文字列を渡した場合のエッジケース"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    engine._deprecation_map = {
        "gemini-2.0-flash": "gemini-3-flash-preview",
    }

    # 1. None 入力 (deprecation_map になければそのまま返る)
    assert engine.validate_and_correct(None) is None

    # 2. 不正な型（整数、辞書、リスト）
    assert engine.validate_and_correct(123) == 123
    assert engine.validate_and_correct(True) is True
    # 辞書やリストはハッシュ不可なので TypeError が発生する
    with pytest.raises(TypeError):
        engine.validate_and_correct([])
    with pytest.raises(TypeError):
        engine.validate_and_correct({})

    # 3. 巨大入力 (10万文字のモデル名)
    huge_model = "a" * 100000
    assert engine.validate_and_correct(huge_model) == huge_model


def test_get_fallback_edge_cases():
    """get_fallback に None や不正な型を渡した場合"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    engine._fallback_chain = {
        "model-a": "model-b",
    }

    # None や不正な型は辞書の get で単に None が返る
    assert engine.get_fallback(None) is None
    assert engine.get_fallback(123) is None
    # 辞書やリストはハッシュ不可なので TypeError
    with pytest.raises(TypeError):
        engine.get_fallback([])


def test_build_fallback_sequence_edge_cases():
    """build_fallback_sequence に None や不正な型を渡した場合"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    engine._fallback_chain = {
        "model-a": "model-b",
    }

    # None や不正型は fallback_chain にないので [start_model] が返る
    assert engine.build_fallback_sequence(None) == [None]
    assert engine.build_fallback_sequence(123) == [123]
    with pytest.raises(TypeError):
        engine.build_fallback_sequence([])


def test_is_fallback_error_edge_cases():
    """is_fallback_error に None や文字列化でエラーになる不正な型を渡した場合"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()

    # None -> "None" となりキーワードにマッチしないので False
    assert engine.is_fallback_error(None) is False
    # 辞書やリスト
    assert engine.is_fallback_error([]) is False
    assert engine.is_fallback_error({}) is False
    
    # 境界値: キーワードを一部含むが完全一致しないもの
    assert engine.is_fallback_error(Exception("RESOURCE_EXHAUST")) is False
    # 境界値: キーワードを含む
    assert engine.is_fallback_error(Exception("RESOURCE_EXHAUSTED")) is True


def test_resolve_model_edge_cases():
    """_resolve_model に None や空文字列、不正型を渡した場合"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    engine._default_model = "gemini-2.5-flash"

    # task が None の場合、default_model が使われる
    assert engine._resolve_model(None) == "gemini-2.5-flash"
    # model が明示指定された場合 (None 以外)、それが最優先される
    assert engine._resolve_model("some_task", model="custom-model") == "custom-model"
    # task, model ともに None の場合
    assert engine._resolve_model(None, model=None) == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_call_gateway_edge_cases():
    """call() に極端な入力値を渡した場合の挙動"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "OK"
    
    async def mock_generate_content_success(*args, **kwargs):
        return mock_response
    mock_client.aio.models.generate_content.side_effect = mock_generate_content_success

    # 1. 巨大なプロンプト入力
    huge_prompt = "p" * 1000000
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        res = await engine.call(task="proofreader", prompt=huge_prompt)
        assert res == "OK"

    # 2. prompt が None (通常は str だが、不正型に対する堅牢性検証)
    mock_client.aio.models.generate_content.side_effect = TypeError("contents must be string")
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        with pytest.raises(TypeError, match="contents must be string"):
            await engine.call(task="proofreader", prompt=None)


def test_event_log_truncation_huge_input():
    """_record_event に非常に長いエラー文を渡した場合に 200 文字に切り詰められるか"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()

    huge_error = "E" * 100000
    engine._record_event("api_error", "original", "resolved", "caller", error=huge_error)
    assert len(engine._event_log) == 1
    recorded_error = engine._event_log[0]["error"]
    assert len(recorded_error) == 200
    assert recorded_error == "E" * 200


def test_load_config_invalid_json_type():
    """model_config.json の中身が辞書ではなくリストなどの場合の例外ハンドリング"""
    from unittest.mock import mock_open
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    with patch("builtins.open", mock_open(read_data="[1, 2, 3]")), \
         pytest.raises(AttributeError):
        engine.__init__()


def test_validate_and_correct_triple_loop():
    """3つ以上のモデルによる循環参照チェーンのテスト"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    engine._deprecation_map = {
        "model-a": "model-b",
        "model-b": "model-c",
        "model-c": "model-a",
    }
    assert engine.validate_and_correct("model-a") == "model-a"


def test_record_event_non_str_error():
    """_record_event に非文字列のエラーオブジェクトが渡された場合"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    with pytest.raises(TypeError):
        engine._record_event("api_error", "original", "resolved", "caller", error=Exception("error"))


def test_proxy_getattr_missing_attribute():
    """プロキシ経由で存在しない属性にアクセスしたときに AttributeError が発生するか"""
    real_models = MagicMock()
    real_models.non_existent_method = MagicMock()
    del real_models.non_existent_method
    
    proxy = GovernedModelsProxy(real_models, caller="test")
    with pytest.raises(AttributeError):
        _ = proxy.non_existent_method

    async_proxy = GovernedAsyncModelsProxy(real_models, caller="test")
    with pytest.raises(AttributeError):
        _ = async_proxy.non_existent_method


@pytest.mark.asyncio
async def test_hooks_invalid_inputs():
    """フック関数に不正な入力を渡した場合"""
    # 1. tool_input が None
    mock_input = MagicMock()
    mock_input.tool_input = None
    mock_input.tool_name = "test_tool"
    assert await _model_governance_hook(mock_input) is None
    assert await _model_usage_tracking_hook(mock_input) is None

    # 2. tool_input が辞書ではない（文字列など）
    mock_input.tool_input = "invalid_string_input"
    with pytest.raises(AttributeError):
        await _model_usage_tracking_hook(mock_input)


def test_singleton_thread_safety():
    """ModelGovernanceEngine がマルチスレッド環境下で同時に初期化された場合でも同一インスタンスを返すか"""
    import threading
    instances = []
    def create_instance():
        inst = ModelGovernanceEngine()
        instances.append(inst)

    threads = [threading.Thread(target=create_instance) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(instances) == 10
    first_instance = instances[0]
    for inst in instances:
        assert inst is first_instance


def test_is_fallback_error_special_exception():
    """is_fallback_error に文字列化で例外を投げるオブジェクトが渡された場合の堅牢性"""
    class BadException(Exception):
        def __str__(self):
            raise RuntimeError("Cannot convert to string")

    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    with pytest.raises(RuntimeError, match="Cannot convert to string"):
        engine.is_fallback_error(BadException())


def test_record_event_none_arguments():
    """_record_event に None 引数が渡された場合の挙動"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    
    engine._record_event(None, None, None, None, error=None)
    assert len(engine._event_log) == 1
    event = engine._event_log[0]
    assert event["type"] is None
    assert event["original"] is None
    assert event["resolved"] is None
    assert event["caller"] is None
    assert event["error"] == ""


def test_get_governed_client_invalid_args():
    """get_governed_client に None や数値など不正な caller を渡した場合の挙動"""
    mock_raw = MagicMock()
    with patch("gemini_client_factory._get_raw_client", return_value=mock_raw):
        client = get_governed_client(None)
        assert client is not None
        assert client.models._caller is None

        client_int = get_governed_client(12345)
        assert client_int is not None
        assert client_int.models._caller == 12345


def test_validate_and_correct_edge_cases():
    """validate_and_correct に対する極端な入力値のエッジケース"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    
    # 巨大な文字列
    huge_model = "gemini-2.5-flash-" + ("x" * 10000)
    assert engine.validate_and_correct(huge_model) == huge_model
    
    # 不正だがハッシュ可能な型 (整数)
    assert engine.validate_and_correct(12345) == 12345
        
    # 不正かつハッシュ不可能な型 (リスト)
    with pytest.raises(TypeError):
        engine.validate_and_correct(["invalid", "list"])


def test_record_event_trimming_boundary():
    """_record_event のログ制限(200件)の境界値テスト"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    
    # 200件まではそのまま記録される
    for i in range(200):
        engine._record_event("test_type", f"orig_{i}", f"res_{i}", "caller")
    assert len(engine._event_log) == 200
    
    # 201件目が記録された瞬間、直近の100件にトリミングされる
    engine._record_event("test_type", "orig_201", "res_201", "caller")
    assert len(engine._event_log) == 100
    
    # 残っている最後のイベントは追加したばかりの orig_201 であること
    assert engine._event_log[-1]["original"] == "orig_201"
    # 残っている最初のイベントは orig_101 であること
    assert engine._event_log[0]["original"] == "orig_101"


def test_record_event_error_truncation():
    """_record_event で error 引数が200文字を超える場合の境界値テスト"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    
    # 199文字
    err_199 = "e" * 199
    engine._record_event("type", "orig", "res", "caller", error=err_199)
    assert len(engine._event_log[0]["error"]) == 199
    
    # 200文字
    err_200 = "e" * 200
    engine._record_event("type", "orig", "res", "caller", error=err_200)
    assert len(engine._event_log[1]["error"]) == 200
    
    # 201文字
    err_201 = "e" * 201
    engine._record_event("type", "orig", "res", "caller", error=err_201)
    assert len(engine._event_log[2]["error"]) == 200
    assert engine._event_log[2]["error"] == "e" * 200


def test_build_fallback_sequence_edge_cases():
    """build_fallback_sequence に対する極端な入力のエッジケース"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()

    # None を指定した場合、[None] が返る
    assert engine.build_fallback_sequence(None) == [None]

    # 空文字を指定した場合、[""] が返る
    assert engine.build_fallback_sequence("") == [""]

    # ハッシュ不可能な型（リストなど）を指定した場合、辞書 get がハッシュエラー (TypeError) を投げること
    with pytest.raises(TypeError):
        engine.build_fallback_sequence(["unhashable", "list"])


def test_resolve_model_edge_cases():
    """_resolve_model に対する極端な入力のエッジケース"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()

    # taskが空文字列の場合、デフォルトモデルが返る
    assert engine._resolve_model("") == "gemini-2.5-flash"

    # model引数が空文字列（falsy）の場合、default_model（"gemini-2.5-flash"）が返るのが仕様
    assert engine._resolve_model("some_task", "") == "gemini-2.5-flash"

    # ハッシュ不可能な task を指定した場合に TypeError が発生すること
    with pytest.raises(TypeError):
        engine._resolve_model(["unhashable"])


@pytest.mark.asyncio
async def test_engine_call_edge_cases():
    """call メソッド of ModelGovernanceEngine - config 等のエッジケース"""
    from unittest.mock import AsyncMock
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()

    # GOOGLE_API_KEY が未設定（client が None）の場合
    with patch("gemini_client_factory._get_raw_client", return_value=None):
        with pytest.raises(ValueError, match="GOOGLE_API_KEY が未設定です"):
            await engine.call(task="test", prompt="hello")

    # config が空辞書の場合と、不正な型（リスト等）の場合
    mock_client = MagicMock()
    mock_client.aio = MagicMock()
    mock_client.aio.models = AsyncMock()
    
    # config = {} (空)
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        await engine.call(task="test", prompt="hello", config={})
        mock_client.aio.models.generate_content.assert_called()

    # config = 12345 (辞書ではない場合: dict.update が TypeError を投げる)
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        with pytest.raises(TypeError):
            await engine.call(task="test", prompt="hello", config=12345)


def test_validate_and_correct_multi_loop():
    """多段階の循環参照チェーンに対する validate_and_correct の挙動"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()
    # A -> B -> C -> D -> E -> A などの循環
    engine._deprecation_map = {
        "model-a": "model-b",
        "model-b": "model-c",
        "model-c": "model-d",
        "model-d": "model-e",
        "model-e": "model-a",
    }
    assert engine.validate_and_correct("model-a") == "model-a"


def test_is_fallback_error_case_sensitivity():
    """is_fallback_error の大文字小文字の差異に対する挙動"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()

    # 現状の仕様では、FALLBACK_ERROR_KEYWORDS はすべて大文字（例: RESOURCE_EXHAUSTED）
    # 大文字が含まれている場合は True になる
    assert engine.is_fallback_error(Exception("This is a RESOURCE_EXHAUSTED error")) is True
    
    # 小文字の場合はマッチしない (仕様の確認)
    assert engine.is_fallback_error(Exception("This is a resource_exhausted error")) is False


def test_track_usage_alert_levels():
    """_track_usage の usage_tracker アラートレベル別挙動テスト"""
    engine = ModelGovernanceEngine.__new__(ModelGovernanceEngine)
    engine._initialized = False
    engine.__init__()

    mock_tracker = MagicMock()
    mock_module = ModuleType("usage_tracker.tracker")
    mock_module.usage_tracker = mock_tracker
    sys_modules_patch = {
        "usage_tracker.tracker": mock_module,
        "backend.usage_tracker.tracker": mock_module
    }

    # 1. block の場合
    mock_tracker.track_request.return_value = {"alert_level": "block", "usage_ratio": 1.0}
    with patch.dict("sys.modules", sys_modules_patch):
        engine._track_usage("gemini-2.5-flash", "test_caller")
        assert engine._event_log[-1]["type"] == "quota_alert"
        assert "alert_level=block" in engine._event_log[-1]["error"]

    # 2. critical の場合
    mock_tracker.track_request.return_value = {"alert_level": "critical", "usage_ratio": 1.2}
    with patch.dict("sys.modules", sys_modules_patch):
        engine._track_usage("gemini-2.5-flash", "test_caller")
        assert engine._event_log[-1]["type"] == "quota_alert"
        assert "alert_level=critical" in engine._event_log[-1]["error"]

    # 3. info の場合（警告対象外のため、イベントログは追加されない）
    initial_log_len = len(engine._event_log)
    mock_tracker.track_request.return_value = {"alert_level": "info", "usage_ratio": 0.2}
    with patch.dict("sys.modules", sys_modules_patch):
        engine._track_usage("gemini-2.5-flash", "test_caller")
        assert len(engine._event_log) == initial_log_len


def test_retry_delay_execution():
    """フォールバックチェーン実行時のリトライディレイ時間の適用検証"""
    real_models = MagicMock()
    proxy = GovernedModelsProxy(real_models, caller="test_sync")

    call_count = 0
    def mock_generate_content(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise APIError(429, {"message": "RESOURCE_EXHAUSTED"})
        return "OK"

    real_models.generate_content.side_effect = mock_generate_content

    # 429 は同じモデルで待って再試行する（降格はその後）。
    # 待ち時間はジッターで散るので固定値では比較できない。
    # RETRY_DELAY_SECONDS=2 → 初回の待ちは equal jitter で [1, 2] に入る。
    with patch("backend.model_governance.time.sleep") as mock_sleep:
        res = proxy.generate_content(model="gemini-3-flash-preview")
        assert res == "OK"
        mock_sleep.assert_called_once()
        assert 1.0 <= mock_sleep.call_args.args[0] <= 2.0


def test_governed_client_getattr_delegation():
    """get_governed_client が返すクライアントが models 以外の属性を正しく委譲すること"""
    mock_raw = MagicMock()
    mock_raw.some_other_method.return_value = "raw_value"
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_raw):
        client = get_governed_client("test_client")
        assert client is not None
        assert client.some_other_method() == "raw_value"
        mock_raw.some_other_method.assert_called_once()

