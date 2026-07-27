import os
import sys
import pytest
from pathlib import Path

# バックエンドルートをパスに追加
BACKEND_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# テスト対象モジュールのインポート
from tests.scratch.map_prefixes import PrefixMapper, scan_file


def test_parse_classes():
    mapper = PrefixMapper()
    content = (
        "class TestE2E1:\n"
        "    def test_foo(self):\n"
        "        pass\n"
        "class TestE2E2:\n"
        "    def test_bar(self):\n"
        "        pass\n"
    )
    classes = mapper.parse_classes(content)
    assert len(classes) == 2
    assert classes[0][0] == "TestE2E1"
    assert "test_foo" in classes[0][1]
    assert classes[1][0] == "TestE2E2"
    assert "test_bar" in classes[1][1]


def test_find_prefixes():
    mapper = PrefixMapper(prefixes=["O1-", "A1-"])
    block = "def test_something(self):\n    # O1-test\n    # A1_test"
    found = mapper.find_prefixes(block)
    assert "O1-" in found
    assert "A1-" in found


def test_find_hints():
    mapper = PrefixMapper(prefixes=["O1-", "A1-"])
    block = "def test_something(self):\n    # O1 test\n    # A1 test"
    hints = mapper.find_hints(block)
    assert "O1" in hints
    assert "A1" in hints


def test_scan_file_success(tmp_path):
    temp_file = tmp_path / "dummy_test.py"
    temp_file.write_text(
        "class TestE2E1:\n"
        "    # O1-test\n"
        "    pass\n"
        "class TestE2E2:\n"
        "    # A1_test\n"
        "    pass\n",
        encoding="utf-8"
    )

    results = scan_file(str(temp_file), prefixes=["O1-", "A1-"])
    assert "TestE2E1" in results
    assert results["TestE2E1"]["prefixes"] == ["O1-"]
    assert "TestE2E2" in results
    assert results["TestE2E2"]["prefixes"] == ["A1-"]


def test_scan_file_not_found():
    with pytest.raises(FileNotFoundError):
        scan_file("non_existent_file.py")


def test_scan_file_no_prefixes_but_hints(tmp_path):
    temp_file = tmp_path / "dummy_test_hints.py"
    temp_file.write_text(
        "class TestE2E3:\n"
        "    # O1 test without dash\n"
        "    pass\n",
        encoding="utf-8"
    )
    results = scan_file(str(temp_file), prefixes=["O1-", "A1-"])
    assert "TestE2E3" in results
    assert results["TestE2E3"]["prefixes"] == []
    assert results["TestE2E3"]["hints"] == ["O1"]


def test_prefix_mapper_default():
    mapper = PrefixMapper()
    assert "O1-" in mapper.prefixes
    assert "A9-" in mapper.prefixes


def test_scan_file_empty_file(tmp_path):
    temp_file = tmp_path / "empty_test.py"
    temp_file.write_text("", encoding="utf-8")
    results = scan_file(str(temp_file))
    assert results == {}


def test_parse_classes_no_class():
    mapper = PrefixMapper()
    content = "def test_func():\n    pass\n"
    classes = mapper.parse_classes(content)
    assert classes == []


def test_parse_classes_indented_class():
    mapper = PrefixMapper()
    content = (
        "class OuterClass:\n"
        "    class InnerClass:\n"
        "        pass\n"
    )
    classes = mapper.parse_classes(content)
    assert len(classes) == 1
    assert classes[0][0] == "OuterClass"
    assert "class InnerClass" in classes[0][1]


def test_find_hints_with_regex_characters():
    # プレフィックスに正規表現メタ文字が含まれる場合のエスケープテスト
    mapper = PrefixMapper(prefixes=["A.*-", "B+-"])
    block = "def test_something(self):\n    # A.* test\n    # B+ test"
    hints = mapper.find_hints(block)
    assert "A.*" in hints
    assert "B+" in hints


def test_scan_file_encoding_issue(tmp_path):
    # 不正なUTF-8バイトを含むファイルでのパース継続テスト
    temp_file = tmp_path / "bad_encoding.py"
    with open(temp_file, "wb") as f:
        f.write(b"class TestBad:\n    # O1-\x82\xa0\n    pass\n")
        
    results = scan_file(str(temp_file), prefixes=["O1-"])
    assert "TestBad" in results
    assert results["TestBad"]["prefixes"] == ["O1-"]


def test_scan_file_default_prefixes(tmp_path):
    # 引数 prefixes を省略し、デフォルトのプレフィックスを使って正常にスキャンできることを確認
    temp_file = tmp_path / "default_pref_test.py"
    temp_file.write_text(
        "class TestDefault:\n"
        "    # O1-test\n"
        "    pass\n",
        encoding="utf-8"
    )
    results = scan_file(str(temp_file))
    assert "TestDefault" in results
    assert results["TestDefault"]["prefixes"] == ["O1-"]


def test_find_hints_non_word_start():
    # プレフィックスのハイフン除去後に非単語文字から始まる場合の find_hints の挙動を確認
    # 例: "*A1-" -> ハイフン除去後は "*A1"
    # "*A1" の先頭は非単語文字なので \b は付かず、末尾は "1" (単語文字) なので \b が付く
    mapper = PrefixMapper(prefixes=["*A1-"])
    block = "def test_something(self):\n    # prefix is *A1 but not *A1word"
    hints = mapper.find_hints(block)
    assert "*A1" in hints

    # 単語文字が末尾に続く場合はマッチしないこと（\b が末尾に付くため）
    block_no_match = "def test_something(self):\n    # prefix is *A1word"
    hints_no_match = mapper.find_hints(block_no_match)
    assert "*A1" not in hints_no_match


