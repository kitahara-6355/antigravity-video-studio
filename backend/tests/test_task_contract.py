import pytest
from pathlib import Path
from backend.agents.task_contract import (
    TaskContract,
    TaskStatus,
    EvidenceType,
    EvidenceRequirement,
    TaskContractManager,
    task_contract_manager
)
from backend.agents.memory.technical_debt import technical_debt_store

def test_task_status_enum():
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.IN_PROGRESS.value == "in_progress"
    assert TaskStatus.AWAITING_REVIEW.value == "awaiting_review"
    assert TaskStatus.PASSED.value == "passed"
    assert TaskStatus.FAILED.value == "failed"
    assert TaskStatus.ESCALATED.value == "escalated"

def test_evidence_type_enum():
    assert EvidenceType.FILE_EXISTS.value == "file_exists"
    assert EvidenceType.FILE_CONTENT.value == "file_content"
    assert EvidenceType.API_RESPONSE.value == "api_response"
    assert EvidenceType.SCORE_THRESHOLD.value == "score_threshold"
    assert EvidenceType.LOG_CONTAINS.value == "log_contains"
    assert EvidenceType.CUSTOM.value == "custom"

def test_create_contract():
    manager = TaskContractManager()
    evidence_list = [
        {"type": "file_exists", "description": "Output exists", "data": {"path": "test.txt"}},
        {"type": "custom", "description": "Custom check"}
    ]
    contract = manager.create_contract(
        task_id="task_1",
        description="Test task 1",
        definition_of_done="File must exist",
        evidence=evidence_list,
        max_retries=2,
        timeout_seconds=120,
        fallback_strategy="escalate"
    )

    assert contract.task_id == "task_1"
    assert contract.description == "Test task 1"
    assert contract.definition_of_done == "File must exist"
    assert len(contract.evidence_required) == 2
    assert contract.evidence_required[0].evidence_type == "file_exists"
    assert contract.evidence_required[0].description == "Output exists"
    assert contract.evidence_required[0].verification_data == {"path": "test.txt"}
    assert contract.evidence_required[1].evidence_type == "custom"
    assert contract.evidence_required[1].description == "Custom check"
    assert contract.evidence_required[1].verification_data == {}
    assert contract.max_retries == 2
    assert contract.timeout_seconds == 120
    assert contract.fallback_strategy == "escalate"
    assert contract.status == "pending"
    assert contract.created_at is not None
    assert manager.active_contracts["task_1"] == contract

def test_create_contract_robustness():
    manager = TaskContractManager()
    
    # task_id が不正な場合
    with pytest.raises(ValueError, match="task_id must be a non-empty string"):
        manager.create_contract("", "Desc", "DoD")
        
    with pytest.raises(ValueError, match="task_id must be a non-empty string"):
        manager.create_contract(None, "Desc", "DoD")

    # 型異常パラメータのフォールバック検証
    contract = manager.create_contract(
        task_id="task_2",
        description=None,
        definition_of_done=123,
        evidence=[
            "not a dict",
            {"type": 123, "description": None, "data": "not a dict"}
        ],
        max_retries="invalid",
        timeout_seconds=-1,
        fallback_strategy=None
    )

    assert contract.task_id == "task_2"
    assert contract.description == ""
    assert contract.definition_of_done == ""
    assert contract.max_retries == 3
    assert contract.timeout_seconds == 300
    assert contract.fallback_strategy == "report_to_coordinator"
    assert len(contract.evidence_required) == 1
    assert contract.evidence_required[0].evidence_type == "custom"
    assert contract.evidence_required[0].description == ""
    assert contract.evidence_required[0].verification_data == {}

