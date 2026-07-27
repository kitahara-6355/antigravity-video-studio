"""
test_smart_cut_plugin_integration.py — Integration Tests for SmartCutPlugin and AutoEditorWrapper

This module tests the integration between SmartCutPlugin and the Auto-Editor CLI wrapper.
"""

import pytest
from unittest.mock import patch
from backend.plugins.smart_cut_plugin import SmartCutPlugin


@patch("backend.video_pipeline.auto_editor_wrapper.AutoEditorWrapper.run_smart_cut")
def test_smart_cut_plugin_run_smart_cut_success(mock_run_smart_cut):
    """Verify that SmartCutPlugin.run_smart_cut calls AutoEditorWrapper correctly and returns True."""
    mock_run_smart_cut.return_value = True
    
    plugin = SmartCutPlugin()
    result = plugin.run_smart_cut(
        input_path="input.mp4",
        output_path="output.mp4",
        threshold=0.05,
        margin="0.3s"
    )
    
    assert result is True
    mock_run_smart_cut.assert_called_once_with(
        input_path="input.mp4",
        output_path="output.mp4",
        threshold=0.05,
        margin="0.3s"
    )


@patch("backend.video_pipeline.auto_editor_wrapper.AutoEditorWrapper.run_smart_cut")
def test_smart_cut_plugin_run_smart_cut_failure(mock_run_smart_cut):
    """Verify that exceptions raised by AutoEditorWrapper propagate through SmartCutPlugin."""
    mock_run_smart_cut.side_effect = Exception("Auto-Editor execution error")
    
    plugin = SmartCutPlugin()
    with pytest.raises(Exception, match="Auto-Editor execution error"):
        plugin.run_smart_cut("input.mp4", "output.mp4")
