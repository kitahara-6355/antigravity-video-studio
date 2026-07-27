"""
共通エラーレスポンススキーマ

推奨タスク R3.3: 統一エラーレスポンス形式
全APIで一貫したエラーレスポンスを提供
"""

import warnings

# Pydantic の shadows warning および V2 config warning を抑制
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message="Field name .* shadows an attribute in parent"
)
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message="Valid config keys have changed in V2"
)

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from enum import Enum
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ErrorCode(str, Enum):
    """エラーコード定義"""
    # 一般
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    
    # ドメイン固有
    PROCESSING_FAILED = "PROCESSING_FAILED"
    AI_ERROR = "AI_ERROR"
    FILE_ERROR = "FILE_ERROR"
    WEBSOCKET_ERROR = "WEBSOCKET_ERROR"


class ErrorDetail(BaseModel):
    """エラー詳細"""
    field: Optional[str] = None
    message: str
    code: Optional[str] = None


class StandardErrorResponse(BaseModel):
    """標準エラーレスポンス"""
    success: bool = False
    error: str
    code: ErrorCode
    details: Optional[List[ErrorDetail]] = None
    request_id: Optional[str] = None
    timestamp: str
    
    model_config = ConfigDict(use_enum_values=True)


def create_error_response(
    code: ErrorCode,
    message: str,
    status_code: int = 500,
    details: Optional[List[ErrorDetail]] = None,
    request_id: Optional[str] = None
) -> JSONResponse:
    """標準エラーレスポンス生成"""
    error_response = StandardErrorResponse(
        error=message,
        code=code,
        details=details,
        request_id=request_id,
        timestamp=datetime.now().isoformat()
    )
    
    return JSONResponse(
        status_code=status_code,
        content=error_response.model_dump()
    )


def _extract_request_id(request: Request) -> Optional[str]:
    """リクエストヘッダーからリクエストIDを抽出する"""
    if request is None:
        return None
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    if hasattr(headers, "get"):
        try:
            return headers.get("X-Request-ID")
        except HTTPException:
            raise
        except (AttributeError, TypeError) as e:
            logger.warning(f"Failed to get X-Request-ID from headers: {e}")
            return None
    return None


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """グローバル例外ハンドラ"""
    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)
        
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    try:
        request_id = _extract_request_id(request)
    except HTTPException:
        raise
    except (AttributeError, TypeError) as e:
        logger.error(f"Error extracting request ID in global_exception_handler: {e}", exc_info=True)
        request_id = None
    
    return create_error_response(
        code=ErrorCode.INTERNAL_ERROR,
        message="予期せぬエラーが発生しました",
        status_code=500,
        request_id=request_id
    )


def _map_status_code_to_error_code(status_code: int) -> ErrorCode:
    """HTTPステータスコードからErrorCode Enumへマッピングする"""
    code_map = {
        400: ErrorCode.VALIDATION_ERROR,
        401: ErrorCode.UNAUTHORIZED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        500: ErrorCode.INTERNAL_ERROR,
    }
    return code_map.get(status_code, ErrorCode.INTERNAL_ERROR)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """HTTPExceptionハンドラ"""
    try:
        request_id = _extract_request_id(request)
    except HTTPException:
        raise
    except (AttributeError, TypeError) as e:
        logger.error(f"Error extracting request ID in http_exception_handler: {e}", exc_info=True)
        request_id = None
        
    error_code = _map_status_code_to_error_code(exc.status_code)
    
    detail = exc.detail
    message = str(detail) if not isinstance(detail, (dict, list)) else "HTTP error occurred"
    details = None
    
    if isinstance(detail, dict):
        msg = detail.get("message") or detail.get("error") or str(detail)
        message = str(msg)
        field = detail.get("field")
        err_code = detail.get("code")
        details = [ErrorDetail(field=field, message=message, code=err_code)]
    elif isinstance(detail, list):
        details = []
        for item in detail:
            if isinstance(item, dict):
                details.append(ErrorDetail(
                    field=item.get("field"),
                    message=item.get("message") or item.get("error") or str(item),
                    code=item.get("code")
                ))
            else:
                details.append(ErrorDetail(message=str(item)))
                
    return create_error_response(
        code=error_code,
        message=message,
        status_code=exc.status_code,
        details=details,
        request_id=request_id
    )


def register_error_handlers(app: FastAPI) -> None:
    """FastAPIアプリにエラーハンドラを登録"""
    app.add_exception_handler(Exception, global_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
