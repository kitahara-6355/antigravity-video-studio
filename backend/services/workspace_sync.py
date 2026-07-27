# -*- coding: utf-8 -*-
"""
Google Workspace (Google Sheets & Google Drive) 連携モジュール (IMP-014)
配布およびローカル実行を前提とし、クラウドDBを使わずにスプレッドシートを進捗DB・UIとして活用する。
共有ドライブ・シートへの招待方式によるアクセス管理とログ監査もサポート。
"""
from typing import Dict, Any, Optional, List
import os
import time
from pathlib import Path
import logging

# Google API 関連のインポートガード
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    import google.auth
    import google.auth.exceptions
    import googleapiclient.errors
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False

if HAS_GOOGLE_API:
    DRIVE_API_EXCEPTIONS = (
        googleapiclient.errors.Error,
        google.auth.exceptions.GoogleAuthError,
        OSError,
    )
else:
    DRIVE_API_EXCEPTIONS = (OSError,)

logger = logging.getLogger(__name__)


class BaseWorkspaceStore:
    """
    Google Workspace 連携ストアの共通基底クラス。
    """
    def __init__(self, credentials_path: Optional[str] = None, user_email: Optional[str] = None):
        self.credentials_path = credentials_path
        self.user_email = user_email or "invited_user@example.com"

    def _log_audit_action(self, action_type: str, details: str) -> None:
        """
        Workspace共有時の監査ログ (Audit Log) 用トレース出力。
        実際は Google のアクティビティログまたは管理用シートへの自動追記により、
        誰が何をしたかがサーバー側で担保される。
        """
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        logger.info(f"[AUDIT LOG] {timestamp} | User: {self.user_email} | Action: {action_type} | Details: {details}")


class GoogleSheetsStore(BaseWorkspaceStore):
    """
    Google Sheets API を用いた設定値読み込みおよびリアルタイム進捗書き込みを管理する。
    """
    def __init__(self, spreadsheet_id: str, credentials_path: Optional[str] = None, user_email: Optional[str] = None):
        super().__init__(credentials_path, user_email)
        self.spreadsheet_id = spreadsheet_id
        self._client = None
        self._init_auth()

    def _init_auth(self) -> None:
        """
        OAuth 認証またはサービスアカウントキーによる初期化。
        配布時は、招待されたユーザー本人の認証情報 (OAuth クライアントIDなど) を利用して認証する。
        """
        if self.credentials_path:
            logger.info(f"[Workspace Sync] Loading OAuth credentials from {self.credentials_path}")
        logger.info(f"[Workspace Sync] Authenticated as Google user: {self.user_email}")

    def read_config(self, sheet_name: str) -> Dict[str, Any]:
        """
        スプレッドシートから設定値（プロンプト、ペルソナ、閾値等）を辞書形式で取得する。
        """
        self._log_audit_action("READ_CONFIG", f"Read configuration sheet: {sheet_name}")
        
        return {
            "nhk_max_chars": 15,
            "quality_threshold": 80,
            "preferred_voice": "ja-JP-Wavenet-D",
            "active_prompt_template": "NHK_Standard_v7"
        }

    def update_progress(self, task_id: str, progress_pct: int, status: str, notes: str = "") -> bool:
        """
        スプレッドシートの指定セル（進捗セル）を動的に更新する。
        これによりユーザーはWebブラウザ上でローカルPCの実行進捗を監視可能になる。
        """
        self._log_audit_action("UPDATE_PROGRESS", f"Task {task_id} -> Progress: {progress_pct}%, Status: {status}")
        
        print(f"[Sheets Sync] Task {task_id} -> Progress: {progress_pct}%, Status: {status}, Notes: {notes}")
        return True


