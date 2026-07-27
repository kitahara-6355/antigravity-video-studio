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

# gemini_client_factory.get_gemini_client と model_registry.get_model が呼ばれたときにモックを返すようにする
mock_gemini_client = MagicMock()
with patch("gemini_client_factory.get_gemini_client", return_value=mock_gemini_client), \
     patch("model_registry.get_model", return_value="mocked-model", create=True):
    from gemini_semantic_chunker_deprecated import (
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
    # runpy を使用して、model_registry.get_model が例外を投げる状況下での評価を検証し、
    # 21-22 行目の except 節を安全にカバーする
    import sys
    old_module = sys.modules.get("gemini_semantic_chunker_deprecated")
    try:
        sys.modules.pop("gemini_semantic_chunker_deprecated", None)
        with patch("model_registry.get_model", side_effect=ImportError("mocked error"), create=True), \
             patch("gemini_client_factory.get_gemini_client", return_value=MagicMock()):
            # main ブロックが走って sys.exit(1) で終わるように引数を足りなくしておく
            with patch("sys.argv", ["gemini_semantic_chunker.py"]):
                with pytest.raises(SystemExit):
                    import runpy
                    runpy.run_module("gemini_semantic_chunker_deprecated", run_name="__main__")
    finally:
        if old_module is not None:
            sys.modules["gemini_semantic_chunker_deprecated"] = old_module

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
    
    # 丸め誤差を避けるため、.5 のタイムスタンプを使用
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

@patch("gemini_semantic_chunker_deprecated.client")
def test_chunk_segments_success_json_block(mock_client_instance):
    # Gemini APIが ```json ... ``` の形式でJSONリストを返す場合
    chunker = GeminiSemanticChunker()
    
    # モックのレスポンス設定
    mock_response = MagicMock()
    mock_response.text = '```json\n[\n  {"text": "整形されたテキスト", "start": 1.0, "end": 3.0, "speaker": "話者"}\n]\n```'
    mock_client_instance.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments, video_theme="テストテーマ")
    
    assert len(result) == 1
    assert result[0]["text"] == "整形されたテキスト"
    assert result[0]["start"] == 1.0
    assert result[0]["end"] == 3.0
    assert result[0]["speaker"] == "話者"

@patch("gemini_semantic_chunker_deprecated.client")
def test_chunk_segments_success_raw_json(mock_client_instance):
    # Gemini APIがマークダウンなしで生JSONリストを返す場合
    chunker = GeminiSemanticChunker()
    
    mock_response = MagicMock()
    mock_response.text = '[{"text": "テキストのみ", "start": 2.5, "end": 4.0}]'
    mock_client_instance.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 2.5, "end": 4.0, "text": "テキストのみ"}]
    result = chunker.chunk_segments(whisper_segments)
    
    assert len(result) == 1
    assert result[0]["text"] == "テキストのみ"
    assert result[0]["start"] == 2.5
    assert result[0]["end"] == 4.0
    assert result[0]["speaker"] == ""  # デフォルトは空文字

@patch("gemini_semantic_chunker_deprecated.client")
def test_chunk_segments_error_api(mock_client_instance):
    # APIErrorが発生した場合、元のWhisperセグメントが返ること
    chunker = GeminiSemanticChunker()
    
    # genai.errors.APIError をシミュレート
    api_error = genai.errors.APIError("API Error Mock", 500)
    mock_client_instance.models.generate_content.side_effect = api_error
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

@patch("gemini_semantic_chunker_deprecated.client")
def test_chunk_segments_error_json_decode(mock_client_instance):
    # JSONDecodeErrorが発生した場合、元のWhisperセグメントが返ること
    chunker = GeminiSemanticChunker()
    
    mock_response = MagicMock()
    mock_response.text = "invalid json text"
    mock_client_instance.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

@patch("gemini_semantic_chunker_deprecated.client")
def test_chunk_segments_error_value_not_list(mock_client_instance):
    # Geminiのレスポンスがリストでない場合、元のWhisperセグメントが返ること
    chunker = GeminiSemanticChunker()
    
    mock_response = MagicMock()
    mock_response.text = '{"not": "a list"}'
    mock_client_instance.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

