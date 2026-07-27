import sys
from unittest.mock import patch, AsyncMock, MagicMock
# Pydantic 3.13 MRO ValueError を回避するため、不要な mcp モジュールをダミーモック化
sys.modules['mcp'] = MagicMock()

import pytest
import asyncio
import base64
from fastapi import HTTPException, WebSocketDisconnect, WebSocket
from routers.legacy_live_websocket import websocket_live_endpoint

@pytest.mark.asyncio
async def test_legacy_ws_text_and_audio_flow():
    """正常系: 接続後にテキストと音声、メディアを受信し、AIからの応答を送信する"""
    mock_brain = MagicMock()
    mock_brain._get_system_instruction.return_value = "Mock System Instruction"
    
    mock_handler = MagicMock()
    
    # WebSocket Mock
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.receive_json = AsyncMock(side_effect=[
        {"text": "Hello Live"},
        {"audio": "YXVkaW9fZGF0YQ=="},
        {"media": ["chunk1", "chunk2"]},
        WebSocketDisconnect() # 切断して receive ループを抜ける
    ])
    websocket_mock.send_json = AsyncMock()
    websocket_mock.close = AsyncMock()

    # LiveAPIHandler.run のモック
    async def mock_run(send_queue, ai_callback, system_instruction=None):
        assert system_instruction == "Mock System Instruction"
        
        # 1. "Hello Live" の受信とコールバック応答のテスト
        item1 = await send_queue.get()
        assert item1 == "Hello Live"
        
        msg1 = MagicMock()
        msg1.server_content = MagicMock()
        msg1.server_content.model_turn = MagicMock()
        part1 = MagicMock()
        part1.text = "Hello from AI"
        part1.inline_data = None
        msg1.server_content.model_turn.parts = [part1]
        await ai_callback(msg1)
        
        # 2. "audio" の受信とコールバック音声応答のテスト
        item2 = await send_queue.get()
        assert item2["data"] == "YXVkaW9fZGF0YQ=="
        
        msg2 = MagicMock()
        msg2.server_content = MagicMock()
        msg2.server_content.model_turn = MagicMock()
        part2 = MagicMock()
        part2.text = None
        part2.inline_data = MagicMock()
        part2.inline_data.data = b"ai_audio_response"
        msg2.server_content.model_turn.parts = [part2]
        await ai_callback(msg2)
        
        # 3. "media" の受信テスト
        item3 = await send_queue.get()
        assert item3 == "chunk1"
        item4 = await send_queue.get()
        assert item4 == "chunk2"

        # receive_from_client から None (切断シグナル) が入るのを待つ
        item_none = await send_queue.get()
        assert item_none is None

    mock_handler.run = AsyncMock(side_effect=mock_run)

    with patch("director_engine.DirectorBrain", return_value=mock_brain),          patch("live_api_handler.LiveAPIHandler", return_value=mock_handler):
        
        await websocket_live_endpoint(websocket_mock)
        
    websocket_mock.accept.assert_called_once()
    websocket_mock.close.assert_called_once()
    
    # 送信された JSON を確認
    assert websocket_mock.send_json.call_count == 2
    websocket_mock.send_json.assert_any_call({"text": "Hello from AI"})
    websocket_mock.send_json.assert_any_call({"audio": base64.b64encode(b"ai_audio_response").decode("utf-8")})

@pytest.mark.asyncio
async def test_legacy_ws_ai_callback_variations_and_exceptions():
    """ai_callback の様々なメッセージ構造と例外ハンドリングのテスト"""
    mock_brain = MagicMock()
    mock_brain._get_system_instruction.return_value = "Mock System Instruction"
    
    mock_handler = MagicMock()
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.receive_json = AsyncMock(side_effect=WebSocketDisconnect())
    websocket_mock.send_json = AsyncMock()
    websocket_mock.close = AsyncMock()

    # さまざまなメッセージ構造をテストする
    async def mock_run(send_queue, ai_callback, system_instruction=None):
        # 1. server_content がない
        msg_no_content = MagicMock(spec=[])
        await ai_callback(msg_no_content)
        
        # 2. model_turn がない
        msg_no_turn = MagicMock()
        msg_no_turn.server_content = MagicMock(spec=[])
        await ai_callback(msg_no_turn)
        
        # 3. parts が空
        msg_empty_parts = MagicMock()
        msg_empty_parts.server_content.model_turn.parts = []
        await ai_callback(msg_empty_parts)
        
        # 4. text と inline_data の両方が None
        msg_none_parts = MagicMock()
        part = MagicMock()
        part.text = None
        part.inline_data = None
        msg_none_parts.server_content.model_turn.parts = [part]
        await ai_callback(msg_none_parts)

        # 5. HTTPException 発生
        websocket_mock.send_json.side_effect = HTTPException(status_code=400, detail="HTTP Error")
        msg_valid = MagicMock()
        part_valid = MagicMock()
        part_valid.text = "Error test"
        part_valid.inline_data = None
        msg_valid.server_content.model_turn.parts = [part_valid]
        
        with pytest.raises(HTTPException):
            await ai_callback(msg_valid)
            
        # 6. 一般例外発生
        websocket_mock.send_json.side_effect = Exception("General send error")
        await ai_callback(msg_valid)

        # 終了シグナル待ちをシミュレート
        await send_queue.get()

    mock_handler.run = AsyncMock(side_effect=mock_run)

    with patch("director_engine.DirectorBrain", return_value=mock_brain),          patch("live_api_handler.LiveAPIHandler", return_value=mock_handler):
        
        await websocket_live_endpoint(websocket_mock)
        
    websocket_mock.close.assert_called_once()

