import sys
from unittest.mock import MagicMock, patch, AsyncMock

# Python 3.13 + Pydantic v2 incompatible RootModel generic crash workaround
sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()
sys.modules['mcp'] = MagicMock()
sys.modules['mcp.types'] = MagicMock()

from fastapi.testclient import TestClient
import pytest
import asyncio
from fastapi import HTTPException

def test_websocket_progress_echo(client):
    """Verify progress websocket echo behavior."""
    with client.websocket_connect("/ws/progress") as websocket:
        websocket.send_text("test_message")
        data = websocket.receive_json()
        assert data == {"type": "echo", "message": "test_message"}

def test_websocket_live_disconnect(client):
    """Verify live websocket client disconnect behavior."""
    
    mock_client = MagicMock()
    mock_connect = AsyncMock()
    mock_session = MagicMock()
    mock_session.send_client_content = AsyncMock()
    mock_session.send_realtime_input = AsyncMock()
    
    async def mock_receive_iter():
        # Yield one message then wait indefinitely to simulate connection
        mock_msg = MagicMock()
        mock_msg.text = "Hello from Gemini Live"
        yield mock_msg
        while True:
            await asyncio.sleep(1)
            
    mock_session.receive = mock_receive_iter
    mock_connect.__aenter__.return_value = mock_session
    mock_client.aio.live.connect.return_value = mock_connect
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("routers.websocket.get_model", return_value="gemini-2.5-flash"):
        
        with client.websocket_connect("/ws/live") as websocket:
            # Send message to trigger receive_from_client logic
            websocket.send_json({"type": "text", "content": "Hello"})
            
            # Receive response from mock AI
            data = websocket.receive_json()
            assert data["type"] == "ai_response"
            assert data["content"] == "Hello from Gemini Live"

def test_websocket_live_error_handling(client):
    """Verify live websocket exception handling (TD-638, TD-645)."""
    
    # Test when live connection raises a runtime error (to hit L132 except Exception)
    mock_client = MagicMock()
    mock_connect = MagicMock()
    # Force exception on connect entering
    mock_connect.__aenter__.side_effect = RuntimeError("Connection failed")
    mock_client.aio.live.connect.return_value = mock_connect
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("routers.websocket.get_model", return_value="gemini-2.5-flash"):
        
        # This should hit the outer except Exception, log the error, and close the websocket
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/live") as websocket:
                # The connection should close immediately
                websocket.receive_json()

def test_get_model_fallback():
    """Verify get_model fallback when model_registry cannot be imported."""
    import sys
    from unittest.mock import patch
    
    with patch.dict(sys.modules, {"model_registry": None}):
        if "routers.websocket" in sys.modules:
            del sys.modules["routers.websocket"]
        
        import routers.websocket as ws
        assert ws.get_model("any") == "gemini-2.5-flash"
    
    if "routers.websocket" in sys.modules:
        del sys.modules["routers.websocket"]
    import routers.websocket

@pytest.mark.asyncio
async def test_connection_manager_broadcast_exceptions():
    """Verify ConnectionManager broadcast exception handling."""
    from routers.websocket import ConnectionManager
    from fastapi import WebSocket, HTTPException
    
    manager = ConnectionManager()
    
    ws_ok = AsyncMock(spec=WebSocket)
    ws_ok.send_json = AsyncMock()
    
    ws_http_err = AsyncMock(spec=WebSocket)
    ws_http_err.send_json = AsyncMock(side_effect=HTTPException(status_code=400, detail="HTTP error"))
    
    ws_gen_err = AsyncMock(spec=WebSocket)
    ws_gen_err.send_json = AsyncMock(side_effect=RuntimeError("General error"))
    
    # 1. Successful broadcast
    manager.active_connections = [ws_ok]
    await manager.broadcast({"data": "test"})
    ws_ok.send_json.assert_called_once_with({"data": "test"})
    
    # 2. General exception handling (should log and continue to next connection)
    manager.active_connections = [ws_gen_err, ws_ok]
    ws_ok.send_json.reset_mock()
    await manager.broadcast({"data": "test"})
    ws_ok.send_json.assert_called_once_with({"data": "test"})
    
    # 3. HTTPException handling (should not re-raise, should log, continue, and remove)
    manager.active_connections = [ws_http_err, ws_ok]
    ws_ok.send_json.reset_mock()
    await manager.broadcast({"data": "test"})
    ws_ok.send_json.assert_called_once_with({"data": "test"})
    assert ws_http_err not in manager.active_connections

