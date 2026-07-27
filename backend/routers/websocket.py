"""
WebSocket Router - リアルタイム通信関連エンドポイント
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
import asyncio
import logging

# Model Registry (SSoT: model_config.json)
try:
    from model_registry import get_model
except ImportError:
    def get_model(task): return "gemini-2.5-flash"

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """全接続にブロードキャスト"""
        failed_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
                failed_connections.append(connection)
        for connection in failed_connections:
            self.disconnect(connection)


manager = ConnectionManager()


@router.websocket("/ws/progress")
async def websocket_progress_endpoint(websocket: WebSocket):
    """リアルタイム進捗通知WebSocket"""
    await manager.connect(websocket)
    try:
        while True:
            # クライアントからのメッセージを待機
            data = await websocket.receive_text()
            
            # エコーバック（接続確認用）
            await websocket.send_json({
                "type": "echo",
                "message": data
            })
    except WebSocketDisconnect:
        logger.info("Progress WebSocket client disconnected")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Progress WebSocket error: {e}")
        try:
            await websocket.close(code=1011, reason=str(e))
        except HTTPException:
            raise
        except Exception as close_err:
            logger.debug(f"Failed to close progress websocket: {close_err}")
    finally:
        manager.disconnect(websocket)


async def _handle_ai_message(websocket: WebSocket, message):
    """AIからの応答メッセージをクライアントに転送"""
    if hasattr(message, 'text') and message.text:
        await websocket.send_json({
            "type": "ai_response",
            "content": message.text
        })
    elif hasattr(message, 'data') and message.data:
        data_str = message.data.hex() if isinstance(message.data, bytes) else str(message.data)
        await websocket.send_json({
            "type": "ai_audio",
            "data": data_str
        })


async def _receive_from_client(websocket: WebSocket, session):
    """クライアントからの入力を受信してGemini Liveセッションに送る"""
    try:
        while True:
            data = await websocket.receive_json()
            
            if not isinstance(data, dict):
                logger.warning(f"Invalid message format received (not a dict): {data}")
                await websocket.send_json({"type": "error", "message": "Message format must be a JSON object"})
                continue
                
            msg_type = data.get("type")
            if msg_type == "text":
                content = data.get("content")
                if not content:
                    logger.warning("Empty content in text message")
                    await websocket.send_json({"type": "error", "message": "Text message content cannot be empty"})
                    continue
                await session.send_client_content(
                    turns=[{"role": "user", "parts": [{"text": content}]}]
                )
            elif msg_type == "audio":
                content = data.get("content")
                if not content:
                    logger.warning("Empty content in audio message")
                    await websocket.send_json({"type": "error", "message": "Audio message content cannot be empty"})
                    continue
                try:
                    audio_bytes = bytes.fromhex(content)
                except ValueError as ve:
                    logger.warning(f"Invalid hex string in audio message: {ve}")
                    await websocket.send_json({"type": "error", "message": "Invalid hex format in audio content"})
                    continue
                await session.send_realtime_input(audio=audio_bytes)
            else:
                logger.warning(f"Unknown message type received: {msg_type}")
                await websocket.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})
    except WebSocketDisconnect:
        logger.info("Client disconnected in receive task")
    except HTTPException as e:
        logger.warning(f"HTTPException in receive task: {e}")
    except Exception as e:
        logger.error(f"Error receiving from client: {e}")
        raise


async def _receive_from_ai(websocket: WebSocket, session):
    """AIからの応答を受信してクライアントに転送"""
    try:
        async for message in session.receive():
            await _handle_ai_message(websocket, message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error receiving from AI: {e}")
        raise


async def _cancel_pending_tasks(pending):
    """残った非同期タスクをキャンセルしクリーンアップする"""
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Pending task error on cancel: {e}")


def _check_done_tasks(done):
    """終了したタスクの例外をチェックして伝播させる"""
    for task in done:
        if not task.cancelled():
            exc = task.exception()
            if exc:
                raise exc


@router.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    """Gemini Live API連携WebSocket"""
    await websocket.accept()
    
    try:
        from gemini_client_factory import get_gemini_client
        client = get_gemini_client()
        
        # Gemini Liveセッション開始
        # SSoT: model_config.json task_mapping
        async with client.aio.live.connect(model=get_model("live_api")) as session:
            receive_task = asyncio.create_task(_receive_from_client(websocket, session))
            ai_task = asyncio.create_task(_receive_from_ai(websocket, session))
            
            # どちらか一方が終了したら完了とする
            done, pending = await asyncio.wait(
                [receive_task, ai_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # 残ったタスクをキャンセル
            await _cancel_pending_tasks(pending)
            
            # 終了したタスクの例外をチェックして伝播させる
            _check_done_tasks(done)
            
    except WebSocketDisconnect:
        logger.info("Client disconnected from live session")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Live session error: {e}")
        try:
            await websocket.close(code=1011, reason=str(e))
        except HTTPException:
            raise
        except Exception as close_err:
            logger.debug(f"Failed to close websocket (might already be closed): {close_err}")


async def broadcast_progress(progress_data: dict):
    """外部から呼び出し可能なブロードキャスト関数"""
    await manager.broadcast(progress_data)
