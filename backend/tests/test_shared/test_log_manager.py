"""
log_manager.py のユニットテストおよびAPIテスト
"""

import sys
import os

# backend ディレクトリへのパスを追加
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_path = os.path.abspath(os.path.join(current_dir, "..", ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import logging
import time
from unittest.mock import patch, mock_open
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from log_manager import (
    LogEntry,
    MemoryLogHandler,
    FileLogReader,
    setup_logging,
    router,
    memory_handler
)


@pytest.fixture
def local_client():
    """ルーターテスト用のローカル FastAPI TestClient"""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_log_entry_creation():
    """LogEntry の初期化と属性の検証"""
    entry = LogEntry(
        timestamp="2026-05-23T12:00:00",
        level="INFO",
        message="Test message",
        source="backend",
        extra={"meta": "data"}
    )
    assert entry.timestamp == "2026-05-23T12:00:00"
    assert entry.level == "INFO"
    assert entry.message == "Test message"
    assert entry.source == "backend"
    assert entry.extra == {"meta": "data"}


def test_memory_log_handler_emit_and_get():
    """MemoryLogHandler の emit と get_logs の基本動作"""
    handler = MemoryLogHandler(max_entries=5)
    logger = logging.getLogger("test_emit_logger")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    logger.info("Info message")
    logger.error("Error message")
    logger.debug("Debug message")

    logs = handler.get_logs(limit=10)
    assert len(logs) == 3
    # reversed で返るため、最新がインデックス 0 になる
    assert logs[0]["message"] == "Debug message"
    assert logs[0]["level"] == "DEBUG"
    assert logs[1]["message"] == "Error message"
    assert logs[1]["level"] == "ERROR"
    assert logs[2]["message"] == "Info message"
    assert logs[2]["level"] == "INFO"

    # limit 制限による break (行66) のテスト
    limited_logs = handler.get_logs(limit=2)
    assert len(limited_logs) == 2
    assert limited_logs[0]["message"] == "Debug message"
    assert limited_logs[1]["message"] == "Error message"



def test_memory_log_handler_filtering():
    """MemoryLogHandler.get_logs におけるレベルおよびソースのフィルタリング"""
    handler = MemoryLogHandler(max_entries=10)
    
    # 異なる logger からログを出力してソースを区別する
    logger_a = logging.getLogger("logger_a")
    logger_a.addHandler(handler)
    logger_a.setLevel(logging.DEBUG)
    
    logger_b = logging.getLogger("logger_b")
    logger_b.addHandler(handler)
    logger_b.setLevel(logging.DEBUG)
    
    logger_a.info("Message from A")
    logger_b.error("Message from B")
    
    # 1. レベルによるフィルタ
    logs_error = handler.get_logs(level="ERROR")
    assert len(logs_error) == 1
    assert logs_error[0]["message"] == "Message from B"
    
    # 2. ソースによるフィルタ
    logs_source_a = handler.get_logs(source="logger_a")
    assert len(logs_source_a) == 1
    assert logs_source_a[0]["message"] == "Message from A"
    
    # 3. 一致しないフィルタ（continue パスを通す）
    logs_none = handler.get_logs(level="DEBUG")
    assert len(logs_none) == 0
    
    logs_no_source = handler.get_logs(source="non_existent")
    assert len(logs_no_source) == 0


def test_memory_log_handler_clear():
    """MemoryLogHandler.clear によるログの全削除"""
    handler = MemoryLogHandler(max_entries=5)
    logger = logging.getLogger("test_clear_logger")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    
    logger.info("Before clear")
    assert len(handler.get_logs()) == 1
    
    handler.clear()
    assert len(handler.get_logs()) == 0


def test_setup_logging():
    """setup_logging の実行とロガー設定の検証"""
    root_logger = logging.getLogger()
    initial_handlers = list(root_logger.handlers)
    initial_level = root_logger.level
    
    try:
        setup_logging()
        assert memory_handler in root_logger.handlers
        assert root_logger.level == logging.INFO
    finally:
        # 元の状態に復元
        if memory_handler not in initial_handlers:
            root_logger.removeHandler(memory_handler)
        root_logger.setLevel(initial_level)


def test_file_log_reader_read_success(tmp_path):
    """FileLogReader によるログファイル読み込みの成功ケース"""
    reader = FileLogReader(log_dir=str(tmp_path))
    filename = "app.log"
    filepath = tmp_path / filename
    
    lines = [f"Log line {i}\n" for i in range(15)]
    filepath.write_text("".join(lines), encoding="utf-8")
    
    # 指定行数読み込み (末尾から)
    read_lines = reader.read_log_file(filename, lines=5)
    assert len(read_lines) == 5
    assert read_lines == lines[-5:]


def test_file_log_reader_file_not_found(tmp_path):
    """FileLogReader でファイルが存在しない場合のエラーハンドリング"""
    reader = FileLogReader(log_dir=str(tmp_path))
    read_lines = reader.read_log_file("missing_file.log")
    assert read_lines == []


def test_file_log_reader_read_exception(tmp_path):
    """FileLogReader で読み込み時に例外が発生した場合のエラーハンドリング"""
    reader = FileLogReader(log_dir=str(tmp_path))
    filename = "error.log"
    filepath = tmp_path / filename
    filepath.write_text("some content", encoding="utf-8")
    
    # open 関数をモックして OSError を発生させる
    with patch("builtins.open", mock_open()) as mock_file:
        mock_file.side_effect = OSError("Simulated hardware error")
        read_lines = reader.read_log_file(filename)
        assert len(read_lines) == 1
        assert "Error reading log: Simulated hardware error" in read_lines[0]


def test_file_log_reader_list_files(tmp_path):
    """FileLogReader.list_log_files によるログファイル一覧取得とソートの検証"""
    reader = FileLogReader(log_dir=str(tmp_path))
    
    # 対象外のファイルと対象のファイルを作成
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")
    f1 = tmp_path / "app.log"
    f1.write_text("app log data", encoding="utf-8")
    f2 = tmp_path / "system.txt"
    f2.write_text("system log data", encoding="utf-8")
    
    # ファイルの更新時刻を変更してソート順を決定する
    now = time.time()
    os.utime(str(f1), (now - 10, now - 10))  # 古い
    os.utime(str(f2), (now, now))            # 新しい
    
    files = reader.list_log_files()
    
    assert len(files) == 2
    # 更新日時の降順なので system.txt が先頭
    assert files[0]["name"] == "system.txt"
    assert files[1]["name"] == "app.log"
    assert files[0]["size"] == len("system log data")
    assert "modified" in files[0]


def test_api_get_memory_logs(local_client):
    """GET /api/logs/memory エンドポイントの検証"""
    memory_handler.clear()
    
    # ロガーにハンドラーをセットしてログを出力
    logger = logging.getLogger("api_test_logger")
    if memory_handler not in logger.handlers:
        logger.addHandler(memory_handler)
    logger.setLevel(logging.INFO)
    logger.info("API info log")
    
    # GET リクエスト送信
    response = local_client.get("/api/logs/memory", params={"level": "INFO"})
    assert response.status_code == 200
    logs = response.json()["logs"]
    assert len(logs) == 1
    assert "API info log" in logs[0]["message"]


def test_api_list_log_files(local_client, tmp_path):
    """GET /api/logs/files エンドポイントの検証"""
    from log_manager import file_log_reader
    original_log_dir = file_log_reader.log_dir
    file_log_reader.log_dir = str(tmp_path)
    
    try:
        (tmp_path / "api.log").write_text("api file log", encoding="utf-8")
        
        response = local_client.get("/api/logs/files")
        assert response.status_code == 200
        files = response.json()["files"]
        assert len(files) == 1
        assert files[0]["name"] == "api.log"
    finally:
        file_log_reader.log_dir = original_log_dir


def test_api_read_log_file(local_client, tmp_path):
    """GET /api/logs/files/{filename} エンドポイントの検証"""
    from log_manager import file_log_reader
    original_log_dir = file_log_reader.log_dir
    file_log_reader.log_dir = str(tmp_path)
    
    try:
        (tmp_path / "read_api.log").write_text("Row 1\nRow 2\n", encoding="utf-8")
        
        response = local_client.get("/api/logs/files/read_api.log", params={"lines": 1})
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "read_api.log"
        assert data["lines"] == ["Row 2\n"]
    finally:
        file_log_reader.log_dir = original_log_dir


def test_api_clear_memory_logs(local_client):
    """DELETE /api/logs/memory エンドポイントの検証"""
    logger = logging.getLogger("api_clear_logger")
    if memory_handler not in logger.handlers:
        logger.addHandler(memory_handler)
    logger.setLevel(logging.INFO)
    logger.info("Log to be cleared")
    
    # ログが存在することを確認
    assert len(memory_handler.get_logs()) > 0
    
    # DELETE リクエスト送信
    response = local_client.delete("/api/logs/memory")
    assert response.status_code == 200
    assert response.json() == {"status": "cleared"}
    
    # ログが消去されたことを確認
    assert len(memory_handler.get_logs()) == 0


def test_sys_path_dynamic_resolution():
    """sys.path に追加された backend パスが正しく解決されているかの検証"""
    import sys
    import os
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    expected_backend_path = os.path.abspath(os.path.join(current_dir, "..", ".."))
    
    assert expected_backend_path in sys.path


def test_optional_arguments_handling():
    """Optional引数(level, source)が明示的にNoneの時に正常動作することの検証"""
    from log_manager import memory_handler
    # 正常にNoneを受け入れられることを確認
    logs = memory_handler.get_logs(level=None, source=None, limit=5)
    assert isinstance(logs, list)


def test_file_log_reader_read_file_not_found_handling(tmp_path):
    """FileLogReader で FileNotFoundError が発生した際のエラーハンドリングとログ出力"""
    reader = FileLogReader(log_dir=str(tmp_path))
    filename = "missing_log.log"
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=FileNotFoundError("Simulated file not found")), \
         patch("log_manager.logger.warning") as mock_warn:
        read_lines = reader.read_log_file(filename)
        assert len(read_lines) == 1
        assert "Error reading log: File not found: missing_log.log" in read_lines[0]
        mock_warn.assert_called_once()
        assert "Log file not found" in mock_warn.call_args[0][0]


def test_file_log_reader_read_permission_error_handling(tmp_path):
    """FileLogReader で PermissionError が発生した際のエラーハンドリングとログ出力"""
    reader = FileLogReader(log_dir=str(tmp_path))
    filename = "no_permission.log"
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=PermissionError("Permission denied")), \
         patch("log_manager.logger.error") as mock_error:
        read_lines = reader.read_log_file(filename)
        assert len(read_lines) == 1
        assert "Error reading log: Permission denied: no_permission.log" in read_lines[0]
        mock_error.assert_called_once()
        assert "Permission denied" in mock_error.call_args[0][0]


