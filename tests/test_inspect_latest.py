import json
import os
import subprocess
import pytest
from unittest.mock import MagicMock, patch

from backend.inspect_latest import probe, main

def test_probe_success():
    mock_data = {"format": {"duration": "10.0"}}
    mock_run = MagicMock()
    mock_run.stdout = json.dumps(mock_data)
    
    with patch("subprocess.run", return_value=mock_run) as mock_sub:
        res = probe("dummy_path")
        assert res == mock_data
        mock_sub.assert_called_once()
        args = mock_sub.call_args[0][0]
        assert "ffprobe" in args
        assert "dummy_path" in args

def test_probe_failure():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=30)):
        with pytest.raises(subprocess.TimeoutExpired):
            probe("dummy_path")

def test_main_no_finals(capsys):
    with patch("glob.glob", return_value=[]):
        code = main()
        assert code == 1
        captured = capsys.readouterr()
        assert "No final files found." in captured.out

def test_main_os_error_getsize(capsys):
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else ["/path/to/preview_1.mp4"]), \
         patch("os.path.getsize", side_effect=OSError("file not found")), \
         patch("backend.inspect_latest.probe") as mock_probe:
        
        mock_probe.side_effect = [
            {"format": {"duration": "1000", "size": "10485760"}, "streams": []},
            {"format": {"duration": "100", "size": "1048576"}, "streams": []}
        ]
        
        code = main()
        assert code == 0
        captured = capsys.readouterr()
        assert "final_1.mp4: unknown size" in captured.out

def test_main_probe_final_filenotfound(capsys):
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else []), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe", side_effect=FileNotFoundError("no such file")):
         
        code = main()
        assert code == 1
        captured = capsys.readouterr()
        assert "ffprobe command not found for final:" in captured.out

def test_main_probe_final_subprocess_error(capsys):
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else []), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe", side_effect=subprocess.SubprocessError("subprocess failed")):
         
        code = main()
        assert code == 1
        captured = capsys.readouterr()
        assert "Subprocess error probing final:" in captured.out

def test_main_probe_final_json_error(capsys):
    import json
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else []), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe", side_effect=json.JSONDecodeError("msg", "doc", 0)):
         
        code = main()
        assert code == 1
        captured = capsys.readouterr()
        assert "Failed to parse probe JSON for final:" in captured.out

def test_main_no_previews(capsys):
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else []), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe") as mock_probe:
         
        mock_probe.return_value = {"format": {"duration": "1000", "size": "10485760"}, "streams": []}
        
        code = main()
        assert code == 1
        captured = capsys.readouterr()
        assert "No preview files found." in captured.out

def test_main_probe_preview_filenotfound(capsys):
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else ["/path/to/preview_1.mp4"]), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe") as mock_probe:
         
        mock_probe.side_effect = [
            {"format": {"duration": "1000", "size": "10485760"}, "streams": []},
            FileNotFoundError("no such file")
        ]
        
        code = main()
        assert code == 1
        captured = capsys.readouterr()
        assert "ffprobe command not found for preview:" in captured.out

def test_main_probe_preview_subprocess_error(capsys):
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else ["/path/to/preview_1.mp4"]), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe") as mock_probe:
         
        mock_probe.side_effect = [
            {"format": {"duration": "1000", "size": "10485760"}, "streams": []},
            subprocess.SubprocessError("subprocess failed")
        ]
        
        code = main()
        assert code == 1
        captured = capsys.readouterr()
        assert "Subprocess error probing preview:" in captured.out

def test_main_probe_preview_json_error(capsys):
    import json
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else ["/path/to/preview_1.mp4"]), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe") as mock_probe:
         
        mock_probe.side_effect = [
            {"format": {"duration": "1000", "size": "10485760"}, "streams": []},
            json.JSONDecodeError("msg", "doc", 0)
        ]
        
        code = main()
        assert code == 1
        captured = capsys.readouterr()
        assert "Failed to parse probe JSON for preview:" in captured.out