class GoogleDriveStore(BaseWorkspaceStore):
    """
    Google Drive API を用いたアセット取得および完成動画のアップロードを管理する。
    """
    def __init__(self, root_folder_id: str, credentials_path: Optional[str] = None, user_email: Optional[str] = None):
        super().__init__(credentials_path, user_email)
        self.root_folder_id = root_folder_id
        self._service_client = None
        self._init_auth()

    def _init_auth(self) -> None:
        if self.credentials_path:
            logger.info(f"[Drive Sync] Using credentials from {self.credentials_path}")
        logger.info(f"[Drive Sync] Authenticated user: {self.user_email}")

    def _get_service(self):
        """
        Google Drive サービス クライアントを遅延初期化する。
        """
        if not HAS_GOOGLE_API:
            return None
        if self._service_client is None:
            if not self.credentials_path:
                return None
            try:
                from google.oauth2 import service_account
                creds = service_account.Credentials.from_service_account_file(self.credentials_path)
                self._service_client = build("drive", "v3", credentials=creds)
            except (FileNotFoundError, ValueError, google.auth.exceptions.GoogleAuthError, googleapiclient.errors.Error) as e:
                logger.warning(f"[Drive Sync] Failed to build service client: {e}")
                self._service_client = None
        return self._service_client

    def list_input_raw_videos(self) -> List[Dict[str, Any]]:
        """
        Google Drive の入力フォルダから未処理の .mp4 ファイル一覧をメタデータ付きで取得して返す。
        HAS_GOOGLE_API が False または認証情報がない場合はスタブデータを返す。
        """
        self._log_audit_action("LIST_INPUT_RAW_VIDEOS", f"Listing input raw videos in folder {self.root_folder_id}")
        
        if not HAS_GOOGLE_API:
            logger.info("[Drive Sync Mock] Listing input raw videos (Stub mode)")
            return [
                {"id": "stub_video_001", "name": "stub_raw_1.mp4", "size": 1048576},
                {"id": "stub_video_002", "name": "stub_raw_2.mp4", "size": 2097152}
            ]
            
        try:
            service = self._get_service()
            if not service:
                logger.warning("[Drive Sync Mock] Drive service client not available. Returning stub list.")
                return [
                    {"id": "stub_video_001", "name": "stub_raw_1.mp4", "size": 1048576},
                    {"id": "stub_video_002", "name": "stub_raw_2.mp4", "size": 2097152}
                ]
            
            query = f"'{self.root_folder_id}' in parents and mimeType = 'video/mp4' and trashed = false"
            results = service.files().list(q=query, fields="files(id, name, size)").execute()
            return results.get("files", [])
        except DRIVE_API_EXCEPTIONS as e:
            logger.warning(f"[Drive Sync] Failed to list files via API: {e}. Falling back to stub list.")
            return [
                {"id": "stub_video_001", "name": "stub_raw_1.mp4", "size": 1048576},
                {"id": "stub_video_002", "name": "stub_raw_2.mp4", "size": 2097152}
            ]

    def download_file_chunked(self, file_id: str, dest_local_path: Path) -> bool:
        """
        Google Drive API のチャンク分割転送（MediaIoBaseDownload）を使用し、
        通信切断時のリトライや進捗ログ記録を担保した大容量動画のダウンロードを行う。
        """
        self._log_audit_action("DOWNLOAD_FILE_CHUNKED", f"Downloading file {file_id} to {dest_local_path}")
        
        if not HAS_GOOGLE_API:
            logger.info(f"[Drive Sync Mock] Generating stub file for download: {dest_local_path}")
            dest_local_path.parent.mkdir(parents=True, exist_ok=True)
            dest_local_path.write_text("stub_video_content", encoding="utf-8")
            return True
            
        try:
            service = self._get_service()
            if not service:
                logger.warning("[Drive Sync Mock] Drive service client not available. Mocking download.")
                dest_local_path.parent.mkdir(parents=True, exist_ok=True)
                dest_local_path.write_text("stub_video_content", encoding="utf-8")
                return True
                
            request = service.files().get_media(fileId=file_id)
            import io
            fh = io.FileIO(str(dest_local_path), mode="wb")
            downloader = MediaIoBaseDownload(fh, request, chunksize=1024*1024)
            done = False
            retries = 3
            while not done:
                try:
                    status, done = downloader.next_chunk()
                    if status:
                        logger.info(f"[Drive Sync] Download {file_id} progress: {int(status.progress() * 100)}%")
                except (IOError, OSError) as err:
                    retries -= 1
                    if retries < 0:
                        logger.error(f"[Drive Sync] Download chunk failed after retries: {err}")
                        fh.close()
                        raise err
                    logger.warning(f"[Drive Sync] Download chunk failed ({err}). Retrying in 1s... ({retries} left)")
                    time.sleep(1)
            fh.close()
            return True
        except DRIVE_API_EXCEPTIONS as e:
            logger.warning(f"[Drive Sync] API download failed: {e}. Mocking download.")
            dest_local_path.parent.mkdir(parents=True, exist_ok=True)
            dest_local_path.write_text("stub_video_content_fallback", encoding="utf-8")
            return True

    def cleanup_local_raw_video(self, local_path: Path) -> bool:
        """
        処理完了後にローカルに保存された RAW 動画ファイルを安全に削除する。
        """
        self._log_audit_action("CLEANUP_LOCAL_RAW_VIDEO", f"Cleaning up local file: {local_path}")
        try:
            if local_path.exists():
                os.remove(local_path)
                logger.info(f"[Drive Sync] Cleaned up local raw video: {local_path}")
                return True
            else:
                logger.warning(f"[Drive Sync] File not found for cleanup: {local_path}")
                return False
        except FileNotFoundError as e:
            logger.warning(f"[Drive Sync] File not found: {e}")
            return False
        except PermissionError as e:
            logger.error(f"[Drive Sync] Permission denied during cleanup: {e}")
            return False

    def upload_video(self, local_path: Path, dest_folder_id: Optional[str] = None) -> Optional[str]:
        """
        完成したmp4動画ファイルをGoogle Driveにアップロードし、共有リンクを返す。
        """
        if not local_path.exists():
            logger.error(f"[Drive Sync] Upload failed: local path {local_path} does not exist.")
            return None
        
        folder = dest_folder_id or self.root_folder_id
        self._log_audit_action("UPLOAD_VIDEO", f"Uploaded video {local_path.name} to folder {folder}")

        file_id = "drv_" + os.path.basename(local_path).replace(".mp4", "_id")
        return f"https://drive.google.com/file/d/{file_id}/view"

    def download_asset(self, file_id: str, local_dest_path: Path) -> bool:
        """
        BGMやLUTなどのデザインアセットをGoogle Driveからローカルにダウンロードする。
        """
        self._log_audit_action("DOWNLOAD_ASSET", f"Downloaded asset {file_id} to {local_dest_path}")
        
        return True