def test_parse_classes_global_code_exclusion():
    mapper = PrefixMapper()
    content = (
        "class TestClass:\n"
        "    pass\n"
        "\n"
        "def global_func():\n"
        "    # O1-test\n"
        "    pass\n"
    )
    classes = mapper.parse_classes(content)
    assert len(classes) == 1
    assert classes[0][0] == "TestClass"
    assert "global_func" not in classes[0][1]
    assert "O1-test" not in classes[0][1]


def test_scan_file_directory_path(tmp_path):
    with pytest.raises(ValueError) as excinfo:
        scan_file(str(tmp_path))
    assert "Path is not a file" in str(excinfo.value)



def test_find_hints_word_start_non_word_end():
    # プレフィックスが単語文字で始まり非単語文字で終わる場合のヒント検出
    mapper = PrefixMapper(prefixes=["A1*-"])
    block = "def test_something(self):\n    # hint is A1* but not A1*word"
    hints = mapper.find_hints(block)
    assert "A1*" in hints


def test_find_hints_non_word_start_non_word_end():
    # プレフィックスの先頭と末尾が非単語文字の場合のヒント検出
    mapper = PrefixMapper(prefixes=["*A1*-"])
    block = "def test_something(self):\n    # hint is *A1* anywhere"
    hints = mapper.find_hints(block)
    assert "*A1*" in hints


def test_scan_file_mixed_prefixes_and_hints(tmp_path):
    # プレフィックス一致とヒント一致が混在するファイルのスキャンテスト
    temp_file = tmp_path / "mixed_test.py"
    temp_file.write_text(
        "class TestPref:\n"
        "    # O1-test\n"
        "    pass\n"
        "class TestHint:\n"
        "    # A1 test\n"
        "    pass\n",
        encoding="utf-8"
    )
    results = scan_file(str(temp_file), prefixes=["O1-", "A1-"])
    assert "TestPref" in results
    assert results["TestPref"]["prefixes"] == ["O1-"]
    assert results["TestPref"]["hints"] == []
    
    assert "TestHint" in results
    assert results["TestHint"]["prefixes"] == []
    assert results["TestHint"]["hints"] == ["A1"]


def test_scan_file_permission_error(tmp_path):
    # 読み取り不可能なファイルに対する PermissionError の検証
    from unittest.mock import patch
    temp_file = tmp_path / "perm_error_test.py"
    temp_file.write_text("class A: pass", encoding="utf-8")
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with pytest.raises(PermissionError):
            scan_file(str(temp_file))


def test_parse_classes_multiple_classes_without_empty_lines():
    # 空行がない連続したクラスのパース
    mapper = PrefixMapper()
    content = (
        "class ClassA:\n"
        "    pass\n"
        "class ClassB:\n"
        "    pass\n"
    )
    classes = mapper.parse_classes(content)
    assert len(classes) == 2
    assert classes[0][0] == "ClassA"
    assert classes[1][0] == "ClassB"


def test_parse_classes_non_indented_comment_and_empty_line():
    # クラス定義の直後のインデントされていない空行やコメント行が、クラスブロックに含まれることを検証
    mapper = PrefixMapper()
    content = (
        "class ClassA:\n"
        "    pass\n"
        "# This is a global comment inside ClassA's parser block\n"
        "\n"
        "class ClassB:\n"
        "    pass\n"
    )
    classes = mapper.parse_classes(content)
    assert len(classes) == 2
    assert classes[0][0] == "ClassA"
    assert "global comment" in classes[0][1]
    assert classes[1][0] == "ClassB"


def test_prefix_mapper_hints_complex():
    # プレフィックスにハイフンが複数含まれる、または含まれない場合のヒント検出
    mapper = PrefixMapper(prefixes=["PREF", "A-B-"])
    block = "This block contains PREF and AB but not PREFword or ABword"
    hints = mapper.find_hints(block)
    assert "PREF" in hints
    assert "AB" in hints


def test_parse_class_blocks():
    mapper = PrefixMapper()
    content = (
        "class TestE2E1:\n"
        "    def test_foo(self):\n"
        "        pass\n"
    )
    classes = mapper.parse_class_blocks(content)
    assert len(classes) == 1
    assert classes[0][0] == "TestE2E1"


def test_is_block_end():
    mapper = PrefixMapper()
    # インデントあり -> block end ではない
    assert not mapper._is_block_end("    pass")
    # インデントなしだがコメント -> block end ではない
    assert not mapper._is_block_end("# comment")
    # インデントなしだが空行 -> block end ではない
    assert not mapper._is_block_end("")
    # インデントなし、コメント・空行でもない -> block end
    assert mapper._is_block_end("def global_func():")


def test_build_hint_pattern():
    mapper = PrefixMapper()
    # 単語文字で始まり単語文字で終わる
    pattern1 = mapper._build_hint_pattern("A1", "A1")
    assert pattern1 == r"\bA1\b"
    # 非単語文字で始まり単語文字で終わる
    pattern2 = mapper._build_hint_pattern("*A1", r"\*A1")
    assert pattern2 == r"\*A1\b"
    # 単語文字で始まり非単語文字で終わる
    pattern3 = mapper._build_hint_pattern("A1*", r"A1\*")
    assert pattern3 == r"\bA1\*"
    # 非単語文字で始まり非単語文字で終わる
    pattern4 = mapper._build_hint_pattern("*A1*", r"\*A1\*")
    assert pattern4 == r"\*A1\*"

