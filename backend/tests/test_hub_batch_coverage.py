import pytest
import json
import uuid
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# テストに必要なモジュールのモックを sys.modules に事前注入する
mock_quality_feedback = MagicMock()
mock_quality_feedback_trigger_class = MagicMock()
mock_quality_feedback.QualityFeedbackTrigger = mock_quality_feedback_trigger_class
sys.modules["backend.services.quality_feedback_trigger"] = mock_quality_feedback

mock_wave_scheduler = MagicMock()
mock_wave_scheduler_class = MagicMock()
mock_wave_scheduler.WaveScheduler = mock_wave_scheduler_class
sys.modules["agents.orchestration.wave_scheduler"] = mock_wave_scheduler

mock_resource_governor = MagicMock()
mock_resource_governor_class = MagicMock()
mock_resource_governor.ResourceGovernor = mock_resource_governor_class
sys.modules["agents.orchestration.resource_governor"] = mock_resource_governor

mock_generator = MagicMock()
mock_task_generator_class = MagicMock()
mock_generator.TaskGenerator = mock_task_generator_class
sys.modules["agents.orchestration.generator"] = mock_generator

mock_design_stock = MagicMock()
mock_design_stock_store_class = MagicMock()
mock_design_stock.DesignStockStore = mock_design_stock_store_class
sys.modules["agents.orchestration.design_stock"] = mock_design_stock

mock_learning = MagicMock()
mock_learning.suggest_module_for_group = MagicMock(return_value=None)
mock_learning.get_diminishing_modules = MagicMock(return_value=[])
sys.modules["backend.agents.orchestration.learning_integration"] = mock_learning

mock_convergence = MagicMock()
mock_convergence_loop_class = MagicMock()
mock_convergence.ConvergenceLoop = mock_convergence_loop_class
sys.modules["agents.orchestration.convergence_loop"] = mock_convergence

mock_decomposer = MagicMock()
sys.modules["backend.agents.orchestration.ds_task_decomposer"] = mock_decomposer

mock_ast_generator = MagicMock()
sys.modules["backend.agents.orchestration.ast_test_generator"] = mock_ast_generator


from agents.orchestration.hub_batch import BatchMixin


class DummyOrchestrator(BatchMixin):
    def __init__(self):
        self._current_miss_counts = {}
        self._instrument_fail_counts = {}
        self._flash_batches_completed = 0
        self.blacklisted_modules_list = []

    def check_phase_gate(self, phase):
        return {"conditions": {}, "all_passed": True}

    def get_current_directive(self):
        return {
            "directive_id": "dir_001",
            "priorities": {"bug_hunter": 50, "test_weaver": 50},
            "blacklist_override": [],
            "focus_modules": []
        }

    def flash_session_start(self):
        pass

    def flash_update_status(self, *args, **kwargs):
        pass

    def read_messages(self, *args, **kwargs):
        return [{"id": "msg_001"}]

    def acknowledge_message(self, *args, **kwargs):
        pass

    def blacklist_module(self, mod, reason):
        if mod == "raise_error.py":
            raise Exception("Blacklist error")
        self.blacklisted_modules_list.append(mod)

    def flash_report_error(self, *args, **kwargs):
        pass

    def send_message(self, *args, **kwargs):
        pass

    def _generate_error_debug_report(self, *args, **kwargs):
        if kwargs.get("target_module") == "raise_error.py":
            raise Exception("Report generation error")


@pytest.fixture
def orchestrator():
    mock_learning.suggest_module_for_group.reset_mock()
    mock_learning.suggest_module_for_group.return_value = None
    mock_learning.get_diminishing_modules.reset_mock()
    mock_learning.get_diminishing_modules.return_value = []
    return DummyOrchestrator()


def test_load_coverage_data_error_handling(orchestrator, tmp_path):
    with patch("agents.orchestration.hub_batch.safe_read_json", side_effect=json.JSONDecodeError("msg", "doc", 0)):
        with patch("agents.orchestration.hub_batch._PROJECT_ROOT", tmp_path):
            (tmp_path / "coverage.json").write_text("invalid", encoding="utf-8")
            data = orchestrator._load_coverage_data()
            assert data == {}


