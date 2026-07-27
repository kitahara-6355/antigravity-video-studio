"""
Unit tests for backend/safe_io.py
"""
import sys
import os
import json
import pytest
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from safe_io import SafeJsonStore

def test_safe_json_store_init(tmp_path):
    file_path = tmp_path / "test.json"
    default_data = {"key": "value"}
    store = SafeJsonStore(file_path, default=default_data)
    assert store.path == file_path
    assert store._default == default_data

def test_safe_json_store_load_default(tmp_path):
    file_path = tmp_path / "nonexistent.json"
    default_data = {"key": "value"}
    store = SafeJsonStore(file_path, default=default_data)
    # Returns default copy if file does not exist
    loaded = store.load()
    assert loaded == default_data
    assert loaded is not default_data

def test_safe_json_store_load_existing(tmp_path):
    file_path = tmp_path / "test.json"
    data = {"hello": "world"}
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    
    store = SafeJsonStore(file_path)
    loaded = store.load()
    assert loaded == data

def test_safe_json_store_load_json_decode_error(tmp_path):
    file_path = tmp_path / "invalid.json"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("invalid json string")
    
    default_data = {"key": "value"}
    store = SafeJsonStore(file_path, default=default_data)
    
    # Returns default copy if JSONDecodeError occurs
    loaded = store.load()
    assert loaded == default_data

def test_safe_json_store_load_os_error(tmp_path):
    file_path = tmp_path / "unreadable.json"
    default_data = {"key": "value"}
    store = SafeJsonStore(file_path, default=default_data)
    
    # Mock open to raise OSError
    with patch("builtins.open", side_effect=OSError("Read error")):
        loaded = store.load()
        assert loaded == default_data

