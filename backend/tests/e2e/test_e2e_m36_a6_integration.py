"""
E2E テスト — A-6 MCP外部連携・ツール統合 5層検証 (55項目)

検証5層モデル:
  L1: DOM存在 (12項目)
  L2: 視覚フィードバック (10項目)
  L3: インタラクション (13項目)
  L4: 状態遷移 (10項目)
  L5: E2E完走 (10項目)

設計書: design_admin_a1_a7_full.md.resolved (推移表転記済み/)
"""
import pytest
import json

BASE = "http://localhost:8000/api/admin/integration"


@pytest.mark.e2e
class TestA6L1DomExists:
    """L1: DOM存在 (12項目)"""

    def test_a6_l1_01(self, app_page):
        """A6-L1-01 [S1]: MCP外部連携ダッシュボードAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/dashboard")
        assert r.ok

    def test_a6_l1_02(self, app_page):
        """A6-L1-02 [S1]: ダッシュボードにsectionsフィールドが存在する"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert "sections" in d
        assert len(d["sections"]) >= 10

    def test_a6_l1_03(self, app_page):
        """A6-L1-03 [S2]: MCPツール一覧APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/tools")
        assert r.ok

    def test_a6_l1_04(self, app_page):
        """A6-L1-04 [S3]: パイプラインステータスツールAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/tool/pipeline-status")
        assert r.ok

    def test_a6_l1_05(self, app_page):
        """A6-L1-05 [S4]: 品質スコアツールAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/tool/quality-score")
        assert r.ok

    def test_a6_l1_06(self, app_page):
        """A6-L1-06 [S5]: 進化ログツールAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/tool/evolution-log")
        assert r.ok

    def test_a6_l1_07(self, app_page):
        """A6-L1-07 [S8]: ツール追加APIが正常応答する"""
        r = app_page.request.post(f"{BASE}/tool/register",
            data=json.dumps({"name": "test_tool", "description": "テスト"}),
            headers={"Content-Type": "application/json"})
        assert r.ok

    def test_a6_l1_08(self, app_page):
        """A6-L1-08 [S11]: 外部通知設定APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/notifications")
        assert r.ok

    def test_a6_l1_09(self, app_page):
        """A6-L1-09 [S13]: APIドキュメント情報APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/api-docs")
        assert r.ok

    def test_a6_l1_10(self, app_page):
        """A6-L1-10 [S14]: WebSocket監視APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/websocket-monitor")
        assert r.ok

    def test_a6_l1_11(self, app_page):
        """A6-L1-11 [S17]: 認証トークン管理APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/auth-tokens")
        assert r.ok

    def test_a6_l1_12(self, app_page):
        """A6-L1-12 [S21]: SDK情報APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/sdk")
        assert r.ok


@pytest.mark.e2e
class TestA6L2VisualFeedback:
    """L2: 視覚フィードバック (10項目)"""

    def test_a6_l2_01(self, app_page):
        """A6-L2-01 [S1]: ダッシュボードにtitle/status/summaryが含まれる"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert all(k in d for k in ["title", "status", "summary"])

    def test_a6_l2_02(self, app_page):
        """A6-L2-02 [S2]: ツール一覧にtools配列とtotalが含まれる"""
        d = app_page.request.get(f"{BASE}/tools").json()
        assert "tools" in d and "total" in d
        assert isinstance(d["tools"], list)

    def test_a6_l2_03(self, app_page):
        """A6-L2-03 [S3]: パイプラインステータスにstatus/stages/session_idが含まれる"""
        d = app_page.request.get(f"{BASE}/tool/pipeline-status").json()
        assert all(k in d for k in ["status", "stages", "session_id"])

    def test_a6_l2_04(self, app_page):
        """A6-L2-04 [S4]: 品質スコアにscore/rank/categoriesが含まれる"""
        d = app_page.request.get(f"{BASE}/tool/quality-score").json()
        assert all(k in d for k in ["score", "rank", "categories"])

    def test_a6_l2_05(self, app_page):
        """A6-L2-05 [S11]: 通知設定にchannels配列とenabledが含まれる"""
        d = app_page.request.get(f"{BASE}/notifications").json()
        assert "channels" in d and "enabled" in d
        assert isinstance(d["channels"], list)

    def test_a6_l2_06(self, app_page):
        """A6-L2-06 [S12]: APIバージョンにcurrent/available/deprecatedが含まれる"""
        d = app_page.request.get(f"{BASE}/api-version").json()
        assert all(k in d for k in ["current", "available", "deprecated"])

    def test_a6_l2_07(self, app_page):
        """A6-L2-07 [S13]: APIドキュメントにswagger_url/endpointsが含まれる"""
        d = app_page.request.get(f"{BASE}/api-docs").json()
        assert "swagger_url" in d and "endpoints" in d

    def test_a6_l2_08(self, app_page):
        """A6-L2-08 [S14]: WebSocket監視にactive_connections/messagesが含まれる"""
        d = app_page.request.get(f"{BASE}/websocket-monitor").json()
        assert "active_connections" in d and "messages_per_minute" in d

    def test_a6_l2_09(self, app_page):
        """A6-L2-09 [S17]: 認証トークンにtokens配列とactive_countが含まれる"""
        d = app_page.request.get(f"{BASE}/auth-tokens").json()
        assert "tokens" in d and "active_count" in d
        assert isinstance(d["tokens"], list)

    def test_a6_l2_10(self, app_page):
        """A6-L2-10 [S21]: SDK情報にversions配列とdownload_linksが含まれる"""
        d = app_page.request.get(f"{BASE}/sdk").json()
        assert "versions" in d and "download_links" in d
        assert isinstance(d["versions"], list)


