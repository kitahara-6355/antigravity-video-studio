import os
import json
import pytest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from agents.tick_loop import TickLoop, TickActionType, TickResult

@pytest.mark.asyncio
async def test_tick_loop_init_and_status():
    loop = TickLoop(tick_interval=10, sleep_interval=20, blocking_budget=5)
    status = loop.get_status()
    assert status["is_running"] is False
    assert status["is_sleeping"] is False
    assert status["total_ticks"] == 0
    assert status["foreground_active"] is False
    assert status["current_interval"] == 10

@pytest.mark.asyncio
async def test_tick_loop_foreground_skip():
    loop = TickLoop()
    loop.set_foreground_active(True)
    res = await loop.manual_tick()
    assert res is None

@pytest.mark.asyncio
async def test_tick_loop_idle():
    loop = TickLoop()
    with patch.object(loop, "_should_act", return_value=TickActionType.IDLE):
        res = await loop.manual_tick()
        assert res is not None
        assert res.action == "idle"
        assert loop.state.consecutive_idle == 1

@pytest.mark.asyncio
async def test_tick_loop_sleep_transition():
    loop = TickLoop()
    loop.state.consecutive_idle = 9
    with patch.object(loop, "_should_act", return_value=TickActionType.IDLE):
        res = await loop.manual_tick()
        assert loop.state.is_sleeping is True
        
        # スリープ時のインターバル確認
        status = loop.get_status()
        assert status["current_interval"] == loop.sleep_interval

@pytest.mark.asyncio
async def test_tick_loop_sleep_wakeup():
    loop = TickLoop()
    loop.state.is_sleeping = True
    # SLEEP状態で IDLE 以外の時、解除されることを確認
    with patch.object(loop, "_should_act", return_value=TickActionType.COST_MONITOR):
        with patch.object(loop, "_execute_action", return_value={"data": {}, "alerts": []}):
            res = await loop.manual_tick()
            assert loop.state.is_sleeping is False
            assert loop.state.consecutive_idle == 0

@pytest.mark.asyncio
async def test_tick_loop_start_stop():
    loop = TickLoop(tick_interval=1)
    
    # すでに起動中の場合に警告が出ることをテスト
    loop.state.is_running = True
    with patch("agents.tick_loop.logger") as mock_logger:
        await loop.start()
        mock_logger.warning.assert_called_with("TickLoop は既に実行中です")
    loop.state.is_running = False

    # 正常なライフサイクルのテスト
    loop_task = asyncio.create_task(loop.start())
    
    # 起動されるまで少し待つ
    await asyncio.sleep(0.1)
    assert loop.state.is_running is True
    
    # 停止
    await loop.stop()
    await loop_task
    assert loop.state.is_running is False

@pytest.mark.asyncio
async def test_tick_loop_start_timeout_handling():
    loop = TickLoop(tick_interval=0.001)
    
    # 1回目のループでタイムアウトを発生させ、その後すぐに停止するようにする
    # _tick が呼ばれたら停止フラグをセットするように _tick をパッチ
    original_tick = loop._tick
    async def mock_tick():
        await original_tick()
        loop._stopped.set()
        
    with patch.object(loop, "_tick", side_effect=mock_tick):
        await loop.start()
        
    assert loop.state.is_running is False

@pytest.mark.asyncio
async def test_tick_loop_start_cancelled():
    loop = TickLoop(tick_interval=10)
    
    # startのループをCancelledErrorで抜けるテスト
    # loop._stopped.wait() をモックして CancelledError を発生させる
    with patch.object(loop._stopped, "wait", side_effect=asyncio.CancelledError):
        await loop.start()
    assert loop.state.is_running is False

@pytest.mark.asyncio
async def test_tick_loop_stop_with_cancelled_task():
    loop = TickLoop()
    
    # 実際のダミータスクオブジェクトを起動して、stop() 内での CancelledError をカバー
    async def dummy_task_fn():
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
            
    task = asyncio.create_task(dummy_task_fn())
    loop._task = task
    
    await loop.stop()

@pytest.mark.asyncio
async def test_tick_loop_blocking_budget_timeout():
    loop = TickLoop(blocking_budget=0.01)
    
    # _execute_action で遅延を発生させてタイムアウトさせる
    async def delayed_action(*args, **kwargs):
        await asyncio.sleep(0.2)
        return {"data": {}, "alerts": []}
        
    with patch.object(loop, "_should_act", return_value=TickActionType.COST_MONITOR):
        with patch.object(loop, "_execute_action", side_effect=delayed_action):
            res = await loop.manual_tick()
            assert res is not None
            assert "ブロッキング予算超越で強制中断" in res.alerts
            assert res.duration_seconds == 0.01

