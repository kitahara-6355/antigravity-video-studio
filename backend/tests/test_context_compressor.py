import sys
from unittest.mock import MagicMock, patch
import pytest
from datetime import datetime

# ============================================================
# 外部依存モジュールのモック化
# ContextCompressor がインポートするモジュールを事前に sys.modules に登録
# ============================================================

mock_client = MagicMock()
mock_client_factory = MagicMock()
mock_client_factory.get_gemini_client.return_value = mock_client

mock_types = MagicMock()
mock_genai = MagicMock()
mock_genai.types = mock_types

sys.modules['gemini_client_factory'] = mock_client_factory
sys.modules['google'] = MagicMock()
sys.modules['google.genai'] = mock_genai

mock_facts_store = MagicMock()
mock_facts = MagicMock()
mock_facts.verified_facts_store = mock_facts_store
sys.modules['agents.memory.verified_facts'] = mock_facts

# ============================================================
# テスト対象モジュールのインポート
# ============================================================
from backend.agents.context_compressor import (
    ContextCompressor,
    Message,
    CompressedContext,
    context_compressor
)

@pytest.fixture(autouse=True)
def cleanup_mock_effects():
    # 各テスト実行前後に mock_client の side_effect をリセットする
    mock_client.models.generate_content.side_effect = None
    mock_client.models.generate_content.return_value = MagicMock()
    yield
    mock_client.models.generate_content.side_effect = None


def test_compressor_init():
    compressor = ContextCompressor(token_limit=1000, autocompact_threshold=0.5, fullcompact_threshold=0.8)
    assert compressor.token_limit == 1000
    assert compressor.autocompact_threshold == 0.5
    assert compressor.fullcompact_threshold == 0.8
    assert compressor._consecutive_failures == 0


def test_estimate_tokens():
    compressor = ContextCompressor()
    assert compressor.estimate_tokens("12345678") == 2
    assert compressor.estimate_tokens("") == 0


def test_mark_protected():
    compressor = ContextCompressor()
    messages = [
        Message(role="user", content="hello", timestamp="1", metadata={"file_path": "a.py"}),
        Message(role="agent", content="world", timestamp="2", metadata={"file_path": "b.py"}),
    ]
    compressor._mark_protected(messages, ["a.py"])
    assert messages[0].is_protected is True
    assert messages[1].is_protected is False


def test_snip_logic():
    compressor = ContextCompressor()
    
    messages = [
        # index 0 (is_old=True)
        Message(role="tool_result", content="a" * 2001, timestamp="1", token_estimate=500), # Snip!
        # index 1 (is_old=True)
        Message(role="tool_result", content="a" * 1000, timestamp="2", token_estimate=250), # 残る (<=2000)
        # index 2 (is_old=True, but protected)
        Message(role="tool_result", content="a" * 2500, timestamp="3", token_estimate=600, is_protected=True), # 残る (protected)
        # index 3 (is_old=True, but empty)
        Message(role="user", content="", timestamp="4", token_estimate=10), # Snip! (empty)
        # index 4 (is_old=True, but blank)
        Message(role="user", content="   ", timestamp="5", token_estimate=10), # Snip! (blank)
        # index 5 (is_old=False)
        Message(role="tool_result", content="a" * 2500, timestamp="6", token_estimate=600), # 残る (not old)
    ]
    
    # len(messages) = 6. 20% limit = 1.2. index 0, 1 are is_old.
    result, new_tokens = compressor._snip(messages, 2000)
    
    # Snip items: index 0 (tool_result > 2000, is_old), index 3 (empty), index 4 (blank)
    # Remaining items: index 1 (<=2000), index 2 (protected), index 5 (not old)
    assert len(result) == 3
    assert result[0].timestamp == "2"
    assert result[1].timestamp == "3"
    assert result[2].timestamp == "6"


def test_microcompact_logic():
    compressor = ContextCompressor()
    messages = [
        Message(role="tool_result", content="a" * 6000, timestamp="1", token_estimate=1500),
        Message(role="tool_result", content="a" * 6000, timestamp="2", token_estimate=1500, is_protected=True),
        Message(role="user", content="a" * 6000, timestamp="3", token_estimate=1500),
    ]
    
    result, new_tokens = compressor._microcompact(messages, 4500)
    
    # 1番目は切り詰められる
    assert len(result[0].content) == 5000 + len("\n\n... [MicroCompact: 1000文字切り詰め]")
    assert "切り詰め]" in result[0].content
    
    # 2番目は保護されているので切り詰められない
    assert len(result[1].content) == 6000
    
    # 3番目は role != tool_result なので切り詰められない
    assert len(result[2].content) == 6000


def test_collapse_logic():
    compressor = ContextCompressor()
    
    # 通常マージ
    messages = [
        Message(role="agent", content="execute tool", timestamp="1", token_estimate=5),
        Message(role="tool_result", content="success", timestamp="2", token_estimate=5),
        Message(role="agent", content="analyse result", timestamp="3", token_estimate=5),
    ]
    result, new_tokens = compressor._collapse(messages, 15)
    assert len(result) == 1
    assert result[0].role == "agent"
    assert "[Collapsed]" in result[0].content
    
    # 保護されているためマージされない (tool_result)
    messages_protected = [
        Message(role="agent", content="execute tool", timestamp="1", token_estimate=5),
        Message(role="tool_result", content="success", timestamp="2", token_estimate=5, is_protected=True),
        Message(role="agent", content="analyse result", timestamp="3", token_estimate=5),
    ]
    result_p, _ = compressor._collapse(messages_protected, 15)
    assert len(result_p) == 3
    
    # 保護されているためマージされない (後続agent)
    messages_protected_agent = [
        Message(role="agent", content="execute tool", timestamp="1", token_estimate=5),
        Message(role="tool_result", content="success", timestamp="2", token_estimate=5),
        Message(role="agent", content="analyse result", timestamp="3", token_estimate=5, is_protected=True),
    ]
    result_pa, _ = compressor._collapse(messages_protected_agent, 15)
    assert len(result_pa) == 3

    # 境界外（メッセージ数が2個）
    messages_short = [
        Message(role="agent", content="execute tool", timestamp="1", token_estimate=5),
        Message(role="tool_result", content="success", timestamp="2", token_estimate=5),
    ]
    result_s, _ = compressor._collapse(messages_short, 10)
    assert len(result_s) == 2


