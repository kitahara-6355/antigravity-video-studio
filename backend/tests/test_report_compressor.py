# -*- coding: utf-8 -*-
import pytest
from agents.orchestration.report_compressor import ReportCompressor

def test_compress_normal():
    compressor = ReportCompressor()
    tasks = [
        {"status": "pass", "target_module": "module_a", "report": {"message": "Success"}},
        {"status": "fail", "target_module": "module_b", "report": {"error": "AssertionError: count 5 != 10\nStack trace here", "traceback": "Traceback info"}}
    ]
    
    result = compressor.compress(tasks)
    assert result["total"] == 2
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert len(result["clustered_errors"]) == 1
    assert result["clustered_errors"][0]["error"] == "AssertionError: count N != N"
    assert result["clustered_errors"][0]["module"] == "module_b"

def test_compress_with_none_task():
    compressor = ReportCompressor()
    tasks = [
        {"status": "pass", "target_module": "module_a", "report": {"message": "Success"}},
        None,  # 異常値
        {"status": "fail", "target_module": "module_b", "report": {"error": "ConnectionError"}}
    ]
    
    result = compressor.compress(tasks)
    assert result["total"] == 3
    assert result["passed"] == 1
    assert result["failed"] == 1

def test_compress_with_non_dict_task():
    compressor = ReportCompressor()
    tasks = [
        {"status": "pass", "target_module": "module_a", "report": {"message": "Success"}},
        "invalid_task_string",  # 異常値
        {"status": "fail", "target_module": "module_b", "report": {"error": "ConnectionError"}}
    ]
    
    result = compressor.compress(tasks)
    assert result["total"] == 3
    assert result["passed"] == 1
    assert result["failed"] == 1

def test_compress_with_missing_status():
    compressor = ReportCompressor()
    tasks = [
        {"status": "pass", "target_module": "module_a", "report": {"message": "Success"}},
        {"target_module": "module_c"},  # 'status'キーが欠損
        {"status": "fail", "target_module": "module_b", "report": {"error": "ConnectionError"}}
    ]
    
    result = compressor.compress(tasks)
    assert result["total"] == 3
    assert result["passed"] == 1
    assert result["failed"] == 1

def test_compress_with_non_string_error():
    compressor = ReportCompressor()
    tasks = [
        {
            "status": "fail",
            "target_module": "module_b",
            "report": {
                "error": {"code": 500, "message": "Internal Server Error"},  # 非文字列型エラー
                "traceback": "Traceback info"
            }
        }
    ]
    
    result = compressor.compress(tasks)
    assert len(result["clustered_errors"]) == 1
    assert "Internal Server Error" in result["clustered_errors"][0]["error"] or "500" in result["clustered_errors"][0]["error"]

def test_compress_with_non_dict_report():
    compressor = ReportCompressor()
    tasks = [
        {
            "status": "fail",
            "target_module": "module_b",
            "report": "Timeout occurred while connecting to database"  # 辞書ではない文字列型report
        }
    ]
    
    result = compressor.compress(tasks)
    assert len(result["clustered_errors"]) == 1
    assert result["clustered_errors"][0]["error"] == "Timeout occurred while connecting to database"
    assert result["clustered_errors"][0]["module"] == "module_b"
    assert result["clustered_errors"][0]["sample_traceback"] == ""

def test_compress_empty_normalized_error():
    compressor = ReportCompressor()
    
    # None、空文字列、空白文字、あるいは変換できないオブジェクトの検証
    assert compressor._normalize_error(None) == "UnknownError"
    assert compressor._normalize_error("") == "UnknownError"
    assert compressor._normalize_error("   ") == "UnknownError"
    
    # 例外的なオブジェクトの検証
    class UnstrObject:
        def __str__(self):
            raise ValueError("Cannot convert to string")
            
    assert compressor._normalize_error(UnstrObject()) == "UnknownError"

    # 具体的な例外（TypeError, AttributeError, RuntimeError）の検証
    class TypeErrorObject:
        def __str__(self):
            raise TypeError("Cannot convert to string")

    class AttributeErrorObject:
        def __str__(self):
            raise AttributeError("Cannot convert to string")

    class RuntimeErrorObject:
        def __str__(self):
            raise RuntimeError("Cannot convert to string")

    assert compressor._normalize_error(TypeErrorObject()) == "UnknownError"
    assert compressor._normalize_error(AttributeErrorObject()) == "UnknownError"
    assert compressor._normalize_error(RuntimeErrorObject()) == "UnknownError"

def test_compress_methods_with_non_string_args():
    compressor = ReportCompressor()
    
    # 短い非文字列を渡す（MAX_SUMMARY_CHARS以下） -> そのまま文字列として返る
    response_summary_short = compressor.compress_agent_response({"status": "success"}, task_id="T1")
    assert "status" in response_summary_short
    assert "T1" not in response_summary_short  # 短い場合はプレフィックスが付加されない
    
    # 長い非文字列を渡す（MAX_SUMMARY_CHARS超） -> 圧縮されてプレフィックスが付加される
    long_obj = {"status": "success", "payload": "A" * 500}
    response_summary_long = compressor.compress_agent_response(long_obj, task_id="T1")
    assert "status" in response_summary_long
    assert "T1" in response_summary_long  # 圧縮されたのでプレフィックスが付加される
    
    # compress_test_output に非文字列を渡す
    test_summary = compressor.compress_test_output(12345)
    assert "12345" in test_summary
    
    # compress_traceback に非文字列を渡す
    tb_summary = compressor.compress_traceback(["Traceback line 1", "Traceback line 2"])
    assert "Traceback" in tb_summary

def test_compress_with_complex_nested_error():
    compressor = ReportCompressor()
    tasks = [
        {
            "status": "fail",
            "target_module": "complex_mod",
            "report": {
                "error": ["Error line 1", "Error line 2"],  # エラーメッセージがリスト型
                "traceback": 12345  # トレースバックが数値型
            }
        }
    ]
    result = compressor.compress(tasks)
    assert len(result["clustered_errors"]) == 1
    # 正常にキャストされ、何らかのエラー文字列が抽出されることを検証
    assert result["clustered_errors"][0]["module"] == "complex_mod"
    assert result["clustered_errors"][0]["sample_traceback"] == "12345"

def test_compress_agent_response_modified_files_validation():
    compressor = ReportCompressor()
    
    # response_text を MAX_SUMMARY_CHARS (400) より長くして圧縮処理を走らせる
    long_response = "✅ 完了 " * 100
    
    # 正常ケース (リスト)
    res = compressor.compress_agent_response(long_response, task_id="T1", modified_files=["file1.py", "file2.py"])
    assert "変更: file1.py, file2.py" in res
    assert "[T1]" in res
    
    # modified_files が文字列の場合 (非リスト)
    res_str = compressor.compress_agent_response(long_response, task_id="T1", modified_files="single_file.py")
    assert "変更: single_file.py" in res_str
    
    # modified_files がリストで、数値や None が混ざっている場合
    res_mixed = compressor.compress_agent_response(long_response, task_id="T1", modified_files=["file1.py", 123, None, "file2.py"])
    assert "変更: file1.py, 123, file2.py" in res_mixed