@pytest.mark.asyncio
async def test_action_dream_check_success():
    loop = TickLoop()
    mock_dream = MagicMock()
    mock_dream.should_dream = AsyncMock(return_value=True)
    
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.gather_count = 5
    mock_result.consolidation.new_facts = 2
    mock_result.duration_seconds = 1.5
    mock_dream.run_dream_cycle = AsyncMock(return_value=mock_result)

    with patch.dict("sys.modules", {"agents.dream_engine": MagicMock(dream_engine=mock_dream)}):
        # 正常にDreamEngineが動き、アラートが追加されるケース
        result = await loop._action_dream_check()
        assert "dream_success" in result["data"]
        assert result["data"]["dream_success"] is True
        assert len(result["alerts"]) == 1
        assert "Verified Facts追加" in result["alerts"][0]

@pytest.mark.asyncio
async def test_action_dream_check_not_should_dream():
    loop = TickLoop()
    mock_dream = MagicMock()
    mock_dream.should_dream = AsyncMock(return_value=False)
    
    with patch.dict("sys.modules", {"agents.dream_engine": MagicMock(dream_engine=mock_dream)}):
        result = await loop._action_dream_check()
        assert result["data"] == {}
        assert result["alerts"] == []

@pytest.mark.asyncio
async def test_action_dream_check_import_error():
    loop = TickLoop()
    
    # インポートエラー発生時のテスト
    with patch("builtins.__import__", side_effect=ImportError("mocked import error")):
        result = await loop._action_dream_check()
        assert "error" in result["data"]
        assert "mocked import error" in result["data"]["error"]

@pytest.mark.asyncio
async def test_action_cost_monitor_success():
    loop = TickLoop()
    mock_stats = {"remaining_pct": 5, "used_usd": 12.5}
    
    with patch.dict("sys.modules", {"usage_tracker.sdk_checker": MagicMock(get_usage_stats=MagicMock(return_value=mock_stats))}):
        # 10%未満でアラートが出るケース
        result = await loop._action_cost_monitor()
        assert result["data"]["remaining_pct"] == 5
        assert len(result["alerts"]) == 1
        assert "API使用量警告" in result["alerts"][0]

@pytest.mark.asyncio
async def test_action_cost_monitor_no_alert():
    loop = TickLoop()
    mock_stats = {"remaining_pct": 50, "used_usd": 5.0}
    
    with patch.dict("sys.modules", {"usage_tracker.sdk_checker": MagicMock(get_usage_stats=MagicMock(return_value=mock_stats))}):
        # 10%以上でアラートが出ないケース
        result = await loop._action_cost_monitor()
        assert result["data"]["remaining_pct"] == 50
        assert len(result["alerts"]) == 0

@pytest.mark.asyncio
async def test_action_cost_monitor_import_error():
    loop = TickLoop()
    with patch("builtins.__import__", side_effect=ImportError):
        result = await loop._action_cost_monitor()
        assert result == {"data": {}, "alerts": []}

@pytest.mark.asyncio
async def test_action_file_integrity_success():
    loop = TickLoop()
    
    # 全ての重要ファイルが存在する場合のテスト
    with patch.object(Path, "exists", return_value=True):
        result = await loop._action_file_integrity()
        assert result["data"]["checked_files"] == 5
        assert len(result["data"]["issues"]) == 0
        assert len(result["alerts"]) == 0

@pytest.mark.asyncio
async def test_action_file_integrity_missing():
    loop = TickLoop()
    
    # 全ての重要ファイルが欠損している場合のテスト
    with patch.object(Path, "exists", return_value=False):
        result = await loop._action_file_integrity()
        assert result["data"]["checked_files"] == 5
        assert len(result["data"]["issues"]) == 5
        assert len(result["alerts"]) == 5
        assert "重要ファイル欠損" in result["alerts"][0]

@pytest.mark.asyncio
async def test_action_quality_trend_success():
    loop = TickLoop()
    mock_store = MagicMock()
    mock_store.get_stats.return_value = {"facts_count": 42}
    
    with patch.dict("sys.modules", {"agents.memory.verified_facts": MagicMock(verified_facts_store=mock_store)}):
        result = await loop._action_quality_trend()
        assert result["data"]["verified_facts"]["facts_count"] == 42
        assert len(result["alerts"]) == 0