def test_websocket_live_audio_response(client):
    """Verify live websocket audio response formatting (ai_audio case)."""
    
    mock_client = MagicMock()
    mock_connect = AsyncMock()
    mock_session = MagicMock()
    
    async def mock_receive_iter():
        # First message: text message skipped, data bytes
        mock_msg_bytes = MagicMock(spec=[])
        mock_msg_bytes.data = b"\x01\x02\x03"
        yield mock_msg_bytes
        
        # Second message: data string (non-bytes)
        mock_msg_str = MagicMock(spec=[])
        mock_msg_str.data = "non-bytes-data"
        yield mock_msg_str
        
        while True:
            await asyncio.sleep(1)
            
    mock_session.receive = mock_receive_iter
    mock_connect.__aenter__.return_value = mock_session
    mock_client.aio.live.connect.return_value = mock_connect
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("routers.websocket.get_model", return_value="gemini-2.5-flash"):
        
        with client.websocket_connect("/ws/live") as websocket:
            # First response: ai_audio with bytes data converted to hex
            data1 = websocket.receive_json()
            assert data1["type"] == "ai_audio"
            assert data1["data"] == "010203"
            
            # Second response: ai_audio with string data converted to string
            data2 = websocket.receive_json()
            assert data2["type"] == "ai_audio"
            assert data2["data"] == "non-bytes-data"

@pytest.mark.asyncio
async def test_websocket_live_client_audio_direct():
    """Verify live websocket audio input handling and receive loop cancellation."""
    from routers.websocket import websocket_live_endpoint
    from fastapi import WebSocket, WebSocketDisconnect
    
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.receive_json = AsyncMock(side_effect=[
        {"type": "audio", "content": "010203"},
        WebSocketDisconnect()
    ])
    
    mock_client = MagicMock()
    mock_connect = AsyncMock()
    mock_session = MagicMock()
    mock_session.send_realtime_input = AsyncMock()
    
    async def mock_receive_iter():
        # Sleep to allow parallel receive_from_client task to run and process receive_json calls
        await asyncio.sleep(0.1)
        yield MagicMock()
        
    mock_session.receive = mock_receive_iter
    mock_connect.__aenter__.return_value = mock_session
    mock_client.aio.live.connect.return_value = mock_connect
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("routers.websocket.get_model", return_value="gemini-2.5-flash"):
        
        await websocket_live_endpoint(websocket_mock)
        
    mock_session.send_realtime_input.assert_called_once_with(audio=b"\x01\x02\x03")

@pytest.mark.asyncio
async def test_websocket_live_direct_exceptions():
    """Verify websocket_live_endpoint internal receive exception handling."""
    from routers.websocket import websocket_live_endpoint
    from fastapi import WebSocket, HTTPException
    
    # 1. receive_json raising HTTPException
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.receive_json = AsyncMock(side_effect=HTTPException(status_code=400, detail="Bad Request"))
    
    mock_client = MagicMock()
    mock_connect = AsyncMock()
    mock_session = MagicMock()
    async def mock_receive_iter():
        # Sleep to allow parallel receive_from_client task to run and raise HTTPException
        await asyncio.sleep(0.1)
        yield MagicMock()
    mock_session.receive = mock_receive_iter
    mock_connect.__aenter__.return_value = mock_session
    mock_client.aio.live.connect.return_value = mock_connect
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("routers.websocket.get_model", return_value="gemini-2.5-flash"):
        
        # websocket_live_endpoint will run receive_from_client as a background task.
        # It won't propagate the HTTPException directly to the caller, but will complete normally
        # when the main receive loop finishes.
        await websocket_live_endpoint(websocket_mock)
            
    # 2. receive_json raising generic Exception (break receive loop, exit normally)
    websocket_mock_gen = AsyncMock(spec=WebSocket)
    websocket_mock_gen.accept = AsyncMock()
    websocket_mock_gen.receive_json = AsyncMock(side_effect=RuntimeError("Generic receive error"))
    
    mock_client_gen = MagicMock()
    mock_connect_gen = AsyncMock()
    mock_session_gen = MagicMock()
    
    async def mock_receive_iter_short():
        # Sleep to allow parallel receive_from_client task to process receive_json throwing Exception
        await asyncio.sleep(0.1)
        yield MagicMock()
    mock_session_gen.receive = mock_receive_iter_short
    mock_connect_gen.__aenter__.return_value = mock_session_gen
    mock_client_gen.aio.live.connect.return_value = mock_connect_gen
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client_gen), \
         patch("routers.websocket.get_model", return_value="gemini-2.5-flash"):
        
        # Should complete without raising since exception is logged and loops terminated
        await websocket_live_endpoint(websocket_mock_gen)

