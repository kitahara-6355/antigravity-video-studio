"""

test_whisper_transcriber.py — WhisperTranscriber の単体テストおよびカバレッジ 100% 達成用のテストコード

"""



import sys

import os

import json

import pytest

from pathlib import Path

from unittest.mock import MagicMock, patch

import importlib

import runpy



# backend ディレクトリを sys.path に追加

backend_dir = Path(__file__).parent.parent

if str(backend_dir) not in sys.path:

    sys.path.insert(0, str(backend_dir))



# モックの準備

# faster_whisper がインポートできるようにダミーを sys.modules に追加する

mock_faster_whisper = MagicMock()

mock_whisper_model_class = MagicMock()

mock_faster_whisper.WhisperModel = mock_whisper_model_class

sys.modules['faster_whisper'] = mock_faster_whisper



# whisper_transcriber をインポート

import whisper_transcriber





def test_format_timestamp():

    """_format_timestamp の様々な境界値のテスト"""

    # 0秒

    assert whisper_transcriber.WhisperTranscriber._format_timestamp(0.0) == "00:00:00,000"

    # 通常の秒

    assert whisper_transcriber.WhisperTranscriber._format_timestamp(3661.123) == "01:01:01,123"

    # ミリ秒切り捨て境界

    assert whisper_transcriber.WhisperTranscriber._format_timestamp(86399.999) == "23:59:59,998"





def test_estimate_speakers():

    """estimate_speakers メソッドの検証"""

    transcriber = whisper_transcriber.WhisperTranscriber(model_size="dummy")

    segments = [{"id": 1, "start": 0.0, "end": 1.0, "text": "hello"}]

    res = transcriber.estimate_speakers(segments)

    assert res[0]["speaker"] == "話者_1"





def test_transcribe_video_file_not_found(tmp_path):

    """動画ファイルが存在しない場合の FileNotFoundError 検証"""

    transcriber = whisper_transcriber.WhisperTranscriber(model_size="dummy")

    nonexistent = tmp_path / "nonexistent.mp4"

    with pytest.raises(FileNotFoundError):

        transcriber.transcribe_video(str(nonexistent))





def test_transcribe_video_success_json_and_srt(tmp_path):

    """正常系での JSON & SRT 出力処理の検証"""

    # ダミー動画ファイル作成

    video_file = tmp_path / "test.mp4"

    video_file.write_bytes(b"\x00" * 100)



    # WhisperModel のモック設定

    mock_model_instance = MagicMock()

    mock_whisper_model_class.return_value = mock_model_instance



    mock_info = MagicMock()

    mock_info.language = "ja"

    mock_info.language_probability = 0.99

    mock_info.duration = 15.0



    # 10セグメント以上を返して、進捗表示 (i % 10 == 0) の分岐を通す

    dummy_segments = []

    for i in range(1, 12):

        seg = MagicMock()

        seg.start = (i - 1) * 1.0

        seg.end = i * 1.0

        seg.text = f" segment {i} "

        seg.avg_logprob = -0.5

        dummy_segments.append(seg)



    mock_model_instance.transcribe.return_value = (dummy_segments, mock_info)



    transcriber = whisper_transcriber.WhisperTranscriber(model_size="dummy")

    

    # srt 出力を検証

    output_data = transcriber.transcribe_video(str(video_file), language="ja", output_format="srt")



    assert output_data["language"] == "ja"

    assert len(output_data["segments"]) == 11

    assert output_data["segments"][0]["text"] == "segment 1"



    # JSON ファイルが保存されていることを確認

    json_path = tmp_path / "test_whisper.json"

    assert json_path.exists()

    with open(json_path, "r", encoding="utf-8") as f:

        saved_data = json.load(f)

        assert saved_data["language"] == "ja"



    # SRT ファイルが保存されていることを確認

    srt_path = tmp_path / "test_whisper.srt"

    assert srt_path.exists()

    with open(srt_path, "r", encoding="utf-8") as f:

        srt_content = f.read()

        assert "00:00:00,000 --> 00:00:01,000" in srt_content

        assert "segment 1" in srt_content





