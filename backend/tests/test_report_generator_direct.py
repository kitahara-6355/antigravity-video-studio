# -*- coding: utf-8 -*-
import pytest
import os
import json
from datetime import datetime
from pathlib import Path
import sys

cwd = Path.cwd()
workspace_root = str(cwd)
workspace_backend = str(cwd / 'backend')
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)
if workspace_backend not in sys.path:
    sys.path.insert(0, workspace_backend)

from backend.report_generator import (
    load_json_file,
    _sanitize_markdown_cell,
    _parse_execution_time,
    _build_memory_section,
    _build_cleanup_section,
    _build_ffmpeg_section,
    _build_quality_section,
    _build_fact_list,
    generate_durability_report,
)

def test_sanitize_markdown_cell():
    assert _sanitize_markdown_cell(None) == ""
    assert _sanitize_markdown_cell("normal text") == "normal text"
    assert _sanitize_markdown_cell("text | with | pipes") == "text \\| with \\| pipes"
    assert _sanitize_markdown_cell("text" + "\n" + "with" + "\n" + "newlines") == "text with newlines"
    assert _sanitize_markdown_cell(123) == "123"

def test_load_json_file_not_dict(tmp_path):
    list_json = tmp_path / "list.json"
    with open(list_json, "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
    assert load_json_file(str(list_json)) == {}

def test_parse_execution_time():
    assert _parse_execution_time({"timestamp": "2026-06-15T12:00:00+09:00"}, {}) == "2026-06-15 12:00:00"
    assert _parse_execution_time({"timestamp": "invalid_time"}, {}) == "invalid_time"
    current_time_str = _parse_execution_time({}, {})
    assert len(current_time_str) == 19

def test_build_memory_section_robustness():
    bad_data = {
        "memory_metrics": [
            "not_a_dict",
            {"timestamp": "12:00 | leak", "usage_mb": "invalid_float"},
            {"timestamp": "12:05" + "\n" + "leak", "usage_mb": 150.5}
        ],
        "memory_leak_detected": "True"
    }
    table, result, passed = _build_memory_section(bad_data)
    assert "\\|" in table
    assert "12:05" + "\n" + "leak" not in table
    assert "12:05 leak" in table
    assert "無効な値" in table
    assert "⚠️ 異常（メモリリーク検出）" in result
    assert passed is False

def test_build_cleanup_section_robustness():
    bad_data = {
        "temp_dir_metrics": {
            "initial_size_bytes": "1000",
            "final_size_bytes": "50",
            "cleanup_success": "False"
        }
    }
    report, result, passed = _build_cleanup_section(bad_data)
    assert "1000 バイト" in report
    assert "50 バイト" in report
    assert "クリーンアップ不完全" in result
    assert passed is False

    zero_size_data = {
        "temp_dir_metrics": {
            "initial_size_bytes": "1000",
            "final_size_bytes": "0",
            "cleanup_success": None
        }
    }
    report, result, passed = _build_cleanup_section(zero_size_data)
    assert "クリーンアップ成功" in result
    assert passed is True

def test_build_ffmpeg_section_robustness():
    bad_data = {
        "ffmpeg_process_metrics": {
            "remaining_child_processes": "invalid",
            "zombie_processes": None
        }
    }
    report, result, passed = _build_ffmpeg_section(bad_data)
    assert "プロセス残存情報: 未取得" in report
    assert "判定データなし" in result
    assert passed is False

def test_build_quality_section_robustness():
    bad_data = {
        "iterations": [
            {"iteration": "1 | hack", "score": "85.5", "passed": "True", "vision_violations": "0"}
        ],
        "final_score": "85.5",
        "vision_violations": "0",
        "passed": "True"
    }
    table, status, result, passed = _build_quality_section(bad_data)
    assert "\\|" in table
    assert "合格" in status
    assert "85.5 点" in result
    assert passed is True


def test_load_json_file_unicode_decode_error(tmp_path):
    # UTF-8としてデコード不可能なバイナリファイルを書き込む
    binary_file = tmp_path / "binary.json"
    with open(binary_file, "wb") as f:
        f.write(b"\xff\xfe\x00\x00{invalid json")
    
    # UnicodeDecodeErrorが発生するが、安全に {} が返されることを検証
    assert load_json_file(str(binary_file)) == {}


def test_build_cleanup_section_partial_invalid():
    # final_size_bytes だけが無効な場合
    partial_bad_data = {
        "temp_dir_metrics": {
            "initial_size_bytes": "5000",
            "final_size_bytes": "invalid_int",
            "cleanup_success": "False"
        }
    }
    report, result, passed = _build_cleanup_section(partial_bad_data)
    # final_size_bytes が None になるため、全体のレポートは「サイズ情報: 未取得」になるが、例外でクラッシュはしない
    assert "一時フォルダサイズ情報: 未取得" in report
    assert "判定データなし" in result
    assert passed is False


def test_build_ffmpeg_section_partial_invalid():
    # zombie_processes だけが無効な場合でも、正常な remaining_child_processes はデコードされる
    partial_bad_data = {
        "ffmpeg_process_metrics": {
            "remaining_child_processes": "3",
            "zombie_processes": "invalid_int"
        }
    }
    report, result, passed = _build_ffmpeg_section(partial_bad_data)
    # 正常な child_processes はデコードされ、zombiesはデコードされないため、結果的に判定データなし（未検証）になる
    assert "残存子プロセス数" not in report or "判定データなし" in result
    assert passed is False


def test_build_quality_section_passed_string_false():
    # passed が文字列の "False" の場合
    data_false = {
        "iterations": [
            {"iteration": 1, "score": 85.0, "passed": "False", "vision_violations": 0}
        ],
        "final_score": 85.0,
        "vision_violations": 0,
        "passed": "False"
    }
    _, status, _, passed = _build_quality_section(data_false)
    assert status == "⚠️ 不合格"
    assert passed is False

    # passed が文字列の "True" の場合
    data_true = {
        "iterations": [
            {"iteration": 1, "score": 85.0, "passed": "True", "vision_violations": 0}
        ],
        "final_score": 85.0,
        "vision_violations": 0,
        "passed": "True"
    }
    _, status, _, passed = _build_quality_section(data_true)
    assert status == "✅ 合格"
    assert passed is True


def test_generate_durability_report_value_error_robustness(tmp_path):
    from unittest.mock import patch
    
    stability_file = tmp_path / "stability.json"
    quality_file = tmp_path / "quality.json"
    output_file = tmp_path / "report.md"
    
    with open(stability_file, "w", encoding="utf-8") as f:
        f.write('{"platform": "test", "timestamp": "2026-06-15T12:00:00"}')
    with open(quality_file, "w", encoding="utf-8") as f:
        f.write('{"timestamp": "2026-06-15T12:00:00"}')
        
    # _build_memory_section の呼び出し時に ValueError を発生させる
    with patch("backend.report_generator._build_memory_section", side_effect=ValueError("Test value error")):
        # ValueError がキャッチされてクラッシュせずに False が返ることを検証
        res = generate_durability_report(str(stability_file), str(quality_file), str(output_file))
        assert res is False
