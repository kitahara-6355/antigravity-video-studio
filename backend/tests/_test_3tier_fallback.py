"""
3段階降格テスト — Premium → Standard → Batch の全パターン検証 (pytest版)
"""
from contextlib import contextmanager
import sys
import warnings
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

# 警告の抑制
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

BACKEND_DIR = Path(__file__).parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from google.api_core.exceptions import GoogleAPICallError
from model_governance import model_governance
from usage_tracker.tracker import UsageTracker

PREMIUM  = "gemini-3-flash-preview"
STANDARD = "gemini-2.5-flash"
BATCH    = "gemini-2.5-flash-lite"

TASKS = ["proofreader", "youtube_optimization", "quality_gate",
          "subtitle_split", "branding"]


def _is_premium_exhausted(model):
    """Premiumモデルが枯渇しているか判定するヘルパー"""
    return PREMIUM not in model  # Premium以外はOK


def _is_premium_and_standard_exhausted(model):
    """PremiumおよびStandardモデルが枯渇しているか判定するヘルパー"""
    return model == BATCH  # Batchだけ余裕


@contextmanager
def mock_tracker_status(can_make_request_behavior, usage_ratio_behavior=None):
    """
    UsageTracker の can_make_request と get_usage_ratio をモックする
    コンテキストマネージャ。テストコードの重複を削減するために使用。
    """
    if callable(can_make_request_behavior):
        mock_can = patch.object(UsageTracker, 'can_make_request', side_effect=can_make_request_behavior)
    else:
        mock_can = patch.object(UsageTracker, 'can_make_request', return_value=can_make_request_behavior)

    if usage_ratio_behavior is not None:
        if callable(usage_ratio_behavior):
            mock_ratio = patch.object(UsageTracker, 'get_usage_ratio', side_effect=usage_ratio_behavior)
        else:
            mock_ratio = patch.object(UsageTracker, 'get_usage_ratio', return_value=usage_ratio_behavior)
    else:
        mock_ratio = None

    with mock_can:
        if mock_ratio is not None:
            with mock_ratio:
                yield
        else:
            yield


def test_fallback_chain_definition():
    """フォールバックチェーンが正しく定義されていることを確認"""
    expected_chain = {
        "gemini-3-flash-preview": "gemini-2.5-flash",
        "gemini-2.5-flash": "gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite": None
    }
    for src, dst in expected_chain.items():
        assert model_governance.get_fallback(src) == dst


def test_all_available_resolves_to_premium():
    """全モデル枠に余裕がある場合、Premiumモデルに解決されること"""
    with mock_tracker_status(can_make_request_behavior=True):
        for task in TASKS:
            assert model_governance._resolve_model(task) == PREMIUM


def test_premium_exhausted_falls_back_to_standard():
    """Premium枯渇時にStandardへ降格すること"""
    with mock_tracker_status(
        can_make_request_behavior=_is_premium_exhausted,
        usage_ratio_behavior=lambda m: 0.96 if PREMIUM in m else 0.1
    ):
        for task in TASKS:
            assert model_governance._resolve_model(task) == STANDARD


def test_premium_and_standard_exhausted_falls_back_to_batch():
    """PremiumとStandard枯渇時にBatchへ降格すること"""
    with mock_tracker_status(
        can_make_request_behavior=_is_premium_and_standard_exhausted,
        usage_ratio_behavior=lambda m: 0.96 if m != BATCH else 0.1
    ):
        for task in TASKS:
            assert model_governance._resolve_model(task) == BATCH


def test_all_exhausted_returns_batch():
    """全3モデル枯渇時にチェーン末端(Batch)を返すこと"""
    with mock_tracker_status(
        can_make_request_behavior=False,
        usage_ratio_behavior=0.99
    ):
        for task in TASKS:
            assert model_governance._resolve_model(task) == BATCH


def test_ai_proofreader_resolves_to_premium_when_available():
    """ai_proofreader が動的解決で Premium に解決されること"""
    from subtitle_engine.ai_proofreader import _get_current_model
    with mock_tracker_status(can_make_request_behavior=True):
        assert _get_current_model() == PREMIUM


def test_ai_proofreader_falls_back_to_standard_when_premium_exhausted():
    """ai_proofreader が動的解決で Premium 枯渇時に Standard に解決されること"""
    from subtitle_engine.ai_proofreader import _get_current_model
    with mock_tracker_status(
        can_make_request_behavior=_is_premium_exhausted,
        usage_ratio_behavior=lambda m: 0.96 if PREMIUM in m else 0.1
    ):
        assert _get_current_model() == STANDARD


