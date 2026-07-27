import os
import sys
import pytest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def test_scratch_verify_learning_flow():
    mock_director_inst = mock.MagicMock()
    mock_director_inst.name = "TestDirector"
    mock_director_inst.soul_path = "/path/to/soul"
    mock_director_inst.recall.return_value = ["I hate jump cuts. Never use them."]
    mock_director_inst.process.return_value = {"detail": "Avoid jump cuts."}
    
    sys.modules.pop("backend.verify_learning", None)
    sys.modules.pop("agents.director", None)
    
    with mock.patch("agents.director.Director", return_value=mock_director_inst) as mock_class, \
         mock.patch("time.sleep"):
        
        from backend.verify_learning import test_learning_loop
        test_learning_loop()
        
        mock_class.assert_called()
        mock_director_inst.learn.assert_called_once_with(
            mock.ANY, "AGREE", "REJECT", feedback_text="I hate jump cuts. Never use them."
        )
        mock_director_inst.recall.assert_called_once_with("jump cuts")
        mock_director_inst.process.assert_called_once_with(
            {"text": "How should I cut the video?"}, {}
        )

def test_scratch_verify_learning_main():
    mock_director_inst = mock.MagicMock()
    mock_director_inst.name = "TestDirector"
    mock_director_inst.recall.return_value = ["I hate jump cuts. Never use them."]
    mock_director_inst.process.return_value = {"detail": "Avoid jump cuts."}
    
    sys.modules.pop("backend.verify_learning", None)
    sys.modules.pop("agents.director", None)
    
    with mock.patch("agents.director.Director", return_value=mock_director_inst) as mock_class, \
         mock.patch("time.sleep"):
         
        import runpy
        runpy.run_module("backend.verify_learning", run_name="__main__")
        mock_director_inst.learn.assert_called_once()

def test_scratch_verify_learning_flow_failure():
    mock_director_inst = mock.MagicMock()
    mock_director_inst.name = "TestDirector"
    mock_director_inst.soul_path = "/path/to/soul"
    mock_director_inst.recall.return_value = []
    mock_director_inst.process.return_value = {"detail": "Avoid jump cuts."}
    
    sys.modules.pop("backend.verify_learning", None)
    sys.modules.pop("agents.director", None)
    
    with mock.patch("agents.director.Director", return_value=mock_director_inst) as mock_class, \
         mock.patch("time.sleep"):
        
        from backend.verify_learning import test_learning_loop
        test_learning_loop()
        
        mock_class.assert_called()
        mock_director_inst.learn.assert_called_once_with(
            mock.ANY, "AGREE", "REJECT", feedback_text="I hate jump cuts. Never use them."
        )
        mock_director_inst.recall.assert_called_once_with("jump cuts")
        mock_director_inst.process.assert_called_once_with(
            {"text": "How should I cut the video?"}, {}
        )
