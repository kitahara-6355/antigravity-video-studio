"""

Safe File I/O Utilities — アトミック書き込みとスレッドセーフなJSON永続化



品質監査 DT-01 対応:

- tempfile + os.replace によるアトミック書き込み（書き込み中断によるデータ破損を防止）

- threading.Lock による並行リクエスト保護

- パス解決の統一（OP-01 対応: 共通 BASE_DIR 定義）

"""

import json

import copy

import os

import tempfile

import threading

import logging

from pathlib import Path

from typing import Any, Dict



logger = logging.getLogger(__name__)



# OP-01: 全モジュール共通の基準ディレクトリ

# backend/ の親ディレクトリ（video-automation/）を基準とする

BACKEND_DIR = Path(__file__).resolve().parent

PROJECT_ROOT = BACKEND_DIR.parent



# データディレクトリの定義

BRANDING_DIR = BACKEND_DIR / "branding"

# 保存先は ANTIGRAVITY_VAULT_OUTPUTS で差し替えられる。
# Drive のマウント先や CI の作業領域へ、参照元を直さずに移すための1点。
VAULT_OUTPUTS_DIR = Path(
    os.environ.get("ANTIGRAVITY_VAULT_OUTPUTS") or (PROJECT_ROOT / "vault-outputs")
)

ASSETS_DIR = PROJECT_ROOT / "assets"





class SafeJsonStore:
    """スレッドセーフなJSON永続化ストア。

    データ破損を防ぐためのアトミック書き込み、スレッド保護、および
    データ型バリデーションを提供します。

    Attributes:
        _path (Path): 永続化先のファイルパス。
        _default (Dict[str, Any]): ファイルが存在しない場合やエラー時のデフォルトデータ。
        _lock (threading.Lock): スレッドセーフティ用のロックオブジェクト。
    """

    def __init__(self, file_path: Path, default: Dict[str, Any] = None):
        """JSON永続化ストアを初期化します。

        Args:
            file_path (Path): 永続化先のJSONファイルパス。
            default (Dict[str, Any], optional): デフォルト値。辞書型である必要があります。

        Raises:
            TypeError: default が辞書型でない場合に発生します。
        """
        if default is not None and not isinstance(default, dict):
            raise TypeError("default must be a dictionary")
        self._path = Path(file_path)
        self._default = copy.deepcopy(default) if default is not None else {}
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        """ストアのファイルパスを取得します。

        Returns:
            Path: ストアのファイルパス。
        """
        return self._path

    def load(self) -> Dict[str, Any]:
        """スレッドセーフにJSONファイルを読み込みます。

        ファイルが存在しない場合、あるいは読み込みやパースでエラーが発生した場合は、
        デフォルト値のディープコピーを返します。

        Returns:
            Dict[str, Any]: 読み込まれたJSONデータ。
        """
        with self._lock:
            if not self._path.exists():
                return copy.deepcopy(self._default)
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    logger.error(f"❌ JSONファイルデータ型エラー: {self._path} は辞書ではありません。defaultを返します。")
                    return copy.deepcopy(self._default)
                return data
            except Exception as e:
                logger.error(f"❌ JSONファイル読み込みエラー: {self._path} - {type(e).__name__}: {e}")
                return copy.deepcopy(self._default)

    def save(self, data: Dict[str, Any]) -> None:
        """アトミック書き込みにより、データをスレッドセーフにJSONファイルへ保存します。

        書き込み途中でプロセスが中断しても、元のファイルは破損しません。

        Args:
            data (Dict[str, Any]): 保存するデータ。辞書型である必要があります。

        Raises:
            TypeError: data が辞書型でない場合に発生します。
        """
        if not isinstance(data, dict):
            raise TypeError("data must be a dictionary")
        with self._lock:
            self._save_unsafe(data)

    def update(self, updater_fn) -> Dict[str, Any]:
        """読み込み、更新、保存の全ステップをアトミック（排他的）に実行します。

        Args:
            updater_fn (callable): データを引数として受け取り、更新後のデータを返す（またはインプレースで更新する）関数。

        Returns:
            Dict[str, Any]: 更新後のデータ。
        """
        with self._lock:
            data = self._load_unsafe()
            result = updater_fn(data)
            if result is not None:
                data = result
            if not isinstance(data, dict):
                raise TypeError("updater_fn must return a dictionary")
            self._save_unsafe(data)
            return data

    def _load_unsafe(self) -> Dict[str, Any]:
        """ロックを掛けずにJSONファイルを読み込みます（内部処理用）。

        Returns:
            Dict[str, Any]: 読み込まれたJSONデータ。
        """
        if not self._path.exists():
            return copy.deepcopy(self._default)
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.error(f"❌ JSONファイルデータ型エラー (内部): {self._path} は辞書ではありません。defaultを返します。")
                return copy.deepcopy(self._default)
            return data
        except Exception as e:
            logger.error(f"❌ JSONファイル読み込みエラー (内部): {self._path} - {type(e).__name__}: {e}")
            return copy.deepcopy(self._default)

    def _save_unsafe(self, data: Dict[str, Any]) -> None:
        """ロックを掛けずにデータをJSONファイルへ保存します（内部処理用）。

        一時ファイルに書き出した後、アトミックにファイルを置換します。

        Args:
            data (Dict[str, Any]): 保存するデータ。

        Raises:
            TypeError: data が辞書型でない場合に発生します。
            OSError: ファイルシステムエラー時に発生します。
        """
        if not isinstance(data, dict):
            raise TypeError("data must be a dictionary")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._path.parent),
                suffix=".tmp",
                prefix=f".{self._path.stem}_"
            )
            try:
                try:
                    f = os.fdopen(fd, "w", encoding="utf-8")
                except (OSError, TypeError, ValueError):
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    raise

                try:
                    with f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    os.replace(tmp_path, str(self._path))
                except (OSError, TypeError, ValueError):
                    raise
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        except Exception as e:
            logger.error(f"❌ JSONファイル保存エラー: {self._path} - {type(e).__name__}: {e}")
            raise