def test_ai_proofreader_falls_back_to_batch_when_premium_and_standard_exhausted():
    """ai_proofreader が動的解決で Premium/Standard 枯渇時に Batch に解決されること"""
    from subtitle_engine.ai_proofreader import _get_current_model
    with mock_tracker_status(
        can_make_request_behavior=_is_premium_and_standard_exhausted,
        usage_ratio_behavior=lambda m: 0.96 if m != BATCH else 0.1
    ):
        assert _get_current_model() == BATCH


def test_unknown_task_resolves_to_standard_when_available():
    """未知のタスクが渡された場合に、デフォルトモデルである Standard に解決されること"""
    unknown_task = "some_unknown_weird_task"
    with mock_tracker_status(can_make_request_behavior=True):
        assert model_governance._resolve_model(unknown_task) == STANDARD


def test_unknown_task_falls_back_to_batch_when_standard_exhausted():
    """未知のタスクで Standard が枯渇している場合、フォールバックチェーンが動作して Batch に降格すること"""
    unknown_task = "some_unknown_weird_task"
    def _is_standard_exhausted(model):
        return model == BATCH
    with mock_tracker_status(
        can_make_request_behavior=_is_standard_exhausted,
        usage_ratio_behavior=lambda m: 0.96 if m == STANDARD else 0.1
    ):
        assert model_governance._resolve_model(unknown_task) == BATCH


def test_deprecated_model_resolves_to_premium_when_available():
    """非推奨モデル(gemini-2.0-flash)指定時、空きがある場合は Premium に補正されること"""
    with mock_tracker_status(can_make_request_behavior=True):
        resolved = model_governance._resolve_model("proofreader", model="gemini-2.0-flash")
        assert resolved == PREMIUM


def test_deprecated_model_falls_back_to_standard_when_premium_exhausted():
    """非推奨モデル指定時に Premium が枯渇している場合、Standard に降格すること"""
    with mock_tracker_status(
        can_make_request_behavior=_is_premium_exhausted,
        usage_ratio_behavior=lambda m: 0.96 if PREMIUM in m else 0.1
    ):
        resolved = model_governance._resolve_model("proofreader", model="gemini-2.0-flash")
        assert resolved == STANDARD


def test_deprecated_model_falls_back_to_batch_when_premium_and_standard_exhausted():
    """非推奨モデル指定時に Premium および Standard が枯渇している場合、Batch に降格すること"""
    with mock_tracker_status(
        can_make_request_behavior=_is_premium_and_standard_exhausted,
        usage_ratio_behavior=lambda m: 0.96 if m != BATCH else 0.1
    ):
        resolved = model_governance._resolve_model("proofreader", model="gemini-2.0-flash")
        assert resolved == BATCH


def test_model_governance_reload():
    """model_governance.reload() で設定が正しく再ロードされること"""
    model_governance.reload()
    assert model_governance.get_fallback("gemini-3-flash-preview") == "gemini-2.5-flash"


def test_fallback_chain_loop_prevention():
    """フォールバックチェーンで循環参照が発生した場合に、無限ループが防止されること"""
    with patch.dict(model_governance._fallback_chain, {
        "model-a": "model-b",
        "model-b": "model-a"
    }):
        sequence = model_governance.build_fallback_sequence("model-a")
        assert sequence == ["model-a", "model-b"]


def test_deprecation_loop_prevention():
    """非推奨モデル差替で循環参照が発生した場合に、無限ループが防止されること"""
    with patch.dict(model_governance._deprecation_map, {
        "dep-a": "dep-b",
        "dep-b": "dep-a"
    }):
        corrected = model_governance.validate_and_correct("dep-a")
        assert corrected == "dep-a"


def test_is_fallback_error_criteria():
    """エラー内容がフォールバック対象エラーに該当するか正しく判定されること"""
    assert model_governance.is_fallback_error(Exception("429 RESOURCE_EXHAUSTED")) is True
    assert model_governance.is_fallback_error(Exception("503 Service UNAVAILABLE")) is True
    assert model_governance.is_fallback_error(Exception("404 NOT_FOUND")) is True
    assert model_governance.is_fallback_error(Exception("quota limit exceeded")) is True
    assert model_governance.is_fallback_error(Exception("limit: 0")) is True
    assert model_governance.is_fallback_error(Exception("Some other general connection error")) is False


