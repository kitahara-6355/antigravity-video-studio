import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
import sys
import os
import json
import importlib.util

# 動的なパス解決
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
backend_dir = project_root / "backend"

if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(project_root) not in sys.path:
    sys.path.insert(1, str(project_root))

# usage_tracker/sdk_checker.py を動的・相対的にロードして sys.modules に登録する
sdk_checker_path = backend_dir / "usage_tracker" / "sdk_checker.py"
spec = importlib.util.spec_from_file_location(
    "usage_tracker.sdk_checker",
    str(sdk_checker_path)
)
sdk_checker_module = importlib.util.module_from_spec(spec)
sys.modules["usage_tracker.sdk_checker"] = sdk_checker_module
spec.loader.exec_module(sdk_checker_module)

from usage_tracker.sdk_checker import (
    SDKCompatibilityChecker,
    run_compatibility_check,
    sdk_checker,
)


def test_init():
    checker = SDKCompatibilityChecker()
    assert checker._config_path.name == "model_config.json"
    
    custom_path = Path("/tmp/dummy_config.json")
    checker_custom = SDKCompatibilityChecker(config_path=custom_path)
    assert checker_custom._config_path == custom_path


def test_get_genai_client_success():
    checker = SDKCompatibilityChecker()
    mock_client = MagicMock()
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client) as mock_factory:
        client = checker._get_genai_client()
        assert client == mock_client
        mock_factory.assert_called_once()
        
        # 2回目はキャッシュされる
        client_cached = checker._get_genai_client()
        assert client_cached == mock_client
        mock_factory.assert_called_once()
        
        # エイリアス経由での取得確認
        assert checker._get_client() == mock_client


def test_get_genai_client_import_error():
    checker = SDKCompatibilityChecker()
    with patch("gemini_client_factory.get_gemini_client", side_effect=ImportError("mock import error")):
        client = checker._get_genai_client()
        assert client is None
        # エイリアス経由での取得確認
        assert checker._get_client() is None


def test_get_genai_client_unexpected_exception():
    checker = SDKCompatibilityChecker()
    with patch("gemini_client_factory.get_gemini_client", side_effect=ValueError("unexpected error")):
        client = checker._get_genai_client()
        assert client is None
        # エイリアス経由での取得確認
        assert checker._get_client() is None


def test_get_sdk_version_success():
    checker = SDKCompatibilityChecker()
    
    class DummyGenAI:
        __version__ = "1.2.3"
        
    with patch.dict("sys.modules", {"google": MagicMock(genai=DummyGenAI), "google.genai": DummyGenAI}):
        with patch("google.genai.__version__", "1.2.3", create=True):
            version = checker._get_sdk_version()
            assert version == "1.2.3"


def test_get_sdk_version_import_error():
    checker = SDKCompatibilityChecker()
    original_import = __import__
    
    def mock_import(name, *args, **kwargs):
        if name == "google":
            raise ImportError("no google")
        return original_import(name, *args, **kwargs)
        
    with patch("builtins.__import__", side_effect=mock_import):
        version = checker._get_sdk_version()
        assert version == "not_installed"


def test_get_sdk_version_unexpected_exception():
    checker = SDKCompatibilityChecker()
    original_import = __import__
    
    def mock_import(name, *args, **kwargs):
        if name == "google":
            raise RuntimeError("unexpected runtime error")
        return original_import(name, *args, **kwargs)
        
    with patch("builtins.__import__", side_effect=mock_import):
        version = checker._get_sdk_version()
        assert version == "unknown"


def test_load_config_success():
    checker = SDKCompatibilityChecker()
    dummy_data = {"models": {"gemini-1.5-pro": {"tier": "premium"}}}
    mock_file = mock_open(read_data=json.dumps(dummy_data))
    with patch("builtins.open", mock_file):
        config = checker._load_config()
        assert config == dummy_data


def test_load_config_file_not_found():
    checker = SDKCompatibilityChecker()
    with patch("builtins.open", side_effect=FileNotFoundError()):
        config = checker._load_config()
        assert config is None


def test_load_config_json_decode_error():
    checker = SDKCompatibilityChecker()
    with patch("builtins.open", mock_open(read_data="{invalid json}")):
        config = checker._load_config()
        assert config is None