def test_main_success_verdict_too_long(capsys):
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else ["/path/to/preview_1.mp4"]), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe") as mock_probe:
         
        mock_probe.side_effect = [
            {
                "format": {"duration": "1900.5", "size": "20971520"},
                "streams": [
                    {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "r_frame_rate": "30/1"},
                    {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
                    {"codec_type": "subtitle"}
                ]
            },
            {
                "format": {"duration": "190.5", "size": "2097152"},
                "streams": []
            }
        ]
        
        code = main()
        assert code == 0
        captured = capsys.readouterr()
        assert "LATEST FINAL: final_1.mp4" in captured.out
        assert "Duration: 1900.5s" in captured.out
        assert "Size: 20.0MB" in captured.out
        assert "Video: h264 1920x1080 @ 30/1" in captured.out
        assert "Audio: aac 48000Hz 2ch" in captured.out
        assert "❌ STILL TOO LONG" in captured.out

def test_main_success_verdict_too_short(capsys):
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else ["/path/to/preview_1.mp4"]), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe") as mock_probe:
         
        mock_probe.side_effect = [
            {"format": {"duration": "500.0", "size": "5242880"}, "streams": []},
            {"format": {"duration": "50.0", "size": "524288"}, "streams": []}
        ]
        
        code = main()
        assert code == 0
        captured = capsys.readouterr()
        assert "⚠️ TOO SHORT" in captured.out

def test_main_success_verdict_ok(capsys):
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else ["/path/to/preview_1.mp4"]), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe") as mock_probe:
         
        mock_probe.side_effect = [
            {"format": {"duration": "1200.0", "size": "10485760"}, "streams": []},
            {"format": {"duration": "120.0", "size": "1048576"}, "streams": []}
        ]
        
        code = main()
        assert code == 0
        captured = capsys.readouterr()
        assert "✅ DURATION OK" in captured.out

def test_main_block():
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else ["/path/to/preview_1.mp4"]), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("subprocess.run") as mock_run, \
         patch("sys.exit") as mock_exit:
         
        mock_final = MagicMock()
        mock_final.stdout = '{"format": {"duration": "1200.0", "size": "10485760"}, "streams": []}'
        mock_final.returncode = 0
        
        mock_preview = MagicMock()
        mock_preview.stdout = '{"format": {"duration": "120.0", "size": "1048576"}, "streams": []}'
        mock_preview.returncode = 0
        
        mock_run.side_effect = [mock_final, mock_preview]
        
        import sys
        if "backend.inspect_latest" in sys.modules:
            del sys.modules["backend.inspect_latest"]
            
        import runpy
        runpy.run_module("backend.inspect_latest", run_name="__main__")
        
        mock_exit.assert_called_once_with(0)

def test_safe_float_exception():
    from backend.inspect_latest import safe_float
    assert safe_float("invalid") == 0.0
    assert safe_float(None, default=5.0) == 5.0
    assert safe_float([], default=-1.0) == -1.0

def test_safe_int_exception():
    from backend.inspect_latest import safe_int
    assert safe_int("invalid") == 0
    assert safe_int(None, default=10) == 10
    assert safe_int([], default=-5) == -5



def test_main_probe_final_unexpected_exception(capsys):
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else []), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe", side_effect=RuntimeError("unexpected error")):
         
        import sys
        m = sys.modules.get("backend.inspect_latest")
        current_main = m.main if m else main
        code = current_main()
        assert code == 1
        captured = capsys.readouterr()
        assert "Unexpected error probing final: unexpected error" in captured.out


def test_main_probe_final_exception_logging(capsys):
    # final動画のプローブ中に例外が発生した際、stderrに期待するログが出力されることを検証
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else []),          patch("os.path.getsize", return_value=1024*1024),          patch("backend.inspect_latest.probe", side_effect=RuntimeError("probe failure")):
         
        import sys
        m = sys.modules.get("backend.inspect_latest")
        current_main = m.main if m else main
        code = current_main()
        assert code == 1
        captured = capsys.readouterr()
        # stderrに出力されたエラーを確認
        assert "Error: Failed to probe final video: probe failure" in captured.err