def test_transcribe_video_simple(tmp_path):

    """transcribe_video_simple 関数の検証"""

    video_file = tmp_path / "test_simple.mp4"

    video_file.write_bytes(b"\x00" * 100)



    # WhisperModel のモック設定

    mock_model_instance = MagicMock()

    mock_whisper_model_class.return_value = mock_model_instance



    mock_info = MagicMock()

    mock_info.language = "ja"

    mock_info.language_probability = 0.95

    mock_info.duration = 5.0



    seg = MagicMock()

    seg.start = 0.0

    seg.end = 2.0

    seg.text = "test"

    seg.avg_logprob = -0.1



    mock_model_instance.transcribe.return_value = ([seg], mock_info)



    # transcribe_video_simple を呼び出し

    json_path_str = whisper_transcriber.transcribe_video_simple(str(video_file), model_size="dummy")

    

    assert json_path_str == str(tmp_path / "test_simple_whisper.json")

    assert Path(json_path_str).exists()





def test_whisper_model_import_error_mock():

    """WhisperModel が None の場合に ImportError が発生することを確認"""

    with patch("whisper_transcriber.WhisperModel", None):

        with pytest.raises(ImportError) as exc_info:

            whisper_transcriber.WhisperTranscriber()

        assert "faster-whisper が必要です" in str(exc_info.value)





def test_whisper_model_failed_import_block():

    """faster_whisper インポートエラー時の警告表示分岐をテスト"""

    # sys.modules の 'faster_whisper' を一時的に削除し、インポートエラーが発生する状態でリロード

    with patch.dict(sys.modules, {'faster_whisper': None}):

        with patch("sys.modules", {**sys.modules, "faster_whisper": None}):

            with patch('builtins.print') as mock_print:

                # reload し、再インポート

                importlib.reload(whisper_transcriber)

                # 警告メッセージが出力されていることを確認

                mock_print.assert_any_call("⚠️ faster-whisper がインストールされていません")

                assert whisper_transcriber.WhisperModel is None



    # テスト後に元に戻すため、再度 reload

    sys.modules['faster_whisper'] = mock_faster_whisper

    importlib.reload(whisper_transcriber)





def test_main_execution_no_args():

    """引数なしで実行した場合 (sys.exit(1) を期待)"""

    script_path = str(Path(__file__).parent.parent / "whisper_transcriber.py")

    with patch.object(sys, 'argv', ['whisper_transcriber.py']):

        with pytest.raises(SystemExit) as exc_info:

            runpy.run_path(script_path, run_name="__main__")

        assert exc_info.value.code == 1





def test_main_execution_with_args(tmp_path):

    """引数ありで実行した場合 (正常終了を期待)"""

    script_path = str(Path(__file__).parent.parent / "whisper_transcriber.py")

    video_file = tmp_path / "test_main.mp4"

    video_file.write_bytes(b"\x00" * 100)



    # WhisperModel のモック設定

    mock_model_instance = MagicMock()

    mock_whisper_model_class.return_value = mock_model_instance



    mock_info = MagicMock()

    mock_info.language = "ja"

    mock_info.language_probability = 0.95

    mock_info.duration = 5.0



    seg = MagicMock()

    seg.start = 0.0

    seg.end = 2.0

    seg.text = "test"

    seg.avg_logprob = -0.1



    mock_model_instance.transcribe.return_value = ([seg], mock_info)



    with patch.object(sys, 'argv', ['whisper_transcriber.py', str(video_file)]):

        runpy.run_path(script_path, run_name="__main__")

        

    assert (tmp_path / "test_main_whisper.json").exists()





def test_format_timestamp_extreme_values():

    """_format_timestamp の極端な値（負の値、非常に大きな値）に対する検証"""

    assert whisper_transcriber.WhisperTranscriber._format_timestamp(-10.0) == "00:00:00,000"

    assert whisper_transcriber.WhisperTranscriber._format_timestamp(360010.5) == "100:00:10,500"



def test_format_timestamp_invalid_inputs():

    """_format_timestamp に None や無効な型の値が渡された場合の検証"""

    assert whisper_transcriber.WhisperTranscriber._format_timestamp(None) == "00:00:00,000"

    assert whisper_transcriber.WhisperTranscriber._format_timestamp("invalid") == "00:00:00,000"



def test_save_srt_invalid_segments(tmp_path):

    """_save_srt に無効なセグメントデータが渡された場合に ValueError が発生することの検証"""

    transcriber = whisper_transcriber.WhisperTranscriber(model_size="dummy")

    output_srt = tmp_path / "err_test.srt"

    

    # 辞書でない

    with pytest.raises(ValueError):

        transcriber._save_srt(["not_a_dict"], output_srt)

        

    # キーが不足している辞書

    with pytest.raises(ValueError):

        transcriber._save_srt([{"id": 1, "start": 0.0}], output_srt)