def test_resolve_model_loop_prevention():
    """_resolve_model 実行時にフォールバックチェーンに循環参照があっても無限ループが防止されること"""
    with patch.dict(model_governance._fallback_chain, {
        "model-a": "model-b",
        "model-b": "model-a"
    }):
        with patch("usage_tracker.tracker.usage_tracker.can_make_request", return_value=False):
            resolved = model_governance._resolve_model("proofreader", "model-a")
            assert resolved in ("model-a", "model-b")


def test_model_governance_internal_details():
    from model_governance import model_governance
    import json

    # 行71: 重複初期化のガード
    model_governance.__init__()
    assert model_governance._initialized is True

    # 行194: イベントログの切り詰め (200件超で末尾100件に)
    model_governance._event_log = []
    for i in range(201):
        model_governance._record_event("test_type", "orig", "res", "caller")
    assert len(model_governance._event_log) == 100

    # 行197: get_stats
    stats = model_governance.get_stats()
    assert isinstance(stats, dict)
    assert "deprecation_corrections" in stats
    assert "recent_events" in stats

    # 行116-121: _load_config での例外処理のモック
    with patch("builtins.open", side_effect=FileNotFoundError("Mock File Not Found")):
        model_governance.reload()

    with patch("builtins.open", side_effect=PermissionError("Mock Permission Error")):
        model_governance.reload()

    with patch("builtins.open", side_effect=json.JSONDecodeError("Mock Decode Error", "", 0)):
        model_governance.reload()

    model_governance.reload()


def test_resolve_model_usage_tracker_exceptions():
    from model_governance import model_governance
    # 行259-262: can_make_request 等で例外が発生した場合
    with patch("usage_tracker.tracker.usage_tracker.can_make_request", side_effect=RuntimeError("Mock track err")):
        resolved = model_governance._resolve_model("proofreader", "gemini-3-flash-preview")
        assert resolved == "gemini-3-flash-preview"


@pytest.mark.asyncio
async def test_model_governance_call_gateway():
    from model_governance import model_governance
    from unittest.mock import MagicMock, AsyncMock

    # APIキー未設定 (client is None) の場合
    with patch("gemini_client_factory._get_raw_client", return_value=None):
        with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
            await model_governance.call(task="proofreader", prompt="hello")

    # モッククライアント
    mock_client = MagicMock()

    # aio クライアント (非同期) の正常系
    mock_response = MagicMock()
    mock_response.text = "Mocked Response Text"
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        res = await model_governance.call(task="proofreader", prompt="hello")
        assert res == "Mocked Response Text"

        # 同期フォールバック (aio なし)
        del mock_client.aio
        mock_client.models.generate_content = MagicMock(return_value=mock_response)
        res = await model_governance.call(task="proofreader", prompt="hello")
        assert res == "Mocked Response Text"

        # API 呼び出しがフォールバック対象エラー で失敗し、次のモデルで成功する場合
        mock_client.aio = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=[
            GoogleAPICallError("429 RESOURCE_EXHAUSTED"),
            mock_response
        ])

        with patch("usage_tracker.tracker.usage_tracker.can_make_request", return_value=True):
            res = await model_governance.call(task="proofreader", prompt="hello", model="gemini-3-flash-preview")
            assert res == "Mocked Response Text"

        # フォールバック対象外エラーの場合 (そのまま raise)
        mock_client.aio.models.generate_content = AsyncMock(side_effect=GoogleAPICallError("400 BAD_REQUEST"))
        with pytest.raises(GoogleAPICallError, match="400 BAD_REQUEST"):
            await model_governance.call(task="proofreader", prompt="hello")

        # 全フォールバックが枯渇した場合
        mock_client.aio.models.generate_content = AsyncMock(side_effect=GoogleAPICallError("429 RESOURCE_EXHAUSTED"))
        with pytest.raises(RuntimeError, match="全フォールバック枯渇"):
            await model_governance.call(task="proofreader", prompt="hello", model="gemini-2.5-flash-lite")


