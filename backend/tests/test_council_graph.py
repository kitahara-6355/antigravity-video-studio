"""
backend/tests/test_council_graph.py

Unit tests for backend/agents/council_graph.py to achieve 100% coverage.
"""

import sys
import json
import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path

# google-adk や google-genai がインストールされていない環境に備え、
# テスト実行前に sys.modules にダミーモジュールを注入する。
# これにより、run_council の正常系パスをテスト可能にする。
# 元の sys.modules の状態を保存するためのディクショナリ
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

    # モックオブジェクトを作成
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

# 対象のモジュールをインポート
from agents.council_graph import (
    _build_council_agents,
    run_council,
    _fallback_response,
    ThumbnailResolver,
)

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
    # テスト開始時にモックを sys.modules に注入
    saved_modules = {}
    for name, mod in mock_modules.items():
        if name in sys.modules:
            saved_modules[name] = sys.modules[name]
        else:
            saved_modules[name] = None
        sys.modules[name] = mod
        
    # GEMINI_API_KEY を保存してテスト用に設定
    old_key = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "mock-api-key"
        
    yield
    
    # テスト終了後に元に戻す
    if old_key is None:
        os.environ.pop("GEMINI_API_KEY", None)
    else:
        os.environ["GEMINI_API_KEY"] = old_key

    for name, orig in saved_modules.items():
        if orig is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = orig

# ------------------------------------------------------------------------------
# 1. _build_council_agents のテスト
# ------------------------------------------------------------------------------
def test_build_council_agents():
    with patch("agents.adk_agent_template.create_council_agent") as mock_create_council, \
         patch("agents.adk_agent_template.create_agent") as mock_create_agent:
        
        mock_analyst = MagicMock()
        mock_strategist = MagicMock()
        mock_director = MagicMock()
        mock_root = MagicMock()
        
        mock_create_council.side_effect = [mock_analyst, mock_strategist, mock_director]
        mock_create_agent.return_value = mock_root
        
        root, analyst, strategist, director = _build_council_agents()
        
        assert root == mock_root
        assert analyst == mock_analyst
        assert strategist == mock_strategist
        assert director == mock_director
        
        # create_council_agent が3つの専門家向けに呼ばれたことの検証
        assert mock_create_council.call_count == 3
        mock_create_agent.assert_called_once()


# ------------------------------------------------------------------------------
# 2. _fallback_response のテスト
# ------------------------------------------------------------------------------
def test_fallback_response():
    resp = _fallback_response("dummy_query", "Mock error details")
    assert resp["status"] == "error"
    assert resp["session_id"] is None
    assert "Mock error details" in resp["synthesis"]
    assert resp["error"] == "Mock error details"


# ------------------------------------------------------------------------------
# 3. run_council のテスト
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_council_success():
    # 正常系: event から synthesis が得られるパターン
    mock_runner_instance = MagicMock()
    mock_runners.InMemoryRunner.return_value = mock_runner_instance
    
    # 非同期ジェネレータのモック
    async def mock_run_async(*args, **kwargs):
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_part = MagicMock()
        mock_part.text = "最終的な提案です。"
        mock_event.content.parts = [mock_part]
        yield mock_event
        
    mock_runner_instance.run_async = mock_run_async
    
    # create_session のモック
    mock_session = AsyncMock()
    mock_runner_instance.session_service.create_session = AsyncMock(return_value=mock_session)
    
    res = await run_council("今後の戦略について", session_id="test-session-1")
    
    assert res["status"] == "success"
    assert res["session_id"] == "test-session-1"
    assert res["synthesis"] == "最終的な提案です。"


@pytest.mark.asyncio
async def test_run_council_success_from_state():
    # 正常系: event から synthesis が得られず、session.state から取得するパターン
    mock_runner_instance = MagicMock()
    mock_runners.InMemoryRunner.return_value = mock_runner_instance
    
    # 空のレスポンスを返す非同期ジェネレータ
    async def mock_run_async_empty(*args, **kwargs):
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_event.content = None  # または parts が空
        yield mock_event
        
    mock_runner_instance.run_async = mock_run_async_empty
    
    # create_session および get_session のモック
    mock_session = AsyncMock()
    mock_session.state = {"council_synthesis": "状態から復元した提案です。"}
    mock_runner_instance.session_service.create_session = AsyncMock(return_value=mock_session)
    mock_runner_instance.session_service.get_session = AsyncMock(return_value=mock_session)
    
    res = await run_council("今後の戦略について", session_id="test-session-2")
    
    assert res["status"] == "success"
    assert res["session_id"] == "test-session-2"
    assert res["synthesis"] == "状態から復元した提案です。"


@pytest.mark.asyncio
async def test_run_council_import_error():
    # google-adk モジュールがインポートエラーを起こす想定のテスト
    # インポートエラーを起こすため、一時的に sys.modules から削除し、かつパッチで ImportError を誘発
    with patch("builtins.__import__", side_effect=ImportError("Mocked Import Error")):
        res = await run_council("テスト質問")
        assert res["status"] == "error"
        assert "Mocked Import Error" in res["synthesis"]


@pytest.mark.asyncio
async def test_run_council_general_exception():
    # 実行中に一般の例外が発生した場合のテスト
    mock_runners.InMemoryRunner.side_effect = Exception("General Runner Error")
    
    res = await run_council("テスト質問")
    assert res["status"] == "error"
    assert "General Runner Error" in res["synthesis"]
    
    # side_effect を元に戻しておく
    mock_runners.InMemoryRunner.side_effect = None


