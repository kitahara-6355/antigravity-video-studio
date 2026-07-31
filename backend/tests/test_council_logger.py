import os
import json
import pytest
import shutil
import tempfile
import sys
from unittest.mock import patch, MagicMock

# プロジェクトルートとbackendをsys.pathの先頭に追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "backend"))

from backend.agents.council_logger import CouncilSessionLogger, council_logger

def test_council_session_logger_init():
    # カスタムディレクトリでの初期化
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = CouncilSessionLogger(archive_dir=tmpdir)
        assert logger.archive_dir == tmpdir
        assert os.path.exists(tmpdir)

def test_council_session_logger_init_creates_dir():
    # 存在しないディレクトリを指定した時に、自動作成されることを検証
    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent_dir = os.path.join(tmpdir, "new_archive_dir")
        assert not os.path.exists(non_existent_dir)
        
        logger = CouncilSessionLogger(archive_dir=non_existent_dir)
        assert logger.archive_dir == non_existent_dir
        assert os.path.exists(non_existent_dir)

def test_log_session_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = CouncilSessionLogger(archive_dir=tmpdir)
        
        session_id = "test-session-123456789"
        topic = "Test Topic"
        debate_data = [{"agent": "Analyst", "response": "stance"}]
        synthesis = {"proposal": "Test Proposal"}
        
        filepath = logger.log_session(session_id, topic, debate_data, synthesis)
        
        assert filepath is not None
        assert os.path.exists(filepath)
        
        # ファイルの中身の検証
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        assert data["session_id"] == session_id
        assert data["topic"] == topic
        assert data["debate_flow"] == debate_data
        assert data["synthesis"] == synthesis
        assert "timestamp" in data
        assert "datetime" in data

def test_log_session_with_wagamama_linkage():
    # wagamama_manager がインポート可能で、かつ link_council_session が呼ばれるテスト
    # モックを作成して sys.modules に登録する
    mock_wagamama = MagicMock()
    
    with patch.dict(sys.modules, {"backend.wagamama_manager": mock_wagamama}):
        # リロードせずに呼び出すとモックが使われる
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = CouncilSessionLogger(archive_dir=tmpdir)
            
            session_id = "test-session-wagamama"
            topic = "Wagamama Topic"
            debate_data = []
            synthesis = {"proposal": "Wagamama Proposal"}
            wagamama_id = "waga-123"
            
            # wagamama_manager をモックして link_council_session が呼ばれるか確認
            filepath = logger.log_session(session_id, topic, debate_data, synthesis, wagamama_id=wagamama_id)
            
            assert filepath is not None
            mock_wagamama.wagamama_manager.link_council_session.assert_called_once_with(
                wagamama_id, session_id, filepath, synthesis
            )

def test_log_session_wagamama_import_error():
    # wagamama_manager が ImportError になる場合のテスト
    # sys.modules から意図的に wagamama_manager を削除し、さらに import_mock で ImportError を発生させる
    with patch.dict(sys.modules, {"backend.wagamama_manager": None}):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = CouncilSessionLogger(archive_dir=tmpdir)
            
            session_id = "test-session-wagamama-error"
            topic = "Wagamama Error Topic"
            debate_data = []
            synthesis = {"proposal": "Wagamama Error Proposal"}
            wagamama_id = "waga-123"
            
            # インポートエラーになってもクラッシュせず、正常にファイルパスが返ること
            filepath = logger.log_session(session_id, topic, debate_data, synthesis, wagamama_id=wagamama_id)
            assert filepath is not None
            assert os.path.exists(filepath)

def test_log_session_os_error():
    # OSError が発生する場合（書き込み不可ディレクトリ）
    # 存在しないパスや読み取り専用のディレクトリを模倣
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = CouncilSessionLogger(archive_dir=tmpdir)
        
        session_id = "test-session-os-error"
        topic = "OS Error Topic"
        debate_data = []
        synthesis = {}
        
        # open をモックして OSError を発生させる
        with patch("builtins.open", side_effect=OSError("Read-only file system")):
            filepath = logger.log_session(session_id, topic, debate_data, synthesis)
            assert filepath is None

def test_log_session_serialization_error():
    # TypeError (シリアライズ不可データ) が発生する場合
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = CouncilSessionLogger(archive_dir=tmpdir)
        
        session_id = "test-session-serial-error"
        topic = "Serial Error Topic"
        
        # シリアライズできないオブジェクト（例: 関数やクラスインスタンス）を渡す
        class Unserializable:
            pass
            
        debate_data = [Unserializable()]
        synthesis = {}
        
        filepath = logger.log_session(session_id, topic, debate_data, synthesis)
        assert filepath is None

def test_default_instance():
    # デフォルトインスタンスの確認。
    # 既定の相対パスは writable_path で解決される。相対パスのままだと
    # 書き込み先がプロセスの起動ディレクトリ次第になり、import しただけで
    # リポジトリに archives/council_logs ができる。
    from path_resolver import writable_path
    assert isinstance(council_logger, CouncilSessionLogger)
    assert council_logger.archive_dir == str(writable_path("archives/council_logs"))

def test_log_session_wagamama_other_exception():
    # wagamama_managerのメソッド呼び出し時にImportError以外の例外（例: AttributeError）が発生した場合のテスト
    mock_wagamama = MagicMock()
    # find_matching_storyで例外を発生させる
    mock_wagamama.wagamama_manager.find_matching_story.side_effect = AttributeError("Mock attribute error")
    
    with patch.dict(sys.modules, {"backend.wagamama_manager": mock_wagamama}):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = CouncilSessionLogger(archive_dir=tmpdir)
            
            session_id = "test-session-wagamama-attr-error"
            topic = "Wagamama Attr Error Topic"
            debate_data = []
            synthesis = {"proposal": "Wagamama Attr Error Proposal"}
            
            # 例外が発生してもクラッシュせず、正常にファイルパスが返ること
            filepath = logger.log_session(session_id, topic, debate_data, synthesis)
            assert filepath is not None
            assert os.path.exists(filepath)

def test_log_session_none_session_id():
    # session_id が None の場合のテスト
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = CouncilSessionLogger(archive_dir=tmpdir)
        filepath = logger.log_session(None, "None Session ID Topic", [], {})
        assert filepath is not None
        assert os.path.exists(filepath)
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data["session_id"] is None
        assert "session_" in os.path.basename(filepath)

def test_log_session_int_session_id():
    # session_id が文字列以外（例: 整数）の場合のテスト
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = CouncilSessionLogger(archive_dir=tmpdir)
        filepath = logger.log_session(12345, "Int Session ID Topic", [], {})
        assert filepath is not None
        assert os.path.exists(filepath)
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data["session_id"] == 12345
        assert "session_" in os.path.basename(filepath)

def test_council_session_logger_init_invalid_dir():
    # 無効な archive_dir で初期化した際に ValueError が発生することを検証
    with pytest.raises(ValueError, match="archive_dir must be a non-empty string."):
        CouncilSessionLogger(archive_dir=None)
        
    with pytest.raises(ValueError, match="archive_dir must be a non-empty string."):
        CouncilSessionLogger(archive_dir="")
        
    with pytest.raises(ValueError, match="archive_dir must be a non-empty string."):
        CouncilSessionLogger(archive_dir="   ")
        
    with pytest.raises(ValueError, match="archive_dir must be a non-empty string."):
        CouncilSessionLogger(archive_dir=123)

