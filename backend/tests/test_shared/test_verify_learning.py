import os
import sys
import pytest
from pathlib import Path
from unittest import mock

# 適切なパスを追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def test_verify_learning_flow():
    # Directorのモック作成
    mock_director_inst = mock.MagicMock()
    mock_director_inst.name = "TestDirector"
    mock_director_inst.soul_path = "/path/to/soul"
    mock_director_inst.recall.return_value = ["I hate jump cuts. Never use them."]
    mock_director_inst.process.return_value = {"detail": "Avoid jump cuts."}
    
    # モジュールキャッシュをクリアして、インポート時にパッチが適用されるようにする
    sys.modules.pop("backend.verify_learning", None)
    sys.modules.pop("agents.director", None)
    
    with mock.patch("agents.director.Director", return_value=mock_director_inst) as mock_class, \
         mock.patch("time.sleep"):  # 1秒のスリープをスキップ
        
        from backend.verify_learning import test_learning_loop
        
        test_learning_loop()
        
        # 呼ばれたことを確認
        mock_class.assert_called()
        mock_director_inst.learn.assert_called_once_with(
            mock.ANY, "AGREE", "REJECT", feedback_text="I hate jump cuts. Never use them."
        )
        mock_director_inst.recall.assert_called_once_with("jump cuts")
        mock_director_inst.process.assert_called_once_with(
            {"text": "How should I cut the video?"}, {}
        )

def test_verify_learning_main():
    mock_director_inst = mock.MagicMock()
    mock_director_inst.name = "TestDirector"
    mock_director_inst.recall.return_value = ["I hate jump cuts. Never use them."]
    mock_director_inst.process.return_value = {"detail": "Avoid jump cuts."}
    
    # モジュールキャッシュをクリア
    sys.modules.pop("backend.verify_learning", None)
    sys.modules.pop("agents.director", None)
    
    with mock.patch("agents.director.Director", return_value=mock_director_inst) as mock_class, \
         mock.patch("time.sleep"):
         
        import runpy
        runpy.run_module("backend.verify_learning", run_name="__main__")
        
        mock_director_inst.learn.assert_called_once()

def test_verify_learning_flow_failure():
    # Directorのモック作成（recallが空リストを返すことで、学習失敗時の処理をテスト）
    mock_director_inst = mock.MagicMock()
    mock_director_inst.name = "TestDirector"
    mock_director_inst.soul_path = "/path/to/soul"
    mock_director_inst.recall.return_value = []
    mock_director_inst.process.return_value = {"detail": "Avoid jump cuts."}
    
    # モジュールキャッシュをクリア
    sys.modules.pop("backend.verify_learning", None)
    sys.modules.pop("agents.director", None)
    
    with mock.patch("agents.director.Director", return_value=mock_director_inst) as mock_class, \
         mock.patch("time.sleep"):  # 1秒のスリープをスキップ
        
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


def test_verify_learning_process_exception():
    mock_director_inst = mock.MagicMock()
    mock_director_inst.name = "TestDirector"
    mock_director_inst.soul_path = "/path/to/soul"
    mock_director_inst.recall.return_value = ["I hate jump cuts. Never use them."]
    mock_director_inst.process.side_effect = Exception("LLM Error")
    
    sys.modules.pop("backend.verify_learning", None)
    sys.modules.pop("agents.director", None)
    
    with mock.patch("agents.director.Director", return_value=mock_director_inst) as mock_class, \
         mock.patch("time.sleep"):
        
        from backend.verify_learning import test_learning_loop
        
        with pytest.raises(Exception, match="LLM Error"):
            test_learning_loop()
 
 
def test_verify_learning_env_trigger():
    mock_director_inst = mock.MagicMock()
    mock_director_inst.name = "TestDirector"
    mock_director_inst.soul_path = "/path/to/soul"
    mock_director_inst.recall.return_value = ["I hate jump cuts. Never use them."]
    mock_director_inst.process.return_value = {"detail": "Avoid jump cuts."}
    
    sys.modules.pop("backend.verify_learning", None)
    sys.modules.pop("agents.director", None)
    
    with mock.patch("agents.director.Director", return_value=mock_director_inst), \
         mock.patch("time.sleep"), \
         mock.patch.dict(os.environ, {"TEST_VERIFY_LEARNING_MAIN": "1"}):
         
        # インポートするだけで自動実行されるはず
        import backend.verify_learning
        
        mock_director_inst.learn.assert_called_once()


def test_verify_learning_learn_exception():
    mock_director_inst = mock.MagicMock()
    mock_director_inst.name = "TestDirector"
    mock_director_inst.soul_path = "/path/to/soul"
    mock_director_inst.learn.side_effect = Exception("Learn Error")
    
    sys.modules.pop("backend.verify_learning", None)
    sys.modules.pop("agents.director", None)
    
    with mock.patch("agents.director.Director", return_value=mock_director_inst) as mock_class, \
         mock.patch("time.sleep"):
        
        from backend.verify_learning import test_learning_loop
        
        with pytest.raises(Exception, match="Learn Error"):
            test_learning_loop()