def test_file_log_reader_list_files_permission_error():
    """list_log_files で PermissionError が発生した際のハンドリング"""
    reader = FileLogReader(log_dir="/dummy/dir")
    with patch("os.path.exists", return_value=True), \
         patch("os.listdir", side_effect=PermissionError("Listing denied")), \
         patch("log_manager.logger.error") as mock_error:
        files = reader.list_log_files()
        assert files == []
        mock_error.assert_called_once()
        assert "Permission denied" in mock_error.call_args[0][0]


def test_file_log_reader_list_files_individual_stat_failure(tmp_path):
    """一部のファイルの os.stat が失敗した際、そのファイルをスキップして走査を継続することの検証"""
    reader = FileLogReader(log_dir=str(tmp_path))
    
    (tmp_path / "normal1.log").write_text("normal log 1", encoding="utf-8")
    (tmp_path / "failed.log").write_text("failed log", encoding="utf-8")
    (tmp_path / "normal2.txt").write_text("normal log 2", encoding="utf-8")
    
    original_stat = os.stat
    def mock_stat(path):
        if "failed.log" in str(path):
            raise PermissionError("Mock permission error")
        return original_stat(path)
        
    with patch("os.stat", side_effect=mock_stat), \
         patch("log_manager.logger.error") as mock_error:
        files = reader.list_log_files()
        assert len(files) == 2
        file_names = [f["name"] for f in files]
        assert "normal1.log" in file_names
        assert "normal2.txt" in file_names
        assert "failed.log" not in file_names
        mock_error.assert_called_once()


