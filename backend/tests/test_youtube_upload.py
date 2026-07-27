import sys
from unittest.mock import MagicMock
# Prevent google.genai mcp imports causing ValueError: tuple.index(x): x not in tuple in Python 3.13
sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()
sys.modules['google.genai.errors'] = MagicMock()

import pytest
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import types
from pathlib import Path

# routers/__init__.py がインポートされないようにダミーを一時的に差し込む
# これにより、soul_router や mcp/pydantic.root_model エラーを回避する
routers_dir = Path(__file__).parent.parent / "routers"
mock_routers = types.ModuleType("routers")
mock_routers.__path__ = [str(routers_dir)]

original_routers = sys.modules.get("routers")
sys.modules["routers"] = mock_routers

from routers.youtube_upload import router, UploadVideoRequest

if original_routers is not None:
    sys.modules["routers"] = original_routers
else:
    del sys.modules["routers"]

from services.youtube_uploader import UploadResult

class TestYoutubeUploadRouter:
    """routers/youtube_upload.py のテストカバレッジ 100% 達成用のテストクラス"""

    @pytest.fixture(autouse=True)
    def setup_client(self, tmp_path):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
        
        # ダミーファイルの作成
        self.temp_video = tmp_path / "dummy_video.mp4"
        self.temp_video.write_bytes(b"dummy_video_content_with_some_bytes")
        self.temp_thumb = tmp_path / "dummy_thumb.jpg"
        self.temp_thumb.write_bytes(b"dummy_thumb_content_with_some_bytes")

    def test_yu_01_health(self):
        """ヘルスチェックエンドポイントのテスト"""
        r = self.client.get("/api/youtube-upload/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "service": "youtube_upload"}

    # -------------------------------------------------------------------------
    # /status エンドポイントのテスト
    # -------------------------------------------------------------------------

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_02_status_authenticated(self, mock_get_status):
        """ステータス確認：認証済みの場合"""
        mock_get_status.return_value = {
            "is_configured": True,
            "is_authenticated": True,
            "has_refresh_token": True
        }
        r = self.client.get("/api/youtube-upload/status")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["is_authenticated"] is True
        assert data["message"] == "認証済み"

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_02_status_not_authenticated(self, mock_get_status):
        """ステータス確認：未認証の場合"""
        mock_get_status.return_value = {
            "is_configured": True,
            "is_authenticated": False,
            "has_refresh_token": False
        }
        r = self.client.get("/api/youtube-upload/status")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["is_authenticated"] is False
        assert data["message"] == "未認証（OAuth認証が必要）"

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_02_status_http_exception(self, mock_get_status):
        """ステータス確認：HTTPException が発生した場合"""
        mock_get_status.side_effect = HTTPException(status_code=400, detail="Bad status request")
        r = self.client.get("/api/youtube-upload/status")
        assert r.status_code == 400
        assert r.json()["detail"] == "Bad status request"

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_02_status_general_exception(self, mock_get_status):
        """ステータス確認：一般例外が発生した場合"""
        mock_get_status.side_effect = RuntimeError("Internal status failure")
        r = self.client.get("/api/youtube-upload/status")
        assert r.status_code == 500
        assert r.json()["detail"] == "Internal status failure"

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_02_status_invalid_response(self, mock_get_status):
        """ステータス確認：is_authenticatedキーが含まれない場合のエラー"""
        mock_get_status.return_value = {
            "is_configured": True
        }
        r = self.client.get("/api/youtube-upload/status")
        assert r.status_code == 500
        assert "Invalid uploader status response" in r.json()["detail"]

    # -------------------------------------------------------------------------
    # /auth エンドポイントのテスト
    # -------------------------------------------------------------------------

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_03_auth_not_configured(self, mock_get_status):
        """OAuth開始：未設定の場合"""
        mock_get_status.return_value = {"is_configured": False}
        r = self.client.get("/api/youtube-upload/auth")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False
        assert data["setup_required"] is True
        assert "未設定" in data["message"]

    @patch("services.youtube_uploader.youtube_uploader.get_auth_url")
    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_03_auth_configured(self, mock_get_status, mock_get_auth_url):
        """OAuth開始：設定済みの場合"""
        mock_get_status.return_value = {"is_configured": True}
        mock_get_auth_url.return_value = "https://accounts.google.com/o/oauth2/auth?test=1"
        
        r = self.client.get("/api/youtube-upload/auth?redirect_url=http://localhost/callback")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["auth_url"] == "https://accounts.google.com/o/oauth2/auth?test=1"
        mock_get_auth_url.assert_called_once_with(state="http://localhost/callback")

    def test_yu_03_auth_unsafe_redirect(self):
        """OAuth開始：安全でないリダイレクトURLがブロックされる挙動"""
        r = self.client.get("/api/youtube-upload/auth?redirect_url=http://attacker.com")
        assert r.status_code == 400
        assert "Unsafe redirect URL is not allowed" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_03_auth_http_exception(self, mock_get_status):
        """OAuth開始：HTTPException が発生した場合"""
        mock_get_status.side_effect = HTTPException(status_code=403, detail="Forbidden auth")
        r = self.client.get("/api/youtube-upload/auth")
        assert r.status_code == 403
        assert r.json()["detail"] == "Forbidden auth"

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_03_auth_general_exception(self, mock_get_status):
        """OAuth開始：一般例外が発生した場合"""
        mock_get_status.side_effect = RuntimeError("Auth connection failed")
        r = self.client.get("/api/youtube-upload/auth")
        assert r.status_code == 500
        assert r.json()["detail"] == "Auth connection failed"

    # -------------------------------------------------------------------------
    # /callback エンドポイントのテスト
    # -------------------------------------------------------------------------

    def test_yu_04_callback_error_query(self):
        """OAuthコールバック：クエリパラメータに error が含まれる場合"""
        r = self.client.get("/api/youtube-upload/callback?error=access_denied", follow_redirects=False)
        assert r.status_code == 307  # Redirect
        assert r.headers["location"] == "/?error=access_denied"

    def test_yu_04_callback_no_code(self):
        """OAuthコールバック：code が指定されていない場合"""
        r = self.client.get("/api/youtube-upload/callback", follow_redirects=False)
        assert r.status_code == 307  # Redirect
        assert r.headers["location"] == "/?error=no_code"

    @patch("services.youtube_uploader.youtube_uploader.handle_callback", new_callable=AsyncMock)
    def test_yu_04_callback_success_with_state(self, mock_handle_callback):
        """OAuthコールバック：認証成功（stateあり）"""
        mock_handle_callback.return_value = True
        r = self.client.get("/api/youtube-upload/callback?code=valid_code&state=/dashboard", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/dashboard?youtube_auth=success"
        mock_handle_callback.assert_called_once_with("valid_code")

    @patch("services.youtube_uploader.youtube_uploader.handle_callback", new_callable=AsyncMock)
    def test_yu_04_callback_success_no_state(self, mock_handle_callback):
        """OAuthコールバック：認証成功（stateなし）"""
        mock_handle_callback.return_value = True
        r = self.client.get("/api/youtube-upload/callback?code=valid_code", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/?youtube_auth=success"

    @patch("services.youtube_uploader.youtube_uploader.handle_callback", new_callable=AsyncMock)
    def test_yu_04_callback_failed(self, mock_handle_callback):
        """OAuthコールバック：認証失敗"""
        mock_handle_callback.return_value = False
        r = self.client.get("/api/youtube-upload/callback?code=invalid_code", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/?youtube_auth=failed"

    @patch("services.youtube_uploader.youtube_uploader.handle_callback", new_callable=AsyncMock)
    def test_yu_04_callback_http_exception(self, mock_handle_callback):
        """OAuthコールバック：HTTPException が発生した場合"""
        mock_handle_callback.side_effect = HTTPException(status_code=400, detail="Token validation failed")
        r = self.client.get("/api/youtube-upload/callback?code=error_code")
        assert r.status_code == 400
        assert r.json()["detail"] == "Token validation failed"

    @patch("services.youtube_uploader.youtube_uploader.handle_callback", new_callable=AsyncMock)
    def test_yu_04_callback_general_exception(self, mock_handle_callback):
        """OAuthコールバック：一般例外が発生した場合（リダイレクトにフォールバック）"""
        mock_handle_callback.side_effect = RuntimeError("Network timeout")
        r = self.client.get("/api/youtube-upload/callback?code=error_code", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/?error=Network%20timeout"

    @patch("services.youtube_uploader.youtube_uploader.handle_callback", new_callable=AsyncMock)
    def test_yu_04_callback_unsafe_state_fallback(self, mock_handle_callback):
        """OAuthコールバック：安全でないstateの場合はルートへフォールバック"""
        mock_handle_callback.return_value = True
        r = self.client.get("/api/youtube-upload/callback?code=valid_code&state=http://unsafe.com", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/?youtube_auth=success"

    # -------------------------------------------------------------------------
    # /upload エンドポイントのテスト
    # -------------------------------------------------------------------------

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_not_authenticated(self, mock_is_authenticated):
        """動画アップロード：未認証の場合"""
        mock_is_authenticated.return_value = False
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False
        assert data["auth_required"] is True
        assert "認証が必要です" in data["message"]

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_success(self, mock_is_authenticated, mock_upload_video):
        """動画アップロード：認証済みで成功"""
        mock_is_authenticated.return_value = True
        mock_upload_video.return_value = UploadResult(
            success=True,
            video_id="video123",
            video_url="https://youtube.com/watch?v=video123",
            status="processing",
            message="Processing started",
            error=None
        )
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc",
            "tags": ["tag1", "tag2"],
            "category_id": "22",
            "privacy_status": "private",
            "thumbnail_path": str(self.temp_thumb)
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["video_id"] == "video123"
        assert data["video_url"] == "https://youtube.com/watch?v=video123"
        assert data["status"] == "processing"
        
        mock_upload_video.assert_called_once_with(
            video_path=str(self.temp_video),
            title="My Title",
            description="My Desc",
            tags=["tag1", "tag2"],
            category_id="22",
            privacy_status="private",
            thumbnail_path=str(self.temp_thumb)
        )

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_http_exception(self, mock_is_authenticated, mock_upload_video):
        """動画アップロード：HTTPException が発生した場合"""
        mock_is_authenticated.return_value = True
        mock_upload_video.side_effect = HTTPException(status_code=400, detail="Invalid video format")
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert r.json()["detail"] == "Invalid video format"

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_general_exception(self, mock_is_authenticated, mock_upload_video):
        """動画アップロード：一般例外が発生した場合"""
        mock_is_authenticated.return_value = True
        mock_upload_video.side_effect = RuntimeError("Upload backend crash")
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 500
        assert r.json()["detail"] == "Upload backend crash"

    @patch("services.youtube_uploader.youtube_uploader.get_auth_url")
    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_03_auth_url_general_exception(self, mock_get_status, mock_get_auth_url):
        """OAuth開始：get_auth_url で一般例外が発生した場合"""
        mock_get_status.return_value = {"is_configured": True}
        mock_get_auth_url.side_effect = RuntimeError("Failed to generate auth URL")
        r = self.client.get("/api/youtube-upload/auth")
        assert r.status_code == 500
        assert r.json()["detail"] == "Failed to generate auth URL"

    def test_yu_04_callback_empty_code_and_state(self):
        """OAuthコールバック：code が空だが state が指定されている場合の挙動"""
        r = self.client.get("/api/youtube-upload/callback?state=/my_dashboard", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/?error=no_code"

    def test_yu_04_callback_with_error_and_state(self):
        """OAuthコールバック：error と state が同時に指定されている場合の挙動"""
        r = self.client.get("/api/youtube-upload/callback?error=invalid_scope&state=/settings", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/?error=invalid_scope"

    def test_yu_05_upload_validation_error(self):
        """動画アップロード：必須パラメータ（video_path）が欠損しているバリデーションエラー"""
        req_data = {
            "title": "Missing Video Path",
            "description": "Validation test"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 422
        # Pydanticのバリデーションエラー構造が含まれているか
        errors = r.json()["detail"]
        assert any(e["loc"] == ["body", "video_path"] for e in errors)

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_empty_tags_and_default_category(self, mock_is_authenticated, mock_upload_video):
        """動画アップロード：tagsが空、およびcategory_id、privacy_status、thumbnail_pathが省略された時のデフォルト値検証"""
        mock_is_authenticated.return_value = True
        mock_upload_video.return_value = UploadResult(
            success=True,
            video_id="video789",
            video_url="https://youtube.com/watch?v=video789",
            status="uploaded",
            message="Uploaded successfully",
            error=None
        )
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["video_id"] == "video789"
        
        # サービス側がデフォルト引数で呼び出されることを確認
        mock_upload_video.assert_called_once_with(
            video_path=str(self.temp_video),
            title="My Title",
            description="My Desc",
            tags=[],
            category_id="22",
            privacy_status="private",
            thumbnail_path=None
        )

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_result_with_error(self, mock_is_authenticated, mock_upload_video):
        """動画アップロード：アップロード自体は処理されたが結果がエラー（success=False）の場合"""
        mock_is_authenticated.return_value = True
        mock_upload_video.return_value = UploadResult(
            success=False,
            video_id=None,
            video_url=None,
            status="failed",
            message="Upload failed due to API quota limit",
            error="quotaExceeded"
        )
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False
        assert data["video_id"] is None
        assert data["status"] == "failed"
        assert data["message"] == "Upload failed due to API quota limit"
        assert data["error"] == "quotaExceeded"

    # =========================================================================
    # カバレッジ向上用の新規追加テストケース
    # =========================================================================

    def test_is_safe_redirect_edge_cases(self):
        """is_safe_redirect関数のエッジケーステスト"""
        from routers.youtube_upload import is_safe_redirect
        assert is_safe_redirect(None) is True
        assert is_safe_redirect(123) is False
        assert is_safe_redirect("") is True
        # 不正なホスト名パース時の例外ハンドリングを確認 (ValueError/TypeError)
        assert is_safe_redirect("http://[::1]abc") is False

    def test_yu_05_upload_import_error(self):
        """動画アップロード：ImportError が発生した場合"""
        # youtube_uploader モジュールインポート時に例外を投げるようにする
        with patch.dict("sys.modules", {"services.youtube_uploader": None}):
            req_data = {
                "video_path": str(self.temp_video),
                "title": "My Title",
                "description": "My Desc"
            }
            r = self.client.post("/api/youtube-upload/upload", json=req_data)
            assert r.status_code == 500
            assert "Uploader import failed" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_title_empty_or_spaces(self, mock_is_authenticated):
        """動画アップロード：タイトルが空または空白のみの場合"""
        mock_is_authenticated.return_value = True
        req_data = {
            "video_path": str(self.temp_video),
            "title": "   ",
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "Title cannot be empty" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_title_too_long(self, mock_is_authenticated):
        """動画アップロード：タイトルが100文字を超える場合"""
        mock_is_authenticated.return_value = True
        req_data = {
            "video_path": str(self.temp_video),
            "title": "A" * 101,
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "Title cannot exceed 100 characters" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_invalid_privacy_status(self, mock_is_authenticated):
        """動画アップロード：無効な公開設定の場合"""
        mock_is_authenticated.return_value = True
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc",
            "privacy_status": "unsupported_privacy"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "Invalid privacy status" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_invalid_video_path_format(self, mock_is_authenticated):
        """動画アップロード：動画パスの形式が無効な場合（例外発生）"""
        mock_is_authenticated.return_value = True
        req_data = {
            "video_path": "invalid_video_path",
            "title": "My Title",
            "description": "My Desc"
        }
        with patch("pathlib.Path.resolve", side_effect=OSError("Mocked OS error")):
            r = self.client.post("/api/youtube-upload/upload", json=req_data)
            assert r.status_code == 400
            assert "Invalid video path format" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_video_not_exist(self, mock_is_authenticated):
        """動画アップロード：動画ファイルが存在しない場合"""
        mock_is_authenticated.return_value = True
        req_data = {
            "video_path": "non_existent_video.mp4",
            "title": "My Title",
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "Video file does not exist" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_video_is_dir(self, mock_is_authenticated, tmp_path):
        """動画アップロード：動画パスがディレクトリの場合"""
        mock_is_authenticated.return_value = True
        req_data = {
            "video_path": str(tmp_path),
            "title": "My Title",
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "Video path is not a file" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_video_empty(self, mock_is_authenticated, tmp_path):
        """動画アップロード：動画ファイルが空（サイズ0）の場合"""
        mock_is_authenticated.return_value = True
        empty_video = tmp_path / "empty_video.mp4"
        empty_video.write_bytes(b"")
        req_data = {
            "video_path": str(empty_video),
            "title": "My Title",
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "Video file is empty" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_invalid_thumbnail_path_format(self, mock_is_authenticated):
        """動画アップロード：サムネイルパスの形式が無効な場合（例外発生）"""
        mock_is_authenticated.return_value = True
        import pathlib
        original_resolve = pathlib.Path.resolve
        call_count = 0

        def mock_resolve(self_path, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # 1回目はvideo_pathのresolve、2回目はthumbnail_pathのresolve
                raise OSError("Mocked OS error")
            return original_resolve(self_path, *args, **kwargs)

        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc",
            "thumbnail_path": "invalid_thumb"
        }
        with patch("pathlib.Path.resolve", mock_resolve):
            r = self.client.post("/api/youtube-upload/upload", json=req_data)
            assert r.status_code == 400
            assert "Invalid thumbnail path format" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_thumbnail_not_exist(self, mock_is_authenticated):
        """動画アップロード：サムネイルファイルが存在しない場合"""
        mock_is_authenticated.return_value = True
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc",
            "thumbnail_path": "non_existent_thumb.jpg"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "Thumbnail file does not exist" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_thumbnail_is_dir(self, mock_is_authenticated, tmp_path):
        """動画アップロード：サムネイルパスがディレクトリの場合"""
        mock_is_authenticated.return_value = True
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc",
            "thumbnail_path": str(tmp_path)
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "Thumbnail path is not a file" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_thumbnail_empty(self, mock_is_authenticated, tmp_path):
        """動画アップロード：サムネイルファイルが空（サイズ0）の場合"""
        mock_is_authenticated.return_value = True
        empty_thumb = tmp_path / "empty_thumb.jpg"
        empty_thumb.write_bytes(b"")
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc",
            "thumbnail_path": str(empty_thumb)
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "Thumbnail file is empty" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_03_auth_import_error(self, mock_get_status):
        """OAuth開始：ImportError が発生した場合"""
        with patch.dict("sys.modules", {"services.youtube_uploader": None}):
            r = self.client.get("/api/youtube-upload/auth")
            assert r.status_code == 500
            assert "YouTube uploader service could not be loaded" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_03_auth_value_error(self, mock_get_status):
        """OAuth開始：ValueError が発生した場合"""
        mock_get_status.side_effect = ValueError("Invalid auth configurations")
        r = self.client.get("/api/youtube-upload/auth")
        assert r.status_code == 400
        assert "Invalid auth configurations" in r.json()["detail"]

    def test_yu_04_callback_import_error(self):
        """OAuthコールバック：ImportError が発生した場合"""
        with patch.dict("sys.modules", {"services.youtube_uploader": None}):
            r = self.client.get("/api/youtube-upload/callback?code=some_code", follow_redirects=False)
            assert r.status_code == 307
            assert "YouTube%20uploader%20service%20not%20available" in r.headers["location"]

    @patch("services.youtube_uploader.youtube_uploader.handle_callback", new_callable=AsyncMock)
    def test_yu_04_callback_httpx_error(self, mock_handle_callback):
        """OAuthコールバック：httpx.HTTPError が発生した場合"""
        import httpx
        mock_handle_callback.side_effect = httpx.HTTPError("Google network timeout")
        r = self.client.get("/api/youtube-upload/callback?code=some_code", follow_redirects=False)
        assert r.status_code == 307
        assert "Network%20connection%20to%20Google%20API%20failed" in r.headers["location"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_video_permission_error(self, mock_is_authenticated):
        """動画アップロード：動画ファイルアクセスで PermissionError が発生した場合"""
        mock_is_authenticated.return_value = True
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc"
        }
        with patch("pathlib.Path.exists", side_effect=PermissionError("Permission denied on video")):
            r = self.client.post("/api/youtube-upload/upload", json=req_data)
            assert r.status_code == 403
            assert "Permission denied accessing video file" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_thumbnail_permission_error(self, mock_is_authenticated):
        """動画アップロード：サムネイルファイルアクセスで PermissionError が発生した場合"""
        mock_is_authenticated.return_value = True
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc",
            "thumbnail_path": str(self.temp_thumb)
        }
        import pathlib
        def mock_exists(self_path, *args, **kwargs):
            if "dummy_thumb" in str(self_path):
                raise PermissionError("Permission denied on thumb")
            return True

        with patch("pathlib.Path.exists", mock_exists):
            r = self.client.post("/api/youtube-upload/upload", json=req_data)
            assert r.status_code == 403
            assert "Permission denied accessing thumbnail file" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_value_error(self, mock_is_authenticated, mock_upload_video):
        """動画アップロード：アップロード中に ValueError が発生した場合"""
        mock_is_authenticated.return_value = True
        mock_upload_video.side_effect = ValueError("Invalid category parameter")
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "Invalid category parameter" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_file_not_found_error(self, mock_is_authenticated, mock_upload_video):
        """動画アップロード：アップロード中に FileNotFoundError が発生した場合"""
        mock_is_authenticated.return_value = True
        mock_upload_video.side_effect = FileNotFoundError("Video file disappeared")
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "File access error" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_httpx_error(self, mock_is_authenticated, mock_upload_video):
        """動画アップロード：アップロード中に httpx.HTTPError が発生した場合"""
        import httpx
        mock_is_authenticated.return_value = True
        mock_upload_video.side_effect = httpx.HTTPError("YouTube upload API timeout")
        req_data = {
            "video_path": str(self.temp_video),
            "title": "My Title",
            "description": "My Desc"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 502
        assert "Network error communicating with YouTube" in r.json()["detail"]

    def test_yu_02_status_import_error(self):
        """ステータス確認：ImportError が発生した場合"""
        with patch.dict("sys.modules", {"services.youtube_uploader": None}):
            r = self.client.get("/api/youtube-upload/status")
            assert r.status_code == 500
            assert "YouTube uploader service could not be loaded" in r.json()["detail"]

    def test_yu_06_model_config_dict(self):
        """UploadVideoRequest の model_config が正しく設定されていることを確認"""
        from routers.youtube_upload import UploadVideoRequest
        assert hasattr(UploadVideoRequest, "model_config")
        # ConfigDictはdictのサブクラスまたはdictそのものであるため、dictとして評価
        assert isinstance(UploadVideoRequest.model_config, dict)




    # -------------------------------------------------------------------------
    # 具体的な例外型 (TypeError, KeyError, AttributeError, OSError) の捕捉テスト
    # -------------------------------------------------------------------------

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_07_status_specific_exceptions(self, mock_get_status):
        """ステータス確認：具体的な例外（TypeError, KeyError, AttributeError, OSError）が発生した場合"""
        for exc in [TypeError("status type error"), KeyError("status key error"), AttributeError("status attr error"), OSError("status os error")]:
            mock_get_status.side_effect = exc
            r = self.client.get("/api/youtube-upload/status")
            assert r.status_code == 500
            # KeyErrorは文字列表現がクォートされるなどの差分があるため detail キーの存在チェックで代用
            assert "detail" in r.json()

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_07_auth_specific_exceptions(self, mock_get_status):
        """OAuth開始：具体的な例外（TypeError, KeyError, AttributeError, OSError）が発生した場合"""
        for exc in [TypeError("auth type error"), KeyError("auth key error"), AttributeError("auth attr error"), OSError("auth os error")]:
            mock_get_status.side_effect = exc
            r = self.client.get("/api/youtube-upload/auth")
            assert r.status_code == 500
            assert "detail" in r.json()

    @patch("services.youtube_uploader.youtube_uploader.handle_callback", new_callable=AsyncMock)
    def test_yu_07_callback_specific_exceptions(self, mock_handle_callback):
        """OAuthコールバック：具体的な例外（TypeError, ValueError, KeyError, AttributeError, OSError）が発生した場合"""
        for exc in [TypeError("callback type error"), ValueError("callback val error"), KeyError("callback key error"), AttributeError("callback attr error"), OSError("callback os error")]:
            mock_handle_callback.side_effect = exc
            r = self.client.get("/api/youtube-upload/callback?code=error_code", follow_redirects=False)
            assert r.status_code == 307
            assert "/?error=" in r.headers["location"]

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_07_upload_specific_exceptions(self, mock_is_authenticated, mock_upload_video):
        """動画アップロード：具体的な例外（TypeError, KeyError, AttributeError, OSError）が発生した場合"""
        mock_is_authenticated.return_value = True
        for exc in [TypeError("upload type error"), KeyError("upload key error"), AttributeError("upload attr error"), OSError("upload os error")]:
            mock_upload_video.side_effect = exc
            req_data = {
                "video_path": str(self.temp_video),
                "title": "My Title",
                "description": "My Desc"
            }
            r = self.client.post("/api/youtube-upload/upload", json=req_data)
            assert r.status_code == 500
            assert "detail" in r.json()

    @patch("services.youtube_uploader.youtube_uploader.handle_callback", new_callable=AsyncMock)
    def test_yu_04_callback_success_with_state_query_param(self, mock_handle_callback):
        """OAuthコールバック：認証成功（クエリパラメータ付きstate）"""
        mock_handle_callback.return_value = True
        r = self.client.get("/api/youtube-upload/callback?code=valid_code&state=/dashboard?tab=youtube", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/dashboard?tab=youtube&youtube_auth=success"

    # =========================================================================
    # 境界値・極端な値（None, 空値など）のテストケース
    # =========================================================================

    def test_is_safe_redirect_more_edge_cases(self):
        """is_safe_redirect のさらなる境界値テスト（脆弱性偽装URLなど）"""
        from routers.youtube_upload import is_safe_redirect
        # スラッシュ2つで始まる危険なURL（オープンリダイレクトに繋がる可能性のあるもの）
        assert is_safe_redirect("//attacker.com") is False
        assert is_safe_redirect("///attacker.com") is False
        assert is_safe_redirect("javascript:alert(1)") is False
        assert is_safe_redirect("http:localhost") is False
        assert is_safe_redirect("/relative/path?next=http://attacker.com") is True
        assert is_safe_redirect("/relative//path") is True

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_val_errors_none_and_empty(self, mock_is_authenticated):
        """動画アップロード：Noneや空値などの極端な値に対するバリデーションテスト"""
        mock_is_authenticated.return_value = True

        # 1. 必須パラメータ video_path が None
        req_data = {
            "video_path": None,
            "title": "Valid Title",
            "description": "Valid Description"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 422 # Pydantic ValidationError

        # 2. 必須パラメータ title が None
        req_data = {
            "video_path": str(self.temp_video),
            "title": None,
            "description": "Valid Description"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 422 # Pydantic ValidationError

        # 3. オプションパラメータ privacy_status が None
        req_data = {
            "video_path": str(self.temp_video),
            "title": "Valid Title",
            "description": "Valid Description",
            "privacy_status": None
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 422

        # 4. オプションパラメータ category_id が None
        req_data = {
            "video_path": str(self.temp_video),
            "title": "Valid Title",
            "description": "Valid Description",
            "category_id": None
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 422

        # 5. tags が None
        req_data = {
            "video_path": str(self.temp_video),
            "title": "Valid Title",
            "description": "Valid Description",
            "tags": None
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 422

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_empty_thumbnail_path_handling(self, mock_is_authenticated, mock_upload_video):
        """動画アップロード：thumbnail_pathが空文字列やNoneの場合、ファイル検証がバイパスされて正常に動作することを確認"""
        mock_is_authenticated.return_value = True
        mock_upload_video.return_value = UploadResult(
            success=True,
            video_id="video_id_thumbnail_none",
            video_url="https://youtube.com/watch?v=video_id_thumbnail_none",
            status="uploaded",
            message="Uploaded with no thumbnail",
            error=None
        )

        # thumbnail_path = "" (空文字列)
        req_data = {
            "video_path": str(self.temp_video),
            "title": "Valid Title",
            "description": "Valid Description",
            "thumbnail_path": ""
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 200
        assert r.json()["success"] is True

        # thumbnail_path = None
        req_data = {
            "video_path": str(self.temp_video),
            "title": "Valid Title",
            "description": "Valid Description",
            "thumbnail_path": None
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 200
        assert r.json()["success"] is True

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_title_exact_boundary(self, mock_is_authenticated, mock_upload_video):
        """動画アップロード：タイトルの文字数が境界値（ちょうど100文字）の場合に正常にアップロードできることの検証"""
        mock_is_authenticated.return_value = True
        mock_upload_video.return_value = UploadResult(
            success=True,
            video_id="video_boundary",
            video_url="https://youtube.com/watch?v=video_boundary",
            status="uploaded",
            message="Uploaded boundary",
            error=None
        )

        # タイトルがちょうど100文字
        border_title = "A" * 100
        req_data = {
            "video_path": str(self.temp_video),
            "title": border_title,
            "description": "Valid Description"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 200
        assert r.json()["success"] is True

    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_05_upload_privacy_status_empty(self, mock_is_authenticated):
        """動画アップロード：privacy_status が空文字列の場合、400 Bad Request となることの検証"""
        mock_is_authenticated.return_value = True
        req_data = {
            "video_path": str(self.temp_video),
            "title": "Valid Title",
            "description": "Valid Description",
            "privacy_status": ""
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "Invalid privacy status" in r.json()["detail"]

class TestYouTubeUploaderService:
    """services/youtube_uploader.py のテストカバレッジ向上用テストクラス"""

    @pytest.fixture
    def temp_credentials_file(self, tmp_path):
        creds_file = tmp_path / "temp_youtube_credentials.json"
        return str(creds_file)

    def test_service_init_no_file(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService
        service = YouTubeUploaderService(temp_credentials_file)
        assert service._credentials is None

    def test_service_init_valid_file(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService
        import json
        
        creds_data = {
            "client_id": "dummy_client_id",
            "client_secret": "dummy_client_secret",
            "access_token": "dummy_access_token",
            "refresh_token": "dummy_refresh_token",
            "expires_at": 1700000000.0
        }
        with open(temp_credentials_file, "w") as f:
            json.dump(creds_data, f)
            
        service = YouTubeUploaderService(temp_credentials_file)
        assert service._credentials is not None
        assert service._credentials.client_id == "dummy_client_id"
        assert service._credentials.access_token == "dummy_access_token"

    def test_service_init_invalid_json(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService
        with open(temp_credentials_file, "w") as f:
            f.write("invalid json contents")
            
        service = YouTubeUploaderService(temp_credentials_file)
        assert service._credentials is None

    def test_service_save_credentials(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials
        import json
        import os
        
        service = YouTubeUploaderService(temp_credentials_file)
        service._credentials = YouTubeCredentials(
            client_id="id123",
            client_secret="secret123",
            access_token="tok123",
            refresh_token="ref123",
            expires_at=2000000000.0
        )
        service._save_credentials()
        
        assert os.path.exists(temp_credentials_file)
        with open(temp_credentials_file, "r") as f:
            data = json.load(f)
            assert data["client_id"] == "id123"
            assert data["access_token"] == "tok123"

    def test_service_get_auth_url(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials
        service = YouTubeUploaderService(temp_credentials_file)
        
        assert service.get_auth_url() == ""
        
        service._credentials = YouTubeCredentials(client_id="my_client_id", client_secret="my_secret")
        url = service.get_auth_url("my_state")
        assert "my_client_id" in url
        assert "my_state" in url
        assert "prompt=consent" in url

    @pytest.mark.asyncio
    async def test_service_handle_callback_no_creds(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService
        service = YouTubeUploaderService(temp_credentials_file)
        res = await service.handle_callback("my_code")
        assert res is False

    @pytest.mark.asyncio
    async def test_service_handle_callback_success(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials
        service = YouTubeUploaderService(temp_credentials_file)
        service._credentials = YouTubeCredentials(client_id="my_client_id", client_secret="my_secret")
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600
        }
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            res = await service.handle_callback("my_code")
            assert res is True
            assert service._credentials.access_token == "new_access_token"
            assert service._credentials.refresh_token == "new_refresh_token"

    @pytest.mark.asyncio
    async def test_service_handle_callback_http_error(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials
        service = YouTubeUploaderService(temp_credentials_file)
        service._credentials = YouTubeCredentials(client_id="my_client_id", client_secret="my_secret")
        
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request error"
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            res = await service.handle_callback("my_code")
            assert res is False

    @pytest.mark.asyncio
    async def test_service_handle_callback_exception(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials
        service = YouTubeUploaderService(temp_credentials_file)
        service._credentials = YouTubeCredentials(client_id="my_client_id", client_secret="my_secret")
        
        with patch("httpx.AsyncClient.post", side_effect=Exception("Connection broken")):
            res = await service.handle_callback("my_code")
            assert res is False

    @pytest.mark.asyncio
    async def test_service_handle_callback_httpx_http_error(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials
        import httpx
        service = YouTubeUploaderService(temp_credentials_file)
        service._credentials = YouTubeCredentials(client_id="my_client_id", client_secret="my_secret")
        
        with patch("httpx.AsyncClient.post", side_effect=httpx.HTTPError("Mock HTTP error")):
            res = await service.handle_callback("my_code")
            assert res is False

    @pytest.mark.asyncio
    async def test_service_handle_callback_json_decode_error(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials
        import json
        service = YouTubeUploaderService(temp_credentials_file)
        service._credentials = YouTubeCredentials(client_id="my_client_id", client_secret="my_secret")
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            res = await service.handle_callback("my_code")
            assert res is False

    @pytest.mark.asyncio
    async def test_service_upload_video_errors(self, temp_credentials_file, tmp_path):
        from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials
        service = YouTubeUploaderService(temp_credentials_file)
        
        res = await service.upload_video("dummy.mp4", "Title", "Desc", [])
        assert res.success is False
        assert res.error == "not_authenticated"
        
        service._credentials = YouTubeCredentials(client_id="id", client_secret="secret", access_token="token")
        
        res = await service.upload_video("nonexistent_video.mp4", "Title", "Desc", [])
        assert res.success is False
        assert res.error == "file_not_found"
        
        dummy_video = tmp_path / "dummy_video.mp4"
        dummy_video.write_bytes(b"dummy data")
        
        res = await service.upload_video(str(dummy_video), "Title", "Desc", ["tag"])
        assert res.success is True
        assert res.video_id == "placeholder_video_id"
        
        # Exception path
        with patch("services.youtube_uploader.logger.info", side_effect=Exception("Logger failed")):
            res = await service.upload_video(str(dummy_video), "Title", "Desc", ["tag"])
            assert res.success is False
            assert res.error == "upload_error"

    @pytest.mark.asyncio
    async def test_service_upload_video_httpx_http_error(self, temp_credentials_file, tmp_path):
        from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials
        import httpx
        service = YouTubeUploaderService(temp_credentials_file)
        service._credentials = YouTubeCredentials(client_id="id", client_secret="secret", access_token="token")
        
        dummy_video = tmp_path / "dummy_video_for_http_error.mp4"
        dummy_video.write_bytes(b"dummy data")
        
        with patch("services.youtube_uploader.logger.info", side_effect=httpx.HTTPError("Mock httpx upload error")):
            res = await service.upload_video(str(dummy_video), "Title", "Desc", ["tag"])
            assert res.success is False
            assert res.error == "upload_http_error"

    def test_service_is_authenticated(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials
        import time
        service = YouTubeUploaderService(temp_credentials_file)
        
        assert service.is_authenticated() is False
        
        service._credentials = YouTubeCredentials(client_id="id", client_secret="secret")
        assert service.is_authenticated() is False
        
        service._credentials.access_token = "token"
        service._credentials.expires_at = time.time() + 1000
        assert service.is_authenticated() is True
        
        service._credentials.expires_at = time.time() - 10
        assert service.is_authenticated() is False

    def test_service_get_status(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials
        service = YouTubeUploaderService(temp_credentials_file)
        
        status = service.get_status()
        assert status["is_configured"] is False
        assert status["is_authenticated"] is False
        
        service._credentials = YouTubeCredentials(client_id="id", client_secret="secret", access_token="token", refresh_token="refresh")
        service._credentials.expires_at = __import__('time').time() + 1000
        status = service.get_status()
        assert status["is_configured"] is True
        assert status["is_authenticated"] is True
        assert status["has_refresh_token"] is True

    @pytest.mark.asyncio
    async def test_service_handle_callback_runtime_error(self, temp_credentials_file):
        from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials
        service = YouTubeUploaderService(temp_credentials_file)
        service._credentials = YouTubeCredentials(client_id="my_client_id", client_secret="my_secret")
        
        with patch("httpx.AsyncClient.post", side_effect=RuntimeError("Runtime fatal error")):
            res = await service.handle_callback("my_code")
            assert res is False


class TestYouTubeUploadErrorHandlerAndRouterTranslation:
    """YouTubeUploadErrorHandlerと各ルーターエンドポイントでの例外翻訳のテスト"""

    @pytest.fixture(autouse=True)
    def setup_client(self, tmp_path):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
        
        self.temp_video = tmp_path / "dummy_video.mp4"
        self.temp_video.write_bytes(b"dummy_video_content_with_some_bytes")

    def test_yu_08_error_handler_various_exceptions(self):
        """YouTubeUploadErrorHandlerの各種例外に対する挙動テスト"""
        from routers.youtube_upload import YouTubeUploadErrorHandler
        import httpx

        # 1. ValueError
        r1 = YouTubeUploadErrorHandler.handle_auth_error(ValueError("Invalid parameters"))
        assert r1["status_code"] == 400
        assert "Invalid parameters" in r1["detail"]

        r2 = YouTubeUploadErrorHandler.handle_upload_error(ValueError("Invalid size"))
        assert r2["status_code"] == 400
        assert "Invalid size" in r2["detail"]

        # 2. FileNotFoundError / PermissionError
        r3 = YouTubeUploadErrorHandler.handle_upload_error(FileNotFoundError("file lost"))
        assert r3["status_code"] == 400
        assert "File access error" in r3["detail"]

        r4 = YouTubeUploadErrorHandler.handle_upload_error(PermissionError("denied"))
        assert r4["status_code"] == 400
        assert "File access error" in r4["detail"]

        # 3. httpx.HTTPError
        r5 = YouTubeUploadErrorHandler.handle_upload_error(httpx.HTTPError("API quota error"))
        assert r5["status_code"] == 502
        assert "Network error communicating with YouTube" in r5["detail"]

        r6 = YouTubeUploadErrorHandler.handle_callback_error(httpx.HTTPError("Google auth failed"))
        assert r6 == "Network connection to Google API failed"

        # 4. General exception
        r7 = YouTubeUploadErrorHandler.handle_auth_error(RuntimeError("Unexpected auth error"))
        assert r7["status_code"] == 500

        r8 = YouTubeUploadErrorHandler.handle_status_error(RuntimeError("Unexpected status error"))
        assert r8["status_code"] == 500

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_09_router_status_general_exception(self, mock_get_status):
        """get_upload_status で一般例外が発生した場合に 500 にトランスレートされることの検証"""
        mock_get_status.side_effect = RuntimeError("Fatal status error")
        r = self.client.get("/api/youtube-upload/status")
        assert r.status_code == 500
        assert "Fatal status error" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_09_router_auth_value_error(self, mock_get_status):
        """start_auth で ValueError が発生した場合に 400 にトランスレートされることの検証"""
        mock_get_status.side_effect = ValueError("Invalid auth request")
        r = self.client.get("/api/youtube-upload/auth")
        assert r.status_code == 400
        assert "Invalid auth request" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_09_router_upload_file_not_found(self, mock_is_authenticated, mock_upload_video):
        """upload_video で FileNotFoundError が発生した場合に 400 にトランスレートされることの検証"""
        mock_is_authenticated.return_value = True
        mock_upload_video.side_effect = FileNotFoundError("Missing target video")
        req_data = {
            "video_path": str(self.temp_video),
            "title": "Valid Title",
            "description": "Valid Description"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 400
        assert "File access error" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_09_router_upload_httpx_error(self, mock_is_authenticated, mock_upload_video):
        """upload_video で httpx.HTTPError が発生した場合に 502 にトランスレートされることの検証"""
        import httpx
        mock_is_authenticated.return_value = True
        mock_upload_video.side_effect = httpx.HTTPError("Upload timeout")
        req_data = {
            "video_path": str(self.temp_video),
            "title": "Valid Title",
            "description": "Valid Description"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 502
        assert "Network error communicating with YouTube" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.handle_callback", new_callable=AsyncMock)
    def test_yu_09_router_callback_httpx_error(self, mock_handle_callback):
        """auth_callback で httpx.HTTPError が発生した場合に正しくリダイレクトされることの検証"""
        import httpx
        mock_handle_callback.side_effect = httpx.HTTPError("Auth network error")
        r = self.client.get("/api/youtube-upload/callback?code=some_code", follow_redirects=False)
        assert r.status_code == 307
        assert "Network%20connection%20to%20Google%20API%20failed" in r.headers["location"]

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_10_router_status_os_error_translation(self, mock_get_status):
        """get_upload_status で OSError が発生した場合に 500 にトランスレートされることの検証"""
        mock_get_status.side_effect = OSError("Status OS error")
        r = self.client.get("/api/youtube-upload/status")
        assert r.status_code == 500
        assert "Status OS error" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_10_router_auth_os_error_translation(self, mock_get_status):
        """start_auth で OSError が発生した場合に 500 にトランスレートされることの検証"""
        mock_get_status.return_value = {"is_configured": True}
        with patch("services.youtube_uploader.youtube_uploader.get_auth_url", side_effect=OSError("Auth OS error")):
            r = self.client.get("/api/youtube-upload/auth")
            assert r.status_code == 500
            assert "Auth OS error" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_10_router_upload_os_error_translation(self, mock_is_authenticated, mock_upload_video):
        """upload_video で OSError が発生した場合に 500 にトランスレートされることの検証"""
        mock_is_authenticated.return_value = True
        mock_upload_video.side_effect = OSError("Upload OS error")
        req_data = {
            "video_path": str(self.temp_video),
            "title": "Valid Title",
            "description": "Valid Description"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 500
        assert "Upload OS error" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.handle_callback", new_callable=AsyncMock)
    def test_yu_10_router_callback_os_error_translation(self, mock_handle_callback):
        """auth_callback で OSError が発生した場合に正しくリダイレクトされることの検証"""
        mock_handle_callback.side_effect = OSError("Callback OS error")
        r = self.client.get("/api/youtube-upload/callback?code=some_code", follow_redirects=False)
        assert r.status_code == 307
        assert "Callback%20OS%20error" in r.headers["location"]

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_11_router_status_unhandled_exception(self, mock_get_status):
        """get_upload_status で未知の例外 (ZeroDivisionError) が発生した場合に 500 にトランスレートされることの検証"""
        mock_get_status.side_effect = ZeroDivisionError("division by zero status")
        r = self.client.get("/api/youtube-upload/status")
        assert r.status_code == 500
        assert "division by zero status" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_11_router_auth_unhandled_exception(self, mock_get_status):
        """start_auth で未知の例外 (ZeroDivisionError) が発生した場合に 500 にトランスレートされることの検証"""
        mock_get_status.return_value = {"is_configured": True}
        with patch("services.youtube_uploader.youtube_uploader.get_auth_url", side_effect=ZeroDivisionError("division by zero auth")):
            r = self.client.get("/api/youtube-upload/auth")
            assert r.status_code == 500
            assert "division by zero auth" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.upload_video", new_callable=AsyncMock)
    @patch("services.youtube_uploader.youtube_uploader.is_authenticated")
    def test_yu_11_router_upload_unhandled_exception(self, mock_is_authenticated, mock_upload_video):
        """upload_video で未知の例外 (ZeroDivisionError) が発生した場合に 500 にトランスレートされることの検証"""
        mock_is_authenticated.return_value = True
        mock_upload_video.side_effect = ZeroDivisionError("division by zero upload")
        req_data = {
            "video_path": str(self.temp_video),
            "title": "Valid Title",
            "description": "Valid Description"
        }
        r = self.client.post("/api/youtube-upload/upload", json=req_data)
        assert r.status_code == 500
        assert "division by zero upload" in r.json()["detail"]

    @patch("services.youtube_uploader.youtube_uploader.handle_callback", new_callable=AsyncMock)
    def test_yu_11_router_callback_unhandled_exception(self, mock_handle_callback):
        """auth_callback で未知の例外 (ZeroDivisionError) が発生した場合に正しくリダイレクトされることの検証"""
        mock_handle_callback.side_effect = ZeroDivisionError("division by zero callback")
        r = self.client.get("/api/youtube-upload/callback?code=some_code", follow_redirects=False)
        assert r.status_code == 307
        assert "division%20by%20zero%20callback" in r.headers["location"]

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_12_router_specific_exceptions_expanded(self, mock_get_status):
        """新たにキャッチ対象に追加した具体的な例外（LookupError, NameError, ImportError）の検証"""
        for exc in [LookupError("lookup failure"), NameError("name failure"), ImportError("import failure")]:
            mock_get_status.side_effect = exc
            r = self.client.get("/api/youtube-upload/status")
            assert r.status_code == 500
            assert "detail" in r.json()

    @patch("services.youtube_uploader.youtube_uploader.get_status")
    def test_yu_13_router_custom_exception_trapped(self, mock_get_status):
        """任意のカスタム例外が except Exception as e によって適切に一元ハンドラーに捕捉されることを検証"""
        class CustomAppError(Exception):
            pass
        mock_get_status.side_effect = CustomAppError("Custom application error occurred")
        r = self.client.get("/api/youtube-upload/status")
        assert r.status_code == 500
        assert r.json()["detail"] == "Custom application error occurred"



