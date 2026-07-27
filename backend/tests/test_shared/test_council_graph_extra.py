import pytest
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, ANY

# google-adk や google-genai がインストールされていない環境に備え、
# テスト実行前に sys.modules にダミーモジュールを注入する。
# これにより、run_council の正常系パスをテスト可能にする。
original_modules = {}
mock_modules = {}

def setup_mock_adk():
    mock_runners = MagicMock()
    mock_sessions = MagicMock()
    mock_run_config = MagicMock()
    mock_genai = MagicMock()
    mock_genai_types = MagicMock()

    # google.genai.errors 用のダミークラスを定義
    mock_errors = MagicMock()
    class APIError(Exception):
        pass
    class ClientError(Exception):
        pass
    class ServerError(Exception):
        pass
    mock_errors.APIError = APIError
    mock_errors.ClientError = ClientError
    mock_errors.ServerError = ServerError

    mock_modules["google.adk"] = MagicMock()
    mock_modules["google.adk.runners"] = mock_runners
    mock_modules["google.adk.sessions"] = mock_sessions
    mock_modules["google.adk.agents"] = MagicMock()
    mock_modules["google.adk.agents.run_config"] = mock_run_config
    mock_modules["google.genai"] = mock_genai
    mock_modules["google.genai.types"] = mock_genai_types
    mock_modules["google.genai.errors"] = mock_errors

    return mock_runners, mock_sessions, mock_run_config, mock_genai_types

# モックを準備
(mock_runners, mock_sessions, mock_run_config, mock_genai_types) = setup_mock_adk()

# インポート前に一時的に sys.modules にモックを注入
for name, mod in mock_modules.items():
    if name in sys.modules:
        original_modules[name] = sys.modules[name]
    else:
        original_modules[name] = None
    sys.modules[name] = mod

# 対象のモジュールをグローバルで安全にインポート
import agents.council_graph as cg_mod

# インポート完了後、一旦 sys.modules を元の状態に復元して汚染を防ぐ
for name, orig in original_modules.items():
    if orig is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = orig

# 各テストの実行時のみ、sys.modules にモックを一時的にパッチするフィクスチャ
@pytest.fixture(autouse=True)
def mock_adk_environment():
    import os
    saved_modules = {}
    for name, mod in mock_modules.items():
        if name in sys.modules:
            saved_modules[name] = sys.modules[name]
        else:
            saved_modules[name] = None
        sys.modules[name] = mod
        
    old_key = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "mock-api-key"
        
    yield
    
    if old_key is None:
        os.environ.pop("GEMINI_API_KEY", None)
    else:
        os.environ["GEMINI_API_KEY"] = old_key

    for name, orig in saved_modules.items():
        if orig is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = orig


# --- CG-12: run_council でカスタムの council_mode="pre_production" が正しく InMemoryRunner に逆戻されるかの検証 ---
@pytest.mark.asyncio
async def test_run_council_custom_mode():
    mock_runner = MagicMock()
    mock_session_service = AsyncMock()
    mock_session = MagicMock()
    mock_session.state = {"council_synthesis": "pre-production report"}
    mock_session_service.create_session.return_value = mock_session
    mock_session_service.get_session.return_value = mock_session
    mock_runner.session_service = mock_session_service

    class EmptyAsyncEventIterator:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration

    mock_runner.run_async.return_value = EmptyAsyncEventIterator()

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner),          patch("agents.council_graph._build_council_agents", return_value=(MagicMock(), MagicMock(), MagicMock(), MagicMock())):
         
        result = await cg_mod.run_council("テスト質問", council_mode="pre_production")
        
        assert result["status"] == "success"
        assert result["synthesis"] == "pre-production report"
        mock_session_service.create_session.assert_called_once()
        called_args, called_kwargs = mock_session_service.create_session.call_args
        assert called_kwargs["state"]["council_mode"] == "pre_production"


