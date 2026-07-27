import pytest
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient
from backend.websocket_handler import (
    AuthToken,
    TokenManager,
    ConnectionInfo,
    ConnectionManager,
    ProgressBroadcaster,
    handle_progress_websocket,
    token_manager,
    progress_manager
)

# FastAPIのアプリをテスト用に定義
app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = None):
    await handle_progress_websocket(websocket, token)

def test_auth_token_expiration():
    # expires_at = 0 は無期限
    token = AuthToken("tok", "user", expires_at=0)
    assert not token.is_expired()
    
    # 過去の期限
    token_expired = AuthToken("tok", "user", expires_at=time.time() - 10)
    assert token_expired.is_expired()
    
    # 未来の期限
    token_future = AuthToken("tok", "user", expires_at=time.time() + 10)
    assert not token_future.is_expired()

def test_token_manager_generate_validation():
    mgr = TokenManager()
    
    # user_idの型バリデーション
    with pytest.raises(ValueError, match="user_id must be a non-empty string"):
        mgr.generate_token(None)
    with pytest.raises(ValueError, match="user_id must be a non-empty string"):
        mgr.generate_token("")
    with pytest.raises(ValueError, match="user_id must be a non-empty string"):
        mgr.generate_token(123)
        
    # ttlの型・範囲バリデーション
    with pytest.raises(ValueError, match="ttl must be a positive number"):
        mgr.generate_token("user", -10)
    with pytest.raises(ValueError, match="ttl must be a positive number"):
        mgr.generate_token("user", 0)
    with pytest.raises(ValueError, match="ttl must be a positive number"):
        mgr.generate_token("user", "invalid")

def test_token_manager_lifecycle():
    mgr = TokenManager()
    
    # 生成
    token = mgr.generate_token("user1", ttl=60)
    assert isinstance(token, str)
    assert len(token) > 0
    
    # 検証
    assert mgr.validate_token(token) == "user1"
    
    # 無効化
    assert mgr.revoke_token(token)
    assert not mgr.revoke_token(token)
    assert mgr.validate_token(token) is None

def test_token_manager_expired_token():
    mgr = TokenManager()
    # 期限切れトークンを意図的に作成
    token = mgr.generate_token("user2", ttl=0.001)
    time.sleep(0.005)
    
    # 検証（期限切れのため削除され None が返る）
    assert mgr.validate_token(token) is None
    # 既に削除されているため、再検証も None
    assert mgr.validate_token(token) is None

def test_token_manager_validate_invalid_inputs():
    mgr = TokenManager()
    assert mgr.validate_token(None) is None
    assert mgr.validate_token("") is None
    assert mgr.validate_token(123) is None
    
    assert not mgr.revoke_token(None)
    assert not mgr.revoke_token("")
    assert not mgr.revoke_token(123)

@pytest.mark.asyncio
async def test_connection_manager_connect_none_websocket():
    mgr = ConnectionManager()
    assert not await mgr.connect(None)

@pytest.mark.asyncio
async def test_connection_manager_max_connections():
    # 最大同時接続数 = 1
    mgr = ConnectionManager(max_connections=1)
    
    ws1 = MagicMock(spec=WebSocket)
    ws1.accept = AsyncMock()
    ws1.close = AsyncMock()
    
    ws2 = MagicMock(spec=WebSocket)
    ws2.accept = AsyncMock()
    ws2.close = AsyncMock()
    
    # 1つ目接続
    assert await mgr.connect(ws1)
    assert len(mgr.connections) == 1
    
    # 2つ目接続（拒否）
    assert not await mgr.connect(ws2)
    ws2.close.assert_called_once_with(code=1013, reason="Max connections reached")
    assert len(mgr.connections) == 1

@pytest.mark.asyncio
async def test_connection_manager_auth_failures():
    mgr = ConnectionManager()
    
    # 無効なトークンの型
    ws_invalid_type = MagicMock(spec=WebSocket)
    ws_invalid_type.close = AsyncMock()
    assert not await mgr.connect(ws_invalid_type, token=123)
    ws_invalid_type.close.assert_called_once_with(code=4001, reason="Invalid token type")
    
    # 存在しないトークン
    ws_no_token = MagicMock(spec=WebSocket)
    ws_no_token.close = AsyncMock()
    assert not await mgr.connect(ws_no_token, token="non_existent_token")
    ws_no_token.close.assert_called_once_with(code=4001, reason="Invalid token")

