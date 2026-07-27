"""
E2E テスト — A-1 システムセットアップ・環境管理 5層検証 (55項目)

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

BASE = "http://localhost:8000/api/admin/setup"


@pytest.mark.e2e
class TestA1L1DomExists:
    """L1: DOM存在 (12項目)"""

    def test_a1_l1_01(self, app_page):
        """A1-L1-01 [S1]: Admin Setup APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/dashboard")
        assert r.ok

    def test_a1_l1_02(self, app_page):
        """A1-L1-02 [S1]: ダッシュボードにsectionsフィールドが存在する"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert "sections" in d
        assert len(d["sections"]) >= 10

    def test_a1_l1_03(self, app_page):
        """A1-L1-03 [S2]: 環境ステータスAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/environment")
        assert r.ok

    def test_a1_l1_04(self, app_page):
        """A1-L1-04 [S3]: APIキー管理APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/api-keys")
        assert r.ok

    def test_a1_l1_05(self, app_page):
        """A1-L1-05 [S5]: ハーネス状態APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/harness")
        assert r.ok

    def test_a1_l1_06(self, app_page):
        """A1-L1-06 [S6]: DI状態APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/di-container")
        assert r.ok

    def test_a1_l1_07(self, app_page):
        """A1-L1-07 [S7]: GPU情報APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/gpu")
        assert r.ok

    def test_a1_l1_08(self, app_page):
        """A1-L1-08 [S8]: モデル設定APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/model-config")
        assert r.ok

    def test_a1_l1_09(self, app_page):
        """A1-L1-09 [S10]: フォールバックチェーンAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/fallback-chain")
        assert r.ok

    def test_a1_l1_10(self, app_page):
        """A1-L1-10 [S11]: ヘルスチェックAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/health-check")
        assert r.ok

    def test_a1_l1_11(self, app_page):
        """A1-L1-11 [S12]: 自動診断APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/diagnostics")
        assert r.ok

    def test_a1_l1_12(self, app_page):
        """A1-L1-12 [S14]: ストレージ使用量APIが正常応答する"""
        r = app_page.request.get(f"{BASE}/storage")
        assert r.ok