# --- 新規テスト: _build_council_agents の検証 ---
def test_build_council_agents():
    mock_create_council = MagicMock(side_effect=lambda name, role, expertise: f"MockCouncilAgent_{name}")
    mock_create_agent = MagicMock(side_effect=lambda name, instruction, description, sub_agents, output_key: f"MockRootAgent_{name}")
    
    with patch("agents.adk_agent_template.create_council_agent", mock_create_council),          patch("agents.adk_agent_template.create_agent", mock_create_agent):
        
        root, analyst, strategist, director = cg_mod._build_council_agents()
        
        assert root == "MockRootAgent_CouncilSupervisor"
        assert analyst == "MockCouncilAgent_Analyst"
        assert strategist == "MockCouncilAgent_Strategist"
        assert director == "MockCouncilAgent_Director"
        
        mock_create_council.assert_any_call(name="Analyst", role="アナリスト", expertise=ANY)
        mock_create_council.assert_any_call(name="Strategist", role="ストラテジスト", expertise=ANY)
        mock_create_council.assert_any_call(name="Director", role="ディレクター", expertise=ANY)


# --- 新規テスト: run_council のインポートエラー時 ---
@pytest.mark.asyncio
async def test_run_council_import_error():
    original_import = __import__
    def mock_import(name, *args, **kwargs):
        if "google.adk" in name:
            raise ImportError("Mocked ImportError for ADK")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        result = await cg_mod.run_council("テスト質問")
        assert result["status"] == "error"
        assert "依存モジュールのインポートに失敗しました" in result["synthesis"]


# --- 新規テスト: 非同期ループ内でのテキスト結合 ---
@pytest.mark.asyncio
async def test_run_council_event_aggregation():
    mock_runner = MagicMock()
    mock_session_service = AsyncMock()
    mock_session = MagicMock()
    mock_session.state = {"council_synthesis": "fallback"}
    mock_session_service.create_session.return_value = mock_session
    mock_session_service.get_session.return_value = mock_session
    mock_runner.session_service = mock_session_service

    class AsyncEventIterator:
        def __init__(self):
            part1 = MagicMock(text="こんにちは")
            content1 = MagicMock(parts=[part1])
            event1 = MagicMock()
            event1.is_final_response.return_value = True
            event1.content = content1

            part2 = MagicMock(text="！世界。")
            content2 = MagicMock(parts=[part2])
            event2 = MagicMock()
            event2.is_final_response.return_value = True
            event2.content = content2

            self.events = [event1, event2]
            self.idx = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.idx >= len(self.events):
                raise StopAsyncIteration
            ev = self.events[self.idx]
            self.idx += 1
            return ev

    mock_runner.run_async.return_value = AsyncEventIterator()

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner),          patch("agents.council_graph._build_council_agents", return_value=(MagicMock(), MagicMock(), MagicMock(), MagicMock())):
         
        result = await cg_mod.run_council("テスト質問")
        assert result["status"] == "success"
        assert result["synthesis"] == "こんにちは！世界。"


# --- 新規テスト: synthesisが空の場合に session.state から取得 ---
@pytest.mark.asyncio
async def test_run_council_empty_synthesis_fallback():
    mock_runner = MagicMock()
    mock_session_service = AsyncMock()
    mock_session = MagicMock()
    mock_session.state = {"council_synthesis": "セッションステートからのレポート"}
    mock_session_service.create_session.return_value = mock_session
    mock_session_service.get_session.return_value = mock_session
    mock_runner.session_service = mock_session_service

    class EmptyAsyncEventIterator:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration

    mock_runner.run_async.return_value = EmptyAsyncEventIterator()

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner),          patch("agents.council_graph._build_council_agents", return_value=(MagicMock(), MagicMock(), MagicMock(), MagicMock())):
         
        result = await cg_mod.run_council("テスト質問")
        assert result["status"] == "success"
        assert result["synthesis"] == "セッションステートからのレポート"