def test_file_log_reader_list_files_dir_not_exists():
    """list_log_files で log_dir が存在しない場合の挙動と警告ログの検証"""
    reader = FileLogReader(log_dir="/non/existent/directory/path")
    with patch("os.path.exists", return_value=False), \
         patch("log_manager.logger.warning") as mock_warn:
        files = reader.list_log_files()
        assert files == []
        mock_warn.assert_called_once()
        assert "Log directory does not exist" in mock_warn.call_args[0][0]


def test_file_log_reader_list_files_stat_file_not_found(tmp_path):
    """list_log_files で特定のファイルの os.stat が FileNotFoundError を投げた場合の continue 挙動の検証"""
    reader = FileLogReader(log_dir=str(tmp_path))
    (tmp_path / "normal.log").write_text("normal log", encoding="utf-8")
    
    with patch("os.stat", side_effect=FileNotFoundError("Simulated file deleted after listdir")):
        files = reader.list_log_files()
        # normal.log の stat で FileNotFoundError が発生するため、結果は空になるはず
        assert files == []


def test_file_log_reader_list_files_os_error():
    """list_log_files 内で OSError が発生した場合のハンドリングとログ出力"""
    reader = FileLogReader(log_dir="/dummy/dir")
    with patch("os.path.exists", return_value=True), \
         patch("os.listdir", side_effect=OSError("Disk failure")), \
         patch("log_manager.logger.error") as mock_error:
        files = reader.list_log_files()
        assert files == []
        mock_error.assert_called_once()
        assert "OS error listing log files" in mock_error.call_args[0][0]


