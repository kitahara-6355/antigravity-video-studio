# -*- coding: utf-8 -*-
import pytest
from unittest.mock import patch, MagicMock
import os
import sys

# パス設定
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.scratch.find_classes import find_classes_in_file, main

def test_find_classes_file_not_found():
    res = find_classes_in_file("nonexistent_file_path.py")
    assert res == []

def test_find_classes_success(tmp_path):
    temp_file = tmp_path / "dummy_class_file.py"
    temp_file.write_text(
        "class MyClass1:\n"
        "    pass\n"
        "\n"
        "class MyClass2(Base):\n"
        "    pass\n",
        encoding="utf-8"
    )
    
    res = find_classes_in_file(str(temp_file))
    assert len(res) == 2
    assert res[0] == (1, "MyClass1")
    assert res[1] == (4, "MyClass2")

def test_main_no_args_file_not_found():
    with patch("os.path.exists", return_value=False):
        ret = main()
        assert ret == 1

def test_main_with_arg_success(tmp_path):
    temp_file = tmp_path / "dummy_class_file.py"
    temp_file.write_text("class TestClass:\n    pass\n", encoding="utf-8")
    
    with patch("sys.argv", ["find_classes.py", str(temp_file)]):
        ret = main()
        assert ret == 0
