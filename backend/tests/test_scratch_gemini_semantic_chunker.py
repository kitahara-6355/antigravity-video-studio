import pytest
from unittest.mock import MagicMock, patch, mock_open
import sys
import os
import json
from pathlib import Path
from google import genai

# テスト前にモックを適用してインポートエラーを防ぐ
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

backend_parent = os.path.abspath(os.path.join(backend_dir, ".."))
if backend_parent not in sys.path:
    sys.path.insert(0, backend_parent)

# gemini_client_factory.get_gemini_client と model_registry.get_model が呼ばれたときにモックを返すようにする
mock_gemini_client = MagicMock()
with patch("gemini_client_factory.get_gemini_client", return_value=mock_gemini_client), \
     patch("model_registry.get_model", return_value="mocked-model", create=True):
    from backend.gemini_semantic_chunker_deprecated import (
        GeminiSemanticChunker,
        process_whisper_to_semantic_srt,
        DEFAULT_MODEL
    )

def test_init():
    # 引数なし
    chunker = GeminiSemanticChunker()
    assert chunker.model_name == DEFAULT_MODEL

    # 引数あり
    chunker_custom = GeminiSemanticChunker(model_name="custom-model")
    assert chunker_custom.model_name == "custom-model"

def test_default_model_fallback():
    # model_registry.get_model が例外を投げる状況下での評価を検証し、
    # except 節を安全にカバーする
    with patch("model_registry.get_model", side_effect=ImportError("mocked error"), create=True), \
         patch("gemini_client_factory.get_gemini_client", return_value=MagicMock()):
        # sys.modulesから削除して再インポートをテストする
        if "backend.gemini_semantic_chunker_deprecated" in sys.modules:
            del sys.modules["backend.gemini_semantic_chunker_deprecated"]
        
        from backend.gemini_semantic_chunker_deprecated import DEFAULT_MODEL as fallback_model
        assert fallback_model == "gemini-2.0-flash"

def test_format_timestamp():
    # 正常系
    assert GeminiSemanticChunker._format_timestamp(0.0) == "00:00:00,000"
    assert GeminiSemanticChunker._format_timestamp(123.456) == "00:02:03,456"
    assert GeminiSemanticChunker._format_timestamp(3661.123) == "01:01:01,123"
    
    # 異常系・境界値
    assert GeminiSemanticChunker._format_timestamp(-5.0) == "00:00:00,000"
    assert GeminiSemanticChunker._format_timestamp("invalid") == "00:00:00,000"
    assert GeminiSemanticChunker._format_timestamp(None) == "00:00:00,000"

def test_segments_to_text():
    chunker = GeminiSemanticChunker()
    
    # 正常系
    segments = [
        {"start": 1.2, "text": "こんにちは"},
        {"start": 3.45, "text": "テストです"}
    ]
    expected = "[1.20s] こんにちは\n[3.45s] テストです"
    assert chunker._segments_to_text(segments) == expected

    # 異常系
    # 辞書でない要素はスキップされる
    segments_with_invalid = [
        {"start": 1.2, "text": "こんにちは"},
        "not a dict",
        {"start": 3.45, "text": "テストです"}
    ]
    assert chunker._segments_to_text(segments_with_invalid) == expected

    # startやtextが欠けている場合
    segments_missing = [
        {"text": "こんにちは"},  # start欠如 -> 0.00s になる
        {"start": 3.45}          # text欠如 -> "" になる
    ]
    expected_missing = "[0.00s] こんにちは\n[3.45s] "
    assert chunker._segments_to_text(segments_missing) == expected_missing

    # startが数値以外
    segments_bad_start = [
        {"start": "invalid", "text": "こんにちは"}
    ]
    assert chunker._segments_to_text(segments_bad_start) == "[0.00s] こんにちは"

def test_save_as_srt(tmp_path):
    chunker = GeminiSemanticChunker()
    output_file = tmp_path / "output.srt"
    
    # 正常系
    segments = [
        {"start": 1.5, "end": 3.5, "text": "こんにちは", "speaker": "話者A"},
        "not a dict",  # スキップされるが enumerate インデックスはインクリメントされる
        {"start": 4.5, "end": 6.5, "text": "テストです"}  # 話者なし
    ]
    
    chunker.save_as_srt(segments, str(output_file))
    
    assert output_file.exists()
    content = output_file.read_text(encoding="utf-8")
    
    # 内容の検証 (2番目の要素がスキップされて連番が3になる挙動を検証)
    expected_lines = [
        "1",
        "00:00:01,500 --> 00:00:03,500",
        "話者A: こんにちは",
        "",
        "3",
        "00:00:04,500 --> 00:00:06,500",
        "テストです",
        ""
    ]
    assert content.replace("\r\n", "\n").strip() == "\n".join(expected_lines).strip()

    # 異常系: start/end が無効な型の場合
    bad_segments = [
        {"start": "bad", "end": None, "text": "エラー値テスト"}
    ]
    bad_output_file = tmp_path / "bad_output.srt"
    chunker.save_as_srt(bad_segments, str(bad_output_file))
    content_bad = bad_output_file.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:00,000" in content_bad

