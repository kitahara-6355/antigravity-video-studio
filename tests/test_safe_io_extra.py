import sys
import os
import json
import pytest
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

# safe_io がある backend ディレクトリを sys.path に追加
BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from safe_io import SafeJsonStore

def test_load_unsafe_corrupt_json(tmp_path):
    """_load_unsafe で JSON が壊れている場合はデフォルト値を返すこと"""
    corrupt_file = tmp_path / "corrupt_unsafe.json"
    corrupt_file.write_text("{invalid json", encoding="utf-8")

    default = {"fallback": True}
    store = SafeJsonStore(corrupt_file, default=default)
    result = store.update(lambda data: {**data, "updated": True})
    assert result == {"fallback": True, "updated": True}

def test_load_unsafe_os_error(tmp_path):
    """_load_unsafe で OSError が発生した場合はデフォルト値を返すこと"""
    test_file = tmp_path / "unreadable_unsafe.json"
    test_file.write_text("{}", encoding="utf-8")

    default = {"fallback": True}
    store = SafeJsonStore(test_file, default=default)

    with patch("builtins.open", side_effect=OSError("Read permission denied")):
        result = store.update(lambda data: {**data, "updated": True})

    assert result == {"fallback": True, "updated": True}

def test_save_unsafe_write_error(tmp_path):
    """_save_unsafe で書き込み中にエラーが起きても一時ファイルが削除され、例外が再スローされること"""
    store = SafeJsonStore(tmp_path / "save_unsafe.json", default={"count": 0})
    bad_data = {"key": object()}

    with pytest.raises(TypeError):
        store.update(lambda data: bad_data)

    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0
