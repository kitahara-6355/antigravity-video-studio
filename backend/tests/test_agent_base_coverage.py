import sys
import os
import pytest
import json
from unittest.mock import patch, MagicMock, mock_open

# 親のワークスペースの backend ディレクトリを PYTHONPATH/sys.path に追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.agent_base import Agent, DummyClient

# テスト用の具象エージェントクラス
class MockAgent(Agent):
    def process(self, input_data: dict, context: dict, council_context=None) -> dict:
        return self._create_base_response()

# --- Load Soul & Save Soul 正常系および例外系の本質テスト ---

def test_load_soul_success():
    """_load_soulでファイルが存在し正常なJSONが読み込まれることを確認"""
    soul_data = {
        "stats": {"debates": 5, "wins": 2, "losses": 3},
        "bias_weight": 1.2,
        "history": [{"stance": "AGREE"}]
    }
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=json.dumps(soul_data))):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        assert agent.soul["stats"]["debates"] == 5
        assert agent.soul["bias_weight"] == 1.2
        assert len(agent.soul["history"]) == 1

def test_load_soul_json_decode_error_real():
    """_load_soulでJSONDecodeErrorが発生した際、クラッシュせずにデフォルトのsoulを返すことを確認"""
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("builtins.open", mock_open(read_data="invalid json")), \
         patch("os.path.exists", return_value=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        assert agent.soul["stats"]["debates"] == 0
        assert agent.soul["bias_weight"] == 1.0

def test_load_soul_os_error_real():
    """_load_soulでOSErrorが発生した際、クラッシュせずにデフォルトのsoulを返すことを確認"""
    mock_file = MagicMock()
    mock_file.__enter__.side_effect = OSError("Permission denied")
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("builtins.open", return_value=mock_file), \
         patch("os.path.exists", return_value=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        assert agent.soul["stats"]["debates"] == 0

def test_load_soul_unexpected_exception_real():
    """_load_soulで予期せぬ例外(Exception)が発生した際、クラッシュせずにデフォルトのsoulを返すことを確認"""
    mock_file = MagicMock()
    mock_file.__enter__.side_effect = ValueError("Unexpected memory failure")
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("builtins.open", return_value=mock_file), \
         patch("os.path.exists", return_value=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        assert agent.soul["stats"]["debates"] == 0

def test_save_soul_success():
    """_save_soulでファイルが正常に書き込まれることを確認"""
    m = mock_open()
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("builtins.open", m):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent.soul["stats"]["debates"] = 10
        agent._save_soul()
        m.assert_called_with(agent.soul_path, 'w', encoding='utf-8')
        handle = m()
        written = "".join(call.args[0] for call in handle.write.call_args_list)
        data = json.loads(written)
        assert data["stats"]["debates"] == 10

def test_save_soul_type_error():
    """_save_soulでTypeErrorが発生した際に適切にキャッチされることを確認"""
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("builtins.open", side_effect=TypeError("Type error during write")):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        # 例外が発生せずキャッチされること
        agent._save_soul()

def test_save_soul_unexpected_exception_real():
    """_save_soulで予期せぬ例外(Exception)が発生した際、エラーがキャッチされクラッシュしないことを確認"""
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("builtins.open", side_effect=ValueError("Disk failure")):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent._save_soul()

# --- learn() メソッドのテスト ---

def test_learn_approve_win():
    """learn()で勝利判定(APPROVE/AGREE)の際にstatsとhistoryが正しく更新されることを確認"""
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("agents.agent_base.Agent._save_soul") as mock_save:
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent.soul["stats"] = {"debates": 0, "wins": 0, "losses": 0}
        agent.learn("sess_1", "AGREE", "APPROVE", "Good job")
        
        assert agent.soul["stats"]["debates"] == 1
        assert agent.soul["stats"]["wins"] == 1
        assert agent.soul["stats"]["losses"] == 0
        assert len(agent.soul["history"]) == 1
        assert agent.soul["history"][0]["session_id"] == "sess_1"
        assert agent.soul["history"][0]["feedback"] == "Good job"
        mock_save.assert_called_once()

def test_learn_reject_loss_with_lesson():
    """learn()で敗北判定(REJECT/AGREE)の際にstats、lesson、bias_weightが更新されることを確認"""
    dummy_embedding = [0.1, 0.2, 0.3]
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("agents.agent_base.Agent._save_soul") as mock_save, \
         patch("agents.vector_utils.get_embedding", return_value=dummy_embedding) as mock_get_emb:
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent.soul["stats"] = {"debates": 0, "wins": 0, "losses": 0}
        agent.soul["bias_weight"] = 1.0
        
        agent.learn("sess_2", "AGREE", "REJECT", "Invalid parameters")
        
        assert agent.soul["stats"]["debates"] == 1
        assert agent.soul["stats"]["wins"] == 0
        assert agent.soul["stats"]["losses"] == 1
        assert agent.soul["bias_weight"] == 0.9  # 1.0 - 0.1
        assert "lessons" in agent.soul
        assert len(agent.soul["lessons"]) == 1
        assert agent.soul["lessons"][0]["text"] == "Avoid proposal that caused: Invalid parameters"
        assert agent.soul["lessons"][0]["embedding"] == dummy_embedding
        mock_get_emb.assert_called_once()
        mock_save.assert_called_once()

# --- recall() メソッドのテスト ---

def test_recall_empty_lessons_or_query():
    """recall()でクエリまたはレッスンが空の際にdistilled_rulesが返ることを確認"""
    with patch("agents.agent_base.get_gemini_client", return_value=None):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent.soul["distilled_rules"] = ["rule1", "rule2"]
        agent.soul["lessons"] = []
        
        assert agent.recall("") == ["rule1", "rule2"]
        assert agent.recall("some query") == ["rule1", "rule2"]

def test_recall_embedding_failure_fallback():
    """recall()でクエリのembedding取得失敗時に直近レッスンがフォールバックされることを確認"""
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("agents.vector_utils.get_embedding", return_value=None) as mock_get_emb:
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent.soul["distilled_rules"] = ["rule1"]
        agent.soul["lessons"] = [
            {"text": "lesson1"},
            {"text": "lesson2"},
            {"text": "lesson3"},
            {"text": "lesson4"}
        ]
        
        res = agent.recall("query", top_k=2)
        assert res == ["rule1", "lesson3", "lesson4"]
        mock_get_emb.assert_called_once()

def test_recall_cosine_similarity_sorting():
    """recall()でレッスン類似度順にソートされ、オンデマンドでembeddingが生成・保存されることを確認"""
    dummy_query_emb = [0.5, 0.5]
    embeddings = {
        "query": [0.5, 0.5],
        "lesson A": [1.0, 0.0],
        "lesson B": [0.0, 1.0],
        "lesson C": [0.7, 0.7]
    }
    
    def mock_get_embedding_fn(client, text):
        return embeddings.get(text, [0.0, 0.0])
        
    def mock_cosine_similarity_fn(emb1, emb2):
        return sum(x * y for x, y in zip(emb1, emb2))

    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("agents.vector_utils.get_embedding", side_effect=mock_get_embedding_fn) as mock_get_emb, \
         patch("agents.vector_utils.cosine_similarity", side_effect=mock_cosine_similarity_fn), \
         patch("agents.agent_base.Agent._save_soul") as mock_save:
        
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent.soul["distilled_rules"] = ["rule1"]
        agent.soul["lessons"] = [
            {"text": "lesson A", "embedding": embeddings["lesson A"]},
            {"text": "lesson B", "embedding": embeddings["lesson B"]},
            {"text": "lesson C"}  # embedding無し（オンデマンド生成対象）
        ]
        
        res = agent.recall("query", top_k=2)
        
        assert "lesson C" in res
        assert res[0] == "rule1"
        assert res[1] == "lesson C"
        assert res[2] in ("lesson A", "lesson B")
        mock_save.assert_called_once()

# --- _inject_council_findings() メソッド of テスト ---

def test_inject_council_findings():
    """_inject_council_findings()が自分以外のエージェントの知見を適切に整形することを確認"""
    with patch("agents.agent_base.get_gemini_client", return_value=None):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        
        assert agent._inject_council_findings(None) == ""
        
        mock_context = MagicMock()
        mock_context.get_findings.return_value = {}
        assert agent._inject_council_findings(mock_context) == ""
        
        mock_context.get_findings.return_value = {
            "TestAgent": "My own finding",
            "OtherAgent": "Other agent finding"
        }
        res = agent._inject_council_findings(mock_context)
        assert "OtherAgent" in res
        assert "Other agent finding" in res
        assert "TestAgent" not in res

# --- notify_thinking() & notify_done() メソッドのテスト ---

def test_notify_thinking_success():
    """notify_thinking()でWebSocketイベントが正しくブロードキャストされることを確認"""
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True
    
    # コルーチン警告を抑止するため、渡されたコルーチンを即座にクローズする
    def mock_create_task(coro):
        coro.close()
        return MagicMock()
    mock_loop.create_task.side_effect = mock_create_task
    
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("asyncio.get_running_loop", return_value=mock_loop), \
         patch("websocket_handler.broadcaster.update_council_state") as mock_update:
        agent = MockAgent("TestAgent", "Tester", "#123456")
        context = {"session_id": "session_abc"}
        
        agent.notify_thinking(context)
        
        mock_loop.create_task.assert_called_once()
        mock_update.assert_called_once_with("session_abc", "TestAgent", "thinking")

def test_notify_thinking_exception_handling():
    """notify_thinking()で例外が発生した際に適切にエラーハンドリングされクラッシュしないことを確認"""
    mock_loop = MagicMock()
    mock_loop.is_running.side_effect = RuntimeError("Async loop broken")
    mock_logger = MagicMock()
    
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("asyncio.get_running_loop", return_value=mock_loop), \
         patch("agents.agent_base.logger", mock_logger, create=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent.notify_thinking({"session_id": "session_abc"})
        mock_logger.debug.assert_called_once()

def test_notify_done_success():
    """notify_done()でWebSocketイベントが正しくブロードキャストされることを確認"""
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True
    
    # コルーチン警告を抑止するため、渡されたコルーチンを即座にクローズする
    def mock_create_task(coro):
        coro.close()
        return MagicMock()
    mock_loop.create_task.side_effect = mock_create_task
    
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("asyncio.get_running_loop", return_value=mock_loop), \
         patch("websocket_handler.broadcaster.update_council_state") as mock_update:
        agent = MockAgent("TestAgent", "Tester", "#123456")
        context = {"session_id": "session_abc"}
        result = {"stance": "AGREE", "summary": "Looks good"}
        
        agent.notify_done(context, result)
        
        mock_loop.create_task.assert_called_once()
        mock_update.assert_called_once_with("session_abc", "TestAgent", "done", "AGREE", "Looks good")

def test_notify_done_exception_handling():
    """notify_done()で例外が発生した際に適切にエラーハンドリングされクラッシュしないことを確認"""
    mock_loop = MagicMock()
    mock_loop.is_running.side_effect = RuntimeError("Async loop broken")
    mock_logger = MagicMock()
    
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("asyncio.get_running_loop", return_value=mock_loop), \
         patch("agents.agent_base.logger", mock_logger, create=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent.notify_done({"session_id": "session_abc"}, {"stance": "AGREE"})
        mock_logger.debug.assert_called_once()


# --- Specific Exception Handling Tests ---

def test_load_soul_type_error():
    """_load_soulでTypeErrorが発生した際、適切にキャッチされデフォルトのsoulが返ることを確認"""
    mock_file = MagicMock()
    mock_file.__enter__.side_effect = TypeError("Type error during load")
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("builtins.open", return_value=mock_file), \
         patch("os.path.exists", return_value=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        assert agent.soul["stats"]["debates"] == 0

def test_load_soul_value_error():
    """_load_soulでValueErrorが発生した際、適切にキャッチされデフォルトのsoulが返ることを確認"""
    mock_file = MagicMock()
    mock_file.__enter__.side_effect = ValueError("Value error during load")
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("builtins.open", return_value=mock_file), \
         patch("os.path.exists", return_value=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        assert agent.soul["stats"]["debates"] == 0

def test_save_soul_value_error():
    """_save_soulでValueErrorが発生した際、適切にキャッチされクラッシュしないことを確認"""
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("builtins.open", side_effect=ValueError("Value error during write")):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent._save_soul()

def test_notify_thinking_import_error():
    """notify_thinking()でImportErrorが発生した際、適切にキャッチされクラッシュしないことを確認"""
    mock_logger = MagicMock()
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("agents.agent_base.logger", mock_logger, create=True), \
         patch.dict("sys.modules", {"websocket_handler": None}):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent.notify_thinking({"session_id": "session_abc"})
        mock_logger.debug.assert_called_once()

def test_notify_thinking_attribute_error():
    """notify_thinking()でAttributeErrorが発生した際、適切にキャッチされクラッシュしないことを確認"""
    mock_logger = MagicMock()
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("agents.agent_base.logger", mock_logger, create=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        # trigger AttributeError by passing a context that raises AttributeError on get()
        bad_context = MagicMock()
        bad_context.get.side_effect = AttributeError("Context is invalid")
        agent.notify_thinking(bad_context)
        mock_logger.debug.assert_called_once()

def test_notify_thinking_type_error():
    """notify_thinking()でTypeErrorが発生した際、適切にキャッチされクラッシュしないことを確認"""
    mock_logger = MagicMock()
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("agents.agent_base.logger", mock_logger, create=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        # trigger TypeError by passing context of wrong type (e.g. an integer) which doesn't support get
        agent.notify_thinking(12345)
        mock_logger.debug.assert_called_once()

def test_notify_done_import_error():
    """notify_done()でImportErrorが発生した際、適切にキャッチされクラッシュしないことを確認"""
    mock_logger = MagicMock()
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("agents.agent_base.logger", mock_logger, create=True), \
         patch.dict("sys.modules", {"websocket_handler": None}):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent.notify_done({"session_id": "session_abc"}, {"stance": "AGREE"})
        mock_logger.debug.assert_called_once()

def test_notify_done_attribute_error():
    """notify_done()でAttributeErrorが発生した際、適切にキャッチされクラッシュしないことを確認"""
    mock_logger = MagicMock()
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("agents.agent_base.logger", mock_logger, create=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        bad_context = MagicMock()
        bad_context.get.side_effect = AttributeError("Context invalid")
        agent.notify_done(bad_context, {"stance": "AGREE"})
        mock_logger.debug.assert_called_once()

def test_notify_done_type_error():
    """notify_done()でTypeErrorが発生した際、適切にキャッチされクラッシュしないことを確認"""
    mock_logger = MagicMock()
    with patch("agents.agent_base.get_gemini_client", return_value=None), \
         patch("agents.agent_base.logger", mock_logger, create=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        agent.notify_done(12345, {"stance": "AGREE"})
        mock_logger.debug.assert_called_once()
