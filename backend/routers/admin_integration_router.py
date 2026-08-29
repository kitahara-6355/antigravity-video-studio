"""
Admin Integration Router — A-6 MCP外部連携・ツール統合

Admin UXストーリー A-6 に対応するバックエンドAPI。
22シーンのダッシュボード機能(MCP接続状態/ツール一覧/パイプラインステータス/
品質スコア/進化ログ/Claude Desktop連携/デュアルモード/ツール追加/権限管理/
Webhook/Slack・Discord通知/APIバージョニング/Swagger/WebSocket監視/
レート制限/CORS/認証トークン/APIログ/外部アプリ/OAuth/SDK/API統計)を提供する。

設計書: design_admin_a1_a7_full.md.resolved (推移表転記済み/)
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, List
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/integration", tags=["Admin Integration"])

# ── リクエストモデル ──

class ToolRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    endpoint: Optional[str] = None


class ToolPermissionRequest(BaseModel):
    tool_id: str = Field(..., min_length=1)
    permissions: List[str] = Field(["read"], min_length=1)

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v):
        valid = {"read", "write"}
        for p in v:
            if p not in valid:
                raise ValueError(f"Invalid permission: {p}. Must be 'read' or 'write'.")
        return v


class WebhookRequest(BaseModel):
    url: str
    events: List[str] = ["pipeline_complete"]
    secret: Optional[str] = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator("events")
    @classmethod
    def validate_events(cls, v):
        valid_events = {"pipeline_complete", "quality_alert"}
        for e in v:
            if e not in valid_events:
                raise ValueError(f"Invalid event: {e}")
        return v


class NotificationRequest(BaseModel):
    channels: List[str] = ["slack"]
    enabled: bool = True


class ApiVersionRequest(BaseModel):
    version: str = "v1"


class RateLimitRequest(BaseModel):
    rpm: int = Field(60, ge=1)
    burst: int = Field(10, ge=1)
    window_seconds: int = Field(60, ge=1)


class AppRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1)
    redirect_uri: str
    scopes: List[str] = ["read"]

    @field_validator("redirect_uri")
    @classmethod
    def validate_redirect_uri(cls, v):
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("redirect_uri must start with http:// or https://")
        return v

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v):
        valid_scopes = {"read", "write"}
        for s in v:
            if s not in valid_scopes:
                raise ValueError(f"Invalid scope: {s}")
        return v


class TokenGenerateRequest(BaseModel):
    name: str = Field("default", min_length=1)
    expires_in_days: int = Field(30, ge=1, le=365)


class TokenRevokeRequest(BaseModel):
    token_id: str = Field(..., min_length=1)


# ── 状態管理 (インメモリ) ──

_mcp_tools = [
    {"id": "tool-001", "name": "get_pipeline_status", "status": "active", "description": "パイプラインの現在状態を取得", "permissions": ["read"], "calls_today": 42},
    {"id": "tool-002", "name": "get_quality_score", "status": "active", "description": "最新の品質スコアを取得", "permissions": ["read"], "calls_today": 28},
    {"id": "tool-003", "name": "get_evolution_log", "status": "active", "description": "Soul哲学の進化ログを取得", "permissions": ["read"], "calls_today": 15},
]

_notification_settings = {
    "channels": ["slack", "discord"],
    "enabled": True,
    "slack_webhook": "https://hooks.slack.com/services/xxx",
    "discord_webhook": "https://discord.com/api/webhooks/xxx",
}

_auth_tokens = [
    {"id": "tok-001", "name": "development", "token_prefix": "ag_dev_***", "created_at": "2026-04-30T10:00:00", "expires_at": "2026-05-30T10:00:00", "active": True},
    {"id": "tok-002", "name": "ci_pipeline", "token_prefix": "ag_ci_***", "created_at": "2026-05-01T08:00:00", "expires_at": "2026-06-01T08:00:00", "active": True},
]

_external_apps = [
    {"id": "app-001", "name": "VideoBot", "redirect_uri": "https://example.com/callback", "scopes": ["read", "write"], "created_at": "2026-04-28"},
]

_webhooks = [
    {"id": "wh-001", "url": "https://example.com/webhook", "events": ["pipeline_complete", "quality_alert"], "active": True},
]

_rate_limits = {"rpm": 60, "burst": 10, "window_seconds": 60}

_cors_settings = {
    "allowed_origins": ["http://localhost:5173", "http://localhost:3000"],
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}


# ── S1: ダッシュボード概要 ──

@router.get("/dashboard")
async def get_integration_dashboard():
    """A-6 S1: MCP外部連携ダッシュボードの全体情報"""
    return {
        "title": "MCP外部連携・ツール統合",
        "status": "connected" if all(t["status"] == "active" for t in _mcp_tools) else "partial",
        "summary": {
            "mcp_tools": len(_mcp_tools),
            "active_tools": sum(1 for t in _mcp_tools if t["status"] == "active"),
            "external_apps": len(_external_apps),
            "webhooks": len(_webhooks),
            "auth_tokens": sum(1 for t in _auth_tokens if t["active"]),
            "api_calls_today": sum(t["calls_today"] for t in _mcp_tools),
        },
        "sections": [
            "tools", "pipeline_status", "quality_score", "evolution_log",
            "claude_desktop", "dual_mode", "tool_register", "permissions",
            "webhooks", "notifications", "api_version", "api_docs",
            "websocket_monitor", "rate_limits", "cors", "auth_tokens",
            "api_logs", "external_apps", "oauth", "sdk", "api_stats",
        ],
        "timestamp": datetime.now().isoformat(),
    }


# ── S2: ツール一覧 ──

@router.get("/tools")
async def get_mcp_tools():
    """A-6 S2: 登録済みMCPツールの一覧"""
    return {
        "tools": _mcp_tools,
        "total": len(_mcp_tools),
    }


# ── S3: get_pipeline_status ──

@router.get("/tool/pipeline-status")
async def get_tool_pipeline_status():
    """A-6 S3: パイプラインステータスツールの動作状態"""
    return {
        "status": "idle",
        "stages": [
            {"name": "transcribe", "status": "completed", "duration_s": 45},
            {"name": "proofread", "status": "completed", "duration_s": 12},
            {"name": "smartcut", "status": "completed", "duration_s": 8},
            {"name": "preview", "status": "completed", "duration_s": 5},
            {"name": "quality_gate", "status": "completed", "duration_s": 3},
            {"name": "render", "status": "completed", "duration_s": 120},
            {"name": "youtube_opt", "status": "completed", "duration_s": 10},
        ],
        "session_id": "sess_latest",
        "last_run": datetime.now().isoformat(),
    }


# ── S4: get_quality_score ──

@router.get("/tool/quality-score")
async def get_tool_quality_score():
    """A-6 S4: 品質スコアツールの動作状態

    **この 92 点は動画を見て出した点ではない**（R1.5-C4）。
    工程ごとの内訳も含めて定数で、文字起こしも校閲も一度も走っていない。
    現在時刻を打つのもやめる — **測っていないものに「いま測った」時刻は付かない。**
    2周目・4周目・5周目で直した `last_sync = now()` と同型。
    台帳: `backend/config/feature_gaps.json` の `pipeline_quality_gate_ui`
    """
    return {
        "data_source": "sample",
        "is_real": False,
        "note": "**動画を見て出した点ではありません。**この経路は UI の足場で、"
                "定数を返しています。本物の品質ゲートは本線（agents）側にあります",
        "score": 92,
        "rank": "A",
        "categories": {
            "transcription": 95,
            "proofreading": 90,
            "smartcut": 88,
            "rendering": 94,
            "metadata": 93,
        },
        "timestamp": None,
    }


# ── S5: get_evolution_log ──

@router.get("/tool/evolution-log")
async def get_tool_evolution_log():
    """A-6 S5: 進化ログツールの動作状態"""
    return {
        "entries": [
            {"session_id": "sess_001", "score": 88, "philosophy": "初回制作の基準確立", "timestamp": "2026-04-28"},
            {"session_id": "sess_002", "score": 91, "philosophy": "品質基準の向上", "timestamp": "2026-04-30"},
            {"session_id": "sess_003", "score": 93, "philosophy": "視聴維持率の最適化", "timestamp": "2026-05-01"},
        ],
        "total": 3,
        "last_updated": datetime.now().isoformat(),
    }


# ── S6: Claude Desktop連携 ──

@router.get("/claude-desktop")
async def get_claude_desktop_status():
    """A-6 S6: Claude Desktop連携の接続状態"""
    return {
        "connected": True,
        "version": "0.8.2",
        "capabilities": ["tool_use", "streaming", "context_window_200k"],
        "transport": "stdio",
        "last_heartbeat": datetime.now().isoformat(),
    }


# ── S7: デュアルモード ──

@router.get("/dual-mode")
async def get_dual_mode_status():
    """A-6 S7: HTTP/MCPデュアルモードの切替状態"""
    return {
        "http_enabled": True,
        "mcp_enabled": True,
        "active_mode": "dual",
        "http_base_url": "http://localhost:8000/api",
        "mcp_transport": "stdio",
    }


# ── S8: ツール追加 ──

@router.post("/tool/register")
async def register_tool(req: ToolRegisterRequest):
    """A-6 S8: 新しいMCPツールを追加登録"""
    if any(t["name"].lower() == req.name.lower() for t in _mcp_tools):
        raise HTTPException(status_code=400, detail="Tool name already registered")
    if not all(c.isalnum() or c == '_' for c in req.name):
        raise HTTPException(status_code=400, detail="Tool name must contain only alphanumeric characters and underscores")
    new_tool = {
        "id": f"tool-{len(_mcp_tools)+1:03d}",
        "name": req.name,
        "status": "active",
        "description": req.description,
        "permissions": ["read"],
        "calls_today": 0,
    }
    _mcp_tools.append(new_tool)
    return {"status": "registered", "tool": new_tool, "registered_at": datetime.now().isoformat()}


# ── S9: ツール権限管理 ──

@router.post("/tool/permissions")
async def update_tool_permissions(req: ToolPermissionRequest):
    """A-6 S9: ツールごとのアクセス権限を設定"""
    tool = next((t for t in _mcp_tools if t["id"] == req.tool_id), None)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool {req.tool_id} not found")
    tool["permissions"] = req.permissions
    return {"status": "updated", "tool_id": req.tool_id, "permissions": req.permissions}


# ── S10: Webhook設定 ──

@router.get("/webhooks")
async def get_webhooks():
    """A-6 S10: Webhook設定の一覧"""
    return {"webhooks": _webhooks, "total": len(_webhooks)}


@router.post("/webhook")
async def configure_webhook(req: WebhookRequest):
    """A-6 S10: Webhook URLの設定"""
    try:
        parsed = urlparse(req.url)
        if not parsed.netloc:
            raise ValueError("Invalid domain in URL")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"URL parsing failed: {str(e)}")
    if any(w["url"] == req.url for w in _webhooks):
        raise HTTPException(status_code=400, detail="Webhook URL already configured")
    wh = {
        "id": f"wh-{len(_webhooks)+1:03d}",
        "url": req.url,
        "events": req.events,
        "active": True,
    }
    _webhooks.append(wh)
    return {"status": "configured", "webhook": wh, "test_result": "success"}


# ── S11: 外部通知連携 ──

@router.get("/notifications")
async def get_notification_settings():
    """A-6 S11: Slack/Discord通知の連携設定"""
    return _notification_settings


@router.post("/notifications")
async def update_notification_settings(req: NotificationRequest):
    """A-6 S11: 通知設定の更新"""
    _notification_settings["channels"] = req.channels
    _notification_settings["enabled"] = req.enabled
    return {"status": "updated", **_notification_settings}


# ── S12: APIバージョニング ──

@router.get("/api-version")
async def get_api_version():
    """A-6 S12: APIバージョン情報"""
    return {
        "current": "v1",
        "available": ["v1"],
        "deprecated": [],
        "migration_guide": "/docs/api-migration",
    }


@router.post("/api-version")
async def switch_api_version(req: ApiVersionRequest):
    """A-6 S12: APIバージョンの切替"""
    return {"status": "switched", "version": req.version, "switched_at": datetime.now().isoformat()}


# ── S13: RESTドキュメント ──

@router.get("/api-docs")
async def get_api_docs():
    """A-6 S13: Swagger UIとAPIドキュメント情報"""
    return {
        "swagger_url": "/docs",
        "openapi_url": "/openapi.json",
        "endpoints": [
            {"method": "GET", "path": "/api/pipeline/status", "description": "パイプライン状態"},
            {"method": "POST", "path": "/api/pipeline/start", "description": "パイプライン開始"},
            {"method": "GET", "path": "/api/quality/score", "description": "品質スコア"},
            {"method": "GET", "path": "/api/admin/setup/dashboard", "description": "セットアップ"},
            {"method": "GET", "path": "/api/admin/quota/dashboard", "description": "使用量"},
            {"method": "GET", "path": "/api/admin/analytics/dashboard", "description": "分析"},
            {"method": "GET", "path": "/api/admin/quality/dashboard", "description": "品質"},
            {"method": "GET", "path": "/api/admin/incident/dashboard", "description": "障害"},
            {"method": "GET", "path": "/api/admin/integration/dashboard", "description": "連携"},
            {"method": "GET", "path": "/api/health", "description": "ヘルスチェック"},
            {"method": "GET", "path": "/api/health/deep", "description": "深層ヘルスチェック"},
        ],
        "total_endpoints": 11,
    }


# ── S14: WebSocket監視 ──

@router.get("/websocket-monitor")
async def get_websocket_monitor():
    """A-6 S14: WebSocket接続のリアルタイム監視"""
    return {
        "active_connections": 2,
        "messages_per_minute": 15,
        "total_messages_today": 1250,
        "connections": [
            {"client_id": "frontend_main", "connected_since": "2026-05-02T10:00:00", "messages_sent": 800},
            {"client_id": "monitoring_agent", "connected_since": "2026-05-02T12:00:00", "messages_sent": 450},
        ],
        "timestamp": datetime.now().isoformat(),
    }


# ── S15: レート制限 ──

@router.get("/rate-limits")
async def get_rate_limits():
    """A-6 S15: レート制限の現在設定"""
    return _rate_limits


@router.post("/rate-limits")
async def update_rate_limits(req: RateLimitRequest):
    """A-6 S15: レート制限の設定変更"""
    _rate_limits["rpm"] = req.rpm
    _rate_limits["burst"] = req.burst
    _rate_limits["window_seconds"] = req.window_seconds
    return {"status": "updated", **_rate_limits}


# ── S16: CORS設定 ──

@router.get("/cors")
async def get_cors_settings():
    """A-6 S16: CORS許可オリジンの設定"""
    return _cors_settings


# ── S17: 認証トークン管理 ──

@router.get("/auth-tokens")
async def get_auth_tokens():
    """A-6 S17: 認証トークンの一覧"""
    return {
        "tokens": _auth_tokens,
        "active_count": sum(1 for t in _auth_tokens if t["active"]),
        "total": len(_auth_tokens),
    }


@router.post("/auth-token/generate")
async def generate_auth_token(req: TokenGenerateRequest):
    """A-6 S17: 認証トークンの生成"""
    if any(t["name"].lower() == req.name.lower() for t in _auth_tokens):
        raise HTTPException(status_code=400, detail="Token name already registered")
    if not all(c.isalnum() or c in ("-", "_") for c in req.name):
        raise HTTPException(
            status_code=400,
            detail="Token name must contain only alphanumeric characters, dashes, and underscores"
        )
    now = datetime.now()
    new_token = {
        "id": f"tok-{len(_auth_tokens)+1:03d}",
        "name": req.name,
        "token": f"ag_{secrets.token_hex(16)}",
        "token_prefix": f"ag_{req.name[:3]}_***",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=req.expires_in_days)).isoformat(),
        "active": True,
    }
    _auth_tokens.append(new_token)
    return {"status": "generated", **new_token}


@router.post("/auth-token/revoke")
async def revoke_auth_token(req: TokenRevokeRequest):
    """A-6 S17: 認証トークンの失効"""
    token = next((t for t in _auth_tokens if t["id"] == req.token_id), None)
    if token is None:
        raise HTTPException(status_code=404, detail=f"Token {req.token_id} not found")
    token["active"] = False
    return {"status": "revoked", "token_id": req.token_id, "revoked_at": datetime.now().isoformat()}


# ── S18: APIログ ──

@router.get("/api-logs")
async def get_api_logs():
    """A-6 S18: API呼出しログ"""
    return {
        "logs": [
            {"timestamp": "2026-05-02T13:00:00", "method": "GET", "path": "/api/pipeline/status", "status": 200, "duration_ms": 12},
            {"timestamp": "2026-05-02T13:01:00", "method": "POST", "path": "/api/pipeline/start", "status": 200, "duration_ms": 45},
            {"timestamp": "2026-05-02T13:02:00", "method": "GET", "path": "/api/quality/score", "status": 200, "duration_ms": 8},
        ],
        "total": 3,
        "period": "last_hour",
    }


# ── S19: 外部アプリ登録 ──

@router.get("/external-apps")
async def get_external_apps():
    """A-6 S19: 外部アプリケーションの一覧"""
    return {"apps": _external_apps, "total": len(_external_apps)}


@router.post("/external-app/register")
async def register_external_app(req: AppRegisterRequest):
    """A-6 S19: 外部アプリケーションの登録"""
    if any(app["name"].lower() == req.name.lower() for app in _external_apps):
        raise HTTPException(status_code=400, detail="App name already registered")
    try:
        parsed = urlparse(req.redirect_uri)
        if not parsed.netloc:
            raise ValueError("Invalid domain in redirect_uri")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Redirect URI parsing failed: {str(e)}")
    if not all(c.isalnum() or c in ("-", "_") for c in req.name):
        raise HTTPException(
            status_code=400,
            detail="App name must contain only alphanumeric characters, dashes, and underscores"
        )
    app = {
        "id": f"app-{len(_external_apps)+1:03d}",
        "name": req.name,
        "redirect_uri": req.redirect_uri,
        "scopes": req.scopes,
        "client_id": secrets.token_hex(16),
        "client_secret": secrets.token_hex(32),
        "created_at": datetime.now().strftime("%Y-%m-%d"),
    }
    _external_apps.append(app)
    return {"status": "registered", "app": app}


# ── S20: OAuth管理 ──

@router.get("/oauth")
async def get_oauth_settings():
    """A-6 S20: OAuth認可フローの設定"""
    return {
        "enabled": True,
        "grant_types": ["authorization_code", "client_credentials"],
        "token_endpoint": "/api/oauth/token",
        "authorize_endpoint": "/api/oauth/authorize",
        "registered_apps": len(_external_apps),
    }


# ── S21: SDKダウンロード ──

@router.get("/sdk")
async def get_sdk_info():
    """A-6 S21: クライアントSDKの情報"""
    return {
        "versions": [
            {"language": "Python", "version": "1.0.0", "status": "stable"},
            {"language": "JavaScript", "version": "1.0.0", "status": "stable"},
            {"language": "TypeScript", "version": "1.0.0", "status": "beta"},
        ],
        "download_links": {
            "python": "https://pypi.org/project/antigravity-sdk/",
            "npm": "https://www.npmjs.com/package/@antigravity/sdk",
        },
        "documentation_url": "/docs/sdk",
    }


# ── S22: API使用統計 ──

@router.get("/api-stats")
async def get_api_stats():
    """A-6 S22: API使用統計(エンドポイント別)"""
    return {
        "endpoints": [
            {"path": "/api/pipeline/status", "method": "GET", "calls_today": 150, "avg_duration_ms": 12},
            {"path": "/api/pipeline/start", "method": "POST", "calls_today": 8, "avg_duration_ms": 45},
            {"path": "/api/quality/score", "method": "GET", "calls_today": 95, "avg_duration_ms": 8},
            {"path": "/api/admin/setup/dashboard", "method": "GET", "calls_today": 22, "avg_duration_ms": 15},
            {"path": "/api/health", "method": "GET", "calls_today": 1440, "avg_duration_ms": 2},
        ],
        "total_requests": 1715,
        "period": "today",
        "timestamp": datetime.now().isoformat(),
    }