def test_start_task():
    manager = TaskContractManager()
    contract = manager.create_contract("task_1", "Desc", "DoD")
    assert contract.started_at is None
    
    started = manager.start_task("task_1")
    assert started is not None
    assert started.status == "in_progress"
    assert started.started_at is not None
    first_started_at = started.started_at

    # 既に開始されている場合、再開始しても started_at は上書きされないこと
    started_again = manager.start_task("task_1")
    assert started_again.started_at == first_started_at

    # 存在しないタスクIDや不正な型
    assert manager.start_task("invalid_task") is None
    assert manager.start_task(None) is None

def test_submit_evidence_and_completion(tmp_path):
    manager = TaskContractManager()
    file_path = tmp_path / "test.txt"
    file_path.write_text("Hello World")

    evidence_list = [
        {"type": "file_exists", "description": "File exists", "data": {"path": str(file_path), "min_size_bytes": 5}},
        {"type": "score_threshold", "description": "Score check", "data": {"key": "score", "min_value": 80}},
        {"type": "log_contains", "description": "Log check", "data": {"log_key": "log", "contains": "SUCCESS"}},
        {"type": "custom", "description": "Custom verified"}
    ]

    contract = manager.create_contract(
        task_id="task_1",
        description="Desc",
        definition_of_done="DoD",
        evidence=evidence_list
    )

    # 存在しないタスクIDや不適切な引数への証拠提出
    assert manager.submit_evidence("invalid_task", {}) is None
    assert manager.submit_evidence(None, {}) is None

    # 証拠充足前の状態
    manager.submit_evidence("task_1", {"score": 85, "log": "Operation SUCCESS", "verified": True})
    
    # 充足の検証
    assert contract.evidence_required[0].satisfied is True
    assert contract.evidence_required[1].satisfied is True
    assert contract.evidence_required[2].satisfied is True
    assert contract.evidence_required[3].satisfied is True

    # 既に充足された証拠を再度検証しない分岐のカバー
    manager.submit_evidence("task_1", {"score": 0, "log": "FAILED", "verified": False})
    assert contract.evidence_required[0].satisfied is True
    assert contract.evidence_required[1].satisfied is True

    # 完了チェック
    status_info = manager.check_completion("task_1")
    assert status_info["completed"] is True
    assert status_info["all_evidence_satisfied"] is True
    assert len(status_info["missing_evidence"]) == 0
    assert status_info["status"] == "passed"
    
    # アーカイブされたか確認
    assert "task_1" not in manager.active_contracts
    assert len(manager.completed_contracts) == 1
    assert manager.completed_contracts[0].task_id == "task_1"

    # すでに passed であるタスクに対して再度 check_completion / submit_evidence を呼び出す
    # アーカイブされたため、Contract not found / None になるのが正しい挙動
    status_info2 = manager.check_completion("task_1")
    assert status_info2 == {"completed": False, "error": "Contract not found"}
    
    res_sub = manager.submit_evidence("task_1", {})
    assert res_sub is None

def test_check_completion_not_found():
    manager = TaskContractManager()
    assert manager.check_completion("invalid_task") == {"completed": False, "error": "Contract not found"}
    assert manager.check_completion(None) == {"completed": False, "error": "Contract not found"}

def test_submit_evidence_partial_satisfaction():
    manager = TaskContractManager()
    evidence_list = [
        {"type": "score_threshold", "description": "Score check", "data": {"key": "score", "min_value": 80}},
        {"type": "custom", "description": "Custom verified"}
    ]
    contract = manager.create_contract(
        task_id="task_1",
        description="Desc",
        definition_of_done="DoD",
        evidence=evidence_list
    )

    # 不正な型の証拠データ
    manager.submit_evidence("task_1", None)
    assert contract.evidence_required[0].satisfied is False

    # 片方だけ満たす
    manager.submit_evidence("task_1", {"score": 70, "verified": True})
    assert contract.evidence_required[0].satisfied is False
    assert contract.evidence_required[1].satisfied is True

    status_info = manager.check_completion("task_1")
    assert status_info["completed"] is False
    assert status_info["all_evidence_satisfied"] is False
    assert status_info["missing_evidence"] == ["Score check"]
    assert status_info["status"] == "pending"