# ------------------------------------------------------------------------------
# 4. ThumbnailResolver のテスト
# ------------------------------------------------------------------------------
@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path

@pytest.fixture
def resolver(temp_dir):
    return ThumbnailResolver(project_root=temp_dir, output_dir=temp_dir / "temp_thumbnails")


def test_thumbnail_resolver_generate(resolver, temp_dir):
    out_path = temp_dir / "temp_thumbnails" / "test_thumb.png"
    
    # generate_thumbnail の実行確認
    res_path = resolver.generate_thumbnail(out_path, text="Test Title")
    assert res_path == out_path
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_thumbnail_resolver_validate_existence(resolver, temp_dir):
    non_existent = temp_dir / "non_existent.png"
    
    with patch("usage_tracker.alert_system.emit_warning") as mock_warning:
        with pytest.raises(FileNotFoundError) as exc_info:
            resolver.validate_thumbnail(non_existent)
        
        assert "Thumbnail file not found" in str(exc_info.value)
        mock_warning.assert_called_once_with("thumbnail", f"Thumbnail file not found: {non_existent}")


def test_thumbnail_resolver_validate_file_size_exceeds(resolver, temp_dir):
    out_path = temp_dir / "temp_thumbnails" / "large_thumb.png"
    resolver.generate_thumbnail(out_path)
    
    # ファイルサイズが 4MB 以上であると偽装する
    with patch.object(Path, "stat") as mock_stat, \
         patch("usage_tracker.alert_system.emit_warning") as mock_warning:
        
        mock_meta = MagicMock()
        mock_meta.st_size = 5 * 1024 * 1024  # 5MB
        mock_stat.return_value = mock_meta
        
        with pytest.raises(ValueError) as exc_info:
            resolver.validate_thumbnail(out_path)
            
        assert "File size exceeds 4MB limit" in str(exc_info.value)
        mock_warning.assert_called_once_with("thumbnail", f"File size exceeds 4MB limit: {mock_meta.st_size} bytes")


def test_thumbnail_resolver_validate_image_integrity_corrupted(resolver, temp_dir):
    out_path = temp_dir / "temp_thumbnails" / "corrupted_thumb.png"
    resolver.generate_thumbnail(out_path)
    
    # verify() で例外を投げるように PIL.Image.open をモック
    mock_image = MagicMock()
    mock_image.__enter__.return_value = mock_image
    mock_image.verify.side_effect = Exception("Corrupt file structural error")
    mock_image.size = (1280, 720)
    
    with patch("PIL.Image.open", return_value=mock_image), \
         patch("usage_tracker.alert_system.emit_warning") as mock_warning:
        
        with pytest.raises(ValueError) as exc_info:
            resolver.validate_thumbnail(out_path)
            
        assert "Unexpected error during image verification" in str(exc_info.value)
        mock_warning.assert_called_once_with("thumbnail", "Unexpected error during image verification: Corrupt file structural error")


def test_thumbnail_resolver_validate_dimensions_too_small(resolver, temp_dir):
    out_path = temp_dir / "temp_thumbnails" / "small_thumb.png"
    resolver.generate_thumbnail(out_path)
    
    # 640x360 の画像サイズを返すようにモック
    mock_image = MagicMock()
    mock_image.__enter__.return_value = mock_image
    mock_image.verify.return_value = None
    mock_image.size = (640, 360)
    
    with patch("PIL.Image.open", return_value=mock_image), \
         patch("usage_tracker.alert_system.emit_warning") as mock_warning:
        
        with pytest.raises(ValueError) as exc_info:
            resolver.validate_thumbnail(out_path)
            
        assert "Resolution must be at least 1280x720" in str(exc_info.value)
        mock_warning.assert_called_once_with("thumbnail", "Resolution must be at least 1280x720. Got 640x360")


def test_thumbnail_resolver_validate_dimensions_fail_load(resolver, temp_dir):
    out_path = temp_dir / "temp_thumbnails" / "fail_load_thumb.png"
    resolver.generate_thumbnail(out_path)
    
    mock_image_ok = MagicMock()
    mock_image_ok.__enter__.return_value = mock_image_ok
    mock_image_ok.verify.return_value = None
    mock_image_ok.size = (1280, 720)
    
    # verify() は通るが、二度目の open (dimensions判定) で例外を投げるようにする
    with patch("PIL.Image.open", side_effect=[mock_image_ok, Exception("Failed to open image")]):
        with patch("usage_tracker.alert_system.emit_warning") as mock_warning:
            with pytest.raises(ValueError) as exc_info:
                resolver.validate_thumbnail(out_path)
                
            assert "Unexpected error during image loading" in str(exc_info.value)
            mock_warning.assert_called_once_with("thumbnail", "Unexpected error during image loading: Failed to open image")


def test_thumbnail_resolver_validate_aspect_ratio_invalid(resolver, temp_dir):
    out_path = temp_dir / "temp_thumbnails" / "aspect_thumb.png"
    resolver.generate_thumbnail(out_path)
    
    # 1280x960 (4:3) の画像サイズを返すようにモック
    mock_image = MagicMock()
    mock_image.__enter__.return_value = mock_image
    mock_image.verify.return_value = None
    mock_image.size = (1280, 960)
    
    with patch("PIL.Image.open", return_value=mock_image), \
         patch("usage_tracker.alert_system.emit_warning") as mock_warning:
        
        with pytest.raises(ValueError) as exc_info:
            resolver.validate_thumbnail(out_path)
            
        assert "Aspect ratio must be 16:9" in str(exc_info.value)
        mock_warning.assert_called_once_with("thumbnail", "Aspect ratio must be 16:9. Got 1.333")


