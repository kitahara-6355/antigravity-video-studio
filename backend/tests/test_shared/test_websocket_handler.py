"""
M2.5: WebSocket Handler テスト — 20テスト

websocket_handler.py (179 stmts, 105 missed) のカバレッジ改善。
TokenManager, ConnectionManager, ProgressBroadcaster の3クラスを網羅。

外部依存: FastAPI WebSocket → MagicMock で代替。
"""

import pytest
import asyncio
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from websocket_handler import (
    AuthToken, TokenManager, ConnectionInfo, ConnectionManager,
    ProgressBroadcaster, token_manager,
    MAX_CONNECTIONS, MAX_CONNECTIONS_PER_USER, CONNECTION_TIMEOUT,
)

@pytest.fixture(autouse=True)
async def cleanup_connection_managers():
    """テストで作成されたすべての ConnectionManager インスタンスを確実にクリーンアップする"""
    created_managers = []
    original_init = ConnectionManager.__init__
    
    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created_managers.append(self)
        
    with patch.object(ConnectionManager, "__init__", patched_init):
        yield
        
    # テスト後にシングルトンおよび作成されたすべての manager をクリーンアップする
    for cm in created_managers:
        await cm.close()
    
    await progress_manager.close()


# ============================================================
# TokenManager テスト
# ============================================================

class TestTokenManager:
    """TokenManager: トークン生成・検証・無効化"""

    def test_generate_token_returns_string(self):
        """トークン生成: 文字列が返る"""
        tm = TokenManager()
        token = tm.generate_token("user1")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_validate_valid_token(self):
        """有効トークンの検証: user_idが返る"""
        tm = TokenManager()
        token = tm.generate_token("user1", ttl=3600)
        user_id = tm.validate_token(token)
        assert user_id == "user1"

    def test_validate_invalid_token(self):
        """無効トークンの検証: Noneが返る"""
        tm = TokenManager()
        result = tm.validate_token("invalid_token_xyz")
        assert result is None

    def test_validate_expired_token(self):
        """期限切れトークンの検証: Noneが返り、トークンが削除される"""
        tm = TokenManager()
        token = tm.generate_token("user1", ttl=0.001)
        # TTL=0.001 → expires_at = time.time() + 0.001 → 即時期限切れ
        time.sleep(0.005)
        result = tm.validate_token(token)
        assert result is None
        # 削除されていること
        assert token not in tm._tokens

    def test_revoke_existing_token(self):
        """トークン無効化: 存在するトークン → True"""
        tm = TokenManager()
        token = tm.generate_token("user1")
        assert tm.revoke_token(token) is True
        assert tm.validate_token(token) is None

    def test_revoke_nonexistent_token(self):
        """トークン無効化: 存在しないトークン → False"""
        tm = TokenManager()
        assert tm.revoke_token("nonexistent") is False

    def test_generate_token_invalid_args(self):
        """無効な引数でのトークン生成: ValueError"""
        tm = TokenManager()
        with pytest.raises(ValueError, match="user_id must be a non-empty string"):
            tm.generate_token("")
        with pytest.raises(ValueError, match="user_id must be a non-empty string"):
            tm.generate_token(None)
        with pytest.raises(ValueError, match="ttl must be a positive number"):
            tm.generate_token("user1", ttl=-10)
        with pytest.raises(ValueError, match="ttl must be a positive number"):
            tm.generate_token("user1", ttl=0)

    def test_validate_and_revoke_invalid_token_type(self):
        """無効な型のトークン検証・無効化: None / False が返る"""
        tm = TokenManager()
        assert tm.validate_token(None) is None
        assert tm.validate_token(123) is None
        assert tm.revoke_token(None) is False
        assert tm.revoke_token(123) is False


# ============================================================
# AuthToken テスト
# ============================================================

class TestAuthToken:
    """AuthToken: 期限切れ判定"""

    def test_is_expired_with_future_expiry(self):
        """未期限切れ: expires_at > now → False"""
        token = AuthToken(token="t", user_id="u", expires_at=time.time() + 3600)
        assert token.is_expired() is False

    def test_is_expired_with_past_expiry(self):
        """期限切れ: expires_at < now → True"""
        token = AuthToken(token="t", user_id="u", expires_at=time.time() - 100)
        assert token.is_expired() is True

    def test_is_expired_with_zero_expiry(self):
        """無期限: expires_at = 0 → False"""
        token = AuthToken(token="t", user_id="u", expires_at=0)
        assert token.is_expired() is False


