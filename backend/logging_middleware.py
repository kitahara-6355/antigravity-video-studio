"""
ロギングミドルウェア

推奨タスク R2.2: リクエスト/レスポンスロギング
"""

import time
import logging
from typing import Callable
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("api.requests")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """リクエストロギングミドルウェア"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # リクエスト開始
        start_time = time.time()
        request_id = f"{int(start_time * 1000)}"
        
        # リクエスト情報の安全取得
        method = getattr(request, "method", "UNKNOWN")
        if not isinstance(method, str):
            method = str(method) if method is not None else "UNKNOWN"
            
        url_path = "unknown"
        if hasattr(request, "url") and request.url is not None:
            url_path = getattr(request.url, "path", "unknown")
            if not isinstance(url_path, str):
                url_path = str(url_path) if url_path is not None else "unknown"
                
        client_host = "unknown"
        if hasattr(request, "client") and request.client is not None:
            client_host = getattr(request.client, "host", "unknown")
            if not isinstance(client_host, str):
                client_host = str(client_host) if client_host is not None else "unknown"
        
        logger.info(f"[{request_id}] → {method} {url_path} from {client_host}")
        
        # リクエスト処理
        try:
            response = await call_next(request)
            
            # レスポンスが None の場合のガード
            if response is None:
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "Internal Server Error: No response generated from downstream"}
                )
            
            # レスポンス情報
            duration = (time.time() - start_time) * 1000
            status_code = getattr(response, "status_code", 500)
            logger.info(
                f"[{request_id}] ← {status_code} "
                f"({duration:.2f}ms)"
            )
            
            # レスポンスヘッダーへの安全な書き込み
            headers = getattr(response, "headers", None)
            if headers is not None and hasattr(headers, "__setitem__"):
                headers["X-Request-ID"] = request_id
                headers["X-Response-Time"] = f"{duration:.2f}ms"
            
            return response
            
        except HTTPException as e:
            # 既知の HTTP 例外はエラーログなしで再送出するが、完了ログは出力する
            duration = (time.time() - start_time) * 1000
            status_code = getattr(e, "status_code", 500)
            logger.info(
                f"[{request_id}] ← {status_code} "
                f"({duration:.2f}ms) [HTTPException]"
            )
            raise
        except BaseException as e:
            # それ以外の予期せぬ例外（BaseException含む）は経過時間とスタックトレースを含めてロギングし、再送出する
            duration = (time.time() - start_time) * 1000
            err_name = e.__class__.__name__
            known_errs = {"RuntimeError", "ValueError", "TypeError", "AttributeError", "KeyError"}
            if err_name in known_errs:
                err_label = f"{err_name}: {str(e)}"
            else:
                err_label = f"Unexpected Error ({err_name}): {str(e)}"
            logger.error(
                f"[{request_id}] ✕ {err_label} ({duration:.2f}ms)",
                exc_info=True
            )
            raise



class SlowRequestMiddleware(BaseHTTPMiddleware):
    """遅いリクエストを検出"""
    
    def __init__(self, app, threshold_ms: float = 1000):
        super().__init__(app)
        # threshold_ms が正の数値（かつ bool でない）でない場合は 1000.0 にフォールバック
        if isinstance(threshold_ms, (int, float)) and not isinstance(threshold_ms, bool) and threshold_ms > 0:
            self.threshold_ms = float(threshold_ms)
        else:
            self.threshold_ms = 1000.0
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        try:
            response = await call_next(request)
            
            # レスポンスの安全チェック
            if response is None:
                return response
                
            duration = (time.time() - start_time) * 1000
            
            threshold = getattr(self, "threshold_ms", 1000.0)
            if duration > threshold:
                method = getattr(request, "method", "UNKNOWN")
                url_path = "unknown"
                if hasattr(request, "url") and request.url is not None:
                    url_path = getattr(request.url, "path", "unknown")
                    
                logger.warning(
                    f"SLOW REQUEST: {method} {url_path} "
                    f"took {duration:.2f}ms (threshold: {threshold}ms)"
                )
            
            return response
        except BaseException as e:
            # 例外発生時も経過時間を測定し、閾値を超えている場合は警告を出力して再送出する
            duration = (time.time() - start_time) * 1000
            threshold = getattr(self, "threshold_ms", 1000.0)
            if duration > threshold:
                method = getattr(request, "method", "UNKNOWN")
                url_path = "unknown"
                if hasattr(request, "url") and request.url is not None:
                    url_path = getattr(request.url, "path", "unknown")
                logger.warning(
                    f"SLOW REQUEST WITH ERROR: {method} {url_path} "
                    f"took {duration:.2f}ms (threshold: {threshold}ms) - Error: {e.__class__.__name__}: {str(e)}"
                )
            raise


def setup_logging_middleware(app):
    """ミドルウェア設定"""
    if app is None or not hasattr(app, "add_middleware"):
        return
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SlowRequestMiddleware, threshold_ms=1000)
