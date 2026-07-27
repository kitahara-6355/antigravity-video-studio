"""
backend/subtitle_burner.py 用のユニットテスト
"""

import sys
import os
import subprocess
import pytest
import runpy
from unittest.mock import MagicMock, patch

# テスト対象ディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def mock_path_exists_default():
    with patch("pathlib.Path.exists", return_value=True):
        yield

from subtitle_burner import burn_subtitle_simple


def test_burn_subtitle_simple_success_with_template():
    """template_configが正常にロードされ、カスタムスタイルが適用される正常系テスト"""
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ffmpeg"],
        returncode=0,
        stdout="ffmpeg output",
        stderr=""
    )
    
    mock_style = "FontSize=30,PrimaryColour=&H000000"
    with patch("template_config.template_config.get_subtitle_style", return_value=mock_style), \
         patch("subprocess.run", mock_run):
        
        res = burn_subtitle_simple("in.mp4", "sub.srt", "out.mp4")
        assert res == "out.mp4"
        
        called_args = mock_run.call_args[0][0]
        # スタイルが -vf subtitles 引数内に正しく渡されていることを確認
        vf_param = [arg for arg in called_args if "subtitles=" in arg][0]
        assert "force_style='FontSize=30,PrimaryColour=&H000000'" in vf_param


def test_burn_subtitle_simple_success_fallback():
    """template_configのインポート時にエラーが発生し、フォールバックのデフォルトスタイルが適用される正常系テスト"""
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ffmpeg"],
        returncode=0,
        stdout="ffmpeg output",
        stderr=""
    )
    
    with patch.dict("sys.modules", {"template_config": None}), \
         patch("subprocess.run", mock_run):
        
        res = burn_subtitle_simple("in.mp4", "sub.srt", "out.mp4")
        assert res == "out.mp4"
        
        called_args = mock_run.call_args[0][0]
        vf_param = [arg for arg in called_args if "subtitles=" in arg][0]
        # デフォルトスタイルが使用されていることを確認
        default_style = "FontSize=40,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,FontName=Yu Gothic UI,MarginV=72"
        assert f"force_style='{default_style}'" in vf_param


def test_burn_subtitle_simple_success_fallback_attribute_error():
    """template_configモジュールは存在するが、get_subtitle_styleメソッドが存在しない（AttributeError）場合にフォールバックされるかのテスト"""
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ffmpeg"],
        returncode=0,
        stdout="ffmpeg output",
        stderr=""
    )
    
    # get_subtitle_style属性を持たないダミーのオブジェクトを作成
    class DummyTemplateConfig:
        pass
        
    mock_module = DummyTemplateConfig()
    
    with patch.dict("sys.modules", {"template_config": mock_module}), \
         patch("subprocess.run", mock_run):
         
        res = burn_subtitle_simple("in.mp4", "sub.srt", "out.mp4")
        assert res == "out.mp4"
        
        called_args = mock_run.call_args[0][0]
        vf_param = [arg for arg in called_args if "subtitles=" in arg][0]
        default_style = "FontSize=40,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,FontName=Yu Gothic UI,MarginV=72"
        assert f"force_style='{default_style}'" in vf_param


def test_burn_subtitle_simple_path_escaping():
    """Windows形式のパス（バックスラッシュ、コロン）がFFmpegの要件通りに正しくエスケープされるかの検証"""
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ffmpeg"],
        returncode=0
    )
    
    with patch("subprocess.run", mock_run):
        burn_subtitle_simple("in.mp4", "C:\\path\\to\\sub.srt", "out.mp4")
        
        called_args = mock_run.call_args[0][0]
        vf_param = [arg for arg in called_args if "subtitles=" in arg][0]
        # \ が / に、: が \: に変換されていることを確認
        assert "subtitles='C\\:/path/to/sub.srt'" in vf_param


def test_burn_subtitle_simple_timeout():
    """FFmpeg実行がタイムアウトした場合にTimeoutExpired例外が発生することの検証"""
    mock_run = MagicMock()
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=300)
    
    with patch("subprocess.run", mock_run):
        with pytest.raises(subprocess.TimeoutExpired):
            burn_subtitle_simple("in.mp4", "sub.srt", "out.mp4")


def test_burn_subtitle_simple_called_process_error():
    """FFmpegがエラー終了した場合にCalledProcessError例外が発生することの検証"""
    mock_run = MagicMock()
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ffmpeg"],
        stderr="FFmpeg error detail message"
    )
    
    with patch("subprocess.run", mock_run):
        with pytest.raises(subprocess.CalledProcessError):
            burn_subtitle_simple("in.mp4", "sub.srt", "out.mp4")