def test_main_probe_preview_exception_logging(capsys):
    # preview動画のプローブ中に例外が発生した際、stderrに期待するログが出力されることを検証
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else ["/path/to/preview_1.mp4"]),          patch("os.path.getsize", return_value=1024*1024),          patch("backend.inspect_latest.probe") as mock_probe:
         
        # finalは成功、previewは例外
        mock_probe.side_effect = [
            {"format": {"duration": "1000", "size": "10485760"}, "streams": []},
            RuntimeError("preview probe failure")
        ]
        
        import sys
        m = sys.modules.get("backend.inspect_latest")
        current_main = m.main if m else main
        code = current_main()
        assert code == 1
        captured = capsys.readouterr()
        # stderrに出力されたエラーを確認
        assert "Error: Failed to probe preview video: preview probe failure" in captured.err

def test_main_probe_called_process_error_logging(capsys):
    # ffprobeが非ゼロ終了（CalledProcessError）した際、stderrが出力されることを検証
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else []), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe", side_effect=subprocess.CalledProcessError(1, "ffprobe", stderr="detailed error in stderr")):
         
        import sys
        m = sys.modules.get("backend.inspect_latest")
        current_main = m.main if m else main
        code = current_main()
        assert code == 1
        captured = capsys.readouterr()
        # stdoutにSubprocess errorが、stderrにffprobe stderrが出力されることを確認
        assert "Subprocess error probing final" in captured.out
        assert "ffprobe stderr: detailed error in stderr" in captured.err

def test_main_probe_timeout_expired_logging(capsys):
    # ffprobeがタイムアウトした際、タイムアウト値が出力されることを検証
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else []), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe", side_effect=subprocess.TimeoutExpired("ffprobe", 30)):
         
        import sys
        m = sys.modules.get("backend.inspect_latest")
        current_main = m.main if m else main
        code = current_main()
        assert code == 1
        captured = capsys.readouterr()
        assert "Subprocess timeout probing final (timeout=30s)" in captured.out

def test_main_probe_json_decode_error_preview_logging(capsys):
    # JSONパースエラーの際、パース対象データのプレビューが出力されることを検証
    import json
    invalid_json_doc = "{" + "A" * 150 # 100文字を超える不正なJSON
    with patch("glob.glob", side_effect=lambda pat: ["/path/to/final_1.mp4"] if "final_" in pat else []), \
         patch("os.path.getsize", return_value=1024*1024), \
         patch("backend.inspect_latest.probe", side_effect=json.JSONDecodeError("Expecting property name", invalid_json_doc, 1)):
         
        import sys
        m = sys.modules.get("backend.inspect_latest")
        current_main = m.main if m else main
        code = current_main()
        assert code == 1
        captured = capsys.readouterr()
        assert "Failed to parse probe JSON for final" in captured.out
        # プレビューが含まれていることを確認（100文字 + "..."）
        expected_preview = invalid_json_doc[:100] + "..."
        assert expected_preview in captured.out



def test_probe_video_safely_value_error(capsys):
    # probe_video_safely が ValueError をキャッチして再送することを検証
    from backend.inspect_latest import probe_video_safely
    with patch("backend.inspect_latest.probe", side_effect=ValueError("invalid value")):
        with pytest.raises(ValueError):
            probe_video_safely("dummy_path", "test_label")
        captured = capsys.readouterr()
        assert "Unexpected error probing test_label: invalid value" in captured.out

def test_probe_video_safely_os_error(capsys):
    # probe_video_safely が OSError をキャッチして再送することを検証
    from backend.inspect_latest import probe_video_safely
    with patch("backend.inspect_latest.probe", side_effect=PermissionError("permission denied")):
        with pytest.raises(OSError):
            probe_video_safely("dummy_path", "test_label")
        captured = capsys.readouterr()
        assert "Unexpected error probing test_label: permission denied" in captured.out