def test_is_module_eligible_oserror(orchestrator, tmp_path):
    with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
        with patch("agents.orchestration.hub_batch._PROJECT_ROOT", tmp_path):
            with patch.object(Path, "exists", return_value=True):
                assert orchestrator._is_module_eligible("bug_hunter", "mod.py", {}, set()) is True


def test_get_module_miss_counts_edge_cases(orchestrator, tmp_path):
    reports_file = tmp_path / "flash_reports.jsonl"
    
    report = {
        "tasks": [
            {"target_module": "", "result": {}},
            {"target_module": "mod_a", "result": None},
            {"target_module": "mod_b", "result": {"changed_files": []}},
            {"target_module": "mod_b", "result": {"changed_files": ["foo.py"]}},
        ]
    }
    reports_file.write_text(json.dumps(report) + "\n", encoding="utf-8")
    
    with patch("agents.orchestration.hub_batch.FLASH_REPORTS_PATH", reports_file):
        miss_counts = orchestrator._get_module_miss_counts()
        assert "mod_a" in miss_counts
        assert miss_counts["mod_a"] == 1


def test_auto_heal_stagnation(orchestrator, tmp_path):
    state_file = tmp_path / "phase_state.json"
    
    with patch("agents.orchestration.hub_batch.PHASE_STATE_PATH", state_file):
        if state_file.exists():
            state_file.unlink()
        orchestrator.auto_heal_stagnation("test_reason")
        
    state_data = {
        "blacklisted_modules": [],
        "auto_blacklist_expiry": {}
    }
    state_file.write_text(json.dumps(state_data), encoding="utf-8")
    
    with patch.object(orchestrator, "_get_module_miss_counts", return_value={"stuck_mod.py": 2}):
        with patch("agents.orchestration.hub_batch.PHASE_STATE_PATH", state_file):
            orchestrator.auto_heal_stagnation("test_reason")
            
            updated_state = json.loads(state_file.read_text(encoding="utf-8"))
            assert "stuck_mod.py" in updated_state["blacklisted_modules"]
            assert updated_state["auto_blacklist_expiry"]["stuck_mod.py"] == 5


def test_create_random_tasks(orchestrator, tmp_path):
    tdr_file = tmp_path / "technical_debt_index.json"
    tdr_file.write_text(json.dumps({
        "entries": [
            {"status": "open", "file_path": "tdr_mod.py"}
        ]
    }), encoding="utf-8")

    with patch("agents.orchestration.hub_batch._MEMORY_DIR", tmp_path):
        tasks, assigned = orchestrator._create_random_tasks(
            batch_id="b001", phase=5, remaining_slots=2,
            priorities={"test_weaver": 0}, available_modules=["mod.py"]
        )
        assert len(tasks) == 0

        priorities = {"test_weaver": 100, "refactor": 0, "bug_hunter": 0}
        available = ["sat_mod.py"]
        miss_counts = {"sat_mod.py": 2}
        
        tasks, assigned = orchestrator._create_random_tasks(
            batch_id="b001", phase=5, remaining_slots=2,
            priorities=priorities, available_modules=available,
            miss_counts=miss_counts
        )
        assert len(tasks) > 0
        groups = {t["group"] for t in tasks}
        assert "refactor" in groups or "bug_hunter" in groups

        priorities = {"thumbnail": 100}
        available = ["thumbnail_gen.py", "other.py"]
        tasks, assigned = orchestrator._create_random_tasks(
            batch_id="b001", phase=5, remaining_slots=1,
            priorities=priorities, available_modules=available,
            miss_counts={}
        )
        assert len(tasks) == 1
        assert tasks[0]["target_module"] == "thumbnail_gen.py"

        priorities = {"tdr_cleanup": 100}
        available = ["tdr_mod.py", "other.py"]
        tasks, assigned = orchestrator._create_random_tasks(
            batch_id="b001", phase=5, remaining_slots=1,
            priorities=priorities, available_modules=available,
            miss_counts={}
        )
        assert len(tasks) == 1
        assert tasks[0]["target_module"] == "tdr_mod.py"

        priorities = {"coverage": 100}
        available = ["uncovered_mod.py"]
        with patch.object(orchestrator, "_load_coverage_data", return_value={"uncovered_mod.py": {"missing_lines": 5}}):
            tasks, assigned = orchestrator._create_random_tasks(
                batch_id="b001", phase=5, remaining_slots=1,
                priorities=priorities, available_modules=available,
                miss_counts={}
            )
            assert len(tasks) == 1
            assert tasks[0]["target_module"] == "uncovered_mod.py"