# ============================================================
# ConnectionManager テスト
# ============================================================

class TestConnectionManager:
    """ConnectionManager: 接続管理・認証・ブロードキャスト"""

    @pytest.mark.asyncio
    async def test_connect_without_auth(self):
        """認証なし接続: accept + True"""
        cm = ConnectionManager()
        ws = AsyncMock()
        result = await cm.connect(ws)
        assert result is True
        ws.accept.assert_awaited_once()
        assert ws in cm.connections

    @pytest.mark.asyncio
    async def test_connect_max_connections_exceeded(self):
        """最大接続数超過: close + False"""
        cm = ConnectionManager(max_connections=1)
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await cm.connect(ws1)
        result = await cm.connect(ws2)
        assert result is False
        ws2.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self):
        """切断: 接続情報が削除される"""
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        assert ws in cm.connections
        await cm.disconnect(ws)
        assert ws not in cm.connections

    @pytest.mark.asyncio
    async def test_disconnect_with_user_id(self):
        """ユーザー付き切断: user_connectionsからも削除"""
        cm = ConnectionManager()
        tm = TokenManager()
        token = tm.generate_token("user_test")

        ws = AsyncMock()
        with patch("websocket_handler.token_manager", tm):
            await cm.connect(ws, token)
        assert "user_test" in cm.user_connections

        await cm.disconnect(ws)
        assert "user_test" not in cm.user_connections

    @pytest.mark.asyncio
    async def test_active_connections_property(self):
        """active_connections: 後方互換プロパティ"""
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        assert ws in cm.active_connections

    @pytest.mark.asyncio
    async def test_touch_updates_last_activity(self):
        """touch: last_activityが更新される"""
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        old_time = cm.connections[ws].last_activity
        time.sleep(0.01)
        await cm.touch(ws)
        assert cm.connections[ws].last_activity >= old_time

    @pytest.mark.asyncio
    async def test_cancel_sets_flag(self):
        """cancel: cancelled=True"""
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        await cm.cancel(ws)
        assert cm.connections[ws].cancelled is True

    @pytest.mark.asyncio
    async def test_is_cancelled_true_for_cancelled(self):
        """is_cancelled: cancelled=True → True"""
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        await cm.cancel(ws)
        assert cm.is_cancelled(ws) is True

    @pytest.mark.asyncio
    async def test_is_cancelled_true_for_unknown(self):
        """is_cancelled: 未知のwebsocket → True"""
        cm = ConnectionManager()
        ws = AsyncMock()
        assert cm.is_cancelled(ws) is True

    def test_get_stats(self):
        """get_stats: 統計情報の形式"""
        cm = ConnectionManager()
        stats = cm.get_stats()
        assert "total_connections" in stats
        assert "max_connections" in stats
        assert "users_connected" in stats
        assert stats["total_connections"] == 0

    @pytest.mark.asyncio
    async def test_connect_invalid_token(self):
        """無効なトークンでの接続: close + False"""
        cm = ConnectionManager()
        ws = AsyncMock()
        result = await cm.connect(ws, token="invalid_token")
        assert result is False
        ws.close.assert_awaited_once_with(code=4001, reason="Invalid token")

    @pytest.mark.asyncio
    async def test_connect_user_max_connections_exceeded(self):
        """ユーザーごとの最大接続数超過: close + False"""
        cm = ConnectionManager()
        tm = TokenManager()
        tokens = [tm.generate_token("user_limit") for _ in range(MAX_CONNECTIONS_PER_USER + 1)]
        ws_list = [AsyncMock() for _ in range(MAX_CONNECTIONS_PER_USER + 1)]
        
        with patch("websocket_handler.token_manager", tm):
            for i in range(MAX_CONNECTIONS_PER_USER):
                res = await cm.connect(ws_list[i], tokens[i])
                assert res is True
            
            res_exceeded = await cm.connect(ws_list[-1], tokens[-1])
            assert res_exceeded is False
            ws_list[-1].close.assert_awaited_once_with(code=4002, reason="Too many connections")

    @pytest.mark.asyncio
    async def test_cleanup_loop_removes_expired_connections(self):
        """クリーンアップループ: タイムアウトした接続をクリーンアップ"""
        cm = ConnectionManager()
        ws_valid = AsyncMock()
        ws_expired = AsyncMock()
        ws_error = AsyncMock()
        
        # バックグラウンドタスクが立ち上がるのを防ぐ
        # unawaited coroutine 警告を防ぐため、渡されたコルーチンは即座にクローズする
        def mock_create_task(coro):
            coro.close()
            f = asyncio.Future()
            f.set_result(None)
            return f

        with patch("asyncio.create_task", mock_create_task):
            await cm.connect(ws_valid)
            await cm.connect(ws_expired)
            await cm.connect(ws_error)
        
        now = time.time()
        cm.connections[ws_expired].last_activity = now - (CONNECTION_TIMEOUT + 10)
        cm.connections[ws_error].last_activity = now - (CONNECTION_TIMEOUT + 10)
        
        ws_error.close.side_effect = ConnectionError("Close error")
        
        real_sleep = asyncio.sleep
        call_count = 0
        async def mock_sleep(delay):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                cm.connections.clear()
            await real_sleep(0)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            await cm._cleanup_loop()
        
        ws_expired.close.assert_awaited_once_with(code=1000, reason="Connection timeout")
        ws_error.close.assert_awaited_once_with(code=1000, reason="Connection timeout")
        assert ws_expired not in cm.connections
        assert ws_error not in cm.connections

    @pytest.mark.asyncio
    async def test_send_personal_message_success(self):
        """個別メッセージ送信: 成功パターン"""
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        
        cm.connections[ws].last_activity = time.time() - 10
        old_activity = cm.connections[ws].last_activity
        
        await cm.send_personal_message({"data": "hello"}, ws)
        ws.send_json.assert_awaited_once_with({"data": "hello"})
        assert cm.connections[ws].last_activity > old_activity

    @pytest.mark.asyncio
    async def test_send_personal_message_failure(self):
        """個別メッセージ送信: 失敗パターン"""
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        
        ws.send_json.side_effect = ConnectionError("Send fail")
        await cm.send_personal_message({"data": "hello"}, ws)
        ws.send_json.assert_awaited_once_with({"data": "hello"})

    @pytest.mark.asyncio
    async def test_connect_invalid_token_type(self):
        """無効なトークンの型での接続: close(4001, "Invalid token type") + False"""
        cm = ConnectionManager()
        ws = AsyncMock()
        result = await cm.connect(ws, token=123)
        assert result is False
        ws.close.assert_awaited_once_with(code=4001, reason="Invalid token type")

    @pytest.mark.asyncio
    async def test_connect_websocket_none(self):
        """websocketがNoneの場合: False"""
        cm = ConnectionManager()
        result = await cm.connect(None)
        assert result is False