@pytest.mark.asyncio
async def test_legacy_ws_receive_from_client_exceptions():
    """receive_from_client 内の例外ハンドリングテスト"""
    mock_brain = MagicMock()
    mock_brain._get_system_instruction.return_value = "Mock System Instruction"
    
    mock_handler = MagicMock()
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.close = AsyncMock()

    # 1. receive_json が HTTPException を投げるケース
    websocket_mock.receive_json = AsyncMock(side_effect=HTTPException(status_code=400, detail="Client Error"))
    
    async def mock_run_empty(send_queue, ai_callback, system_instruction=None):
        await send_queue.get() # None を待つ

    mock_handler.run = AsyncMock(side_effect=mock_run_empty)

    with patch("director_engine.DirectorBrain", return_value=mock_brain),          patch("live_api_handler.LiveAPIHandler", return_value=mock_handler):
        
        with pytest.raises(HTTPException):
            await websocket_live_endpoint(websocket_mock)

    # 2. receive_json が一般例外を投げるケース
    websocket_mock.receive_json = AsyncMock(side_effect=Exception("General receive error"))
    
    async def mock_run_general(send_queue, ai_callback, system_instruction=None):
        item = await send_queue.get()
        assert item is None # receive_from_client の finally で None が入る

    mock_handler.run = AsyncMock(side_effect=mock_run_general)

    with patch("director_engine.DirectorBrain", return_value=mock_brain),          patch("live_api_handler.LiveAPIHandler", return_value=mock_handler):
        
        await websocket_live_endpoint(websocket_mock)

@pytest.mark.asyncio
async def test_legacy_ws_bridge_exceptions():
    """websocket_live_endpoint メインブロック内の例外ハンドリングテスト"""
    mock_brain = MagicMock()
    mock_brain._get_system_instruction.return_value = "Mock System Instruction"
    
    mock_handler = MagicMock()
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.close = AsyncMock()
    websocket_mock.receive_json = AsyncMock(side_effect=WebSocketDisconnect())

    # handler.run が一般例外を投げるケース
    mock_handler.run = AsyncMock(side_effect=Exception("Bridge Run Error"))

    with patch("director_engine.DirectorBrain", return_value=mock_brain),          patch("live_api_handler.LiveAPIHandler", return_value=mock_handler):
        
        await websocket_live_endpoint(websocket_mock)
        
    websocket_mock.close.assert_called_once()
    
    # websocket.close() で例外が発生した場合のハンドリングテスト
    websocket_mock.close = AsyncMock(side_effect=Exception("Close error"))
    with patch("director_engine.DirectorBrain", return_value=mock_brain),          patch("live_api_handler.LiveAPIHandler", return_value=mock_handler):
        await websocket_live_endpoint(websocket_mock)

@pytest.mark.asyncio
async def test_legacy_ws_robustness_guards():
    """堅牢化ガード（Noneや不正な型）の動作テスト"""
    mock_brain = MagicMock()
    mock_brain._get_system_instruction.return_value = "Mock System Instruction"
    
    mock_handler = MagicMock()
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.send_json = AsyncMock()
    websocket_mock.close = AsyncMock()

    # 1. clientからの非dictデータや、mediaが非listデータの場合のテスト
    websocket_mock.receive_json = AsyncMock(side_effect=[
        None,                 # data is None
        "invalid_string",     # data is not dict
        {"media": "not_list"}, # media is not list
        WebSocketDisconnect() # ループ終了
    ])

    async def mock_run_receive_check(send_queue, ai_callback, system_instruction=None):
        # ai_callback の各種 None/不正型ガードをテスト
        
        # message is None
        await ai_callback(None)
        
        # message has server_content but it is None
        msg_content_none = MagicMock()
        msg_content_none.server_content = None
        await ai_callback(msg_content_none)
        
        # message has server_content, but model_turn is None
        msg_turn_none = MagicMock()
        msg_turn_none.server_content.model_turn = None
        await ai_callback(msg_turn_none)
        
        # message has parts but it is not list/tuple (e.g. dict)
        msg_parts_invalid = MagicMock()
        msg_parts_invalid.server_content.model_turn.parts = "not_a_list"
        await ai_callback(msg_parts_invalid)

        # parts is list, but inline_data has no data (data is None)
        msg_data_none = MagicMock()
        part_data_none = MagicMock()
        part_data_none.text = None
        part_data_none.inline_data.data = None
        msg_data_none.server_content.model_turn.parts = [part_data_none]
        await ai_callback(msg_data_none)

        # 呼び出し元が実行中 (pending) の状態で receive_task が終了するようにスリープ
        # これにより pending タスクのキャンセル処理（L87: task.cancel()）がカバーされる
        await asyncio.sleep(0.05)

    mock_handler.run = AsyncMock(side_effect=mock_run_receive_check)

    with patch("director_engine.DirectorBrain", return_value=mock_brain),          patch("live_api_handler.LiveAPIHandler", return_value=mock_handler):
        
        await websocket_live_endpoint(websocket_mock)

    websocket_mock.send_json.assert_not_called()
    websocket_mock.close.assert_called_once()