# --- 新規テスト: run_council の例外発生時フォールバック ---
@pytest.mark.asyncio
async def test_run_council_exception_fallback():
    mock_runner = MagicMock()
    mock_session_service = AsyncMock()
    mock_session_service.create_session.side_effect = Exception("セッション作成失敗の深刻なエラー")
    mock_runner.session_service = mock_session_service

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner),          patch("agents.council_graph._build_council_agents", return_value=(MagicMock(), MagicMock(), MagicMock(), MagicMock())):
         
        result = await cg_mod.run_council("テスト質問")
        assert result["status"] == "error"
        assert "セッション作成失敗の深刻なエラー" in result["error"]
        assert "起動に失敗しました" in result["synthesis"]


# --- 新規テスト: ThumbnailResolver 正常系・異常系検証 ---
def test_thumbnail_resolver_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        resolver = cg_mod.ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path)
        
        with patch("usage_tracker.alert_system.emit_warning") as mock_warning:
            output_file = tmp_path / "test.png"
            resolver.generate_thumbnail(output_file, width=1280, height=720, text="Test Success")
            
            assert output_file.exists()
            result = resolver.validate_thumbnail(output_file)
            
            assert result["path"] == str(output_file)
            assert result["width"] == 1280
            assert result["height"] == 720
            assert result["size_bytes"] > 0
            mock_warning.assert_not_called()


def test_thumbnail_resolver_existence_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        resolver = cg_mod.ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path)
        
        with patch("usage_tracker.alert_system.emit_warning") as mock_warning:
            non_existent = tmp_path / "non_existent.png"
            with pytest.raises(FileNotFoundError) as exc_info:
                resolver.validate_thumbnail(non_existent)
            
            assert "Thumbnail file not found" in str(exc_info.value)
            mock_warning.assert_called_once_with("thumbnail", ANY)


def test_thumbnail_resolver_size_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        resolver = cg_mod.ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path)
        
        dummy_file = tmp_path / "dummy.png"
        dummy_file.write_text("dummy content")
        
        with patch("usage_tracker.alert_system.emit_warning") as mock_warning,              patch("pathlib.Path.stat") as mock_stat:
            
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 5 * 1024 * 1024  # 5MB
            mock_stat.return_value = mock_stat_result
            
            with pytest.raises(ValueError) as exc_info:
                resolver.validate_thumbnail(dummy_file)
            
            assert "File size exceeds 4MB limit" in str(exc_info.value)
            mock_warning.assert_called_once_with("thumbnail", ANY)


def test_thumbnail_resolver_corrupted_image():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        resolver = cg_mod.ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path)
        
        corrupted_file = tmp_path / "corrupted.png"
        corrupted_file.write_text("not an image")
        
        with patch("usage_tracker.alert_system.emit_warning") as mock_warning:
            with pytest.raises(ValueError) as exc_info:
                resolver.validate_thumbnail(corrupted_file)
            
            assert "Image is corrupted or invalid format" in str(exc_info.value)
            mock_warning.assert_called_once_with("thumbnail", ANY)


def test_thumbnail_resolver_dimension_errors():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        resolver = cg_mod.ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path)
        
        with patch("usage_tracker.alert_system.emit_warning") as mock_warning:
            # 1. 解像度が低すぎる場合 (640x480)
            low_res_file = tmp_path / "low_res.png"
            img = Image.new("RGB", (640, 480), color=(255, 0, 0))
            img.save(low_res_file, "PNG")
            
            with pytest.raises(ValueError) as exc_info:
                resolver.validate_thumbnail(low_res_file)
            assert "Resolution must be at least 1280x720" in str(exc_info.value)
            mock_warning.assert_called_once_with("thumbnail", ANY)
            mock_warning.reset_mock()
            
            # 2. アスペクト比が16:9でない場合 (1280x800)
            wrong_aspect_file = tmp_path / "wrong_aspect.png"
            img = Image.new("RGB", (1280, 800), color=(255, 0, 0))
            img.save(wrong_aspect_file, "PNG")
            
            with pytest.raises(ValueError) as exc_info:
                resolver.validate_thumbnail(wrong_aspect_file)
            assert "Aspect ratio must be 16:9" in str(exc_info.value)
            mock_warning.assert_called_once_with("thumbnail", ANY)