def test_report_failure_and_circuit_breaker():
    manager = TaskContractManager()
    contract = manager.create_contract(
        task_id="task_1",
        description="Desc",
        definition_of_done="DoD",
        max_retries=2,
        fallback_strategy="escalate"
    )

    # 存在しないタスクや不正なIDへの報告
    assert manager.report_failure("invalid_task", "Some error") == {"action": "abort", "reason": "Contract not found"}
    assert manager.report_failure(None, "Some error") == {"action": "abort", "reason": "Contract not found"}

    # 1回目の失敗
    res1 = manager.report_failure("task_1", error=Exception("ErrorObj"), context="invalid_context")
    assert res1["action"] == "retry"
    assert res1["attempt"] == 1
    assert contract.retry_count == 1
    assert len(contract.error_history) == 1
    assert contract.error_history[0]["error"] == "ErrorObj"
    assert contract.error_history[0]["context"] == {}

    # 2回目の失敗
    res2 = manager.report_failure("task_1", "Error 2")
    assert res2["action"] == "escalate"
    assert res2["reason"] == "2回連続失敗"
    assert contract.status == "escalated"

    # すでに escalated であるタスクへの報告
    res3 = manager.report_failure("task_1", "Error 3")
    assert res3["action"] == "abort"
    assert res3["reason"] == "Task already terminated"

def test_verify_evidence_robustness(tmp_path):
    manager = TaskContractManager()
    
    # requirement や data が None などのガード
    assert manager._verify_evidence(None, {}) is False
    req = EvidenceRequirement(evidence_type="custom", description="desc", verification_data=None)
    assert manager._verify_evidence(req, {}) is False
    req.verification_data = {}
    assert manager._verify_evidence(req, None) is False

    # FILE_EXISTS
    req_file = EvidenceRequirement(evidence_type="file_exists", description="desc", verification_data={})
    # path がない
    assert manager._verify_evidence(req_file, {}) is False
    # path が不正な型
    req_file.verification_data = {"path": 123}
    assert manager._verify_evidence(req_file, {}) is False

    # min_size_bytes が指定なしで exists が True のルート
    file_path = tmp_path / "exists.txt"
    file_path.write_text("ok")
    req_file.verification_data = {"path": str(file_path)}
    assert manager._verify_evidence(req_file, {}) is True

    # min_size_bytes が指定ありで exists が True, min_size_bytes が不正な型のガード
    req_file.verification_data = {"path": str(file_path), "min_size_bytes": "invalid"}
    assert manager._verify_evidence(req_file, {}) is False

    # FILE_EXISTS での OSError のガード
    from unittest.mock import patch
    req_file.verification_data = {"path": str(file_path)}
    
    with patch("pathlib.Path.exists", side_effect=OSError("Mocked OS Error")):
        assert manager._verify_evidence(req_file, {}) is False

    # SCORE_THRESHOLD
    req_score = EvidenceRequirement(evidence_type="score_threshold", description="desc", verification_data={})
    # ver_data が辞書でない
    req_score.verification_data = None
    assert manager._verify_evidence(req_score, {}) is False
    
    # key がない、または空文字列、または不正な型
    req_score.verification_data = {}
    assert manager._verify_evidence(req_score, {"score": 100}) is False
    req_score.verification_data = {"key": ""}
    assert manager._verify_evidence(req_score, {"score": 100}) is False
    req_score.verification_data = {"key": 123}
    assert manager._verify_evidence(req_score, {"score": 100}) is False
    
    # min_value が数値でない
    req_score.verification_data = {"key": "score", "min_value": "not_number"}
    assert manager._verify_evidence(req_score, {"score": 100}) is False
    
    # actual が数値でない
    req_score.verification_data = {"key": "score", "min_value": 80}
    assert manager._verify_evidence(req_score, {"score": "not_number"}) is False

    # LOG_CONTAINS
    req_log = EvidenceRequirement(evidence_type="log_contains", description="desc", verification_data={})
    # log_key がない、または空文字列、または不正な型
    assert manager._verify_evidence(req_log, {"log": "SUCCESS"}) is False
    req_log.verification_data = {"log_key": ""}
    assert manager._verify_evidence(req_log, {"log": "SUCCESS"}) is False
    req_log.verification_data = {"log_key": 123}
    assert manager._verify_evidence(req_log, {"log": "SUCCESS"}) is False
    
    # expected (contains) が文字列でない
    req_log.verification_data = {"log_key": "log", "contains": 123}
    assert manager._verify_evidence(req_log, {"log": "SUCCESS"}) is False
    
    # actual が文字列でない
    req_log.verification_data = {"log_key": "log", "contains": "SUCCESS"}
    assert manager._verify_evidence(req_log, {"log": 123}) is False

    # CUSTOM
    req_custom = EvidenceRequirement(evidence_type="custom", description="desc", verification_data={})
    # verified が真偽値以外の値
    assert manager._verify_evidence(req_custom, {"verified": "truthy_string"}) is True
    assert manager._verify_evidence(req_custom, {"verified": ""}) is False

