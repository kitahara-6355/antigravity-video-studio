"""
Legacy Live WebSocket Router
main.py から分離した WebSocket Live API エンドポイント

エンドポイント:
- /ws/live
"""

import base64
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

router = APIRouter(tags=["Live WebSocket"])
logger = logging.getLogger(__name__)


def parse_ai_message(message) -> dict:
    """AIのメッセージオブジェクトからtextやaudioのデータをパースしてpayloadを辞書で返す"""
    payload = {}
    if message is None:
        return payload

    server_content = getattr(message, "server_content", None)
    if not server_content:
        return payload

    model_turn = getattr(server_content, "model_turn", None)
    if not model_turn:
        return payload

    parts = getattr(model_turn, "parts", None)
    if not parts or not isinstance(parts, (list, tuple)):
        return payload

    for part in parts:
        text_val = getattr(part, "text", None)
        if text_val:
            payload["text"] = text_val

        inline_data_val = getattr(part, "inline_data", None)
        if inline_data_val:
            data = getattr(inline_data_val, "data", None)
            if data is not None:
                payload["audio"] = base64.b64encode(data).decode("utf-8")

    return payload


async def receive_from_client_loop(websocket: WebSocket, send_queue: asyncio.Queue):
    """クライアントからデータを受信し、キューに入れるループ処理"""
    try:
        while True:
            data = await websocket.receive_json()
            if data is None or not isinstance(data, dict):
                logger.warning("Received non-dict data from client")
                continue
            if "text" in data:
                await send_queue.put(data["text"])
            if "audio" in data:
                await send_queue.put({"data": data["audio"], "mime_type": "audio/pcm;rate=16000"})
            if "media" in data:
                media_list = data["media"]
                if isinstance(media_list, (list, tuple)):
                    for chunk in media_list:
                        await send_queue.put(chunk)
                else:
                    logger.warning("Media data is not a list/tuple")
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Receive from client error: {e}")
    finally:
        await send_queue.put(None)


@router.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    from live_api_handler import LiveAPIHandler
    from director_engine import DirectorBrain

    await websocket.accept()

    brain = DirectorBrain()
    system_instruction = brain._get_system_instruction(mode="director")
    handler = LiveAPIHandler()
    send_queue = asyncio.Queue()

    async def ai_callback(message):
        try:
            payload = parse_ai_message(message)
            if payload:
                await websocket.send_json(payload)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in ai_callback: {e}")

    try:
        handler_task = asyncio.create_task(
            handler.run(send_queue, ai_callback, system_instruction=system_instruction)
        )
        receive_task = asyncio.create_task(
            receive_from_client_loop(websocket, send_queue)
        )
        done, pending = await asyncio.wait(
            [handler_task, receive_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        for task in done:
            if not task.cancelled():
                exc = task.exception()
                if exc:
                    raise exc
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"WebSocket Bridge Error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