@pytest.mark.asyncio
async def test_action_quality_trend_import_error():
    loop = TickLoop()
    with patch("builtins.__import__", side_effect=ImportError):
        result = await loop._action_quality_trend()
        assert result == {"data": {}, "alerts": []}

@pytest.mark.asyncio
async def test_action_pipeline_knowledge_success(tmp_path):
    loop = TickLoop()
    knowledge_dir = tmp_path / "pipeline_knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    
    test_data = {
        "video": "test_video.mp4",
        "quality_score": 85,
        # **「測った」は値ではなく旗で表す**（R1.5-C4・12周目の指摘）。
        # ここが書くのは VERIFIED_FACTS.md（恒久的に残る「確かめた事実」）なので、
        # 旗が無ければ採点していないとみなす（fail-closed）
        "quality_scored": True,
        "total_corrections": 6,
        "retries_used": 1
    }
    
    knowledge_file = knowledge_dir / "run_001.json"
    knowledge_file.write_text(json.dumps(test_data), encoding="utf-8")
    
    mock_store = MagicMock()
    
    # Path.exists, Path.glob, shutil.move をパッチして、インプロセスで動くようにする
    original_exists = Path.exists
    def mock_exists(self):
        if "pipeline_knowledge" in str(self):
            return True
        return original_exists(self)
        
    def mock_glob(self, pattern):
        if "run_*.json" in pattern:
            return [knowledge_file]
        return []

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "glob", autospec=True, side_effect=mock_glob), \
         patch("agents.tick_loop.shutil.move") as mock_move, \
         patch("agents.memory.verified_facts.verified_facts_store", mock_store):
             
        result = await loop._action_pipeline_knowledge()
        
        assert result["data"]["processed"] == 1
        assert result["data"]["new_facts"] == 3
        assert mock_store.add_fact.call_count == 3

@pytest.mark.asyncio
async def test_action_pipeline_knowledge_invalid_json(tmp_path):
    loop = TickLoop()
    knowledge_dir = tmp_path / "pipeline_knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    
    knowledge_file = knowledge_dir / "run_invalid.json"
    knowledge_file.write_text("{invalid json", encoding="utf-8")
    
    original_exists = Path.exists
    def mock_exists(self):
        if "pipeline_knowledge" in str(self):
            return True
        return original_exists(self)
        
    def mock_glob(self, pattern):
        if "run_*.json" in pattern:
            return [knowledge_file]
        return []

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "glob", autospec=True, side_effect=mock_glob), \
         patch("agents.tick_loop.logger") as mock_logger:
        result = await loop._action_pipeline_knowledge()
        assert result["data"]["processed"] == 0
        assert result["data"]["new_facts"] == 0
        mock_logger.warning.assert_called_once()

@pytest.mark.asyncio
async def test_action_pipeline_knowledge_no_dir():
    loop = TickLoop()
    with patch.object(Path, "exists", return_value=False):
        result = await loop._action_pipeline_knowledge()
        assert result == {"data": {"processed": 0, "new_facts": 0}, "alerts": []}

@pytest.mark.asyncio
async def test_action_pipeline_knowledge_import_error(tmp_path):
    loop = TickLoop()
    knowledge_file = tmp_path / "run_001.json"
    knowledge_file.write_text(json.dumps({"video": "a.mp4", "quality_score": 90}), encoding="utf-8")

    original_exists = Path.exists
    def mock_exists(self):
        if "pipeline_knowledge" in str(self):
            return True
        return original_exists(self)
        
    def mock_glob(self, pattern):
        if "run_*.json" in pattern:
            return [knowledge_file]
        return []

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "glob", autospec=True, side_effect=mock_glob):

        # verified_facts import でエラーが起きた場合のキャッチ
        with patch("builtins.__import__", side_effect=ImportError), \
             patch("agents.tick_loop.shutil.move"):
            result = await loop._action_pipeline_knowledge()
            assert result["data"]["processed"] == 1
            assert result["data"]["new_facts"] == 0

