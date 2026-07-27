"""
Unit tests for backend/utils/json_safe_io.py
"""
import sys
import json
import logging
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from filelock import FileLock, Timeout

# Add backend to path if needed
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.json_safe_io import safe_load_json, safe_save_json, _LOCK_TIMEOUT

def test_safe_load_json_success(tmp_path):
    """正常系: 存在するJSONファイルを正しく読み込めること"""
    test_file = tmp_path / "test.json"
    data = {"key": "value", "number": 42}
    
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
        
    result = safe_load_json(test_file)
    assert result == data

def test_safe_load_json_nonexistent(tmp_path):
    """異常系: 存在しないファイルを読み込もうとした場合、空辞書を返すこと"""
    test_file = tmp_path / "nonexistent.json"
    
    result = safe_load_json(test_file)
    assert result == {}

def test_safe_load_json_decode_error(tmp_path, caplog):
    """異常系: JSONの形式が不正な場合、JSONDecodeErrorを補足して警告ログを吐き、空辞書を返すこと"""
    test_file = tmp_path / "invalid.json"
    test_file.write_text("invalid json format", encoding="utf-8")
    
    with caplog.at_level(logging.WARNING):
        result = safe_load_json(test_file)
        
    assert result == {}
    assert len(caplog.records) == 1
    assert "[json_safe_io] JSON" in caplog.text

def test_safe_load_json_os_error(tmp_path, caplog):
    """異常系: OSErrorが発生した場合、例外を補足して警告ログを吐き、空辞書を返すこと"""
    test_file = tmp_path / "unreadable.json"
    test_file.write_text("{}", encoding="utf-8")
    
    # open関数でOSErrorを発生させる
    with patch("builtins.open", side_effect=OSError("Read permission denied")):
        with caplog.at_level(logging.WARNING):
            result = safe_load_json(test_file)
            
    assert result == {}
    assert len(caplog.records) == 1
    assert "[json_safe_io] JSON" in caplog.text
    assert "Read permission denied" in caplog.text

def test_safe_load_json_lock_creation(tmp_path):
    """filelockの作成とロック獲得を検証"""
    test_file = tmp_path / "lock_test.json"
    test_file.write_text("{}", encoding="utf-8")
    
    with patch("utils.json_safe_io.FileLock") as mock_filelock:
        mock_lock_instance = MagicMock()
        mock_filelock.return_value = mock_lock_instance
        
        safe_load_json(test_file)
        
        # lockのコンストラクタが正しいパスとタイムアウトで呼ばれたか確認
        mock_filelock.assert_called_once_with(str(test_file) + ".lock", timeout=_LOCK_TIMEOUT)
        # lockオブジェクト of context managerが呼ばれたか確認
        mock_lock_instance.__enter__.assert_called_once()
        mock_lock_instance.__exit__.assert_called_once()