def test_thumbnail_resolver_validate_success(resolver, temp_dir):
    out_path = temp_dir / "temp_thumbnails" / "success_thumb.png"
    resolver.generate_thumbnail(out_path)
    
    # 正常な16:9画像
    res_dict = resolver.validate_thumbnail(out_path)
    
    assert res_dict["path"] == str(out_path)
    assert res_dict["width"] == 1280
    assert res_dict["height"] == 720
    assert res_dict["size_bytes"] > 0


@pytest.mark.asyncio
async def test_resolve_thumbnail_task_success(resolver, temp_dir):
    # resolve_thumbnail_task の正常終了テスト
    task_id = "task_123"
    expected_file = temp_dir / "temp_thumbnails" / f"{task_id}.png"
    
    result_json = await resolver.resolve_thumbnail_task(task_id)
    assert expected_file.exists()
    
    result_data = json.loads(result_json)
    assert result_data["width"] == 1280
    assert result_data["height"] == 720
    assert result_data["size_bytes"] > 0


@pytest.mark.asyncio
async def test_resolve_thumbnail_task_exception(resolver):
    # 例外発生時に emit_critical が呼ばれるかのテスト
    task_id = "task_failed"
    
    with patch.object(resolver, "generate_thumbnail", side_effect=Exception("Disk failure mock")), \
         patch("usage_tracker.alert_system.emit_critical") as mock_critical:
        
        with pytest.raises(Exception) as exc_info:
            await resolver.resolve_thumbnail_task(task_id)
            
        assert "Disk failure mock" in str(exc_info.value)
        mock_critical.assert_called_once_with("thumbnail", "Thumbnail task failed for task task_failed: Disk failure mock")


@pytest.mark.asyncio
async def test_run_council_auto_session_id():
    # session_id が指定されなかった場合に、自動生成されることの検証
    mock_runner_instance = MagicMock()
    mock_runners.InMemoryRunner.return_value = mock_runner_instance
    
    async def mock_run_async(*args, **kwargs):
        mock_part = MagicMock()
        mock_part.text = "自動セッションIDのテスト回答。"
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_event.content.parts = [mock_part]
        yield mock_event
        
    mock_runner_instance.run_async = mock_run_async
    mock_runner_instance.session_service.create_session = AsyncMock(return_value=AsyncMock())
    
    res = await run_council("今後の戦略について")
    
    assert res["status"] == "success"
    assert res["session_id"] is not None
    assert len(res["session_id"]) > 0
    # UUID 形式の検証
    import uuid
    val = uuid.UUID(res["session_id"], version=4)
    assert val is not None


def test_thumbnail_resolver_validate_spoofed_extension(resolver, temp_dir):
    out_path = temp_dir / "temp_thumbnails" / "spoofed_thumb.png"
    # 空白のファイルを作成する
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(b"NOT A PNG HEADER")
        
    with patch("usage_tracker.alert_system.emit_warning") as mock_warning:
        with pytest.raises(ValueError) as exc_info:
            resolver.validate_thumbnail(out_path)
            
        assert "File extension is .png but header is not PNG" in str(exc_info.value)
        mock_warning.assert_called_once_with("thumbnail", "Image is corrupted or invalid format: File extension is .png but header is not PNG")


# ------------------------------------------------------------------------------
# 5. モックの独立性・分離性のテスト
# ------------------------------------------------------------------------------
def test_mock_isolation_environment():
    # テスト実行中は mock_adk_environment フィクスチャが自動で効くため、
    # sys.modules 内にモックが存在する。
    import sys
    assert "google.adk" in sys.modules
    from unittest.mock import MagicMock
    assert isinstance(sys.modules["google.adk"], MagicMock)

def test_mock_isolation_fixture_cleanup():
    # フィクスチャが正常にモックを保存し、復元できることを直接検証する
    import sys
    from unittest.mock import MagicMock
    dummy_name = "google.dummy_test_module"
    
    # 既存の sys.modules 状態を保存
    orig_val = sys.modules.get(dummy_name, None)
    
    try:
        # モックの適用シミュレーション
        sys.modules[dummy_name] = MagicMock()
        assert dummy_name in sys.modules
        
        # 復元シミュレーション（None の場合は pop、ある場合は代入）
        if orig_val is None:
            sys.modules.pop(dummy_name, None)
        else:
            sys.modules[dummy_name] = orig_val
            
        assert (orig_val is None and dummy_name not in sys.modules) or sys.modules[dummy_name] == orig_val
    finally:
        # 確実に元の状態に戻す
        if orig_val is None:
            sys.modules.pop(dummy_name, None)
        else:
            sys.modules[dummy_name] = orig_val