@pytest.mark.asyncio
async def test_action_tdr_resolve_success():
    loop = TickLoop()
    
    # 負債のテストデータ
    debt_deleted = MagicMock(debt_id="TD-001", file_path="deleted_file.py", pattern="except Exception:")
    debt_fixed = MagicMock(debt_id="TD-002", file_path="exists.py", pattern="old_pattern")
    debt_open = MagicMock(debt_id="TD-003", file_path="exists.py", pattern="still_here")
    
    mock_store = MagicMock()
    mock_store.get_open_entries.return_value = [debt_deleted, debt_fixed, debt_open]
    
    with patch("agents.memory.technical_debt.technical_debt_store", mock_store):
        def mock_exists(self):
            if "deleted_file.py" in str(self):
                return False
            return True
            
        def mock_read_text(self, encoding=None):
            if "exists.py" in str(self):
                return "def test():\n    # still_here is present\n    pass"
            return ""
            
        with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
             patch.object(Path, "read_text", autospec=True, side_effect=mock_read_text):
             
            result = await loop._action_tdr_resolve()
            
            assert result["data"]["resolved_count"] == 2
            assert "TD-001" in result["data"]["resolved_ids"]
            assert "TD-002" in result["data"]["resolved_ids"]
            assert "TD-003" not in result["data"]["resolved_ids"]
            mock_store.resolve_debt.call_count == 2

@pytest.mark.asyncio
async def test_action_tdr_resolve_io_error():
    loop = TickLoop()
    debt = MagicMock(debt_id="TD-001", file_path="error.py", pattern="error")
    
    mock_store = MagicMock()
    mock_store.get_open_entries.return_value = [debt]
    
    with patch("agents.memory.technical_debt.technical_debt_store", mock_store):
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "read_text", side_effect=OSError("Read error")):
            result = await loop._action_tdr_resolve()
            assert result["data"]["resolved_count"] == 0
            assert mock_store.resolve_debt.call_count == 0

@pytest.mark.asyncio
async def test_action_tdr_resolve_import_error():
    loop = TickLoop()
    with patch("builtins.__import__", side_effect=ImportError("import failed")):
        result = await loop._action_tdr_resolve()
        assert "error" in result["data"]
        assert "import failed" in result["data"]["error"]

@pytest.mark.asyncio
async def test_should_act_priorities():
    loop = TickLoop()
    
    # 1. QUALITY_TREND (tick_id % 50 == 0)
    loop.state.total_ticks = 50
    res = await loop._should_act()
    assert res == TickActionType.QUALITY_TREND

    # 2. DREAM_CHECK (tick_id % 20 == 0)
    loop.state.total_ticks = 20
    mock_dream = MagicMock()
    mock_dream.should_dream = AsyncMock(return_value=True)
    with patch.dict("sys.modules", {"agents.dream_engine": MagicMock(dream_engine=mock_dream)}):
        res = await loop._should_act()
        assert res == TickActionType.DREAM_CHECK

    # 2.1. DREAM_CHECK で should_dream=False の時は、次にマッチする FILE_INTEGRITY (20 % 10 == 0) が返る
    loop.state.total_ticks = 20
    mock_dream.should_dream = AsyncMock(return_value=False)
    with patch.dict("sys.modules", {"agents.dream_engine": MagicMock(dream_engine=mock_dream)}):
        res = await loop._should_act()
        assert res == TickActionType.FILE_INTEGRITY

    # 2.2. DREAM_CHECK で例外が起きたら except を通って FILE_INTEGRITY (20 % 10 == 0) が返る
    loop.state.total_ticks = 20
    with patch("builtins.__import__", side_effect=ImportError):
        res = await loop._should_act()
        assert res == TickActionType.FILE_INTEGRITY

    # 3. TDR_RESOLVE (tick_id % 15 == 0)
    loop.state.total_ticks = 15
    res = await loop._should_act()
    assert res == TickActionType.TDR_RESOLVE

    # 4. FILE_INTEGRITY (tick_id % 10 == 0)
    loop.state.total_ticks = 10
    res = await loop._should_act()
    assert res == TickActionType.FILE_INTEGRITY

    # 5. COST_MONITOR (tick_id % 5 == 0)
    loop.state.total_ticks = 5
    res = await loop._should_act()
    assert res == TickActionType.COST_MONITOR

    # 6. PIPELINE_KNOWLEDGE (tick_id % 7 == 0)
    # ディレクトリが存在し、ファイルがあるケース
    loop.state.total_ticks = 7
    original_exists = Path.exists
    def mock_exists(self):
        if "pipeline_knowledge" in str(self):
            return True
        return original_exists(self)
        
    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "glob", return_value=[Path("run_001.json")]):
        res = await loop._should_act()
        assert res == TickActionType.PIPELINE_KNOWLEDGE

    # 6.1. PIPELINE_KNOWLEDGE でファイルが存在しないときは IDLE
    loop.state.total_ticks = 7
    with patch.object(Path, "exists", return_value=False):
        res = await loop._should_act()
        assert res == TickActionType.IDLE

    # 7. IDLE (tick_id = 1)
    loop.state.total_ticks = 1
    res = await loop._should_act()
    assert res == TickActionType.IDLE