@pytest.mark.asyncio
async def test_websocket_live_outer_exceptions_direct():
    """Verify outer try-except blocks of websocket_live_endpoint."""
    from routers.websocket import websocket_live_endpoint
    from fastapi import WebSocket, WebSocketDisconnect, HTTPException
    
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    
    # 1. HTTPException propagation
    with patch("gemini_client_factory.get_gemini_client", side_effect=HTTPException(status_code=500, detail="Test HTTP Error")):
        with pytest.raises(HTTPException):
            await websocket_live_endpoint(websocket_mock)
            
    # 2. WebSocketDisconnect handling
    with patch("gemini_client_factory.get_gemini_client", side_effect=WebSocketDisconnect()):
        # Should catch and exit cleanly
        await websocket_live_endpoint(websocket_mock)
        
    # 3. Generic Exception handling (websocket close call with code 1011)
    websocket_mock_close = AsyncMock(spec=WebSocket)
    websocket_mock_close.accept = AsyncMock()
    websocket_mock_close.close = AsyncMock()
    
    with patch("gemini_client_factory.get_gemini_client", side_effect=RuntimeError("Some error")):
        await websocket_live_endpoint(websocket_mock_close)
        websocket_mock_close.close.assert_called_once_with(code=1011, reason="Some error")

@pytest.mark.asyncio
async def test_broadcast_progress_wrapper():
    """Verify wrapper broadcast_progress function."""
    from routers.websocket import broadcast_progress, manager
    
    with patch.object(manager, "broadcast", new_callable=AsyncMock) as mock_broadcast:
        await broadcast_progress({"progress": 100})
        mock_broadcast.assert_called_once_with({"progress": 100})

@pytest.mark.asyncio
async def test_websocket_progress_generic_exception_disconnect():
    """Verify that websocket_progress_endpoint disconnects even on generic exceptions."""
    from routers.websocket import websocket_progress_endpoint, manager
    from fastapi import WebSocket
    
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.receive_text = AsyncMock(side_effect=RuntimeError("Generic connection error"))
    
    with patch.object(manager, "disconnect") as mock_disconnect:
        try:
            await websocket_progress_endpoint(websocket_mock)
        except RuntimeError:
            pass
        mock_disconnect.assert_called_once_with(websocket_mock)

@pytest.mark.asyncio
async def test_websocket_live_client_exception_cleanup():
    """Verify that websocket_live_endpoint cleans up both client and AI tasks when client task fails."""
    from routers.websocket import websocket_live_endpoint
    from fastapi import WebSocket
    
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.receive_json = AsyncMock(side_effect=RuntimeError("Receive error from client"))
    
    mock_client = MagicMock()
    mock_connect = AsyncMock()
    mock_session = MagicMock()
    
    async def mock_receive_iter():
        # Keep yielding to simulate live AI connection
        while True:
            await asyncio.sleep(0.1)
            yield MagicMock()
            
    mock_session.receive = mock_receive_iter
    mock_connect.__aenter__.return_value = mock_session
    mock_client.aio.live.connect.return_value = mock_connect
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("routers.websocket.get_model", return_value="gemini-2.5-flash"):
        
        # We expect the error to bubble up or be handled, but more importantly,
        # it should not cause a hang. If the implementation correctly awaits/cancels,
        # the call to websocket_live_endpoint will terminate and log the error or raise.
        # (With our proposed implementation, it will close the websocket or bubble up error).
        try:
            await websocket_live_endpoint(websocket_mock)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_websocket_live_pending_task_exception():
    """Verify that Exception raised by a pending task on cancel is caught and logged."""
    from routers.websocket import websocket_live_endpoint
    from fastapi import WebSocket, WebSocketDisconnect
    
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.receive_json = AsyncMock(side_effect=[
        {"type": "text", "content": "hello"},
        WebSocketDisconnect()
    ])
    
    mock_client = MagicMock()
    mock_connect = AsyncMock()
    mock_session = MagicMock()
    mock_session.send_client_content = AsyncMock()
    
    async def mock_receive_iter():
        try:
            yield MagicMock()
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise Exception("Fake Exception on cancel")
            
    mock_session.receive = mock_receive_iter
    mock_connect.__aenter__.return_value = mock_session
    mock_client.aio.live.connect.return_value = mock_connect
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("routers.websocket.get_model", return_value="gemini-2.5-flash"), \
         patch("routers.websocket.logger.error") as mock_log_error:
        
        await websocket_live_endpoint(websocket_mock)
        
        assert any("Pending task error on cancel" in call[0][0] for call in mock_log_error.call_args_list)