def test_completed_task_guards():
    manager = TaskContractManager()
    
    # PASSED 状態のタスクがアクティブに残っている場合のガード
    contract = manager.create_contract("task_passed", "Desc", "DoD")
    contract.status = "passed"
    
    # submit_evidence は何もせず contract を返す
    res = manager.submit_evidence("task_passed", {"verified": True})
    assert res == contract
    
    # check_completion は completed: True を返す
    res_comp = manager.check_completion("task_passed")
    assert res_comp["completed"] is True
    assert res_comp["status"] == "passed"
    
    # report_failure は abort を返す
    res_fail = manager.report_failure("task_passed", "Error")
    assert res_fail["action"] == "abort"
    assert res_fail["reason"] == "Task already terminated"

def test_verify_evidence_unsupported_type():
    manager = TaskContractManager()
    req = EvidenceRequirement(evidence_type="unsupported", description="Unsupported type")
    assert manager._verify_evidence(req, {}) is False

def test_get_pipeline_contracts():
    manager = TaskContractManager()
    contracts = manager.get_pipeline_contracts()
    assert len(contracts) == 5
    task_ids = [c["task_id"] for c in contracts]
    assert "transcribe" in task_ids
    assert "proofread" in task_ids
    assert "quality_gate" in task_ids
    assert "render" in task_ids
    assert "thumbnail" in task_ids

def test_get_stats():
    manager = TaskContractManager()
    stats = manager.get_stats()
    assert stats == {"active": 0, "completed": 0, "passed": 0, "escalated": 0}

    c1 = manager.create_contract("task_1", "Desc", "DoD")
    stats = manager.get_stats()
    assert stats["active"] == 1
    assert stats["completed"] == 0

    manager.start_task("task_1")
    manager.check_completion("task_1")
    stats = manager.get_stats()
    assert stats["active"] == 0
    assert stats["completed"] == 1
    assert stats["passed"] == 1
    assert stats["escalated"] == 0

    c2 = manager.create_contract("task_2", "Desc", "DoD", max_retries=1)
    manager.report_failure("task_2", "Error")
    stats = manager.get_stats()
    assert stats["escalated"] == 1

def test_singleton_instance():
    assert isinstance(task_contract_manager, TaskContractManager)

def create_valid_thumbnail_file(path, width=1280, height=720, fmt="PNG"):
    from PIL import Image
    img = Image.new("RGB", (width, height), color=(73, 109, 137))
    img.save(path, format=fmt)
    return path

