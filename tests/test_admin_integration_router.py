import sys
import importlib.util
from pathlib import Path

# カレントディレクトリ(ワークスペースルート)を取得
cwd = Path.cwd()
workspace_root = str(cwd)
workspace_backend = str(cwd / "backend")

# sys.path に追加 (親指示に沿うよう workspace_root を追加)
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)

# 対象の admin_integration_router.py の絶対パスを指定して直接ロード
router_file_path = Path(__file__).parent.parent / "backend" / "routers" / "admin_integration_router.py"

spec = importlib.util.spec_from_file_location("backend.routers.admin_integration_router", str(router_file_path))
air = importlib.util.module_from_spec(spec)
sys.modules["backend.routers.admin_integration_router"] = air
sys.modules["routers.admin_integration_router"] = air
spec.loader.exec_module(air)

router = air.router

import pytest
import copy
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_state():
    orig_mcp = copy.deepcopy(air._mcp_tools)
    orig_notif = copy.deepcopy(air._notification_settings)
    orig_tokens = copy.deepcopy(air._auth_tokens)
    orig_apps = copy.deepcopy(air._external_apps)
    orig_whs = copy.deepcopy(air._webhooks)
    orig_limits = copy.deepcopy(air._rate_limits)
    orig_cors = copy.deepcopy(air._cors_settings)
    yield
    air._mcp_tools = orig_mcp
    air._notification_settings = orig_notif
    air._auth_tokens = orig_tokens
    air._external_apps = orig_apps
    air._webhooks = orig_whs
    air._rate_limits = orig_limits
    air._cors_settings = orig_cors