def test_main_execution_exceptions(tmp_path):

    """CLI 実行時に FileNotFoundError や例外が発生した場合のハンドリング検証"""

    script_path = str(Path(__file__).parent.parent / "whisper_transcriber.py")

    video_file = tmp_path / "nonexistent_main.mp4" # 存在しないパス



    # FileNotFoundError が発生し、sys.exit(1) となることを検証

    with patch.object(sys, 'argv', ['whisper_transcriber.py', str(video_file)]):

        with pytest.raises(SystemExit) as exc_info:

            runpy.run_path(script_path, run_name="__main__")

        assert exc_info.value.code == 1



    # WhisperTranscriptionError が発生した場合の検証

    video_file_exists = tmp_path / "existent_but_fails.mp4"

    video_file_exists.write_bytes(b"\x00" * 100)

    

    mock_model_instance = MagicMock()

    mock_whisper_model_class.return_value = mock_model_instance

    mock_model_instance.transcribe.side_effect = RuntimeError("Transcribe crash")



    with patch.object(sys, 'argv', ['whisper_transcriber.py', str(video_file_exists)]):

        with pytest.raises(SystemExit) as exc_info:

            runpy.run_path(script_path, run_name="__main__")

        assert exc_info.value.code == 1





def test_estimate_speakers_empty():

    """estimate_speakers に空配列を渡した場合の挙動"""

    transcriber = whisper_transcriber.WhisperTranscriber(model_size="dummy")

    assert transcriber.estimate_speakers([]) == []





def test_main_execution_multiple_args(tmp_path):

    """余分な引数が指定された状態で __main__ が実行された場合の挙動"""

    script_path = str(Path(__file__).parent.parent / "whisper_transcriber.py")

    video_file = tmp_path / "test_main_extra.mp4"

    video_file.write_bytes(b"\x00" * 100)



    # WhisperModel のモック設定

    mock_model_instance = MagicMock()

    mock_whisper_model_class.return_value = mock_model_instance



    mock_info = MagicMock()

    mock_info.language = "ja"

    mock_info.language_probability = 0.95

    mock_info.duration = 5.0



    seg = MagicMock()

    seg.start = 0.0

    seg.end = 2.0

    seg.text = "test"

    seg.avg_logprob = -0.1



    mock_model_instance.transcribe.return_value = ([seg], mock_info)



    # 3つ以上の引数を渡す

    with patch.object(sys, 'argv', ['whisper_transcriber.py', str(video_file), 'extra_argument']):

        runpy.run_path(script_path, run_name="__main__")

        

    assert (tmp_path / "test_main_extra_whisper.json").exists()





def test_whisper_model_init_exception():

    """WhisperModelロード時に例外が発生した場合に WhisperTranscriptionError が送出されることのテスト"""

    mock_whisper_model_class.side_effect = RuntimeError("Failed to load model")

    with pytest.raises(whisper_transcriber.WhisperTranscriptionError) as exc_info:

        whisper_transcriber.WhisperTranscriber(model_size="error-model")

    assert "Whisperモデルのロードに失敗しました" in str(exc_info.value)

    # 副作用をクリア

    mock_whisper_model_class.side_effect = None





def test_transcribe_video_exception(tmp_path):

    """transcribe実行中に例外が発生した場合に WhisperTranscriptionError が送出されることのテスト"""

    video_file = tmp_path / "test_err.mp4"

    video_file.write_bytes(b"\x00" * 100)



    mock_model_instance = MagicMock()

    mock_whisper_model_class.return_value = mock_model_instance

    mock_model_instance.transcribe.side_effect = RuntimeError("Transcribe failed")



    transcriber = whisper_transcriber.WhisperTranscriber(model_size="dummy")

    with pytest.raises(whisper_transcriber.WhisperTranscriptionError) as exc_info:

        transcriber.transcribe_video(str(video_file))

    assert "音声の文字起こし処理中にエラーが発生しました" in str(exc_info.value)