def test_safe_json_store_save_basic(tmp_path):
    file_path = tmp_path / "test.json"
    store = SafeJsonStore(file_path)
    data = {"saved": "data"}
    store.save(data)
    
    assert file_path.exists()
    with open(file_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data

def test_safe_json_store_save_exception_removes_tmp(tmp_path):
    file_path = tmp_path / "test.json"
    store = SafeJsonStore(file_path)
    data = {"saved": "data"}
    
    # Raise exception during os.replace
    with patch("os.replace", side_effect=OSError("Atomic replace failed")):
        with pytest.raises(OSError, match="Atomic replace failed"):
            store.save(data)
        
        # Verify temporary files are cleaned up
        files = list(tmp_path.glob("*.tmp"))
        assert len(files) == 0

def test_safe_json_store_save_exception_in_outer_try(tmp_path):
    file_path = tmp_path / "test.json"
    store = SafeJsonStore(file_path)
    data = {"saved": "data"}
    
    # Raise exception during tempfile.mkstemp
    with patch("tempfile.mkstemp", side_effect=Exception("Tempfile creation failed")):
        with pytest.raises(Exception, match="Tempfile creation failed"):
            store.save(data)

def test_safe_json_store_update_basic(tmp_path):
    file_path = tmp_path / "test.json"
    default_data = {"count": 1}
    store = SafeJsonStore(file_path, default=default_data)
    
    def updater(data):
        data["count"] += 1
        return data

    updated = store.update(updater)
    assert updated == {"count": 2}
    
    loaded = store.load()
    assert loaded == {"count": 2}

def test_safe_json_store_update_returns_none(tmp_path):
    file_path = tmp_path / "test.json"
    default_data = {"items": []}
    store = SafeJsonStore(file_path, default=default_data)
    
    def updater(data):
        data["items"].append("item1")
        return None

    updated = store.update(updater)
    assert updated == {"items": ["item1"]}
    assert store.load() == {"items": ["item1"]}

def test_safe_json_store_unsafe_load_json_decode_error(tmp_path):
    file_path = tmp_path / "invalid_unsafe.json"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("{invalid}")
    
    default_data = {"default": True}
    store = SafeJsonStore(file_path, default=default_data)
    
    result = store.update(lambda data: data)
    assert result == default_data

def test_safe_json_store_unsafe_load_os_error(tmp_path):
    file_path = tmp_path / "unreadable_unsafe.json"
    file_path.write_text("{}", encoding="utf-8")
    store = SafeJsonStore(file_path, default={"default": True})
    
    with patch("builtins.open", side_effect=OSError("Read error")):
        result = store.update(lambda data: data)
        assert result == {"default": True}

def test_safe_json_store_unsafe_save_exception_removes_tmp(tmp_path):
    file_path = tmp_path / "test.json"
    store = SafeJsonStore(file_path)
    
    # Raise exception during os.replace
    with patch("os.replace", side_effect=OSError("Unsafe replace failed")):
        with pytest.raises(OSError, match="Unsafe replace failed"):
            store.update(lambda data: {"test": 1})
            
        files = list(tmp_path.glob("*.tmp"))
        assert len(files) == 0

def test_safe_json_store_concurrency(tmp_path):
    file_path = tmp_path / "concurrent.json"
    store = SafeJsonStore(file_path, default={"count": 0})
    
    num_threads = 10
    num_increments = 50
    
    def worker():
        for _ in range(num_increments):
            store.update(lambda data: {"count": data["count"] + 1})
            
    threads = []
    for _ in range(num_threads):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    assert store.load()["count"] == num_threads * num_increments

def test_safe_json_store_save_fd_leak_prevention(tmp_path):
    file_path = tmp_path / "test_leak.json"
    store = SafeJsonStore(file_path)
    data = {"test": 1}

    mock_fdopen = MagicMock(side_effect=OSError("fdopen failed"))
    
    with patch("os.fdopen", mock_fdopen), patch("os.close", wraps=os.close) as mock_close:
        with pytest.raises(OSError, match="fdopen failed"):
            store.save(data)
        
        assert mock_close.called
        files = list(tmp_path.glob("*.tmp"))
        assert len(files) == 0

def test_safe_json_store_unsafe_save_fd_leak_prevention(tmp_path):
    file_path = tmp_path / "test_unsafe_leak.json"
    store = SafeJsonStore(file_path)
    
    mock_fdopen = MagicMock(side_effect=OSError("fdopen failed"))
    
    with patch("os.fdopen", mock_fdopen), patch("os.close", wraps=os.close) as mock_close:
        with pytest.raises(OSError, match="fdopen failed"):
            store.update(lambda data: {"test": 1})
            
        assert mock_close.called
        files = list(tmp_path.glob("*.tmp"))
        assert len(files) == 0

def test_safe_json_store_save_os_close_error(tmp_path):
    file_path = tmp_path / "test_close_error.json"
    store = SafeJsonStore(file_path)
    data = {"test": 1}

    mock_fdopen = MagicMock(side_effect=OSError("fdopen failed"))
    
    original_close = os.close
    def side_effect(fd):
        try:
            original_close(fd)
        finally:
            raise OSError("close failed")
            
    mock_close = MagicMock(side_effect=side_effect)
    
    with patch("os.fdopen", mock_fdopen), patch("os.close", mock_close):
        with pytest.raises(OSError, match="fdopen failed"):
            store.save(data)
        
        assert mock_close.called
        files = list(tmp_path.glob("*.tmp"))
        assert len(files) == 0

def test_safe_json_store_unsafe_save_os_close_error(tmp_path):
    file_path = tmp_path / "test_unsafe_close_error.json"
    store = SafeJsonStore(file_path)
    
    mock_fdopen = MagicMock(side_effect=OSError("fdopen failed"))
    
    original_close = os.close
    def side_effect(fd):
        try:
            original_close(fd)
        finally:
            raise OSError("close failed")
            
    mock_close = MagicMock(side_effect=side_effect)
    
    with patch("os.fdopen", mock_fdopen), patch("os.close", mock_close):
        with pytest.raises(OSError, match="fdopen failed"):
            store.update(lambda data: {"test": 1})
            
        assert mock_close.called
        files = list(tmp_path.glob("*.tmp"))
        assert len(files) == 0


def test_safe_json_store_save_json_dump_exception_removes_tmp(tmp_path):
    file_path = tmp_path / "test.json"
    store = SafeJsonStore(file_path)
    # json.dump will raise TypeError because set is not JSON serializable
    data = {"invalid_set": {1, 2, 3}}
    
    with pytest.raises(TypeError):
        store.save(data)
        
    # Verify temporary files are cleaned up
    files = list(tmp_path.glob("*.tmp"))
    assert len(files) == 0

def test_safe_json_store_unsafe_save_json_dump_exception_removes_tmp(tmp_path):
    file_path = tmp_path / "test.json"
    store = SafeJsonStore(file_path)
    
    with pytest.raises(TypeError):
        store.update(lambda data: {"invalid_set": {1, 2, 3}})
        
    # Verify temporary files are cleaned up
    files = list(tmp_path.glob("*.tmp"))
    assert len(files) == 0


def test_safe_json_store_save_fdopen_exception_closes_fd_strict(tmp_path):
    file_path = tmp_path / "test_strict.json"
    store = SafeJsonStore(file_path)
    data = {"test": 1}

    with patch("os.fdopen", side_effect=OSError("fdopen failed")), patch("os.close", wraps=os.close) as mock_close:
        with pytest.raises(OSError, match="fdopen failed"):
            store.save(data)
        assert mock_close.called

def test_safe_json_store_unsafe_save_fdopen_exception_closes_fd_strict(tmp_path):
    file_path = tmp_path / "test_unsafe_strict.json"
    store = SafeJsonStore(file_path)

    with patch("os.fdopen", side_effect=OSError("fdopen failed")), patch("os.close", wraps=os.close) as mock_close:
        with pytest.raises(OSError, match="fdopen failed"):
            store.update(lambda data: {"test": 1})
        assert mock_close.called

def test_safe_json_store_save_any_exception_inside_with_closes_fd(tmp_path):
    file_path = tmp_path / "test_any.json"
    store = SafeJsonStore(file_path)
    
    with patch("json.dump", side_effect=KeyError("any key error")):
        with pytest.raises(KeyError, match="any key error"):
            store.save({"test": 1})
            
    files = list(tmp_path.glob("*.tmp"))
    assert len(files) == 0


def test_safe_json_store_default_mutation(tmp_path):
    file_path = tmp_path / "nonexistent.json"
    default_data = {"nested": {"key": "value"}}
    store = SafeJsonStore(file_path, default=default_data)
    
    # 1回目の読み込みで取得したデータを変更
    loaded1 = store.load()
    loaded1["nested"]["key"] = "mutated"
    
    # 2回目の読み込みで、デフォルト値が汚染されていないか検証
    loaded2 = store.load()
    assert loaded2["nested"]["key"] == "value"


def test_safe_json_store_update_exception_logging(tmp_path):
    """update で例外が発生した際に、正しくログが記録され、一時ファイルがクリーンアップされること"""
    from safe_io import logger
    from unittest.mock import patch
    
    file_path = tmp_path / "test_update_log.json"
    store = SafeJsonStore(file_path, default={"count": 0})

    with patch.object(logger, "error") as mock_log:
        with pytest.raises(TypeError):
            store.update(lambda data: {"invalid_set": {1, 2, 3}})
        
        # logger.error が "❌ JSONファイル保存エラー" で呼ばれたか確認
        assert mock_log.called
        args, _ = mock_log.call_args
        assert "❌ JSONファイル保存エラー" in args[0]
        
        # 一時ファイルが残っていないことを確認
        files = list(tmp_path.glob("*.tmp"))
        assert len(files) == 0


def test_safe_json_store_unsafe_load_logging(tmp_path):
    """_load_unsafe で例外が発生した際に、正しくログが記録されること"""
    from safe_io import logger
    
    file_path = tmp_path / "test_unsafe_log.json"
    file_path.write_text("invalid json", encoding="utf-8")
    store = SafeJsonStore(file_path, default={"count": 0})

    with patch.object(logger, "error") as mock_log:
        result = store.update(lambda data: data)
        
        # logger.error が "❌ JSONファイル読み込みエラー (内部)" で呼ばれたか確認
        assert mock_log.called
        args, _ = mock_log.call_args
        assert "❌ JSONファイル読み込みエラー (内部)" in args[0]
        assert result == {"count": 0}


def test_safe_json_store_init_invalid_default(tmp_path):
    """defaultに辞書以外を渡した際にTypeErrorが発生することを確認"""
    file_path = tmp_path / "test.json"
    with pytest.raises(TypeError, match="default must be a dictionary"):
        SafeJsonStore(file_path, default="not a dict")  # type: ignore


def test_safe_json_store_load_invalid_type_fallback(tmp_path):
    """JSONファイルの中身が辞書以外（例: リストや文字列）のとき、defaultのコピーが返されることを確認"""
    file_path = tmp_path / "test_list.json"
    default_data = {"key": "value"}
    store = SafeJsonStore(file_path, default=default_data)

    # 辞書以外の有効なJSON（リスト）を書き込む
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)

    loaded = store.load()
    assert loaded == default_data
    assert loaded is not default_data


