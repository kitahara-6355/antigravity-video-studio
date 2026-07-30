"""Google Workspace (Sheets / Drive) 連携。

素材と成果物の置き場を Google Drive に置き、進捗 DB / UI を Google
スプレッドシートで代用する。クラウド DB は使わない。

## フォルダ構成（2026-07-30 に共有ドライブへ移行）

Workspace の共有ドライブを使う。マイドライブではない。共有ドライブでは
ファイルの所有者が個人ではなくドライブ自体になるため、投稿者が抜けても
素材が消えず、外部から RAW を受け取っても相手の容量枠を消費しない。

    共有ドライブ「10-チャンネルA」
      01-input/    未処理 RAW      → root_folder_id
      02-output/   成果物          → output_folder_id
      03-library/  インサート素材
      04-work/     予約（未使用）

**入力と出力は必ず別フォルダにする。** 同じにすると、アップロードした成果物が
次回の実行で未処理 RAW として拾われ、無限に再処理される。`upload_video` は
出力フォルダが未設定なら入力へ書き戻さずに失敗する。

素材の同一性をファイル名で判定しないこと。名前と中身が食い違う実例が既にある
（`20251010_..._インタビュー.mp4` の中身が別収録だった）。Drive のファイル ID か
`appProperties` を使う。

## 2026-07-28 の作り直しについて

これ以前の実装は**動くが何もしなかった**。認証情報なし・実在しないフォルダ ID
でもパイプラインが `COMPLETED 100%` まで進み、実在しない Drive リンクを返した。

| 旧実装 | 実態 |
|---|---|
| `upload_video` | API 呼び出しなし。偽リンクを組み立てて返すだけ |
| `read_config` | API 呼び出しなし。ハードコードされた辞書 |
| `update_progress` | API 呼び出しなし。`print` するだけ |
| `download_file_chunked` | 失敗時に `"stub_video_content_fallback"` を .mp4 として書き `True` |

他人の動画を預かる運用では、この「成功したように見えて何もしていない」経路が
最も危険なので全廃した。**このモジュールは失敗したら例外を上げる。**
スタブへのフォールバックは存在しない。

## 認証

`google_oauth.load_credentials()` に集約。サービスアカウントは使わない
（理由は `google_oauth.py` の docstring を参照）。

## スプレッドシートの構成

読み書きする範囲を固定している。列を増やすのは自由だが、先頭の意味は変えないこと。

- 設定シート: A列=キー / B列=値
- 進捗シート: A列=task_id / B列=進捗% / C列=ステータス / D列=備考
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

try:
    from backend.path_resolver import project_root
    from backend.services.google_oauth import (
        DRIVE_SCOPES,
        SHEETS_SCOPES,
        GoogleAuthError,
        load_credentials,
    )
except ImportError:  # backend/ を直接 sys.path に載せている経路向け
    from path_resolver import project_root
    from services.google_oauth import (  # type: ignore[no-redef]
        DRIVE_SCOPES,
        SHEETS_SCOPES,
        GoogleAuthError,
        load_credentials,
    )

logger = logging.getLogger(__name__)

__all__ = [
    "DOWNLOAD_CHUNK_SIZE",
    "GoogleDriveStore",
    "GoogleSheetsStore",
    "InsufficientDiskSpaceError",
    "WorkspacePipelineRunner",
    "WorkspaceSyncError",
    "ensure_disk_space",
    "temp_raw_videos_dir",
]

# ダウンロードのチャンクサイズ。チャンク1個につき HTTPS の往復が1回起きるため、
# 小さいと往復回数が律速になる。2026-07-30 に共有ドライブ上の 239.3 MB で実測:
#
#     1 MB  → 172.5 秒 (1.4 MB/秒)  往復 240 回   ← 変更前の値
#    16 MB  →  19.5 秒 (12.3 MB/秒) 往復  15 回
#    64 MB  →  11.2 秒 (21.3 MB/秒) 往復   4 回
#
# 回線ではなく往復回数が支配的だった。6 GB の RAW で約74分→約5分の差になる。
# 大きくするとチャンク1個ぶんがメモリに載るので、64 MB を上限とする。
DOWNLOAD_CHUNK_SIZE = 64 * 1024 * 1024

# ダウンロード前に確保を要求する空き容量の倍率（元動画サイズに対して）。
# 内訳: 原本1 + ffmpeg の中間ファイル2 + 出力1。多段処理では中間が実サイズで
# 2本残ることがあるため 4 を採る。足りないまま始めると、原本のダウンロードは
# 通っても中間生成で力尽きる。原因が容量だと分かりにくいので事前に落とす。
DISK_HEADROOM_FACTOR = 4


class WorkspaceSyncError(RuntimeError):
    """Drive / Sheets との同期に失敗した。"""


class InsufficientDiskSpaceError(WorkspaceSyncError):
    """作業に必要な空き容量が無い。"""


def ensure_disk_space(target_dir: Path, required_bytes: int) -> None:
    """`target_dir` のあるドライブに `required_bytes` の空きがあることを確認する。

    無ければ `InsufficientDiskSpaceError` を上げて、ダウンロードを始める前に止める。
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(target_dir).free
    if free >= required_bytes:
        return
    gb = 1024**3
    raise InsufficientDiskSpaceError(
        f"空き容量が足りません: 必要 {required_bytes / gb:,.2f} GB / "
        f"空き {free / gb:,.2f} GB ({target_dir})"
    )