def test_transcribe_segment_exception(tmp_path):

    """セグメント処理中に例外が発生した場合に WhisperTranscriptionError が送出されることのテスト"""

    video_file = tmp_path / "test_seg_err.mp4"

    video_file.write_bytes(b"\x00" * 100)



    mock_model_instance = MagicMock()

    mock_whisper_model_class.return_value = mock_model_instance



    mock_info = MagicMock()

    mock_info.language = "ja"

    mock_info.language_probability = 0.95

    mock_info.duration = 5.0



    # segments が generator で、反復中に例外を発生させる

    def broken_generator():

        seg = MagicMock()

        seg.start = 0.0

        seg.end = 1.0

        seg.text = "broken"

        seg.avg_logprob = -0.1

        yield seg

        raise RuntimeError("Generator broken")



    mock_model_instance.transcribe.return_value = (broken_generator(), mock_info)



    transcriber = whisper_transcriber.WhisperTranscriber(model_size="dummy")

    with pytest.raises(whisper_transcriber.WhisperTranscriptionError) as exc_info:

        transcriber.transcribe_video(str(video_file))

    assert "セグメント処理中にエラーが発生しました" in str(exc_info.value)





def test_transcribe_video_json_write_error(tmp_path):

    """JSON保存時に例外が発生した場合に WhisperTranscriptionError が送出されることのテスト"""

    video_file = tmp_path / "test_json_err.mp4"

    video_file.write_bytes(b"\x00" * 100)



    mock_model_instance = MagicMock()

    mock_whisper_model_class.return_value = mock_model_instance

    mock_info = MagicMock()

    mock_info.language = "ja"

    mock_info.language_probability = 0.95

    mock_info.duration = 5.0

    mock_model_instance.transcribe.return_value = ([], mock_info)



    transcriber = whisper_transcriber.WhisperTranscriber(model_size="dummy")

    

    # openをモックして OSError をスローさせる

    with patch("builtins.open", side_effect=OSError("Write permission denied")):

        with pytest.raises(whisper_transcriber.WhisperTranscriptionError) as exc_info:

            transcriber.transcribe_video(str(video_file))

        assert "JSONファイルの保存に失敗しました" in str(exc_info.value)





def test_transcribe_video_srt_write_error(tmp_path):

    """SRT保存時に例外が発生した場合に WhisperTranscriptionError が送出されることのテスト"""

    video_file = tmp_path / "test_srt_err.mp4"

    video_file.write_bytes(b"\x00" * 100)



    mock_model_instance = MagicMock()

    mock_whisper_model_class.return_value = mock_model_instance

    mock_info = MagicMock()

    mock_info.language = "ja"

    mock_info.language_probability = 0.95

    mock_info.duration = 5.0

    

    seg = MagicMock()

    seg.start = 0.0

    seg.end = 2.0

    seg.text = "test srt err"

    seg.avg_logprob = -0.1

    mock_model_instance.transcribe.return_value = ([seg], mock_info)



    transcriber = whisper_transcriber.WhisperTranscriber(model_size="dummy")

    

    # _save_srt をモックして OSError をスローさせる

    with patch.object(transcriber, "_save_srt", side_effect=OSError("Disk full")):

        with pytest.raises(whisper_transcriber.WhisperTranscriptionError) as exc_info:

            transcriber.transcribe_video(str(video_file), output_format="srt")

        assert "SRTファイルの保存に失敗しました" in str(exc_info.value)





def test_transcribe_video_output_format_both(tmp_path):

    """output_format='both' の指定で JSON と SRT の両方が出力されることのテスト"""

    video_file = tmp_path / "test_both.mp4"

    video_file.write_bytes(b"\x00" * 100)



    mock_model_instance = MagicMock()

    mock_whisper_model_class.return_value = mock_model_instance

    mock_info = MagicMock()

    mock_info.language = "ja"

    mock_info.language_probability = 0.95

    mock_info.duration = 5.0



    seg = MagicMock()

    seg.start = 0.0

    seg.end = 2.0

    seg.text = "test both"

    seg.avg_logprob = -0.1

    mock_model_instance.transcribe.return_value = ([seg], mock_info)



    transcriber = whisper_transcriber.WhisperTranscriber(model_size="dummy")

    

    # transcribe_video を both で呼び出す

    output_data = transcriber.transcribe_video(str(video_file), output_format="both")



    assert (tmp_path / "test_both_whisper.json").exists()

    assert (tmp_path / "test_both_whisper.srt").exists()