@patch("gemini_semantic_chunker_deprecated.client")
def test_chunk_segments_error_value_item_not_dict(mock_client_instance):
    # リスト内の要素が辞書でない場合、元のWhisperセグメントが返ること
    chunker = GeminiSemanticChunker()
    
    mock_response = MagicMock()
    mock_response.text = '["not a dict"]'
    mock_client_instance.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

@patch("gemini_semantic_chunker_deprecated.client")
def test_chunk_segments_error_value_missing_keys(mock_client_instance):
    # 必須キーが不足している場合、元のWhisperセグメントが返ること
    chunker = GeminiSemanticChunker()
    
    mock_response = MagicMock()
    mock_response.text = '[{"start": 1.0, "end": 3.0}]'  # textが欠如
    mock_client_instance.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

@patch("gemini_semantic_chunker_deprecated.client")
def test_chunk_segments_error_value_invalid_times(mock_client_instance):
    # 時刻キーが数値に変換できない場合、元のWhisperセグメントが返ること
    chunker = GeminiSemanticChunker()
    
    mock_response = MagicMock()
    mock_response.text = '[{"text": "テスト", "start": "bad", "end": 3.0}]'
    mock_client_instance.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

@patch("gemini_semantic_chunker_deprecated.client")
def test_chunk_segments_unexpected_exception(mock_client_instance):
    # 想定外のExceptionが発生した場合、元のWhisperセグメントが返ること
    chunker = GeminiSemanticChunker()
    
    mock_client_instance.models.generate_content.side_effect = RuntimeError("unexpected error")
    
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    result = chunker.chunk_segments(whisper_segments)
    assert result == whisper_segments

@patch("gemini_semantic_chunker_deprecated.GeminiSemanticChunker.chunk_segments")
def test_process_whisper_to_semantic_srt(mock_chunk_segments, tmp_path):
    # テスト用Whisper JSONファイルの作成
    whisper_data = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "こんにちは"}
        ]
    }
    whisper_json_path = tmp_path / "whisper.json"
    with open(whisper_json_path, "w", encoding="utf-8") as f:
        json.dump(whisper_data, f)
        
    # モックのチャンクセグメント設定
    mock_chunk_segments.return_value = [
        {"start": 0.0, "end": 2.0, "text": "こんにちは", "speaker": ""}
    ]
    
    # 正常系 (出力パス指定あり)
    output_srt_path = tmp_path / "output.srt"
    result_path = process_whisper_to_semantic_srt(
        str(whisper_json_path),
        video_theme="テーマ",
        output_srt_path=str(output_srt_path)
    )
    
    assert result_path == str(output_srt_path)
    assert output_srt_path.exists()
    
    # 正常系 (出力パス指定なし - デフォルトパス)
    result_path_default = process_whisper_to_semantic_srt(
        str(whisper_json_path),
        video_theme="テーマ",
        output_srt_path=None
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
        output_srt_path=None
    )
    assert Path(result_path_bad).exists()

def test_main_block():
    import sys
    old_module = sys.modules.get("gemini_semantic_chunker_deprecated")
    try:
        # 引数が足りない場合 (sys.exit(1) が呼ばれる)
        sys.modules.pop("gemini_semantic_chunker_deprecated", None)
        with patch("sys.argv", ["gemini_semantic_chunker.py"]):
            with patch("gemini_client_factory.get_gemini_client", return_value=MagicMock()), \
                 patch("model_registry.get_model", return_value="mocked-model", create=True):
                with pytest.raises(SystemExit) as exc_info:
                    import runpy
                    runpy.run_module("gemini_semantic_chunker_deprecated", run_name="__main__")
                assert exc_info.value.code == 1

        # 引数がある場合 (正常に動作して process_whisper_to_semantic_srt が呼ばれる)
        sys.modules.pop("gemini_semantic_chunker_deprecated", None)
        with patch("sys.argv", ["gemini_semantic_chunker.py", "dummy_whisper.json", "dummy_theme"]):
            # get_gemini_client が返すクライアントの generate_content をモックする
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = '[]'
            mock_client.models.generate_content.return_value = mock_response

            with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
                 patch("model_registry.get_model", return_value="mocked-model", create=True):
                # open をモックして dummy_whisper.json の読み込みと出力先への書き込みを安全にする
                m_open = mock_open(read_data='{"segments": [{"start": 1.0, "end": 2.0, "text": "テスト"}]}')
                with patch("builtins.open", m_open):
                    import runpy
                    runpy.run_module("gemini_semantic_chunker_deprecated", run_name="__main__")
                    
                    # アサーション: mock_client の API が呼ばれたことを検証
                    mock_client.models.generate_content.assert_called_once()
    finally:
        if old_module is not None:
            sys.modules["gemini_semantic_chunker_deprecated"] = old_module