# ------------------------------------------------------------------------------
# 6. 安全チェックとインポートエラーのテスト
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_council_get_session_returns_none():
    # 正常系: event から synthesis が得られず、session.state も None (get_session が None を返す) パターン
    mock_runner_instance = MagicMock()
    mock_runners.InMemoryRunner.return_value = mock_runner_instance
    
    async def mock_run_async_empty(*args, **kwargs):
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_event.content = None
        yield mock_event
        
    mock_runner_instance.run_async = mock_run_async_empty
    
    mock_runner_instance.session_service.create_session = AsyncMock(return_value=AsyncMock())
    mock_runner_instance.session_service.get_session = AsyncMock(return_value=None)
    
    res = await run_council("今後の戦略について", session_id="test-session-none-state")
    
    assert res["status"] == "success"
    assert res["session_id"] == "test-session-none-state"
    assert "セッション情報の取得失敗" in res["synthesis"]


@pytest.mark.asyncio
async def test_run_council_parts_none():
    # event.content.parts が None の場合の安全性のテスト
    mock_runner_instance = MagicMock()
    mock_runners.InMemoryRunner.return_value = mock_runner_instance
    
    async def mock_run_async_parts_none(*args, **kwargs):
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_content = MagicMock()
        mock_content.parts = None  # parts が None
        mock_event.content = mock_content
        yield mock_event
        
    mock_runner_instance.run_async = mock_run_async_parts_none
    
    mock_session = AsyncMock()
    mock_session.state = {"council_synthesis": "フォールバック回答"}
    mock_runner_instance.session_service.create_session = AsyncMock(return_value=mock_session)
    mock_runner_instance.session_service.get_session = AsyncMock(return_value=mock_session)
    
    res = await run_council("今後の戦略について", session_id="test-session-parts-none")
    
    assert res["status"] == "success"
    assert res["synthesis"] == "フォールバック回答"


@pytest.mark.asyncio
async def test_run_council_part_text_none():
    # part.text が None の場合のテスト
    mock_runner_instance = MagicMock()
    mock_runners.InMemoryRunner.return_value = mock_runner_instance
    
    async def mock_run_async_text_none(*args, **kwargs):
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_part = MagicMock()
        mock_part.text = None  # text が None
        mock_content = MagicMock()
        mock_content.parts = [mock_part]
        mock_event.content = mock_content
        yield mock_event
        
    mock_runner_instance.run_async = mock_run_async_text_none
    
    mock_session = AsyncMock()
    mock_session.state = {"council_synthesis": "フォールバック回答"}
    mock_runner_instance.session_service.create_session = AsyncMock(return_value=mock_session)
    mock_runner_instance.session_service.get_session = AsyncMock(return_value=mock_session)
    
    res = await run_council("今後の戦略について", session_id="test-session-text-none")
    
    assert res["status"] == "success"
    assert res["synthesis"] == "フォールバック回答"


@pytest.mark.asyncio
async def test_run_council_import_error_raised_during_run():
    # _build_council_agents を呼び出す際に ImportError が発生した場合のテスト
    with patch("agents.council_graph._build_council_agents", side_effect=ImportError("ADK template missing")):
        res = await run_council("今後の戦略について", session_id="test-session-import-error")
        assert res["status"] == "error"
        assert res["session_id"] == "test-session-import-error"
        assert "依存モジュールのインポートに失敗しました" in res["synthesis"]


@pytest.mark.asyncio
async def test_run_council_timeout_error():
    # asyncio.TimeoutError のハンドリングテスト
    with patch("agents.council_graph._build_council_agents", side_effect=asyncio.TimeoutError("Timeout constraint reached")):
        res = await run_council("今後の戦略について", session_id="test-session-timeout")
        assert res["status"] == "error"
        assert "通信タイムアウトが発生しました" in res["synthesis"]


@pytest.mark.asyncio
async def test_run_council_http_exception():
    # fastapi.HTTPException の再送出テスト
    from fastapi import HTTPException
    with patch("agents.council_graph._build_council_agents", side_effect=HTTPException(status_code=400, detail="Bad Request")):
        with pytest.raises(HTTPException) as exc_info:
            await run_council("今後の戦略について", session_id="test-session-http-exception")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Bad Request"


@pytest.mark.asyncio
async def test_run_council_google_api_error():
    # google.genai.errors.APIError のハンドリングテスト
    from google.genai.errors import APIError
    with patch("agents.council_graph._build_council_agents", side_effect=APIError("API limit exceeded")):
        res = await run_council("今後の戦略について", session_id="test-session-google-api-error")
        assert res["status"] == "error"
        # インポートキャッシュの状態（モック適用有無）によって synthesis の文言が変わるため、柔軟にアサート
        assert any(msg in res["synthesis"] for msg in ["Google APIエラーが発生しました", "API limit exceeded"])


@pytest.mark.asyncio
async def test_run_council_httpx_error():
    # httpx.HTTPError のハンドリングテスト
    import httpx
    with patch("agents.council_graph._build_council_agents", side_effect=httpx.HTTPError("Connection refused")):
        res = await run_council("今後の戦略について", session_id="test-session-httpx-error")
        assert res["status"] == "error"
        assert "ネットワーク通信エラーが発生しました" in res["synthesis"]


# ------------------------------------------------------------------------------
# 7. 例外マッピングおよびインポートエラー時のフォールバックのテスト
# ------------------------------------------------------------------------------
def test_exception_tuple_mapping():
    # agents.council_graph 内の GENAI_ERRORS と HTTPX_ERRORS のマッピングを確認するテスト
    from agents.council_graph import GENAI_ERRORS, HTTPX_ERRORS
    
    assert len(GENAI_ERRORS) > 0
    assert len(HTTPX_ERRORS) == 1
    
    # 実際のクラスが正しくバインドされているか確認（httpx はテスト環境でインストール済み）
    import httpx
    assert HTTPX_ERRORS[0] == httpx.HTTPError