@pytest.mark.asyncio
async def test_connection_manager_user_connection_limit():
    mgr = ConnectionManager()
    
    # トークンを生成
    tok = token_manager.generate_token("limited_user", ttl=300)
    
    ws_list = []
    # 制限は MAX_CONNECTIONS_PER_USER = 5
    for i in range(5):
        ws = MagicMock(spec=WebSocket)
        ws.accept = AsyncMock()
        assert await mgr.connect(ws, token=tok)
        ws_list.append(ws)
        
    # 6つ目は拒否される
    ws_excess = MagicMock(spec=WebSocket)
    ws_excess.close = AsyncMock()
    assert not await mgr.connect(ws_excess, token=tok)
    ws_excess.close.assert_called_once_with(code=4002, reason="Too many connections")
    
    # クリーンアップ
    for ws in ws_list:
        await mgr.disconnect(ws)

@pytest.mark.asyncio
async def test_connection_manager_accept_exception():
    mgr = ConnectionManager()
    ws = MagicMock(spec=WebSocket)
    ws.accept = AsyncMock(side_effect=RuntimeError("Accept failed"))
    
    assert not await mgr.connect(ws)
    assert ws not in mgr.connections

@pytest.mark.asyncio
async def test_connection_manager_websocket_close_exception_on_rejection():
    mgr = ConnectionManager(max_connections=0) # 常に拒否
    ws = MagicMock(spec=WebSocket)
    ws.close = AsyncMock(side_effect=RuntimeError("Close failed"))
    
    # 接続は失敗するが、例外は内部でキャッチされ、エラーにならず False を返す
    assert not await mgr.connect(ws)

@pytest.mark.asyncio
async def test_connection_manager_disconnect_none():
    mgr = ConnectionManager()
    # Noneを渡しても例外が出ないこと
    await mgr.disconnect(None)

@pytest.mark.asyncio
async def test_connection_manager_touch_cancel():
    mgr = ConnectionManager()
    ws = MagicMock(spec=WebSocket)
    ws.accept = AsyncMock()
    
    # 存在しない WebSocket
    await mgr.touch(None)
    await mgr.touch(ws)
    await mgr.cancel(None)
    await mgr.cancel(ws)
    assert mgr.is_cancelled(None)
    assert mgr.is_cancelled(ws)
    
    # 接続した状態
    await mgr.connect(ws)
    assert not mgr.is_cancelled(ws)
    
    # touch
    prev_activity = mgr.connections[ws].last_activity
    time.sleep(0.001)
    await mgr.touch(ws)
    assert mgr.connections[ws].last_activity > prev_activity
    
    # cancel
    await mgr.cancel(ws)
    assert mgr.is_cancelled(ws)

@pytest.mark.asyncio
async def test_connection_manager_cleanup_loop():
    mgr = ConnectionManager()
    mgr._connection_timeout = -1  # 常にタイムアウトするように設定
    
    ws = MagicMock(spec=WebSocket)
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    
    await mgr.connect(ws)
    assert len(mgr.connections) == 1
    
    # クリーンアップタスクを一度だけ手動で回すようにするために、
    # _cleanup_loopが1ループ回って connections が空になり終了するのを待つ
    # connections が空になるとループは break する
    # asyncio.sleep(1.1) で _cleanup_loop の1ループが実行されるのを待つ
    await asyncio.sleep(1.2)
    
    # タイムアウトにより切断されているはず
    assert len(mgr.connections) == 0
    ws.close.assert_called_once_with(code=1000, reason="Connection timeout")

@pytest.mark.asyncio
async def test_connection_manager_broadcast():
    mgr = ConnectionManager()
    
    ws1 = MagicMock(spec=WebSocket)
    ws1.accept = AsyncMock()
    ws1.send_json = AsyncMock()
    
    ws2 = MagicMock(spec=WebSocket)
    ws2.accept = AsyncMock()
    ws2.send_json = AsyncMock(side_effect=RuntimeError("Send error")) # 送信エラーで切断されるべき
    
    ws3 = MagicMock(spec=WebSocket)
    ws3.accept = AsyncMock()
    ws3.send_json = MagicMock(side_effect=TypeError("Not JSON serializable")) # シリアライズエラー
    
    await mgr.connect(ws1)
    await mgr.connect(ws2)
    await mgr.connect(ws3)
    
    msg = {"test": "data"}
    await mgr.broadcast_progress(msg)
    
    # 不適切なメッセージ型は無視される
    await mgr.broadcast_progress("not a dict")
    
    ws1.send_json.assert_called_with(msg)
    # ws2 はエラーのため切断されているはず
    assert ws1 in mgr.connections
    assert ws2 not in mgr.connections
    # ws3 はシリアライズエラーで送信は失敗するが、切断はされない（メッセージ不備のため）
    assert ws3 in mgr.connections

