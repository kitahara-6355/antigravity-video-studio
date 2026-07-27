# -*- coding: utf-8 -*-
import pytest
from unittest.mock import patch, MagicMock
import os
import sys

# パス設定
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inspect_latest import probe, main

def test_probe():
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = '{"format": {"duration": "1200.5"}}'
        mock_run.return_value = mock_result
        
        res = probe("dummy.mp4")
        assert res["format"]["duration"] == "1200.5"

def test_main_no_files():
    with patch("glob.glob") as mock_glob:
        mock_glob.return_value = []
        
        # files not found -> exits with 1
        ret = main()
        assert ret == 1

def test_main_success_normal_duration():
    with patch("glob.glob") as mock_glob, \
         patch("os.path.getsize") as mock_getsize, \
         patch("inspect_latest.probe") as mock_probe:
         
        # glob mock (finals and previews)
        mock_glob.side_effect = lambda pat: (
            ["/path/to/final_1.mp4"] if "final" in pat else ["/path/to/preview_1.mp4"]
        )
        mock_getsize.return_value = 100 * 1024 * 1024 # 100MB
        
        # probe mock responses
        mock_probe.side_effect = lambda path: (
            {
                "format": {"duration": "1200.0", "size": str(100 * 1024 * 1024)},
                "streams": [
                    {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720, "r_frame_rate": "30/1"},
                    {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100", "channels": 2}
                ]
            } if "final" in path else {
                "format": {"duration": "600.0", "size": str(50 * 1024 * 1024)}
            }
        )
        
        # normal duration (20min target is met)
        ret = main()
        assert ret == 0

def test_main_too_long():
    with patch("glob.glob") as mock_glob, \
         patch("os.path.getsize") as mock_getsize, \
         patch("inspect_latest.probe") as mock_probe:
         
        mock_glob.side_effect = lambda pat: (
            ["/path/to/final_1.mp4"] if "final" in pat else ["/path/to/preview_1.mp4"]
        )
        mock_getsize.return_value = 100 * 1024 * 1024
        
        # 31min duration (too long)
        mock_probe.side_effect = lambda path: (
            {
                "format": {"duration": "1900.0", "size": str(100 * 1024 * 1024)},
                "streams": []
            } if "final" in path else {
                "format": {"duration": "600.0", "size": str(50 * 1024 * 1024)}
            }
        )
        
        ret = main()
        assert ret == 0

def test_main_too_short():
    with patch("glob.glob") as mock_glob, \
         patch("os.path.getsize") as mock_getsize, \
         patch("inspect_latest.probe") as mock_probe:
         
        mock_glob.side_effect = lambda pat: (
            ["/path/to/final_1.mp4"] if "final" in pat else ["/path/to/preview_1.mp4"]
        )
        mock_getsize.return_value = 100 * 1024 * 1024
        
        # 8min duration (too short)
        mock_probe.side_effect = lambda path: (
            {
                "format": {"duration": "500.0", "size": str(100 * 1024 * 1024)},
                "streams": []
            } if "final" in path else {
                "format": {"duration": "600.0", "size": str(50 * 1024 * 1024)}
            }
        )
        
        ret = main()
        assert ret == 0

def test_main_probe_error():
    with patch("glob.glob") as mock_glob, \
         patch("os.path.getsize") as mock_getsize, \
         patch("inspect_latest.probe", side_effect=Exception("Probe failed")):
         
        mock_glob.side_effect = lambda pat: (
            ["/path/to/final_1.mp4"] if "final" in pat else ["/path/to/preview_1.mp4"]
        )
        mock_getsize.return_value = 100 * 1024 * 1024
        
        ret = main()
        assert ret == 1