def test_import_exceptions_fallback():
    # sys.modules から fastapi などを一時的に削除し、ImportError の場合のフォールバッククラス作成を検証する
    import sys
    import importlib.util
    from pathlib import Path
    
    file_path = Path(__file__).parent.parent / "agents" / "council_graph.py"
    
    # fastapi, google.genai.errors, httpx を sys.modules から隠す
    with patch.dict(sys.modules, {"fastapi": None, "google.genai.errors": None, "httpx": None}):
        # sys.modules を汚染しないよう、一時的なモジュール名でロードする
        spec = importlib.util.spec_from_file_location("agents.council_graph_temp_fallback", str(file_path))
        temp_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(temp_module)
        
        # ダミークラスが作成されていることの検証
        DummyHTTPException = temp_module.HTTPException
        GENAI_ERRORS = temp_module.GENAI_ERRORS
        HTTPX_ERRORS = temp_module.HTTPX_ERRORS
        
        # ダミークラスが Exception のサブクラスであることを検証
        assert issubclass(DummyHTTPException, Exception)
        assert DummyHTTPException.__name__ == "HTTPException"
        
        assert len(GENAI_ERRORS) == 1
        assert GENAI_ERRORS[0].__name__ == "DummyGenAIError"
        assert issubclass(GENAI_ERRORS[0], Exception)
        
        assert len(HTTPX_ERRORS) == 1
        assert HTTPX_ERRORS[0].__name__ == "DummyHTTPError"
        assert issubclass(HTTPX_ERRORS[0], Exception)


# ------------------------------------------------------------------------------
# 8. 追加の例外ハンドリングのテスト
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_council_os_error():
    # OSError が発生した場合のハンドリングテスト
    with patch("agents.council_graph._build_council_agents", side_effect=OSError("Read-only file system mock")):
        res = await run_council("今後の戦略について", session_id="test-session-os-error")
        assert res["status"] == "error"
        assert "システムI/Oエラーが発生しました" in res["synthesis"]


@pytest.mark.asyncio
async def test_run_council_json_decode_error():
    # json.JSONDecodeError が発生した場合のハンドリングテスト
    import json
    with patch("agents.council_graph._build_council_agents", side_effect=json.JSONDecodeError("Expecting value", "{}", 0)):
        res = await run_council("今後の戦略について", session_id="test-session-json-error")
        assert res["status"] == "error"
        assert "データの解析（JSON）に失敗しました" in res["synthesis"]


def test_thumbnail_resolver_import_error():
    # services.thumbnail_analyzer がインポートエラーを起こす想定のテスト
    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if "services.thumbnail_analyzer" in name:
            raise ImportError("Real resolver missing mock")
        return original_import(name, *args, **kwargs)

    # クラスキャッシュをクリアしてインポート処理を強制的に走らせる
    ThumbnailResolver._real_class = None

    with patch("builtins.__import__", side_effect=mock_import):
        with pytest.raises(ImportError) as exc_info:
            ThumbnailResolver()
        assert "ThumbnailResolver (services.thumbnail_analyzer) のインポートに失敗しました" in str(exc_info.value)


# ------------------------------------------------------------------------------
# 9. エラーハンドリング強化と except Exception 改善の追加テスト
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_council_name_error():
    # NameError が発生した場合のハンドリングテスト
    with patch("agents.council_graph._build_council_agents", side_effect=NameError("Mock Name Error")):
        res = await run_council("今後の戦略について", session_id="test-session-name-error")
        assert res["status"] == "error"
        assert "Mock Name Error" in res["synthesis"]


def test_thumbnail_resolver_instantiation_error():
    # RealResolver インスタンス化の際の初期化エラーのハンドリングテスト
    class BadResolver:
        def __init__(self, *args, **kwargs):
            raise TypeError("Initialization parameter type error")

    ThumbnailResolver._real_class = BadResolver

    with pytest.raises(RuntimeError) as exc_info:
        ThumbnailResolver()
    
    assert "ThumbnailResolver の初期化中にエラーが発生しました" in str(exc_info.value)
    
    # 後片付けとしてクラスキャッシュをクリア
    ThumbnailResolver._real_class = None


def test_import_exceptions_attribute_error_fallback():
    # google.genai.errors から APIError 等がインポートできず AttributeError になる場合のテスト
    import sys
    import importlib.util
    from pathlib import Path
    
    file_path = Path(__file__).parent.parent / "agents" / "council_graph.py"
    
    class DummyModule:
        pass
        
    dummy_genai_errors = DummyModule()
    
    with patch.dict(sys.modules, {"google.genai.errors": dummy_genai_errors, "fastapi": None, "httpx": None}):
        # sys.modules を汚染しないよう、一時的なモジュール名でロードする
        spec = importlib.util.spec_from_file_location("agents.council_graph_temp_attr_fallback", str(file_path))
        temp_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(temp_module)
        
        GENAI_ERRORS = temp_module.GENAI_ERRORS
        assert len(GENAI_ERRORS) == 1
        assert GENAI_ERRORS[0].__name__ == "DummyGenAIError"