def test_evidence_thumbnail_quality_success(tmp_path):
    manager = TaskContractManager()
    file_path = tmp_path / "valid_thumb.png"
    create_valid_thumbnail_file(file_path, 1280, 720)

    evidence_list = [
        {"type": "thumbnail_quality", "description": "Thumbnail check", "data": {"path": str(file_path)}}
    ]
    contract = manager.create_contract(
        task_id="task_thumb_success",
        description="Thumbnail check",
        definition_of_done="Valid thumbnail must be generated",
        evidence=evidence_list
    )

    manager.submit_evidence("task_thumb_success", {})
    assert contract.evidence_required[0].satisfied is True
    
    status_info = manager.check_completion("task_thumb_success")
    assert status_info["completed"] is True

def test_evidence_thumbnail_quality_failures(tmp_path):
    manager = TaskContractManager()
    
    # 1. 存在しないファイル
    req = EvidenceRequirement(evidence_type="thumbnail_quality", description="desc", verification_data={"path": str(tmp_path / "missing.png")})
    assert manager._verify_evidence(req, {}) is False

    # 2. 解像度不足の画像
    low_res_path = tmp_path / "low_res.png"
    create_valid_thumbnail_file(low_res_path, 640, 360)
    req = EvidenceRequirement(evidence_type="thumbnail_quality", description="desc", verification_data={"path": str(low_res_path)})
    assert manager._verify_evidence(req, {}) is False

    # 3. アスペクト比異常
    bad_ratio_path = tmp_path / "bad_ratio.png"
    create_valid_thumbnail_file(bad_ratio_path, 1280, 960) # 4:3
    req = EvidenceRequirement(evidence_type="thumbnail_quality", description="desc", verification_data={"path": str(bad_ratio_path)})
    assert manager._verify_evidence(req, {}) is False

    # 4. ファイルサイズ超過 (>4MB)
    valid_path = tmp_path / "mock_size.png"
    create_valid_thumbnail_file(valid_path, 1280, 720)
    req = EvidenceRequirement(evidence_type="thumbnail_quality", description="desc", verification_data={"path": str(valid_path)})
    from unittest.mock import patch
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        assert manager._verify_evidence(req, {}) is False

    # 5. 画像ファイル破損
    corrupted_path = tmp_path / "corrupted.png"
    corrupted_path.write_text("not an image binary")
    req = EvidenceRequirement(evidence_type="thumbnail_quality", description="desc", verification_data={"path": str(corrupted_path)})
    assert manager._verify_evidence(req, {}) is False

def test_stage_bound_agent_thumbnail_task_contract_integration(tmp_path):
    import asyncio
    import sqlite3
    import json
    from backend.agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "stage_bound_contract.db"
    output_dir = tmp_path / "output_thumbs"
    output_dir.mkdir(parents=True, exist_ok=True)

    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "task_contract_integration_test"
    
    async def process_thumbnail_task(tid):
        out_path = output_dir / f"{tid}.png"
        create_valid_thumbnail_file(out_path, 1280, 720)
        
        contract_mgr = TaskContractManager()
        evidence_list = [
            {"type": "thumbnail_quality", "description": "Verify thumbnail", "data": {"path": str(out_path)}}
        ]
        contract = contract_mgr.create_contract(
            task_id=tid,
            description="Integration test",
            definition_of_done="Verify DoD",
            evidence=evidence_list
        )
        
        contract_mgr.start_task(tid)
        contract_mgr.submit_evidence(tid, {})
        comp_info = contract_mgr.check_completion(tid)
        
        if comp_info["completed"]:
            return json.dumps({
                "status": "success",
                "width": 1280,
                "height": 720,
                "path": str(out_path)
            })
        else:
            raise ValueError(f"DoD verification failed: {comp_info['missing_evidence']}")

    async def run_test():
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        await agent.start(process_thumbnail_task)
        
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, result FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, result_str = row
            assert status == "COMPLETED"
            
            result_data = json.loads(result_str)
            assert result_data["status"] == "success"
            assert result_data["width"] == 1280
            assert result_data["height"] == 720
        finally:
            conn.close()
            
    asyncio.run(run_test())