@pytest.mark.asyncio
async def test_connection_manager_send_personal_message():
    mgr = ConnectionManager()
    
    ws = MagicMock(spec=WebSocket)
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    
    # 存在しない場合や不正引数
    await mgr.send_personal_message({"test": "data"}, None)
    await mgr.send_personal_message("not a dict", ws)
    
    await mgr.connect(ws)
    await mgr.send_personal_message({"test": "data"}, ws)
    ws.send_json.assert_called_with({"test": "data"})
    
    # 送信エラー時のキャッチ
    ws.send_json = AsyncMock(side_effect=RuntimeError("Send error"))
    await mgr.send_personal_message({"test": "data"}, ws) # 例外が出ずに終了すること
    
    # シリアライズエラー時のキャッチ
    ws.send_json = AsyncMock(side_effect=TypeError("Type error"))
    await mgr.send_personal_message({"test": "data"}, ws) # 例外が出ずに終了すること

def test_connection_manager_stats():
    mgr = ConnectionManager()
    stats = mgr.get_stats()
    assert stats["total_connections"] == 0
    assert stats["max_connections"] == 100

@pytest.mark.asyncio
async def test_progress_broadcaster():
    mock_mgr = MagicMock(spec=ConnectionManager)
    mock_mgr.broadcast_progress = AsyncMock()
    
    broadcaster = ProgressBroadcaster(manager=mock_mgr)
    
    # update_phase
    await broadcaster.update_phase("phase1", 50, "step1", eta=10, preview_url="url")
    mock_mgr.broadcast_progress.assert_called_once()
    args = mock_mgr.broadcast_progress.call_args[0][0]
    assert args["type"] == "progress_update"
    assert args["phase"] == "phase1"
    assert args["progress"] == 50
    assert args["step"] == "step1"
    assert args["eta"] == 10
    assert args["previewUrl"] == "url"
    
    # send_error
    mock_mgr.broadcast_progress.reset_mock()
    await broadcaster.send_error("error message", "ERR_CODE")
    mock_mgr.broadcast_progress.assert_called_once()
    args = mock_mgr.broadcast_progress.call_args[0][0]
    assert args["type"] == "error"
    assert args["message"] == "error message"
    assert args["code"] == "ERR_CODE"
    
    # send_completion
    mock_mgr.broadcast_progress.reset_mock()
    await broadcaster.send_completion({"result": "ok"})
    mock_mgr.broadcast_progress.assert_called_once()
    args = mock_mgr.broadcast_progress.call_args[0][0]
    assert args["type"] == "complete"
    assert args["result"] == {"result": "ok"}

def test_websocket_endpoint_integration():
    client = TestClient(app)
    
    # 認証トークンを取得
    tok = token_manager.generate_token("test_user", ttl=60)
    
    with client.websocket_connect(f"/ws?token={tok}") as websocket:
        # 接続時メッセージの検証
        data = websocket.receive_json()
        assert data["type"] == "connected"
        assert "stats" in data
        
        # ping -> pong
        websocket.send_text("ping")
        data = websocket.receive_json()
        assert data["type"] == "pong"
        
        # stats
        websocket.send_text("stats")
        data = websocket.receive_json()
        assert data["type"] == "stats"
        assert "data" in data
        
        # cancel -> cancelled
        websocket.send_text("cancel")
        data = websocket.receive_json()
        assert data["type"] == "cancelled"
        
        # 不明なコマンド
        websocket.send_text("unknown")
        data = websocket.receive_json()
        assert data["type"] == "error"
        assert "Unknown command" in data["message"]

def test_websocket_endpoint_unauthorized():
    client = TestClient(app)
    # トークンなし、または無効なトークン
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws?token=invalid_token"):
            pass
    assert exc.value.code == 4001