def test_process_whisper_to_semantic_srt_errors(tmp_path):
    # 1. ファイルが存在しない場合 (ValueError が発生すること)
    with pytest.raises(ValueError) as exc_info:
        process_whisper_to_semantic_srt(
            "non_existent_file.json",
            video_theme="テーマ",
            output_srt_path=None
        )
    assert "Whisper JSON file not found" in str(exc_info.value)

    # 2. JSONデコードに失敗する場合 (ValueError が発生すること)
    bad_json_file = tmp_path / "invalid_format.json"
    with open(bad_json_file, "w", encoding="utf-8") as f:
        f.write("{invalid json}")
    
    with pytest.raises(ValueError) as exc_info:
        process_whisper_to_semantic_srt(
            str(bad_json_file),
            video_theme="テーマ",
            output_srt_path=None
        )
    assert "Failed to decode Whisper JSON" in str(exc_info.value)

    # 3. OSError が発生する場合 (ValueError が発生すること)
    with patch("builtins.open", side_effect=OSError("Mock OS error")):
        with pytest.raises(ValueError) as exc_info:
            process_whisper_to_semantic_srt(
                "any_file.json",
                video_theme="テーマ",
                output_srt_path=None
            )
        assert "Error reading Whisper JSON" in str(exc_info.value)


@patch("gemini_semantic_chunker_deprecated.client")
def test_chunk_segments_uses_correct_model(mock_client_instance):
    custom_model = "my-special-model-123"
    chunker = GeminiSemanticChunker(model_name=custom_model)
    
    mock_response = MagicMock()
    mock_response.text = '[]'
    mock_client_instance.models.generate_content.return_value = mock_response
    
    whisper_segments = [{"start": 1.0, "end": 2.0, "text": "テスト"}]
    chunker.chunk_segments(whisper_segments)
    
    mock_client_instance.models.generate_content.assert_called_once()
    kwargs = mock_client_instance.models.generate_content.call_args[1]
    assert kwargs.get("model") == custom_model


def test_segments_to_text_empty():
    chunker = GeminiSemanticChunker()
    assert chunker._segments_to_text([]) == ""


def test_chunk_segments_invalid_input():
    chunker = GeminiSemanticChunker()
    # 非リスト入力
    assert chunker.chunk_segments(None) == []
    assert chunker.chunk_segments("invalid_type") == []
    # 空リスト入力
    assert chunker.chunk_segments([]) == []


@patch("gemini_semantic_chunker_deprecated.client")
def test_chunk_segments_programming_errors(mock_client_instance):
    chunker = GeminiSemanticChunker()
    
    # 1. responseがNoneの場合 (AttributeErrorが発生する)
    mock_client_instance.models.generate_content.return_value = None
    whisper_segments = [{"start": 1.0, "end": 3.0, "text": "元のテキスト"}]
    assert chunker.chunk_segments(whisper_segments) == whisper_segments

    # 2. response.text が float などの場合 (TypeErrorが発生する)
    mock_response = MagicMock()
    mock_response.text = 12345  # split() などが呼べず TypeError
    mock_client_instance.models.generate_content.return_value = mock_response
    assert chunker.chunk_segments(whisper_segments) == whisper_segments