def test_replenish_from_design_stock_md(orchestrator, tmp_path):
    ds_dir = tmp_path / "backend" / "agents" / "orchestration" / "design_stock"
    ds_dir.mkdir(parents=True, exist_ok=True)
    md_file = ds_dir / "ds_phase_5.md"
    
    with patch("agents.orchestration.hub_batch._PROJECT_ROOT", tmp_path):
        items = orchestrator._replenish_from_design_stock_md(phase=5, existing_items=[], target_count=2)
        assert len(items) == 0

    md_file.write_text("Some text without target group definition", encoding="utf-8")
    with patch("agents.orchestration.hub_batch._PROJECT_ROOT", tmp_path):
        items = orchestrator._replenish_from_design_stock_md(phase=5, existing_items=[], target_count=2)
        assert len(items) > 0

    md_content = """
    ## 4. タスクグループ定義
    ### test_weaver（配分: 50%）
    - **対象**: agents/orchestration/hub_batch.py
    ```
    test_weaver_template_instruction
    ```
    """
    md_file.write_text(md_content, encoding="utf-8")
    with patch("agents.orchestration.hub_batch._PROJECT_ROOT", tmp_path):
        items = orchestrator._replenish_from_design_stock_md(phase=5, existing_items=[], target_count=1)
        assert len(items) == 1
        assert "test_weaver" in items[0]["id"]


def test_replenish_from_coverage_gaps(orchestrator, tmp_path):
    module_index_path = tmp_path / "backend" / "agents" / "orchestration" / "module_index.json"
    module_index_path.parent.mkdir(parents=True, exist_ok=True)
    module_index_path.write_text(json.dumps({
        "modules": ["agents/orchestration/hub_batch.py"]
    }), encoding="utf-8")

    state_file = tmp_path / "phase_state.json"
    state_file.write_text(json.dumps({
        "coverage_pct": 50.0,
        "blacklisted_modules": []
    }), encoding="utf-8")

    gates_path = tmp_path / "backend" / "agents" / "memory" / "phase_gates.json"
    gates_path.parent.mkdir(parents=True, exist_ok=True)
    gates_path.write_text(json.dumps({
        "5": {"min_coverage": 60.0}
    }), encoding="utf-8")

    with patch("agents.orchestration.hub_batch._PROJECT_ROOT", tmp_path):
        with patch("agents.orchestration.hub_batch.PHASE_STATE_PATH", state_file):
            items = orchestrator._replenish_from_coverage_gaps(phase=5, existing_items=[], target_count=2)
            assert len(items) > 0
            assert "hub_batch" in items[0]["description"]


def test_replenish_from_failed_tasks(orchestrator, tmp_path):
    reports_file = tmp_path / "flash_reports.jsonl"
    report = {
        "batch_id": "b001",
        "tasks": [
            {
                "group": "bug_hunter",
                "target_module": "failed_mod.py",
                "status": "fail",
                "result": {"error": "Test failure occurred"}
            }
        ]
    }
    reports_file.write_text(json.dumps(report) + "\n", encoding="utf-8")

    with patch("agents.orchestration.hub_batch.FLASH_REPORTS_PATH", reports_file):
        items = orchestrator._replenish_from_failed_tasks(phase=5, existing_items=[], target_count=1)
        assert len(items) == 1
        assert "failed_mod.py" in items[0]["title"]