def test_websocket_endpoint_heartbeat():
    client = TestClient(app)
    tok = token_manager.generate_token("test_user_hb", ttl=60)
    
    # HEARTBEAT_INTERVAL を短くしてテストする
    with patch("backend.websocket_handler.HEARTBEAT_INTERVAL", 0.01):
        with client.websocket_connect(f"/ws?token={tok}") as websocket:
            # 接続メッセージ
            websocket.receive_json()
            
            # しばらく待つとTimeoutErrorからハートビートが送信される
            # receive_jsonで待機
            data = websocket.receive_json()
            assert data["type"] == "heartbeat"

def test_handle_progress_websocket_none():
    # websocketがNoneの場合に即座に終了すること
    # 例外なく終了すればテスト成功
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(handle_progress_websocket(None))
    finally:
        loop.close()

@pytest.mark.asyncio
async def test_connection_manager_active_connections():
    mgr = ConnectionManager()
    ws = MagicMock(spec=WebSocket)
    ws.accept = AsyncMock()
    await mgr.connect(ws)
    assert mgr.active_connections == [ws]

@pytest.mark.asyncio
async def test_connection_manager_close_exceptions_detailed():
    # トークン型無効の時の close 例外
    mgr = ConnectionManager()
    ws1 = MagicMock(spec=WebSocket)
    ws1.close = AsyncMock(side_effect=RuntimeError("Close failed"))
    assert not await mgr.connect(ws1, token=123)
    
    # トークン無効の時の close 例外
    ws2 = MagicMock(spec=WebSocket)
    ws2.close = AsyncMock(side_effect=RuntimeError("Close failed"))
    assert not await mgr.connect(ws2, token="invalid_tok")
    
    # ユーザー接続数超過の時の close 例外
    tok = token_manager.generate_token("user_close_exc", ttl=300)
    ws_list = []
    for _ in range(5):
        ws_ok = MagicMock(spec=WebSocket)
        ws_ok.accept = AsyncMock()
        await mgr.connect(ws_ok, token=tok)
        ws_list.append(ws_ok)
    ws_excess = MagicMock(spec=WebSocket)
    ws_excess.close = AsyncMock(side_effect=RuntimeError("Close failed"))
    assert not await mgr.connect(ws_excess, token=tok)
    
    # クリーンアップ時の close 例外
    mgr_cleanup = ConnectionManager()
    mgr_cleanup._connection_timeout = -1
    ws_cleanup = MagicMock(spec=WebSocket)
    ws_cleanup.accept = AsyncMock()
    ws_cleanup.close = AsyncMock(side_effect=RuntimeError("Close failed during cleanup"))
    await mgr_cleanup.connect(ws_cleanup)
    await asyncio.sleep(1.2)
    assert len(mgr_cleanup.connections) == 0

@pytest.mark.asyncio
async def test_connection_manager_broadcast_empty():
    mgr = ConnectionManager()
    # 接続が空の状態で broadcast しても何も起きないこと
    await mgr.broadcast_progress({"test": "data"})

@pytest.mark.asyncio
async def test_websocket_endpoint_exceptions():
    # 1. receive_text での OSError
    ws1 = MagicMock(spec=WebSocket)
    ws1.accept = AsyncMock()
    ws1.close = AsyncMock()
    ws1.send_json = AsyncMock()
    ws1.receive_text = AsyncMock(side_effect=OSError("Read error"))
    
    tok = token_manager.generate_token("test_user_exc1", ttl=60)
    await handle_progress_websocket(ws1, token=tok)
    
    ws1.accept.assert_called_once()
    assert ws1 not in progress_manager.connections
    
    # 2. heartbeat送信時のOSError
    ws2 = MagicMock(spec=WebSocket)
    ws2.accept = AsyncMock()
    ws2.close = AsyncMock()
    
    # receive_textでTimeoutErrorを投げさせる
    ws2.receive_text = MagicMock(side_effect=asyncio.TimeoutError())
    # 1回目(connected)は成功、2回目(heartbeat)でOSErrorを投げるように設定
    ws2.send_json = AsyncMock(side_effect=[None, OSError("Write error")])
    
    tok2 = token_manager.generate_token("test_user_exc2", ttl=60)
    
    with patch("backend.websocket_handler.HEARTBEAT_INTERVAL", 0.001):
        await handle_progress_websocket(ws2, token=tok2)
        
    ws2.accept.assert_called_once()
    assert ws2 not in progress_manager.connections