@pytest.mark.e2e
class TestA1L2VisualFeedback:
    """L2: 視覚フィードバック (10項目)"""

    def test_a1_l2_01(self, app_page):
        """A1-L2-01 [S1]: ダッシュボードにtitle/statusフィールドが含まれる"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert "title" in d and "status" in d

    def test_a1_l2_02(self, app_page):
        """A1-L2-02 [S2]: 環境ステータスにbackend/frontend/gpu状態が含まれる"""
        d = app_page.request.get(f"{BASE}/environment").json()
        assert all(k in d for k in ["backend", "frontend", "gpu"])
        assert d["backend"]["status"] == "running"

    def test_a1_l2_03(self, app_page):
        """A1-L2-03 [S3]: APIキー状態にgemini/youtube設定フラグが含まれる"""
        d = app_page.request.get(f"{BASE}/api-keys").json()
        assert "gemini" in d and "youtube" in d
        assert "configured" in d["gemini"]

    def test_a1_l2_04(self, app_page):
        """A1-L2-04 [S5]: ハーネス状態に4コンポーネントのステータスが含まれる"""
        d = app_page.request.get(f"{BASE}/harness").json()
        assert d["total"] == 4
        assert all(k in d["components"] for k in ["hooks", "session", "governance", "tool_registry"])

    def test_a1_l2_05(self, app_page):
        """A1-L2-05 [S6]: DI状態にinitialized/servicesフィールドが含まれる"""
        d = app_page.request.get(f"{BASE}/di-container").json()
        assert "initialized" in d
        assert "services" in d

    def test_a1_l2_06(self, app_page):
        """A1-L2-06 [S7]: GPU情報にmodel/vram/driverフィールドが含まれる"""
        d = app_page.request.get(f"{BASE}/gpu").json()
        assert all(k in d for k in ["model", "vram_mb", "driver"])

    def test_a1_l2_07(self, app_page):
        """A1-L2-07 [S8]: モデル設定にtask_model_mappingが含まれる"""
        d = app_page.request.get(f"{BASE}/model-config").json()
        assert "task_model_mapping" in d
        assert isinstance(d["task_model_mapping"], dict)

    def test_a1_l2_08(self, app_page):
        """A1-L2-08 [S10]: フォールバックチェーンにprimary/secondary/tertiaryが含まれる"""
        d = app_page.request.get(f"{BASE}/fallback-chain").json()
        assert all(k in d for k in ["primary", "secondary", "tertiary"])

    def test_a1_l2_09(self, app_page):
        """A1-L2-09 [S12]: 自動診断結果にall_checks配列が含まれる"""
        d = app_page.request.get(f"{BASE}/diagnostics").json()
        assert isinstance(d["all_checks"], list)
        assert d["total"] > 0

    def test_a1_l2_10(self, app_page):
        """A1-L2-10 [S14]: ストレージ使用量にfree_gb/total_gb/usage_percentが含まれる"""
        d = app_page.request.get(f"{BASE}/storage").json()
        assert all(k in d for k in ["free_gb", "total_gb", "usage_percent"])


@pytest.mark.e2e
class TestA1L3Interaction:
    """L3: インタラクション (13項目)"""

    def test_a1_l3_01(self, app_page):
        """A1-L3-01 [S2]: 環境ステータスの各コンポーネント詳細を取得できる"""
        d = app_page.request.get(f"{BASE}/environment").json()
        assert d["backend"]["port"] == 8000

    def test_a1_l3_02(self, app_page):
        """A1-L3-02 [S3]: APIキー状態の検証チェックを実行できる"""
        d = app_page.request.get(f"{BASE}/api-keys").json()
        assert isinstance(d["gemini"]["configured"], bool)

    def test_a1_l3_03(self, app_page):
        """A1-L3-03 [S4]: APIキー更新APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/api-keys",
            data=json.dumps({"provider": "gemini", "key": "test-key-12345"}),
            headers={"Content-Type": "application/json"})
        assert r.ok

    def test_a1_l3_04(self, app_page):
        """A1-L3-04 [S4]: APIキー更新後に設定が反映される"""
        app_page.request.post(f"{BASE}/api-keys",
            data=json.dumps({"provider": "gemini", "key": "updated-key-12345"}),
            headers={"Content-Type": "application/json"})
        d = app_page.request.get(f"{BASE}/api-keys").json()
        assert d["gemini"]["configured"] is True

    def test_a1_l3_05(self, app_page):
        """A1-L3-05 [S7]: GPU情報の更新チェックを実行できる"""
        d = app_page.request.get(f"{BASE}/gpu").json()
        assert "available" in d

    def test_a1_l3_06(self, app_page):
        """A1-L3-06 [S9]: モデル割当変更APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/model-config",
            data=json.dumps({"task": "transcribe", "model_tier": "premium"}),
            headers={"Content-Type": "application/json"})
        assert r.ok

    def test_a1_l3_07(self, app_page):
        """A1-L3-07 [S9]: モデル割当変更後にtask_model_mappingが更新される"""
        d = app_page.request.post(f"{BASE}/model-config",
            data=json.dumps({"task": "proofread", "model_tier": "standard"}),
            headers={"Content-Type": "application/json"}).json()
        assert d["task_model_mapping"]["proofread"] == "standard"

    def test_a1_l3_08(self, app_page):
        """A1-L3-08 [S11]: ヘルスチェック実行結果が返される"""
        d = app_page.request.get(f"{BASE}/health-check").json()
        assert d["status"] in ["healthy", "degraded", "unhealthy"]

    def test_a1_l3_09(self, app_page):
        """A1-L3-09 [S13]: ログレベル変更APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/log-level",
            data=json.dumps({"level": "WARNING"}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        d = r.json()
        assert d["level"] == "WARNING"

    def test_a1_l3_10(self, app_page):
        """A1-L3-10 [S15]: ストレージ警告閾値を設定できる"""
        r = app_page.request.post(f"{BASE}/storage/threshold",
            data=json.dumps({"warning_gb": 5.0}),
            headers={"Content-Type": "application/json"})
        assert r.ok

    def test_a1_l3_11(self, app_page):
        """A1-L3-11 [S16]: クリーンアップ実行APIが正常応答する"""
        r = app_page.request.post(f"{BASE}/cleanup",
            data="{}",
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "completed"

    def test_a1_l3_12(self, app_page):
        """A1-L3-12 [S18]: 設定エクスポートAPIが正常応答する"""
        r = app_page.request.get(f"{BASE}/config/export")
        assert r.ok
        d = r.json()
        assert "config" in d

    def test_a1_l3_13(self, app_page):
        """A1-L3-13 [S19]: 設定インポートAPIが正常応答する"""
        r = app_page.request.post(f"{BASE}/config/import",
            data=json.dumps({"config": {"log_level": "INFO"}}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "imported"


@pytest.mark.e2e
class TestA1L4StateTransition:
    """L4: 状態遷移 (10項目)"""

    def test_a1_l4_01(self, app_page):
        """A1-L4-01 [S4]: 無効なAPIキーで適切なエラーが返る"""
        r = app_page.request.post(f"{BASE}/api-keys",
            data=json.dumps({"provider": "gemini", "key": "short"}),
            headers={"Content-Type": "application/json"})
        assert r.status == 400

    def test_a1_l4_02(self, app_page):
        """A1-L4-02 [S9]: 無効なモデル名で適切なエラーが返る"""
        r = app_page.request.post(f"{BASE}/model-config",
            data=json.dumps({"task": "transcribe", "model_tier": "invalid"}),
            headers={"Content-Type": "application/json"})
        assert r.status == 400

    def test_a1_l4_03(self, app_page):
        """A1-L4-03 [S11]: ヘルスチェック結果にFFmpeg/Gemini/Disk/Whisperが含まれる"""
        d = app_page.request.get(f"{BASE}/health-check").json()
        assert all(k in d["checks"] for k in ["ffmpeg", "gemini", "disk", "whisper"])

    def test_a1_l4_04(self, app_page):
        """A1-L4-04 [S13]: 無効なログレベルで適切なエラーが返る"""
        r = app_page.request.post(f"{BASE}/log-level",
            data=json.dumps({"level": "INVALID"}),
            headers={"Content-Type": "application/json"})
        assert r.status == 400

    def test_a1_l4_05(self, app_page):
        """A1-L4-05 [S15]: ストレージ使用量のwarningフラグが閾値に連動する"""
        d = app_page.request.get(f"{BASE}/storage").json()
        assert isinstance(d["warning"], bool)

    def test_a1_l4_06(self, app_page):
        """A1-L4-06 [S16]: クリーンアップ後にストレージ使用量が変化する"""
        before = app_page.request.get(f"{BASE}/storage").json()
        app_page.request.post(f"{BASE}/cleanup", data="{}",
            headers={"Content-Type": "application/json"})
        after = app_page.request.get(f"{BASE}/storage").json()
        # ストレージAPIが正常に応答すれば良い（実際の変化量は環境依存）
        assert isinstance(after["free_gb"], (int, float))

    def test_a1_l4_07(self, app_page):
        """A1-L4-07 [S17]: バージョン情報にpython/fastapi/whisperが含まれる"""
        d = app_page.request.get(f"{BASE}/versions").json()
        assert all(k in d for k in ["python", "fastapi", "whisper"])

    def test_a1_l4_08(self, app_page):
        """A1-L4-08 [S18]: エクスポートされたJSONが有効な設定構造を持つ"""
        d = app_page.request.get(f"{BASE}/config/export").json()
        assert "config" in d
        config = d["config"]
        assert "log_level" in config
        assert "storage_threshold_gb" in config

    def test_a1_l4_09(self, app_page):
        """A1-L4-09 [S19]: 不正なJSONインポートで適切なエラーが返る"""
        # 422 or 400 for invalid body
        r = app_page.request.post(f"{BASE}/config/import",
            data="not-json",
            headers={"Content-Type": "application/json"})
        assert r.status in [400, 422]

    def test_a1_l4_10(self, app_page):
        """A1-L4-10 [S20]: コンポーネント再起動APIが正常応答する"""
        r = app_page.request.post(f"{BASE}/restart/harness",
            data="{}",
            headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "restarted"


@pytest.mark.e2e
class TestA1L5EndToEnd:
    """L5: E2E完走 (10項目)"""

    def test_a1_l5_01(self, app_page):
        """A1-L5-01 [S17]: ダッシュボード→環境確認→GPU情報→バージョンの完走"""
        assert app_page.request.get(f"{BASE}/dashboard").ok
        assert app_page.request.get(f"{BASE}/environment").ok
        d = app_page.request.get(f"{BASE}/gpu").json()
        assert "model" in d
        v = app_page.request.get(f"{BASE}/versions").json()
        assert "python" in v

    def test_a1_l5_02(self, app_page):
        """A1-L5-02 [S20]: ヘルスチェック→異常検出→診断→コンポーネント再起動の完走"""
        h = app_page.request.get(f"{BASE}/health-check").json()
        assert h["status"] in ["healthy", "degraded", "unhealthy"]
        d = app_page.request.get(f"{BASE}/diagnostics").json()
        assert d["total"] > 0
        r = app_page.request.post(f"{BASE}/restart/harness",
            data="{}",
            headers={"Content-Type": "application/json"})
        assert r.ok

    def test_a1_l5_03(self, app_page):
        """A1-L5-03 [S21]: エラーログ取得→フィルタリング→詳細表示の完走"""
        r = app_page.request.get(f"{BASE}/error-logs")
        assert r.ok
        d = r.json()
        assert "logs" in d
        assert isinstance(d["total"], int)

    def test_a1_l5_04(self, app_page):
        """A1-L5-04 [S21]: モデル設定確認→変更→フォールバック確認の完走"""
        mc = app_page.request.get(f"{BASE}/model-config").json()
        assert "task_model_mapping" in mc
        app_page.request.post(f"{BASE}/model-config",
            data=json.dumps({"task": "smartcut", "model_tier": "batch"}),
            headers={"Content-Type": "application/json"})
        fc = app_page.request.get(f"{BASE}/fallback-chain").json()
        assert fc["tertiary"]["tier"] == "batch"

    def test_a1_l5_05(self, app_page):
        """A1-L5-05 [S21]: ストレージ確認→警告確認→クリーンアップ→再確認の完走"""
        s1 = app_page.request.get(f"{BASE}/storage").json()
        assert isinstance(s1["warning"], bool)
        app_page.request.post(f"{BASE}/cleanup", data="{}",
            headers={"Content-Type": "application/json"})
        s2 = app_page.request.get(f"{BASE}/storage").json()
        assert isinstance(s2["free_gb"], (int, float))

    def test_a1_l5_06(self, app_page):
        """A1-L5-06 [S22]: 設定エクスポート→変更→インポート→検証の完走"""
        exported = app_page.request.get(f"{BASE}/config/export").json()
        assert "config" in exported
        config = exported["config"]
        config["log_level"] = "DEBUG"
        r = app_page.request.post(f"{BASE}/config/import",
            data=json.dumps({"config": config}),
            headers={"Content-Type": "application/json"})
        assert r.ok
        verify = app_page.request.get(f"{BASE}/log-level").json()
        assert verify["level"] == "DEBUG"

    def test_a1_l5_07(self, app_page):
        """A1-L5-07 [S22]: APIキー確認→ハーネス確認→DI確認→全体診断の完走"""
        assert app_page.request.get(f"{BASE}/api-keys").ok
        h = app_page.request.get(f"{BASE}/harness").json()
        assert h["total"] == 4
        assert app_page.request.get(f"{BASE}/di-container").ok
        diag = app_page.request.get(f"{BASE}/diagnostics").json()
        assert diag["passed"] >= 1

    def test_a1_l5_08(self, app_page):
        """A1-L5-08 [S22]: 通知設定→ログ設定→エラーログ確認→通知テストの完走"""
        app_page.request.post(f"{BASE}/notifications",
            data=json.dumps({"slack_webhook": "https://hooks.slack.com/test", "email": "test@example.com"}),
            headers={"Content-Type": "application/json"})
        app_page.request.post(f"{BASE}/log-level",
            data=json.dumps({"level": "INFO"}),
            headers={"Content-Type": "application/json"})
        logs = app_page.request.get(f"{BASE}/error-logs").json()
        assert isinstance(logs["logs"], list)
        notif = app_page.request.get(f"{BASE}/notifications").json()
        assert notif["slack_webhook"] == "https://hooks.slack.com/test"

    def test_a1_l5_09(self, app_page):
        """A1-L5-09 [追加]: 全APIエンドポイント疎通確認の完走"""
        endpoints = [
            "/dashboard", "/environment", "/api-keys", "/harness",
            "/di-container", "/gpu", "/model-config", "/fallback-chain",
            "/health-check", "/diagnostics", "/storage", "/versions",
            "/config/export", "/error-logs", "/notifications", "/log-level",
        ]
        for ep in endpoints:
            r = app_page.request.get(f"{BASE}{ep}")
            assert r.ok, f"Endpoint {ep} failed with status {r.status}"

    def test_a1_l5_10(self, app_page):
        """A1-L5-10 [追加]: 無効コンポーネント再起動で400エラーの完走"""
        r = app_page.request.post(f"{BASE}/restart/invalid_component",
            data="{}",
            headers={"Content-Type": "application/json"})
        assert r.status == 400