def test_generate_batch_and_load_design_stock(orchestrator, tmp_path):
    orchestrator._auto_replenish_design_stock = MagicMock()
    ds_item = {
        "id": "DS-001",
        "title": "DS test item",
        "status": "pending",
        "phase": 5,
        "implementation_steps": []
    }
    orchestrator._load_design_stock_items = MagicMock(return_value=[ds_item])
    orchestrator._create_tasks_from_design_stock = MagicMock(return_value=[{
        "id": "T-DS-001",
        "group": "refactor",
        "target_module": "mod.py",
        "status": "pending"
    }])
    orchestrator._update_design_stock_status = MagicMock()
    
    state_file = tmp_path / "phase_state.json"
    state_file.write_text(json.dumps({
        "coverage_pct": 50.0,
        "blacklisted_modules": [],
        "module_cooldown": {},
        "flash_batches_completed": 1
    }), encoding="utf-8")
    
    with patch("agents.orchestration.hub_batch.PHASE_STATE_PATH", state_file):
        with patch.object(orchestrator, "_get_available_modules", return_value=["mod.py"]):
            with patch.object(orchestrator, "_create_random_tasks", return_value=([], set())):
                with patch("agents.orchestration.hub_batch.TASK_QUEUE_PATH", tmp_path / "task_queue.json"):
                    batch = orchestrator._generate_batch(phase=5, milestone="M5.1", batch_size=2)
                    assert batch["current_batch_id"] is not None
                    assert batch["design_stock_tasks"] == 1


def test_load_design_stock_items(orchestrator, tmp_path):
    ds_file = tmp_path / "design_stock.json"
    
    with patch("agents.orchestration.hub_batch.DESIGN_STOCK_PATH", ds_file):
        if ds_file.exists():
            ds_file.unlink()
        items = orchestrator._load_design_stock_items(5)
        assert items == []

    ds_data = {
        "stock_items": [
            {"id": "DS-1", "status": "pending", "phase": 5},
            {"id": "DS-2", "status": "completed", "phase": 5},
            {"id": "DS-3", "status": "pending", "phase": 6},
        ]
    }
    ds_file.write_text(json.dumps(ds_data), encoding="utf-8")
    with patch("agents.orchestration.hub_batch.DESIGN_STOCK_PATH", ds_file):
        items = orchestrator._load_design_stock_items(5)
        assert len(items) == 1
        assert items[0]["id"] == "DS-1"


def test_create_tasks_from_design_stock(orchestrator):
    ds_item = {
        "id": "DS-001",
        "title": "DS item",
        "implementation_steps": ["step1"]
    }
    
    mock_gen_instance = MagicMock()
    mock_gen_instance.create_batch_tasks.return_value = [{"id": "T-1"}]
    mock_task_generator_class.return_value = mock_gen_instance
    
    tasks = orchestrator._create_tasks_from_design_stock(ds_item, "b001", 5)
    assert len(tasks) == 1
    assert tasks[0]["id"] == "T-1"


def test_update_design_stock_status(orchestrator, tmp_path):
    ds_file = tmp_path / "design_stock.json"
    ds_file.write_text(json.dumps({"stock_items": []}), encoding="utf-8")
    
    mock_store_instance = MagicMock()
    mock_design_stock_store_class.return_value = mock_store_instance
    
    with patch("agents.orchestration.hub_batch.DESIGN_STOCK_PATH", ds_file):
        orchestrator._update_design_stock_status("DS-001", "completed")
        mock_store_instance.update_status.assert_called_with("DS-001", "completed")


