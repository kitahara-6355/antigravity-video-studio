"""
WebSocket進捗通知ハンドラー

システム改善計画 フェーズ3: リアルタイム進捗通知
接続されたクライアントに処理進捗をリアルタイムで配信

追加機能:
- P3.3: WebSocket認証統合
- P3.2: 接続数制限
- P7.1: タイムアウト設定
- P7.2: キャンセル対応
"""

from fastapi import WebSocket, WebSocketDisconnect, Query
from typing import List, Dict, Any, Optional, Set
import asyncio
import json
import logging
import time
import secrets
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ===========================================
# P3.3: 認証トークン管理
# ===========================================

@dataclass
class AuthToken:
    """認証トークン"""
    token: str
    user_id: str
    expires_at: float = 0
    
    def is_expired(self) -> bool:
        return time.time() > self.expires_at if self.expires_at > 0 else False


class TokenManager:
    """トークン管理"""
    def __init__(self):
        self._tokens: Dict[str, AuthToken] = {}
    
    def generate_token(self, user_id: str, ttl: int = 3600) -> str:
        """トークン生成"""
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("user_id must be a non-empty string")
        if not isinstance(ttl, (int, float)) or ttl <= 0:
            raise ValueError("ttl must be a positive number")
        token = secrets.token_urlsafe(32)
        self._tokens[token] = AuthToken(
            token=token,
            user_id=user_id,
            expires_at=time.time() + ttl
        )
        return token
    
    def validate_token(self, token: str) -> Optional[str]:
        """トークン検証、user_idを返す"""
        if not isinstance(token, str) or not token:
            return None
        auth_token = self._tokens.get(token)
        if not auth_token:
            return None
        if auth_token.is_expired():
            self._tokens.pop(token, None)
            return None
        return auth_token.user_id
    
    def revoke_token(self, token: str) -> bool:
        """トークン無効化"""
        if not isinstance(token, str) or not token:
            return False
        return self._tokens.pop(token, None) is not None


token_manager = TokenManager()


# ===========================================
# P3.2: 接続数制限
# ===========================================

MAX_CONNECTIONS = 100  # 最大同時接続数
MAX_CONNECTIONS_PER_USER = 5  # ユーザー当たり最大接続数


# ===========================================
# P7.1/P7.2: タイムアウト/キャンセル
# ===========================================

CONNECTION_TIMEOUT = 300  # 5分
HEARTBEAT_INTERVAL = 30   # 30秒


@dataclass
class ConnectionInfo:
    """接続情報"""
    websocket: WebSocket
    user_id: Optional[str] = None
    connected_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    cancelled: bool = False