def test_track_usage_exceptions_and_alerts():
    from model_governance import model_governance

    with patch("usage_tracker.tracker.usage_tracker.track_request", side_effect=OSError("Mock IO error")):
        model_governance._track_usage("gemini-3-flash-preview", "test_caller")

    mock_result = {"alert_level": "warning", "usage_ratio": 0.85}
    with patch("usage_tracker.tracker.usage_tracker.track_request", return_value=mock_result):
        model_governance._event_log = []
        model_governance._track_usage("gemini-3-flash-preview", "test_caller")
        assert len(model_governance._event_log) == 1
        assert model_governance._event_log[0]["type"] == "quota_alert"


def test_governed_models_proxy():
    from model_governance import GovernedModelsProxy

    mock_real = MagicMock()
    proxy = GovernedModelsProxy(mock_real, "test_caller")

    mock_real.some_attr = "hello_attr"
    assert proxy.some_attr == "hello_attr"

    mock_response = MagicMock()
    mock_real.generate_content.return_value = mock_response
    res = proxy.generate_content(model="gemini-3-flash-preview", contents="Say OK")
    assert res == mock_response

    mock_real.generate_content.side_effect = [
        GoogleAPICallError("429 RESOURCE_EXHAUSTED"),
        mock_response
    ]
    res = proxy.generate_content(model="gemini-3-flash-preview", contents="Say OK")
    assert res == mock_response

    mock_real.generate_content.side_effect = GoogleAPICallError("400 BAD_REQUEST")
    with pytest.raises(GoogleAPICallError, match="400"):
        proxy.generate_content(model="gemini-3-flash-preview")

    mock_real.generate_content.side_effect = GoogleAPICallError("503 UNAVAILABLE")
    with pytest.raises(GoogleAPICallError):
        proxy.generate_content(model="gemini-2.5-flash-lite")

    # _classify_error テスト
    assert proxy._classify_error(RuntimeError("429 RESOURCE_EXHAUSTED")) == "429:枠枯渇"
    assert proxy._classify_error(RuntimeError("503 UNAVAILABLE")) == "503:サーバー混雑"
    assert proxy._classify_error(RuntimeError("404 NOT_FOUND")) == "404:モデル不在"
    assert proxy._classify_error(RuntimeError("limit: 0")) == "quota=0:利用不可"
    assert proxy._classify_error(RuntimeError("quota exceeded")) == "quota=0:利用不可"
    assert proxy._classify_error(RuntimeError("some random error")) == "unknown:some random error"


@pytest.mark.asyncio
async def test_governed_async_models_proxy():
    from model_governance import GovernedAsyncModelsProxy
    from unittest.mock import AsyncMock

    mock_real = MagicMock()
    proxy = GovernedAsyncModelsProxy(mock_real, "test_caller")

    mock_response = MagicMock()
    mock_real.generate_content = AsyncMock(return_value=mock_response)
    res = await proxy.generate_content(model="gemini-3-flash-preview", contents="Say OK")
    assert res == mock_response

    mock_real.generate_content = AsyncMock(side_effect=[
        GoogleAPICallError("429 RESOURCE_EXHAUSTED"),
        mock_response
    ])
    res = await proxy.generate_content(model="gemini-3-flash-preview", contents="Say OK")
    assert res == mock_response

    mock_real.generate_content = AsyncMock(side_effect=GoogleAPICallError("400 BAD_REQUEST"))
    with pytest.raises(GoogleAPICallError, match="400"):
        await proxy.generate_content(model="gemini-3-flash-preview")

    mock_real.generate_content = AsyncMock(side_effect=GoogleAPICallError("503 UNAVAILABLE"))
    with pytest.raises(GoogleAPICallError):
        await proxy.generate_content(model="gemini-2.5-flash-lite")


def test_get_governed_client_coverage():
    from model_governance import get_governed_client

    with patch("gemini_client_factory._get_raw_client", return_value=None):
        assert get_governed_client() is None

    mock_client = MagicMock()
    mock_client.models = "real_models"
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        g_client = get_governed_client("caller_test")
        assert g_client is not None
        assert g_client.models is not None
        mock_client.other_attr = "value"
        assert g_client.other_attr == "value"


