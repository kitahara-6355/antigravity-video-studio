"""
json_safe_io — filelock付きJSON読み書きユーティリティ

Sprint 4.2.4 C-05: evolution_log.json同時書込のファイルロック

複数サービス(EvolutionTriggerService, PhilosophyProposalService,
EvolutionSyncService, pipeline_router)から同時に読み書きされる
evolution_log.jsonの排他制御を提供する。

使用ライブラリ: filelock (PyPI, 年間1億DL超の定番)
"""
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict

from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)

# filelock タイムアウト (秒)
_LOCK_TIMEOUT = 10


def safe_load_json(path: Path) -> dict:
    """filelock付きJSONロード

    Args:
        path: JSONファイルのパス

    Returns:
        パースされた辞書。ファイルが存在しない or パース失敗時は空辞書
    """
    lock = FileLock(str(path) + ".lock", timeout=_LOCK_TIMEOUT)
    try:
        with lock:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, OSError, TypeError, ValueError) as e:
                    logger.warning(f"[json_safe_io] JSON読込失敗: {path} — {e}")
    except Timeout as e:
        logger.warning(f"[json_safe_io] ロックタイムアウト（ロード失敗）: {path} — {e}")
    return {}


def safe_save_json(path: Path, data: dict) -> None:
    """filelock付きJSON保存 (一時ファイルを用いたアトミック書き込み)

    Args:
        path: JSONファイルのパス
        data: 保存する辞書データ
    """
    lock = FileLock(str(path) + ".lock", timeout=_LOCK_TIMEOUT)
    try:
        with lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path_str = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".tmp_")
            tmp_path = Path(tmp_path_str)
            try:
                try:
                    f = os.fdopen(tmp_fd, "w", encoding="utf-8")
                except (OSError, ValueError, TypeError):
                    os.close(tmp_fd)
                    raise
                
                with f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, path)
            except (OSError, TypeError, ValueError) as e:
                if tmp_path.exists():
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                
                if isinstance(e, TypeError):
                    logger.error(f"[json_safe_io] JSONシリアライズ失敗: {path} — {e}")
                else:
                    logger.error(f"[json_safe_io] JSON保存失敗: {path} — {e}")
                raise
    except Timeout as e:
        logger.error(f"[json_safe_io] ロックタイムアウト（保存失敗）: {path} — {e}")
        raise
