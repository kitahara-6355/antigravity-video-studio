# -*- coding: utf-8 -*-
import pytest
from unittest.mock import patch
from pathlib import Path
from backend.agents.orchestration.directive_applicator import DirectiveApplicator

def test_apply_file_not_found(tmp_path):
    # 存在しないファイルを指定した場合に False が返ることを検証
    non_existent_file = tmp_path / "non_existent.txt"
    applicator = DirectiveApplicator(non_existent_file)
    result = applicator.apply({"strategy": "test"})
    assert result is False

def test_apply_read_os_error(tmp_path):
    # ファイルは存在するが読み込み時に OSError が発生した場合に False が返ることを検証
    test_file = tmp_path / "test_prompt.txt"
    test_file.write_text("dummy", encoding="utf-8")
    
    applicator = DirectiveApplicator(test_file)
    with patch.object(Path, "read_text", side_effect=OSError("Read error")):
        result = applicator.apply({"strategy": "test"})
        assert result is False

def test_apply_missing_tags(tmp_path):
    # タグが完全に欠落している場合に False が返ることを検証
    test_file = tmp_path / "test_prompt.txt"
    test_file.write_text("Hello World", encoding="utf-8")
    
    applicator = DirectiveApplicator(test_file)
    result = applicator.apply({"strategy": "test"})
    assert result is False

    # 開始タグのみ存在する場合に False が返ることを検証
    test_file.write_text("<!-- OPUS_DIRECTIVE_START -->", encoding="utf-8")
    result = applicator.apply({"strategy": "test"})
    assert result is False

    # 終了タグのみ存在する場合に False が返ることを検証
    test_file.write_text("<!-- OPUS_DIRECTIVE_END -->", encoding="utf-8")
    result = applicator.apply({"strategy": "test"})
    assert result is False

