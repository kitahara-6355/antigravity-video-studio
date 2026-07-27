import sys
from pathlib import Path
project_root = str(Path(__file__).parent.parent.parent.absolute())
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pytest
import importlib
from unittest.mock import patch, MagicMock, mock_open, PropertyMock
from pathlib import Path
from core import ProductionContext

def get_plugin_module():
    """sys.modules から常に最新のモジュールオブジェクトを動的に取得する"""
    if "plugins.opening_ending_plugin" not in sys.modules:
        importlib.import_module("plugins.opening_ending_plugin")
    return sys.modules["plugins.opening_ending_plugin"]

@pytest.fixture(autouse=True)
def ensure_clean_plugin_state():
    """各テストの実行前後にモジュールの状態をクリーンに保つ"""
    if "model_registry" in sys.modules and sys.modules["model_registry"] is None:
        del sys.modules["model_registry"]
    
    # モジュールを確実にリロード
    plugin_mod = get_plugin_module()
    importlib.reload(plugin_mod)
    
    # シングルトンレジストリの task_mapping に直接 video_generation を登録
    try:
        from model_registry import get_registry
        # opening_video に割り当てられているモデル名を動的に取得して video_generation にマッピング
        correct_model = get_registry().get_model_for_task("opening_video")
        get_registry()._config["task_mapping"]["video_generation"] = correct_model
    except Exception:
        pass
        
    yield
    
    if "model_registry" in sys.modules and sys.modules["model_registry"] is None:
        del sys.modules["model_registry"]
    importlib.reload(plugin_mod)

def test_can_execute():
    plugin_mod = get_plugin_module()
    p = plugin_mod.OpeningEndingPlugin()
    context = ProductionContext(task_id="test_task")
    context._extensions = {}
    
    # video_title が無い場合は False
    assert p.can_execute(context) is False
    
    # video_title がある場合は True
    context.set_extension("video_title", "My Awesome Video")
    assert p.can_execute(context) is True

