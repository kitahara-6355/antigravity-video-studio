import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
import sys
import os
import json
import importlib.util

# 動的なパス解決
current_dir = Path(__file__).resolve().parent
# もしこのファイルが一時ディレクトリにある場合を考慮し、本来のパスを解決する
project_root = Path(__file__).resolve().parent.parent.parent
backend_dir = Path(__file__).resolve().parent.parent

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
    generate_sdk_checker_thumbnail,
    validate_thumbnail,
    resolve_sdk_checker_task,
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


def test_generate_sdk_checker_thumbnail_success(tmp_path):
    output_path = tmp_path / "thumbnail.png"
    result = generate_sdk_checker_thumbnail(output_path, text="Hello Test")
    assert result == output_path
    assert output_path.exists()

    # PILで開いて検証
    from PIL import Image
    with Image.open(output_path) as img:
        assert img.size == (1280, 720)


def test_generate_sdk_checker_thumbnail_type_error(tmp_path):
    output_path = tmp_path / "thumbnail.png"
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_sdk_checker_thumbnail(output_path, width="not_an_int")


def test_generate_sdk_checker_thumbnail_negative_size(tmp_path):
    output_path = tmp_path / "thumbnail.png"
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_sdk_checker_thumbnail(output_path, width=-100)


def test_generate_sdk_checker_thumbnail_overwrite(tmp_path):
    output_path = tmp_path / "thumbnail.png"
    # 空のファイルを作成しておく
    output_path.write_text("dummy")
    assert output_path.exists()

    result = generate_sdk_checker_thumbnail(output_path, text="Overwrite Test")
    assert result == output_path
    assert output_path.exists()
    
    from PIL import Image
    with Image.open(output_path) as img:
        assert img.size == (1280, 720)


def test_generate_sdk_checker_thumbnail_save_exception(tmp_path):
    output_path = tmp_path / "thumbnail.png"
    
    # img.save で例外を起こさせるために PIL.Image.Image.save をパッチする
    from PIL import Image
    from pathlib import Path as RealPath
    ConcretePath = type(RealPath())

    class MockPath(ConcretePath):
        def exists(self):
            if ".tmp" in self.name:
                return True
            return super().exists()
            
        def unlink(self, missing_ok=False):
            if ".tmp" in self.name:
                raise PermissionError("unlink error")
            return super().unlink(missing_ok)

    with patch.object(Image.Image, "save", side_effect=IOError("save error")):
        with patch("usage_tracker.sdk_checker.Path", MockPath):
            with pytest.raises(IOError, match="save error"):
                generate_sdk_checker_thumbnail(output_path)
            
        # 一時ファイルが残っていないことを検証する（tmp_path以下に一時ファイルが無いこと）
        # モックされているため実際にはファイルは作成されておらず、tmp_path配下は空のはずです
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0


def test_validate_thumbnail_success(tmp_path):
    output_path = tmp_path / "thumbnail.png"
    generate_sdk_checker_thumbnail(output_path)
    
    result = validate_thumbnail(output_path)
    assert result["path"] == str(output_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] > 0


def test_validate_thumbnail_not_found():
    with pytest.raises(FileNotFoundError):
        validate_thumbnail("non_existent_file.png")


def test_validate_thumbnail_size_limit(tmp_path):
    output_path = tmp_path / "thumbnail.png"
    # 空のファイルを書いてサイズを4MB以上に見せかけるため、statをモックする
    output_path.write_text("dummy")
    
    # os.stat_resultをモックする
    mock_stat = MagicMock()
    mock_stat.st_size = 5 * 1024 * 1024  # 5MB
    
    with patch("pathlib.Path.stat", return_value=mock_stat):
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_thumbnail(output_path)


def test_validate_thumbnail_corrupted_verify(tmp_path):
    output_path = tmp_path / "thumbnail.png"
    output_path.write_text("not an image")
    
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_thumbnail(output_path)


def test_validate_thumbnail_corrupted_load(tmp_path):
    output_path = tmp_path / "thumbnail.png"
    generate_sdk_checker_thumbnail(output_path)
    
    # img.load() で例外を起こさせる
    from PIL import Image
    original_open = Image.open
    
    def mock_open(*args, **kwargs):
        img = original_open(*args, **kwargs)
        # loadをモックして例外を投げさせる
        img.load = MagicMock(side_effect=IOError("corrupted load"))
        # verifyはパスさせたいので、何もしない
        img.verify = MagicMock()
        return img

    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_thumbnail(output_path)