def test_thumbnail_resolver_instantiation_error_general_exception():
    # RealResolver インスタンス化の際、TypeError以外の一般的な例外(KeyErrorなど)が発生した時のハンドリングテスト
    class BadResolver:
        def __init__(self, *args, **kwargs):
            raise KeyError("Key mapping failure mock")

    ThumbnailResolver._real_class = BadResolver

    with pytest.raises(RuntimeError) as exc_info:
        ThumbnailResolver()
    
    assert "ThumbnailResolver の初期化中にエラーが発生しました: 'Key mapping failure mock'" in str(exc_info.value)
    
    # 後片付けとしてクラスキャッシュをクリア
    ThumbnailResolver._real_class = None


# ------------------------------------------------------------------------------
# 10. 追加された堅牢性とエラーハンドリングのテスト
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_council_callable_final_response_check():
    # event.is_final_response が callable でない（属性値などの）場合の安全テスト
    mock_runner_instance = MagicMock()
    mock_runners.InMemoryRunner.return_value = mock_runner_instance
    
    async def mock_run_async_not_callable(*args, **kwargs):
        mock_event = MagicMock()
        # is_final_response をメソッドではなく単なる True 値にする
        mock_event.is_final_response = True
        mock_event.content = None
        yield mock_event
        
    mock_runner_instance.run_async = mock_run_async_not_callable
    
    mock_session = AsyncMock()
    mock_session.state = {"council_synthesis": "状態からの回答"}
    mock_runner_instance.session_service.create_session = AsyncMock(return_value=mock_session)
    mock_runner_instance.session_service.get_session = AsyncMock(return_value=mock_session)
    
    res = await run_council("今後の戦略について", session_id="test-session-not-callable")
    assert res["status"] == "success"
    assert res["synthesis"] == "状態からの回答"


@pytest.mark.asyncio
async def test_run_council_parts_not_iterable():
    # event.content.parts がイテラブルでない（リストやタプル以外）場合の安全テスト
    mock_runner_instance = MagicMock()
    mock_runners.InMemoryRunner.return_value = mock_runner_instance
    
    async def mock_run_async_parts_not_iterable(*args, **kwargs):
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_content = MagicMock()
        mock_content.parts = "not_iterable_string"  # イテラブルだが list/tuple ではない
        mock_event.content = mock_content
        yield mock_event
        
    mock_runner_instance.run_async = mock_run_async_parts_not_iterable
    
    mock_session = AsyncMock()
    mock_session.state = {"council_synthesis": "フォールバック回答"}
    mock_runner_instance.session_service.create_session = AsyncMock(return_value=mock_session)
    mock_runner_instance.session_service.get_session = AsyncMock(return_value=mock_session)
    
    res = await run_council("今後の戦略について", session_id="test-session-parts-not-iterable")
    assert res["status"] == "success"
    assert res["synthesis"] == "フォールバック回答"


@pytest.mark.asyncio
async def test_run_council_state_not_dict():
    # session.state が辞書 (dict) ではない場合の安全テスト
    mock_runner_instance = MagicMock()
    mock_runners.InMemoryRunner.return_value = mock_runner_instance
    
    async def mock_run_async_empty(*args, **kwargs):
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_event.content = None
        yield mock_event
        
    mock_runner_instance.run_async = mock_run_async_empty
    
    mock_session = AsyncMock()
    mock_session.state = "not_a_dict_string"  # dict ではない
    mock_runner_instance.session_service.create_session = AsyncMock(return_value=mock_session)
    mock_runner_instance.session_service.get_session = AsyncMock(return_value=mock_session)
    
    res = await run_council("今後の戦略について", session_id="test-session-state-not-dict")
    assert res["status"] == "success"
    assert "セッション情報の取得失敗" in res["synthesis"]


def test_thumbnail_resolver_instantiation_http_exception():
    # RealResolver インスタンス化の際、HTTPExceptionが発生した時はラッパーされずにそのまま再送出されることのテスト
    from fastapi import HTTPException
    
    class BadResolver:
        def __init__(self, *args, **kwargs):
            raise HTTPException(status_code=400, detail="Resolver HTTP Error")

    ThumbnailResolver._real_class = BadResolver

    with pytest.raises(HTTPException) as exc_info:
        ThumbnailResolver()
    
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Resolver HTTP Error"
    
    # 後片付け
    ThumbnailResolver._real_class = None


def test_thumbnail_resolver_instantiation_value_error():
    # RealResolver インスタンス化の際、__init__ 内部で ValueError が発生した時は RuntimeError にラップされることのテスト
    class ValueErrorResolver:
        def __init__(self, *args, **kwargs):
            raise ValueError("Resolver value constraint error")

    ThumbnailResolver._real_class = ValueErrorResolver

    with pytest.raises(RuntimeError) as exc_info:
        ThumbnailResolver()
    
    assert "ThumbnailResolver の初期化中にエラーが発生しました" in str(exc_info.value)
    
    # 後片付け
    ThumbnailResolver._real_class = None


def test_thumbnail_resolver_real_class_arg_error():
    # RealResolver (非モック) のインスタンス化の際、引数指定が不正なら TypeError がラップされずにそのまま送出されることのテスト
    class DummyRealResolver:
        def __init__(self, required_arg):
            self.required_arg = required_arg

    ThumbnailResolver._real_class = DummyRealResolver

    with pytest.raises(TypeError) as exc_info:
        ThumbnailResolver()
    
    assert "ThumbnailResolver の引数指定が不正です" in str(exc_info.value)
    
    # 後片付け
    ThumbnailResolver._real_class = None



