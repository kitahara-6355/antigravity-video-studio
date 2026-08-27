import os
import asyncio
import logging
from google.genai.errors import APIError
from google.genai import types
from dotenv import load_dotenv

# Model Registry (SSoT: model_config.json)
try:
    from model_registry import get_model
except ImportError:
    # **モデル ID を直書きしない**（R1.5-C6）。正典は model_config.json で、
    # それを読む解決器が model_policy（標準ライブラリだけに依存するので
    # model_registry より落ちにくい）。直書きの既定値は入替のたびに腐り、
    # 実際それで 2026-10-16 に提供終了する 2.5 系が本番の実行経路に居座った。
    from model_policy import resolve as _resolve

    def get_model(task):
        return _resolve(task).model

load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LiveAPIHandler:
    """
    Gemini Multimodal Live API handler for real-time interaction.
    Manages persistent async sessions and handles bidirectional streaming.
    """
    def __init__(self, model_id=None):
        if model_id is None:
            model_id = get_model("live_api")
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY is not set.")
            
        from gemini_client_factory import get_gemini_client
        self.client = get_gemini_client()
        # NOTE: Live API requires api_version='v1alpha' — may need special client
        self.model_id = model_id
        self._session_context = None
        self.session = None

    def _prepare_system_instruction(self, system_instruction):
        """Converts raw system instruction string to types.Content structure if needed."""
        if not system_instruction:
            return None
        try:
            if isinstance(system_instruction, str):
                return types.Content(
                    parts=[types.Part.from_text(text=system_instruction)]
                )
        except (TypeError, ValueError, AttributeError) as e:
            logger.warning(f"Could not convert system_instruction to Content: {e}")
        return system_instruction

    def _prepare_config(self, config=None, system_instruction=None):
        """Prepares session configuration and merges system instructions."""
        if not config:
            config = {"generation_config": {"response_modalities": ["AUDIO"]}}
        
        prepared_instruction = self._prepare_system_instruction(system_instruction)
        if prepared_instruction:
            if isinstance(config, dict):
                config["system_instruction"] = prepared_instruction
            else:
                setattr(config, "system_instruction", prepared_instruction)
        return config

    async def start(self, config=None, system_instruction=None):
        """Initializes the session context."""
        session_config = self._prepare_config(config=config, system_instruction=system_instruction)
        logger.info(f"🔗 Connecting to Gemini Live API: {self.model_id}")
        self._session_context = self.client.aio.live.connect(model=self.model_id, config=session_config)
        return self._session_context

    async def run(self, send_queue: asyncio.Queue, receive_callback, system_instruction=None):
        """
        Main loop for bidirectional communication.
        send_queue: items to send to Gemini
        receive_callback: function to call with messages from Gemini
        """
        try:
            if not self._session_context:
                await self.start(system_instruction=system_instruction)

            async with self._session_context as session:
                self.session = session
                logger.info("✅ Live API Session Established.")
                await self._execute_session_loop(send_queue, receive_callback)
                    
        except APIError as e:
            logger.error(f"❌ Session API Error: {e}", exc_info=True)
            await receive_callback("error_fallback")
        except (TypeError, ValueError, RuntimeError, OSError, ConnectionError) as e:
            logger.error(f"❌ Unexpected Session Error ({type(e).__name__}): {e}", exc_info=True)
            await receive_callback("error_fallback")
        finally:
            self.session = None
            logger.info("🛑 Live API Session Closed.")

    async def _execute_session_loop(self, send_queue: asyncio.Queue, receive_callback):
        """Creates and manages concurrent tasks for sending and receiving."""
        send_task = asyncio.create_task(self._send_loop(send_queue))
        receive_task = asyncio.create_task(self._receive_loop(receive_callback))
        
        done, pending = await asyncio.wait(
            [send_task, receive_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        self._handle_completed_tasks(done)
        await self._cancel_pending_tasks(pending)

    def _handle_completed_tasks(self, done):
        """Log exceptions of completed tasks."""
        for task in done:
            if not task.cancelled():
                exc = task.exception()
                if exc:
                    logger.error(f"❌ Session task failed with exception: {exc}", exc_info=exc)

    async def _cancel_pending_tasks(self, pending):
        """Cancel and clean up any pending tasks."""
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def _prepare_payload(self, queue_item):
        """Formats the queue item into API-compliant payload structure."""
        if isinstance(queue_item, str):
            return {
                "client_content": {
                    "turns": [
                        {
                            "role": "user",
                            "parts": [{"text": queue_item}]
                        }
                    ]
                }
            }
        elif isinstance(queue_item, dict) and "data" in queue_item and "mime_type" in queue_item:
            return {
                "realtime_input": {
                    "media_chunks": [
                        {
                            "data": queue_item["data"],
                            "mime_type": queue_item["mime_type"]
                        }
                    ]
                }
            }
        return queue_item

    async def _send_loop(self, queue: asyncio.Queue):
        """Consumes the queue and sends formatted payloads to Gemini."""
        while True:
            queue_item = await queue.get()
            if queue_item is None:  # Shutdown signal
                break
            try:
                request_payload = self._prepare_payload(queue_item)
                await self.session.send(request_payload)
            except asyncio.CancelledError:
                logger.info("📡 Send loop cancelled.")
                raise
            except APIError as e:
                logger.error(f"⚠️ API Error sending to Gemini: {e}", exc_info=True)
                break
            except (TypeError, ValueError, AttributeError, RuntimeError, OSError) as e:
                logger.error(f"⚠️ Unexpected error sending to Gemini ({type(e).__name__}): {e}", exc_info=True)
                break

    async def _receive_loop(self, callback):
        """Listens for responses from Gemini."""
        try:
            async for message in self.session:
                await callback(message)
        except asyncio.CancelledError:
            logger.info("📡 Receive loop cancelled.")
            raise
        except APIError as e:
            logger.error(f"⚠️ API Error listening to Gemini: {e}", exc_info=True)
            await callback("error_fallback")
        except (TypeError, ValueError, RuntimeError, OSError) as e:
            logger.error(f"⚠️ Unexpected error listening to Gemini ({type(e).__name__}): {e}", exc_info=True)
            await callback("error_fallback")