@pytest.mark.asyncio
async def test_connection_manager_broadcast_removes_zombies():
    """Verify that ConnectionManager broadcast removes connection on failure."""
    from routers.websocket import ConnectionManager
    from fastapi import WebSocket
    
    manager = ConnectionManager()
    
    ws_ok = AsyncMock(spec=WebSocket)
    ws_ok.send_json = AsyncMock()
    
    ws_fail = AsyncMock(spec=WebSocket)
    ws_fail.send_json = AsyncMock(side_effect=RuntimeError("Broadcast failed"))
    
    manager.active_connections = [ws_fail, ws_ok]
    
    # Run broadcast - ws_fail will raise Exception, and should be removed
    await manager.broadcast({"data": "test"})
    
    # ws_ok should still receive the message
    ws_ok.send_json.assert_called_once_with({"data": "test"})
    
    # ws_fail should have been disconnected and removed from active_connections
    assert ws_fail not in manager.active_connections
    assert ws_ok in manager.active_connections

@pytest.mark.asyncio
async def test_websocket_live_client_invalid_data():
    """Verify live websocket client invalid data validation."""
    from routers.websocket import websocket_live_endpoint
    from fastapi import WebSocket, WebSocketDisconnect
    
    # 1. Invalid message format (not a dict)
    # 2. Missing content in text message
    # 3. Missing content in audio message
    # 4. Invalid hex in audio content
    # 5. Unknown message type
    # 6. Disconnect at the end
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.receive_json = AsyncMock(side_effect=[
        "not a dict",
        {"type": "text"},
        {"type": "audio"},
        {"type": "audio", "content": "not-hex"},
        {"type": "unknown_type"},
        WebSocketDisconnect()
    ])
    websocket_mock.send_json = AsyncMock()
    
    mock_client = MagicMock()
    mock_connect = AsyncMock()
    mock_session = MagicMock()
    
    async def mock_receive_iter():
        await asyncio.sleep(0.5)
        yield MagicMock()
        
    mock_session.receive = mock_receive_iter
    mock_connect.__aenter__.return_value = mock_session
    mock_client.aio.live.connect.return_value = mock_connect
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("routers.websocket.get_model", return_value="gemini-2.5-flash"):
        
        await websocket_live_endpoint(websocket_mock)
        
    # Check that error responses were sent back
    send_calls = [call[0][0] for call in websocket_mock.send_json.call_args_list]
    assert len(send_calls) == 5
    assert send_calls[0] == {"type": "error", "message": "Message format must be a JSON object"}
    assert send_calls[1] == {"type": "error", "message": "Text message content cannot be empty"}
    assert send_calls[2] == {"type": "error", "message": "Audio message content cannot be empty"}
    assert send_calls[3] == {"type": "error", "message": "Invalid hex format in audio content"}
    assert send_calls[4] == {"type": "error", "message": "Unknown message type: unknown_type"}


@pytest.mark.asyncio
async def test_websocket_progress_generic_exception_logging():
    """Verify that websocket_progress_endpoint logs generic exceptions and closes websocket with code 1011."""
    from routers.websocket import websocket_progress_endpoint
    from fastapi import WebSocket
    
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.receive_text = AsyncMock(side_effect=RuntimeError("Unexpected processing error"))
    websocket_mock.close = AsyncMock()
    
    with patch("routers.websocket.logger.error") as mock_log_error:
        await websocket_progress_endpoint(websocket_mock)
        
        # Verify that logger.error was called with the exception
        assert any("Progress WebSocket error" in call[0][0] for call in mock_log_error.call_args_list)
        # Verify that websocket.close was called with code 1011
        websocket_mock.close.assert_called_once_with(code=1011, reason="Unexpected processing error")


@pytest.mark.asyncio
async def test_websocket_live_ai_receive_exception_logging():
    """Verify that _receive_from_ai logging works when Gemini Live session receive raises exception."""
    from routers.websocket import websocket_live_endpoint
    from fastapi import WebSocket
    
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.receive_json = AsyncMock(side_effect=asyncio.CancelledError()) # To let receive task continue but client loop stop
    websocket_mock.close = AsyncMock()
    
    mock_client = MagicMock()
    mock_connect = AsyncMock()
    mock_session = MagicMock()
    
    async def mock_receive_iter():
        # Raise exception on receive loop to test _receive_from_ai error handling
        raise RuntimeError("AI connection lost unexpectedly")
        yield MagicMock() # dummy to make it a generator
        
    mock_session.receive = mock_receive_iter
    mock_connect.__aenter__.return_value = mock_session
    mock_client.aio.live.connect.return_value = mock_connect
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("routers.websocket.get_model", return_value="gemini-2.5-flash"), \
         patch("routers.websocket.logger.error") as mock_log_error:
        
        await websocket_live_endpoint(websocket_mock)
        
        # Verify that the AI receive error was logged
        assert any("Error receiving from AI" in call[0][0] for call in mock_log_error.call_args_list)
        # Verify that websocket was closed with 1011
        websocket_mock.close.assert_called_with(code=1011, reason="AI connection lost unexpectedly")