@pytest.mark.asyncio
async def test_execute_action_invalid():
    loop = TickLoop()
    # 存在しないアクションの実行
    res = await loop._execute_action(MagicMock(value="invalid_action"))
    assert res == {"data": {}, "alerts": []}

@pytest.mark.asyncio
async def test_execute_action_success():
    loop = TickLoop()
    # 存在するアクション（例: COST_MONITOR）の実行と、ハンドラーが呼ばれて結果を返すことの検証（340行目をカバー）
    mock_stats = {"remaining_pct": 50, "used_usd": 5.0}
    with patch.dict("sys.modules", {"usage_tracker.sdk_checker": MagicMock(get_usage_stats=MagicMock(return_value=mock_stats))}):
        res = await loop._execute_action(TickActionType.COST_MONITOR)
        assert res["data"] == mock_stats

@pytest.mark.asyncio
async def test_tick_alert_logging():
    loop = TickLoop()
    # アラートがある場合のログ出力をテスト
    with patch.object(loop, "_should_act", return_value=TickActionType.COST_MONITOR), \
         patch.object(loop, "_execute_action", return_value={"data": {}, "alerts": ["Test Alert"]}):
        res = await loop.manual_tick()
        assert res is not None
        assert loop.state.alerts_sent == 1


# ============================================================
# 新規追加の極限テストケース（異常系・境界値・__main__ の網羅）
# ============================================================
import sys
import runpy

def test_main_block_kairos_mode():
    test_args = ["tick_loop.py", "--mode", "kairos"]
    def mock_run(coro):
        coro.close()
        return None
    with patch.object(sys, "argv", test_args), \
         patch("asyncio.run", side_effect=mock_run) as mock_run_spy:
        runpy.run_path("backend/agents/tick_loop.py", run_name="__main__")
        mock_run_spy.assert_called_once()

def test_main_block_kairos_mode_keyboard_interrupt():
    test_args = ["tick_loop.py", "--mode", "kairos"]
    def mock_run(coro):
        coro.close()
        raise KeyboardInterrupt
    with patch.object(sys, "argv", test_args), \
         patch("asyncio.run", side_effect=mock_run):
        runpy.run_path("backend/agents/tick_loop.py", run_name="__main__")

def test_main_block_flash_mode_success():
    test_args = ["tick_loop.py", "--mode", "flash", "--session-id", "test-session"]
    
    mock_hub = MagicMock()
    mock_hub.get_flash_session.return_value = {"status": "idle", "session_id": "test-session", "tasks_completed_in_session": 3}
    mock_hub.flash_session_start = MagicMock()
    mock_hub.flash_update_status = MagicMock()
    mock_hub.flash_session_end = MagicMock()
    
    mock_hub_class = MagicMock(return_value=mock_hub)
    mock_sleep = AsyncMock(side_effect=KeyboardInterrupt)
    
    mock_orchestrator = MagicMock()
    mock_orchestrator.OrchestrationHub = mock_hub_class
    
    def mock_run(coro):
        try:
            coro.send(None)
            raise KeyboardInterrupt
        finally:
            coro.close()
            
    with patch.object(sys, "argv", test_args), \
         patch.dict("sys.modules", {
             "agents.orchestration.orchestrator": mock_orchestrator,
             "backend.agents.orchestration.orchestrator": mock_orchestrator
         }), \
         patch("asyncio.sleep", mock_sleep), \
         patch("asyncio.run", side_effect=mock_run):
         
        runpy.run_path("backend/agents/tick_loop.py", run_name="__main__")
        
        mock_hub_class.assert_called_once()
        mock_hub.get_flash_session.assert_called()
        mock_hub.flash_session_start.assert_called_once_with("test-session")
        mock_hub.flash_update_status.assert_called_once_with(
            activity="running",
            step="Flash session heartbeat active",
            progress_pct=100
        )
        mock_hub.flash_session_end.assert_called_once_with("KeyboardInterrupt: ユーザーによる停止")