@pytest.mark.asyncio
async def test_connection_manager_close():
    mgr = ConnectionManager()
    
    ws1 = MagicMock(spec=WebSocket)
    ws1.accept = AsyncMock()
    ws1.close = AsyncMock()
    
    ws2 = MagicMock(spec=WebSocket)
    ws2.accept = AsyncMock()
    ws2.close = AsyncMock(side_effect=OSError("Close error")) # 例外を発生させて無視されるか検証
    
    # 接続を登録
    await mgr.connect(ws1)
    await mgr.connect(ws2)
    
    # _cleanup_taskが動いていることを確認
    assert mgr._cleanup_task is not None
    assert not mgr._cleanup_task.done()
    
    # closeを実行
    await mgr.close()
    
    # _cleanup_taskが停止し、Noneになっていること
    assert mgr._cleanup_task is None
    
    # 接続がすべてクローズされ、クリアされていること
    ws1.close.assert_called_once_with(code=1000, reason="Manager closing")
    ws2.close.assert_called_once_with(code=1000, reason="Manager closing")
    assert len(mgr.connections) == 0
    assert len(mgr.user_connections) == 0


@pytest.mark.asyncio
async def test_progress_broadcaster_update_council_state():
    mock_mgr = MagicMock(spec=ConnectionManager)
    mock_mgr.broadcast_progress = AsyncMock()
    
    broadcaster = ProgressBroadcaster(manager=mock_mgr)
    
    await broadcaster.update_council_state(
        session_id="session123",
        agent_name="agent_review",
        state="thinking",
        stance="AGREE",
        detail="Reviewed the design, looks premium."
    )
    
    mock_mgr.broadcast_progress.assert_called_once()
    args = mock_mgr.broadcast_progress.call_args[0][0]
    assert args["type"] == "council_update"
    assert args["sessionId"] == "session123"
    assert args["agent"] == "agent_review"
    assert args["state"] == "thinking"
    assert args["stance"] == "AGREE"
    assert args["detail"] == "Reviewed the design, looks premium."
    assert "timestamp" in args


@pytest.mark.asyncio
async def test_websocket_endpoint_generate_thumbnail_success():
    import json
    client = TestClient(app)
    tok = token_manager.generate_token("test_user_thumb_ok", ttl=60)
    
    mock_overlay = MagicMock()
    mock_overlay.generate_thumbnail = MagicMock()
    mock_overlay.validate_thumbnail = MagicMock(return_value={"valid": True, "path": "test.png"})
    
    with patch("combined_overlay.CombinedOverlay", return_value=mock_overlay):
        with client.websocket_connect(f"/ws?token={tok}") as websocket:
            # 接続イベント受信
            websocket.receive_json()
            
            # thumbnail 生成コマンド送信
            command = {
                "action": "generate_thumbnail",
                "output_path": "test_output.png",
                "width": 800,
                "height": 600,
                "text": "Hello WS"
            }
            websocket.send_text(json.dumps(command))
            
            # レスポンス受信
            response = websocket.receive_json()
            assert response["type"] == "thumbnail_result"
            assert response["status"] == "success"
            assert response["data"] == {"valid": True, "path": "test.png"}
            
            # CombinedOverlay の呼び出し検証
            mock_overlay.generate_thumbnail.assert_called_once_with(
                "test_output.png", width=800, height=600, text="Hello WS"
            )
            mock_overlay.validate_thumbnail.assert_called_once_with("test_output.png")


@pytest.mark.asyncio
async def test_websocket_endpoint_generate_thumbnail_failure():
    import json
    client = TestClient(app)
    tok = token_manager.generate_token("test_user_thumb_fail", ttl=60)
    
    mock_overlay = MagicMock()
    mock_overlay.generate_thumbnail = MagicMock(side_effect=RuntimeError("Gen error"))
    
    with patch("combined_overlay.CombinedOverlay", return_value=mock_overlay):
        with client.websocket_connect(f"/ws?token={tok}") as websocket:
            # 接続イベント受信
            websocket.receive_json()
            
            # thumbnail 生成コマンド送信
            command = {
                "action": "generate_thumbnail",
                "output_path": "test_output.png"
            }
            websocket.send_text(json.dumps(command))
            
            # レスポンス受信
            response = websocket.receive_json()
            assert response["type"] == "thumbnail_result"
            assert response["status"] == "failed"
            assert response["error"] == "Gen error"