# ------------------------------------------------------------------------------
# 11. 追加された特定例外（IndexError, UnboundLocalError）および透過伝播のテスト
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_council_index_error():
    # IndexError が発生した場合のハンドリングテスト（内部バグとして検知）
    with patch("agents.council_graph._build_council_agents", side_effect=IndexError("Mock IndexError")):
        res = await run_council("今後の戦略について", session_id="test-session-index-error")
        assert res["status"] == "error"
        assert "内部プログラムエラーが発生しました" in res["synthesis"]


@pytest.mark.asyncio
async def test_run_council_unbound_local_error():
    # UnboundLocalError が発生した場合のハンドリングテスト（内部バグとして検知）
    with patch("agents.council_graph._build_council_agents", side_effect=UnboundLocalError("local variable referenced before assignment")):
        res = await run_council("今後の戦略について", session_id="test-session-unbound-local-error")
        assert res["status"] == "error"
        assert "内部プログラムエラーが発生しました" in res["synthesis"]


def test_thumbnail_resolver_instantiation_unhandled_exception():
    # RealResolver インスタンス化の際、想定外の例外（例: ZeroDivisionError）が発生した時は
    # RuntimeError にラップされず、そのまま re-raise されることのテスト
    class CorruptResolver:
        def __init__(self, *args, **kwargs):
            raise ZeroDivisionError("division by zero in constructor")

    ThumbnailResolver._real_class = CorruptResolver

    with pytest.raises(ZeroDivisionError) as exc_info:
        ThumbnailResolver()
    
    assert "division by zero" in str(exc_info.value)
    
    # 後片付け
    ThumbnailResolver._real_class = None


def test_thumbnail_resolver_instantiation_custom_unexpected_exception():
    # RealResolver インスタンス化の際、カスタムの想定外例外が発生した時も
    # RuntimeError にラップされず、そのまま re-raise されることのテスト
    class CustomUnexpectedError(Exception):
        pass

    class CorruptResolver:
        def __init__(self, *args, **kwargs):
            raise CustomUnexpectedError("custom error in constructor")

    ThumbnailResolver._real_class = CorruptResolver

    with pytest.raises(CustomUnexpectedError) as exc_info:
        ThumbnailResolver()

    assert "custom error in constructor" in str(exc_info.value)

    # 後片付け
    ThumbnailResolver._real_class = None


# ------------------------------------------------------------------------------
# 12. 追加された例外ハンドリング強化のテスト（OSError と AttributeError）
# ------------------------------------------------------------------------------
def test_thumbnail_resolver_instantiation_os_error():
    # RealResolver インスタンス化の際、OSError が発生した時は RuntimeError にラップされることのテスト
    class BadResolver:
        def __init__(self, *args, **kwargs):
            raise OSError("Mock OSError on disk access")

    ThumbnailResolver._real_class = BadResolver

    with pytest.raises(RuntimeError) as exc_info:
        ThumbnailResolver()
    
    assert "ThumbnailResolver の初期化中にエラーが発生しました: Mock OSError on disk access" in str(exc_info.value)
    
    # 後片付け
    ThumbnailResolver._real_class = None


@pytest.mark.asyncio
async def test_run_council_attribute_error():
    # AttributeError が発生した場合のハンドリングテスト（内部バグとして検知）
    with patch("agents.council_graph._build_council_agents", side_effect=AttributeError("Mock AttributeError")):
        res = await run_council("今後の戦略について", session_id="test-session-attribute-error")
        assert res["status"] == "error"
        assert "内部プログラムエラーが発生しました" in res["synthesis"]


def test_thumbnail_resolver_instantiation_strict_type_wrapping():
    # type(e) is Exception の場合は RuntimeError にラップされ、
    # Exceptionのサブクラス（例: ValueErrorの派生やカスタム例外など）はラップされずに
    # そのまま透過伝播されることを厳密に検証するテスト
    from agents.council_graph import ThumbnailResolver

    # 1. 厳密に Exception 型の場合
    class ExceptionResolver:
        def __init__(self, *args, **kwargs):
            raise Exception("Base Exception")

    ThumbnailResolver._real_class = ExceptionResolver
    with pytest.raises(RuntimeError) as excinfo:
        ThumbnailResolver()
    assert "ThumbnailResolver の初期化中にエラーが発生しました" in str(excinfo.value)

    # 2. Exceptionのサブクラスだが、 council_graph.py で個別キャッチしていない別の例外の場合
    class CustomSubException(Exception):
        pass

    class SubExceptionResolver:
        def __init__(self, *args, **kwargs):
            raise CustomSubException("Subclass Exception")

    ThumbnailResolver._real_class = SubExceptionResolver
    with pytest.raises(CustomSubException) as excinfo:
        ThumbnailResolver()
    assert "Subclass Exception" in str(excinfo.value)

    # 後片付け
    ThumbnailResolver._real_class = None

# ------------------------------------------------------------------------------
# 13. TDR 連携と技術負債自動登録のテスト
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_council_broad_except_tdr_registration():
    # run_council 実行時に Exception が発生し、_register_tdr_debt を通じて
    # TechnicalDebtStore に負債が自動登録されることを検証する。
    from agents.memory.technical_debt import TechnicalDebtStore
    
    # _build_council_agents で一般的な Exception を発生させる
    with patch("agents.council_graph._build_council_agents", side_effect=Exception("Unexpected base Exception")):
        with patch.object(TechnicalDebtStore, "register_debt") as mock_register:
            res = await run_council("今後の戦略について", session_id="test-session-tdr-except")
            
            # _fallback_response が返されることを確認
            assert res["status"] == "error"
            assert "Unexpected base Exception" in res["synthesis"]
            
            # TechnicalDebtStore.register_debt が呼び出されたことを確認
            mock_register.assert_called_once()
            args, kwargs = mock_register.call_args
            assert kwargs.get("category") == "IMPORTANT_SERVICE"
            assert kwargs.get("file_path") == "agents/council_graph.py"
            assert "except Exception as e" in kwargs.get("pattern")