def test_subtitle_burner_main_block():
    """subtitle_burner.pyの if __name__ == '__main__': ブロックの網羅"""
    burner_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "subtitle_burner.py"
    )
    
    # subprocess.run の mock
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ffmpeg"],
        returncode=0,
        stdout="ffmpeg output",
        stderr=""
    )
    
    # 1. 必要なファイルが存在し、burn_subtitle_simple が呼び出される場合
    mock_exists = MagicMock(side_effect=[True, True, True, True])
    
    with patch("pathlib.Path.exists", mock_exists), \
         patch("subprocess.run", mock_run):
        runpy.run_path(burner_path, run_name="__main__")
        
        mock_run.assert_called_once()
        
    # 2. ファイルが存在せず、burn_subtitle_simple が呼び出されない場合
    mock_exists_false = MagicMock(side_effect=[False, False])
    mock_run_2 = MagicMock()
    
    with patch("pathlib.Path.exists", mock_exists_false), \
         patch("subprocess.run", mock_run_2):
        runpy.run_path(burner_path, run_name="__main__")
        
        mock_run_2.assert_not_called()


def test_burn_subtitle_simple_path_escaping_edge_cases():
    """パスにスペース、日本語、フォワードスラッシュとバックスラッシュの混在、シングルクォートが含まれる場合のエスケープ処理検証"""
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ffmpeg"],
        returncode=0
    )
    
    with patch("subprocess.run", mock_run):
        # 1. スペースを含むパス
        burn_subtitle_simple("in.mp4", "C:\\path with spaces\\sub.srt", "out.mp4")
        called_args = mock_run.call_args[0][0]
        vf_param = [arg for arg in called_args if "subtitles=" in arg][0]
        assert "subtitles='C\\:/path with spaces/sub.srt'" in vf_param
        
        # 2. 日本語（マルチバイト）を含むパス
        burn_subtitle_simple("in.mp4", "C:\\path\\日本語\\sub.srt", "out.mp4")
        called_args = mock_run.call_args[0][0]
        vf_param = [arg for arg in called_args if "subtitles=" in arg][0]
        assert "subtitles='C\\:/path/日本語/sub.srt'" in vf_param

        # 3. フォワードスラッシュとバックスラッシュの混在
        burn_subtitle_simple("in.mp4", "C:/path\\to/sub.srt", "out.mp4")
        called_args = mock_run.call_args[0][0]
        vf_param = [arg for arg in called_args if "subtitles=" in arg][0]
        assert "subtitles='C\\:/path/to/sub.srt'" in vf_param

        # 4. シングルクォートを含むパス
        burn_subtitle_simple("in.mp4", "C:\\path's\\sub.srt", "out.mp4")
        called_args = mock_run.call_args[0][0]
        vf_param = [arg for arg in called_args if "subtitles=" in arg][0]
        assert "subtitles='C\\:/path'\\\\''s/sub.srt'" in vf_param


def test_burn_subtitle_simple_logging(caplog):
    """正常系、タイムアウト時、エラー時のロギングメッセージとレベルの検証"""
    import logging
    caplog.set_level(logging.INFO)
    
    # 1. 正常系
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ffmpeg"],
        returncode=0,
        stdout="ffmpeg output",
        stderr=""
    )
    with patch("subprocess.run", mock_run):
        caplog.clear()
        burn_subtitle_simple("in.mp4", "sub.srt", "out_log.mp4")
        
        log_records = [(r.levelname, r.message) for r in caplog.records]
        assert ("INFO", "Burning subtitles...") in log_records
        assert ("INFO", "  Video: in.mp4") in log_records
        assert ("INFO", "  SRT: sub.srt") in log_records
        assert ("INFO", "✅ Subtitle burned: out_log.mp4") in log_records

    # 2. タイムアウト時
    mock_run_timeout = MagicMock()
    mock_run_timeout.side_effect = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=300)
    with patch("subprocess.run", mock_run_timeout):
        caplog.clear()
        with pytest.raises(subprocess.TimeoutExpired):
            burn_subtitle_simple("in.mp4", "sub.srt", "out_log.mp4")
            
        log_records = [(r.levelname, r.message) for r in caplog.records]
        assert ("ERROR", "Timeout: 字幕焼き込みが5分以内に完了しませんでした") in log_records

    # 3. エラー終了時
    mock_run_error = MagicMock()
    mock_run_error.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ffmpeg"],
        stderr="FFmpeg specific error occurred"
    )
    with patch("subprocess.run", mock_run_error):
        caplog.clear()
        with pytest.raises(subprocess.CalledProcessError):
            burn_subtitle_simple("in.mp4", "sub.srt", "out_log.mp4")
            
        log_records = [(r.levelname, r.message) for r in caplog.records]
        assert ("ERROR", "FFmpeg error: FFmpeg specific error occurred") in log_records