def test_chunk_segments_success_json_block():
    # Gemini APIが ```json ... ``` の形式でJSONリストを返す場合
    mock_client = MagicMock()
    chunker = GeminiSemanticChunker(client=mock_client)
    
    # モックのレスポンス設定
    mock_response = MagicMock()
    mock_response.text = '```json\n[\n  {"text": "整形されたテキスト", "start": 1.0, "end": 3.0, "speaker": "話者"}\n]\n```'
    mock_client.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments, video_theme="テストテーマ")
    
    assert len(result) == 1
    assert result[0]["text"] == "整形されたテキスト"
    assert result[0]["start"] == 1.0
    assert result[0]["end"] == 3.0
    assert result[0]["speaker"] == "話者"

def test_chunk_segments_success_raw_json():
    # Gemini APIがマークダウンなしで生JSONリストを返す場合
    mock_client = MagicMock()
    chunker = GeminiSemanticChunker(client=mock_client)
    
    mock_response = MagicMock()
    mock_response.text = '[{"text": "テキストのみ", "start": 2.5, "end": 4.0}]'
    mock_client.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 2.5, "end": 4.0, "text": "テキストのみ"}]
    result = chunker.chunk_segments(whisper_segments)
    
    assert len(result) == 1
    assert result[0]["text"] == "テキストのみ"
    assert result[0]["start"] == 2.5
    assert result[0]["end"] == 4.0
    assert result[0]["speaker"] == ""  # デフォルトは空文字

def test_chunk_segments_error_api():
    # APIErrorが発生した場合、元のWhisperセグメントが返ること
    mock_client = MagicMock()
    chunker = GeminiSemanticChunker(client=mock_client)
    
    # genai.errors.APIError をシミュレート
    api_error = genai.errors.APIError("API Error Mock", 500)
    mock_client.models.generate_content.side_effect = api_error
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

def test_chunk_segments_error_json_decode():
    # JSONDecodeErrorが発生した場合、元のWhisperセグメントが返ること
    mock_client = MagicMock()
    chunker = GeminiSemanticChunker(client=mock_client)
    
    mock_response = MagicMock()
    mock_response.text = "invalid json text"
    mock_client.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

def test_chunk_segments_error_value_not_list():
    # Geminiのレスポンスがリストでない場合、元のWhisperセグメントが返ること
    mock_client = MagicMock()
    chunker = GeminiSemanticChunker(client=mock_client)
    
    mock_response = MagicMock()
    mock_response.text = '{"not": "a list"}'
    mock_client.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

def test_chunk_segments_error_value_item_not_dict():
    # リスト内の要素が辞書でない場合、元のWhisperセグメントが返ること
    mock_client = MagicMock()
    chunker = GeminiSemanticChunker(client=mock_client)
    
    mock_response = MagicMock()
    mock_response.text = '["not a dict"]'
    mock_client.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

def test_chunk_segments_error_value_missing_keys():
    # 必須キーが不足している場合、元のWhisperセグメントが返ること
    mock_client = MagicMock()
    chunker = GeminiSemanticChunker(client=mock_client)
    
    mock_response = MagicMock()
    mock_response.text = '[{"start": 1.0, "end": 3.0}]'  # textが欠如
    mock_client.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

def test_chunk_segments_error_value_invalid_times():
    # 時刻キーが数値に変換できない場合、元のWhisperセグメントが返ること
    mock_client = MagicMock()
    chunker = GeminiSemanticChunker(client=mock_client)
    
    mock_response = MagicMock()
    mock_response.text = '[{"text": "テスト", "start": "bad", "end": 3.0}]'
    mock_client.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

def test_chunk_segments_unexpected_exception():
    # 想定外の例外が発生した場合、元のWhisperセグメントが返ること
    mock_client = MagicMock()
    chunker = GeminiSemanticChunker(client=mock_client)
    
    mock_client.models.generate_content.side_effect = RuntimeError("unexpected error")
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