def test_autocompact_success():
    compressor = ContextCompressor()
    messages = [
        Message(role="user", content="hello", timestamp="1", token_estimate=2),
        Message(role="agent", content="hi", timestamp="2", token_estimate=2, is_protected=True),
    ]
    
    mock_response = MagicMock()
    mock_response.text = "This is a summary"
    mock_client.models.generate_content.return_value = mock_response
    
    result, new_tokens, summary = compressor._autocompact(messages, 100)
    
    assert summary == "This is a summary"
    assert len(result) == 2  # 要約メッセージ + 保護メッセージ
    assert result[0].content == "[AutoCompact Summary]\nThis is a summary"
    assert result[1].is_protected is True


def test_autocompact_no_old_messages():
    compressor = ContextCompressor()
    messages = [
        Message(role="user", content="hello", timestamp="1", token_estimate=2, is_protected=True),
    ]
    result, new_tokens, summary = compressor._autocompact(messages, 100)
    assert result == messages
    assert summary is None


def test_autocompact_failure():
    compressor = ContextCompressor()
    messages = [
        Message(role="user", content="hello", timestamp="1", token_estimate=2),
    ]
    
    mock_client.models.generate_content.side_effect = Exception("API error")
    result, new_tokens, summary = compressor._autocompact(messages, 100)
    
    assert result == messages
    assert summary is None


def test_fullcompact_success():
    compressor = ContextCompressor()
    messages = [
        Message(role="user", content="hello", timestamp="1", token_estimate=2, is_protected=True),
        Message(role="user", content="world", timestamp="2", token_estimate=2, is_protected=True),
    ]
    
    mock_response = MagicMock()
    mock_response.text = "Ultra summary"
    mock_client.models.generate_content.return_value = mock_response
    mock_facts_store.get_facts_for_context.return_value = "Verified facts context"
    
    result, new_tokens, summary = compressor._fullcompact(messages, 100)
    
    assert summary == "Ultra summary"
    assert len(result) == 3  # core_msg + 2 protected messages
    assert "[FullCompact — 緊急圧縮実行]" in result[0].content
    assert "Verified facts context" in result[0].content
    assert "Ultra summary" in result[0].content


def test_fullcompact_failure():
    compressor = ContextCompressor()
    messages = [
        Message(role="user", content="hello", timestamp="1", token_estimate=2),
    ]
    
    mock_client.models.generate_content.side_effect = Exception("API error")
    result, new_tokens, summary = compressor._fullcompact(messages, 100)
    
    assert result == messages
    assert summary is None


def test_compress_no_action_needed():
    compressor = ContextCompressor(token_limit=1000)
    messages = [Message(role="user", content="hello", timestamp="1", token_estimate=2)]
    result = compressor.compress(messages, token_count=100)
    assert result.messages == messages
    assert result.compression_applied == []
    assert result.circuit_breaker_tripped is False


def test_circuit_breaker_tripping():
    compressor = ContextCompressor(token_limit=100)
    messages = [Message(role="user", content="hello", timestamp="1", token_estimate=2)]
    
    with patch.object(compressor, "_snip", side_effect=Exception("Snip error")):
        # 1回目
        res = compressor.compress(messages, token_count=90)
        assert compressor._consecutive_failures == 1
        assert res.circuit_breaker_tripped is False
        
        # 2回目
        res = compressor.compress(messages, token_count=90)
        assert compressor._consecutive_failures == 2
        assert res.circuit_breaker_tripped is False
        
        # 3回目
        res = compressor.compress(messages, token_count=90)
        assert compressor._consecutive_failures == 3
        assert res.circuit_breaker_tripped is False
        
        # 4回目: Circuit Breaker 発動
        res = compressor.compress(messages, token_count=90)
        assert res.circuit_breaker_tripped is True
        assert res.compression_applied == []


def test_compress_full_pipeline():
    compressor = ContextCompressor(token_limit=100)
    messages = [
        Message(role="user", content="hello", timestamp="1", token_estimate=10),
    ]
    
    with patch.object(compressor, "_snip", return_value=(messages, 110)) as mock_snip,          patch.object(compressor, "_microcompact", return_value=(messages, 110)) as mock_micro,          patch.object(compressor, "_collapse", return_value=(messages, 110)) as mock_collapse,          patch.object(compressor, "_autocompact", return_value=(messages, 110, "auto")) as mock_auto,          patch.object(compressor, "_fullcompact", return_value=(messages, 50, "full")) as mock_full:
         
         result = compressor.compress(messages, token_count=110, recent_files=["a.py"])
         
         mock_snip.assert_called_once()
         mock_micro.assert_called_once()
         mock_collapse.assert_called_once()
         mock_auto.assert_called_once()
         mock_full.assert_called_once()
         
         assert result.compression_applied == ["snip", "microcompact", "collapse", "autocompact", "fullcompact"]
         assert result.protected_files == ["a.py"]


def test_singleton_reset_circuit_breaker():
    context_compressor.reset_circuit_breaker()
    assert context_compressor._consecutive_failures == 0
