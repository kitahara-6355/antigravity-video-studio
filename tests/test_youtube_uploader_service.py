import sys
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
import httpx

# カレントディレクトリ(ワークスペースルート)を取得してsys.pathに追加
cwd = Path.cwd()
workspace_root = str(cwd)
workspace_backend = str(cwd / "backend")

if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)
if workspace_backend not in sys.path:
    sys.path.insert(0, workspace_backend)

from services.youtube_uploader import YouTubeUploaderService, YouTubeCredentials, UploadResult

@pytest.fixture
def temp_creds_path(tmp_path):
    """テスト用の一時的な認証情報ファイルのパスを提供するフィクスチャ"""
    return tmp_path / "youtube_credentials.json"


def test_load_credentials_success(temp_creds_path):
    # 正常な認証情報ファイルを準備
    creds_data = {
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "access_token": "test_access_token",
        "refresh_token": "test_refresh_token",
        "expires_at": 123456789.0
    }
    temp_creds_path.write_text(json.dumps(creds_data), encoding="utf-8")
    
    # サービスを初期化してロードさせる
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    
    assert service._credentials is not None
    assert service._credentials.client_id == "test_client_id"
    assert service._credentials.client_secret == "test_client_secret"
    assert service._credentials.access_token == "test_access_token"
    assert service._credentials.refresh_token == "test_refresh_token"
    assert service._credentials.expires_at == 123456789.0


def test_load_credentials_file_not_found(temp_creds_path):
    # ファイルが存在しない状態で初期化
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    assert service._credentials is None


def test_load_credentials_json_decode_error(temp_creds_path):
    # 不正なJSONデータを書き込む
    temp_creds_path.write_text("{invalid_json", encoding="utf-8")
    
    # 警告ログが出力されつつ、正常に初期化（_credentialsはNone）されることを確認
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    assert service._credentials is None


def test_load_credentials_os_error(temp_creds_path):
    # ファイル読み込み時に OSError が発生するよう mock する
    with patch("builtins.open", side_effect=OSError("Mocked permission error")):
        temp_creds_path.write_text("{}", encoding="utf-8")
        service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
        assert service._credentials is None