def temp_raw_videos_dir() -> Path:
    """Drive から落とした RAW の一時置き場。

    旧実装は `Path("temp_raw_videos")` と書いていたため、カレントディレクトリ
    次第で書き込み先が変わっていた。`path_resolver` 起点に固定する。
    """
    override = os.environ.get("ANTIGRAVITY_TEMP_RAW_VIDEOS")
    if override:
        return Path(override)
    return project_root() / "temp_raw_videos"


def _build_service(name: str, version: str, scopes: Sequence[str]) -> Any:
    """認証済みの API クライアントを作る。失敗は例外で伝える。"""
    try:
        from googleapiclient.discovery import build
    except ImportError as e:
        raise WorkspaceSyncError(
            "google-api-python-client が入っていません。"
            "pip install -r requirements.txt を実行してください。"
        ) from e

    credentials = load_credentials(scopes)
    return build(name, version, credentials=credentials, cache_discovery=False)


class BaseWorkspaceStore:
    """Sheets / Drive ストアの共通部分。"""

    def __init__(self, user_email: str | None = None):
        self.user_email = user_email or "(unknown)"

    def _log_audit_action(self, action_type: str, details: str) -> None:
        """誰が何をしたかの監査トレース。

        実際の権威ある記録は Google 側のアクティビティログ。これはローカルの
        突き合わせ用。
        """
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        logger.info(
            f"[AUDIT LOG] {timestamp} | User: {self.user_email} "
            f"| Action: {action_type} | Details: {details}"
        )