def test_main_execution_unexpected_exception(tmp_path):

    """CLI 実行時に予期しない Exception が発生した場合のハンドリング検証"""

    script_path = str(Path(__file__).parent.parent / "whisper_transcriber.py")

    video_file = tmp_path / "unexpected_error.mp4"

    video_file.write_bytes(b"\x00" * 100)

    

    # transcribe メソッドが KeyError を投げるようにモック

    mock_model_instance = MagicMock()

    mock_whisper_model_class.return_value = mock_model_instance

    mock_model_instance.transcribe.side_effect = KeyError("Unexpected dictionary error")

    

    with patch.object(sys, 'argv', ['whisper_transcriber.py', str(video_file)]):

        with pytest.raises(SystemExit) as exc_info:

            runpy.run_path(script_path, run_name="__main__")

        assert exc_info.value.code == 1



def test_whisper_transcriber_gpu_auto_detection():
    """GPU自動検出およびパラメータ指定のテスト"""
    # 1. GPUが検出されない場合のデフォルト
    with patch("ctranslate2.get_cuda_device_count", return_value=0, create=True):
        mock_whisper_model_class.reset_mock()
        transcriber = whisper_transcriber.WhisperTranscriber()
        mock_whisper_model_class.assert_called_with(
            "large-v3",
            device="cpu",
            compute_type="int8"
        )

    # 2. GPUが検出された場合
    with patch("ctranslate2.get_cuda_device_count", return_value=1, create=True):
        mock_whisper_model_class.reset_mock()
        transcriber = whisper_transcriber.WhisperTranscriber()
        mock_whisper_model_class.assert_called_with(
            "large-v3",
            device="cuda",
            compute_type="float16"
        )

    # 3. パラメータを明示的に指定した場合
    mock_whisper_model_class.reset_mock()
    transcriber = whisper_transcriber.WhisperTranscriber(
        model_size="small",
        device="cuda",
        compute_type="int8_float16"
    )
    mock_whisper_model_class.assert_called_with(
        "small",
        device="cuda",
        compute_type="int8_float16"
    )


def test_estimate_speakers_by_gap():
    """発話間隔（gap）に基づく簡易話者推定のテスト"""
    transcriber = whisper_transcriber.WhisperTranscriber(model_size="dummy")
    
    # テストデータ: gap_threshold = 2.0 (デフォルト)
    # 1. 初期話者 label: 話者_1
    # 2. 2番目の発話: start 2.5 (前のendは 1.0) -> gap 1.5 < 2.0 -> 話者_1 のまま
    # 3. 3番目の発話: start 5.0 (前のendは 2.8) -> gap 2.2 > 2.0 -> 話者_2 へ交代
    # 4. 4番目の発話: start 6.0 (前のendは 5.5) -> gap 0.5 < 2.0 -> 話者_2 のまま
    # 5. 5番目の発話: start 9.0 (前のendは 6.5) -> gap 2.5 > 2.0 -> 話者_1 へ交代
    segments = [
        {"id": 1, "start": 0.0, "end": 1.0, "text": "A"},
        {"id": 2, "start": 2.5, "end": 2.8, "text": "B"},
        {"id": 3, "start": 5.0, "end": 5.5, "text": "C"},
        {"id": 4, "start": 6.0, "end": 6.5, "text": "D"},
        {"id": 5, "start": 9.0, "end": 10.0, "text": "E"},
    ]
    
    result = transcriber.estimate_speakers(segments, gap_threshold=2.0)
    assert result[0]["speaker"] == "話者_1"
    assert result[1]["speaker"] == "話者_1"
    assert result[2]["speaker"] == "話者_2"
    assert result[3]["speaker"] == "話者_2"
    assert result[4]["speaker"] == "話者_1"

    # 空リストの挙動
    assert transcriber.estimate_speakers([], gap_threshold=2.0) == []
    
    # 異常値・Noneチェックの堅牢性
    segments_with_none = [
        {"id": 1, "start": None, "end": 1.0, "text": "A"},
        {"id": 2, "start": 2.5, "end": None, "text": "B"},
        {"id": 3, "start": 5.0, "end": 5.5, "text": "C"},
    ]
    # start/endがNoneまたは存在しない場合は交代判断できず、直前と同じ話者になること
    result_none = transcriber.estimate_speakers(segments_with_none, gap_threshold=2.0)
    assert len(result_none) == 3


def test_whisper_transcriber_gpu_auto_detection_import_error():
    """ctranslate2インポートエラー時のGPU自動検出フォールバックテスト"""
    with patch.dict("sys.modules", {"ctranslate2": None}):
        mock_whisper_model_class.reset_mock()
        transcriber = whisper_transcriber.WhisperTranscriber()
        mock_whisper_model_class.assert_called_with(
            "large-v3",
            device="cpu",
            compute_type="int8"
        )
