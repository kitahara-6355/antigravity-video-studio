"""
YouTube Upload Router - YouTubeアップロードAPIエンドポイント

PROJECT_CONSTITUTION §23 YouTube最適化規約準拠:
- OAuth認証フロー
- 動画アップロード
- 認証状態確認
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict
from typing import Dict, Any, List, Optional, TypedDict
import logging
import urllib.parse
from urllib.parse import urlparse
import httpx


class YouTubeErrorDetail(TypedDict):
    """YouTubeアップロード処理におけるエラー詳細の型定義"""
    status_code: int
    detail: str


class YouTubeUploadErrorHandler:
    """例外から適切なレスポンス/エラーメッセージ/HTTPExceptionへの変換を行うハンドラー"""

    @staticmethod
    def handle_auth_error(e: Exception) -> YouTubeErrorDetail:
        """start_auth での例外ハンドリング"""
        if isinstance(e, ValueError):
            return {"status_code": 400, "detail": str(e)}
        return {"status_code": 500, "detail": str(e)}

    @staticmethod
    def handle_callback_error(e: Exception) -> str:
        """auth_callback での例外ハンドリング"""
        if isinstance(e, httpx.HTTPError):
            return "Network connection to Google API failed"
        return str(e)

    @staticmethod
    def handle_upload_error(e: Exception) -> YouTubeErrorDetail:
        """upload_video での例外ハンドリング"""
        if isinstance(e, ValueError):
            return {"status_code": 400, "detail": str(e)}
        elif isinstance(e, (FileNotFoundError, PermissionError)):
            return {"status_code": 400, "detail": f"File access error: {e}"}
        elif isinstance(e, httpx.HTTPError):
            return {"status_code": 502, "detail": f"Network error communicating with YouTube: {e}"}
        return {"status_code": 500, "detail": str(e)}

    @staticmethod
    def handle_status_error(e: Exception) -> YouTubeErrorDetail:
        """get_upload_status での例外ハンドリング"""
        return {"status_code": 500, "detail": str(e)}


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/youtube-upload", tags=["YouTube Upload"])


class UploadVideoRequest(BaseModel):
    """動画アップロードリクエスト"""
    model_config = ConfigDict(populate_by_name=True)
    video_path: str
    title: str
    description: str
    tags: List[str] = []
    category_id: str = "22"
    privacy_status: str = "private"  # private, unlisted, public
    thumbnail_path: Optional[str] = None


def is_safe_redirect(url: str) -> bool:
    """オープンリダイレクト脆弱性を防止するためのURL検証"""
    if url is None:
        return True
    if not isinstance(url, str):
        return False
    if not url:
        return True
    try:
        # 相対パスは安全
        if url.startswith("/") and not url.startswith("//"):
            return True
        # 絶対URLの場合はホスト名が許可されたもののみ
        parsed = urlparse(url)
        return parsed.hostname in ("localhost", "127.0.0.1")
    except (ValueError, TypeError):
        return False


@router.get("/auth")
async def start_auth(redirect_url: str = "") -> Dict[str, Any]:
    """
    OAuth認証を開始
    
    Google Cloud ConsoleでのOAuth設定が必要です。
    docs/youtube_api_setup.md を参照してください。
    """
    if redirect_url and not is_safe_redirect(redirect_url):
        logger.warning(f"Unsafe redirect URL blocked: {redirect_url}")
        raise HTTPException(status_code=400, detail="Unsafe redirect URL is not allowed")

    try:
        from services.youtube_uploader import youtube_uploader
        
        status = youtube_uploader.get_status()
        
        if not isinstance(status, dict) or not status.get("is_configured", False):
            return {
                "success": False,
                "message": "YouTube APIが未設定です。docs/youtube_api_setup.md を参照して設定してください。",
                "setup_required": True
            }
        
        auth_url = youtube_uploader.get_auth_url(state=redirect_url)
        
        return {
            "success": True,
            "auth_url": auth_url,
            "message": "以下のURLでGoogle認証を行ってください"
        }
        
    except ImportError as e:
        logger.error(f"Uploader import failed: {e}")
        raise HTTPException(status_code=500, detail=f"YouTube uploader service could not be loaded: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth start failed: {e}")
        err = YouTubeUploadErrorHandler.handle_auth_error(e)
        raise HTTPException(status_code=err["status_code"], detail=err["detail"])


@router.get("/callback")
async def auth_callback(code: str = "", state: str = "", error: str = ""):
    """OAuth認証コールバック"""
    # stateが安全でないリダイレクト先の場合はデフォルトの / に戻す
    safe_state = state
    if state and not is_safe_redirect(state):
        logger.warning(f"Unsafe callback state URL blocked and fallback to root: {state}")
        safe_state = "/"

    if error:
        # 改行除去 & サニタイズ
        safe_error = "".join(c for c in error if c not in "\r\n")
        safe_error = urllib.parse.quote(safe_error)
        return RedirectResponse(url=f"/?error={safe_error}")
    
    if not code:
        return RedirectResponse(url="/?error=no_code")
    
    try:
        from services.youtube_uploader import youtube_uploader
        
        success = await youtube_uploader.handle_callback(code)
        
        if success:
            redirect_url = safe_state if safe_state else "/"
            separator = "&" if "?" in redirect_url else "?"
            return RedirectResponse(url=f"{redirect_url}{separator}youtube_auth=success")
        else:
            return RedirectResponse(url="/?youtube_auth=failed")
            
    except ImportError as e:
        logger.error(f"Uploader import failed: {e}")
        return RedirectResponse(url=f"/?error={urllib.parse.quote('YouTube uploader service not available')}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth callback failed: {e}")
        err_msg = YouTubeUploadErrorHandler.handle_callback_error(e)
        return RedirectResponse(url=f"/?error={urllib.parse.quote(err_msg)}")


@router.post("/upload")
async def upload_video(req: UploadVideoRequest) -> Dict[str, Any]:
    """
    動画をYouTubeにアップロード
    
    事前にOAuth認証が必要です。
    """
    # 1. 認証チェック
    try:
        from services.youtube_uploader import youtube_uploader
    except ImportError as e:
        logger.error(f"Uploader import failed: {e}")
        raise HTTPException(status_code=500, detail=f"Uploader import failed: {e}")

    if not youtube_uploader.is_authenticated():
        return {
            "success": False,
            "message": "YouTube認証が必要です。/api/youtube-upload/auth でOAuth認証を行ってください。",
            "auth_required": True
        }

    # 2. パラメータの検証
    if not req.title or not req.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty or whitespace only")
    if len(req.title) > 100:
        raise HTTPException(status_code=400, detail="Title cannot exceed 100 characters")

    valid_privacy = {"private", "unlisted", "public"}
    if req.privacy_status not in valid_privacy:
        raise HTTPException(status_code=400, detail=f"Invalid privacy status. Must be one of {valid_privacy}")

    # 3. ファイルシステム例外のガード
    from pathlib import Path
    
    # 動画ファイルの存在・フォーマットチェック
    try:
        video_p = Path(req.video_path).resolve()
        if not video_p.exists():
            raise HTTPException(status_code=400, detail=f"Video file does not exist: {req.video_path}")
        if not video_p.is_file():
            raise HTTPException(status_code=400, detail=f"Video path is not a file: {req.video_path}")
        if video_p.stat().st_size == 0:
            raise HTTPException(status_code=400, detail=f"Video file is empty: {req.video_path}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"Permission denied accessing video file: {e}")
    except (ValueError, TypeError, OSError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid video path format or access error: {e}")

    # サムネイルファイルの存在・フォーマットチェック
    if req.thumbnail_path:
        try:
            thumb_p = Path(req.thumbnail_path).resolve()
            if not thumb_p.exists():
                raise HTTPException(status_code=400, detail=f"Thumbnail file does not exist: {req.thumbnail_path}")
            if not thumb_p.is_file():
                raise HTTPException(status_code=400, detail=f"Thumbnail path is not a file: {req.thumbnail_path}")
            if thumb_p.stat().st_size == 0:
                raise HTTPException(status_code=400, detail=f"Thumbnail file is empty: {req.thumbnail_path}")
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=f"Permission denied accessing thumbnail file: {e}")
        except (ValueError, TypeError, OSError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid thumbnail path format or access error: {e}")

    try:
        result = await youtube_uploader.upload_video(
            video_path=req.video_path,
            title=req.title,
            description=req.description,
            tags=req.tags,
            category_id=req.category_id,
            privacy_status=req.privacy_status,
            thumbnail_path=req.thumbnail_path
        )
        
        return {
            "success": result.success,
            "video_id": result.video_id,
            "video_url": result.video_url,
            "status": result.status,
            "message": result.message,
            "error": result.error
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        err = YouTubeUploadErrorHandler.handle_upload_error(e)
        raise HTTPException(status_code=err["status_code"], detail=err["detail"])


@router.get("/status")
async def get_upload_status() -> Dict[str, Any]:
    """認証状態とアップロード可否を確認"""
    try:
        from services.youtube_uploader import youtube_uploader
        
        status = youtube_uploader.get_status()
        
        if not isinstance(status, dict) or "is_authenticated" not in status:
            raise HTTPException(status_code=500, detail="Invalid uploader status response")

        return {
            "success": True,
            **status,
            "message": "認証済み" if status["is_authenticated"] else "未認証（OAuth認証が必要）"
        }
        
    except ImportError as e:
        logger.error(f"Uploader import failed: {e}")
        raise HTTPException(status_code=500, detail=f"YouTube uploader service could not be loaded: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        err = YouTubeUploadErrorHandler.handle_status_error(e)
        raise HTTPException(status_code=err["status_code"], detail=err["detail"])


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """ヘルスチェック"""
    return {"status": "ok", "service": "youtube_upload"}