def test_file_log_reader_invalid_filename_validation(tmp_path):
    """FileLogReader.read_log_file で不正なファイル名が指定された場合のバリデーション検証"""
    reader = FileLogReader(log_dir=str(tmp_path))
    
    # パス・トラバーサルのケース
    assert reader.read_log_file("../etc/passwd") == ["Error reading log: Invalid filename: ../etc/passwd"]
    assert reader.read_log_file("sub/app.log") == ["Error reading log: Invalid filename: sub/app.log"]
    assert reader.read_log_file("") == ["Error reading log: Invalid filename: "]
    assert reader.read_log_file("..\\app.log") == ["Error reading log: Invalid filename: ..\\app.log"]

    # 負の行数指定のケース
    assert reader.read_log_file("app.log", lines=0) == ["Error reading log: Invalid lines count: 0"]
    assert reader.read_log_file("app.log", lines=-5) == ["Error reading log: Invalid lines count: -5"]


def test_api_get_memory_logs_validation_error(local_client):
    """GET /api/logs/memory における limit パラメータのバリデーション検証"""
    # limit=0 (ge=1 に反する)
    response = local_client.get("/api/logs/memory", params={"limit": 0})
    assert response.status_code == 422
    
    # limit=1001 (le=1000 に反する)
    response = local_client.get("/api/logs/memory", params={"limit": 1001})
    assert response.status_code == 422
    
    # 正常値
    response = local_client.get("/api/logs/memory", params={"limit": 5})
    assert response.status_code == 200


def test_api_read_log_file_validation_error(local_client, tmp_path):
    """GET /api/logs/files/{filename} におけるバリデーション検証"""
    from log_manager import file_log_reader
    original_log_dir = file_log_reader.log_dir
    file_log_reader.log_dir = str(tmp_path)
    
    try:
        # 1. 正常なファイル名の作成と読み込み
        (tmp_path / "valid.log").write_text("valid log line", encoding="utf-8")
        response = local_client.get("/api/logs/files/valid.log", params={"lines": 1})
        assert response.status_code == 200
        
        # 2. lines が 0 以下の場合は 422 になる
        response = local_client.get("/api/logs/files/valid.log", params={"lines": 0})
        assert response.status_code == 422
        
        # 3. lines が 1001 以上の場合は 422 になる
        response = local_client.get("/api/logs/files/valid.log", params={"lines": 1001})
        assert response.status_code == 422

        # 4. filename パターンに反する文字が含まれる場合は 422 になる
        # (pattern="^[a-zA-Z0-9_.-]+$")
        response = local_client.get("/api/logs/files/invalid@file.log")
        assert response.status_code == 422
        
        response = local_client.get("/api/logs/files/invalid%20file.log")
        assert response.status_code == 422

    finally:
        file_log_reader.log_dir = original_log_dir