# ============================================================
# ProgressBroadcaster テスト
# ============================================================

class TestProgressBroadcaster:
    """ProgressBroadcaster: 進捗配信"""

    @pytest.mark.asyncio
    async def test_broadcast_progress_empty(self):
        """接続なし: ブロードキャストがスキップされる"""
        cm = ConnectionManager()
        pb = ProgressBroadcaster(cm)
        # 例外なし
        await cm.broadcast_progress({"type": "test"})

    @pytest.mark.asyncio
    async def test_update_phase(self):
        """update_phase: メッセージがブロードキャストされる"""
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        pb = ProgressBroadcaster(cm)
        await pb.update_phase("transcribe", 50, "処理中")
        ws.send_json.assert_awaited()
        call_args = ws.send_json.await_args[0][0]
        assert call_args["type"] == "progress_update"
        assert call_args["progress"] == 50

    @pytest.mark.asyncio
    async def test_send_error(self):
        """send_error: エラーメッセージがブロードキャストされる"""
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        pb = ProgressBroadcaster(cm)
        await pb.send_error("テストエラー", "E001")
        call_args = ws.send_json.await_args[0][0]
        assert call_args["type"] == "error"
        assert call_args["message"] == "テストエラー"

    @pytest.mark.asyncio
    async def test_send_completion(self):
        """send_completion: 完了通知がブロードキャストされる"""
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        pb = ProgressBroadcaster(cm)
        await pb.send_completion({"task": "done"})
        call_args = ws.send_json.await_args[0][0]
        assert call_args["type"] == "complete"
        assert call_args["result"] == {"task": "done"}

    @pytest.mark.asyncio
    async def test_broadcast_disconnects_failed(self):
        """送信失敗: 切断される"""
        cm = ConnectionManager()
        ws = AsyncMock()
        ws.send_json.side_effect = ConnectionError("connection lost")
        await cm.connect(ws)
        await cm.broadcast_progress({"type": "test"})
        assert ws not in cm.connections

    @pytest.mark.asyncio
    async def test_update_council_state(self):
        """update_council_state: 合議の進行状況がブロードキャストされる"""
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        pb = ProgressBroadcaster(cm)
        await pb.update_council_state("session123", "thumbnail_agent", "thinking", "AGREE", "詳細テキスト")
        call_args = ws.send_json.await_args[0][0]
        assert call_args["type"] == "council_update"
        assert call_args["sessionId"] == "session123"
        assert call_args["agent"] == "thumbnail_agent"
        assert call_args["state"] == "thinking"
        assert call_args["stance"] == "AGREE"
        assert call_args["detail"] == "詳細テキスト"


