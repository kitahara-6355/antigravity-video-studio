"""
アトミックファイルI/Oユーティリティ

共通処理機構（OrchestrationHub）で使用される状態ファイル（JSON/JSONL）の
安全な読み書きを提供する。

設計原則:
- 書込みは一時ファイル + os.replace() によるアトミック置換
- 読込みは例外安全（破損ファイルにはバックアップからフォールバック）
- UTF-8を強制（ファイルI/O安全規約準拠）
- O_CREAT | O_EXCL によるアトミックファイルロック（ロスト・アップデート防止）
"""

import json
import os
import shutil
import tempfile
import time
import random
import threading
from typing import Any, Optional


# スレッドローカルに保持しているロックのカウンターを管理
_thread_local_locks = threading.local()


class FileLock:
    """排他ファイルロック (O_CREAT | os.O_EXCL によるアトミック生成ロック、再入可能設計)"""
    def __init__(self, lock_path: str, timeout: float = 10.0, delay: float = 0.05, zombie_timeout: float = 30.0):
        self.lock_path = os.path.abspath(lock_path)
        self.timeout = timeout
        self.delay = delay
        self.zombie_timeout = zombie_timeout
        self.acquired = False

    def __enter__(self):
        if not hasattr(_thread_local_locks, "held"):
            _thread_local_locks.held = {}
            
        # すでにこのスレッドでロックを保持している場合は、カウンターをインクリメントして即座に終了 (再入許可)
        if self.lock_path in _thread_local_locks.held:
            _thread_local_locks.held[self.lock_path] += 1
            self.acquired = True
            return self

        start_time = time.time()
        dir_name = os.path.dirname(self.lock_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
            
        while True:
            try:
                # O_CREAT | O_EXCL はOSレベルでアトミックに動作する
                fd = os.open(self.lock_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
                os.close(fd)
                self.acquired = True
                _thread_local_locks.held[self.lock_path] = 1
                return self
            except (FileExistsError, PermissionError):
                # ゾンビロック（古い放置ロックファイル）の強制解放ガードを各ループで試行
                try:
                    st = os.stat(self.lock_path)
                    if time.time() - st.st_mtime > self.zombie_timeout:
                        try:
                            os.unlink(self.lock_path)
                            continue  # 削除成功時は即座に再試行
                        except FileNotFoundError:
                            continue
                        except PermissionError:
                            pass
                except OSError:
                    pass

                # タイムアウトチェック
                if time.time() - start_time > self.timeout:
                    raise TimeoutError(f"Could not acquire lock on {self.lock_path} within {self.timeout}s")
                
                # 指数バックオフ + ジッター待機
                sleep_time = random.uniform(self.delay, self.delay * 2)
                time.sleep(sleep_time)
            except OSError as e:
                # ディレクトリ未作成等のエラー対策
                raise e

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            if hasattr(_thread_local_locks, "held") and self.lock_path in _thread_local_locks.held:
                _thread_local_locks.held[self.lock_path] -= 1
                if _thread_local_locks.held[self.lock_path] <= 0:
                    del _thread_local_locks.held[self.lock_path]
                    try:
                        os.unlink(self.lock_path)
                    except OSError:
                        pass
            self.acquired = False


def _write_to_temp_file(fd: int, tmp_path: str, data: Any, indent: int) -> None:
    """一時ファイルディスクリプタにJSONデータを書き込み、永続化する。"""
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def _create_backup(path: str) -> None:
    """既存ファイルのバックアップを .bak として作成する。"""
    if os.path.exists(path):
        bak_path = path + ".bak"
        try:
            shutil.copy2(path, bak_path)
        except OSError:
            pass  # バックアップ失敗は致命的ではない


def _cleanup_temp_file(fd: int, tmp_path: str) -> None:
    """例外発生時に一時ファイルをクリーンアップする。"""
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(tmp_path)
    except OSError:
        pass


def atomic_write_json(path: str, data: Any, *, indent: int = 2) -> None:
    """
    JSONファイルをアトミックに書き込む。

    手順:
    1. 排他ファイルロックを取得
    2. 同一ディレクトリに一時ファイルを作成し、データを書き込む
    3. 既存ファイルがあれば .bak にバックアップ
    4. os.replace() で一時ファイルをターゲットにアトミック置換

    Args:
        path: 書込み先のファイルパス
        data: JSON化可能なデータ
        indent: JSONインデント幅
    """
    lock_path = path + ".lock"
    with FileLock(lock_path):
        dir_name = os.path.dirname(os.path.abspath(path))
        os.makedirs(dir_name, exist_ok=True)

        # 一時ファイルを同一ディレクトリに作成（クロスデバイスリネーム防止）
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix=os.path.basename(path) + ".",
            dir=dir_name,
        )
        try:
            _write_to_temp_file(fd, tmp_path, data, indent)
            _create_backup(path)
            os.replace(tmp_path, path)
        except (TypeError, ValueError, OSError):
            _cleanup_temp_file(fd, tmp_path)
            raise


def safe_read_json(path: str, default: Any = None) -> Any:
    """
    JSONファイルを安全に読み込む。

    読込み失敗時（ファイル不在、JSON破損）はバックアップ (.bak) を試行し、
    それも失敗した場合はデフォルト値を返す。

    Args:
        path: 読込み対象のファイルパス
        default: 読込み失敗時のデフォルト値

    Returns:
        読み込んだJSONデータ、またはデフォルト値
    """
    # 本体ファイルを試行
    success, data = _try_read_json(path)
    if success:
        return data

    # バックアップを試行
    bak_path = path + ".bak"
    bak_success, bak_data = _try_read_json(bak_path)
    if bak_success:
        # バックアップから復旧成功 — 本体を修復
        try:
            shutil.copy2(bak_path, path)
        except OSError:
            pass
        return bak_data

    return default


def _try_read_json(path: str) -> tuple[bool, Any]:
    """JSON読込みを試行し、(success, data) を返す。"""
    if not os.path.exists(path):
        return False, None
    for i in range(3):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return True, json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # OSError 全体をキャッチし、共有違反などの一時的エラーから安全に復旧させる
            if i < 2:
                time.sleep(random.uniform(0.01, 0.03))
                continue
            return False, None
    return False, None


def atomic_append_jsonl(path: str, entry: Any) -> None:
    """
    JSONLファイルの末尾に1エントリをアトミックに追記する。

    追記はファイルロック無しだが、1行の書込みはOSレベルで
    十分小さいため実用上は安全。flush + fsync で永続化を保証。

    Args:
        path: JSONL ファイルパス
        entry: JSON化可能な1エントリ
    """
    dir_name = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_name, exist_ok=True)

    line = json.dumps(entry, ensure_ascii=False) + "\n"
    
    # 共有違反などの一時的エラーを考慮してリトライを導入
    for i in range(3):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
                return
        except OSError as e:
            if i < 2:
                time.sleep(random.uniform(0.01, 0.03))
                continue
            raise e


def safe_read_jsonl(path: str) -> list:
    """
    JSONLファイルを安全に読み込む。

    各行を個別にパースし、破損行はスキップする。

    Args:
        path: JSONL ファイルパス

    Returns:
        パース成功したエントリのリスト
    """
    if not os.path.exists(path):
        return []

    entries = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # 破損行はスキップ
    except (OSError, UnicodeDecodeError):
        return []

    return entries