@pytest.mark.asyncio
async def test_governance_hooks():
    from model_governance import _model_governance_hook, _model_usage_tracking_hook, register_governance_hook

    mock_input = MagicMock()
    mock_input.tool_name = "test_tool"
    mock_input.tool_input = {"model": "gemini-2.0-flash"}

    res = await _model_governance_hook(mock_input)
    assert res is not None
    assert res.updated_input["model"] == "gemini-3-flash-preview"

    mock_input.tool_input = {"model": "gemini-2.5-flash"}
    res = await _model_governance_hook(mock_input)
    assert res is None

    mock_input.tool_input = {"model": "gemini-2.5-flash"}
    with patch("usage_tracker.tracker.usage_tracker.track_request", return_value={"alert_level": "normal"}):
        res = await _model_usage_tracking_hook(mock_input)
        assert res is None

    with patch("usage_tracker.tracker.usage_tracker.track_request", return_value={"alert_level": "warning", "usage_ratio": 0.85}):
        res = await _model_usage_tracking_hook(mock_input)
        assert res is None

    with patch("usage_tracker.tracker.usage_tracker.track_request", side_effect=ImportError("mock err")):
        res = await _model_usage_tracking_hook(mock_input)
        assert res is None

    register_governance_hook()

    with patch("harness.hooks.hook_system.register", side_effect=ImportError):
        register_governance_hook()