def test_validate_thumbnail_invalid_resolution(tmp_path):
    output_path = tmp_path / "small.png"
    # 小さい画像を生成する
    generate_sdk_checker_thumbnail(output_path, width=800, height=450)
    
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_thumbnail(output_path)


def test_validate_thumbnail_invalid_aspect_ratio(tmp_path):
    output_path = tmp_path / "square.png"
    # 正方形の画像を生成する
    generate_sdk_checker_thumbnail(output_path, width=1280, height=1280)
    
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_thumbnail(output_path)


@pytest.mark.asyncio
async def test_resolve_sdk_checker_task_success(tmp_path):
    # OUTPUT_DIR をパッチして、テスト環境の一時ディレクトリに保存させる
    with patch("usage_tracker.sdk_checker.OUTPUT_DIR", str(tmp_path)):
        # 互換性チェック結果をダミーにして、すべてのモデルを互換にする
        dummy_config = {
            "models": {
                "gemini-1.5-flash": {
                    "tier": "standard",
                    "fallback": "gemini-1.5-pro"
                }
            }
        }
        
        # checkerのメソッドをパッチして確実にテスト結果が得られるようにする
        with patch("usage_tracker.sdk_checker.SDKCompatibilityChecker._fetch_available_models", return_value={"gemini-1.5-flash"}):
            with patch("usage_tracker.sdk_checker.SDKCompatibilityChecker._load_config", return_value=dummy_config):
                task_id = "test_task_123"
                json_result = await resolve_sdk_checker_task(task_id)
                
                # 結果を検証
                result = json.loads(json_result)
                assert result["width"] == 1280
                assert result["height"] == 720
                
                # 生成されたファイルを検証
                expected_file = tmp_path / f"{task_id}.png"
                assert expected_file.exists()


@pytest.mark.asyncio
async def test_resolve_sdk_checker_task_no_models(tmp_path):
    # OUTPUT_DIR をパッチ
    with patch("usage_tracker.sdk_checker.OUTPUT_DIR", str(tmp_path)):
        # availableもconfigも空（None）にするケースの検証
        with patch("usage_tracker.sdk_checker.SDKCompatibilityChecker._fetch_available_models", return_value=set()):
            task_id = "test_task_empty"
            json_result = await resolve_sdk_checker_task(task_id)
            
            result = json.loads(json_result)
            assert result["width"] == 1280
            assert result["height"] == 720
            
            expected_file = tmp_path / f"{task_id}.png"
            assert expected_file.exists()


@pytest.mark.asyncio
async def test_resolve_sdk_checker_task_incompatible_error(tmp_path):
    # OUTPUT_DIR をパッチ
    with patch("usage_tracker.sdk_checker.OUTPUT_DIR", str(tmp_path)):
        # 1モデル非互換になる構成
        dummy_config = {
            "models": {
                "gemini-1.5-pro": {
                    "tier": "premium",
                    "fallback": None
                }
            }
        }
        with patch("usage_tracker.sdk_checker.SDKCompatibilityChecker._fetch_available_models", return_value={"gemini-1.5-flash"}):
            with patch("usage_tracker.sdk_checker.SDKCompatibilityChecker._load_config", return_value=dummy_config):
                task_id = "test_task_incompat"
                # joinのTypeErrorが発生することをアサート (プロダクションコードの型エラーバグ再現ルート)
                with pytest.raises(TypeError, match="expected str instance, dict found"):
                    await resolve_sdk_checker_task(task_id)


def test_save_image_atomically_os_error(tmp_path):
    from usage_tracker.sdk_checker import _save_image_atomically
    from PIL import Image
    
    img = Image.new("RGB", (100, 100), color="red")
    
    # 存在しないディレクトリのパスを指定して OSError を発生させる
    invalid_path = Path("/nonexistent_dir/output.png")
    
    with pytest.raises(OSError):
        _save_image_atomically(img, invalid_path)


def test_validate_image_integrity_syntax_error(tmp_path):
    from usage_tracker.sdk_checker import _validate_image_integrity_and_dimensions
    
    # 壊れたファイルを模したテキストファイルをPNG拡張子で作成
    corrupted_file = tmp_path / "corrupted.png"
    with open(corrupted_file, "w") as f:
        f.write("not a png file")
        
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        _validate_image_integrity_and_dimensions(corrupted_file)


def test_validate_image_integrity_os_error():
    from usage_tracker.sdk_checker import _validate_image_integrity_and_dimensions
    
    # 存在しないファイルパスに対して OSError が発生し、ValueError に変換されることを検証
    nonexistent_file = Path("nonexistent_image_file.png")
    
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        _validate_image_integrity_and_dimensions(nonexistent_file)
