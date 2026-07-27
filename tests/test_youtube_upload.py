import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# カレントディレクトリ(ワークスペースルート)を取得してsys.pathに追加
cwd = Path.cwd()
workspace_root = str(cwd)
workspace_backend = str(cwd / "backend")

if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)
if workspace_backend not in sys.path:
    sys.path.insert(0, workspace_backend)

# backend/routers/__init__.py がインポートされないようにダミーを一時的に差し込む
# これにより、soul_router や mcp/pydantic.root_model エラーを回避する
routers_dir = Path(__file__).parent.parent / "backend" / "routers"
mock_routers = types.ModuleType("backend.routers")
mock_routers.__path__ = [str(routers_dir)]

original_backend_routers = sys.modules.get("backend.routers")
sys.modules["backend.routers"] = mock_routers

# youtube_upload routerモジュールをインポート
import backend.routers.youtube_upload as youtube_upload_mod

# インポート完了後に元に戻して sys.modules の汚染を防ぐ
if original_backend_routers is not None:
    sys.modules["backend.routers"] = original_backend_routers
else:
    del sys.modules["backend.routers"]

# テスト用FastAPIアプリの設定
app = FastAPI()
app.include_router(youtube_upload_mod.router)
client = TestClient(app)

# youtube_uploader のモックを取得しやすくするためのヘルパー
@pytest.fixture
def mock_uploader():
    with patch("services.youtube_uploader.youtube_uploader") as mock:
        yield mock


# --- /auth テスト ---

def test_start_auth_success(mock_uploader):
    # 設定済み & 認証URL取得成功
    mock_uploader.get_status.return_value = {"is_configured": True, "is_authenticated": False}
    mock_uploader.get_auth_url.return_value = "https://accounts.google.com/o/oauth2/auth?client_id=xxx"

    response = client.get("/api/youtube-upload/auth?redirect_url=http://localhost/redirect")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["auth_url"] == "https://accounts.google.com/o/oauth2/auth?client_id=xxx"
    mock_uploader.get_auth_url.assert_called_once_with(state="http://localhost/redirect")


def test_start_auth_not_configured(mock_uploader):
    # API未設定の場合
    mock_uploader.get_status.return_value = {"is_configured": False, "is_authenticated": False}

    response = client.get("/api/youtube-upload/auth")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["setup_required"] is True
    assert "未設定" in data["message"]


def test_start_auth_http_exception(mock_uploader):
    # HTTPExceptionが発生した場合
    mock_uploader.get_status.side_effect = HTTPException(status_code=400, detail="Custom HTTP Error")

    response = client.get("/api/youtube-upload/auth")
    assert response.status_code == 400
    assert response.json()["detail"] == "Custom HTTP Error"


def test_start_auth_unexpected_exception(mock_uploader):
    # 汎用Exceptionが発生した場合
    mock_uploader.get_status.side_effect = RuntimeError("Unexpected config load error")

    response = client.get("/api/youtube-upload/auth")
    assert response.status_code == 500
    assert "Unexpected config load error" in response.json()["detail"]


# --- /callback テスト ---