def test_load_config_permission_error():
    checker = SDKCompatibilityChecker()
    with patch("builtins.open", side_effect=PermissionError()):
        config = checker._load_config()
        assert config is None


def test_load_config_unexpected_exception():
    checker = SDKCompatibilityChecker()
    with patch("builtins.open", side_effect=RuntimeError("unexpected error")):
        config = checker._load_config()
        assert config is None


def test_is_model_available():
    checker = SDKCompatibilityChecker()
    available = {"gemini-1.5-flash", "models/gemini-1.5-pro", "gemini_2_0_flash"}
    
    # 完全一致
    assert checker._is_model_available("gemini-1.5-flash", available) is True
    
    # プレフィックス付き (models/ model_name)
    assert checker._is_model_available("gemini-1.5-pro", available) is True
    
    # 置換 (ハイフンからアンダースコア)
    assert checker._is_model_available("gemini-2-0-flash", available) is True
    
    # 部分一致 (available内の要素がmodel_nameに含まれる、あるいはその逆)
    assert checker._is_model_available("gemini-1.5-flash-latest", available) is True
    assert checker._is_model_available("gemini", available) is True
    
    # 一致しない
    assert checker._is_model_available("non-existent-model", available) is False


@pytest.mark.asyncio
async def test_fetch_available_models_no_client():
    checker = SDKCompatibilityChecker()
    with patch.object(checker, "_get_genai_client", return_value=None):
        models = await checker._fetch_available_models()
        assert models == set()


@pytest.mark.asyncio
async def test_fetch_available_models_success():
    checker = SDKCompatibilityChecker()
    mock_client = MagicMock()
    
    class DummyModel:
        def __init__(self, name):
            self.name = name
            
    mock_models = [DummyModel("models/gemini-1.5-flash"), DummyModel("gemini-1.5-pro"), "gemini-2.0"]
    
    mock_client.models.list.return_value = mock_models
    with patch.object(checker, "_get_genai_client", return_value=mock_client):
        models = await checker._fetch_available_models()
        assert models == {"gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0"}


@pytest.mark.asyncio
async def test_fetch_available_models_exception():
    checker = SDKCompatibilityChecker()
    mock_client = MagicMock()
    mock_client.models.list.side_effect = RuntimeError("api error")
    with patch.object(checker, "_get_genai_client", return_value=mock_client):
        models = await checker._fetch_available_models()
        assert models == set()


@pytest.mark.asyncio
async def test_check_compatibility():
    checker = SDKCompatibilityChecker()
    
    # 1. available が空の場合
    with patch.object(checker, "_fetch_available_models", return_value=set()):
        result = await checker.check_compatibility()
        assert "SDKからモデル一覧を取得できませんでした" in result["warnings"]
        
    # 2. configロード失敗の場合
    with patch.object(checker, "_fetch_available_models", return_value={"gemini-1.5-flash"}):
        with patch.object(checker, "_load_config", return_value=None):
            result = await checker.check_compatibility()
            assert "model_config.jsonを読み込めませんでした" in result["warnings"]
            
    # 3. 正常系、一部非互換（フォールバックあり/なし）
    dummy_config = {
        "models": {
            "gemini-1.5-flash": {
                "tier": "standard",
                "fallback": "gemini-1.5-pro"
            },
            "gemini-1.5-pro": {
                "tier": "premium",
                "fallback": None
            },
            "deprecated-model": {
                "status": "deprecated"
            }
        }
    }
    
    # gemini-1.5-flash はあるが、gemini-1.5-pro はないケース
    with patch.object(checker, "_fetch_available_models", return_value={"gemini-1.5-flash"}):
        with patch.object(checker, "_load_config", return_value=dummy_config):
            result = await checker.check_compatibility()
            
            # gemini-1.5-flash は compatible
            compatible_names = [m["model"] for m in result["compatible"]]
            assert "gemini-1.5-flash" in compatible_names
            
            # gemini-1.5-pro は incompatible
            incompatible_names = [m["model"] for m in result["incompatible"]]
            assert "gemini-1.5-pro" in incompatible_names
            
            # deprecated-model はスキップされるため compatibleにもincompatibleにも入らない
            assert "deprecated-model" not in compatible_names
            assert "deprecated-model" not in incompatible_names
            
            # 警告の確認（gemini-1.5-proはfallbackなし）
            assert any("gemini-1.5-pro はSDKで利用不可。フォールバック先がありません。" in w for w in result["warnings"])
            
            # 状態更新の確認
            assert checker.get_last_check_time() == result["timestamp"]
            assert checker.is_compatible("gemini-1.5-flash") is True
            assert checker.is_compatible("gemini-1.5-pro") is False

    # 4. fallbackありの警告ルート (gemini-1.5-flash も利用不可の場合)
    with patch.object(checker, "_fetch_available_models", return_value=set(["some-other-model"])):
        with patch.object(checker, "_load_config", return_value=dummy_config):
            result = await checker.check_compatibility()
            assert any("gemini-1.5-flash はSDKで利用不可。gemini-1.5-pro にフォールバックします。" in w for w in result["warnings"])

    # 5. 全モデル互換あり (incompatible_count == 0 のログ出力ルート)
    dummy_config_all_ok = {
        "models": {
            "gemini-1.5-flash": {
                "tier": "standard",
                "fallback": "gemini-1.5-pro"
            }
        }
    }
    with patch.object(checker, "_fetch_available_models", return_value={"gemini-1.5-flash"}):
        with patch.object(checker, "_load_config", return_value=dummy_config_all_ok):
            result = await checker.check_compatibility()
            assert len(result["incompatible"]) == 0