def test_main_block_flash_mode_errors():
    test_args = ["tick_loop.py", "--mode", "flash", "--session-id", "test-session"]
    
    mock_hub = MagicMock()
    mock_hub.get_flash_session.side_effect = [ValueError("session error"), ValueError("loop error")]
    mock_hub.flash_session_start = MagicMock()
    mock_hub.flash_update_status = MagicMock()
    mock_hub.flash_session_end = MagicMock(side_effect=RuntimeError("end error"))
    
    mock_hub_class = MagicMock(return_value=mock_hub)
    mock_sleep = AsyncMock(side_effect=KeyboardInterrupt)
    
    mock_orchestrator = MagicMock()
    mock_orchestrator.OrchestrationHub = mock_hub_class
    
    def mock_run(coro):
        try:
            coro.send(None)
            raise KeyboardInterrupt
        finally:
            coro.close()

    with patch.object(sys, "argv", test_args), \
         patch.dict("sys.modules", {
             "agents.orchestration.orchestrator": mock_orchestrator,
             "backend.agents.orchestration.orchestrator": mock_orchestrator
         }), \
         patch("asyncio.sleep", mock_sleep), \
         patch("asyncio.run", side_effect=mock_run):
         
        runpy.run_path("backend/agents/tick_loop.py", run_name="__main__")
        mock_hub.flash_session_end.assert_called_once()

@pytest.mark.asyncio
async def test_action_dream_check_attribute_error():
    loop = TickLoop()
    mock_dream = MagicMock()
    mock_dream.should_dream = AsyncMock(return_value=True)
    
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.consolidation = None
    mock_dream.run_dream_cycle = AsyncMock(return_value=mock_result)
    
    with patch.dict("sys.modules", {"agents.dream_engine": MagicMock(dream_engine=mock_dream)}):
        result = await loop._action_dream_check()
        assert "error" in result["data"]
        assert "NoneType" in result["data"]["error"]

@pytest.mark.asyncio
async def test_action_cost_monitor_missing_keys():
    loop = TickLoop()
    with patch.dict("sys.modules", {"usage_tracker.sdk_checker": MagicMock(get_usage_stats=MagicMock(return_value={}))}):
        result = await loop._action_cost_monitor()
        assert result["data"] == {}
        assert result["alerts"] == []

    with patch.dict("sys.modules", {"usage_tracker.sdk_checker": MagicMock(get_usage_stats=MagicMock(return_value={"remaining_pct": "invalid"}))}):
        result = await loop._action_cost_monitor()
        assert result == {"data": {"remaining_pct": "invalid"}, "alerts": []}

@pytest.mark.asyncio
async def test_action_pipeline_knowledge_non_dict_json(tmp_path):
    loop = TickLoop()
    knowledge_dir = tmp_path / "pipeline_knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    
    knowledge_file = knowledge_dir / "run_non_dict.json"
    knowledge_file.write_text("[1, 2, 3]", encoding="utf-8")
    
    original_exists = Path.exists
    def mock_exists(self):
        if "pipeline_knowledge" in str(self):
            return True
        return original_exists(self)
        
    def mock_glob(self, pattern):
        if "run_*.json" in pattern:
            return [knowledge_file]
        return []
        
    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "glob", autospec=True, side_effect=mock_glob), \
         patch("agents.tick_loop.shutil.move") as mock_move, \
         patch("agents.tick_loop.logger") as mock_logger:
         
        result = await loop._action_pipeline_knowledge()
        # リスト型JSONはパースに成功するが、.get()呼び出しでAttributeErrorが発生。
        # 内側の例外ハンドラでキャッチ・無視されるため、processed=1となり、shutil.move も呼ばれる。
        assert result["data"]["processed"] == 1
        assert result["data"]["new_facts"] == 0
        mock_logger.warning.assert_not_called()
        mock_move.assert_called_once()