def test_process_whisper_to_semantic_srt(tmp_path):
    # テスト用Whisper JSONファイルの作成
    whisper_data = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "こんにちは"}
        ]
    }
    whisper_json_path = tmp_path / "whisper.json"
    with open(whisper_json_path, "w", encoding="utf-8") as f:
        json.dump(whisper_data, f)
        
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '[{"text": "こんにちは", "start": 0.0, "end": 2.0, "speaker": ""}]'
    mock_client.models.generate_content.return_value = mock_response
    
    # 正常系 (出力パス指定あり)
    output_srt_path = tmp_path / "output.srt"
    result_path = process_whisper_to_semantic_srt(
        str(whisper_json_path),
        video_theme="テーマ",
        output_srt_path=str(output_srt_path),
        client=mock_client
    )
    
    assert result_path == str(output_srt_path)
    assert output_srt_path.exists()
    
    # 正常系 (出力パス指定なし - デフォルトパス)
    result_path_default = process_whisper_to_semantic_srt(
        str(whisper_json_path),
        video_theme="テーマ",
        output_srt_path=None,
        client=mock_client
    )
    expected_default_path = tmp_path / "whisper_semantic.srt"
    assert result_path_default == str(expected_default_path)
    assert expected_default_path.exists()

    # 異常系：辞書でないJSONデータ
    whisper_bad_json_path = tmp_path / "whisper_bad.json"
    with open(whisper_bad_json_path, "w", encoding="utf-8") as f:
        f.write("[]")  # リスト構造
    
    result_path_bad = process_whisper_to_semantic_srt(
        str(whisper_bad_json_path),
        video_theme="テーマ",
        output_srt_path=None,
        client=mock_client
    )
    assert Path(result_path_bad).exists()

def test_main_block():
    # 引数が足りない場合 (sys.exit(1) が呼ばれる)
    with patch("sys.argv", ["gemini_semantic_chunker.py"]):
        with patch("gemini_client_factory.get_gemini_client", return_value=MagicMock()), \
             patch("model_registry.get_model", return_value="mocked-model", create=True):
            with pytest.raises(SystemExit) as exc_info:
                import runpy
                runpy.run_path(os.path.abspath(os.path.join(backend_dir, "gemini_semantic_chunker_deprecated.py")), run_name="__main__")
            assert exc_info.value.code == 1

    # 引数がある場合 (正常に動作して process_whisper_to_semantic_srt が呼ばれる)
    with patch("sys.argv", ["gemini_semantic_chunker.py", "dummy_whisper.json", "dummy_theme"]):
        # get_gemini_client が返すクライアントの generate_content をモックする
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[]'
        mock_client.models.generate_content.return_value = mock_response

        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
             patch("model_registry.get_model", return_value="mocked-model", create=True):
            # open をモックして dummy_whisper.json の読み込みと出力先への書き込みを安全にする
            m_open = mock_open(read_data='{"segments": [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]}')
            with patch("builtins.open", m_open):
                import runpy
                if "backend.gemini_semantic_chunker_deprecated" in sys.modules:
                    del sys.modules["backend.gemini_semantic_chunker_deprecated"]
                runpy.run_path(os.path.abspath(os.path.join(backend_dir, "gemini_semantic_chunker_deprecated.py")), run_name="__main__")
                
                # アサーション: mock_client の API が呼ばれたことを検証
                mock_client.models.generate_content.assert_called_once()

# 新規追加テストケース（例外型 (RuntimeError, OSError) への置換の検証）
def test_chunk_segments_os_error():
    # OSErrorが発生した場合、元のWhisperセグメントが返ること
    mock_client = MagicMock()
    chunker = GeminiSemanticChunker(client=mock_client)
    
    mock_client.models.generate_content.side_effect = OSError("network connection failure")
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

def test_chunk_segments_runtime_error():
    # RuntimeErrorが発生した場合、元のWhisperセグメントが返ること
    mock_client = MagicMock()
    chunker = GeminiSemanticChunker(client=mock_client)
    
    mock_client.models.generate_content.side_effect = RuntimeError("gemini platform error")
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

def test_chunk_segments_unhandled_exception():
    # 完全に補足対象外の例外が発生した場合、それがそのまま上にスローされることを検証
    mock_client = MagicMock()
    chunker = GeminiSemanticChunker(client=mock_client)
    
    mock_client.models.generate_content.side_effect = ZeroDivisionError("division by zero")
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    with pytest.raises(ZeroDivisionError):
        chunker.chunk_segments(whisper_segments)