def test_get_available_model():
    checker = SDKCompatibilityChecker()
    checker._available_models = {"gemini-1.5-flash", "gemini-1.5-pro"}
    checker._incompatible_models = ["gemini-1.0-pro"]
    
    # 1. 優先モデルが available にある場合
    assert checker.get_available_model("gemini-1.5-flash") == "gemini-1.5-flash"
    
    # 2. 優先モデルが incompatible だが、フォールバックモデルが available にある場合
    dummy_config = {
        "models": {
            "gemini-1.0-pro": {
                "fallback": "gemini-1.5-pro"
            }
        }
    }
    with patch.object(checker, "_load_config", return_value=dummy_config):
        assert checker.get_available_model("gemini-1.0-pro") == "gemini-1.5-pro"
        
    # 3. 優先モデルが incompatible だが、フォールバックモデルが available にない場合
    dummy_config_no_avail = {
        "models": {
            "gemini-1.0-pro": {
                "fallback": "gemini-2.0-pro"  # availableに存在しない
            }
        }
    }
    with patch.object(checker, "_load_config", return_value=dummy_config_no_avail):
        assert checker.get_available_model("gemini-1.0-pro") == "gemini-1.0-pro"


@pytest.mark.asyncio
async def test_run_compatibility_check_function():
    with patch.object(sdk_checker, "check_compatibility", return_value={"status": "ok"}) as mock_check:
        result = await run_compatibility_check()
        assert result == {"status": "ok"}
        mock_check.assert_called_once()


def test_normalize_model_name():
    checker = SDKCompatibilityChecker()
    class DummyModel:
        def __init__(self, name):
            self.name = name
    assert checker._normalize_model_name(DummyModel("models/gemini-1.5-pro")) == "gemini-1.5-pro"
    assert checker._normalize_model_name("gemini/gemini-1.5-flash") == "gemini-1.5-flash"
    assert checker._normalize_model_name("gemini-2.0") == "gemini-2.0"


def test_get_fallback_model():
    checker = SDKCompatibilityChecker()
    dummy_config = {
        "models": {
            "gemini-1.0-pro": {
                "fallback": "gemini-1.5-pro"
            },
            "gemini-1.5-flash": {
                "fallback": None
            }
        }
    }
    with patch.object(checker, "_load_config", return_value=dummy_config):
        assert checker._fetch_fallback_model("gemini-1.0-pro") == "gemini-1.5-pro"
        assert checker._fetch_fallback_model("gemini-1.5-flash") is None
        assert checker._fetch_fallback_model("non-existent-model") is None
        
    with patch.object(checker, "_load_config", return_value=None):
        assert checker._fetch_fallback_model("gemini-1.0-pro") is None


def test_sdk_checker_module_source():
    # usage_tracker.sdk_checker が正しい場所からインポートされているかを検証する
    import sys
    sdk_checker_module = sys.modules.get("usage_tracker.sdk_checker")
    assert sdk_checker_module is not None
    source_file = sdk_checker_module.__file__
    assert "backend" in source_file
    assert "usage_tracker" in source_file
    assert source_file.endswith("sdk_checker.py")