def test_safe_json_store_save_invalid_type_error(tmp_path):
    """saveに辞書以外を渡した際にTypeErrorが発生することを確認"""
    file_path = tmp_path / "test.json"
    store = SafeJsonStore(file_path)
    with pytest.raises(TypeError, match="data must be a dictionary"):
        store.save("not a dict")  # type: ignore


def test_safe_json_store_update_invalid_type_error(tmp_path):
    """updater_fnが辞書以外を返した際にTypeErrorが発生することを確認"""
    file_path = tmp_path / "test.json"
    store = SafeJsonStore(file_path, default={"key": "value"})
    with pytest.raises(TypeError, match="updater_fn must return a dictionary"):
        store.update(lambda d: "not a dict")  # type: ignore


def test_safe_json_store_unsafe_load_invalid_type_fallback(tmp_path):
    """_load_unsafeで辞書以外のJSONを読み込んだ際、defaultのコピーが返されることを確認"""
    file_path = tmp_path / "test_unsafe_list.json"
    default_data = {"key": "value"}
    store = SafeJsonStore(file_path, default=default_data)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump("just a string", f)

    # update を通して _load_unsafe を走らせる
    result = store.update(lambda d: d)
    assert result == default_data


def test_safe_json_store_load_unexpected_exception(tmp_path):
    """load メソッドで想定外の例外（例: AttributeError）が発生した際に、安全にフォールバックされること"""
    file_path = tmp_path / "unexpected.json"
    default_data = {"fallback": True}
    store = SafeJsonStore(file_path, default=default_data)
    
    file_path.write_text("{}", encoding="utf-8")
    with patch("json.load", side_effect=AttributeError("Unexpected mock error")):
        loaded = store.load()
        assert loaded == default_data