def test_safe_save_json_success(tmp_path):
    """正常系: データを指定されたパスに正しく保存でき、必要なら親ディレクトリも作成されること"""
    # ネストされたパスを指定してディレクトリ自動生成もテストする
    test_file = tmp_path / "sub_dir" / "save_test.json"
    data = {"hello": "world", "nested": {"list": [1, 2, 3]}}
    
    safe_save_json(test_file, data)
    
    # 保存されたファイルの存在と内容確認
    assert test_file.exists()
    with open(test_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data == data

def test_safe_save_json_lock_creation(tmp_path):
    """safe_save_jsonでfilelockが正しく使用されることの検証"""
    test_file = tmp_path / "save_lock.json"
    data = {"a": 1}
    
    with patch("utils.json_safe_io.FileLock") as mock_filelock:
        mock_lock_instance = MagicMock()
        mock_filelock.return_value = mock_lock_instance
        
        safe_save_json(test_file, data)
        
        # lockのコンストラクタが正しいパスとタイムアウトで呼ばれたか確認
        mock_filelock.assert_called_once_with(str(test_file) + ".lock", timeout=_LOCK_TIMEOUT)
        # lockオブジェクト of context managerが呼ばれたか確認
        mock_lock_instance.__enter__.assert_called_once()
        mock_lock_instance.__exit__.assert_called_once()


def test_safe_load_json_lock_timeout(tmp_path, caplog):
    """異常系: ロック獲得がタイムアウトした場合、警告ログを吐き、空辞書を返すこと"""
    test_file = tmp_path / "timeout_load.json"
    test_file.write_text("{}", encoding="utf-8")
    
    # 外部の代わりに、手動でロックを取得しておく
    lock_file = str(test_file) + ".lock"
    external_lock = FileLock(lock_file)
    
    # 短いタイムアウトでテストできるように_LOCK_TIMEOUTを一時的にパッチ
    with external_lock:
        with patch("utils.json_safe_io._LOCK_TIMEOUT", 0.1):
            with caplog.at_level(logging.WARNING):
                result = safe_load_json(test_file)
                
    assert result == {}
    assert len(caplog.records) == 1
    assert "[json_safe_io] ロックタイムアウト" in caplog.text


def test_safe_save_json_lock_timeout(tmp_path, caplog):
    """異常系: 保存時にロック獲得がタイムアウトした場合、エラーログを吐き、Timeout例外を再スローすること"""
    test_file = tmp_path / "timeout_save.json"
    lock_file = str(test_file) + ".lock"
    external_lock = FileLock(lock_file)
    
    with external_lock:
        with patch("utils.json_safe_io._LOCK_TIMEOUT", 0.1):
            with caplog.at_level(logging.ERROR):
                with pytest.raises(Timeout):
                    safe_save_json(test_file, {"data": "fail"})
                    
    assert len(caplog.records) == 1
    assert "[json_safe_io] ロックタイムアウト" in caplog.text


def test_safe_save_json_os_error(tmp_path, caplog):
    """異常系: 保存時にOSErrorが発生した場合、エラーログを出力して例外を再スローすること"""
    test_file = tmp_path / "os_error_save.json"
    
    with patch("os.fdopen", side_effect=OSError("Write permission denied")):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(OSError, match="Write permission denied"):
                safe_save_json(test_file, {"test": "data"})
                
    assert len(caplog.records) == 1
    assert "[json_safe_io] JSON保存失敗" in caplog.text


def test_safe_save_json_type_error(tmp_path, caplog):
    """異常系: 保存データがシリアライズ不可能な型の場合、エラーログを出力してTypeErrorを再スローすること"""
    test_file = tmp_path / "type_error_save.json"
    invalid_data = {"set_data": {1, 2, 3}}  # setはJSONシリアライズ不可
    
    with caplog.at_level(logging.ERROR):
        with pytest.raises(TypeError):
            safe_save_json(test_file, invalid_data)
            
    assert len(caplog.records) == 1
    assert "[json_safe_io] JSONシリアライズ失敗" in caplog.text


def test_safe_save_json_preserves_existing_file_on_error(tmp_path):
    """異常系: 保存中にエラーが発生した場合、既存のファイルデータが破損せず保護されること"""
    test_file = tmp_path / "existing_data.json"
    original_data = {"status": "ok", "version": 1}
    
    # あらかじめ有効なJSONデータを書き込んでおく
    safe_save_json(test_file, original_data)
    assert test_file.exists()
    
    # シリアライズ不可能な無効データを書き込もうとする
    invalid_data = {"invalid_set": {1, 2, 3}}
    with pytest.raises(TypeError):
        safe_save_json(test_file, invalid_data)
        
    # エラー発生後も、元のデータが変更されずに残っていることを確認する
    with open(test_file, "r", encoding="utf-8") as f:
        loaded_data = json.load(f)
    assert loaded_data == original_data


def test_safe_save_json_various_types(tmp_path):
    """正常系: 辞書以外のシリアライズ可能なデータ型（リスト、文字列など）も保存できること"""
    test_file = tmp_path / "types.json"
    
    # リスト
    list_data = [1, "two", {"three": 3}]
    safe_save_json(test_file, list_data)
    assert safe_load_json(test_file) == list_data
    
    # 文字列
    string_data = "plain_string"
    safe_save_json(test_file, string_data)
    assert safe_load_json(test_file) == string_data



def test_safe_io_invalid_path_type():
    """異常系: Path以外の型（文字列など）を渡した場合、適切な例外（AttributeError）が発生すること"""
    with pytest.raises(AttributeError):
        safe_save_json("invalid_path_str", {"key": "value"})
        
    with pytest.raises(AttributeError):
        safe_load_json("invalid_path_str")


def test_safe_io_concurrent_writes(tmp_path):
    """正常系: 複数スレッドからの同時書き込みがファイルロックによって保護され、破損しないこと"""
    import threading
    import time
    
    test_file = tmp_path / "concurrent.json"
    num_threads = 5
    iterations = 20
    
    # 初期データ
    safe_save_json(test_file, {"count": 0})
    
    errors = []
    
    def worker():
        try:
            for _ in range(iterations):
                # 読み込んでインクリメントして保存
                # 完全に Lost Update を防ぐわけではないが、JSONファイルが破損したり例外が出ないことを保証する
                data = safe_load_json(test_file)
                count = data.get("count", 0)
                data["count"] = count + 1
                time.sleep(0.01)
                safe_save_json(test_file, data)
        except Exception as e:
            errors.append(e)
            
    threads = []
    for _ in range(num_threads):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    assert not errors, f"Concurrent writes threw errors: {errors}"
    
    final_data = safe_load_json(test_file)
    assert isinstance(final_data, dict)
    assert "count" in final_data


def test_safe_save_json_os_remove_error_on_cleanup(tmp_path):
    """異常系: 保存時のクリーンアップ処理において、一時ファイルの削除(os.remove)自体がOSErrorを投げた場合、
    それを無視して元の例外(TypeError/OSError)を再スローすること"""
    test_file = tmp_path / "cleanup_fail.json"
    
    # 意図的にTypeErrorを発生させるためにシリアライズ不可なデータを使用
    invalid_data = {"set_data": {1, 2, 3}}
    
    with patch("os.remove", side_effect=OSError("Remove failed")):
        with pytest.raises(TypeError):
            safe_save_json(test_file, invalid_data)

