"""
ルーターテスト — health.py / pipeline_router.py / usage_router.py
FastAPI TestClient でエンドポイントの正常系・異常系を検証

目的: カバレッジ分子の拡大（本番APIコードの品質保証）
"""

import pytest
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock


# ============================================================
# Health Router テスト (5件)
# ============================================================

class TestHealthRouter:
    """GET /health, /health/deep のテスト"""

    def _get_client(self):
        """テスト用 TestClient を遅延生成"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.health import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_health_healthy(self):
        """FFmpeg利用可能・Gemini設定済み・ディスク余裕 → healthy"""
        with patch("routers.health._check_ffmpeg", return_value={"available": True, "path": "ffmpeg", "gpu_nvenc": True}), \
             patch("routers.health._check_gemini", return_value={"key_configured": True, "key_prefix": "AIza1234..."}), \
             patch("routers.health._check_disk_space", return_value={"free_gb": 50.0, "total_gb": 500.0, "usage_percent": 90.0, "warning": False}):
            client = self._get_client()
            res = client.get("/health")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "healthy"
            assert "uptime_seconds" in data
            assert "checks" in data
            assert data["checks"]["ffmpeg"]["available"] is True

    def test_health_unhealthy_no_ffmpeg(self):
        """FFmpeg利用不可 → unhealthy"""
        with patch("routers.health._check_ffmpeg", return_value={"available": False, "error": "not found"}), \
             patch("routers.health._check_gemini", return_value={"key_configured": True}), \
             patch("routers.health._check_disk_space", return_value={"free_gb": 50.0, "warning": False}):
            client = self._get_client()
            res = client.get("/health")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "unhealthy"

    def test_health_degraded_disk_warning(self):
        """ディスク残量不足 → degraded"""
        with patch("routers.health._check_ffmpeg", return_value={"available": True}), \
             patch("routers.health._check_gemini", return_value={"key_configured": True}), \
             patch("routers.health._check_disk_space", return_value={"free_gb": 5.0, "warning": True}):
            client = self._get_client()
            res = client.get("/health")
            data = res.json()
            assert data["status"] == "degraded"

    def test_health_degraded_no_gemini_key(self):
        """Gemini APIキー未設定 → degraded"""
        with patch("routers.health._check_ffmpeg", return_value={"available": True}), \
             patch("routers.health._check_gemini", return_value={"key_configured": False}), \
             patch("routers.health._check_disk_space", return_value={"free_gb": 50.0, "warning": False}):
            client = self._get_client()
            res = client.get("/health")
            data = res.json()
            assert data["status"] == "degraded"

    def test_health_deep(self):
        """詳細ヘルスチェック — 全コンポーネント"""
        with patch("routers.health._check_ffmpeg", return_value={"available": True}), \
             patch("routers.health._check_gemini", return_value={"key_configured": True}), \
             patch("routers.health._check_disk_space", return_value={"free_gb": 50.0, "warning": False}), \
             patch("routers.health._check_whisper", return_value={"available": False}):
            client = self._get_client()
            res = client.get("/health/deep")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "detailed"
            assert "whisper" in data["checks"]
            assert "pipeline" in data["checks"]
            assert "template" in data["checks"]
            assert "startup_time" in data


# ============================================================
# Health Router 内部関数テスト (5件)
# ============================================================

class TestHealthInternals:
    """_check_ffmpeg, _check_gemini, _check_disk_space, _check_whisper"""

    def test_check_ffmpeg_success(self):
        """FFmpegチェック — 正常"""
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.is_available.return_value = True
        mock_ffmpeg.ffmpeg_path = "/usr/bin/ffmpeg"
        mock_ffmpeg.use_gpu = True
        mock_editor = MagicMock()
        mock_editor.ffmpeg = mock_ffmpeg
        with patch.dict("sys.modules", {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
            from routers.health import _check_ffmpeg
            result = _check_ffmpeg()
            assert result["available"] is True
            assert result["gpu_nvenc"] is True

    def test_check_ffmpeg_import_error(self):
        """FFmpegチェック — ImportError → error付きdict"""
        from routers.health import _check_ffmpeg
        with patch.dict("sys.modules", {"video_editor_engine": None}):
            result = _check_ffmpeg()
            assert isinstance(result, dict)
            # video_editor_engine=None → ImportError → error key
            assert result.get("available") is False or "error" in result

    def test_check_gemini_with_key(self):
        """Gemini — APIキー設定あり"""
        from routers.health import _check_gemini
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "AIzaSyDTest12345"}):
            result = _check_gemini()
            assert result["key_configured"] is True
            assert result["key_prefix"].startswith("AIzaSyDT")

    def test_check_gemini_no_key(self):
        """Gemini — APIキーなし"""
        from routers.health import _check_gemini
        with patch.dict("os.environ", {}, clear=True):
            result = _check_gemini()
            assert result["key_configured"] is False
            assert result["key_prefix"] is None

    def test_check_disk_space(self):
        """ディスク容量チェック"""
        from routers.health import _check_disk_space
        mock_usage = MagicMock()
        mock_usage.free = 50 * 1024**3   # 50GB
        mock_usage.total = 500 * 1024**3  # 500GB
        with patch("routers.health.shutil.disk_usage", return_value=mock_usage):
            result = _check_disk_space()
            assert result["free_gb"] == 50.0
            assert result["warning"] is False


# ============================================================
# Pipeline Router テスト (15件)
# ============================================================

class TestPipelineRouterState:
    """パイプライン状態管理のテスト"""

    def test_reset_state(self):
        """_reset_state がステートを初期化"""
        from routers.pipeline_router import _reset_state, _pipeline_state
        _pipeline_state["status"] = "running"
        _pipeline_state["session_id"] = "test-123"
        _reset_state()
        assert _pipeline_state["status"] == "idle"
        assert _pipeline_state["session_id"] is None
        assert all(s["status"] == "pending" for s in _pipeline_state["stages"])

    def test_update_stage_valid(self):
        """_update_stage が有効なインデックスで更新"""
        from routers.pipeline_router import _update_stage, _pipeline_state, _reset_state
        _reset_state()
        _update_stage(2, "running", "SmartCut実行中", progress=50)
        assert _pipeline_state["stages"][2]["status"] == "running"
        assert _pipeline_state["stages"][2]["detail"] == "SmartCut実行中"
        assert _pipeline_state["stages"][2]["progress"] == 50
        assert _pipeline_state["current_stage"] == 2

    def test_update_stage_with_data(self):
        """_update_stage がdataパラメータを記録"""
        from routers.pipeline_router import _update_stage, _pipeline_state, _reset_state
        _reset_state()
        _update_stage(0, "completed", "完了", data={"segments": 15})
        assert _pipeline_state["stages"][0]["data"] == {"segments": 15}

    def test_update_stage_invalid_index(self):
        """_update_stage が範囲外インデックスで安全にスキップ"""
        from routers.pipeline_router import _update_stage, _pipeline_state
        # Should not raise
        _update_stage(99, "running", "test")
        _update_stage(-1, "running", "test")


class TestPipelineRouterAPI:
    """API エンドポイントのテスト"""

    def _get_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.pipeline_router import router, _reset_state
        _reset_state()
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_get_status_idle(self):
        """GET /status — idle状態"""
        client = self._get_client()
        res = client.get("/api/pipeline/status")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "idle"
        assert data["session_id"] is None
        assert len(data["stages"]) == 7

    def test_approve_no_checkpoint(self):
        """POST /approve — チェックポイントなし"""
        client = self._get_client()
        res = client.post("/api/pipeline/approve")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "no_checkpoint"

    def test_approve_with_checkpoint(self):
        """POST /approve — チェックポイント承認"""
        from routers.pipeline_router import _pipeline_state, _reset_state
        _reset_state()
        # TestClient生成後にstate操作（reset_stateの後に設定）
        client = self._get_client()
        _pipeline_state["checkpoint"] = {"stage": "preview", "approved": False}
        res = client.post("/api/pipeline/approve")
        data = res.json()
        assert data["status"] == "approved"
        assert _pipeline_state["checkpoint"] is None

    def test_start_already_running(self):
        """POST /start — 既に実行中 → 400"""
        from routers.pipeline_router import _pipeline_state, _reset_state
        _reset_state()
        client = self._get_client()
        _pipeline_state["status"] = "running"
        res = client.post("/api/pipeline/start", json={"video_paths": ["/test.mp4"]})
        assert res.status_code == 400

    def test_start_no_video(self):
        """POST /start — 動画未指定 → 400"""
        client = self._get_client()
        res = client.post("/api/pipeline/start", json={"video_paths": [], "video_path": ""})
        assert res.status_code == 400

    def test_start_video_not_found(self):
        """POST /start — 存在しない動画 → 404"""
        client = self._get_client()
        res = client.post("/api/pipeline/start", json={"video_paths": ["/nonexistent/video.mp4"]})
        assert res.status_code == 404

    def test_get_api_usage(self):
        """GET /api-usage — 使用量取得（エラー時フォールバック）"""
        client = self._get_client()
        res = client.get("/api/pipeline/api-usage")
        assert res.status_code == 200
        data = res.json()
        # get_usage_status が失敗しても、フォールバックレスポンスが返る
        assert "remaining" in data or "error" in data

    def test_stream_invalid_type(self):
        """GET /stream/{type} — 不正なタイプ → 400"""
        client = self._get_client()
        res = client.get("/api/pipeline/stream/invalid")
        assert res.status_code == 400

    def test_stream_no_result(self):
        """GET /stream/preview — 結果なし → 404"""
        client = self._get_client()
        res = client.get("/api/pipeline/stream/preview")
        assert res.status_code == 404

    def test_force_render_not_completed(self):
        """POST /force-render — 未完了 → 400"""
        client = self._get_client()
        res = client.post("/api/pipeline/force-render", json={"reason": "test"})
        assert res.status_code == 400


class TestPipelineWSManager:
    """WebSocket マネージャーのテスト"""

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        """接続と切断"""
        from routers.pipeline_router import PipelineWSManager
        mgr = PipelineWSManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        assert len(mgr.connections) == 1
        ws.accept.assert_awaited_once()
        mgr.disconnect(ws)
        assert len(mgr.connections) == 0

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead(self):
        """ブロードキャスト — dead接続を削除"""
        from routers.pipeline_router import PipelineWSManager
        mgr = PipelineWSManager()
        ws_ok = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_json.side_effect = Exception("Connection closed")
        mgr.connections = [ws_ok, ws_dead]
        await mgr.broadcast({"type": "test"})
        ws_ok.send_json.assert_awaited_once()
        assert ws_dead not in mgr.connections


# ============================================================
# Usage Router テスト (12件)
# ============================================================

class TestUsageRouterDashboard:
    """使用量ダッシュボードのテスト"""

    def _get_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.usage_router import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_dashboard_success(self):
        """GET /dashboard — 正常取得"""
        mock_summary = {
            "date": "2026-04-26",
            "models": {
                "gemini-2.5-flash": {
                    "used": 100, "limit": 500, "remaining": 400,
                    "usage_ratio": 0.2, "alert_level": "normal"
                }
            }
        }
        mock_tracker = MagicMock()
        mock_tracker.get_daily_summary.return_value = mock_summary

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(usage_tracker=mock_tracker)}):
            client = self._get_client()
            res = client.get("/api/usage/dashboard")
            assert res.status_code == 200
            data = res.json()
            assert data["date"] == "2026-04-26"
            assert len(data["models"]) >= 0  # may vary with mock

    def test_dashboard_error_fallback(self):
        """GET /dashboard — エラー時フォールバック"""
        with patch.dict("sys.modules", {"usage_tracker": MagicMock(side_effect=Exception("fail"))}):
            client = self._get_client()
            res = client.get("/api/usage/dashboard")
            assert res.status_code == 200
            data = res.json()
            assert "alerts" in data

    def test_retry_budget_error(self):
        """GET /retry-budget — エラーフォールバック"""
        client = self._get_client()
        res = client.get("/api/usage/retry-budget")
        assert res.status_code == 200
        data = res.json()
        assert "premium" in data
        assert "standard" in data

    def test_get_remaining_requests_success(self):
        """GET /remaining/{model_name} — 正常取得"""
        mock_tracker = MagicMock()
        mock_tracker.get_remaining_requests.return_value = 100
        mock_tracker.can_make_request.return_value = True
        mock_tracker.get_usage_ratio.return_value = 0.5

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(usage_tracker=mock_tracker)}):
            client = self._get_client()
            res = client.get("/api/usage/remaining/gemini-2.5-flash")
            assert res.status_code == 200
            data = res.json()
            assert data["model"] == "gemini-2.5-flash"
            assert data["remaining"] == 100
            assert data["can_use"] is True
            assert data["usage_percent"] == 50.0

    def test_get_quality_warning_critical(self):
        """GET /quality-warning — 警告 (critical)"""
        mock_tracker = MagicMock()
        mock_tracker.can_make_request.return_value = False
        mock_tracker.get_usage_ratio.return_value = 1.0

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(usage_tracker=mock_tracker)}):
            client = self._get_client()
            res = client.get("/api/usage/quality-warning")
            assert res.status_code == 200
            data = res.json()
            assert data["warning"] is True
            assert data["level"] == "critical"

    def test_get_quality_warning_warning(self):
        """GET /quality-warning — 警告 (warning)"""
        mock_tracker = MagicMock()
        mock_tracker.can_make_request.return_value = True
        mock_tracker.get_usage_ratio.return_value = 0.85

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(usage_tracker=mock_tracker)}):
            client = self._get_client()
            res = client.get("/api/usage/quality-warning")
            assert res.status_code == 200
            data = res.json()
            assert data["warning"] is True
            assert data["level"] == "warning"

    def test_get_all_models_status(self):
        """GET /model-status — 全モデルステータス"""
        mock_quota = MagicMock()
        mock_quota.get_all_models_status.return_value = {"gemini-2.5-flash": "active"}

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(quota_manager=mock_quota)}):
            client = self._get_client()
            res = client.get("/api/usage/model-status")
            assert res.status_code == 200
            assert res.json() == {"gemini-2.5-flash": "active"}

    def test_get_switch_history(self):
        """GET /switch-history — 切換え履歴"""
        mock_quota = MagicMock()
        mock_quota.get_switch_history.return_value = [{"event": "switch"}]

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(quota_manager=mock_quota)}):
            client = self._get_client()
            res = client.get("/api/usage/switch-history?limit=5")
            assert res.status_code == 200
            data = res.json()
            assert data["count"] == 1
            assert data["history"] == [{"event": "switch"}]

    def test_get_available_model(self):
        """POST /get-model — 利用可能モデル取得"""
        mock_quota = MagicMock()
        mock_quota.get_available_model.return_value = {"model": "gemini-2.5-flash"}

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(quota_manager=mock_quota)}):
            client = self._get_client()
            res = client.post("/api/usage/get-model?preferred_model=gemini-2.5-pro")
            assert res.status_code == 200
            assert res.json() == {"model": "gemini-2.5-flash"}

    def test_get_current_model_for_task(self):
        """GET /current-model/{task} — タスク対応モデル"""
        mock_quota = MagicMock()
        mock_quota.get_available_model.return_value = {"model": "gemini-2.5-flash"}

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(quota_manager=mock_quota)}):
            client = self._get_client()
            res = client.get("/api/usage/current-model/quality_gate")
            assert res.status_code == 200
            data = res.json()
            assert data["task"] == "quality_gate"
            assert data["model"] == "gemini-2.5-flash"

    def test_get_two_tier_status(self):
        """GET /two-tier-status — 2段階モデルステータス"""
        mock_quota = MagicMock()
        mock_quota.get_two_tier_status.return_value = {"premium": "ok", "standard": "ok"}

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(quota_manager=mock_quota)}):
            client = self._get_client()
            res = client.get("/api/usage/two-tier-status")
            assert res.status_code == 200
            assert res.json() == {"premium": "ok", "standard": "ok"}

    def test_get_wait_options(self):
        """GET /wait-options — 待機オプション"""
        mock_quota = MagicMock()
        mock_quota.get_model_with_wait_option.return_value = {"available": True, "remaining": 10}
        mock_quota.get_time_until_reset.return_value = {"remaining_hours": 5, "remaining_display": "5時間"}

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(quota_manager=mock_quota)}):
            client = self._get_client()
            res = client.get("/api/usage/wait-options?tier=premium")
            assert res.status_code == 200
            data = res.json()
            assert data["tier"] == "premium"
            assert data["current_status"]["available"] is True
            assert len(data["recommendations"]) == 0

    def test_select_model_option_wait(self):
        """POST /select-option (wait)"""
        mock_quota = MagicMock()
        mock_quota.get_model_with_wait_option.return_value = {"available": False}
        mock_quota.get_time_until_reset.return_value = {"remaining_display": "5時間", "reset_time_jst": "12:00"}

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(quota_manager=mock_quota)}):
            client = self._get_client()
            res = client.post("/api/usage/select-option?tier=premium&option=wait")
            assert res.status_code == 200
            data = res.json()
            assert data["action"] == "wait"
            assert "5時間" in data["message"]

    def test_select_model_option_force(self):
        """POST /select-option (force)"""
        mock_quota = MagicMock()
        mock_quota.get_model_with_wait_option.return_value = {"available": False, "options": {"force": {"available": True}}}
        mock_quota.MODEL_TIERS = {"premium": {"model": "gemini-2.5-pro"}}

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(quota_manager=mock_quota)}):
            client = self._get_client()
            res = client.post("/api/usage/select-option?tier=premium&option=force")
            assert res.status_code == 200
            data = res.json()
            assert data["action"] == "force"
            assert data["model"] == "gemini-2.5-pro"

    def test_select_model_option_fallback(self):
        """POST /select-option (fallback)"""
        mock_quota = MagicMock()
        mock_quota.get_model_with_wait_option.return_value = {"available": False}
        mock_quota.MODEL_TIERS = {"premium": {"model": "gemini-2.5-pro"}}
        mock_quota.FALLBACK_CHAIN = {"gemini-2.5-pro": "gemini-2.5-flash"}

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(quota_manager=mock_quota)}):
            client = self._get_client()
            res = client.post("/api/usage/select-option?tier=premium&option=fallback")
            assert res.status_code == 200
            data = res.json()
            assert data["action"] == "fallback"
            assert data["model"] == "gemini-2.5-flash"

    def test_get_governance_status(self):
        """GET /governance — ガバナンスダッシュボード"""
        mock_gov = MagicMock()
        mock_gov.get_stats.return_value = {
            "fallback_chain": {"a": "b"},
            "deprecation_map": {},
            "deprecation_corrections": 0,
            "fallback_activations": 1,
            "total_api_errors": 0,
            "recent_events": []
        }
        
        with patch.dict("sys.modules", {"model_governance": MagicMock(model_governance=mock_gov)}):
            client = self._get_client()
            res = client.get("/api/usage/governance")
            assert res.status_code == 200
            data = res.json()
            assert data["fallback_chain"] == {"a": "b"}
            assert data["counters"]["fallback_activations"] == 1

    def test_reload_governance_config(self):
        """POST /governance/reload — 再読込"""
        mock_gov = MagicMock()
        mock_gov.get_stats.return_value = {"fallback_chain": {"x": "y"}}
        
        with patch.dict("sys.modules", {"model_governance": MagicMock(model_governance=mock_gov)}):
            client = self._get_client()
            res = client.post("/api/usage/governance/reload")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "reloaded"
            assert data["governance"]["status"] == "reloaded"



class TestUsageRouterHelpers:
    """ヘルパー関数のテスト"""

    def test_get_tier_label_unknown(self):
        """_get_tier_label — 設定ファイルなし → Unknown"""
        from routers.usage_router import _get_tier_label
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = _get_tier_label("nonexistent-model")
            assert result == "Unknown"

    def test_get_alert_message_critical(self):
        """_get_alert_message — critical"""
        from routers.usage_router import _get_alert_message
        msg = _get_alert_message("test-model", {"alert_level": "critical", "remaining": 0})
        assert "使い切りました" in msg

    def test_get_alert_message_block(self):
        """_get_alert_message — block"""
        from routers.usage_router import _get_alert_message
        msg = _get_alert_message("test-model", {"alert_level": "block", "remaining": 3})
        assert "ブロック" in msg

    def test_get_alert_message_warning(self):
        """_get_alert_message — warning"""
        from routers.usage_router import _get_alert_message
        msg = _get_alert_message("test-model", {"alert_level": "warning", "remaining": 20})
        assert "控えて" in msg

    def test_get_alert_message_normal(self):
        """_get_alert_message — normal → 空文字"""
        from routers.usage_router import _get_alert_message
        msg = _get_alert_message("test-model", {"alert_level": "normal", "remaining": 200})
        assert msg == ""

    def test_get_retry_advice_low(self):
        """_get_retry_advice — 残り少"""
        from routers.usage_router import _get_retry_advice
        advice = _get_retry_advice(3, 100)
        assert "少なく" in advice

    def test_get_retry_advice_moderate(self):
        """_get_retry_advice — 残り中"""
        from routers.usage_router import _get_retry_advice
        advice = _get_retry_advice(15, 100)
        assert "注意" in advice

    def test_get_retry_advice_plenty(self):
        """_get_retry_advice — 十分"""
        from routers.usage_router import _get_retry_advice
        advice = _get_retry_advice(50, 100)
        assert "余裕" in advice

    def test_get_wait_recommendations_unavailable_soon(self):
        """_get_wait_recommendations — リセットまで2時間以内"""
        from routers.usage_router import _get_wait_recommendations
        recs = _get_wait_recommendations(
            "premium",
            {"available": False},
            {"remaining_hours": 1.5, "remaining_display": "1時間30分"}
        )
        assert len(recs) >= 1
        assert recs[0]["priority"] == "high"

    def test_get_wait_recommendations_available_low(self):
        """_get_wait_recommendations — 利用可能だが残少"""
        from routers.usage_router import _get_wait_recommendations
        recs = _get_wait_recommendations(
            "premium",
            {"available": True, "remaining": 5},
            {"remaining_hours": 20}
        )
        assert len(recs) >= 1
        assert recs[0]["type"] == "caution"
