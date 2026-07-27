import os
import sys
import shutil
import subprocess
import logging
import ctypes
from typing import Dict, Optional
import urllib.request

logger = logging.getLogger(__name__)

# TDR 連携用のストア取得（インポートエラー時はスタブを使用）
try:
    from backend.agents.memory.technical_debt import TechnicalDebtStore
    HAS_TDR = True
except ImportError:
    HAS_TDR = False


class BasePreflightHandler:
    """起動時プレフライト検証のOS別抽象ハンドラ"""

    def check_ffmpeg_dependency(self) -> bool:
        raise NotImplementedError

    def check_disk_space(self, min_gb: float) -> bool:
        raise NotImplementedError

    def check_workspace_connection(self, drive_store) -> bool:
        raise NotImplementedError

    def check_ai_studio_connection(self) -> bool:
        raise NotImplementedError

    def _common_check_workspace_connection(self, drive_store, platform_label: str) -> bool:
        if not drive_store:
            return False
        try:
            # Google Drive の未処理動画取得 API などを呼び出して疎通確認
            videos = drive_store.list_input_raw_videos()
            return videos is not None
        except Exception as e:
            logger.warning(f"{platform_label} Workspace connection check failed: {e}")
            return False

    def _common_check_ai_studio_connection(self, platform_label: str) -> bool:
        try:
            # Google AI Studio API エンドポイントへの疎通チェック
            url = "https://generativelanguage.googleapis.com"
            with urllib.request.urlopen(url, timeout=3) as conn:
                status = conn.getcode()
                return status in (200, 404, 403)  # API疎通自体が確認できれば合格
        except Exception as e:
            logger.warning(f"{platform_label} AI Studio connection check failed: {e}")
            return False

    def _common_check_ffmpeg_dependency(self, ffmpeg_path: str, platform_label: str) -> bool:
        try:
            # バージョン取得コマンドの実行確認
            res = subprocess.run(
                [ffmpeg_path, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5
            )
            return res.returncode == 0
        except subprocess.TimeoutExpired as e:
            logger.warning(f"{platform_label} FFmpeg check timed out: {e}")
            return False
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            logger.warning(f"{platform_label} FFmpeg check failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during {platform_label} FFmpeg check: {e}", exc_info=True)
            return False


class WindowsPreflightHandler(BasePreflightHandler):
    """Windows環境向けプレフライト検証実装"""

    def __init__(self, target_dir: Optional[str] = None):
        self.target_dir = target_dir or os.getcwd()

    def _resolve_ffmpeg_path(self) -> str:
        # PyInstaller一時解凍先 sys._MEIPASS がある場合はそこを優先
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            # 優先してバンドルされたバイナリを確認
            ffmpeg_path = os.path.join(meipass, "bin", "ffmpeg.exe")
            if os.path.exists(ffmpeg_path):
                return ffmpeg_path

        # 通常ローカルの ./bin/ffmpeg.exe を確認
        local_bin_path = os.path.join(os.getcwd(), "bin", "ffmpeg.exe")
        if os.path.exists(local_bin_path):
            return local_bin_path

        # 環境変数 PATH から検索
        which_path = shutil.which("ffmpeg")
        if which_path:
            return which_path

        return "ffmpeg"  # フォールバック

    def check_ffmpeg_dependency(self) -> bool:
        ffmpeg_path = self._resolve_ffmpeg_path()
        return self._common_check_ffmpeg_dependency(ffmpeg_path, "Windows")

    def check_disk_space(self, min_gb: float) -> bool:
        try:
            total, used, free = shutil.disk_usage(self.target_dir)
            free_gb = free / (1024 ** 3)
            return free_gb >= min_gb
        except Exception as e:
            logger.warning(f"Windows disk check failed: {e}")
            return False

    def check_workspace_connection(self, drive_store) -> bool:
        return self._common_check_workspace_connection(drive_store, "Windows")

    def check_ai_studio_connection(self) -> bool:
        return self._common_check_ai_studio_connection("Windows")


class AndroidPreflightHandler(BasePreflightHandler):
    """Android環境向けプレフライト検証実装 (Chaquopy / Kivy 連携前提)"""

    def __init__(self, files_dir: Optional[str] = None):
        # アプリ内ローカル内部ストレージを想定
        self.files_dir = files_dir or "/data/data/com.example/files"

    def _resolve_ffmpeg_path(self) -> str:
        ffmpeg_path = os.path.join(self.files_dir, "ffmpeg")
        if os.path.exists(ffmpeg_path):
            return ffmpeg_path
        
        which_path = shutil.which("ffmpeg")
        if which_path:
            return which_path

        return "ffmpeg"

    def check_ffmpeg_dependency(self) -> bool:
        ffmpeg_path = self._resolve_ffmpeg_path()
        return self._common_check_ffmpeg_dependency(ffmpeg_path, "Android")

    def check_disk_space(self, min_gb: float) -> bool:
        # モバイル環境は空き容量の基準値を小さくする（例: min_gb）
        try:
            if not os.path.exists(self.files_dir):
                os.makedirs(self.files_dir, exist_ok=True)
            total, used, free = shutil.disk_usage(self.files_dir)
            free_gb = free / (1024 ** 3)
            return free_gb >= min_gb
        except Exception as e:
            logger.warning(f"Android disk check failed: {e}")
            return False

    def check_workspace_connection(self, drive_store) -> bool:
        return self._common_check_workspace_connection(drive_store, "Android")

    def check_ai_studio_connection(self) -> bool:
        return self._common_check_ai_studio_connection("Android")


class iOSPreflightHandler(BasePreflightHandler):
    """iOS環境向けプレフライト検証実装 (ctypes による静的ライブラリ・スタティックリンク確認)"""

    def __init__(self, doc_dir: Optional[str] = None):
        self.doc_dir = doc_dir or os.path.expanduser("~/Documents")

    def check_ffmpeg_dependency(self) -> bool:
        # iOSでは subprocess の外部 ffmpeg 起動は制限されるため、
        # アプリに静的リンクされた Cライブラリ (libavcodec などの lib) を ctypes でロードテストする。
        # (iOS実機では CAPI/Swift 側から呼び出すため、Python側ではロード可否が起動条件)
        possible_libs = ["libavcodec.dylib", "libavcodec.so", "ffmpeg-kit", "libffmpeg.dylib"]
        for lib in possible_libs:
            try:
                ctypes.CDLL(lib)
                return True
            except OSError:
                continue
        # いずれのロードも失敗した場合は、モック・ダミーロードまたは失敗とみなす
        return False

    def check_disk_space(self, min_gb: float) -> bool:
        # iOSはサンドボックスのドキュメントディレクトリをチェック
        try:
            if not os.path.exists(self.doc_dir):
                os.makedirs(self.doc_dir, exist_ok=True)
            total, used, free = shutil.disk_usage(self.doc_dir)
            free_gb = free / (1024 ** 3)
            return free_gb >= min_gb
        except Exception as e:
            logger.warning(f"iOS disk check failed: {e}")
            return False

    def check_workspace_connection(self, drive_store) -> bool:
        return self._common_check_workspace_connection(drive_store, "iOS")

    def check_ai_studio_connection(self) -> bool:
        return self._common_check_ai_studio_connection("iOS")


class PreflightValidator:
    """起動環境プレフライト検証のオーケストレーター"""

    def __init__(self, platform_name: Optional[str] = None, drive_store = None, target_dir: Optional[str] = None):
        self.platform = platform_name or sys.platform
        self.drive_store = drive_store
        
        # プラットフォームに応じたハンドラの初期化
        if self.platform.startswith("win"):
            self.handler = WindowsPreflightHandler(target_dir=target_dir)
        elif "android" in self.platform.lower() or os.environ.get("ANDROID_ARGUMENT") is not None:
            self.handler = AndroidPreflightHandler(files_dir=target_dir)
        elif self.platform.startswith("darwin") or "ios" in self.platform.lower():
            self.handler = iOSPreflightHandler(doc_dir=target_dir)
        else:
            # デフォルトとして Windows 用ハンドラをフォールバックに適用
            self.handler = WindowsPreflightHandler(target_dir=target_dir)

    def validate_all(self, min_disk_gb: Optional[float] = None) -> Dict[str, bool]:
        """全項目を検査し、適合結果を返す。不適合時は TDR に自動登録。"""
        # モバイル環境（Android/iOS）ではディスク要求閾値を 0.5 GB (500MB) に緩和
        if min_disk_gb is None:
            if "android" in self.platform.lower() or "ios" in self.platform.lower() or self.platform.startswith("darwin"):
                min_disk_gb = 0.5
            else:
                min_disk_gb = 10.0

        results = {
            "ffmpeg": self.handler.check_ffmpeg_dependency(),
            "disk_space": self.handler.check_disk_space(min_disk_gb),
            "workspace": self.handler.check_workspace_connection(self.drive_store),
            "ai_studio": self.handler.check_ai_studio_connection(),
        }

        # いずれかの検査が失敗した場合、TDR へ債務として登録
        failed_items = [k for k, v in results.items() if not v]
        if failed_items and HAS_TDR:
            try:
                store = TechnicalDebtStore()
                for item in failed_items:
                    store.register_debt(
                        category="IMPORTANT_SERVICE",
                        file_path="backend/services/preflight_validator.py",
                        line_number=270,  # 代表登録行
                        pattern=f"Preflight check failed on platform: {self.platform}",
                        cause_pattern="DP-06",  # プラットフォーム環境不適合パターン
                        fix_pattern=f"クライアントのローカル {item} 環境を修復する、またはハイブリッド委託モードに切り替える",
                        registered_by="preflight_validator",
                        notes=f"プラットフォーム: {self.platform} 上で {item} の検証が不合格となりました。",
                        tags=["preflight", self.platform, item]
                    )
            except Exception as e:
                logger.error(f"Failed to register preflight errors to TechnicalDebtStore: {e}")

        return results
