import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from routers.admin_integration_router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)

def test_get_dashboard():
    response = client.get("/api/admin/integration/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "MCP外部連携・ツール統合"
    assert "tools" in data["sections"]

def test_get_tools():
    response = client.get("/api/admin/integration/tools")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert len(data["tools"]) >= 3

def test_get_pipeline_status():
    response = client.get("/api/admin/integration/tool/pipeline-status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "idle"

def test_get_quality_score():
    response = client.get("/api/admin/integration/tool/quality-score")
    assert response.status_code == 200
    assert response.json()["score"] == 92

def test_get_evolution_log():
    response = client.get("/api/admin/integration/tool/evolution-log")
    assert response.status_code == 200
    assert response.json()["total"] == 3

def test_get_claude_desktop():
    response = client.get("/api/admin/integration/claude-desktop")
    assert response.status_code == 200
    assert response.json()["connected"] is True

def test_get_dual_mode():
    response = client.get("/api/admin/integration/dual-mode")
    assert response.status_code == 200
    assert response.json()["active_mode"] == "dual"

def test_register_tool_edge_cases():
    response = client.post("/api/admin/integration/tool/register", json={"name": "test_tool", "description": "desc"})
    assert response.status_code == 200
    assert response.json()["status"] == "registered"

    response = client.post("/api/admin/integration/tool/register", json={"name": "test_tool"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Tool name already registered"

    response = client.post("/api/admin/integration/tool/register", json={"name": ""})
    assert response.status_code == 422

def test_update_tool_permissions_edge_cases():
    response = client.post("/api/admin/integration/tool/permissions", json={"tool_id": "tool-001", "permissions": ["write"]})
    assert response.status_code == 200
    assert response.json()["status"] == "updated"

    response = client.post("/api/admin/integration/tool/permissions", json={"tool_id": "nonexistent", "permissions": ["read"]})
    assert response.status_code == 404

    response = client.post("/api/admin/integration/tool/permissions", json={"tool_id": "tool-001", "permissions": ["invalid_perm"]})
    assert response.status_code == 422

def test_webhook_edge_cases():
    response = client.post("/api/admin/integration/webhook", json={"url": "http://example.com/callback", "events": ["pipeline_complete"]})
    assert response.status_code == 200
    assert response.json()["status"] == "configured"

    response = client.post("/api/admin/integration/webhook", json={"url": "ftp://example.com", "events": ["pipeline_complete"]})
    assert response.status_code == 422

    response = client.post("/api/admin/integration/webhook", json={"url": "http://example.com", "events": ["invalid_event"]})
    assert response.status_code == 422

def test_get_webhooks():
    response = client.get("/api/admin/integration/webhooks")
    assert response.status_code == 200
    assert "webhooks" in response.json()

def test_notification_settings_edge_cases():
    response = client.post("/api/admin/integration/notifications", json={"channels": ["slack"], "enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    response = client.get("/api/admin/integration/notifications")
    assert response.status_code == 200
    assert response.json()["enabled"] is False

def test_api_version_edge_cases():
    response = client.get("/api/admin/integration/api-version")
    assert response.status_code == 200

    response = client.post("/api/admin/integration/api-version", json={"version": "v2"})
    assert response.status_code == 200
    assert response.json()["version"] == "v2"

def test_api_docs():
    response = client.get("/api/admin/integration/api-docs")
    assert response.status_code == 200

def test_websocket_monitor():
    response = client.get("/api/admin/integration/websocket-monitor")
    assert response.status_code == 200

def test_rate_limits_edge_cases():
    response = client.post("/api/admin/integration/rate-limits", json={"rpm": 100, "burst": 20, "window_seconds": 30})
    assert response.status_code == 200
    assert response.json()["rpm"] == 100

    response = client.post("/api/admin/integration/rate-limits", json={"rpm": 0, "burst": 10, "window_seconds": 60})
    assert response.status_code == 422

    response = client.post("/api/admin/integration/rate-limits", json={"rpm": 60, "burst": -5, "window_seconds": 60})
    assert response.status_code == 422

    response = client.get("/api/admin/integration/rate-limits")
    assert response.status_code == 200
    assert response.json()["rpm"] == 100

def test_cors_settings():
    response = client.get("/api/admin/integration/cors")
    assert response.status_code == 200

def test_auth_tokens_edge_cases():
    response = client.post("/api/admin/integration/auth-token/generate", json={"name": "prod_key", "expires_in_days": 90})
    assert response.status_code == 200
    token_id = response.json()["id"]

    response = client.post("/api/admin/integration/auth-token/revoke", json={"token_id": token_id})
    assert response.status_code == 200

    response = client.post("/api/admin/integration/auth-token/generate", json={"name": "test", "expires_in_days": 366})
    assert response.status_code == 422

    response = client.post("/api/admin/integration/auth-token/generate", json={"name": "test", "expires_in_days": 0})
    assert response.status_code == 422

    response = client.post("/api/admin/integration/auth-token/revoke", json={"token_id": "tok-nonexistent"})
    assert response.status_code == 404

    response = client.get("/api/admin/integration/auth-tokens")
    assert response.status_code == 200

def test_api_logs():
    response = client.get("/api/admin/integration/api-logs")
    assert response.status_code == 200

def test_external_apps_edge_cases():
    response = client.post("/api/admin/integration/external-app/register", json={"name": "AppB", "redirect_uri": "https://example.com/oauth", "scopes": ["read"]})
    assert response.status_code == 200
    assert response.json()["status"] == "registered"

    response = client.post("/api/admin/integration/external-app/register", json={"name": "AppB", "redirect_uri": "https://example.com/oauth"})
    assert response.status_code == 400

    response = client.post("/api/admin/integration/external-app/register", json={"name": "AppC", "redirect_uri": "ftp://invalid-url"})
    assert response.status_code == 422

    response = client.post("/api/admin/integration/external-app/register", json={"name": "AppC", "redirect_uri": "https://example.com", "scopes": ["invalid_scope"]})
    assert response.status_code == 422

    response = client.get("/api/admin/integration/external-apps")
    assert response.status_code == 200

def test_oauth_settings():
    response = client.get("/api/admin/integration/oauth")
    assert response.status_code == 200

def test_sdk_info():
    response = client.get("/api/admin/integration/sdk")
    assert response.status_code == 200

def test_api_stats():
    response = client.get("/api/admin/integration/api-stats")
    assert response.status_code == 200


def test_get_dashboard_partial_status():
    # 接続ステータスが "partial" になる分岐をテストするため、_mcp_tools の一部を inactive に変更
    from routers.admin_integration_router import _mcp_tools
    
    original_status = [t["status"] for t in _mcp_tools]
    try:
        # 1つのツールを inactive に変更
        _mcp_tools[0]["status"] = "inactive"
        response = client.get("/api/admin/integration/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "partial"
    finally:
        # 元の状態に戻す
        for i, status in enumerate(original_status):
            _mcp_tools[i]["status"] = status

def test_update_tool_permissions_multiple_permissions():
    response = client.post(
        "/api/admin/integration/tool/permissions",
        json={"tool_id": "tool-001", "permissions": ["read", "write"]}
    )
    assert response.status_code == 200
    assert response.json()["permissions"] == ["read", "write"]

def test_webhook_multiple_events_and_secret():
    response = client.post(
        "/api/admin/integration/webhook",
        json={
            "url": "https://example.com/callback",
            "events": ["pipeline_complete", "quality_alert"],
            "secret": "my-secret-key"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "configured"
    assert data["webhook"]["url"] == "https://example.com/callback"
    assert set(data["webhook"]["events"]) == {"pipeline_complete", "quality_alert"}

def test_register_external_app_multiple_scopes():
    # 重複エラーを避けるためにユニークな名前を使用
    response = client.post(
        "/api/admin/integration/external-app/register",
        json={
            "name": "AppUniqueName",
            "redirect_uri": "https://example.com/oauth-callback",
            "scopes": ["read", "write"]
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "registered"
    assert data["app"]["name"] == "AppUniqueName"
    assert set(data["app"]["scopes"]) == {"read", "write"}

def test_auth_token_boundary_days():
    # 期限の境界値 (1日)
    response1 = client.post(
        "/api/admin/integration/auth-token/generate",
        json={"name": "min_expires", "expires_in_days": 1}
    )
    assert response1.status_code == 200
    assert response1.json()["name"] == "min_expires"

    # 期限の境界値 (365日)
    response2 = client.post(
        "/api/admin/integration/auth-token/generate",
        json={"name": "max_expires", "expires_in_days": 365}
    )
    assert response2.status_code == 200
    assert response2.json()["name"] == "max_expires"

    # nameを省略した場合（デフォルト値の検証）
    response3 = client.post(
        "/api/admin/integration/auth-token/generate",
        json={"expires_in_days": 30}
    )
    assert response3.status_code == 200
    assert response3.json()["name"] == "default"

def test_auth_token_revoke_state_change():
    # トークンを生成
    gen_response = client.post(
        "/api/admin/integration/auth-token/generate",
        json={"name": "to_revoke", "expires_in_days": 30}
    )
    token_id = gen_response.json()["id"]

    # 失効を実行
    revoke_response = client.post(
        "/api/admin/integration/auth-token/revoke",
        json={"token_id": token_id}
    )
    assert revoke_response.status_code == 200

    # トークン一覧を取得し、該当トークンが非アクティブになっていることを確認
    list_response = client.get("/api/admin/integration/auth-tokens")
    assert list_response.status_code == 200
    tokens = list_response.json()["tokens"]
    target_token = next((t for t in tokens if t["id"] == token_id), None)
    assert target_token is not None
    assert target_token["active"] is False