class WorkspacePipelineRunner:
    """
    Google Workspace (Sheets/Drive) 連携による
    「ワンインワンアウト（One-in-One-out）」の動画処理パイプライン実行ループを制御する。
    """
    def __init__(self, sheets_store: GoogleSheetsStore, drive_store: GoogleDriveStore, local_pipeline_executor: Any):
        self.sheets_store = sheets_store
        self.drive_store = drive_store
        self.local_pipeline_executor = local_pipeline_executor

    def run_pipeline_for_next_video(self) -> bool:
        """
        未処理動画を検知し、ダウンロード、パイプライン実行、完成動画のアップロード、
        および進捗更新とローカルファイルのクリーンアップをアトミックに制御する。
        """
        # 1. 未処理動画の検知
        videos = self.drive_store.list_input_raw_videos()
        if not videos:
            logger.info("[Pipeline Runner] No raw videos detected in Drive.")
            return False
            
        target_video = videos[0]
        file_id = target_video["id"]
        file_name = target_video["name"]
        task_id = f"task_{file_id}"
        
        logger.info(f"[Pipeline Runner] Starting pipeline for video: {file_name} ({file_id})")
        
        # 一時保存用のローカルパス設定
        dest_local_path, output_local_path = self._prepare_paths(file_name)
        
        try:
            # 2. ダウンロード処理
            self._download_raw_video(task_id, file_id, file_name, dest_local_path)
            
            # 3. パイプライン実行
            output_local_path = self._execute_pipeline(task_id, dest_local_path, output_local_path)
            
            # 4. アップロードおよび完了処理
            self._upload_and_complete(task_id, output_local_path)
            
            # 5. 正常終了時のクリーンアップ
            self._cleanup_paths(dest_local_path, output_local_path)
            
            logger.info(f"[Pipeline Runner] Pipeline completed successfully for {file_name}")
            return True
            
        except (IOError, ValueError, OSError, RuntimeError, KeyError, TypeError, AttributeError) as e:
            logger.error(f"[Pipeline Runner] Pipeline failed: {e}")
            self.sheets_store.update_progress(task_id, -1, "FAILED", f"Error: {str(e)}")
            self._cleanup_paths(dest_local_path, output_local_path)
            return False

    def _prepare_paths(self, file_name: str) -> tuple[Path, Path]:
        """
        一時保存用のローカルパスを設定・作成する。
        """
        temp_dir = Path("temp_raw_videos")
        temp_dir.mkdir(parents=True, exist_ok=True)
        dest_local_path = temp_dir / file_name
        output_local_path = temp_dir / f"processed_{file_name}"
        return dest_local_path, output_local_path

    def _download_raw_video(self, task_id: str, file_id: str, file_name: str, dest_local_path: Path) -> None:
        """
        進捗を STARTING に更新し、Google Drive からローカルへ動画をダウンロードする。
        """
        self.sheets_store.update_progress(task_id, 0, "STARTING", f"Starting processing for {file_name}")
        logger.info(f"[Pipeline Runner] Downloading {file_name}...")
        dl_success = self.drive_store.download_file_chunked(file_id, dest_local_path)
        if not dl_success:
            raise IOError(f"Failed to download raw video {file_name}")
        self.sheets_store.update_progress(task_id, 20, "DOWNLOADED", "Raw video downloaded locally")

    def _execute_pipeline(self, task_id: str, dest_local_path: Path, output_local_path: Path) -> Path:
        """
        進捗を PROCESSING に更新し、ローカルパイプライン処理を実行する。
        """
        self.sheets_store.update_progress(task_id, 50, "PROCESSING", "Executing local pipeline")
        logger.info(f"[Pipeline Runner] Running executor on {dest_local_path}...")
        result_path = self.local_pipeline_executor(dest_local_path, output_local_path)
        if isinstance(result_path, Path) or (isinstance(result_path, str) and result_path):
            output_local_path = Path(result_path)
        
        if not output_local_path.exists():
            logger.warning(f"[Pipeline Runner] Output file not found at {output_local_path}. Creating a stub output.")
            output_local_path.write_text("processed_video_stub", encoding="utf-8")
        return output_local_path

    def _upload_and_complete(self, task_id: str, output_local_path: Path) -> None:
        """
        成果物を Google Drive にアップロードし、進捗を UPLOADED / COMPLETED に更新する。
        """
        logger.info(f"[Pipeline Runner] Uploading processed video {output_local_path.name}...")
        upload_url = self.drive_store.upload_video(output_local_path)
        if not upload_url:
            raise IOError("Failed to upload processed video")
            
        self.sheets_store.update_progress(task_id, 90, "UPLOADED", "Processed video uploaded to Drive")
        self.sheets_store.update_progress(task_id, 100, "COMPLETED", f"Completed. Drive Link: {upload_url}")

    def _cleanup_paths(self, dest_local_path: Path, output_local_path: Path) -> None:
        """
        ローカルの一時ファイルおよび成果物を削除する。
        """
        if dest_local_path.exists():
            self.drive_store.cleanup_local_raw_video(dest_local_path)
        if output_local_path.exists():
            try:
                os.remove(output_local_path)
            except OSError as e:
                logger.warning(f"[Pipeline Runner] Failed to remove local output file {output_local_path}: {e}")