class GoogleSheetsStore(BaseWorkspaceStore):
    """スプレッドシートを設定の読み出し先・進捗の書き込み先として使う。"""

    def __init__(self, spreadsheet_id: str, user_email: str | None = None):
        super().__init__(user_email)
        if not spreadsheet_id:
            raise ValueError("spreadsheet_id は必須です")
        self.spreadsheet_id = spreadsheet_id
        self._service: Any = None

    def _get_service(self) -> Any:
        if self._service is None:
            self._service = _build_service("sheets", "v4", SHEETS_SCOPES)
        return self._service

    def _values(self) -> Any:
        return self._get_service().spreadsheets().values()

    def read_config(self, sheet_name: str) -> dict[str, Any]:
        """設定シート（A列=キー / B列=値）を辞書で返す。

        数値に見える値は int / float に変換する。シートには文字列しか
        入らないため、閾値の比較が文字列比較になる事故を防ぐ。
        """
        self._log_audit_action("READ_CONFIG", f"Read configuration sheet: {sheet_name}")
        try:
            response = self._values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{sheet_name}!A:B",
            ).execute()
        except GoogleAuthError:
            raise
        except Exception as e:
            raise WorkspaceSyncError(
                f"設定シート '{sheet_name}' を読めません: {e}"
            ) from e

        config: dict[str, Any] = {}
        for row in response.get("values", []):
            if not row or not row[0]:
                continue
            key = str(row[0]).strip()
            raw = row[1] if len(row) > 1 else ""
            config[key] = _coerce(raw)
        return config

    def update_progress(
        self, task_id: str, progress_pct: int, status: str, notes: str = ""
    ) -> bool:
        """進捗シートの当該行を更新する。無ければ追記する。

        Returns:
            True: 書き込み成功。失敗時は例外を上げるので False は返らない。
        """
        self._log_audit_action(
            "UPDATE_PROGRESS", f"Task {task_id} -> Progress: {progress_pct}%, Status: {status}"
        )
        sheet = os.environ.get("ANTIGRAVITY_SHEETS_PROGRESS_TAB", "Progress")
        row_values = [[task_id, progress_pct, status, notes]]

        try:
            existing = self._values().get(
                spreadsheetId=self.spreadsheet_id, range=f"{sheet}!A:A"
            ).execute()
            column = [r[0] if r else "" for r in existing.get("values", [])]

            if task_id in column:
                row_number = column.index(task_id) + 1  # シートは1始まり
                self._values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{sheet}!A{row_number}:D{row_number}",
                    valueInputOption="RAW",
                    body={"values": row_values},
                ).execute()
            else:
                self._values().append(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{sheet}!A:D",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": row_values},
                ).execute()
        except GoogleAuthError:
            raise
        except Exception as e:
            raise WorkspaceSyncError(
                f"進捗の書き込みに失敗しました (task={task_id}): {e}"
            ) from e
        return True


def _coerce(raw: Any) -> Any:
    """シートの文字列を数値・真偽値に寄せる。判別できなければそのまま返す。"""
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