class TestOpeningEndingPluginExecute:
    @patch("gemini_client_factory.get_gemini_client")
    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_execute_success_both(self, mock_mkdir, mock_file_open, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        mock_operation = MagicMock()
        mock_operation.done = True
        
        mock_video = MagicMock()
        mock_video.video = b"fake_mp4_binary"
        mock_result = MagicMock()
        mock_result.generated_videos = [mock_video]
        mock_operation.result = mock_result
        
        mock_client.models.generate_videos.return_value = mock_operation
        
        plugin_mod = get_plugin_module()
        p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=True)
        
        context = ProductionContext(task_id="test_task")
        context._extensions = {}
        context.output_dir = Path("/tmp/fake_output")
        context.set_extension("video_title", "Title")
        context.mood_settings = {"veo_prompt_suffix": "cinematic"}
        
        res = p.execute(context)
        
        assert res.opening == str(Path("/tmp/fake_output/oped/opening_test_task.mp4"))
        assert res.ending == str(Path("/tmp/fake_output/oped/ending_test_task.mp4"))
        
        # プラグインが実際に使用したモデル名を取得
        expected_model = p.get_model() or "veo-2.0-generate-001"
        
        mock_client.models.generate_videos.assert_any_call(
            model=expected_model,
            prompt="Opening sequence for 'Title'. Dynamic intro, logo reveal. cinematic"
        )
        mock_client.models.generate_videos.assert_any_call(
            model=expected_model,
            prompt="Ending credits for 'Title'. Thank you message, subscribe button animation. cinematic"
        )
        mock_file_open.assert_called()

    @patch("gemini_client_factory.get_gemini_client")
    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_execute_only_opening(self, mock_mkdir, mock_file_open, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_video = MagicMock()
        mock_video.video = b"fake_mp4_binary"
        mock_result = MagicMock()
        mock_result.generated_videos = [mock_video]
        mock_operation.result = mock_result
        
        mock_client.models.generate_videos.return_value = mock_operation
        
        plugin_mod = get_plugin_module()
        p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=False)
        context = ProductionContext(task_id="test_task")
        context._extensions = {}
        context.output_dir = Path("/tmp/fake_output")
        context.set_extension("video_title", "Title")
        context.mood_settings = {}
        
        res = p.execute(context)
        
        assert res.opening == str(Path("/tmp/fake_output/oped/opening_test_task.mp4"))
        assert res.ending is None

    @patch("gemini_client_factory.get_gemini_client")
    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_execute_only_ending(self, mock_mkdir, mock_file_open, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_video = MagicMock()
        mock_video.video = b"fake_mp4_binary"
        mock_result = MagicMock()
        mock_result.generated_videos = [mock_video]
        mock_operation.result = mock_result
        
        mock_client.models.generate_videos.return_value = mock_operation
        
        plugin_mod = get_plugin_module()
        p = plugin_mod.OpeningEndingPlugin(generate_opening=False, generate_ending=True)
        context = ProductionContext(task_id="test_task")
        context._extensions = {}
        context.output_dir = Path("/tmp/fake_output")
        context.set_extension("video_title", "Title")
        context.mood_settings = {}
        
        res = p.execute(context)
        
        assert res.opening is None
        assert res.ending == str(Path("/tmp/fake_output/oped/ending_test_task.mp4"))

    @patch("gemini_client_factory.get_gemini_client")
    @patch("time.sleep")
    def test_execute_wait_loop(self, mock_sleep, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        mock_operation = MagicMock()
        type(mock_operation).done = PropertyMock(side_effect=[False, True])
        
        mock_video = MagicMock()
        mock_video.video = b"fake_mp4"
        mock_result = MagicMock()
        mock_result.generated_videos = [mock_video]
        mock_operation.result = mock_result
        
        mock_client.models.generate_videos.return_value = mock_operation
        
        with patch("builtins.open", mock_open()), patch("pathlib.Path.mkdir"):
            plugin_mod = get_plugin_module()
            p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=False)
            context = ProductionContext(task_id="test_task")
            context._extensions = {}
            context.output_dir = Path("/tmp/fake_output")
            context.set_extension("video_title", "Title")
            context.mood_settings = {}
            p.execute(context)
        
        mock_sleep.assert_called_once_with(5)

    @patch("gemini_client_factory.get_gemini_client")
    def test_veo_generation_client_exception(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("Failed to connect")
        
        plugin_mod = get_plugin_module()
        p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=False)
        context = ProductionContext(task_id="test_task")
        context._extensions = {}
        context.output_dir = Path("/tmp/fake_output")
        context.set_extension("video_title", "Title")
        context.mood_settings = {}
        
        res = p.execute(context)
        assert res.opening is None

    @patch("gemini_client_factory.get_gemini_client")
    def test_veo_generation_api_exception(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.models.generate_videos.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_client
        
        plugin_mod = get_plugin_module()
        p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=False)
        context = ProductionContext(task_id="test_task")
        context._extensions = {}
        context.output_dir = Path("/tmp/fake_output")
        context.set_extension("video_title", "Title")
        context.mood_settings = {}
        
        res = p.execute(context)
        assert res.opening is None

    @patch("gemini_client_factory.get_gemini_client")
    def test_veo_generation_empty_result(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.result = None
        mock_client.models.generate_videos.return_value = mock_operation
        
        plugin_mod = get_plugin_module()
        p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=False)
        context = ProductionContext(task_id="test_task")
        context._extensions = {}
        context.output_dir = Path("/tmp/fake_output")
        context.set_extension("video_title", "Title")
        context.mood_settings = {}
        
        res = p.execute(context)
        assert res.opening is None

    @patch("gemini_client_factory.get_gemini_client")
    @patch("pathlib.Path.mkdir")
    def test_veo_generation_io_error(self, mock_mkdir, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_video = MagicMock()
        mock_video.video = b"fake_mp4"
        mock_result = MagicMock()
        mock_result.generated_videos = [mock_video]
        mock_operation.result = mock_result
        mock_client.models.generate_videos.return_value = mock_operation
        
        with patch("builtins.open", side_effect=OSError("Write failed")):
            plugin_mod = get_plugin_module()
            p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=False)
            context = ProductionContext(task_id="test_task")
            context._extensions = {}
            context.output_dir = Path("/tmp/fake_output")
            context.set_extension("video_title", "Title")
            context.mood_settings = {}
            res = p.execute(context)
            assert res.opening is None

    def test_execute_plugin_level_exception(self):
        plugin_mod = get_plugin_module()
        p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=True)
        context = ProductionContext(task_id="test_task")
        context._extensions = {}
        context.output_dir = Path("/tmp/fake_output")
        context.set_extension("video_title", "Title")
        context.mood_settings = {}
        
        with patch.object(p, "_generate_video", side_effect=ValueError("Unexpected plugin error")):
            res = p.execute(context)
            assert res.opening is None
            assert res.ending is None

    @patch("gemini_client_factory.get_gemini_client")
    @patch("time.sleep")
    def test_execute_veo_generation_timeout(self, mock_sleep, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        # done が常に False を返すことでタイムアウトを発生させる
        mock_operation = MagicMock()
        mock_operation.done = False
        mock_client.models.generate_videos.return_value = mock_operation
        
        plugin_mod = get_plugin_module()
        p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=False)
        context = ProductionContext(task_id="test_task")
        context._extensions = {}
        context.output_dir = Path("/tmp/fake_output")
        context.set_extension("video_title", "Title")
        context.mood_settings = {}
        
        res = p.execute(context)
        assert res.opening is None
        # 300秒 / 5秒間隔 = 60回スリープが呼ばれる
        assert mock_sleep.call_count == 60