class ConnectionManager:
    """WebSocket接続管理クラス（強化版）"""
    
    def __init__(self, max_connections: int = MAX_CONNECTIONS):
        self.connections: Dict[WebSocket, ConnectionInfo] = {}
        self.user_connections: Dict[str, Set[WebSocket]] = {}
        self.max_connections = max_connections
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._connection_timeout = CONNECTION_TIMEOUT
    
    @property
    def active_connections(self) -> List[WebSocket]:
        """後方互換性のため"""
        return list(self.connections.keys())
    
    async def _check_max_connections_limit(self, websocket: WebSocket) -> bool:
        """システム全体の最大接続数をチェックし、超過していればクローズする"""
        if len(self.connections) >= self.max_connections:
            try:
                await websocket.close(code=1013, reason="Max connections reached")
            except (RuntimeError, ConnectionError, OSError) as e:
                logger.debug(f"Error closing websocket during max connection rejection: {e}")
            logger.warning("接続拒否: 最大接続数超過")
            return False
        return True

    async def _authenticate_and_check_user_limit(self, websocket: WebSocket, token: str) -> tuple[bool, Optional[str]]:
        """トークンを検証し、ユーザー毎の接続数制限をチェックする。失敗した場合はクローズする"""
        if not isinstance(token, str):
            try:
                await websocket.close(code=4001, reason="Invalid token type")
            except (RuntimeError, ConnectionError, OSError) as e:
                logger.debug(f"Error closing websocket during invalid token type rejection: {e}")
            logger.warning("接続拒否: トークンの型が無効")
            return False, None
        
        user_id = token_manager.validate_token(token)
        if not user_id:
            try:
                await websocket.close(code=4001, reason="Invalid token")
            except (RuntimeError, ConnectionError, OSError) as e:
                logger.debug(f"Error closing websocket during invalid token rejection: {e}")
            logger.warning("接続拒否: 無効なトークン")
            return False, None
        
        # ユーザー当たりの接続数チェック
        user_conns = self.user_connections.get(user_id, set())
        if len(user_conns) >= MAX_CONNECTIONS_PER_USER:
            try:
                await websocket.close(code=4002, reason="Too many connections")
            except (RuntimeError, ConnectionError, OSError) as e:
                logger.debug(f"Error closing websocket during user connection limit rejection: {e}")
            logger.warning(f"接続拒否: ユーザー{user_id}の接続数超過")
            return False, None
            
        return True, user_id

    def _register_connection(self, websocket: WebSocket, user_id: Optional[str]):
        """接続情報を内部ディクショナリに登録する"""
        self.connections[websocket] = ConnectionInfo(
            websocket=websocket,
            user_id=user_id
        )
        if user_id:
            if user_id not in self.user_connections:
                self.user_connections[user_id] = set()
            self.user_connections[user_id].add(websocket)

    async def _ensure_cleanup_task_running(self):
        """クリーンアップループタスクが開始されていることを保証する"""
        async with self._lock:
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def connect(self, websocket: WebSocket, token: str = None) -> bool:
        """新しい接続を受け入れ（認証付き）"""
        if websocket is None:
            logger.warning("接続拒否: websocketがNoneです")
            return False

        async with self._lock:
            # 1. 全体接続数制限チェック
            if not await self._check_max_connections_limit(websocket):
                return False
            
            # 2. 認証 & ユーザー接続数制限チェック
            user_id = None
            if token is not None:
                success, uid = await self._authenticate_and_check_user_limit(websocket, token)
                if not success:
                    return False
                user_id = uid
            
            # 3. WebSocket accept
            try:
                await websocket.accept()
            except (RuntimeError, ConnectionError, OSError) as e:
                logger.warning(f"WebSocket accept失敗: {e}")
                return False
                
            # 4. 接続情報の登録
            self._register_connection(websocket, user_id)
        
        logger.info(f"WebSocket接続: 現在{len(self.connections)}クライアント接続中")
        
        # 5. クリーンアップタスク起動
        await self._ensure_cleanup_task_running()
        
        return True
    
    async def disconnect(self, websocket: WebSocket):
        """接続を削除"""
        if websocket is None:
            return
        async with self._lock:
            info = self.connections.pop(websocket, None)
            if info and info.user_id:
                user_conns = self.user_connections.get(info.user_id, set())
                user_conns.discard(websocket)
                if not user_conns:
                    self.user_connections.pop(info.user_id, None)
        logger.info(f"WebSocket切断: 現在{len(self.connections)}クライアント接続中")
    
    async def touch(self, websocket: WebSocket):
        """最終アクティビティ時刻を更新"""
        if websocket is None:
            return
        async with self._lock:
            if websocket in self.connections:
                self.connections[websocket].last_activity = time.time()
    
    async def cancel(self, websocket: WebSocket):
        """P7.2: 接続キャンセル"""
        if websocket is None:
            return
        async with self._lock:
            if websocket in self.connections:
                self.connections[websocket].cancelled = True
    
    def is_cancelled(self, websocket: WebSocket) -> bool:
        """キャンセル状態確認"""
        if websocket is None:
            return True
        info = self.connections.get(websocket)
        return info.cancelled if info else True
    
    async def _cleanup_loop(self):
        """P7.1: タイムアウト接続のクリーンアップ"""
        while True:
            async with self._lock:
                if not self.connections:
                    break
            
            await asyncio.sleep(1)
            
            now = time.time()
            to_disconnect = []
            
            async with self._lock:
                for ws, info in list(self.connections.items()):
                    if now - info.last_activity > self._connection_timeout:
                        to_disconnect.append(ws)
            
            for ws in to_disconnect:
                try:
                    await ws.close(code=1000, reason="Connection timeout")
                except (RuntimeError, ConnectionError, OSError) as e:
                    logger.debug(f"WebSocket close during cleanup: {e}")
                await self.disconnect(ws)
            
            if to_disconnect:
                logger.info(f"タイムアウトで{len(to_disconnect)}接続をクリーンアップ")
    
    async def broadcast_progress(self, message: Dict[str, Any]):
        """全クライアントに進捗を配信"""
        if not isinstance(message, dict):
            logger.warning("送信メッセージが辞書型ではありません")
            return
        
        async with self._lock:
            if not self.connections:
                return
            targets = list(self.connections.keys())
        
        disconnected = []
        for websocket in targets:
            try:
                await websocket.send_json(message)
            except (RuntimeError, ConnectionError, OSError) as e:
                logger.warning(f"WebSocket送信エラー: {e}")
                disconnected.append(websocket)
            except TypeError as e:
                logger.error(f"JSONシリアライズエラー: {e}")
        
        for conn in disconnected:
            await self.disconnect(conn)
    
    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket):
        """特定のクライアントにメッセージを送信"""
        if websocket is None:
            return
        if not isinstance(message, dict):
            logger.warning("個別送信メッセージが辞書型ではありません")
            return
        try:
            await websocket.send_json(message)
            await self.touch(websocket)
        except (RuntimeError, ConnectionError, OSError) as e:
            logger.warning(f"個別メッセージ送信エラー: {e}")
        except TypeError as e:
            logger.error(f"JSONシリアライズエラー: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """接続統計"""
        return {
            "total_connections": len(self.connections),
            "max_connections": self.max_connections,
            "users_connected": len(self.user_connections),
            "connections_by_user": {
                uid: len(conns) for uid, conns in self.user_connections.items()
            }
        }

    async def close(self):
        """リソースを解放し、クリーンアップタスクを停止"""
        async with self._lock:
            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
                self._cleanup_task = None
            
            # 残っているすべての接続を閉じる
            for ws in list(self.connections.keys()):
                try:
                    await ws.close(code=1000, reason="Manager closing")
                except (RuntimeError, ConnectionError, OSError):
                    pass
            self.connections.clear()
            self.user_connections.clear()


# シングルトンインスタンス
progress_manager = ConnectionManager()


class ProgressBroadcaster:
    """進捗をブロードキャストするユーティリティクラス"""
    
    def __init__(self, manager: ConnectionManager = None):
        self.manager = manager or progress_manager
    
    async def update_phase(self, phase: str, progress: int, step: str, 
                           eta: int = None, preview_url: str = None):
        """処理フェーズを更新してブロードキャスト"""
        message = {
            "type": "progress_update",
            "phase": phase,
            "progress": progress,
            "step": step,
            "eta": eta,
            "previewUrl": preview_url,
            "timestamp": time.time()
        }
        await self.manager.broadcast_progress(message)
    
    async def send_error(self, error_message: str, error_code: str = None):
        """エラーをブロードキャスト"""
        message = {
            "type": "error",
            "message": error_message,
            "code": error_code,
            "timestamp": time.time()
        }
        await self.manager.broadcast_progress(message)
    
    async def send_completion(self, result: Dict[str, Any] = None):
        """完了通知をブロードキャスト"""
        message = {
            "type": "complete",
            "result": result or {},
            "timestamp": time.time()
        }
        await self.manager.broadcast_progress(message)

    async def update_council_state(self, session_id: str, agent_name: str, 
                                   state: str, stance: str = "NEUTRAL", 
                                   detail: str = ""):
        """合議の進行状況（各エージェントの思考や発言）を更新してブロードキャスト"""
        message = {
            "type": "council_update",
            "sessionId": session_id,
            "agent": agent_name,
            "state": state,       # "thinking" (思考中), "done" (思考完了)
            "stance": stance,     # "AGREE", "DISAGREE", "NEUTRAL"
            "detail": detail,     # 発言内容サマリー
            "timestamp": time.time()
        }
        await self.manager.broadcast_progress(message)


# グローバルブロードキャスター
broadcaster = ProgressBroadcaster()


async def _process_client_command(websocket: WebSocket, data: str):
    """クライアントからの受信コマンドを処理する"""
    await progress_manager.touch(websocket)
    
    # JSONコマンドのパースを試みる
    try:
        command_data = json.loads(data)
        if isinstance(command_data, dict):
            action = command_data.get("action")
            if action == "generate_thumbnail":
                output_path = command_data.get("output_path", "backend/temp/ws_thumbnail.png")
                width = command_data.get("width", 1280)
                height = command_data.get("height", 720)
                text = command_data.get("text", "Thumbnail")
                
                from combined_overlay import CombinedOverlay
                overlay = CombinedOverlay()
                
                try:
                    overlay.generate_thumbnail(output_path, width=width, height=height, text=text)
                    val_result = overlay.validate_thumbnail(output_path)
                    
                    await websocket.send_json({
                        "type": "thumbnail_result",
                        "status": "success",
                        "data": val_result
                    })
                    await broadcaster.update_phase(
                        phase="thumbnail",
                        progress=100,
                        step="completed",
                        preview_url=str(output_path)
                    )
                except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, ConnectionError) as e:
                    await websocket.send_json({
                        "type": "thumbnail_result",
                        "status": "failed",
                        "error": str(e)
                    })
                    await broadcaster.send_error(
                        error_message=f"Thumbnail generation failed: {str(e)}",
                        error_code="THUMB_GEN_ERR"
                    )
                return
    except json.JSONDecodeError:
        pass

    if data == "ping":
        await websocket.send_json({"type": "pong"})
    elif data == "cancel":
        await progress_manager.cancel(websocket)
        await websocket.send_json({"type": "cancelled"})
    elif data == "stats":
        await websocket.send_json({
            "type": "stats",
            "data": progress_manager.get_stats()
        })
    else:
        await websocket.send_json({
            "type": "error",
            "message": f"Unknown command: {data}"
        })


async def handle_progress_websocket(websocket: WebSocket, token: str = Query(None)):
    """進捗WebSocketのエンドポイントハンドラ（認証対応）"""
    if websocket is None:
        return
        
    if not await progress_manager.connect(websocket, token):
        return
    
    try:
        # 接続時に現在の状態を送信
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket接続が確立されました",
            "stats": progress_manager.get_stats()
        })
        
        # クライアントからのメッセージを待機
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=HEARTBEAT_INTERVAL * 2
                )
                
                await _process_client_command(websocket, data)
                    
            except asyncio.TimeoutError:
                # ハートビート送信
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except (RuntimeError, ConnectionError, OSError):
                    break
            except WebSocketDisconnect:
                break
            except (RuntimeError, ConnectionError, OSError):
                break
    finally:
        await progress_manager.disconnect(websocket)