class GoogleDriveStore(BaseWorkspaceStore):
    """Drive を素材の取得元・成果物の置き場として使う。"""

    # 共有ドライブ対応のフラグ。個人 Drive では無害。Workspace へ移す場合に要る。
    _SHARED_DRIVE_ARGS: ClassVar[dict[str, bool]] = {
        "supportsAllDrives": True,
        "includeItemsFromAllDrives": True,
    }

    def __init__(
        self,
        root_folder_id: str,
        *,
        output_folder_id: str | None = None,
        user_email: str | None = None,
    ):
        """
        `output_folder_id` を第2引数に足したため、以降はキーワード専用にしている。
        位置引数を許すと `GoogleDriveStore(folder, "u@example.com")` が
        「出力フォルダ = u@example.com」と解釈され、静かに誤動作する。

        Args:
            root_folder_id: 未処理 RAW を読む入力フォルダ。
            output_folder_id: 成果物を書く出力フォルダ。**入力とは別にすること。**
                同じにすると、アップロードした成果物が次回の実行で未処理 RAW として
                拾われ、無限に再処理される。読み取りしかしない場合は省略してよい
                （その場合 `upload_video` は失敗する）。
        """
        super().__init__(user_email)
        if not root_folder_id:
            raise ValueError("root_folder_id は必須です")
        self.root_folder_id = root_folder_id
        self.output_folder_id = output_folder_id
        self._service: Any = None

    def _get_service(self) -> Any:
        if self._service is None:
            self._service = _build_service("drive", "v3", DRIVE_SCOPES)
        return self._service

    def list_input_raw_videos(self) -> list[dict[str, Any]]:
        """入力フォルダ内の未処理 .mp4 を列挙する。

        ページングを辿るので、フォルダに100件以上あっても取りこぼさない。
        """
        self._log_audit_action(
            "LIST_INPUT_RAW_VIDEOS", f"Listing input raw videos in folder {self.root_folder_id}"
        )
        query = (
            f"'{self.root_folder_id}' in parents "
            "and mimeType = 'video/mp4' and trashed = false"
        )
        files: list[dict[str, Any]] = []
        page_token: str | None = None
        try:
            service = self._get_service()
            while True:
                response = service.files().list(
                    q=query,
                    fields="nextPageToken, files(id, name, size, modifiedTime)",
                    pageToken=page_token,
                    **self._SHARED_DRIVE_ARGS,
                ).execute()
                files.extend(response.get("files", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
        except GoogleAuthError:
            raise
        except Exception as e:
            raise WorkspaceSyncError(
                f"入力フォルダ {self.root_folder_id} を列挙できません: {e}"
            ) from e
        return files

    def download_file_chunked(self, file_id: str, dest_local_path: Path) -> bool:
        """チャンク分割でダウンロードする。

        旧実装は失敗時にテキストを .mp4 として書き `True` を返していた。
        いまは失敗を隠さず、書きかけのファイルも残さない。

        Returns:
            True: 完了。失敗時は例外を上げるので False は返らない。
        """
        self._log_audit_action(
            "DOWNLOAD_FILE_CHUNKED", f"Downloading file {file_id} to {dest_local_path}"
        )
        try:
            from googleapiclient.http import MediaIoBaseDownload
        except ImportError as e:
            raise WorkspaceSyncError("google-api-python-client が入っていません。") from e

        service = self._get_service()
        dest_local_path.parent.mkdir(parents=True, exist_ok=True)
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

        import io

        retries_left = 3
        try:
            with io.FileIO(str(dest_local_path), mode="wb") as fh:
                downloader = MediaIoBaseDownload(fh, request, chunksize=DOWNLOAD_CHUNK_SIZE)
                done = False
                while not done:
                    try:
                        status, done = downloader.next_chunk()
                        if status:
                            logger.info(
                                f"[Drive Sync] Download {file_id} progress: "
                                f"{int(status.progress() * 100)}%"
                            )
                    except OSError as err:
                        retries_left -= 1
                        if retries_left < 0:
                            raise
                        logger.warning(
                            f"[Drive Sync] チャンク取得に失敗 ({err})。"
                            f"1秒後に再試行します (残り {retries_left})"
                        )
                        time.sleep(1)
        except Exception as e:
            # 中途半端なファイルを「落とせた」と誤認させない
            dest_local_path.unlink(missing_ok=True)
            raise WorkspaceSyncError(
                f"ファイル {file_id} のダウンロードに失敗しました: {e}"
            ) from e
        return True

    def upload_video(self, local_path: Path, dest_folder_id: str | None = None) -> str:
        """完成した動画を Drive にアップロードし、閲覧リンクを返す。

        旧実装はアップロードせずに偽リンクを返していた。

        宛先は `dest_folder_id` → `self.output_folder_id` の順に解決する。
        どちらも無いときに入力フォルダへ書き戻すことはしない。それをやると
        成果物が次回の未処理 RAW として拾われ、無限に再処理される。
        """
        if not local_path.exists():
            raise WorkspaceSyncError(f"アップロード対象がありません: {local_path}")

        folder = dest_folder_id or self.output_folder_id
        if not folder:
            raise WorkspaceSyncError(
                "出力フォルダが設定されていません。"
                "GoogleDriveStore(output_folder_id=...) を指定してください"
                "（入力フォルダに書き戻すと無限に再処理されます）"
            )
        if folder == self.root_folder_id:
            logger.warning(
                "[Drive Sync] 出力先が入力フォルダと同じです (%s)。"
                "成果物が次回の未処理 RAW として拾われます",
                folder,
            )
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as e:
            raise WorkspaceSyncError("google-api-python-client が入っていません。") from e

        try:
            service = self._get_service()
            media = MediaFileUpload(str(local_path), resumable=True)
            created = service.files().create(
                body={"name": local_path.name, "parents": [folder]},
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,
            ).execute()
        except GoogleAuthError:
            raise
        except Exception as e:
            raise WorkspaceSyncError(
                f"{local_path.name} のアップロードに失敗しました: {e}"
            ) from e

        self._log_audit_action(
            "UPLOAD_VIDEO", f"Uploaded video {local_path.name} to folder {folder}"
        )
        link = created.get("webViewLink")
        if not link:
            file_id = created.get("id")
            if not file_id:
                raise WorkspaceSyncError(
                    f"アップロードの応答にファイル ID がありません: {created}"
                )
            link = f"https://drive.google.com/file/d/{file_id}/view"
        return link

    def download_asset(self, file_id: str, local_dest_path: Path) -> bool:
        """BGM や LUT などの素材を落とす。動画と同じ経路を使う。"""
        self._log_audit_action(
            "DOWNLOAD_ASSET", f"Downloading asset {file_id} to {local_dest_path}"
        )
        return self.download_file_chunked(file_id, local_dest_path)

    def cleanup_local_raw_video(self, local_path: Path) -> bool:
        """処理済みのローカル RAW を削除する。"""
        self._log_audit_action("CLEANUP_LOCAL_RAW_VIDEO", f"Cleaning up local file: {local_path}")
        try:
            if not local_path.exists():
                logger.warning(f"[Drive Sync] File not found for cleanup: {local_path}")
                return False
            os.remove(local_path)
            logger.info(f"[Drive Sync] Cleaned up local raw video: {local_path}")
            return True
        except OSError as e:
            # 消せなくてもパイプラインは成立する。ディスクを食うだけなので警告に留める。
            logger.error(f"[Drive Sync] Failed to clean up {local_path}: {e}")
            return False


class WorkspacePipelineRunner:
    """Drive の未処理動画を1本取り、処理し、書き戻すループ。"""

    def __init__(
        self,
        sheets_store: GoogleSheetsStore,
        drive_store: GoogleDriveStore,
        local_pipeline_executor: Any,
    ):
        self.sheets_store = sheets_store
        self.drive_store = drive_store
        self.local_pipeline_executor = local_pipeline_executor

    def run_pipeline_for_next_video(self) -> bool:
        """未処理動画を1本処理する。

        Returns:
            True: 1本処理した / False: 対象が無かった、または失敗した。
        """
        videos = self.drive_store.list_input_raw_videos()
        if not videos:
            logger.info("[Pipeline Runner] No raw videos detected in Drive.")
            return False

        target_video = videos[0]
        file_id = target_video["id"]
        file_name = target_video["name"]
        task_id = f"task_{file_id}"

        logger.info(f"[Pipeline Runner] Starting pipeline for video: {file_name} ({file_id})")
        job_dir, dest_local_path, output_local_path = self._prepare_paths(task_id, file_name)
        remote_size = int(target_video.get("size") or 0)

        try:
            self._download_raw_video(task_id, file_id, file_name, dest_local_path, remote_size)
            output_local_path = self._execute_pipeline(task_id, dest_local_path, output_local_path)
            self._upload_and_complete(task_id, output_local_path)
            logger.info(f"[Pipeline Runner] Pipeline completed successfully for {file_name}")
            return True
        except Exception as e:  # noqa: BLE001 — ループの最上位。1本の失敗で運用を止めない
            logger.error(f"[Pipeline Runner] Pipeline failed: {e}")
            self._report_failure(task_id, e)
            return False
        finally:
            # 成否にかかわらず片付ける。残すとローカルが埋まり、次のジョブが
            # 容量チェックで弾かれる。
            self._cleanup_job_dir(job_dir, output_local_path)

    def _report_failure(self, task_id: str, error: Exception) -> None:
        """失敗をシートに書き戻す。

        書き戻し自体が失敗しても元の失敗を握り潰さない。Drive が落ちていれば
        Sheets も落ちている可能性が高く、そこで例外を上げると
        「元の失敗」がログから消える。
        """
        try:
            self.sheets_store.update_progress(task_id, -1, "FAILED", f"Error: {error}")
        except Exception as report_error:  # noqa: BLE001 — 記録の失敗で元の失敗を消さない
            logger.error(
                f"[Pipeline Runner] 失敗の記録にも失敗しました: {report_error} "
                f"(元の失敗: {error})"
            )

    def _prepare_paths(self, task_id: str, file_name: str) -> tuple[Path, Path, Path]:
        """ジョブ専用の作業ディレクトリを作る。

        以前は全ジョブが `temp_raw_videos/` を直接共有していたため、同名の
        RAW を扱うジョブ同士が上書きし合い、失敗時のゴミも誰の物か分からなく
        なっていた。ジョブごとに掘れば、片付けはディレクトリごと消すだけで済む。
        """
        job_dir = temp_raw_videos_dir() / task_id
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir, job_dir / file_name, job_dir / f"processed_{file_name}"

    def _download_raw_video(
        self,
        task_id: str,
        file_id: str,
        file_name: str,
        dest_local_path: Path,
        remote_size: int = 0,
    ) -> None:
        # ダウンロードを始める前に容量を見る。始めてしまうと、原本は落ちても
        # 中間ファイル生成の途中で力尽きる。そこで出る例外は容量が原因だと
        # 分かりにくく、切り分けに時間を取られる。
        if remote_size > 0:
            ensure_disk_space(dest_local_path.parent, remote_size * DISK_HEADROOM_FACTOR)

        self.sheets_store.update_progress(
            task_id, 0, "STARTING", f"Starting processing for {file_name}"
        )
        logger.info(f"[Pipeline Runner] Downloading {file_name}...")
        self.drive_store.download_file_chunked(file_id, dest_local_path)
        self.sheets_store.update_progress(
            task_id, 20, "DOWNLOADED", "Raw video downloaded locally"
        )

    def _execute_pipeline(
        self, task_id: str, dest_local_path: Path, output_local_path: Path
    ) -> Path:
        """ローカルのパイプラインを実行する。

        旧実装は成果物が無いとき `"processed_video_stub"` というテキストを
        書いて先へ進んでいた。そのまま Drive に上がると、中身がテキストの
        .mp4 が納品される。いまは成果物が無ければ失敗させる。
        """
        self.sheets_store.update_progress(task_id, 50, "PROCESSING", "Executing local pipeline")
        logger.info(f"[Pipeline Runner] Running executor on {dest_local_path}...")
        result_path = self.local_pipeline_executor(dest_local_path, output_local_path)
        if isinstance(result_path, (str, Path)) and str(result_path):
            output_local_path = Path(result_path)

        if not output_local_path.exists():
            raise WorkspaceSyncError(
                f"パイプラインが成果物を作りませんでした: {output_local_path}"
            )
        if output_local_path.stat().st_size == 0:
            raise WorkspaceSyncError(f"パイプラインの成果物が空です: {output_local_path}")
        return output_local_path

    def _upload_and_complete(self, task_id: str, output_local_path: Path) -> None:
        logger.info(f"[Pipeline Runner] Uploading processed video {output_local_path.name}...")
        upload_url = self.drive_store.upload_video(output_local_path)
        if not upload_url:
            raise WorkspaceSyncError("アップロードのリンクが得られませんでした")
        self.sheets_store.update_progress(
            task_id, 90, "UPLOADED", "Processed video uploaded to Drive"
        )
        self.sheets_store.update_progress(
            task_id, 100, "COMPLETED", f"Completed. Drive Link: {upload_url}"
        )

    def _cleanup_job_dir(self, job_dir: Path, output_local_path: Path | None = None) -> None:
        """ジョブの作業ディレクトリを丸ごと消す。

        `local_pipeline_executor` が作業ディレクトリ外のパスを返すことがあるため、
        その場合は個別に消してから本体を消す。片付けの失敗でジョブを失敗扱いに
        はしない（成果物は既に Drive にある）。警告だけ残す。
        """
        if output_local_path is not None and output_local_path.exists():
            try:
                outside = job_dir.resolve() not in output_local_path.resolve().parents
            except OSError:
                outside = False
            if outside:
                try:
                    os.remove(output_local_path)
                except OSError as e:
                    logger.warning(
                        f"[Pipeline Runner] Failed to remove local output file "
                        f"{output_local_path}: {e}"
                    )

        if job_dir.exists():
            try:
                shutil.rmtree(job_dir)
            except OSError as e:
                logger.warning(
                    f"[Pipeline Runner] Failed to remove job directory {job_dir}: {e}"
                )