@pytest.mark.asyncio
async def test_action_pipeline_knowledge_add_fact_exception(tmp_path):
    loop = TickLoop()
    knowledge_dir = tmp_path / "pipeline_knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    
    test_data = {"video": "test.mp4", "quality_score": 95}
    knowledge_file = knowledge_dir / "run_001.json"
    knowledge_file.write_text(json.dumps(test_data), encoding="utf-8")
    
    original_exists = Path.exists
    def mock_exists(self):
        if "pipeline_knowledge" in str(self):
            return True
        return original_exists(self)
        
    def mock_glob(self, pattern):
        if "run_*.json" in pattern:
            return [knowledge_file]
        return []
        
    mock_store = MagicMock()
    mock_store.add_fact.side_effect = RuntimeError("db error")
    
    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "glob", autospec=True, side_effect=mock_glob), \
         patch("agents.tick_loop.shutil.move") as mock_move, \
         patch("agents.memory.verified_facts.verified_facts_store", mock_store):
         
        result = await loop._action_pipeline_knowledge()
        assert result["data"]["processed"] == 1
        assert result["data"]["new_facts"] == 0
        mock_move.assert_called_once()

@pytest.mark.asyncio
async def test_action_pipeline_knowledge_shutil_move_error(tmp_path):
    loop = TickLoop()
    knowledge_dir = tmp_path / "pipeline_knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    
    test_data = {"video": "test.mp4", "quality_score": 95}
    knowledge_file = knowledge_dir / "run_001.json"
    knowledge_file.write_text(json.dumps(test_data), encoding="utf-8")
    
    original_exists = Path.exists
    def mock_exists(self):
        if "pipeline_knowledge" in str(self):
            return True
        return original_exists(self)
        
    def mock_glob(self, pattern):
        if "run_*.json" in pattern:
            return [knowledge_file]
        return []
        
    mock_store = MagicMock()
    
    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "glob", autospec=True, side_effect=mock_glob), \
         patch("agents.tick_loop.shutil.move", side_effect=OSError("move error")), \
         patch("agents.memory.verified_facts.verified_facts_store", mock_store), \
         patch("agents.tick_loop.logger") as mock_logger:
         
        result = await loop._action_pipeline_knowledge()
        assert result["data"]["processed"] == 0
        mock_logger.warning.assert_called_once()

@pytest.mark.asyncio
async def test_action_tdr_resolve_decode_error():
    loop = TickLoop()
    
    debt_err = MagicMock(debt_id="TD-ERR", file_path="bad_encoding.py", pattern="some_pattern")
    debt_ok = MagicMock(debt_id="TD-OK", file_path="good.py", pattern="old_pattern")
    
    mock_store = MagicMock()
    mock_store.get_open_entries.return_value = [debt_err, debt_ok]
    
    with patch("agents.memory.technical_debt.technical_debt_store", mock_store):
        def mock_exists(self):
            return True
            
        def mock_read_text(self, encoding=None):
            if "bad_encoding.py" in str(self):
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
            return "good content"
            
        with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
             patch.object(Path, "read_text", autospec=True, side_effect=mock_read_text):
             
            result = await loop._action_tdr_resolve()
            
            assert result["data"]["resolved_count"] == 1
            assert "TD-OK" in result["data"]["resolved_ids"]
            assert "TD-ERR" not in result["data"]["resolved_ids"]
            mock_store.resolve_debt.assert_called_once_with(
                debt_id="TD-OK",
                fixed_by="tick_loop_tdr_resolve",
                fix_evidence="コードからパターン 'old_pattern' が消滅したため解消"
            )


@pytest.mark.asyncio
async def test_tick_loop_foreground_active_toggle():
    loop = TickLoop()
    loop.set_foreground_active(True)
    res = await loop.manual_tick()
    assert res is None
    
    loop.set_foreground_active(False)
    with patch.object(loop, "_should_act", return_value=TickActionType.IDLE):
        res = await loop.manual_tick()
        assert res is not None
        assert res.action == "idle"


@pytest.mark.asyncio
async def test_action_tdr_resolve_unexpected_error():
    loop = TickLoop()
    debt = MagicMock(debt_id="TD-UNEXP", file_path="unexp.py", pattern="pattern")
    
    mock_store = MagicMock()
    mock_store.get_open_entries.return_value = [debt]
    
    with patch("agents.memory.technical_debt.technical_debt_store", mock_store):
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "read_text", side_effect=RuntimeError("Unexpected error")):
            result = await loop._action_tdr_resolve()
            assert "error" in result["data"]
            assert "Unexpected error" in result["data"]["error"]
            assert mock_store.resolve_debt.call_count == 0
