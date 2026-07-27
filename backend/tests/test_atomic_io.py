"""
atomic_io.py のユニットテスト
"""
import json
import os
import pytest
import tempfile
from unittest.mock import patch



# テスト対象のインポート
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents", "orchestration"))
from atomic_io import (
    atomic_write_json,
    safe_read_json,
    atomic_append_jsonl,
    safe_read_jsonl,
    FileLock,
)


@pytest.fixture
def tmp_dir():
    """テスト用一時ディレクトリ"""
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestAtomicWriteJson:
    """atomic_write_json のテスト"""

    def test_basic_write(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")
        data = {"key": "value", "number": 42}
        atomic_write_json(path, data)

        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)
        assert result == data

    def test_overwrites_existing(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")
        atomic_write_json(path, {"old": True})
        atomic_write_json(path, {"new": True})

        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)
        assert result == {"new": True}

    def test_creates_backup(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")
        atomic_write_json(path, {"version": 1})
        atomic_write_json(path, {"version": 2})

        bak_path = path + ".bak"
        assert os.path.exists(bak_path)
        with open(bak_path, "r", encoding="utf-8") as f:
            bak_data = json.load(f)
        assert bak_data == {"version": 1}

    def test_creates_directories(self, tmp_dir):
        path = os.path.join(tmp_dir, "sub", "dir", "test.json")
        atomic_write_json(path, {"nested": True})

        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)
        assert result == {"nested": True}

    def test_utf8_content(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")
        data = {"日本語": "テスト", "emoji": "🚀"}
        atomic_write_json(path, data)

        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)
        assert result == data

    def test_no_temp_file_on_success(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")
        atomic_write_json(path, {"clean": True})

        # 一時ファイルが残っていないことを確認
        files = os.listdir(tmp_dir)
        tmp_files = [f for f in files if f.endswith(".tmp")]
        assert len(tmp_files) == 0

    def test_backup_os_error(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")
        atomic_write_json(path, {"version": 1})

        # shutil.copy2 が OSError を投げるようにモックするが、書込み自体は成功する
        with patch("shutil.copy2", side_effect=OSError("Permission denied")):
            atomic_write_json(path, {"version": 2})

        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)
        assert result == {"version": 2}

    def test_write_failure_and_unlink_os_error(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")

        # json.dump が TypeError を投げ、かつ os.unlink も OSError を投げる状況を再現
        with patch("os.unlink", side_effect=OSError("File in use")):
            with pytest.raises(TypeError):
                atomic_write_json(path, {"unserializable": object()})

    def test_specific_exceptions_cleanup_and_reraise(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")

        # 1. TypeError (json.dumpで非シリアライズオブジェクト)
        with pytest.raises(TypeError):
            atomic_write_json(path, {"unserializable": object()})
        assert len([f for f in os.listdir(tmp_dir) if f.endswith(".tmp")]) == 0

        # 2. ValueError
        with patch("json.dump", side_effect=ValueError("Invalid value")):
            with pytest.raises(ValueError):
                atomic_write_json(path, {"val": 1})
        assert len([f for f in os.listdir(tmp_dir) if f.endswith(".tmp")]) == 0

        # 3. OSError
        with patch("os.fdopen", side_effect=OSError("Disk full")):
            with pytest.raises(OSError):
                atomic_write_json(path, {"val": 1})
        assert len([f for f in os.listdir(tmp_dir) if f.endswith(".tmp")]) == 0

    def test_unhandled_exception_does_not_cleanup(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")

        with patch("json.dump", side_effect=KeyboardInterrupt("User break")):
            with pytest.raises(KeyboardInterrupt):
                atomic_write_json(path, {"val": 1})
        
        # 一時ファイルが残っていることを確認
        tmp_files = [f for f in os.listdir(tmp_dir) if f.endswith(".tmp")]
        assert len(tmp_files) == 1

    def test_cleanup_close_os_error(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")
        original_close = os.close
        
        def mock_close(fd):
            mock_close.calls.append(fd)
            # 1回目の呼び出し（FileLock内）は通し、2回目（一時ファイルクリーンアップ）でOSErrorを投げる
            if len(mock_close.calls) > 1:
                raise OSError("Invalid file descriptor")
            original_close(fd)
            
        mock_close.calls = []
        
        with patch("os.close", side_effect=mock_close):
            with pytest.raises(TypeError):
                atomic_write_json(path, {"unserializable": object()})




class TestSafeReadJson:
    """safe_read_json のテスト"""

    def test_reads_valid_json(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")
        data = {"key": "value"}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        result = safe_read_json(path)
        assert result == data

    def test_returns_default_on_missing(self, tmp_dir):
        path = os.path.join(tmp_dir, "nonexistent.json")
        result = safe_read_json(path, default={"fallback": True})
        assert result == {"fallback": True}

    def test_returns_default_on_corrupt(self, tmp_dir):
        path = os.path.join(tmp_dir, "corrupt.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{broken json content")

        result = safe_read_json(path, default=[])
        assert result == []

    def test_recovers_from_backup(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")
        bak_path = path + ".bak"

        # 本体は壊れている
        with open(path, "w", encoding="utf-8") as f:
            f.write("corrupted!")

        # バックアップは正常
        with open(bak_path, "w", encoding="utf-8") as f:
            json.dump({"recovered": True}, f)

        result = safe_read_json(path)
        assert result == {"recovered": True}

    def test_returns_none_default(self, tmp_dir):
        path = os.path.join(tmp_dir, "nonexistent.json")
        result = safe_read_json(path)
        assert result is None

    def test_recover_from_backup_os_error(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")
        bak_path = path + ".bak"

        # 本体は壊れている
        with open(path, "w", encoding="utf-8") as f:
            f.write("corrupted!")

        # バックアップは正常
        with open(bak_path, "w", encoding="utf-8") as f:
            json.dump({"recovered": True}, f)

        # shutil.copy2 が OSError を投げるようにモックするが、バックアップデータの読込み自体は成功する
        with patch("shutil.copy2", side_effect=OSError("Read-only file system")):
            result = safe_read_json(path)
        
        assert result == {"recovered": True}

    def test_reads_null_json(self, tmp_dir):
        path = os.path.join(tmp_dir, "null.json")
        atomic_write_json(path, None)
        result = safe_read_json(path, default="fallback")
        assert result is None

    def test_returns_default_on_unicode_decode_error(self, tmp_dir):
        path = os.path.join(tmp_dir, "bad_encoding.json")
        # 不正なUTF-8シーケンスを書き込む
        with open(path, "wb") as f:
            f.write(b"\xff\xff\xff")
        
        result = safe_read_json(path, default={"fallback": True})
        assert result == {"fallback": True}

    def test_try_read_json_empty_range_fallthrough(self, tmp_dir):
        """_try_read_json 内の range(3) ループが空で即終了した場合に、
        ループ外の return False, None に到達して正しく False, None が返ること"""
        from atomic_io import _try_read_json
        path = os.path.join(tmp_dir, "empty_range.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"a": 1}, f)

        # range をモックして空のリストを返すようにする
        with patch("builtins.range", return_value=[]):
            success, result = _try_read_json(path)

        assert success is False
        assert result is None


class TestAtomicAppendJsonl:
    """atomic_append_jsonl のテスト"""

    def test_creates_new_file(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.jsonl")
        atomic_append_jsonl(path, {"entry": 1})

        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"entry": 1}

    def test_appends_to_existing(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.jsonl")
        atomic_append_jsonl(path, {"entry": 1})
        atomic_append_jsonl(path, {"entry": 2})

        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"entry": 1}
        assert json.loads(lines[1]) == {"entry": 2}

    def test_atomic_append_jsonl_exhaust_retries_raise_os_error(self, tmp_dir):
        """atomic_append_jsonl 中に OSError が3回連続で発生した場合、
        リトライ上限に達して OSError が呼び出し元に raise されること"""
        path = os.path.join(tmp_dir, "raise_append.jsonl")

        # 常に OSError を投げるように open をモック
        with patch("builtins.open", side_effect=OSError("Permanent lock issue")):
            with pytest.raises(OSError) as excinfo:
                atomic_append_jsonl(path, {"item": 1})
            
            assert "Permanent lock issue" in str(excinfo.value)


class TestSafeReadJsonl:
    """safe_read_jsonl のテスト"""

    def test_reads_valid_jsonl(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"a": 1}) + "\n")
            f.write(json.dumps({"b": 2}) + "\n")

        result = safe_read_jsonl(path)
        assert len(result) == 2
        assert result[0] == {"a": 1}
        assert result[1] == {"b": 2}

    def test_skips_corrupt_lines(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"good": 1}) + "\n")
            f.write("this is not json\n")
            f.write(json.dumps({"good": 2}) + "\n")

        result = safe_read_jsonl(path)
        assert len(result) == 2
        assert result[0] == {"good": 1}
        assert result[1] == {"good": 2}

    def test_returns_empty_on_missing(self, tmp_dir):
        path = os.path.join(tmp_dir, "nonexistent.jsonl")
        result = safe_read_jsonl(path)
        assert result == []

    def test_skips_blank_lines(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"a": 1}) + "\n")
            f.write("\n")
            f.write("  \n")
            f.write(json.dumps({"b": 2}) + "\n")

        result = safe_read_jsonl(path)
        assert len(result) == 2

    def test_read_jsonl_os_error(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.jsonl")
        # 存在チェックを通過させるためにファイルを作っておく
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"a": 1}) + "\n")

        original_open = open

        def mock_open(file, *args, **kwargs):
            if file == path:
                raise OSError("Permission denied")
            return original_open(file, *args, **kwargs)

        with patch("builtins.open", mock_open):
            result = safe_read_jsonl(path)

        assert result == []

    def test_read_jsonl_unicode_decode_error(self, tmp_dir):
        path = os.path.join(tmp_dir, "bad_encoding.jsonl")
        # 不正なUTF-8シーケンスを書き込む
        with open(path, "wb") as f:
            f.write(b"\xff\xff\xff\n")
            
        result = safe_read_jsonl(path)
        assert result == []


class TestFileLock:
    """FileLock のユニットテスト"""

    def test_basic_lock(self, tmp_dir):
        lock_path = os.path.join(tmp_dir, "test.lock")
        lock = FileLock(lock_path)
        assert not os.path.exists(lock_path)
        with lock:
            assert os.path.exists(lock_path)
        assert not os.path.exists(lock_path)

    def test_reentrancy(self, tmp_dir):
        lock_path = os.path.join(tmp_dir, "test.lock")
        lock1 = FileLock(lock_path)
        lock2 = FileLock(lock_path)

        with lock1:
            assert os.path.exists(lock_path)
            # 同じスレッドでの再入は成功するはず
            with lock2:
                assert os.path.exists(lock_path)
            assert os.path.exists(lock_path)
        assert not os.path.exists(lock_path)

    def test_timeout_and_block(self, tmp_dir):
        import threading
        import time
        lock_path = os.path.join(tmp_dir, "test.lock")
        
        lock_acquired = threading.Event()
        stop_thread = threading.Event()

        def hold_lock():
            with FileLock(lock_path):
                lock_acquired.set()
                stop_thread.wait()

        t = threading.Thread(target=hold_lock)
        t.start()
        
        # サブスレッドがロックを確保するのを待つ
        lock_acquired.wait(timeout=2.0)
        assert os.path.exists(lock_path)

        # 別のスレッド（メインスレッド）からロックを試みてタイムアウトすることを確認
        lock_fail = FileLock(lock_path, timeout=0.1, delay=0.01)
        with pytest.raises(TimeoutError):
            with lock_fail:
                pass

        # ロック解放してスレッド終了
        stop_thread.set()
        t.join(timeout=2.0)

    def test_zombie_lock_cleanup(self, tmp_dir):
        import time
        lock_path = os.path.join(tmp_dir, "test.lock")
        
        # 事前に古いロックファイルを作成しておく
        with open(lock_path, "w") as f:
            f.write("zombie")
        
        # 最終更新日時を過去に変更する (zombie_timeout = 0.1秒より古くする)
        past_time = time.time() - 100.0
        os.utime(lock_path, (past_time, past_time))
        
        # ゾンビロックが自動解放され、ロックが確保できること
        lock = FileLock(lock_path, timeout=0.5, zombie_timeout=0.1, delay=0.02)
        with lock:
            assert os.path.exists(lock_path)
            with open(lock_path, "r") as f:
                # O_CREAT | O_EXCL によって上書きされ、空ファイルになっているはず
                content = f.read()
                assert content == ""
        assert not os.path.exists(lock_path)

    def test_zombie_lock_permission_error(self, tmp_dir):
        import time
        lock_path = os.path.join(tmp_dir, "test.lock")
        # ゾンビファイルを用意
        with open(lock_path, "w") as f:
            f.write("zombie")
        past_time = time.time() - 100.0
        os.utime(lock_path, (past_time, past_time))

        # os.unlink が PermissionError を投げる場合
        with patch("os.unlink", side_effect=PermissionError("Locked file")):
            # 解放を試みるが削除できないため、タイムアウトすることを確認
            lock = FileLock(lock_path, timeout=0.1, zombie_timeout=0.1, delay=0.01)
            with pytest.raises(TimeoutError):
                with lock:
                    pass

    def test_os_error_handling(self, tmp_dir):
        # 存在しない親ディレクトリに対するロック試行で OSError が発生すること
        bad_lock_path = os.path.join(tmp_dir, "nonexistent_parent_dir", "test.lock")
        with patch("os.open", side_effect=OSError("Device error")):
            lock = FileLock(bad_lock_path, timeout=0.1)
            with pytest.raises(OSError):
                with lock:
                    pass



    def test_zombie_lock_immediate_cleanup(self, tmp_dir):
        """ゾンビロックがタイムアウトを待たずに、即座にクリーンアップされて取得できることを検証"""
        import time
        lock_path = os.path.join(tmp_dir, "test_immediate.lock")
        
        # 事前に古いロックファイルを作成しておく
        with open(lock_path, "w") as f:
            f.write("zombie")
        
        # 最終更新日時を過去に変更する (zombie_timeout = 0.1秒より古くする)
        past_time = time.time() - 100.0
        os.utime(lock_path, (past_time, past_time))
        
        # timeoutを長く（10秒）設定し、もしタイムアウト後にしかゾンビ解放されないなら
        # 10秒待たされるはずだが、各ループでチェックされるため
        # ほぼ一瞬（0.5秒未満）でロックが取得できるはず
        start_t = time.time()
        lock = FileLock(lock_path, timeout=10.0, zombie_timeout=0.1, delay=0.01)
        with lock:
            assert os.path.exists(lock_path)
        
        elapsed = time.time() - start_t
        # 少なくとも 1 秒未満で取得できていることをアサート（即時クリーンアップの証拠）
        assert elapsed < 1.0

    def test_try_read_json_os_error_retry(self, tmp_dir):
        """_try_read_json が OSError (共有違反など) 発生時に即時失敗せずリトライして成功すること"""
        from atomic_io import _try_read_json
        path = os.path.join(tmp_dir, "retry_read.json")
        data = {"success": True}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
            
        original_open = open
        open_calls = []
        
        def mock_open(file, mode="r", *args, **kwargs):
            open_calls.append(file)
            # 1回目は共有違反 (OSError) を投げ、2回目は普通に通す
            if len(open_calls) == 1 and file == path:
                raise OSError("Sharing violation")
            return original_open(file, mode, *args, **kwargs)
            
        with patch("builtins.open", side_effect=mock_open):
            success, result = _try_read_json(path)
            
        assert success is True
        assert result == data
        assert len(open_calls) == 2  # 2回呼び出されたことを確認

    def test_atomic_append_jsonl_os_error_retry(self, tmp_dir):
        """atomic_append_jsonl が OSError 時にリトライして最終的に書き込めること"""
        path = os.path.join(tmp_dir, "retry_append.jsonl")
        
        original_open = open
        open_calls = []
        
        def mock_open(file, mode="a", *args, **kwargs):
            open_calls.append(file)
            # 1回目は OSError を投げ、2回目は普通に通す
            if len(open_calls) == 1 and file == path:
                raise OSError("Lock sharing issue")
            return original_open(file, mode, *args, **kwargs)
            
        with patch("builtins.open", side_effect=mock_open):
            atomic_append_jsonl(path, {"item": 1})
            
        assert len(open_calls) == 2
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"item": 1}

    def test_zombie_lock_deleted_by_other_process_continue(self, tmp_dir):
        """ゾンビロック削除時に他プロセスに先を越されて FileNotFoundError が発生しても、
        ループが続行してロックを正常に取得できること"""
        import time
        lock_path = os.path.join(tmp_dir, "zombie_deleted.lock")
        
        # ゾンビファイルを用意
        with open(lock_path, "w") as f:
            f.write("zombie")
        past_time = time.time() - 100.0
        os.utime(lock_path, (past_time, past_time))

        original_unlink = os.unlink
        unlink_calls = []

        def mock_unlink(path):
            unlink_calls.append(path)
            if path == lock_path:
                if len(unlink_calls) == 1:
                    raise FileNotFoundError("Already deleted")
            original_unlink(path)

        lock = FileLock(lock_path, timeout=1.0, zombie_timeout=0.1, delay=0.01)
        with patch("os.unlink", side_effect=mock_unlink):
            with lock:
                assert os.path.exists(lock_path)
        assert not os.path.exists(lock_path)
        assert len(unlink_calls) >= 1

    def test_zombie_lock_stat_os_error_pass(self, tmp_dir):
        """ゾンビロック確認時に os.stat が OSError を投げても、
        正常に pass してタイムアウト処理などが行われること"""
        import time
        lock_path = os.path.join(tmp_dir, "zombie_stat_error.lock")
        
        # ゾンビファイルを用意
        with open(lock_path, "w") as f:
            f.write("zombie")

        # os.stat が OSError を投げるようにモック
        with patch("os.stat", side_effect=OSError("Permission denied or disk issue")):
            # timeout を短く設定し、ロック取得失敗により TimeoutError が発生することを確認
            lock = FileLock(lock_path, timeout=0.1, zombie_timeout=0.1, delay=0.01)
            with pytest.raises(TimeoutError):
                with lock:
                    pass