def test_dashboard():
    response = client.get("/api/admin/integration/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "MCP外部連携・ツール統合"
    assert data["status"] == "connected"
    assert "summary" in data

def test_dashboard_partial_status():
    air._mcp_tools[0]["status"] = "inactive"
    response = client.get("/api/admin/integration/dashboard")
    assert response.status_code == 200
    assert response.json()["status"] == "partial"

def test_get_tools():
    response = client.get("/api/admin/integration/tools")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert len(data["tools"]) == 3

def test_pipeline_status():
    response = client.get("/api/admin/integration/tool/pipeline-status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "idle"

def test_quality_score():
    response = client.get("/api/admin/integration/tool/quality-score")
    assert response.status_code == 200
    data = response.json()
    assert data["score"] == 92

def test_evolution_log():
    response = client.get("/api/admin/integration/tool/evolution-log")
    assert response.status_code == 200
    data = response.json()
    assert "entries" in data

def test_claude_desktop():
    response = client.get("/api/admin/integration/claude-desktop")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is True

def test_dual_mode():
    response = client.get("/api/admin/integration/dual-mode")
    assert response.status_code == 200
    data = response.json()
    assert data["http_enabled"] is True

def test_register_tool_success():
    payload = {"name": "test_tool", "description": "test_desc", "endpoint": "http://localhost/test"}
    response = client.post("/api/admin/integration/tool/register", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "registered"
    assert data["tool"]["name"] == "test_tool"
    assert data["tool"]["id"] == "tool-004"

def test_register_tool_duplicate():
    payload = {"name": "get_pipeline_status", "description": "duplicate"}
    response = client.post("/api/admin/integration/tool/register", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Tool name already registered"

def test_update_permissions_success():
    payload = {"tool_id": "tool-001", "permissions": ["read", "write"]}
    response = client.post("/api/admin/integration/tool/permissions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"
    assert data["permissions"] == ["read", "write"]

def test_update_permissions_not_found():
    payload = {"tool_id": "tool-999", "permissions": ["read"]}
    response = client.post("/api/admin/integration/tool/permissions", json=payload)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]

def test_get_webhooks():
    response = client.get("/api/admin/integration/webhooks")
    assert response.status_code == 200
    assert "webhooks" in response.json()

def test_configure_webhook_success():
    payload = {"url": "https://test.com/webhook", "events": ["pipeline_complete"]}
    response = client.post("/api/admin/integration/webhook", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "configured"
    assert data["webhook"]["url"] == "https://test.com/webhook"

def test_get_notifications():
    response = client.get("/api/admin/integration/notifications")
    assert response.status_code == 200
    assert "slack" in response.json()["channels"]

def test_update_notifications():
    payload = {"channels": ["discord"], "enabled": False}
    response = client.post("/api/admin/integration/notifications", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"
    assert data["channels"] == ["discord"]
    assert data["enabled"] is False

def test_get_api_version():
    response = client.get("/api/admin/integration/api-version")
    assert response.status_code == 200
    assert response.json()["current"] == "v1"

def test_switch_api_version():
    payload = {"version": "v2"}
    response = client.post("/api/admin/integration/api-version", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "switched"
    assert response.json()["version"] == "v2"

def test_get_api_docs():
    response = client.get("/api/admin/integration/api-docs")
    assert response.status_code == 200
    assert "swagger_url" in response.json()

def test_websocket_monitor():
    response = client.get("/api/admin/integration/websocket-monitor")
    assert response.status_code == 200
    assert "active_connections" in response.json()

def test_get_rate_limits():
    response = client.get("/api/admin/integration/rate-limits")
    assert response.status_code == 200
    assert "rpm" in response.json()

def test_update_rate_limits():
    payload = {"rpm": 120, "burst": 20, "window_seconds": 30}
    response = client.post("/api/admin/integration/rate-limits", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"
    assert data["rpm"] == 120
    assert data["burst"] == 20
    assert data["window_seconds"] == 30

def test_get_cors():
    response = client.get("/api/admin/integration/cors")
    assert response.status_code == 200
    assert "allowed_origins" in response.json()

def test_get_auth_tokens():
    response = client.get("/api/admin/integration/auth-tokens")
    assert response.status_code == 200
    assert "tokens" in response.json()

def test_generate_auth_token():
    payload = {"name": "test_tok", "expires_in_days": 10}
    response = client.post("/api/admin/integration/auth-token/generate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "generated"
    assert data["name"] == "test_tok"
    assert "token" in data

def test_revoke_auth_token_success():
    response = client.post("/api/admin/integration/auth-token/revoke", json={"token_id": "tok-001"})
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"

def test_revoke_auth_token_not_found():
    response = client.post("/api/admin/integration/auth-token/revoke", json={"token_id": "tok-999"})
    assert response.status_code == 404

def test_get_api_logs():
    response = client.get("/api/admin/integration/api-logs")
    assert response.status_code == 200
    assert "logs" in response.json()

def test_get_external_apps():
    response = client.get("/api/admin/integration/external-apps")
    assert response.status_code == 200
    assert "apps" in response.json()

def test_register_external_app_success():
    payload = {"name": "NewApp", "redirect_uri": "https://app.com/callback", "scopes": ["read"]}
    response = client.post("/api/admin/integration/external-app/register", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "registered"
    assert data["app"]["name"] == "NewApp"

def test_register_external_app_duplicate():
    payload = {"name": "VideoBot", "redirect_uri": "https://app.com/callback"}
    response = client.post("/api/admin/integration/external-app/register", json=payload)
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]

def test_oauth():
    response = client.get("/api/admin/integration/oauth")
    assert response.status_code == 200
    assert response.json()["enabled"] is True

def test_sdk():
    response = client.get("/api/admin/integration/sdk")
    assert response.status_code == 200
    assert "versions" in response.json()

def test_api_stats():
    response = client.get("/api/admin/integration/api-stats")
    assert response.status_code == 200
    assert "endpoints" in response.json()

# Pydantic Validation tests
def test_tool_permission_request_invalid_val():
    with pytest.raises(ValidationError) as exc_info:
        air.ToolPermissionRequest(tool_id="tool-001", permissions=["invalid_perm"])
    assert "Invalid permission" in str(exc_info.value)

def test_webhook_request_invalid_url():
    with pytest.raises(ValidationError) as exc_info:
        air.WebhookRequest(url="ftp://invalid.url")
    assert "URL must start with http:// or https://" in str(exc_info.value)

def test_webhook_request_invalid_event():
    with pytest.raises(ValidationError) as exc_info:
        air.WebhookRequest(url="https://valid.url", events=["invalid_event"])
    assert "Invalid event" in str(exc_info.value)

def test_app_register_request_invalid_uri():
    with pytest.raises(ValidationError) as exc_info:
        air.AppRegisterRequest(name="app", redirect_uri="ftp://invalid.uri")
    assert "redirect_uri must start with http:// or https://" in str(exc_info.value)

def test_app_register_request_invalid_scope():
    with pytest.raises(ValidationError) as exc_info:
        air.AppRegisterRequest(name="app", redirect_uri="https://valid.uri", scopes=["invalid_scope"])
    assert "Invalid scope" in str(exc_info.value)


# 新規追加：強化されたエラーハンドリングの検証テスト
def test_register_tool_invalid_name():
    payload = {"name": "invalid-tool!", "description": "invalid name with special character"}
    response = client.post("/api/admin/integration/tool/register", json=payload)
    assert response.status_code == 400
    assert "alphanumeric characters and underscores" in response.json()["detail"]

def test_update_permissions_empty():
    payload = {"tool_id": "tool-001", "permissions": []}
    # Note: Pydantic field_validator validate_permissions handles validation if there are values,
    # and now we enforce min_length=1 in the schema.
    response = client.post("/api/admin/integration/tool/permissions", json=payload)
    assert response.status_code == 422

def test_configure_webhook_invalid_domain():
    payload = {"url": "https:///path/without/domain", "events": ["pipeline_complete"]}
    response = client.post("/api/admin/integration/webhook", json=payload)
    assert response.status_code == 400
    assert "URL parsing failed" in response.json()["detail"]

def test_generate_auth_token_duplicate():
    # 'development' is pre-registered in _auth_tokens
    payload = {"name": "development", "expires_in_days": 10}
    response = client.post("/api/admin/integration/auth-token/generate", json=payload)
    assert response.status_code == 400
    assert "Token name already registered" in response.json()["detail"]

def test_generate_auth_token_invalid_name():
    payload = {"name": "tok_invalid!", "expires_in_days": 10}
    response = client.post("/api/admin/integration/auth-token/generate", json=payload)
    assert response.status_code == 400
    assert "Token name must contain only alphanumeric characters, dashes, and underscores" in response.json()["detail"]

def test_register_external_app_invalid_uri():
    payload = {"name": "NewApp2", "redirect_uri": "https:///callback/without/domain"}
    response = client.post("/api/admin/integration/external-app/register", json=payload)
    assert response.status_code == 400
    assert "Redirect URI parsing failed" in response.json()["detail"]

def test_register_external_app_invalid_name():
    payload = {"name": "InvalidAppName!", "redirect_uri": "https://example.com/callback"}
    response = client.post("/api/admin/integration/external-app/register", json=payload)
    assert response.status_code == 400
    assert "App name must contain only alphanumeric characters, dashes, and underscores" in response.json()["detail"]

def test_configure_webhook_duplicate():
    payload = {"url": "https://test.com/webhook", "events": ["pipeline_complete"]}
    response1 = client.post("/api/admin/integration/webhook", json=payload)
    assert response1.status_code == 200
    response2 = client.post("/api/admin/integration/webhook", json=payload)
    assert response2.status_code == 400
    assert "Webhook URL already configured" in response2.json()["detail"]

def test_register_tool_duplicate_case_insensitive():
    payload1 = {"name": "Test_Tool_Case", "description": "desc"}
    response1 = client.post("/api/admin/integration/tool/register", json=payload1)
    assert response1.status_code == 200
    payload2 = {"name": "test_tool_case", "description": "desc duplicate"}
    response2 = client.post("/api/admin/integration/tool/register", json=payload2)
    assert response2.status_code == 400
    assert "Tool name already registered" in response2.json()["detail"]

def test_generate_auth_token_duplicate_case_insensitive():
    payload1 = {"name": "Token_Case", "expires_in_days": 10}
    response1 = client.post("/api/admin/integration/auth-token/generate", json=payload1)
    assert response1.status_code == 200
    payload2 = {"name": "token_case", "expires_in_days": 10}
    response2 = client.post("/api/admin/integration/auth-token/generate", json=payload2)
    assert response2.status_code == 400
    assert "Token name already registered" in response2.json()["detail"]

def test_register_external_app_duplicate_case_insensitive():
    payload1 = {"name": "App_Case", "redirect_uri": "https://app.com/callback"}
    response1 = client.post("/api/admin/integration/external-app/register", json=payload1)
    assert response1.status_code == 200
    payload2 = {"name": "app_case", "redirect_uri": "https://app.com/callback"}
    response2 = client.post("/api/admin/integration/external-app/register", json=payload2)
    assert response2.status_code == 400
    assert "App name already registered" in response2.json()["detail"]