def test_get_available_modules(orchestrator):
    cache_data = {
        "modules": ["agents/orchestration/hub_batch.py"],
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    # 1. 正常なキャッシュロード
    with patch("agents.orchestration.hub_batch.safe_read_json", return_value=cache_data):
        mods = orchestrator._get_available_modules(blacklisted=set())
        assert mods == ["agents/orchestration/hub_batch.py"]

    # 2. キャッシュの読み込み例外をカバー
    with patch("agents.orchestration.hub_batch.safe_read_json", side_effect=Exception("Cache read error")):
        with patch.object(orchestrator, "_scan_backend_modules", return_value=["backend/new.py"]):
            with patch("agents.orchestration.hub_batch.atomic_write_json") as mock_write:
                mods = orchestrator._get_available_modules(blacklisted=set())
                assert mods == ["backend/new.py"]
                mock_write.assert_called()

    # 3. キャッシュの書き込み例外をカバー
    with patch("agents.orchestration.hub_batch.safe_read_json", return_value={}):
        with patch.object(orchestrator, "_scan_backend_modules", return_value=["backend/new.py"]):
            with patch("agents.orchestration.hub_batch.atomic_write_json", side_effect=Exception("Cache write error")):
                mods = orchestrator._get_available_modules(blacklisted=set())
                assert mods == ["backend/new.py"]


def test_scan_backend_modules(orchestrator, tmp_path):
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True, exist_ok=True)
    
    prod_file = backend_dir / "prod.py"
    content = (
        "import os\n"
        "import sys\n"
        "import json\n"
        "def f1():\n"
        "    pass\n"
        "def f2():\n"
        "    pass\n"
    )
    content += "#" * 500
    prod_file.write_text(content, encoding="utf-8")
    
    excluded_file = backend_dir / "scratch_test.py"
    excluded_file.write_text("def f(): pass", encoding="utf-8")
    
    with patch("agents.orchestration.hub_batch._PROJECT_ROOT", tmp_path):
        mods = orchestrator._scan_backend_modules()
        assert "prod.py" in mods
        assert "scratch_test.py" not in mods


def test_is_production_module(tmp_path):
    prod_file = tmp_path / "prod.py"
    
    prod_file.write_text("short", encoding="utf-8")
    assert BatchMixin._is_production_module(prod_file) is False

    content = (
        "import os\n"
        "import sys\n"
        "import json\n"
        "def func1():\n"
        "    pass\n"
        "def func2():\n"
        "    pass\n"
    )
    content += "#" * 500
    prod_file.write_text(content, encoding="utf-8")
    assert BatchMixin._is_production_module(prod_file) is True


def test_trigger_quality_fix(orchestrator):
    mock_trigger_instance = MagicMock()
    mock_trigger_instance.evaluate_and_trigger.return_value = {
        "triggered": True,
        "low_axes": ["audio"],
        "tasks_created": 1,
        "details": "Details msg"
    }
    mock_quality_feedback_trigger_class.return_value = mock_trigger_instance
    
    res = orchestrator.trigger_quality_fix({"report": {}})
    assert res == "Details msg"


def test_calculate_dynamic_limit(orchestrator):
    session = {"recent_errors": []}
    assert orchestrator._calculate_dynamic_limit(session) == 15

    session = {
        "recent_errors": [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": "429: Too many requests"
            }
        ]
    }
    assert orchestrator._calculate_dynamic_limit(session) == 2


def test_recover_timed_out_tasks(orchestrator, tmp_path):
    session_file = tmp_path / "flash_session.json"
    session_file.write_text(json.dumps({}), encoding="utf-8")
    
    started_at = (datetime.now(timezone.utc) - timedelta(seconds=1000)).isoformat()
    queue = {
        "tasks": [
            {
                "id": "T-1",
                "status": "running",
                "started_at": started_at,
                "retry_count": 0,
                "target_module": "mod.py"
            }
        ]
    }
    
    with patch("agents.orchestration.hub_batch.FLASH_SESSION_PATH", session_file):
        changed = orchestrator._recover_timed_out_tasks(queue, timeout_seconds=900)
        assert changed is True
        assert queue["tasks"][0]["status"] == "pending"
        assert queue["tasks"][0]["retry_count"] == 1


def test_is_cooldown_active(orchestrator):
    session = {
        "recent_errors": [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": "RESOURCE_EXHAUSTED"
            }
        ]
    }
    assert orchestrator._is_cooldown_active(session, datetime.now(timezone.utc)) is True


def test_reset_stale_running_tasks(orchestrator):
    started_at = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
    queue = {
        "tasks": [
            {"id": "T-1", "status": "running", "started_at": started_at}
        ]
    }
    count = orchestrator._reset_stale_running_tasks(queue, datetime.now(timezone.utc))
    assert count == 1
    assert queue["tasks"][0]["status"] == "pending"