@pytest.mark.asyncio
async def test_legacy_ws_pending_task_cleanup_success():
    """タスクキャンセル時に pending タスクが正しく await され、CancelledError が処理されることを確認するテスト"""
    mock_brain = MagicMock()
    mock_brain._get_system_instruction.return_value = "Mock Instruction"
    
    mock_handler = MagicMock()
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.close = AsyncMock()
    
    # 接続直後に WebSocketDisconnect を発生させて receive_from_client を即座に終了させる
    websocket_mock.receive_json = AsyncMock(side_effect=WebSocketDisconnect())
    
    # キャンセル完了を確認するためのフラグ
    cleanup_called = False
    
    async def mock_run_pending(send_queue, ai_callback, system_instruction=None):
        nonlocal cleanup_called
        try:
            # 呼び出し元が終了するまで無限待機する pending タスク
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cleanup_called = True
            raise # キャンセルエラーを再送出して asyncio.wait のクリーンアップを走らせる
            
    mock_handler.run = AsyncMock(side_effect=mock_run_pending)
    
    with patch("director_engine.DirectorBrain", return_value=mock_brain), \
         patch("live_api_handler.LiveAPIHandler", return_value=mock_handler):
         
        await websocket_live_endpoint(websocket_mock)
        
    assert cleanup_called is True
    websocket_mock.close.assert_called_once()


@pytest.mark.asyncio
async def test_receive_from_client_loop_http_exception_direct():
    """receive_from_client_loop 内で HTTPException が発生したときに、正しく再スローされることを直接検証"""
    from routers.legacy_live_websocket import receive_from_client_loop
    
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.receive_json = AsyncMock(side_effect=HTTPException(status_code=400, detail="Test HTTP Exception"))
    send_queue = asyncio.Queue()
    
    with pytest.raises(HTTPException):
        await receive_from_client_loop(websocket_mock, send_queue)
    
    # 最後にキューに None が入れられることを確認
    assert await send_queue.get() is None


@pytest.mark.asyncio
async def test_legacy_ws_endpoint_http_exception_re_raise():
    """websocket_live_endpoint 内でタスクから HTTPException が発生したときに、正しく再スローされることを検証"""
    mock_brain = MagicMock()
    mock_brain._get_system_instruction.return_value = "Mock Instruction"
    
    mock_handler = MagicMock()
    # handler.run が HTTPException を発生させるようにする
    mock_handler.run = AsyncMock(side_effect=HTTPException(status_code=403, detail="Handler Forbidden"))
    
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.close = AsyncMock()
    websocket_mock.receive_json = AsyncMock(side_effect=WebSocketDisconnect())
    
    with patch("director_engine.DirectorBrain", return_value=mock_brain), \
         patch("live_api_handler.LiveAPIHandler", return_value=mock_handler):
         
        with pytest.raises(HTTPException) as excinfo:
            await websocket_live_endpoint(websocket_mock)
            
        assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_legacy_ws_ai_callback_http_exception_propagation():
    """ai_callback で発生した HTTPException がモックランから websocket_live_endpoint まで伝播することを検証"""
    mock_brain = MagicMock()
    mock_brain._get_system_instruction.return_value = "Mock Instruction"
    
    mock_handler = MagicMock()
    websocket_mock = AsyncMock(spec=WebSocket)
    websocket_mock.accept = AsyncMock()
    websocket_mock.close = AsyncMock()
    # send_json で HTTPException を発生させる
    websocket_mock.send_json = AsyncMock(side_effect=HTTPException(status_code=400, detail="Send Error"))
    websocket_mock.receive_json = AsyncMock(side_effect=WebSocketDisconnect())
    
    async def mock_run_with_exception(send_queue, ai_callback, system_instruction=None):
        # メッセージを作成して ai_callback を呼び出す。例外はキャッチしない
        msg = MagicMock()
        part = MagicMock()
        part.text = "Trigger exception"
        part.inline_data = None
        msg.server_content.model_turn.parts = [part]
        
        # ここで例外が発生し、mock_run 自体がこの例外で終了する
        await ai_callback(msg)
        
    mock_handler.run = AsyncMock(side_effect=mock_run_with_exception)
    
    with patch("director_engine.DirectorBrain", return_value=mock_brain), \
         patch("live_api_handler.LiveAPIHandler", return_value=mock_handler):
         
        with pytest.raises(HTTPException) as excinfo:
            await websocket_live_endpoint(websocket_mock)
            
        assert excinfo.value.status_code == 400