def test_burn_subtitle_simple_arguments():
    """subprocess.run に渡されるコマンド引数の完全性検証"""
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ffmpeg"],
        returncode=0
    )
    
    with patch.dict("sys.modules", {"template_config": None}),          patch("subprocess.run", mock_run):
        burn_subtitle_simple("input_vid.mp4", "subtitle_file.srt", "output_vid.mp4")
        
        mock_run.assert_called_once()
        called_cmd = mock_run.call_args[0][0]
        
        expected_cmd = [
            "ffmpeg",
            "-i", "input_vid.mp4",
            "-vf", "subtitles='subtitle_file.srt':force_style='FontSize=40,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,FontName=Yu Gothic UI,MarginV=72'",
            "-c:a", "copy",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-y",
            "output_vid.mp4"
        ]
        
        assert called_cmd == expected_cmd


def test_burn_subtitle_simple_input_video_not_found():
    """入力動画ファイルが存在しない場合に FileNotFoundError が発生することの検証"""
    with patch("pathlib.Path.exists", side_effect=[False, True]):
        with pytest.raises(FileNotFoundError) as exc_info:
            burn_subtitle_simple("non_existent_video.mp4", "sub.srt", "out.mp4")
        assert "Input video file not found" in str(exc_info.value)


def test_burn_subtitle_simple_srt_not_found():
    """SRTファイルが存在しない場合に FileNotFoundError が発生することの検証"""
    with patch("pathlib.Path.exists", side_effect=[True, False]):
        with pytest.raises(FileNotFoundError) as exc_info:
            burn_subtitle_simple("in.mp4", "non_existent_sub.srt", "out.mp4")
        assert "SRT subtitle file not found" in str(exc_info.value)


def test_burn_subtitle_simple_path_escaping_complex_symbols():
    """Windowsパスに複雑な記号（%, $, &, (, ), commas, brackets）が含まれる場合のエスケープ処理検証"""
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ffmpeg"],
        returncode=0
    )
    
    with patch("subprocess.run", mock_run):
        complex_path = "C:\\path_$%&()[]_comma,\\sub.srt"
        burn_subtitle_simple("in.mp4", complex_path, "out.mp4")
        called_args = mock_run.call_args[0][0]
        vf_param = [arg for arg in called_args if "subtitles=" in arg][0]
        assert "subtitles='C\\:/path_$%&()[]_comma,/sub.srt'" in vf_param


def test_burn_subtitle_simple_success_fallback_other_exception():
    """template_configの取得中に予期せぬ例外が発生した際、呼び出し元に例外が正しく伝播するかの検証"""
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ffmpeg"],
        returncode=0,
        stdout="ffmpeg output",
        stderr=""
    )
    
    with patch("template_config.template_config.get_subtitle_style", side_effect=TypeError("Unexpected type error")), \
         patch("subprocess.run", mock_run):
         
        with pytest.raises(TypeError) as exc_info:
            burn_subtitle_simple("in.mp4", "sub.srt", "out.mp4")
        assert "Unexpected type error" in str(exc_info.value)

def test_burn_subtitle_simple_ffmpeg_not_found(caplog):
    """FFmpegコマンドが見つからない場合（FileNotFoundError）に正しくログ出力して例外を再スローするかの検証"""
    import logging
    caplog.set_level(logging.INFO)
    
    mock_run = MagicMock()
    mock_run.side_effect = FileNotFoundError("[WinError 2] 指定されたファイルが見つかりません。")
    
    with patch("subprocess.run", mock_run):
        caplog.clear()
        with pytest.raises(FileNotFoundError):
            burn_subtitle_simple("in.mp4", "sub.srt", "out.mp4")
            
        log_records = [(r.levelname, r.message) for r in caplog.records]
        assert any(
            r[0] == "ERROR" and "FFmpeg command not found. Please ensure FFmpeg is installed and added to PATH." in r[1]
            for r in log_records
        )


def test_burn_subtitle_simple_os_error(caplog):
    """FFmpeg実行中にその他のOSErrorが発生した場合に正しくログ出力して例外を再スローするかの検証"""
    import logging
    caplog.set_level(logging.INFO)
    
    mock_run = MagicMock()
    mock_run.side_effect = OSError("Permission denied")
    
    with patch("subprocess.run", mock_run):
        caplog.clear()
        with pytest.raises(OSError):
            burn_subtitle_simple("in.mp4", "sub.srt", "out.mp4")
            
        log_records = [(r.levelname, r.message) for r in caplog.records]
        assert any(
            r[0] == "ERROR" and "OS error occurred while running FFmpeg: Permission denied" in r[1]
            for r in log_records
        )


def test_burn_subtitle_simple_path_escaping_strict_alignment():
    """subtitle_burnerとsubtitle_previewの間でエスケープ仕様が完全に一致していることを検証"""
    complex_path = "C:\\path\\to\\ューザー's_字幕_test:file.srt"
    
    # burnerのエスケープ処理
    from subtitle_burner import _escape_srt_path as burner_escape
    burner_result = burner_escape(complex_path)
    
    # previewのエスケープ処理（期待値としての実績値）
    expected_escaped_path = "C\\:/path/to/ューザー'\\\\''s_字幕_test\\:file.srt"
    
    assert burner_result == expected_escaped_path