def test_thumbnail_resolver_load_image_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        resolver = cg_mod.ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path)
        
        # 1回目のImage.openは成功させてverifyを通過させ、2回目のImage.openで例外を発生させる
        mock_img = MagicMock()
        mock_img.verify.return_value = None
        
        with patch("usage_tracker.alert_system.emit_warning") as mock_warning,              patch("PIL.Image.open", side_effect=[mock_img, RuntimeError("PILの寸法チェック時例外")]):
             
            dummy_file = tmp_path / "dummy.png"
            # escapeシーケンスを避けるため整数リストを使用
            dummy_file.write_bytes(bytes([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]) + b"dummy")
            
            with pytest.raises(ValueError) as exc_info:
                resolver.validate_thumbnail(dummy_file)
                
            assert "Unexpected error during image loading" in str(exc_info.value)
            mock_warning.assert_called_once_with("thumbnail", ANY)


def test_thumbnail_resolver_spoofed_header_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        resolver = cg_mod.ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path)
        
        with patch("usage_tracker.alert_system.emit_warning") as mock_warning:
            dummy_file = tmp_path / "spoofed.png"
            dummy_file.write_text("dummy text (not a png)")
            
            with pytest.raises(ValueError) as exc_info:
                resolver.validate_thumbnail(dummy_file)
                
            assert "Image is corrupted or invalid format" in str(exc_info.value)
            assert "header is not PNG" in str(exc_info.value)
            mock_warning.assert_called_once_with("thumbnail", ANY)


@pytest.mark.asyncio
async def test_thumbnail_resolver_resolve_task_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        resolver = cg_mod.ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path)
        
        with patch("usage_tracker.alert_system.emit_critical") as mock_critical:
            result_str = await resolver.resolve_thumbnail_task("task_123")
            result = json.loads(result_str)
            
            assert result["width"] == 1280
            assert result["height"] == 720
            assert Path(result["path"]).name == "task_123.png"
            mock_critical.assert_not_called()


@pytest.mark.asyncio
async def test_thumbnail_resolver_resolve_task_failure():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        resolver = cg_mod.ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path)
        
        with patch.object(resolver, "generate_thumbnail", side_effect=Exception("生成処理のエラー")),              patch("usage_tracker.alert_system.emit_critical") as mock_critical:
             
            with pytest.raises(Exception) as exc_info:
                await resolver.resolve_thumbnail_task("task_fail")
                
            assert "生成処理のエラー" in str(exc_info.value)
            mock_critical.assert_called_once_with("thumbnail", ANY)


# --- 追加テスト: ThumbnailResolver の引数不正時の TypeError 透過伝播検証 ---
def test_thumbnail_resolver_real_class_type_error():
    class DummyRealResolver:
        def __init__(self, required_arg):
            pass

    original_real = cg_mod.ThumbnailResolver._real_class
    cg_mod.ThumbnailResolver._real_class = DummyRealResolver
    try:
        with pytest.raises(TypeError) as exc_info:
            cg_mod.ThumbnailResolver()
        assert "ThumbnailResolver の引数指定が不正です" in str(exc_info.value)
    finally:
        cg_mod.ThumbnailResolver._real_class = original_real


# --- 追加テスト: run_council 構成エラー (ValueError) 検証 ---
@pytest.mark.asyncio
async def test_run_council_val_error():
    mock_runner = MagicMock()
    mock_session_service = AsyncMock()
    mock_session_service.create_session.side_effect = ValueError("Mocked Value Error")
    mock_runner.session_service = mock_session_service

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner),          patch("agents.council_graph._build_council_agents", return_value=(MagicMock(), MagicMock(), MagicMock(), MagicMock())):
         
        result = await cg_mod.run_council("テスト質問")
        assert result["status"] == "error"
        assert "構成エラーが発生しました" in result["synthesis"]