def test_auth_callback_error_param():
    # エラーパラメータが渡された場合
    response = client.get("/api/youtube-upload/callback?error=access_denied", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/?error=access_denied"


def test_auth_callback_no_code():
    # codeパラメータがない場合
    response = client.get("/api/youtube-upload/callback", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/?error=no_code"


def test_auth_callback_success(mock_uploader):
    # コールバック処理成功 (stateあり)
    mock_uploader.handle_callback = AsyncMock(return_value=True)

    response = client.get("/api/youtube-upload/callback?code=valid_code&state=http://localhost/my-app", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost/my-app?youtube_auth=success"
    mock_uploader.handle_callback.assert_called_once_with("valid_code")


def test_auth_callback_success_default_state(mock_uploader):
    # コールバック処理成功 (stateなし)
    mock_uploader.handle_callback = AsyncMock(return_value=True)

    response = client.get("/api/youtube-upload/callback?code=valid_code", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/?youtube_auth=success"


def test_auth_callback_failed(mock_uploader):
    # コールバック処理失敗
    mock_uploader.handle_callback = AsyncMock(return_value=False)

    response = client.get("/api/youtube-upload/callback?code=invalid_code", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/?youtube_auth=failed"


def test_auth_callback_http_exception(mock_uploader):
    # コールバック処理でHTTPExceptionが発生した場合
    mock_uploader.handle_callback = AsyncMock(side_effect=HTTPException(status_code=401, detail="Token rejected"))

    response = client.get("/api/youtube-upload/callback?code=err_code")
    assert response.status_code == 401
    assert response.json()["detail"] == "Token rejected"


def test_auth_callback_unexpected_exception(mock_uploader):
    # コールバック処理で汎用Exceptionが発生した場合
    mock_uploader.handle_callback = AsyncMock(side_effect=RuntimeError("OAuth network error"))

    response = client.get("/api/youtube-upload/callback?code=err_code", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/?error=OAuth%20network%20error"


# --- /upload テスト ---

def test_upload_video_unauthenticated(mock_uploader):
    # 未認証状態でアップロード要求
    mock_uploader.is_authenticated.return_value = False

    payload = {
        "video_path": "videos/output.mp4",
        "title": "Test Title",
        "description": "Test Desc"
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["auth_required"] is True
    assert "YouTube認証が必要です" in data["message"]


def test_upload_video_success(mock_uploader, tmp_path):
    # 認証済み & アップロード成功
    mock_uploader.is_authenticated.return_value = True
    
    # ダミーファイル作成
    video_file = tmp_path / "output.mp4"
    video_file.write_bytes(b"dummy")
    thumb_file = tmp_path / "thumb.jpg"
    thumb_file.write_bytes(b"dummy_thumb")

    from services.youtube_uploader import UploadResult
    mock_result = UploadResult(
        success=True,
        video_id="xyz123",
        video_url="https://youtube.com/watch?v=xyz123",
        status="processing",
        message="Upload completed, now processing",
        error=None
    )
    mock_uploader.upload_video = AsyncMock(return_value=mock_result)

    payload = {
        "video_path": str(video_file),
        "title": "Test Title",
        "description": "Test Desc",
        "tags": ["funny", "ai"],
        "category_id": "22",
        "privacy_status": "unlisted",
        "thumbnail_path": str(thumb_file)
    }
    
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["video_id"] == "xyz123"
    assert data["video_url"] == "https://youtube.com/watch?v=xyz123"
    assert data["status"] == "processing"
    assert data["error"] is None

    mock_uploader.upload_video.assert_called_once_with(
        video_path=str(video_file),
        title="Test Title",
        description="Test Desc",
        tags=["funny", "ai"],
        category_id="22",
        privacy_status="unlisted",
        thumbnail_path=str(thumb_file)
    )


def test_upload_video_http_exception(mock_uploader, tmp_path):
    # アップロード中にHTTPExceptionが発生
    mock_uploader.is_authenticated.return_value = True
    mock_uploader.upload_video = AsyncMock(side_effect=HTTPException(status_code=403, detail="Quota exceeded"))

    video_file = tmp_path / "output.mp4"
    video_file.write_bytes(b"dummy")

    payload = {
        "video_path": str(video_file),
        "title": "Test Title",
        "description": "Test Desc"
    }
    
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 403
    assert response.json()["detail"] == "Quota exceeded"


def test_upload_video_unexpected_exception(mock_uploader, tmp_path):
    # アップロード中に一般例外が発生
    mock_uploader.is_authenticated.return_value = True
    mock_uploader.upload_video = AsyncMock(side_effect=RuntimeError("Read timeout"))

    video_file = tmp_path / "output.mp4"
    video_file.write_bytes(b"dummy")

    payload = {
        "video_path": str(video_file),
        "title": "Test Title",
        "description": "Test Desc"
    }
    
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 500
    assert "Read timeout" in response.json()["detail"]


# --- /status テスト ---

def test_get_upload_status_authenticated(mock_uploader):
    # 認証済みステータス
    mock_uploader.get_status.return_value = {
        "is_configured": True,
        "is_authenticated": True,
        "has_refresh_token": True
    }

    response = client.get("/api/youtube-upload/status")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["is_authenticated"] is True
    assert data["message"] == "認証済み"


def test_get_upload_status_unauthenticated(mock_uploader):
    # 未認証ステータス
    mock_uploader.get_status.return_value = {
        "is_configured": True,
        "is_authenticated": False,
        "has_refresh_token": False
    }

    response = client.get("/api/youtube-upload/status")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["is_authenticated"] is False
    assert data["message"] == "未認証（OAuth認証が必要）"


def test_get_upload_status_http_exception(mock_uploader):
    # ステータス取得中にHTTPExceptionが発生
    mock_uploader.get_status.side_effect = HTTPException(status_code=401, detail="Credentials invalid")

    response = client.get("/api/youtube-upload/status")
    assert response.status_code == 401
    assert response.json()["detail"] == "Credentials invalid"


def test_get_upload_status_unexpected_exception(mock_uploader):
    # ステータス取得中に一般例外が発生
    mock_uploader.get_status.side_effect = RuntimeError("Config corruption")

    response = client.get("/api/youtube-upload/status")
    assert response.status_code == 500
    assert "Config corruption" in response.json()["detail"]


# --- /health テスト ---

def test_health_check():
    response = client.get("/api/youtube-upload/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "youtube_upload"}


# --- 堅牢化ガード処理用テスト ---

def test_is_safe_redirect_direct():
    # is_safe_redirect を直接インポートして詳細に検証
    is_safe = youtube_upload_mod.is_safe_redirect
    
    # None or empty (36行目カバー)
    assert is_safe("") is True
    assert is_safe(None) is True
    
    # Safe relative paths (40行目カバー)
    assert is_safe("/home") is True
    assert is_safe("/") is True
    
    # Safe absolute URL (localhost / 127.0.0.1)
    assert is_safe("http://localhost/callback") is True
    assert is_safe("https://127.0.0.1:8000/callback") is True
    
    # Unsafe absolute URL
    assert is_safe("http://evil.com") is False
    assert is_safe("https://google.com") is False
    
    # Unsafe relative URL starting with //
    assert is_safe("//evil.com") is False
    
    # Exceptions (ValueError / TypeError / AttributeError) (44-45行目カバー)
    assert is_safe(12345) is False
    assert is_safe(["http://localhost"]) is False

    # urlparse Exception (48-49行目カバー)
    with patch("backend.routers.youtube_upload.urlparse", side_effect=ValueError("Mocked urlparse error")):
        assert is_safe("http://localhost/callback") is False


def test_start_auth_unsafe_redirect_url(mock_uploader):
    # 不正なドメインのredirect_urlはHTTP 400エラーとなること
    mock_uploader.get_status.return_value = {"is_configured": True, "is_authenticated": False}
    
    response = client.get("/api/youtube-upload/auth?redirect_url=http://evil.com/redirect")
    assert response.status_code == 400
    assert "Unsafe redirect URL" in response.json()["detail"]


def test_auth_callback_unsafe_state(mock_uploader):
    # 不正なstateはデフォルト of /?youtube_auth=success にフォールバックすること
    mock_uploader.handle_callback = AsyncMock(return_value=True)

    response = client.get("/api/youtube-upload/callback?code=valid_code&state=http://evil.com/my-app", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/?youtube_auth=success"


def test_auth_callback_newline_in_error():
    # errorパラメータに改行が含まれている場合、改行が除去されてリダイレクトされること
    response = client.get("/api/youtube-upload/callback?error=access_denied%0d%0aLocation:%20http://evil.com", follow_redirects=False)
    assert response.status_code == 307
    location = response.headers["location"]
    assert "\r" not in location
    assert "\n" not in location
    assert "evil.com" in location or "access_denied" in location


def test_upload_video_import_error():
    # services.youtube_uploader をインポートしたときに ImportError が発生するケースをテスト
    with patch.dict("sys.modules", {"services.youtube_uploader": None}):
        payload = {
            "video_path": "videos/output.mp4",
            "title": "Test Title",
            "description": "Test Desc"
        }
        response = client.post("/api/youtube-upload/upload", json=payload)
        # ローカルインポートで ImportError が発生するため、500 になるはず
        assert response.status_code == 500
        assert "Uploader import failed" in response.json()["detail"]


def test_upload_video_path_resolve_exception(mock_uploader, tmp_path):
    mock_uploader.is_authenticated.return_value = True
    
    # 1. ビデオパスでの例外 (160-161行目カバー)
    with patch("pathlib.Path.resolve", side_effect=OSError("Mocked OS error")):
        payload = {
            "video_path": "invalid_video.mp4",
            "title": "Test Title",
            "description": "Test Desc"
        }
        response = client.post("/api/youtube-upload/upload", json=payload)
        assert response.status_code == 400
        assert "Invalid video path format" in response.json()["detail"]

    # 2. サムネイルパスでの例外 (174-175行目カバー)
    valid_video = tmp_path / "video.mp4"
    valid_video.write_bytes(b"dummy")
    
    from pathlib import Path as RealPath
    original_resolve = RealPath.resolve
    
    call_count = 0
    def resolve_mock(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("Mocked OS error")
        return original_resolve(self, *args, **kwargs)
        
    with patch("pathlib.Path.resolve", new=resolve_mock):
        payload = {
            "video_path": str(valid_video),
            "title": "Test Title",
            "description": "Test Desc",
            "thumbnail_path": "invalid_thumb.jpg"
        }
        response = client.post("/api/youtube-upload/upload", json=payload)
        assert response.status_code == 400
        assert "Invalid thumbnail path format" in response.json()["detail"]


def test_upload_video_invalid_paths(mock_uploader, tmp_path):
    mock_uploader.is_authenticated.return_value = True
    
    # 存在しない動画ファイル
    payload = {
        "video_path": str(tmp_path / "nonexistent.mp4"),
        "title": "Test Title",
        "description": "Test Desc"
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]

    # ディレクトリパスを指定
    payload = {
        "video_path": str(tmp_path),
        "title": "Test Title",
        "description": "Test Desc"
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 400
    assert "is not a file" in response.json()["detail"]

    # 空ファイル
    empty_video = tmp_path / "empty.mp4"
    empty_video.touch()
    payload = {
        "video_path": str(empty_video),
        "title": "Test Title",
        "description": "Test Desc"
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 400
    assert "is empty" in response.json()["detail"]

    # 不正なサムネイルパス（存在しない）
    valid_video = tmp_path / "video.mp4"
    valid_video.write_bytes(b"dummy_data")
    payload = {
        "video_path": str(valid_video),
        "title": "Test Title",
        "description": "Test Desc",
        "thumbnail_path": str(tmp_path / "nonexistent.jpg")
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 400
    assert "Thumbnail file does not exist" in response.json()["detail"]

    # 不正なサムネイルパス（空ファイル）
    empty_thumb = tmp_path / "empty.jpg"
    empty_thumb.touch()
    payload = {
        "video_path": str(valid_video),
        "title": "Test Title",
        "description": "Test Desc",
        "thumbnail_path": str(empty_thumb)
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 400
    assert "Thumbnail file is empty" in response.json()["detail"]

    # 不正なサムネイルパス（ディレクトリ）
    payload = {
        "video_path": str(valid_video),
        "title": "Test Title",
        "description": "Test Desc",
        "thumbnail_path": str(tmp_path)
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 400
    assert "Thumbnail path is not a file" in response.json()["detail"]


def test_upload_video_invalid_params(mock_uploader, tmp_path):
    mock_uploader.is_authenticated.return_value = True
    valid_video = tmp_path / "video.mp4"
    valid_video.write_bytes(b"dummy_data")

    # 空のタイトル
    payload = {
        "video_path": str(valid_video),
        "title": "   ",
        "description": "Test Desc"
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 400
    assert "Title cannot be empty" in response.json()["detail"]

    # 長すぎるタイトル
    payload = {
        "video_path": str(valid_video),
        "title": "a" * 101,
        "description": "Test Desc"
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 400
    assert "Title cannot exceed 100 characters" in response.json()["detail"]

    # 不正なプライバシーステータス
    payload = {
        "video_path": str(valid_video),
        "title": "Test Title",
        "description": "Test Desc",
        "privacy_status": "invalid_status"
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 400
    assert "Invalid privacy status" in response.json()["detail"]


def test_get_upload_status_invalid_data(mock_uploader):
    # status が dict でない場合 (220行目カバー)
    mock_uploader.get_status.return_value = "not_a_dict"
    response = client.get("/api/youtube-upload/status")
    assert response.status_code == 500
    assert "Invalid uploader status response" in response.json()["detail"]
    
    # status に "is_authenticated" キーがない場合
    mock_uploader.get_status.return_value = {"is_configured": True}
    response = client.get("/api/youtube-upload/status")
    assert response.status_code == 500
    assert "Invalid uploader status response" in response.json()["detail"]


# --- 追加のカバレッジ向上テスト ---

def test_start_auth_import_error():
    # start_auth で ImportError が発生するケースをテスト
    with patch.dict("sys.modules", {"services.youtube_uploader": None}):
        response = client.get("/api/youtube-upload/auth")
        assert response.status_code == 500
        assert "YouTube uploader service could not be loaded" in response.json()["detail"]


def test_start_auth_value_error(mock_uploader):
    # start_auth で ValueError が発生するケースをテスト
    mock_uploader.get_status.return_value = {"is_configured": True}
    mock_uploader.get_auth_url.side_effect = ValueError("Invalid auth configs")
    response = client.get("/api/youtube-upload/auth")
    assert response.status_code == 400
    assert "Invalid auth configs" in response.json()["detail"]


def test_auth_callback_import_error():
    # auth_callback で ImportError が発生するケースをテスト
    with patch.dict("sys.modules", {"services.youtube_uploader": None}):
        response = client.get("/api/youtube-upload/callback?code=some_code", follow_redirects=False)
        assert response.status_code == 307
        assert "YouTube%20uploader%20service%20not%20available" in response.headers["location"]


def test_auth_callback_httpx_error(mock_uploader):
    # auth_callback で httpx.HTTPError が発生するケースをテスト
    import httpx
    mock_uploader.handle_callback = AsyncMock(side_effect=httpx.HTTPError("Google auth callback network error"))
    response = client.get("/api/youtube-upload/callback?code=some_code", follow_redirects=False)
    assert response.status_code == 307
    assert "Network%20connection%20to%20Google%20API%20failed" in response.headers["location"]


def test_upload_video_permission_error(mock_uploader):
    # upload_video で Path.exists のPermissionError が発生するケースをテスト
    mock_uploader.is_authenticated.return_value = True
    payload = {
        "video_path": "permission_denied_video.mp4",
        "title": "Test Title",
        "description": "Test Desc"
    }
    with patch("pathlib.Path.exists", side_effect=PermissionError("Mocked Permission Error")):
        response = client.post("/api/youtube-upload/upload", json=payload)
        assert response.status_code == 403
        assert "Permission denied accessing video file" in response.json()["detail"]


def test_upload_video_thumbnail_permission_error(mock_uploader, tmp_path):
    # upload_video で サムネイルに対する PermissionError が発生するケースをテスト
    mock_uploader.is_authenticated.return_value = True
    
    valid_video = tmp_path / "video.mp4"
    valid_video.write_bytes(b"dummy")
    
    payload = {
        "video_path": str(valid_video),
        "title": "Test Title",
        "description": "Test Desc",
        "thumbnail_path": "permission_denied_thumb.jpg"
    }
    
    from pathlib import Path as RealPath
    original_exists = RealPath.exists
    
    def exists_mock(self, *args, **kwargs):
        if "permission_denied_thumb" in str(self):
            raise PermissionError("Mocked Permission Error for thumb")
        return original_exists(self, *args, **kwargs)
        
    with patch("pathlib.Path.exists", new=exists_mock):
        response = client.post("/api/youtube-upload/upload", json=payload)
        assert response.status_code == 403
        assert "Permission denied accessing thumbnail file" in response.json()["detail"]


def test_upload_video_upload_value_error(mock_uploader, tmp_path):
    # upload_video で youtube_uploader.upload_video が ValueError を投げるケースをテスト
    mock_uploader.is_authenticated.return_value = True
    mock_uploader.upload_video = AsyncMock(side_effect=ValueError("Invalid category parameter"))
    
    valid_video = tmp_path / "video.mp4"
    valid_video.write_bytes(b"dummy")
    
    payload = {
        "video_path": str(valid_video),
        "title": "Test Title",
        "description": "Test Desc"
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 400
    assert "Invalid category parameter" in response.json()["detail"]


def test_upload_video_upload_file_error(mock_uploader, tmp_path):
    # upload_video で youtube_uploader.upload_video が FileNotFoundError を投げるケースをテスト
    mock_uploader.is_authenticated.return_value = True
    mock_uploader.upload_video = AsyncMock(side_effect=FileNotFoundError("Disappeared"))
    
    valid_video = tmp_path / "video.mp4"
    valid_video.write_bytes(b"dummy")
    
    payload = {
        "video_path": str(valid_video),
        "title": "Test Title",
        "description": "Test Desc"
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 400
    assert "File access error: Disappeared" in response.json()["detail"]


def test_upload_video_upload_httpx_error(mock_uploader, tmp_path):
    # upload_video で youtube_uploader.upload_video が httpx.HTTPError を投げるケースをテスト
    import httpx
    mock_uploader.is_authenticated.return_value = True
    mock_uploader.upload_video = AsyncMock(side_effect=httpx.HTTPError("YouTube api timeout"))
    
    valid_video = tmp_path / "video.mp4"
    valid_video.write_bytes(b"dummy")
    
    payload = {
        "video_path": str(valid_video),
        "title": "Test Title",
        "description": "Test Desc"
    }
    response = client.post("/api/youtube-upload/upload", json=payload)
    assert response.status_code == 502
    assert "Network error communicating with YouTube" in response.json()["detail"]


def test_get_upload_status_import_error():
    # get_upload_status で ImportError が発生するケースをテスト
    with patch.dict("sys.modules", {"services.youtube_uploader": None}):
        response = client.get("/api/youtube-upload/status")
        assert response.status_code == 500
        assert "YouTube uploader service could not be loaded" in response.json()["detail"]