def test_calculate_max_concurrent(orchestrator, tmp_path):
    """段（tier）からモデルを引き、その枠と残数で同時実行数を決める。

    **2026-08-28 まで設定ファイルを置く場所が違っていて（`backend/` が
    抜けていた）、この設定は一度も読まれていなかった。** モデル名を
    直書きしていたので気づけなかった（R1.5-C6）。
    """
    session = {"recent_errors": []}
    
    (tmp_path / "backend").mkdir()
    config_file = tmp_path / "backend" / "model_config.json"
    config_file.write_text(json.dumps({
        "text_generation": {
            "tiers": {
                "batch": {"model": "gemini-3.5-flash-lite"},
                "standard": {"model": "gemini-3.6-flash"},
            }
        },
        "free_tier_limits": {
            "gemini-3.6-flash": {"rpm": 15}
        }
    }), encoding="utf-8")
    
    mock_tracker = MagicMock()
    mock_tracker.get_remaining_requests.return_value = 10
    
    with patch("agents.orchestration.hub_batch._PROJECT_ROOT", tmp_path):
        with patch("backend.usage_tracker.tracker.usage_tracker", mock_tracker, create=True):
            res = orchestrator._calculate_max_concurrent(phase=6, batch_size=30, session=session)
            assert res == 10
            # 段から引いた実モデル ID で残数を聞いていること
            mock_tracker.get_remaining_requests.assert_called_with("gemini-3.6-flash")


def test_calculate_max_concurrent_段を引けなければ絞らない(orchestrator, tmp_path):
    """**設定を読み損ねたことを「残り 0 件」と読み替えない**（R1.5-C6）。

    段からモデルを引けないと `get_remaining_requests("")` が 0 を返し、
    同時実行数が 2 に落ちる。設定の読み損ねが処理速度の低下として現れ、
    原因が見えなくなる。
    """
    session = {"recent_errors": []}
    mock_tracker = MagicMock()
    mock_tracker.get_remaining_requests.return_value = 0

    with patch("agents.orchestration.hub_batch._PROJECT_ROOT", tmp_path):
        with patch("backend.usage_tracker.tracker.usage_tracker", mock_tracker, create=True):
            res = orchestrator._calculate_max_concurrent(phase=6, batch_size=30, session=session)

    assert res == 12, res           # min(30, 15, 15*0.8) — 残数では絞らない
    mock_tracker.get_remaining_requests.assert_not_called()


def test_get_next_batch(orchestrator, tmp_path):
    queue_file = tmp_path / "task_queue.json"
    queue_file.write_text(json.dumps({
        "current_batch_id": "b001",
        "tasks": [
            {"id": "T-1", "status": "pending", "dependencies": []}
        ]
    }), encoding="utf-8")
    
    session_file = tmp_path / "flash_session.json"
    session_file.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    
    mock_scheduler_instance = MagicMock()
    mock_scheduler_instance.schedule_waves.return_value = [[{"id": "T-1", "status": "pending"}]]
    mock_wave_scheduler_class.return_value = mock_scheduler_instance
    
    mock_gov_instance = MagicMock()
    mock_resource_governor_class.return_value = mock_gov_instance
    
    with patch("agents.orchestration.hub_batch.TASK_QUEUE_PATH", queue_file):
        with patch("agents.orchestration.hub_batch.FLASH_SESSION_PATH", session_file):
            orchestrator._calculate_max_concurrent = MagicMock(return_value=5)
            
            batch = orchestrator.get_next_batch(phase=5, milestone="M5.1")
            assert len(batch) == 1
            assert batch[0]["id"] == "T-1"


