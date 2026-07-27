import pytest
import sys
import os
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# Setup paths
backend_dir = Path(__file__).resolve().parents[2]
archive_dir = backend_dir / "archives" / "archive_stable_v3.0_20260118_0953"

if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(archive_dir) not in sys.path:
    sys.path.insert(0, str(archive_dir))

# Mock modules that might not import cleanly or need mock implementation
# To avoid pollution, we can patch them during import or mock the sys.modules
sys.modules["proper_noun_dict"] = MagicMock()
sys.modules["subtitle_normalizer"] = MagicMock()
sys.modules["semantic_store"] = MagicMock()
sys.modules["telop_proposal_engine"] = MagicMock()
sys.modules["asset_library"] = MagicMock()
sys.modules["self_review_engine"] = MagicMock()
sys.modules["learning_loop"] = MagicMock()

# Import the target module
import importlib.util
module_path = archive_dir / "antigravity_pipeline.py"
spec = importlib.util.spec_from_file_location("antigravity_pipeline_archive", str(module_path))
pipeline_mod = importlib.util.module_from_spec(spec)
sys.modules["antigravity_pipeline_archive"] = pipeline_mod
spec.loader.exec_module(pipeline_mod)

from antigravity_pipeline_archive import AntigravityPipeline

def test_pipeline_status():
    pipeline = AntigravityPipeline()
    
    # Mock status check attributes
    pipeline_mod.proper_noun_dict.get_all_entries.return_value = [1, 2]
    pipeline_mod.proper_noun_dict.get_pending.return_value = [1]
    pipeline_mod.asset_library.assets = [1, 2, 3]
    pipeline_mod.learning_loop.get_pending_proposals.return_value = []
    
    status = pipeline.get_pipeline_status()
    assert status["proper_noun_entries"] == 2
    assert status["pending_confirmations"] == 1
    assert status["available_assets"] == 3
    assert status["pending_proposals"] == 0

def test_parse_srt_valid():
    pipeline = AntigravityPipeline()
    srt_content = """1
00:00:01,000 --> 00:00:04,500
Hello World

2
00:00:05,200 --> 00:00:08,000
Second segment
"""
    with patch("builtins.open", mock_open(read_data=srt_content)):
        segments = pipeline._parse_srt(Path("dummy.srt"))
        
        assert len(segments) == 2
        assert segments[0]["id"] == "seg_001"
        assert segments[0]["start"] == 1.0
        assert segments[0]["end"] == 4.5
        assert segments[0]["text"] == "Hello World"
        
        assert segments[1]["id"] == "seg_002"
        assert segments[1]["start"] == 5.2
        assert segments[1]["end"] == 8.0
        assert segments[1]["text"] == "Second segment"

def test_parse_srt_invalid_format():
    pipeline = AntigravityPipeline()
    # Invalid index and timestamps
    srt_content = """invalid_idx
not_a_timestamp
Hello World

2
00:00:05,200 --> 00:00:08,000
Second segment
"""
    with patch("builtins.open", mock_open(read_data=srt_content)):
        segments = pipeline._parse_srt(Path("dummy.srt"))
        
        # Should skip invalid block and parse the valid one
        assert len(segments) == 1
        assert segments[0]["id"] == "seg_002"

def test_process_srt_success(tmp_path):
    pipeline = AntigravityPipeline(output_dir=tmp_path)
    
    srt_content = """1
00:00:01,000 --> 00:00:04,500
Hello World
"""
    
    # Mocking pipeline functions
    pipeline_mod.apply_dictionary.return_value = ("Hello World", [])
    
    mock_semantic_store = MagicMock()
    mock_semantic_store.topics = [1]
    mock_semantic_store.key_moments = [1, 2]
    pipeline_mod.create_semantic_store.return_value = mock_semantic_store
    
    pipeline_mod.extract_telops.return_value = [{"text": "Hello"}]
    pipeline_mod.propose_scenes.return_value = [{"scene": "Scene 1"}]
    
    pipeline_mod.get_assets_for.return_value = {"available": [1], "missing": []}
    
    with patch("builtins.open", mock_open(read_data=srt_content)):
        result = pipeline.process_srt(Path("dummy.srt"))
        
        assert result["input"] == "dummy.srt"
        assert result["phases"]["phase_1"]["status"] == "completed"
        assert result["phases"]["phase_2"]["status"] == "completed"
        assert result["phases"]["phase_3"]["status"] == "completed"
        assert result["phases"]["phase_4"]["status"] == "completed"