def test_apply_success_with_all_fields(tmp_path):
    # 正常系: priorities と strategy の両方が含まれる場合に正しく置換されることを検証
    test_file = tmp_path / "test_prompt.txt"
    initial_content = (
        "Prefix\n"
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "Old directive\n"
        "<!-- OPUS_DIRECTIVE_END -->\n"
        "Suffix"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    directive = {
        "priorities": ["Priority A", "Priority B"],
        "strategy": "Improve quality"
    }

    applicator = DirectiveApplicator(test_file)
    result = applicator.apply(directive)
    assert result is True

    updated_content = test_file.read_text(encoding="utf-8")
    expected_content = (
        "Prefix\n"
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "- Priorities:\n"
        "  - Priority A\n"
        "  - Priority B\n"
        "- Strategy: Improve quality\n"
        "<!-- OPUS_DIRECTIVE_END -->\n"
        "Suffix"
    )
    assert updated_content == expected_content

def test_apply_success_only_priorities(tmp_path):
    # 正常系: priorities のみ含まれる場合に正しく置換されることを検証
    test_file = tmp_path / "test_prompt.txt"
    initial_content = (
        "Prefix\n"
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "Old directive\n"
        "<!-- OPUS_DIRECTIVE_END -->\n"
        "Suffix"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    directive = {
        "priorities": ["Priority A"]
    }

    applicator = DirectiveApplicator(test_file)
    result = applicator.apply(directive)
    assert result is True

    updated_content = test_file.read_text(encoding="utf-8")
    expected_content = (
        "Prefix\n"
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "- Priorities:\n"
        "  - Priority A\n"
        "<!-- OPUS_DIRECTIVE_END -->\n"
        "Suffix"
    )
    assert updated_content == expected_content

def test_apply_success_only_strategy(tmp_path):
    # 正常系: strategy のみ含まれる場合に正しく置換されることを検証
    test_file = tmp_path / "test_prompt.txt"
    initial_content = (
        "Prefix\n"
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "Old directive\n"
        "<!-- OPUS_DIRECTIVE_END -->\n"
        "Suffix"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    directive = {
        "strategy": "Improve quality"
    }

    applicator = DirectiveApplicator(test_file)
    result = applicator.apply(directive)
    assert result is True

    updated_content = test_file.read_text(encoding="utf-8")
    expected_content = (
        "Prefix\n"
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "- Strategy: Improve quality\n"
        "<!-- OPUS_DIRECTIVE_END -->\n"
        "Suffix"
    )
    assert updated_content == expected_content

def test_apply_success_empty_directive(tmp_path):
    # 正常系: directive が空の場合にタグの間が空に置換されることを検証
    test_file = tmp_path / "test_prompt.txt"
    initial_content = (
        "Prefix\n"
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "Old directive\n"
        "<!-- OPUS_DIRECTIVE_END -->\n"
        "Suffix"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    applicator = DirectiveApplicator(test_file)
    result = applicator.apply({})
    assert result is True

    updated_content = test_file.read_text(encoding="utf-8")
    expected_content = (
        "Prefix\n"
        "<!-- OPUS_DIRECTIVE_START -->\n\n"
        "<!-- OPUS_DIRECTIVE_END -->\n"
        "Suffix"
    )
    assert updated_content == expected_content

def test_apply_write_os_error(tmp_path):
    # 書き込み時に OSError が発生した場合に False が返ることを検証
    test_file = tmp_path / "test_prompt.txt"
    initial_content = (
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "<!-- OPUS_DIRECTIVE_END -->"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    applicator = DirectiveApplicator(test_file)
    with patch.object(Path, "write_text", side_effect=OSError("Write error")):
        result = applicator.apply({"strategy": "test"})
        assert result is False


def test_apply_path_as_string(tmp_path):
    # コンストラクタに Path ではなく文字列でパスを渡しても正しく動作することを検証
    test_file = tmp_path / "test_prompt.txt"
    initial_content = (
        "Prefix\n"
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "Old\n"
        "<!-- OPUS_DIRECTIVE_END -->\n"
        "Suffix"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    applicator = DirectiveApplicator(str(test_file))
    result = applicator.apply({"strategy": "test"})
    assert result is True
    assert "Strategy: test" in test_file.read_text(encoding="utf-8")

def test_apply_non_string_priorities(tmp_path):
    # priorities に文字列以外の型が含まれる場合に正しく文字列化されることを検証
    test_file = tmp_path / "test_prompt.txt"
    initial_content = (
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "<!-- OPUS_DIRECTIVE_END -->"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    applicator = DirectiveApplicator(test_file)
    result = applicator.apply({"priorities": [123, None, True]})
    assert result is True

    updated_content = test_file.read_text(encoding="utf-8")
    assert "- Priorities:\n  - 123\n  - None\n  - True" in updated_content

def test_apply_multiple_tags(tmp_path):
    # 重複タグがある場合、最初のペアが正しく置換され、他はそのまま残ることを検証
    test_file = tmp_path / "test_prompt.txt"
    initial_content = (
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "First block\n"
        "<!-- OPUS_DIRECTIVE_END -->\n"
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "Second block\n"
        "<!-- OPUS_DIRECTIVE_END -->"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    applicator = DirectiveApplicator(test_file)
    result = applicator.apply({"strategy": "test"})
    assert result is True

    updated_content = test_file.read_text(encoding="utf-8")
    # 最初のタグペアだけが置換されていること
    assert "- Strategy: test" in updated_content
    assert "Second block" in updated_content


def test_apply_unicode_characters(tmp_path):
    # 日本語や絵文字などの Unicode 文字が含まれる場合でも正しくマージされ、UTF-8 で保存されることを検証
    test_file = tmp_path / "test_prompt.txt"
    initial_content = (
        "Prefix\n"
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "Old\n"
        "<!-- OPUS_DIRECTIVE_END -->\n"
        "Suffix"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    directive = {
        "priorities": ["優先事項１ 🚀", "日本語のテスト"],
        "strategy": "品質の向上を目指す🌟"
    }

    applicator = DirectiveApplicator(test_file)
    result = applicator.apply(directive)
    assert result is True

    updated_content = test_file.read_text(encoding="utf-8")
    expected_content = (
        "Prefix\n"
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "- Priorities:\n"
        "  - 優先事項１ 🚀\n"
        "  - 日本語のテスト\n"
        "- Strategy: 品質の向上を目指す🌟\n"
        "<!-- OPUS_DIRECTIVE_END -->\n"
        "Suffix"
    )
    assert updated_content == expected_content


def test_apply_tags_without_newlines(tmp_path):
    # タグの直前に改行がない一行のテキストであっても、正しく改行を伴って置換されることを検証
    test_file = tmp_path / "test_prompt.txt"
    initial_content = "Prefix<!-- OPUS_DIRECTIVE_START -->Old<!-- OPUS_DIRECTIVE_END -->Suffix"
    test_file.write_text(initial_content, encoding="utf-8")

    applicator = DirectiveApplicator(test_file)
    result = applicator.apply({"strategy": "inline_test"})
    assert result is True

    updated_content = test_file.read_text(encoding="utf-8")
    expected_content = (
        "Prefix<!-- OPUS_DIRECTIVE_START -->\n"
        "- Strategy: inline_test\n"
        "<!-- OPUS_DIRECTIVE_END -->Suffix"
    )
    assert updated_content == expected_content


def test_apply_invalid_directive_type(tmp_path):
    # directive に辞書以外（Noneなど）が渡された場合、AttributeError が発生することを検証
    test_file = tmp_path / "test_prompt.txt"
    initial_content = (
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "<!-- OPUS_DIRECTIVE_END -->"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    applicator = DirectiveApplicator(test_file)
    with pytest.raises(AttributeError):
        applicator.apply(None)  # type: ignore


def test_apply_priorities_not_iterable(tmp_path):
    # priorities にイテラブルでないオブジェクトが指定された場合、TypeError が発生することを検証
    test_file = tmp_path / "test_prompt.txt"
    initial_content = (
        "<!-- OPUS_DIRECTIVE_START -->\n"
        "<!-- OPUS_DIRECTIVE_END -->"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    applicator = DirectiveApplicator(test_file)
    with pytest.raises(TypeError):
        applicator.apply({"priorities": 123})  # type: ignore