def test_mark_task_done(orchestrator, tmp_path):
    queue_file = tmp_path / "task_queue.json"
    queue_file.write_text(json.dumps({
        "tasks": [
            {"id": "T-1", "status": "running", "target_module": "mod.py", "retry_count": 1},
            {"id": "T-2", "status": "pending", "dependencies": ["T-1"]}
        ]
    }), encoding="utf-8")
    
    state_file = tmp_path / "phase_state.json"
    state_file.write_text(json.dumps({
        "flash_tasks_total": 0,
        "flash_tasks_passed": 0,
        "flash_consecutive_failures": 0
    }), encoding="utf-8")
    
    session_file = tmp_path / "flash_session.json"
    session_file.write_text(json.dumps({}), encoding="utf-8")
    
    with patch("agents.orchestration.hub_batch.TASK_QUEUE_PATH", queue_file):
        with patch("agents.orchestration.hub_batch.PHASE_STATE_PATH", state_file):
            with patch("agents.orchestration.hub_batch.FLASH_SESSION_PATH", session_file):
                # 1. 正常終了 (pass) + 収束ループでのリトライ成功記録
                mock_conv_instance = MagicMock()
                mock_convergence_loop_class.return_value = mock_conv_instance
                
                orchestrator.mark_task_done("T-1", "pass", {"changed_files": ["foo.py"]})
                
                queue_data = json.loads(queue_file.read_text(encoding="utf-8"))
                assert queue_data["tasks"][0]["status"] == "pass"
                
                state_data = json.loads(state_file.read_text(encoding="utf-8"))
                assert state_data["flash_tasks_passed"] == 1
                mock_conv_instance.record_retry_event.assert_called()

                # 2. ConvergenceLoop 例外カバー (1830-1831)
                mock_conv_instance.record_retry_event.side_effect = Exception("ConvergenceLoop error")
                orchestrator.mark_task_done("T-1", "pass", {"changed_files": ["foo.py"]})
                mock_conv_instance.record_retry_event.side_effect = None

                # 3. FAIL時の処理（リトライ可能）
                queue_file.write_text(json.dumps({
                    "tasks": [
                        {"id": "T-1", "status": "running", "target_module": "mod.py", "retry_count": 0},
                        {"id": "T-2", "status": "pending", "dependencies": ["T-1"]}
                    ]
                }), encoding="utf-8")
                
                mock_conv_instance.should_retry.return_value = {"retry": True, "retry_count": 0, "feedback_prompt": "retry it"}
                
                orchestrator.mark_task_done("T-1", "fail", {"error": "Compilation error"})
                mock_conv_instance.prepare_retry.assert_called_with("T-1", "retry it")
                
                # 4. FAIL時の処理（リトライ不可、連続3回FAILでブラックリスト & 依存タスクのカスケード失敗）
                queue_file.write_text(json.dumps({
                    "tasks": [
                        {"id": "T-1", "status": "running", "target_module": "mod.py", "retry_count": 0},
                        {"id": "T-2", "status": "pending", "dependencies": ["T-1"]}
                    ]
                }), encoding="utf-8")
                state_file.write_text(json.dumps({
                    "flash_tasks_total": 0,
                    "flash_tasks_passed": 0,
                    "flash_consecutive_failures": 2
                }), encoding="utf-8")
                
                mock_conv_instance.should_retry.return_value = {"retry": False, "reason": "Max retries"}
                
                orchestrator.mark_task_done("T-1", "fail", {"error": "Critical compilation error"})
                
                assert "mod.py" in orchestrator.blacklisted_modules_list
                queue_final = json.loads(queue_file.read_text(encoding="utf-8"))
                assert queue_final["tasks"][1]["status"] == "skipped"

                # 5. should_retry などの例外カバー (1886-1887)
                mock_conv_instance.should_retry.side_effect = Exception("should_retry error")
                orchestrator.mark_task_done("T-1", "fail", {"error": "Critical compilation error"})
                mock_conv_instance.should_retry.side_effect = None

                # 6. report_error / debug_report 生成例外カバー (1900-1901, 1913-1914)
                queue_file.write_text(json.dumps({
                    "tasks": [
                        {"id": "T-1", "status": "running", "target_module": "raise_error.py", "retry_count": 0}
                    ]
                }), encoding="utf-8")
                orchestrator.mark_task_done("T-1", "fail", {"error": "Critical compilation error"})


def test_filter_blacklisted(orchestrator):
    modules = ["mod_a.py", "mod_b.py", "dir/mod_c.py"]
    blacklisted = {None, "", "mod_a", "dir/mod_c.py"}
    
    filtered = orchestrator._filter_blacklisted(modules, blacklisted)
    assert filtered == ["mod_b.py"]