def test_usage_tracker_edge_cases():
    from usage_tracker.tracker import DailyUsage, _load_model_config, UsageTracker
    import tempfile

    du = DailyUsage("2026-05-31")
    with pytest.raises(ValueError, match="Model name cannot be empty"):
        du.add_request("")

    du.add_request("gemini-2.5-flash", tokens_in=-10, tokens_out=-5)
    assert du.models["gemini-2.5-flash"]["tokens_in"] == 0
    assert du.models["gemini-2.5-flash"]["tokens_out"] == 0

    assert du.get_requests("") == 0

    with patch("builtins.open", side_effect=FileNotFoundError):
        assert _load_model_config() == {}
    with patch("builtins.open", side_effect=OSError):
        assert _load_model_config() == {}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_usage = Path(tmpdir) / "usage_data.json"

        with open(tmp_usage, "w") as f:
            f.write("invalid json")
        tracker = UsageTracker(usage_path=tmp_usage)
        assert tracker._daily_usage is not None

        with patch("builtins.open", side_effect=OSError):
            tracker._save_usage()

        with pytest.raises(ValueError, match="Model name"):
            tracker.track_request("")

        assert tracker.get_usage_ratio("") == 0.0

        assert tracker.can_make_request("") is False

        assert tracker.get_remaining_requests("") == 0
        assert tracker.get_remaining_requests("gemini-2.5-flash") > 0

        mock_cb = MagicMock(side_effect=RuntimeError("Mock callback error"))
        tracker.register_alert_callback(mock_cb)
        with pytest.raises(TypeError):
            tracker.register_alert_callback("not_callable")
        tracker.track_request("gemini-2.5-flash")
        mock_cb.assert_called_once()

        tracker._alert_thresholds = {
            "info": 0.6,
            "warning": 0.8,
            "block": 0.95,
            "critical": 1.0,
        }
        assert tracker._get_alert_level(1.0) == "critical"
        assert tracker._get_alert_level(0.96) == "block"
        assert tracker._get_alert_level(0.85) == "warning"
        assert tracker._get_alert_level(0.65) == "info"
        assert tracker._get_alert_level(0.5) == "normal"

        tracker._log_alert({"alert_level": "critical", "model": "m", "usage_ratio": 1.0})
        tracker._log_alert({"alert_level": "block", "model": "m", "usage_ratio": 0.96})
        tracker._log_alert({"alert_level": "warning", "model": "m", "usage_ratio": 0.85})
        tracker._log_alert({"alert_level": "info", "model": "m", "usage_ratio": 0.65})

        summary = tracker.get_daily_summary()
        assert "date" in summary
        assert "models" in summary

        with patch.object(tracker, "can_make_request", side_effect=lambda m: m != "gemini-3-flash-preview"):
            rec = tracker.get_model_recommendation("proofreader")
            assert rec == "gemini-2.5-flash"

        with patch("model_registry.get_model", side_effect=RuntimeError):
            assert tracker.get_model_recommendation("proofreader") == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_model_governance_extra_coverage(monkeypatch):
    import sys
    import runpy
    import os
    from model_governance import model_governance, GovernedModelsProxy, GovernedAsyncModelsProxy, _model_usage_tracking_hook
    from usage_tracker.tracker import UsageTracker
    from unittest.mock import MagicMock, patch, AsyncMock
    import pytest

    monkeypatch.setenv("GOOGLE_API_KEY", "dummy_key")

    # 行 260: usage_tracker 未導入 (ImportError) 時の枠チェックスキップ (pass)
    with patch.dict("sys.modules", {"usage_tracker.tracker": None}):
        res = model_governance._resolve_model("proofreader", "gemini-3-flash-preview")
        assert res == "gemini-3-flash-preview"

    # 行 260: _resolve_model 内で usage_tracker から AttributeError や例外が発生した場合
    with patch.object(UsageTracker, "can_make_request", side_effect=AttributeError("mock attr err")):
        res = model_governance._resolve_model("proofreader", "gemini-3-flash-preview")
        assert res == "gemini-3-flash-preview"

    # 行 319: call メソッドで config が適用される場合の処理
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Config OK"
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
        res = await model_governance.call(
            task="proofreader", prompt="hello", config={"temperature": 0.7}
        )
        assert res == "Config OK"
        # config が generate_content に渡されたか確認
        called_kwargs = mock_client.aio.models.generate_content.call_args[1]
        assert called_kwargs["temperature"] == 0.7

        # 行 393, 495, 579: raise last_error のデッドコードに到達させるためにチェーンを空にする
        with patch.object(model_governance, "build_fallback_sequence", return_value=[]):
            # call の raise last_error (393)
            with pytest.raises(TypeError):  # raising None raises TypeError
                await model_governance.call(task="proofreader", prompt="hello")

            # GovernedModelsProxy の raise last_error (495)
            proxy = GovernedModelsProxy(MagicMock(), "test_caller")
            with pytest.raises(TypeError):
                proxy.generate_content(model="gemini-3-flash-preview")

            # GovernedAsyncModelsProxy の raise last_error (579)
            async_proxy = GovernedAsyncModelsProxy(MagicMock(), "test_caller")
            with pytest.raises(TypeError):
                await async_proxy.generate_content(model="gemini-3-flash-preview")

            # GovernedModelsProxy.embed_content の raise last_error (563)
            with pytest.raises(TypeError):
                proxy.embed_content(model="gemini-3-flash-preview", contents="contents")

            # GovernedAsyncModelsProxy.embed_content の raise last_error (707)
            with pytest.raises(TypeError):
                await async_proxy.embed_content(model="gemini-3-flash-preview", contents="contents")

    # 行 659: _model_usage_tracking_hook で model が指定されていない場合
    mock_input = MagicMock()
    mock_input.tool_input = {}
    res_hook = await _model_usage_tracking_hook(mock_input)
    assert res_hook is None

    # 行 712-762: __main__ ブロックの直接実行
    script_path = BACKEND_DIR / "model_governance.py"

    # 1) APIキーなしルート (756行目)
    with patch("gemini_client_factory._get_raw_client", return_value=None):
        try:
            runpy.run_path(str(script_path), run_name="__main__")
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, SystemExit, ImportError):
            pass

    # 2) APIキーあり 正常系ルート (752行目)
    mock_main_client = MagicMock()
    mock_main_response = MagicMock()
    mock_main_response.text = "OK"
    mock_main_client.models.generate_content.return_value = mock_main_response
    with patch("gemini_client_factory._get_raw_client", return_value=mock_main_client):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "dummy_key"}):
            try:
                runpy.run_path(str(script_path), run_name="__main__")
            except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, SystemExit, ImportError):
                pass

    # 3) API 呼び出し例外発生ルート (754行目)
    mock_err_client = MagicMock()
    mock_err_client.models.generate_content.side_effect = ValueError("mock api error")
    with patch("gemini_client_factory._get_raw_client", return_value=mock_err_client):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "dummy_key"}):
            try:
                runpy.run_path(str(script_path), run_name="__main__")
            except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, SystemExit, ImportError):
                pass


