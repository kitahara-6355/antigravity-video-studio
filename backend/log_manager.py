"""
ログマネージャー

推奨タスク P6.1: ログ連携
バックエンドログの取得とフロントエンド表示用API
"""

import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import deque
from dataclasses import dataclass, field
import json


@dataclass
class LogEntry:
    """ログエントリ"""
    timestamp: str
    level: str
    message: str
    source: str = "backend"
    extra: Dict[str, Any] = field(default_factory=dict)


class MemoryLogHandler(logging.Handler):
    """メモリ内ログハンドラー"""
    
    def __init__(self, max_entries: int = 1000):
        super().__init__()
        self.logs: deque = deque(maxlen=max_entries)
    
    def emit(self, record: logging.LogRecord):
        entry = LogEntry(
            timestamp=datetime.fromtimestamp(record.created).isoformat(),
            level=record.levelname,
            message=self.format(record),
            source=record.name,
            extra={
                "pathname": record.pathname,
                "lineno": record.lineno,
                "funcName": record.funcName,
            }
        )
        self.logs.append(entry)
    
    def get_logs(self, 
                 level: Optional[str] = None, 
                 source: Optional[str] = None,
                 limit: int = 100) -> List[Dict[str, Any]]:
        """ログ取得"""
        result = []
        for entry in reversed(self.logs):
            if level and entry.level != level.upper():
                continue
            if source and source not in entry.source:
                continue
            result.append({
                "timestamp": entry.timestamp,
                "level": entry.level,
                "message": entry.message,
                "source": entry.source,
            })
            if len(result) >= limit:
                break
        return result
    
    def clear(self):
        """ログクリア"""
        self.logs.clear()


# グローバルハンドラー
memory_handler = MemoryLogHandler(max_entries=1000)
memory_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
))


def setup_logging():
    """ロギング設定"""
    root_logger = logging.getLogger()
    root_logger.addHandler(memory_handler)
    root_logger.setLevel(logging.INFO)


# ファイルログ連携
logger = logging.getLogger(__name__)


class FileLogReader:
    """ファイルログ読み込み"""
    
    def __init__(self, log_dir: str = None):
        self.log_dir = log_dir or os.path.dirname(__file__)
    
    def read_log_file(self, filename: str, lines: int = 100) -> List[str]:
        """ログファイル読み込み"""
        if not filename or os.path.basename(filename) != filename or ".." in filename or "/" in filename or "\\" in filename:
            logger.warning(f"Invalid filename requested: {filename}")
            return [f"Error reading log: Invalid filename: {filename}"]

        if lines <= 0:
            logger.warning(f"Invalid lines count requested: {lines}")
            return [f"Error reading log: Invalid lines count: {lines}"]

        filepath = os.path.join(self.log_dir, filename)
        if not os.path.exists(filepath):
            return []
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
                return all_lines[-lines:]
        except FileNotFoundError as e:
            logger.warning(f"Log file not found: {filepath}", exc_info=True)
            return [f"Error reading log: File not found: {filename}"]
        except PermissionError as e:
            logger.error(f"Permission denied to read log file: {filepath}", exc_info=True)
            return [f"Error reading log: Permission denied: {filename}"]
        except OSError as e:
            logger.error(f"OS error reading log file: {filepath}", exc_info=True)
            return [f"Error reading log: {e}"]
    
    def list_log_files(self) -> List[Dict[str, Any]]:
        """ログファイル一覧"""
        result = []
        try:
            if not os.path.exists(self.log_dir):
                logger.warning(f"Log directory does not exist: {self.log_dir}")
                return []
            for f in os.listdir(self.log_dir):
                if f.endswith('.log') or f.endswith('.txt'):
                    filepath = os.path.join(self.log_dir, f)
                    try:
                        stat = os.stat(filepath)
                        result.append({
                            "name": f,
                            "size": stat.st_size,
                            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                        })
                    except FileNotFoundError:
                        # listdirの後にファイルが削除された場合などを許容
                        continue
                    except PermissionError as e:
                        logger.error(f"Permission denied for stat on file: {filepath}", exc_info=True)
                        continue
        except PermissionError as e:
            logger.error(f"Permission denied to list directory: {self.log_dir}", exc_info=True)
        except OSError as e:
            logger.error(f"OS error listing log files: {e}", exc_info=True)
        return sorted(result, key=lambda x: x['modified'], reverse=True)


file_log_reader = FileLogReader()


# FastAPI ルーター
from fastapi import APIRouter, Query, Path

router = APIRouter(prefix="/api/logs", tags=["Logs"])


@router.get("/memory")
async def get_memory_logs(
    level: Optional[str] = None, 
    source: Optional[str] = None, 
    limit: int = Query(100, ge=1, le=1000, description="取得するログ件数の上限")
):
    """メモリログ取得"""
    return {"logs": memory_handler.get_logs(level, source, limit)}


@router.get("/files")
async def list_log_files():
    """ログファイル一覧"""
    return {"files": file_log_reader.list_log_files()}


@router.get("/files/{filename}")
async def read_log_file(
    filename: str = Path(..., description="ログファイル名", pattern="^[a-zA-Z0-9_.-]+$"),
    lines: int = Query(100, ge=1, le=1000, description="読み込む行数")
):
    """ログファイル読み込み"""
    content = file_log_reader.read_log_file(filename, lines)
    return {"filename": filename, "lines": content}


@router.delete("/memory")
async def clear_memory_logs():
    """メモリログクリア"""
    memory_handler.clear()
    return {"status": "cleared"}