def test_save_credentials_success(temp_creds_path):
    # サービスを初期化
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    
    # 認証情報を手動設定
    service._credentials = YouTubeCredentials(
        client_id="new_client_id",
        client_secret="new_client_secret",
        access_token="new_access_token",
        refresh_token="new_refresh_token",
        expires_at=987654321.0
    )
    
    # 保存を実行
    service._save_credentials()
    
    # ファイルが作成され、内容が一致することを確認
    assert temp_creds_path.exists()
    with open(temp_creds_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    assert data["client_id"] == "new_client_id"
    assert data["client_secret"] == "new_client_secret"
    assert data["access_token"] == "new_access_token"
    assert data["refresh_token"] == "new_refresh_token"
    assert data["expires_at"] == 987654321.0


def test_get_auth_url_success(temp_creds_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = YouTubeCredentials(
        client_id="test_client_id",
        client_secret="test_client_secret"
    )
    url = service.get_auth_url(state="my_state")
    import urllib.parse
    assert "client_id=test_client_id" in url
    assert "state=my_state" in url
    assert "response_type=code" in url
    assert urllib.parse.quote(service.REDIRECT_URI, safe='') in url


def test_get_auth_url_not_configured(temp_creds_path):
    # credentials が None
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    assert service.get_auth_url() == ""
    
    # client_id が空文字
    service._credentials = YouTubeCredentials(client_id="", client_secret="")
    assert service.get_auth_url() == ""


def test_is_authenticated(temp_creds_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    
    # _credentials が None
    assert service.is_authenticated() is False
    
    # access_token が None
    service._credentials = YouTubeCredentials(client_id="id", client_secret="secret")
    assert service.is_authenticated() is False
    
    # 期限切れ
    service._credentials.access_token = "token"
    service._credentials.expires_at = time.time() - 10
    assert service.is_authenticated() is False
    
    # 有効期限内
    service._credentials.expires_at = time.time() + 100
    assert service.is_authenticated() is True
    
    # expires_at が None の場合
    service._credentials.expires_at = None
    assert service.is_authenticated() is True


def test_get_status(temp_creds_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    
    # 初期状態 (未設定)
    status = service.get_status()
    assert status["is_configured"] is False
    assert status["is_authenticated"] is False
    assert status["has_refresh_token"] is False
    
    # 設定済み・未認証・リフレッシュトークンあり
    service._credentials = YouTubeCredentials(
        client_id="id",
        client_secret="secret",
        refresh_token="refresh"
    )
    status = service.get_status()
    assert status["is_configured"] is True
    assert status["is_authenticated"] is False
    assert status["has_refresh_token"] is True


@pytest.mark.asyncio
async def test_handle_callback_no_credentials(temp_creds_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = None
    success = await service.handle_callback("code")
    assert success is False


@pytest.mark.asyncio
async def test_handle_callback_success(temp_creds_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = YouTubeCredentials(
        client_id="test_client_id",
        client_secret="test_client_secret"
    )
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
        "expires_in": 3600
    }
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        success = await service.handle_callback("valid_code")
        assert success is True
        assert service._credentials.access_token == "new_access_token"
        assert service._credentials.refresh_token == "new_refresh_token"
        assert service._credentials.expires_at is not None
        assert temp_creds_path.exists()


@pytest.mark.asyncio
async def test_handle_callback_failed_status(temp_creds_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = YouTubeCredentials(
        client_id="test_client_id",
        client_secret="test_client_secret"
    )
    
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        success = await service.handle_callback("invalid_code")
        assert success is False


@pytest.mark.asyncio
async def test_handle_callback_http_error(temp_creds_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = YouTubeCredentials(
        client_id="test_client_id",
        client_secret="test_client_secret"
    )
    
    with patch("httpx.AsyncClient.post", side_effect=httpx.HTTPError("Network failure")):
        success = await service.handle_callback("code")
        assert success is False


@pytest.mark.asyncio
async def test_handle_callback_unexpected_error(temp_creds_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = YouTubeCredentials(
        client_id="test_client_id",
        client_secret="test_client_secret"
    )
    
    # post自体で一般例外を発生させる
    with patch("httpx.AsyncClient.post", side_effect=ValueError("Unexpected")):
        success = await service.handle_callback("code")
        assert success is False


@pytest.mark.asyncio
async def test_handle_callback_os_error(temp_creds_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = YouTubeCredentials(
        client_id="test_client_id",
        client_secret="test_client_secret"
    )
    
    with patch.object(service, "_save_credentials", side_effect=OSError("Disk full")):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            success = await service.handle_callback("valid_code")
            assert success is False



@pytest.mark.asyncio
async def test_upload_video_not_authenticated(temp_creds_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = None
    
    result = await service.upload_video(
        video_path="dummy.mp4",
        title="Title",
        description="Desc",
        tags=[]
    )
    assert result.success is False
    assert result.error == "not_authenticated"


@pytest.mark.asyncio
async def test_upload_video_file_not_found(temp_creds_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = YouTubeCredentials(
        client_id="id",
        client_secret="secret",
        access_token="token"
    )
    
    result = await service.upload_video(
        video_path="nonexistent_video.mp4",
        title="Title",
        description="Desc",
        tags=[]
    )
    assert result.success is False
    assert result.error == "file_not_found"


@pytest.mark.asyncio
async def test_upload_video_未実装として失敗する(temp_creds_path, tmp_path):
    """**未実装として失敗させる**（R1.5-C4・2026-08-26 ユーザー決定）。

    以前は `success=True` / `video_id="placeholder_video_id"` を返しており、
    **投稿していないのに「できた」と記録されていた**。チャンネルの数字と
    実装の状態が食い違い、収益化の前提が崩れる。

    このファイルは `pytest.ini` の testpaths の外にあるため CI が見ておらず、
    `backend/tests/test_youtube_upload.py` の重複テストだけを直した結果、
    **ここが赤いまま残っていた**（gate-verifier 1周目の指摘 N-4）。
    """
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = YouTubeCredentials(
        client_id="id",
        client_secret="secret",
        access_token="token"
    )
    
    video_file = tmp_path / "test_video.mp4"
    video_file.write_bytes(b"video data")
    
    result = await service.upload_video(
        video_path=str(video_file),
        title="Title",
        description="Desc",
        tags=["tag1"]
    )
    assert result.success is False
    assert result.error == "not_implemented"
    assert result.status == "failed"
    assert result.video_id is None
    assert "手動で投稿" in result.message


@pytest.mark.asyncio
async def test_upload_video_http_error(temp_creds_path, tmp_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = YouTubeCredentials(
        client_id="id",
        client_secret="secret",
        access_token="token"
    )
    
    video_file = tmp_path / "test_video.mp4"
    video_file.write_bytes(b"video data")
    
    # logger.info をモックして httpx.HTTPError をスローさせる
    with patch("services.youtube_uploader.logger.info", side_effect=httpx.HTTPError("Mock HTTP Error")):
        result = await service.upload_video(
            video_path=str(video_file),
            title="Title",
            description="Desc",
            tags=[]
        )
        assert result.success is False
        assert result.error == "upload_http_error"


@pytest.mark.asyncio
async def test_upload_video_unexpected_error(temp_creds_path, tmp_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = YouTubeCredentials(
        client_id="id",
        client_secret="secret",
        access_token="token"
    )
    
    video_file = tmp_path / "test_video.mp4"
    video_file.write_bytes(b"video data")
    
    # logger.info をモックして ValueError をスローさせる
    with patch("services.youtube_uploader.logger.info", side_effect=ValueError("Unexpected Error")):
        result = await service.upload_video(
            video_path=str(video_file),
            title="Title",
            description="Desc",
            tags=[]
        )
        assert result.success is False
        assert result.error == "upload_error"


@pytest.mark.asyncio
async def test_upload_video_os_error(temp_creds_path, tmp_path):
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    service._credentials = YouTubeCredentials(
        client_id="id",
        client_secret="secret",
        access_token="token"
    )
    
    video_file = tmp_path / "test_video.mp4"
    video_file.write_bytes(b"video data")
    
    with patch("services.youtube_uploader.logger.info", side_effect=OSError("Read error")):
        result = await service.upload_video(
            video_path=str(video_file),
            title="Title",
            description="Desc",
            tags=[]
        )
        assert result.success is False
        assert result.error == "upload_error"



def test_save_credentials_no_credentials(temp_creds_path):
    # サービスを初期化
    service = YouTubeUploaderService(credentials_path=str(temp_creds_path))
    
    # 認証情報を明示的に None に設定
    service._credentials = None
    
    # 事前にファイルが存在しないことを確認
    if temp_creds_path.exists():
        temp_creds_path.unlink()
        
    # 保存を実行
    service._save_credentials()
    
    # ファイルが作成されていないことを確認
    assert not temp_creds_path.exists()