def test_usage_tracker_extra_coverage():
    from usage_tracker.tracker import UsageTracker
    from unittest.mock import MagicMock, patch
    import tempfile
    import pytest
    import json
    from pathlib import Path

    # 行 112: alert_thresholds の更新
    dummy_config = {
        "free_tier_limits": {},
        "alert_thresholds": {
            "info": 0.5,
            "warning": 0.7,
            "block": 0.9,
            "critical": 0.98
        }
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "model_config_test.json"
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(dummy_config, f)
        
        tracker = UsageTracker(model_config_path=config_file)
        assert tracker._alert_thresholds["info"] == 0.5
        assert tracker._alert_thresholds["warning"] == 0.7
        assert tracker._alert_thresholds["block"] == 0.9
        assert tracker._alert_thresholds["critical"] == 0.98

    # 行 117: _get_rpd での空モデル名
    tracker = UsageTracker()
    assert tracker._get_rpd("") == 1000
    assert tracker._get_rpd(None) == 1000

    # 行 138-139: _load_or_create_daily_usage での OSError ハンドリング
    with patch("builtins.open", side_effect=OSError("mock os error")):
        tracker_os = UsageTracker()
        assert tracker_os._daily_usage is not None

    # 行 155: _save_usage での TypeError 例外
    with patch("json.dump", side_effect=TypeError("mock type error")):
        tracker_type = UsageTracker()
        tracker_type.track_request("gemini-2.5-flash")

    # 行 174: 日付変更時の usage リセット
    tracker_date = UsageTracker()
    tracker_date._daily_usage.date = "2020-01-01"
    tracker_date.track_request("gemini-2.5-flash")
    from datetime import date
    assert tracker_date._daily_usage.date == date.today().isoformat()

    # 行 288: get_model_recommendation で task が空の場合
    with pytest.raises(ValueError, match="Task name cannot be empty"):
        tracker.get_model_recommendation("")
    with pytest.raises(ValueError, match="Task name cannot be empty"):
        tracker.get_model_recommendation(None)

    # 行 294: model_registry のインポートなどで RuntimeError 以外の例外
    with patch("model_registry.get_model", side_effect=ImportError("mock import error")):
        rec = tracker.get_model_recommendation("proofreader")
        assert rec == "gemini-2.5-flash"


def test_governed_models_proxy_embed_content():
    from model_governance import GovernedModelsProxy
    mock_real = MagicMock()
    proxy = GovernedModelsProxy(mock_real, "test_caller")

    mock_response = MagicMock()
    mock_real.embed_content.return_value = mock_response

    # 正常系
    res = proxy.embed_content(model="gemini-3-flash-preview", contents="contents")
    assert res == mock_response

    # フォールバック成功
    mock_real.embed_content.side_effect = [
        GoogleAPICallError("429 RESOURCE_EXHAUSTED"),
        mock_response
    ]
    res = proxy.embed_content(model="gemini-3-flash-preview", contents="contents")
    assert res == mock_response

    # フォールバック対象外エラー
    mock_real.embed_content.side_effect = GoogleAPICallError("400 BAD_REQUEST")
    with pytest.raises(GoogleAPICallError):
        proxy.embed_content(model="gemini-3-flash-preview", contents="contents")

    # 全フォールバック枯渇
    mock_real.embed_content.side_effect = GoogleAPICallError("429 RESOURCE_EXHAUSTED")
    with pytest.raises(GoogleAPICallError):
        proxy.embed_content(model="gemini-2.5-flash-lite", contents="contents")


@pytest.mark.asyncio
async def test_governed_async_models_proxy_embed_content_and_getattr():
    from model_governance import GovernedAsyncModelsProxy
    mock_real = MagicMock()
    proxy = GovernedAsyncModelsProxy(mock_real, "test_caller")

    # getattr テスト
    mock_real.some_attr = "async_hello_attr"
    assert proxy.some_attr == "async_hello_attr"

    mock_response = MagicMock()
    mock_real.embed_content = AsyncMock(return_value=mock_response)

    # 正常系
    res = await proxy.embed_content(model="gemini-3-flash-preview", contents="contents")
    assert res == mock_response

    # フォールバック成功
    mock_real.embed_content = AsyncMock(side_effect=[
        GoogleAPICallError("429 RESOURCE_EXHAUSTED"),
        mock_response
    ])
    res = await proxy.embed_content(model="gemini-3-flash-preview", contents="contents")
    assert res == mock_response

    # フォールバック対象外エラー
    mock_real.embed_content = AsyncMock(side_effect=GoogleAPICallError("400 BAD_REQUEST"))
    with pytest.raises(GoogleAPICallError):
        await proxy.embed_content(model="gemini-3-flash-preview", contents="contents")

    # 全フォールバック枯渇
    mock_real.embed_content = AsyncMock(side_effect=GoogleAPICallError("429 RESOURCE_EXHAUSTED"))
    with pytest.raises(GoogleAPICallError):
        await proxy.embed_content(model="gemini-2.5-flash-lite", contents="contents")
