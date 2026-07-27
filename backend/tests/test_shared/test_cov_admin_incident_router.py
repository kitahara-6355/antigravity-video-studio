"""
Milestone 22.6 Task B — admin_incident_router.py カバレッジ 100% 達成テスト
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.admin_incident_router import (
    router,
    _incidents,
    _alerts,
    _worker_status,
    _pipeline_failures,
    _self_healing_log,
    _patterns,
)

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    
    # 元の状態を退避
    orig_incidents = list(_incidents)
    orig_alerts = list(_alerts)
    orig_workers = list(_worker_status)
    
    # テスト用のダミーデータ設定
    _incidents.clear()
    _incidents.extend([
        {"id": "INC-001", "type": "pipeline_failure", "severity": "critical", "status": "open",
         "title": "TranscribeWorker Whisperモデルロード失敗",
         "worker": "TranscribeWorker", "error": "CUDA out of memory",
         "started_at": "2026-05-01T08:00:00", "resolved_at": None,
         "resolution": None},
        {"id": "INC-002", "type": "quota_breach", "severity": "high", "status": "resolved",
         "title": "Gemini API日次クォータ超過",
         "worker": "ProofreadWorker", "error": "429 Rate Limited",
         "started_at": "2026-05-01T14:00:00", "resolved_at": "2026-05-01T14:30:00",
         "resolution": "Standard→Batchモデル自動降格"},
    ])
    
    _alerts.clear()
    _alerts.extend([
        {"id": 1, "type": "quota_warning", "level": "WARNING", "message": "Gemini API使用量が80%超過", "threshold": 80, "created_at": "2026-05-02T10:00:00", "acknowledged": False},
        {"id": 2, "type": "pipeline_failure", "level": "CRITICAL", "message": "TranscribeWorker タイムアウト", "threshold": None, "created_at": "2026-05-02T11:30:00", "acknowledged": True},
    ])
    
    yield TestClient(app, raise_server_exceptions=False)
    
    # 状態の復元
    _incidents.clear()
    _incidents.extend(orig_incidents)
    _alerts.clear()
    _alerts.extend(orig_alerts)
    _worker_status.clear()
    _worker_status.extend(orig_workers)

def test_get_incident_dashboard(client):
    # active_alertsにCRITICAL(未確認)がある場合のstatus="critical"をテストするため、アラート1つをCRITICALで未確認にする
    _alerts.clear()
    _alerts.extend([
        {"id": 1, "type": "quota_warning", "level": "CRITICAL", "message": "Gemini API使用量が80%超過", "threshold": 80, "created_at": "2026-05-02T10:00:00", "acknowledged": False}
    ])
    resp = client.get("/api/admin/incident/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "critical"
    assert data["summary"]["active_alerts"] == 1
    
    # active_alertsがあり、CRITICALがない場合のstatus="warning"
    _alerts.clear()
    _alerts.extend([
        {"id": 1, "type": "quota_warning", "level": "WARNING", "message": "Gemini API使用量が80%超過", "threshold": 80, "created_at": "2026-05-02T10:00:00", "acknowledged": False}
    ])
    resp = client.get("/api/admin/incident/dashboard")
    assert resp.json()["status"] == "warning"

    # active_alertsがない場合のstatus="healthy"
    _alerts.clear()
    _alerts.extend([
        {"id": 1, "type": "quota_warning", "level": "WARNING", "message": "Gemini API使用量が80%超過", "threshold": 80, "created_at": "2026-05-02T10:00:00", "acknowledged": True}
    ])
    resp = client.get("/api/admin/incident/dashboard")
    assert resp.json()["status"] == "healthy"

def test_get_quota_breach(client):
    resp = client.get("/api/admin/incident/quota-breach")
    assert resp.status_code == 200
    assert resp.json()["level"] == "WARNING"

def test_get_pipeline_failures(client):
    resp = client.get("/api/admin/incident/pipeline-failures")
    assert resp.status_code == 200
    assert "failures" in resp.json()

def test_get_quality_degradation(client):
    resp = client.get("/api/admin/incident/quality-degradation")
    assert resp.status_code == 200
    assert resp.json()["current_score"] == 72

def test_get_auto_retry(client):
    resp = client.get("/api/admin/incident/auto-retry")
    assert resp.status_code == 200
    assert "retry_count" in resp.json()

def test_trigger_retry(client):
    resp = client.post("/api/admin/incident/retry", json={"session_id": "sess_123", "worker": "TranscribeWorker"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "retry_started"
    assert resp.json()["session_id"] == "sess_123"
    assert resp.json()["worker"] == "TranscribeWorker"

def test_manual_intervention_success(client):
    resp = client.post("/api/admin/incident/manual-intervention", json={"incident_id": "INC-001", "action": "restart"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "intervention_applied"
    assert resp.json()["action_taken"] == "restart"

def test_manual_intervention_not_found(client):
    resp = client.post("/api/admin/incident/manual-intervention", json={"incident_id": "INC-999", "action": "restart"})
    assert resp.status_code == 404
    assert "Incident INC-999 not found" in resp.json()["detail"]

def test_get_alerts(client):
    resp = client.get("/api/admin/incident/alerts")
    assert resp.status_code == 200
    assert resp.json()["total"] == len(_alerts)

def test_acknowledge_alert_success(client):
    resp = client.post("/api/admin/incident/alert-ack", json={"alert_id": 1})
    assert resp.status_code == 200
    assert resp.json()["status"] == "acknowledged"
    assert _alerts[0]["acknowledged"] is True

def test_acknowledge_alert_not_found(client):
    resp = client.post("/api/admin/incident/alert-ack", json={"alert_id": 999})
    assert resp.status_code == 404
    assert "Alert 999 not found" in resp.json()["detail"]

def test_get_incident_history(client):
    resp = client.get("/api/admin/incident/incidents")
    assert resp.status_code == 200
    assert len(resp.json()["incidents"]) == len(_incidents)

def test_get_incident_detail_success(client):
    resp = client.get("/api/admin/incident/incidents/INC-001")
    assert resp.status_code == 200
    assert resp.json()["id"] == "INC-001"

def test_get_incident_detail_not_found(client):
    resp = client.get("/api/admin/incident/incidents/INC-999")
    assert resp.status_code == 404
    assert "Incident INC-999 not found" in resp.json()["detail"]

def test_get_root_cause_analysis_success(client):
    resp = client.get("/api/admin/incident/rca/INC-001")
    assert resp.status_code == 200
    assert resp.json()["incident_id"] == "INC-001"
    assert "root_cause" in resp.json()

def test_get_root_cause_analysis_not_found(client):
    resp = client.get("/api/admin/incident/rca/INC-999")
    assert resp.status_code == 404
    assert "Incident INC-999 not found" in resp.json()["detail"]

def test_get_recovery_guide(client):
    resp = client.get("/api/admin/incident/recovery-guide")
    assert resp.status_code == 200
    assert "steps" in resp.json()

def test_get_sla_status(client):
    resp = client.get("/api/admin/incident/sla")
    assert resp.status_code == 200
    assert "uptime_pct" in resp.json()

def test_generate_incident_report_success(client):
    resp = client.post("/api/admin/incident/incident-report", json={"incident_id": "INC-001", "format": "pdf"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "generated"
    assert resp.json()["format"] == "pdf"

def test_generate_incident_report_invalid_format(client):
    resp = client.post("/api/admin/incident/incident-report", json={"incident_id": "INC-001", "format": "txt"})
    assert resp.status_code == 400
    assert "Invalid format" in resp.json()["detail"]

def test_escalate_incident(client):
    resp = client.post("/api/admin/incident/escalate", json={"incident_id": "INC-001", "channels": ["slack"], "message": "Help"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "escalated"

def test_get_recovery_check(client):
    # チェックリストで all_passed = True を発生させるために temporary に w["status"] = "healthy" にする
    orig_workers = [dict(w) for w in _worker_status]
    for w in _worker_status:
        w["status"] = "healthy"
    resp = client.get("/api/admin/incident/recovery-check")
    assert resp.status_code == 200
    # ただし、品質スコア(72)が90以上でないため「品質スコアが90以上」がFalseになり、all_passedはFalseになるはず
    assert resp.json()["all_passed"] is False

    # 復元
    _worker_status.clear()
    _worker_status.extend(orig_workers)

def test_get_performance(client):
    resp = client.get("/api/admin/incident/performance")
    assert resp.status_code == 200
    assert "cpu_pct" in resp.json()

def test_get_worker_isolation(client):
    resp = client.get("/api/admin/incident/worker-isolation")
    assert resp.status_code == 200
    assert "workers" in resp.json()

def test_get_self_healing(client):
    resp = client.get("/api/admin/incident/self-healing")
    assert resp.status_code == 200
    assert "events" in resp.json()

def test_get_failure_patterns(client):
    resp = client.get("/api/admin/incident/patterns")
    assert resp.status_code == 200
    assert "patterns" in resp.json()

def test_get_preventive_suggestions(client):
    resp = client.get("/api/admin/incident/preventive")
    assert resp.status_code == 200
    assert "suggestions" in resp.json()

def test_get_downtime(client):
    resp = client.get("/api/admin/incident/downtime")
    assert resp.status_code == 200
    assert "total_minutes" in resp.json()

def test_get_status_page(client):
    resp = client.get("/api/admin/incident/status-page")
    assert resp.status_code == 200
    assert "overall_status" in resp.json()

def test_get_incident_timeline_success_resolved(client):
    resp = client.get("/api/admin/incident/timeline/INC-002")
    assert resp.status_code == 200
    assert resp.json()["timeline"][-1]["event"] == "復旧完了"

def test_get_incident_timeline_success_open(client):
    resp = client.get("/api/admin/incident/timeline/INC-001")
    assert resp.status_code == 200
    # INC-001 は status が "open" なので "対応中" が返る
    assert resp.json()["timeline"][-1]["event"] == "対応中"

def test_get_incident_timeline_not_found(client):
    resp = client.get("/api/admin/incident/timeline/INC-999")
    assert resp.status_code == 404
    assert "Incident INC-999 not found" in resp.json()["detail"]