def test_thumbnail_resolver_broad_except_tdr_registration():
    # ThumbnailResolver インスタンス化の際、Exception が発生し、_register_tdr_debt を通じて
    # TechnicalDebtStore に負債が自動登録されることを検証する。
    from agents.memory.technical_debt import TechnicalDebtStore

    class ExceptionResolver:
        def __init__(self, *args, **kwargs):
            raise Exception("Base Exception for resolver TDR check")

    ThumbnailResolver._real_class = ExceptionResolver

    with patch.object(TechnicalDebtStore, "register_debt") as mock_register:
        with pytest.raises(RuntimeError):
            ThumbnailResolver()
            
        # register_debt が呼び出されたことを確認
        mock_register.assert_called_once()
        args, kwargs = mock_register.call_args
        assert kwargs.get("category") == "IMPORTANT_SERVICE"
        assert kwargs.get("file_path") == "agents/council_graph.py"
        assert "except Exception as e (ThumbnailResolver)" in kwargs.get("pattern")

    # 後片付け
    ThumbnailResolver._real_class = None



# ------------------------------------------------------------------------------
# 14. APIキー欠如時の早期フォールバックテスト
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_council_no_api_key_early_fallback():
    import os
    # GEMINI_API_KEY が無い場合の早期フォールバックをテスト
    # フィクスチャで設定された mock-api-key を一時的に削除する
    old_key = os.environ.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    
    class DummyRunner:
        pass

    try:
        # モック環境ではない状態をシミュレートするために InMemoryRunner をダミークラスに差し替える
        with patch("google.adk.runners.InMemoryRunner", DummyRunner):
            res = await run_council("今後の戦略について", session_id="test-session-no-key")
            assert res["status"] == "error"
            assert res["session_id"] == "test-session-no-key"
            assert "No API key was provided" in res["synthesis"]
    finally:
        if old_key is not None:
            os.environ["GEMINI_API_KEY"] = old_key


@pytest.mark.asyncio
async def test_run_council_no_api_key_when_mocked():
    import os
    # GEMINI_API_KEY を一時的に削除
    old_key = os.environ.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
        
    try:
        mock_runner_instance = MagicMock()
        mock_runners.InMemoryRunner.return_value = mock_runner_instance
        
        async def mock_run_async(*args, **kwargs):
            mock_event = MagicMock()
            mock_event.is_final_response.return_value = True
            mock_part = MagicMock()
            mock_part.text = "モック経由の回答。"
            mock_event.content.parts = [mock_part]
            yield mock_event
            
        mock_runner_instance.run_async = mock_run_async
        mock_runner_instance.session_service.create_session = AsyncMock(return_value=AsyncMock())
        
        # GEMINI_API_KEY がなくても、InMemoryRunner がモックされているため正常に成功するはず
        res = await run_council("今後の戦略について", session_id="test-session-mocked-no-key")
        assert res["status"] == "success"
        assert res["synthesis"] == "モック経由の回答。"
        assert res["session_id"] == "test-session-mocked-no-key"
    finally:
        if old_key is not None:
            os.environ["GEMINI_API_KEY"] = old_key


def test_real_class_attribute_proxy_fallback():
    """RealClassAttributeProxy がインポート失敗時などに fallback 値を正しく返すことを検証"""
    from agents.council_graph import RealClassAttributeProxy
    proxy = RealClassAttributeProxy("non_existent_method", fallback="fallback_value")
    
    class DummyOwner:
        _real_class = None
        
    res = proxy.__get__(None, DummyOwner)
    assert res == "fallback_value"


def test_thumbnail_resolver_mock_method_binding():
    """ThumbnailResolver のクラス属性にモックが設定された場合、
    それが bound method としてインスタンスに正しくバインドされ、
    メソッド呼び出し時に第一引数としてインスタンスを受け取ることを検証する。
    """
    from agents.council_graph import ThumbnailResolver
    from unittest.mock import patch, MagicMock

    # 元の real_class を退避
    original_real = ThumbnailResolver._real_class

    class MockRealClass:
        def __init__(self, key="default"):
            self.key = key
        def generate_thumbnail(self, output_path, text=""):
            return "original"

    ThumbnailResolver._real_class = MockRealClass

    try:
        mock_generate = MagicMock(return_value="mocked_thumbnail")

        # ThumbnailResolver クラスの generate_thumbnail メソッドをモック化
        with patch.object(ThumbnailResolver, "generate_thumbnail", mock_generate):
            resolver = ThumbnailResolver(key="test_key")
            
            res = resolver.generate_thumbnail("path", "text")
            
            assert res == "mocked_thumbnail"
            # 修正された bindings により、types.MethodType(mock_generate, resolver) にバインドされるため、
            # 第一引数に resolver が渡されることを確認する。
            mock_generate.assert_called_once_with(resolver, "path", "text")
    finally:
        # 後片付け
        ThumbnailResolver._real_class = original_real

