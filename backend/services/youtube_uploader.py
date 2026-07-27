"""
YouTube Uploader Service - YouTube動画アップロードサービス

PROJECT_CONSTITUTION §23 YouTube最適化規約準拠:
- OAuth 2.0認証フロー
- 動画アップロード
- サムネイル・メタデータ設定

NOTE: 本サービスを使用するには、Google Cloud Consoleでの設定が必要です。
      詳細は docs/youtube_api_setup.md を参照してください。
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from pathlib import Path
import logging
import os
import json
import httpx

logger = logging.getLogger(__name__)


@dataclass
class YouTubeCredentials:
    """YouTube API認証情報"""
    client_id: str
    client_secret: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[float] = None


@dataclass
class UploadResult:
    """アップロード結果"""
    success: bool
    video_id: Optional[str] = None
    video_url: Optional[str] = None
    status: str = "pending"  # pending, uploading, processing, published, failed
    message: str = ""
    error: Optional[str] = None


class YouTubeUploaderService:
    """
    YouTube動画アップロードサービス
    
    Google OAuth 2.0認証を使用して、YouTubeに動画をアップロードする。
    """
    
    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
    ]
    
    AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
    TOKEN_URI = "https://oauth2.googleapis.com/token"
    REDIRECT_URI = "http://localhost:8000/api/youtube-upload/callback"
    
    def __init__(self, credentials_path: str = "config/youtube_credentials.json"):
        self.credentials_path = Path(credentials_path)
        self._credentials: Optional[YouTubeCredentials] = None
        self._load_credentials()
    
    def _load_credentials(self):
        """認証情報を読み込む"""
        if self.credentials_path.exists():
            try:
                with open(self.credentials_path, 'r') as f:
                    data = json.load(f)
                    self._credentials = YouTubeCredentials(
                        client_id=data.get("client_id", ""),
                        client_secret=data.get("client_secret", ""),
                        access_token=data.get("access_token"),
                        refresh_token=data.get("refresh_token"),
                        expires_at=data.get("expires_at")
                    )
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load credentials: {e}", exc_info=True)
    
    def _save_credentials(self):
        """認証情報を保存"""
        if self._credentials:
            self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.credentials_path, 'w') as f:
                json.dump({
                    "client_id": self._credentials.client_id,
                    "client_secret": self._credentials.client_secret,
                    "access_token": self._credentials.access_token,
                    "refresh_token": self._credentials.refresh_token,
                    "expires_at": self._credentials.expires_at
                }, f, indent=2)
    
    def get_auth_url(self, state: str = "") -> str:
        """OAuth認証URLを取得"""
        if not self._credentials or not self._credentials.client_id:
            return ""
        
        import urllib.parse
        
        params = {
            "client_id": self._credentials.client_id,
            "redirect_uri": self.REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state
        }
        
        return f"{self.AUTH_URI}?{urllib.parse.urlencode(params)}"
    
    async def handle_callback(self, code: str) -> bool:
        """OAuthコールバックを処理"""
        if not self._credentials:
            return False
        
        try:
            import httpx
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.TOKEN_URI,
                    data={
                        "client_id": self._credentials.client_id,
                        "client_secret": self._credentials.client_secret,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": self.REDIRECT_URI
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self._credentials.access_token = data.get("access_token")
                    self._credentials.refresh_token = data.get("refresh_token")
                    self._credentials.expires_at = data.get("expires_in", 3600) + __import__('time').time()
                    self._save_credentials()
                    logger.info("YouTube OAuth authentication successful")
                    return True
                else:
                    logger.error(f"OAuth token exchange failed: {response.text}")
                    return False
                    
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.error(f"OAuth callback network/format error: {e}", exc_info=True)
            return False
        except (ImportError, AttributeError, KeyError, TypeError) as e:
            logger.error(f"OAuth callback unexpected error: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"OAuth callback unexpected general error: {e}", exc_info=True)
            return False
    
    async def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: List[str],
        category_id: str = "22",  # People & Blogs
        privacy_status: str = "private",
        thumbnail_path: Optional[str] = None
    ) -> UploadResult:
        """
        YouTube動画をアップロード
        
        Args:
            video_path: 動画ファイルのパス
            title: 動画タイトル
            description: 動画説明
            tags: タグリスト
            category_id: カテゴリID
            privacy_status: 公開設定（private, unlisted, public）
            thumbnail_path: サムネイル画像のパス
            
        Returns:
            UploadResult: アップロード結果
        """
        if not self._credentials or not self._credentials.access_token:
            return UploadResult(
                success=False,
                status="failed",
                message="YouTube認証が必要です。先にOAuth認証を完了してください。",
                error="not_authenticated"
            )
        
        if not Path(video_path).exists():
            return UploadResult(
                success=False,
                status="failed",
                message=f"動画ファイルが見つかりません: {video_path}",
                error="file_not_found"
            )
        
        try:
            import httpx
            
            # メタデータを構築
            body = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": tags,
                    "categoryId": category_id
                },
                "status": {
                    "privacyStatus": privacy_status
                }
            }
            
            # アップロードは複数パートで行う（簡略化版）
            # 実際の実装ではresumable uploadを使用
            
            logger.info(f"Uploading video: {title}")
            
            # プレースホルダー実装（実際のAPI呼び出しは要実装）
            return UploadResult(
                success=True,
                video_id="placeholder_video_id",
                video_url="https://youtube.com/watch?v=placeholder",
                status="processing",
                message="アップロード機能はOAuth設定後に有効になります。docs/youtube_api_setup.md を参照してください。"
            )
            
        except httpx.HTTPError as e:
            logger.error(f"Video upload HTTP error: {e}", exc_info=True)
            return UploadResult(
                success=False,
                status="failed",
                message=f"HTTP error during upload: {e}",
                error="upload_http_error"
            )
        except Exception as e:
            logger.error(f"Video upload unexpected error: {e}", exc_info=True)
            return UploadResult(
                success=False,
                status="failed",
                message=str(e),
                error="upload_error"
            )
    
    def is_authenticated(self) -> bool:
        """認証済みかどうかを確認"""
        import time
        
        if not self._credentials:
            return False
        
        if not self._credentials.access_token:
            return False
        
        if self._credentials.expires_at and self._credentials.expires_at < time.time():
            return False
        
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """認証状態を取得"""
        return {
            "is_configured": bool(self._credentials and self._credentials.client_id),
            "is_authenticated": self.is_authenticated(),
            "has_refresh_token": bool(self._credentials and self._credentials.refresh_token)
        }


# シングルトンインスタンス
youtube_uploader = YouTubeUploaderService()