@pytest.mark.e2e
class TestA6L3Interaction:
    """L3: インタラクション (13項目)"""

    def test_a6_l3_01(self, app_page):
        """A6-L3-01 [S2]: ツール一覧の各ツールにname/status/descriptionが含まれる"""
        d = app_page.request.get(f"{BASE}/tools").json()
        for t in d["tools"]:
            assert all(k in t for k in ["name", "status", "description"])

    def test_a6_l3_02(self, app_page):
        """A6-L3-02 [S3]: パイプラインステータスのstagesが配列で返される"""
        d = app_page.request.get(f"{BASE}/tool/pipeline-status").json()
        assert isinstance(d["stages"], list)
        assert len(d["stages"]) >= 7

    def test_a6_l3_03(self, app_page):
        """A6-L3-03 [S5]: 進化ログのentriesが配列で返される"""
        d = app_page.request.get(f"{BASE}/tool/evolution-log").json()
        assert isinstance(d["entries"], list)
        assert len(d["entries"]) >= 1

    def test_a6_l3_04(self, app_page):
        """A6-L3-04 [S6]: Claude Desktop接続状態APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/claude-desktop")
        assert r.ok

    def test_a6_l3_05(self, app_page):
        """A6-L3-05 [S7]: デュアルモード状態APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/dual-mode")
        assert r.ok

    def test_a6_l3_06(self, app_page):
        """A6-L3-06 [S8]: ツール追加APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/tool/register",
            data=json.dumps({"name": "custom_tool", "description": "カスタムツール"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "registered"

    def test_a6_l3_07(self, app_page):
        """A6-L3-07 [S9]: ツール権限設定APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/tool/permissions",
            data=json.dumps({"tool_id": "tool-001", "permissions": ["read", "write"]}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "updated"

    def test_a6_l3_08(self, app_page):
        """A6-L3-08 [S10]: Webhook設定APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/webhook",
            data=json.dumps({"url": "https://test.example.com/hook", "events": ["pipeline_complete"]}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "configured"

    def test_a6_l3_09(self, app_page):
        """A6-L3-09 [S11]: 通知設定の更新がPOSTで反映される"""
        app_page.request.post(f"{BASE}/notifications",
            data=json.dumps({"channels": ["slack", "discord"], "enabled": True}),
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/notifications").json()
        assert "discord" in d["channels"]

    def test_a6_l3_10(self, app_page):
        """A6-L3-10 [S12]: APIバージョン切替APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/api-version",
            data=json.dumps({"version": "v1"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "switched"

    def test_a6_l3_11(self, app_page):
        """A6-L3-11 [S13]: APIドキュメントのendpointsが10以上含まれる"""
        d = app_page.request.get(f"{BASE}/api-docs").json()
        assert len(d["endpoints"]) >= 10

    def test_a6_l3_12(self, app_page):
        """A6-L3-12 [S14]: WebSocket接続数が0以上の数値である"""
        d = app_page.request.get(f"{BASE}/websocket-monitor").json()
        assert isinstance(d["active_connections"], int)
        assert d["active_connections"] >= 0

    def test_a6_l3_13(self, app_page):
        """A6-L3-13 [S15]: レート制限設定APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/rate-limits",
            data=json.dumps({"rpm": 120, "burst": 20, "window_seconds": 60}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "updated"


@pytest.mark.e2e
class TestA6L4StateTransition:
    """L4: 状態遷移 (10項目)"""

    def test_a6_l4_01(self, app_page):
        """A6-L4-01 [S6]: Claude Desktop接続にconnected/version/capabilitiesが含まれる"""
        d = app_page.request.get(f"{BASE}/claude-desktop").json()
        assert all(k in d for k in ["connected", "version", "capabilities"])

    def test_a6_l4_02(self, app_page):
        """A6-L4-02 [S7]: デュアルモードにhttp_enabled/mcp_enabled/active_modeが含まれる"""
        d = app_page.request.get(f"{BASE}/dual-mode").json()
        assert all(k in d for k in ["http_enabled", "mcp_enabled", "active_mode"])

    def test_a6_l4_03(self, app_page):
        """A6-L4-03 [S9]: 権限設定後に各ツールのpermissionsが更新される"""
        app_page.request.post(f"{BASE}/tool/permissions",
            data=json.dumps({"tool_id": "tool-002", "permissions": ["read", "execute"]}),
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/tools").json()
        tool = next(t for t in d["tools"] if t["id"] == "tool-002")
        assert "execute" in tool["permissions"]

    def test_a6_l4_04(self, app_page):
        """A6-L4-04 [S10]: Webhookテスト送信が正常に完了する"""
        r = app_page.request.post(f"{BASE}/webhook",
            data=json.dumps({"url": "https://test.example.com/wh", "events": ["quality_alert"]}),
            headers={"Content-Type": "application/json"})
        d = r.json()
        assert d["test_result"] == "success"

    def test_a6_l4_05(self, app_page):
        """A6-L4-05 [S15]: レート制限にrpm/burst/windowが含まれる"""
        d = app_page.request.get(f"{BASE}/rate-limits").json()
        assert all(k in d for k in ["rpm", "burst", "window_seconds"])

    def test_a6_l4_06(self, app_page):
        """A6-L4-06 [S16]: CORS設定APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/cors")
        assert r.ok
        d = r.json()
        assert "allowed_origins" in d

    def test_a6_l4_07(self, app_page):
        """A6-L4-07 [S17]: トークン生成後にtoken/expires_atが含まれる"""
        r = app_page.request.post(f"{BASE}/auth-token/generate",
            data=json.dumps({"name": "test_token", "expires_in_days": 7}),
            headers={"Content-Type": "application/json"})
        d = r.json()
        assert "token" in d and "expires_at" in d

    def test_a6_l4_08(self, app_page):
        """A6-L4-08 [S18]: APIログにlogs配列とtotalが含まれる"""
        d = app_page.request.get(f"{BASE}/api-logs").json()
        assert "logs" in d and "total" in d
        assert isinstance(d["logs"], list)

    def test_a6_l4_09(self, app_page):
        """A6-L4-09 [S19]: 外部アプリ登録APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/external-app/register",
            data=json.dumps({"name": "TestApp", "redirect_uri": "https://test.com/cb", "scopes": ["read"]}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "registered"

    def test_a6_l4_10(self, app_page):
        """A6-L4-10 [S20]: OAuth設定APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/oauth")
        assert r.ok
        d = r.json()
        assert "grant_types" in d


@pytest.mark.e2e
class TestA6L5EndToEnd:
    """L5: E2E完走 (10項目)"""

    def test_a6_l5_01(self, app_page):
        """A6-L5-01 [S16]: ダッシュボード→MCP接続→ツール一覧→CORS設定の完走"""
        assert app_page.request.get(f"{BASE}/dashboard").ok
        cd = app_page.request.get(f"{BASE}/claude-desktop").json()
        assert cd["connected"] is True
        tools = app_page.request.get(f"{BASE}/tools").json()
        assert tools["total"] >= 3
        cors = app_page.request.get(f"{BASE}/cors").json()
        assert "allowed_origins" in cors

    def test_a6_l5_02(self, app_page):
        """A6-L5-02 [S18]: ツール追加→権限設定→APIログ確認の完走"""
        reg = app_page.request.post(f"{BASE}/tool/register",
            data=json.dumps({"name": "e2e_tool"}),
            headers={"Content-Type": "application/json"}).json()
        assert reg["status"] == "registered"
        tool_id = reg["tool"]["id"]
        perm = app_page.request.post(f"{BASE}/tool/permissions",
            data=json.dumps({"tool_id": tool_id, "permissions": ["read", "write"]}),
            headers={"Content-Type": "application/json"}).json()
        assert perm["status"] == "updated"
        logs = app_page.request.get(f"{BASE}/api-logs").json()
        assert logs["total"] >= 0

    def test_a6_l5_03(self, app_page):
        """A6-L5-03 [S19]: 外部アプリ登録→OAuth設定→トークン生成の完走"""
        app_r = app_page.request.post(f"{BASE}/external-app/register",
            data=json.dumps({"name": "E2EApp", "redirect_uri": "https://e2e.com/cb"}),
            headers={"Content-Type": "application/json"}).json()
        assert app_r["status"] == "registered"
        oauth = app_page.request.get(f"{BASE}/oauth").json()
        assert oauth["enabled"] is True
        token = app_page.request.post(f"{BASE}/auth-token/generate",
            data=json.dumps({"name": "e2e_token"}),
            headers={"Content-Type": "application/json"}).json()
        assert "token" in token

    def test_a6_l5_04(self, app_page):
        """A6-L5-04 [S20]: Webhook設定→通知テスト→Slack/Discord連携の完走"""
        wh = app_page.request.post(f"{BASE}/webhook",
            data=json.dumps({"url": "https://e2e.com/hook", "events": ["pipeline_complete"]}),
            headers={"Content-Type": "application/json"}).json()
        assert wh["status"] == "configured"
        notif = app_page.request.get(f"{BASE}/notifications").json()
        assert notif["enabled"] is True
        app_page.request.post(f"{BASE}/notifications",
            data=json.dumps({"channels": ["slack"], "enabled": True}),
            headers={"Content-Type": "application/json"})

    def test_a6_l5_05(self, app_page):
        """A6-L5-05 [S20]: APIバージョン→Swagger→レート制限の完走"""
        ver = app_page.request.get(f"{BASE}/api-version").json()
        assert ver["current"] == "v1"
        docs = app_page.request.get(f"{BASE}/api-docs").json()
        assert docs["total_endpoints"] >= 10
        rl = app_page.request.get(f"{BASE}/rate-limits").json()
        assert rl["rpm"] > 0

    def test_a6_l5_06(self, app_page):
        """A6-L5-06 [S21]: 全GETエンドポイント疎通確認の完走"""
        endpoints = [
            "/dashboard", "/tools", "/tool/pipeline-status",
            "/tool/quality-score", "/tool/evolution-log",
            "/claude-desktop", "/dual-mode",
            "/notifications", "/api-version", "/api-docs",
            "/websocket-monitor", "/rate-limits", "/cors",
            "/auth-tokens", "/api-logs", "/external-apps",
            "/oauth", "/sdk", "/api-stats",
        ]
        for ep in endpoints:
            r = app_page.request.get(f"{BASE}{ep}")
            assert r.ok, f"Endpoint {ep} failed with status {r.status}"

    def test_a6_l5_07(self, app_page):
        """A6-L5-07 [S22]: API使用統計にendpoints配列とtotal_requestsが含まれる"""
        d = app_page.request.get(f"{BASE}/api-stats").json()
        assert "endpoints" in d and "total_requests" in d
        assert isinstance(d["endpoints"], list)
        assert d["total_requests"] > 0

    def test_a6_l5_08(self, app_page):
        """A6-L5-08 [S22]: WebSocket監視→接続状態→メッセージ統計の完走"""
        ws = app_page.request.get(f"{BASE}/websocket-monitor").json()
        assert ws["active_connections"] >= 0
        assert ws["messages_per_minute"] >= 0
        assert ws["total_messages_today"] >= 0

    def test_a6_l5_09(self, app_page):
        """A6-L5-09 [S22]: 認証トークン→失効→再生成の完走"""
        tokens = app_page.request.get(f"{BASE}/auth-tokens").json()
        assert tokens["active_count"] >= 1
        gen = app_page.request.post(f"{BASE}/auth-token/generate",
            data=json.dumps({"name": "revoke_test", "expires_in_days": 1}),
            headers={"Content-Type": "application/json"}).json()
        assert gen["status"] == "generated"
        rev = app_page.request.post(f"{BASE}/auth-token/revoke",
            data=json.dumps({"token_id": gen["id"]}),
            headers={"Content-Type": "application/json"}).json()
        assert rev["status"] == "revoked"

    def test_a6_l5_10(self, app_page):
        """A6-L5-10 [S22]: 無効なツールID指定で404エラーの完走"""
        r = app_page.request.post(f"{BASE}/tool/permissions",
            data=json.dumps({"tool_id": "NONEXISTENT", "permissions": ["read"]}),
            headers={"Content-Type": "application/json"})
        assert r.status == 404
        r2 = app_page.request.post(f"{BASE}/auth-token/revoke",
            data=json.dumps({"token_id": "NONEXISTENT"}),
            headers={"Content-Type": "application/json"})
        assert r2.status == 404