def test_model_registry_import_fallback():
    with patch.dict("sys.modules", {"model_registry": None}):
        plugin_mod = get_plugin_module()
        importlib.reload(plugin_mod)
        fallback_get_model = plugin_mod.get_model
        assert fallback_get_model("opening_video") == "gemini-2.5-flash"

def test_video_title_empty_string():
    """video_title が空文字列の場合の挙動を検証"""
    plugin_mod = get_plugin_module()
    p = plugin_mod.OpeningEndingPlugin()
    context = ProductionContext(task_id="test_task")
    context._extensions = {}
    
    # video_title が空文字列の場合
    context.set_extension("video_title", "")
    assert p.can_execute(context) is True

@patch("gemini_client_factory.get_gemini_client")
@patch("pathlib.Path.mkdir")
def test_veo_generation_empty_videos_list(mock_mkdir, mock_get_client):
    """operation.result.generated_videos が空リストの場合の挙動を検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_operation = MagicMock()
    mock_operation.done = True
    
    mock_result = MagicMock()
    mock_result.generated_videos = []  # 空リスト
    mock_operation.result = mock_result
    
    mock_client.models.generate_videos.return_value = mock_operation
    
    plugin_mod = get_plugin_module()
    p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=False)
    context = ProductionContext(task_id="test_task")
    context._extensions = {}
    context.output_dir = Path("/tmp/fake_output")
    context.set_extension("video_title", "Title")
    context.mood_settings = {}
    
    res = p.execute(context)
    assert res.opening is None

@patch("gemini_client_factory.get_gemini_client")
def test_veo_generation_mkdir_error(mock_get_client):
    """output_dir.mkdir で OSError が発生した場合の挙動を検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_operation = MagicMock()
    mock_operation.done = True
    
    mock_video = MagicMock()
    mock_video.video = b"fake_mp4"
    mock_result = MagicMock()
    mock_result.generated_videos = [mock_video]
    mock_operation.result = mock_result
    
    mock_client.models.generate_videos.return_value = mock_operation
    
    # Path.mkdir で OSError を発生させる
    with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
        plugin_mod = get_plugin_module()
        p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=False)
        context = ProductionContext(task_id="test_task")
        context._extensions = {}
        context.output_dir = Path("/tmp/fake_output")
        context.set_extension("video_title", "Title")
        context.mood_settings = {}
        
        res = p.execute(context)
        assert res.opening is None