# ============================================================
# handle_progress_websocket エンドポイントハンドラー テスト
# ============================================================

from websocket_handler import handle_progress_websocket, progress_manager, WebSocketDisconnect

class TestHandleProgressWebsocket:
    """handle_progress_websocket: WebSocketエンドポイント"""

    @pytest.mark.asyncio
    async def test_handle_websocket_connection_rejected(self):
        """接続拒否された場合、即座に終了する"""
        ws = AsyncMock()
        with patch.object(progress_manager, "connect", return_value=False) as mock_connect:
            await handle_progress_websocket(ws, token="invalid")
            mock_connect.assert_called_once_with(ws, "invalid")
            ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_websocket_ping(self):
        """ping を受信した場合、pong を返信し、切断される"""
        ws = AsyncMock()
        ws.receive_text.side_effect = ["ping", WebSocketDisconnect()]
        
        with patch.object(progress_manager, "connect", return_value=True), \
             patch.object(progress_manager, "disconnect") as mock_disconnect:
            await handle_progress_websocket(ws, token="valid")
            
            ws.send_json.assert_any_call({
                "type": "connected",
                "message": "WebSocket接続が確立されました",
                "stats": progress_manager.get_stats()
            })
            ws.send_json.assert_any_call({"type": "pong"})
            mock_disconnect.assert_called_once_with(ws)

    @pytest.mark.asyncio
    async def test_handle_websocket_cancel(self):
        """cancel を受信した場合、キャンセルを実行し、cancelled を返信"""
        ws = AsyncMock()
        ws.receive_text.side_effect = ["cancel", WebSocketDisconnect()]
        
        with patch.object(progress_manager, "connect", return_value=True), \
             patch.object(progress_manager, "cancel") as mock_cancel, \
             patch.object(progress_manager, "disconnect") as mock_disconnect:
            await handle_progress_websocket(ws, token="valid")
            
            mock_cancel.assert_called_once_with(ws)
            ws.send_json.assert_any_call({"type": "cancelled"})
            mock_disconnect.assert_called_once_with(ws)

    @pytest.mark.asyncio
    async def test_handle_websocket_stats(self):
        """stats を受信した場合、統計情報を返信"""
        ws = AsyncMock()
        ws.receive_text.side_effect = ["stats", WebSocketDisconnect()]
        
        with patch.object(progress_manager, "connect", return_value=True), \
             patch.object(progress_manager, "disconnect") as mock_disconnect:
            await handle_progress_websocket(ws, token="valid")
            
            ws.send_json.assert_any_call({
                "type": "stats",
                "data": progress_manager.get_stats()
            })
            mock_disconnect.assert_called_once_with(ws)

    @pytest.mark.asyncio
    async def test_handle_websocket_heartbeat_timeout(self):
        """TimeoutError が発生した場合、heartbeat を送信"""
        ws = AsyncMock()
        ws.receive_text.side_effect = [asyncio.TimeoutError(), WebSocketDisconnect()]
        
        with patch.object(progress_manager, "connect", return_value=True), \
             patch.object(progress_manager, "disconnect") as mock_disconnect:
            await handle_progress_websocket(ws, token="valid")
            
            ws.send_json.assert_any_call({"type": "heartbeat"})
            mock_disconnect.assert_called_once_with(ws)

    @pytest.mark.asyncio
    async def test_handle_websocket_heartbeat_timeout_send_failure(self):
        """TimeoutError で heartbeat 送信失敗した場合、ループを抜ける"""
        ws = AsyncMock()
        ws.receive_text.side_effect = [asyncio.TimeoutError()]
        
        send_calls = 0
        async def mock_send_json(data):
            nonlocal send_calls
            send_calls += 1
            if send_calls > 1:
                raise ConnectionError("Heartbeat send failed")
        ws.send_json.side_effect = mock_send_json

        with patch.object(progress_manager, "connect", return_value=True), \
             patch.object(progress_manager, "disconnect") as mock_disconnect:
            await handle_progress_websocket(ws, token="valid")
            
            mock_disconnect.assert_called_once_with(ws)

    @pytest.mark.asyncio
    async def test_handle_websocket_none(self):
        """websocketがNoneの場合、即座に終了する"""
        await handle_progress_websocket(None)

    @pytest.mark.asyncio
    async def test_handle_websocket_unknown_command(self):
        """未知のコマンドを受信した場合、エラーを返信"""
        ws = AsyncMock()
        ws.receive_text.side_effect = ["unknown_cmd", WebSocketDisconnect()]
        with patch.object(progress_manager, "connect", return_value=True), \
             patch.object(progress_manager, "disconnect") as mock_disconnect:
            await handle_progress_websocket(ws, token="valid")
            ws.send_json.assert_any_call({
                "type": "error",
                "message": "Unknown command: unknown_cmd"
            })

    @pytest.mark.asyncio
    async def test_handle_websocket_receive_error(self):
        """receive_text で接続エラー等の例外が発生した場合、切断して終了する"""
        ws = AsyncMock()
        ws.receive_text.side_effect = ConnectionError("Connection lost unexpectedly")
        with patch.object(progress_manager, "connect", return_value=True), \
             patch.object(progress_manager, "disconnect") as mock_disconnect:
            await handle_progress_websocket(ws, token="valid")
            mock_disconnect.assert_called_once_with(ws)

    # ------------------------------------------------------------
    # ConnectionManager 追加カバレッジテスト
    # ------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_disconnect_none(self):
        cm = ConnectionManager()
        await cm.disconnect(None)

    @pytest.mark.asyncio
    async def test_touch_none(self):
        cm = ConnectionManager()
        await cm.touch(None)

    @pytest.mark.asyncio
    async def test_cancel_none(self):
        cm = ConnectionManager()
        await cm.cancel(None)

    def test_is_cancelled_none(self):
        cm = ConnectionManager()
        assert cm.is_cancelled(None) is True

    @pytest.mark.asyncio
    async def test_broadcast_progress_invalid_type(self):
        cm = ConnectionManager()
        await cm.broadcast_progress("not a dict")

    @pytest.mark.asyncio
    async def test_broadcast_progress_type_error(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        ws.send_json.side_effect = TypeError("serialize error")
        await cm.connect(ws)
        await cm.broadcast_progress({"data": object()})

    @pytest.mark.asyncio
    async def test_send_personal_message_none(self):
        cm = ConnectionManager()
        await cm.send_personal_message({"data": "test"}, None)

    @pytest.mark.asyncio
    async def test_send_personal_message_invalid_type(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.send_personal_message("not a dict", ws)

    @pytest.mark.asyncio
    async def test_send_personal_message_type_error(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        ws.send_json.side_effect = TypeError("serialize error")
        await cm.connect(ws)
        await cm.send_personal_message({"data": object()}, ws)

    @pytest.mark.asyncio
    async def test_connect_max_connections_exceeded_exception(self):
        cm = ConnectionManager(max_connections=0)
        ws = AsyncMock()
        ws.close.side_effect = RuntimeError("Close error")
        result = await cm.connect(ws)
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_invalid_token_type_exception(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        ws.close.side_effect = RuntimeError("Close error")
        result = await cm.connect(ws, token=123)
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_invalid_token_exception(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        ws.close.side_effect = RuntimeError("Close error")
        result = await cm.connect(ws, token="invalid")
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_user_limit_exception(self):
        cm = ConnectionManager()
        tm = TokenManager()
        tokens = [tm.generate_token("user_limit_ex") for _ in range(MAX_CONNECTIONS_PER_USER + 1)]
        ws_list = [AsyncMock() for _ in range(MAX_CONNECTIONS_PER_USER + 1)]
        ws_list[-1].close.side_effect = RuntimeError("Close error")
        with patch("websocket_handler.token_manager", tm):
            for i in range(MAX_CONNECTIONS_PER_USER):
                await cm.connect(ws_list[i], tokens[i])
            result = await cm.connect(ws_list[-1], tokens[-1])
            assert result is False

    @pytest.mark.asyncio
    async def test_connect_accept_exception(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        ws.accept.side_effect = RuntimeError("Accept failed")
        result = await cm.connect(ws)
        assert result is False

    @pytest.mark.asyncio
    async def test_close_websocket_close_exception(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        ws.close.side_effect = RuntimeError("Close fail")
        await cm.connect(ws)
        await cm.close()

    @pytest.mark.asyncio
    async def test_handle_websocket_generate_thumbnail_success(self):
        """generate_thumbnail コマンドを受信し、正常に生成・検証された場合"""
        ws = AsyncMock()
        command = {
            "action": "generate_thumbnail",
            "output_path": "dummy_thumb.png",
            "width": 800,
            "height": 600,
            "text": "Hello WS"
        }
        import json
        ws.receive_text.side_effect = [json.dumps(command), WebSocketDisconnect()]
        
        # トークンマネージャーのモック化とトークン生成
        tm = TokenManager()
        token = tm.generate_token("user_success")
        
        mock_overlay_inst = MagicMock()
        mock_overlay_inst.validate_thumbnail.return_value = {"valid": True}
        
        # progress_manager をクリーンにする
        await progress_manager.close()
        
        # クリーンアップループタスクが起動されて無限ループするのを防ぐため、_cleanup_loop を走らせない
        with patch.object(progress_manager, "_ensure_cleanup_task_running"),              patch("websocket_handler.token_manager", tm),              patch("combined_overlay.CombinedOverlay", return_value=mock_overlay_inst):
            
            await handle_progress_websocket(ws, token=token)
            
            mock_overlay_inst.generate_thumbnail.assert_called_once_with(
                "dummy_thumb.png", width=800, height=600, text="Hello WS"
            )
            mock_overlay_inst.validate_thumbnail.assert_called_once_with("dummy_thumb.png")
            
            send_calls = [args[0][0] for args in ws.send_json.call_args_list]
            
            # connected メッセージが含まれているはず
            connected_calls = [c for c in send_calls if c.get("type") == "connected"]
            assert len(connected_calls) == 1
            
            thumb_results = [c for c in send_calls if c.get("type") == "thumbnail_result"]
            assert len(thumb_results) == 1
            assert thumb_results[0]["status"] == "success"
            assert thumb_results[0]["data"] == {"valid": True}
            
            progress_updates = [c for c in send_calls if c.get("type") == "progress_update"]
            assert len(progress_updates) == 1
            assert progress_updates[0]["phase"] == "thumbnail"
            assert progress_updates[0]["step"] == "completed"

    @pytest.mark.asyncio
    async def test_handle_websocket_generate_thumbnail_failure(self):
        """generate_thumbnail コマンドで例外が発生した場合"""
        ws = AsyncMock()
        command = {
            "action": "generate_thumbnail",
            "output_path": "dummy_thumb.png",
            "width": 800,
            "height": 600,
            "text": "Hello WS"
        }
        import json
        ws.receive_text.side_effect = [json.dumps(command), WebSocketDisconnect()]
        
        tm = TokenManager()
        token = tm.generate_token("user_failure")
        
        mock_overlay_inst = MagicMock()
        mock_overlay_inst.generate_thumbnail.side_effect = Exception("Overlay creation failed")
        
        await progress_manager.close()
        
        with patch.object(progress_manager, "_ensure_cleanup_task_running"),              patch("websocket_handler.token_manager", tm),              patch("combined_overlay.CombinedOverlay", return_value=mock_overlay_inst):
            
            await handle_progress_websocket(ws, token=token)
            
            send_calls = [args[0][0] for args in ws.send_json.call_args_list]
            
            thumb_results = [c for c in send_calls if c.get("type") == "thumbnail_result"]
            assert len(thumb_results) == 1
            assert thumb_results[0]["status"] == "failed"
            assert "Overlay creation failed" in thumb_results[0]["error"]
            
            error_calls = [c for c in send_calls if c.get("type") == "error"]
            assert len(error_calls) == 1
            assert error_calls[0]["code"] == "THUMB_GEN_ERR"