def test_safe_json_store_unsafe_load_unexpected_exception(tmp_path):
    """_load_unsafe メソッドで想定外の例外（例: AttributeError）が発生した際に、安全にフォールバックされること"""
    file_path = tmp_path / "unexpected_unsafe.json"
    default_data = {"fallback": True}
    store = SafeJsonStore(file_path, default=default_data)
    
    file_path.write_text("{}", encoding="utf-8")
    with patch("json.load", side_effect=AttributeError("Unexpected mock error")):
        loaded = store.update(lambda d: d)
        assert loaded == default_data

def test_safe_json_store_save_unexpected_exception(tmp_path):
    """_save_unsafe メソッドで想定外の例外（例: AttributeError）が発生した際に、例外が再レイズされること"""
    file_path = tmp_path / "unexpected_save.json"
    store = SafeJsonStore(file_path)
    
    with patch("tempfile.mkstemp", side_effect=AttributeError("Unexpected mock error")):
        with pytest.raises(AttributeError, match="Unexpected mock error"):
            store.save({"test": 1})

def test_safe_json_store_unsafe_save_invalid_data_type(tmp_path):
    """_save_unsafe に辞書以外が渡された際に TypeError が発生すること (カバレッジ L188 対策)"""
    file_path = tmp_path / "invalid_type.json"
    store = SafeJsonStore(file_path)
    with pytest.raises(TypeError, match="data must be a dictionary"):
        store._save_unsafe("not a dict")  # type: ignore

def test_safe_json_store_unlink_os_error_ignored(tmp_path):
    """_save_unsafe のクリーンアップで os.unlink が OSError を投げても無視されること (カバレッジ L216-217 対策)"""
    file_path = tmp_path / "unlink_error.json"
    store = SafeJsonStore(file_path)
    
    with patch("os.replace", side_effect=OSError("Replace error")), \
         patch("os.unlink", side_effect=OSError("Unlink error")) as mock_unlink:
        with pytest.raises(OSError, match="Replace error"):
            store.save({"test": 1})
        assert mock_unlink.called


# --- Vault の保存先を環境変数で差し替えられること ---
# 保存先をローカル固定にしていると、Drive や CI へ移すときに
# 参照元（worker・disk_manager 等）を個別に直すことになる。
# 解決を1点に集約し、環境変数ひとつで差し替えられる状態を保つ。

def test_vault_outputs_dir_defaults_to_project_root(monkeypatch):
    """環境変数が無ければ従来どおり PROJECT_ROOT/vault-outputs を指す"""
    monkeypatch.delenv("ANTIGRAVITY_VAULT_OUTPUTS", raising=False)
    import importlib
    import safe_io
    importlib.reload(safe_io)
    assert safe_io.VAULT_OUTPUTS_DIR == safe_io.PROJECT_ROOT / "vault-outputs"


def test_vault_outputs_dir_honors_env(monkeypatch, tmp_path):
    """環境変数があればそちらを指す（Drive のマウント先などに差し替える用）"""
    target = tmp_path / "drive" / "vault-outputs"
    monkeypatch.setenv("ANTIGRAVITY_VAULT_OUTPUTS", str(target))
    import importlib
    import safe_io
    importlib.reload(safe_io)
    assert safe_io.VAULT_OUTPUTS_DIR == target
    monkeypatch.delenv("ANTIGRAVITY_VAULT_OUTPUTS", raising=False)
    importlib.reload(safe_io)


def test_disk_manager_fallback_honors_env(monkeypatch, tmp_path):
    """safe_io の import に失敗する経路でも同じ環境変数を見ること。

    disk_manager は safe_io から VAULT_OUTPUTS_DIR を取れないとき自前で
    フォールバック定義を持つ。ここが環境変数を見ないと、import 失敗時だけ
    旧パスを向くという分岐が残る。
    """
    target = tmp_path / "drive" / "vault-outputs"
    monkeypatch.setenv("ANTIGRAVITY_VAULT_OUTPUTS", str(target))
    import importlib
    import disk_manager
    with patch.dict(sys.modules, {"safe_io": None}):
        importlib.reload(disk_manager)
        assert disk_manager.VAULT_OUTPUTS_DIR == target
    monkeypatch.delenv("ANTIGRAVITY_VAULT_OUTPUTS", raising=False)
    importlib.reload(disk_manager)