@patch("gemini_client_factory.get_gemini_client")
@patch("builtins.open", new_callable=mock_open)
@patch("pathlib.Path.mkdir")
def test_model_fallback_to_default_veo(mock_mkdir, mock_file_open, mock_get_client):
    """get_model が None を返したときにデフォルトモデルが使用されることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_operation = MagicMock()
    mock_operation.done = True
    
    mock_video = MagicMock()
    mock_video.video = b"fake_mp4"
    mock_result = MagicMock()
    mock_result.generated_videos = [mock_video]
    mock_operation.result = mock_result
    
    mock_client.models.generate_videos.return_value = mock_operation
    
    plugin_mod = get_plugin_module()
    p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=False)
    
    # get_model が None を返すようにモック
    with patch.object(p, "get_model", return_value=None):
        context = ProductionContext(task_id="test_task")
        context._extensions = {}
        context.output_dir = Path("/tmp/fake_output")
        context.set_extension("video_title", "Title")
        context.mood_settings = {}
        
        p.execute(context)
        
        # デフォルトモデル "veo-2.0-generate-001" が渡されていることを確認
        mock_client.models.generate_videos.assert_called_once_with(
            model="veo-2.0-generate-001",
            prompt="Opening sequence for 'Title'. Dynamic intro, logo reveal. "
        )

@patch("gemini_client_factory.get_gemini_client")
@patch("builtins.open", new_callable=mock_open)
@patch("pathlib.Path.mkdir")
def test_model_requirements_property_and_task_based_resolution(mock_mkdir, mock_file_open, mock_get_client):
    """model_requirements がプロパティであり、タスク個別のVeoモデル解決が行われることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_operation = MagicMock()
    mock_operation.done = True
    mock_video = MagicMock()
    mock_video.video = b"fake_mp4"
    mock_result = MagicMock()
    mock_result.generated_videos = [mock_video]
    mock_operation.result = mock_result
    mock_client.models.generate_videos.return_value = mock_operation
    
    plugin_mod = get_plugin_module()
    p = plugin_mod.OpeningEndingPlugin(generate_opening=True, generate_ending=True)
    
    # model_requirements が Dict 型としてプロパティで取得できることを確認
    reqs = p.model_requirements
    assert isinstance(reqs, dict)
    assert reqs["task"] == "video_generation"
    assert reqs["api_type"] == "veo"
    
    # model_registry.get_model が 'opening_video' と 'ending_video' のタスクに対して
    # 適切なモデル名を返すようモックする
    context = ProductionContext(task_id="test_task")
    context._extensions = {}
    context.output_dir = Path("/tmp/fake_output")
    context.set_extension("video_title", "Title")
    context.mood_settings = {}
    
    # 1. 正常なVeoモデル名が解決される場合
    with patch("model_registry.get_model", side_effect=lambda task: "veo-3.1" if task in ("opening_video", "ending_video") else "gemini-2.5-flash"):
        p.execute(context)
        # generate_videos が veo-3.1 で呼ばれていることを検証
        mock_client.models.generate_videos.assert_any_call(
            model="veo-3.1",
            prompt="Opening sequence for 'Title'. Dynamic intro, logo reveal. "
        )
        mock_client.models.generate_videos.assert_any_call(
            model="veo-3.1",
            prompt="Ending credits for 'Title'. Thank you message, subscribe button animation. "
        )
        
    # 2. 不正なモデル（veoを含まないモデル）が解決され、フォールバックされる場合
    mock_client.reset_mock()
    with patch("model_registry.get_model", return_value="gemini-2.5-flash"):
        p.execute(context)
        # generate_videos がフォールバックの veo-2.0-generate-001 で呼ばれていることを検証
        mock_client.models.generate_videos.assert_any_call(
            model="veo-2.0-generate-001",
            prompt="Opening sequence for 'Title'. Dynamic intro, logo reveal. "
        )
