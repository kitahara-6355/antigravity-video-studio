import os
import json
import pytest
import asyncio
from unittest import mock
from pathlib import Path
from datetime import datetime, timedelta
from typing import Generator

# backend/agents にパスを通すために sys.path に追加されることを想定
from agents.dream_engine import (
    DreamEngine,
    Signal,
    ProjectState,
    ConsolidationResult,
    PruneResult,
    DreamResult,
)
from agents.memory.verified_facts import VerifiedFact, verified_facts_store

# テスト用のテンポラリパス設定
TEST_DIR = Path(__file__).parent / "temp_dream_engine"

@pytest.fixture(autouse=True)
def setup_teardown():
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    yield
    import shutil
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)

@pytest.fixture
def dream_engine(monkeypatch) -> DreamEngine:
    state_file = TEST_DIR / "dream_state.json"
    lock_file = TEST_DIR / ".dream_lock"
    
    # パスをモック
    monkeypatch.setattr("agents.dream_engine.DREAM_STATE_FILE", state_file)
    monkeypatch.setattr("agents.dream_engine.DREAM_LOCK_FILE", lock_file)
    monkeypatch.setattr("agents.dream_engine.DATA_DIR", TEST_DIR)
    
    engine = DreamEngine(interval_hours=24, min_sessions=5)
    return engine

# ============================================================
# 1. 初期設定と基本動作テスト
# ============================================================

def test_dream_engine_init(dream_engine):
    assert dream_engine.interval_hours == 24
    assert dream_engine.min_sessions == 5
    assert dream_engine.state_path == TEST_DIR / "dream_state.json"
    assert dream_engine.lock_path == TEST_DIR / ".dream_lock"

# ============================================================
# 2. Gate 判定テスト
# ============================================================

@pytest.mark.asyncio
async def test_should_dream_gate1_time(dream_engine):
    # 初期状態 (last_dream_at = None) -> Gate 1 パス
    # セッション数 = 5 -> Gate 2 パス
    dream_engine._state["sessions_since_last_dream"] = 5
    assert await dream_engine.should_dream() is True

    # last_dream_at が 12時間前 -> Gate 1 で引っかかる (elapsed < 24h)
    dream_engine._state["last_dream_at"] = (datetime.now() - timedelta(hours=12)).isoformat()
    assert await dream_engine.should_dream() is False

    # last_dream_at が 25時間前 -> Gate 1 パス
    dream_engine._state["last_dream_at"] = (datetime.now() - timedelta(hours=25)).isoformat()
    assert await dream_engine.should_dream() is True

@pytest.mark.asyncio
async def test_should_dream_gate2_sessions(dream_engine):
    # sessions_since_last_dream が不足している場合
    dream_engine._state["sessions_since_last_dream"] = 4
    assert await dream_engine.should_dream() is False

    # 十分なセッション数がある場合
    dream_engine._state["sessions_since_last_dream"] = 5
    assert await dream_engine.should_dream() is True

@pytest.mark.asyncio
async def test_should_dream_gate3_lock(dream_engine):
    dream_engine._state["sessions_since_last_dream"] = 5
    
    # ロックファイルが存在する場合
    dream_engine._acquire_lock()
    assert await dream_engine.should_dream() is False
    
    # ロックファイルを解除
    dream_engine._release_lock()
    assert await dream_engine.should_dream() is True

def test_increment_session_count(dream_engine):
    assert dream_engine._state["sessions_since_last_dream"] == 0
    dream_engine.increment_session_count()
    assert dream_engine._state["sessions_since_last_dream"] == 1
    
    # 再ロードして永続化を確認
    engine2 = DreamEngine(interval_hours=24, min_sessions=5)
    engine2.state_path = dream_engine.state_path
    engine2._state = engine2._load_state()
    assert engine2._state["sessions_since_last_dream"] == 1

# ============================================================
# 3. Dream サイクル実行テスト
# ============================================================

@pytest.mark.asyncio
async def test_run_dream_cycle_gate_failed(dream_engine):
    dream_engine._state["sessions_since_last_dream"] = 0
    result = await dream_engine.run_dream_cycle(force=False)
    assert result.success is False
    assert result.error == "ゲート条件未達成"

@pytest.mark.asyncio
async def test_run_dream_cycle_success(dream_engine, monkeypatch):
    dream_engine._state["sessions_since_last_dream"] = 5
    
    # 各フェーズをモック
    mock_orient = mock.AsyncMock(return_value=ProjectState(5, None, 0, 0, {}, []))
    mock_gather = mock.AsyncMock(return_value=[
        Signal("decision", "Test Decision", "test", datetime.now().isoformat(), 0.8)
    ])
    mock_consolidate = mock.AsyncMock(return_value=ConsolidationResult(1, 0, 0, [{"content": "Test Decision"}]))
    mock_prune = mock.AsyncMock(return_value=PruneResult(0, 0, 0.0))
    
    monkeypatch.setattr(dream_engine, "_orient", mock_orient)
    monkeypatch.setattr(dream_engine, "_gather_signal", mock_gather)
    monkeypatch.setattr(dream_engine, "_consolidate", mock_consolidate)
    monkeypatch.setattr(dream_engine, "_prune_and_index", mock_prune)
    
    result = await dream_engine.run_dream_cycle()
    
    assert result.success is True
    assert result.gather_count == 1
    assert result.consolidation.new_facts == 1
    assert dream_engine._state["dream_count"] == 1
    assert dream_engine._state["sessions_since_last_dream"] == 0
    assert not dream_engine.lock_path.exists()  # ロック解放の確認

@pytest.mark.asyncio
async def test_run_dream_cycle_exception(dream_engine, monkeypatch):
    # TD-280 の例外フォールバック境界検証
    dream_engine._state["sessions_since_last_dream"] = 5
    
    # _orient で例外をスローさせる
    mock_orient = mock.AsyncMock(side_effect=RuntimeError("Orient error"))
    monkeypatch.setattr(dream_engine, "_orient", mock_orient)
    
    result = await dream_engine.run_dream_cycle()
    
    assert result.success is False
    assert "Runtime Error" in result.error
    assert "Orient error" in result.error
    assert not dream_engine.lock_path.exists()  # ロックが確実に解放されていること

@pytest.mark.asyncio
async def test_run_dream_cycle_oserror(dream_engine, monkeypatch):
    dream_engine._state["sessions_since_last_dream"] = 5
    mock_orient = mock.AsyncMock(side_effect=OSError("Disk full"))
    monkeypatch.setattr(dream_engine, "_orient", mock_orient)
    
    result = await dream_engine.run_dream_cycle()
    assert result.success is False
    assert "File/JSON Error" in result.error
    assert "Disk full" in result.error
    assert not dream_engine.lock_path.exists()

@pytest.mark.asyncio
async def test_run_dream_cycle_valueerror(dream_engine, monkeypatch):
    dream_engine._state["sessions_since_last_dream"] = 5
    mock_orient = mock.AsyncMock(side_effect=ValueError("Invalid config format"))
    monkeypatch.setattr(dream_engine, "_orient", mock_orient)
    
    result = await dream_engine.run_dream_cycle()
    assert result.success is False
    assert "Value/Type Error" in result.error
    assert "Invalid config format" in result.error
    assert not dream_engine.lock_path.exists()

@pytest.mark.asyncio
async def test_run_dream_cycle_importerror(dream_engine, monkeypatch):
    dream_engine._state["sessions_since_last_dream"] = 5
    mock_orient = mock.AsyncMock(side_effect=ImportError("Cannot import foo"))
    monkeypatch.setattr(dream_engine, "_orient", mock_orient)
    
    result = await dream_engine.run_dream_cycle()
    assert result.success is False
    assert "Import/Attribute/Key Error" in result.error
    assert "Cannot import foo" in result.error
    assert not dream_engine.lock_path.exists()

# ============================================================
# 4. Phase 1: Orient テスト
# ============================================================

@pytest.mark.asyncio
async def test_orient(dream_engine, monkeypatch):
    # memory ディレクトリを作成
    mem_dir = TEST_DIR / "agents" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "test_memory.json").write_text("{}", encoding="utf-8")
    
    # verified_facts_store のモック
    mock_store = mock.MagicMock()
    mock_store.facts = [1, 2, 3]
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)
    
    # decision_logger と learning_loop をダミーモジュールとしてモック
    mock_dec_logger = mock.MagicMock()
    mock_dec_logger.decisions = [
        mock.MagicMock(learned=False),
        mock.MagicMock(learned=True),
    ]
    
    mock_learn_loop = mock.MagicMock()
    mock_learn_loop.get_preferences.return_value = {"key": "val"}
    
    import sys
    sys.modules["decision_logger"] = mock.MagicMock(decision_logger=mock_dec_logger)
    sys.modules["learning_loop"] = mock.MagicMock(learning_loop=mock_learn_loop)
    
    try:
        state = await dream_engine._orient()
        assert state.existing_facts_count == 3
        assert state.pending_decisions == 1
        assert state.active_patterns == {"key": "val"}
        assert "test_memory.json" in state.memory_files
    finally:
        sys.modules.pop("decision_logger", None)
        sys.modules.pop("learning_loop", None)

# ============================================================
# 5. Phase 2: Gather Signal テスト
# ============================================================

@pytest.mark.asyncio
async def test_gather_from_decisions(dream_engine, monkeypatch):
    mock_dec_logger = mock.MagicMock()
    decision_pending = mock.MagicMock(
        decision="reject",
        target_description="Reject rule",
        reason="bad pattern",
        iso_time="2026-05-24T12:00:00",
        decision_id="D1",
        target_type="rule",
        tags=["tag1"],
        learned=False
    )
    decision_learned = mock.MagicMock(learned=True)
    mock_dec_logger.decisions = [decision_pending, decision_learned]
    
    import sys
    sys.modules["decision_logger"] = mock.MagicMock(decision_logger=mock_dec_logger)
    
    try:
        signals = await dream_engine._gather_from_decisions()
        assert len(signals) == 1
        sig = signals[0]
        assert sig.signal_type == "decision"
        assert sig.importance == 0.8
        assert "[reject] Reject rule: bad pattern" in sig.content
    finally:
        sys.modules.pop("decision_logger", None)

@pytest.mark.asyncio
async def test_gather_from_learning(dream_engine, monkeypatch):
    mock_learn_loop = mock.MagicMock()
    
    proposal = mock.MagicMock(
        status="pending",
        proposal="Use UTF-8 Python always",
        created_at="2026-05-24T12:00:00"
    )
    mock_learn_loop.proposals = [proposal]
    
    pattern = mock.MagicMock(
        sample_count=4,
        confidence=0.8,
        preferred=["A", "B"],
        avoided=["C"]
    )
    mock_learn_loop.patterns = {"coding": pattern}
    
    # proposals / patterns を dict に変換する dataclass 互換性のため asdict をパッチするか mock_learn_loop に asdict を耐えさせる
    monkeypatch.setattr("agents.dream_engine.asdict", lambda x: {"mock_key": "mock_val"})
    
    import sys
    sys.modules["learning_loop"] = mock.MagicMock(learning_loop=mock_learn_loop)
    
    try:
        signals = await dream_engine._gather_from_learning()
        assert len(signals) == 2
        signals.sort(key=lambda s: s.importance, reverse=True)
        assert signals[0].importance == 0.9  # proposal
        assert signals[1].importance >= 0.6  # pattern
    finally:
        sys.modules.pop("learning_loop", None)

@pytest.mark.asyncio
async def test_gather_from_agent_memory_success(dream_engine):
    mem_dir = TEST_DIR / "agents" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    
    # 正常なJSONファイルを書き込み
    memory_data = {
        "lessons": [
            {"text": "Always write UTF-8 tests", "created_at": "2026-05-24T12:00:00"}
        ],
        "history": [
            {"outcome": "ERROR", "stance": "test", "feedback": "assertion failed", "timestamp": "2026-05-24T12:05:00"}
        ]
    }
    (mem_dir / "agent_x.json").write_text(json.dumps(memory_data), encoding="utf-8")
    
    signals = await dream_engine._gather_from_agent_memory()
    assert len(signals) == 2
    assert any(s.signal_type == "lesson" and "Always write UTF-8 tests" in s.content for s in signals)
    assert any(s.signal_type == "error_resolution" and "[ERROR]" in s.content for s in signals)

@pytest.mark.asyncio
async def test_gather_from_agent_memory_exceptions(dream_engine):
    # TD-281 の例外境界検証
    mem_dir = TEST_DIR / "agents" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. 壊れたJSON (JSONDecodeError を誘発)
    (mem_dir / "broken.json").write_text("{broken json", encoding="utf-8")
    
    # 2. 読めないファイル (PermissionError -> OSError を誘発)
    unreadable = mem_dir / "unreadable.json"
    unreadable.write_text("{}", encoding="utf-8")
    
    # read_text をモックして PermissionError を投げさせる
    with mock.patch("builtins.open", mock.mock_open()) as mock_file:
        mock_file.side_effect = PermissionError("Permission denied")
        
        # 例外をキャッチして警告ログを出力し、処理がスキップされて正常終了することを確認
        signals = await dream_engine._gather_from_agent_memory()
        # 壊れたファイルや読み込めないファイルは無視されるためシグナルは0件
        assert len(signals) == 0

# ============================================================
# 6. Phase 3: Consolidate テスト
# ============================================================

@pytest.mark.asyncio
async def test_consolidate(dream_engine, monkeypatch):
    mock_store = mock.MagicMock()
    mock_store.add_fact.side_effect = [
        VerifiedFact(fact_id="F1", category="preference", content="Pref Fact", evidence="evidence", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=0.8),
        None, # 2つ目は追加失敗 (既に存在する等)
    ]
    # 矛盾のモック
    fact1 = VerifiedFact(fact_id="F1", category="preference", content="Pref Fact 1", evidence="evidence", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=0.6)
    fact2 = VerifiedFact(fact_id="F2", category="preference", content="Pref Fact 2", evidence="evidence", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=0.8)
    mock_store.get_contradictions.return_value = [(fact1, fact2)]
    
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)
    
    signals = [
        Signal("decision", "Pref Fact", "test", "2026-05-24T12:00:00", 0.8),
        Signal("decision", "Low Importance", "test", "2026-05-24T12:00:00", 0.4),  # スキップされる
        Signal("lesson", "Lesson Fact", "test", "2026-05-24T12:00:00", 0.7),
    ]
    
    result = await dream_engine._consolidate(signals)
    
    assert result.new_facts == 1
    assert result.contradictions_resolved == 1
    mock_store.remove_fact.assert_called_once_with("F1")  # confidence が低い方 (0.6) が削除されること

# ============================================================
# 7. Phase 4: Prune and Index テスト
# ============================================================

@pytest.mark.asyncio
async def test_prune_and_index(dream_engine, monkeypatch):
    mock_store = mock.MagicMock()
    mock_store.prune_stale_facts.return_value = 2
    mock_store.get_stats.return_value = {
        "total_facts": 10,
        "markdown_lines": 50,
        "markdown_size_kb": 2.5,
    }
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)
    
    mock_dec_logger = mock.MagicMock()
    d1 = mock.MagicMock(learned=False)
    d2 = mock.MagicMock(learned=True)
    mock_dec_logger.decisions = [d1, d2]
    
    import sys
    sys.modules["decision_logger"] = mock.MagicMock(decision_logger=mock_dec_logger)
    
    try:
        result = await dream_engine._prune_and_index()
        assert result.entries_removed == 2
        assert result.entries_summarized == 1
        assert d1.learned is True
        mock_dec_logger._save.assert_called_once()
    finally:
        sys.modules.pop("decision_logger", None)

# ============================================================
# 8. Phase 完了時の progress 圧縮テスト (Sprint B-2)
# ============================================================

def test_auto_compress_phase_progress_empty(dream_engine, monkeypatch):
    mock_store = mock.MagicMock()
    mock_store.get_facts_by_category.return_value = []
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)
    
    result = dream_engine._auto_compress_phase_progress(completed_phase="Phase 1")
    assert result["original_count"] == 0
    assert "progressファクトなし" in result["summary"]

def test_auto_compress_phase_progress_success(dream_engine, monkeypatch):
    # progress カテゴリのファクトを準備
    f1 = VerifiedFact(fact_id="F1", category="progress", content="Phase 1 Sprint 1.1: 5/5 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    f2 = VerifiedFact(fact_id="F2", category="progress", content="Phase 1 Sprint 1.2: 10/10 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    f3 = VerifiedFact(fact_id="F3", category="progress", content="Phase 2 Sprint 2.1: 8/8 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    
    mock_store = mock.MagicMock()
    mock_store.get_facts_by_category.return_value = [f1, f2, f3]
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)
    
    # 1. dry_run のテスト (Phase 1 圧縮)
    result_dry = dream_engine._auto_compress_phase_progress(completed_phase="Phase 1", dry_run=True)
    assert result_dry["original_count"] == 2
    assert result_dry["compressed_to"] == 1
    assert result_dry["dry_run"] is True
    assert "Phase 1完了" in result_dry["summary"]
    assert "テスト計15件PASS" in result_dry["summary"]
    mock_store.remove_fact.assert_not_called()
    mock_store.add_fact.assert_not_called()
    
    # 2. 本番のテスト (Phase 1 圧縮)
    result_real = dream_engine._auto_compress_phase_progress(completed_phase="Phase 1", dry_run=False)
    assert result_real["original_count"] == 2
    assert result_real["compressed_to"] == 1
    assert result_real["dry_run"] is False
    assert mock_store.remove_fact.call_count == 2
    mock_store.remove_fact.assert_any_call("F1")
    mock_store.remove_fact.assert_any_call("F2")
    mock_store.add_fact.assert_called_once_with(
        category="progress",
        content=result_real["summary"],
        evidence=mock.ANY,
        source="dream",
        confidence=1.0,
        tags=["auto-compressed"]
    )

def test_auto_compress_phase_progress_all(dream_engine, monkeypatch):
    f1 = VerifiedFact(fact_id="F1", category="progress", content="Phase 1 Sprint 1.1: 5/5 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    f2 = VerifiedFact(fact_id="F2", category="progress", content="Phase 1 Sprint 1.2: 10/10 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    
    mock_store = mock.MagicMock()
    mock_store.get_facts_by_category.return_value = [f1, f2]
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)
    
    # completed_phase を指定しない場合、自動検出して圧縮
    result = dream_engine._auto_compress_phase_progress(completed_phase="", dry_run=False)
    assert result["phase"] == "Phase 1"
    assert result["original_count"] == 2

# ============================================================
# 9. 例外・境界値の頑健性テスト (TD-188, TD-282 のカバレッジ)
# ============================================================

def test_load_state_exceptions(dream_engine):
    # TD-188: 状態ファイル読み込み時の JSONDecodeError & OSError のハンドリング検証
    
    # 1. JSONDecodeError (壊れたJSONファイル)
    dream_engine.state_path.write_text("invalid json", encoding="utf-8")
    state = dream_engine._load_state()
    assert state["last_dream_at"] is None
    assert state["sessions_since_last_dream"] == 0

    # 2. OSError (PermissionError) を投げるように patch
    with mock.patch("builtins.open", mock.mock_open()) as mock_file:
        mock_file.side_effect = PermissionError("Permission denied")
        state = dream_engine._load_state()
        assert state["last_dream_at"] is None
        assert state["sessions_since_last_dream"] == 0

def test_save_state_exception(dream_engine):
    # TD-282: 状態ファイル書き込み時の OSError のハンドリング検証
    # open 組み込み関数をモックして OSError を発生させる
    with mock.patch("builtins.open", mock.mock_open()) as mock_file:
        mock_file.side_effect = OSError("Disk full")
        try:
            dream_engine._save_state()
        except Exception as e:
            pytest.fail(f"save_state raised exception {e} instead of catching it")


# ============================================================
# 10. カバレッジ補強用追加テスト
# ============================================================

@pytest.mark.asyncio
async def test_consolidate_else_branch(dream_engine, monkeypatch):
    # 509行目の else ブロックの検証: fact1.confidence >= fact2.confidence
    mock_store = mock.MagicMock()
    mock_store.add_fact.return_value = None
    
    # fact1 の方が confidence が高い -> fact2 (F2) が削除されるべき
    fact1 = VerifiedFact(fact_id="F1", category="preference", content="Pref Fact 1", evidence="evidence", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=0.9)
    fact2 = VerifiedFact(fact_id="F2", category="preference", content="Pref Fact 2", evidence="evidence", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=0.6)
    mock_store.get_contradictions.return_value = [(fact1, fact2)]
    
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)
    
    signals = [
        Signal("decision", "Pref Fact", "test", "2026-05-24T12:00:00", 0.8),
    ]
    
    result = await dream_engine._consolidate(signals)
    assert result.contradictions_resolved == 1
    mock_store.remove_fact.assert_called_once_with("F2")

def test_auto_compress_phase_progress_milestone_and_unknown(dream_engine, monkeypatch):
    # 634-638行目の milestone_match / Unknown 判定の検証
    f1 = VerifiedFact(fact_id="F1", category="progress", content="M3.2 Sprint 1: 5/5 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    f2 = VerifiedFact(fact_id="F2", category="progress", content="M3.2 Sprint 2: 10/10 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    f3 = VerifiedFact(fact_id="F3", category="progress", content="No phase pattern fact 1", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    f4 = VerifiedFact(fact_id="F4", category="progress", content="No phase pattern fact 2", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)

    mock_store = mock.MagicMock()
    mock_store.get_facts_by_category.return_value = [f1, f2, f3, f4]
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)

    # 1. "M3.2" パターン -> "Phase 3" として処理される
    result_m = dream_engine._auto_compress_phase_progress(completed_phase="Phase 3", dry_run=True)
    assert result_m["original_count"] == 2
    assert "Phase 3完了" in result_m["summary"]

    # 2. パターンマッチしない -> "Unknown" として処理される
    result_u = dream_engine._auto_compress_phase_progress(completed_phase="Unknown", dry_run=True)
    assert result_u["original_count"] == 2
    assert "Unknown完了" in result_u["summary"]

def test_auto_compress_phase_progress_multiple_phases(dream_engine, monkeypatch):
    # 734-736行目の複数Phase圧縮の検証 (completed_phase="" で複数グループが圧縮対象になる場合)
    f1 = VerifiedFact(fact_id="F1", category="progress", content="Phase 1 Sprint 1.1: 5/5 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    f2 = VerifiedFact(fact_id="F2", category="progress", content="Phase 1 Sprint 1.2: 10/10 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    f3 = VerifiedFact(fact_id="F3", category="progress", content="Phase 2 Sprint 2.1: 8/8 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    f4 = VerifiedFact(fact_id="F4", category="progress", content="Phase 2 Sprint 2.2: 12/12 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)

    mock_store = mock.MagicMock()
    mock_store.get_facts_by_category.return_value = [f1, f2, f3, f4]
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)

    result = dream_engine._auto_compress_phase_progress(completed_phase="", dry_run=True)
    assert result["original_count"] == 4
    assert result["compressed_to"] == 2
    assert "2Phase圧縮" in result["summary"]

@pytest.mark.asyncio
async def test_import_errors_handling(dream_engine, monkeypatch):
    # ImportError を意図的に発生させて、各フォールバックルートを通す
    # sys.modules から decision_logger と learning_loop を隠蔽する
    import sys
    
    # 元々の状態を保存
    orig_dec = sys.modules.get("decision_logger")
    orig_learn = sys.modules.get("learning_loop")
    
    # インポート時に ImportError または Exception を発生させるためのダミー
    # dream_engine 内の "import decision_logger" を失敗させるため、sys.modules をクリア
    sys.modules["decision_logger"] = None
    sys.modules["learning_loop"] = None
    
    try:
        # 1. _orient でのインポートエラー確認 (298-299, 306-307)
        state = await dream_engine._orient()
        assert state.pending_decisions == 0
        assert state.active_patterns == {}
        
        # 2. _gather_from_decisions / _gather_from_learning でのインポートエラー確認 (377-378, 414-415)
        dec_signals = await dream_engine._gather_from_decisions()
        assert len(dec_signals) == 0
        
        learn_signals = await dream_engine._gather_from_learning()
        assert len(learn_signals) == 0
        
        # 3. _prune_and_index でのインポートエラー確認 (558-559)
        mock_store = mock.MagicMock()
        monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)
        
        prune_res = await dream_engine._prune_and_index()
        assert prune_res.entries_summarized == 0
        
    finally:
        # sys.modules の復元
        if orig_dec is not None:
            sys.modules["decision_logger"] = orig_dec
        else:
            sys.modules.pop("decision_logger", None)
            
        if orig_learn is not None:
            sys.modules["learning_loop"] = orig_learn
        else:
            sys.modules.pop("learning_loop", None)


# ============================================================
# 11. 100% カバレッジ達成用追加テスト
# ============================================================

@pytest.mark.asyncio
async def test_gather_signal_full(dream_engine, monkeypatch):
    # _gather_signal 自体のカバレッジ (339-354) を通すためのテスト
    mock_dec = mock.AsyncMock(return_value=[
        Signal("decision", "Dec1", "src", "2026-05-24", 0.5)
    ])
    mock_learn = mock.AsyncMock(return_value=[
        Signal("pattern", "Learn1", "src", "2026-05-24", 0.9)
    ])
    mock_mem = mock.AsyncMock(return_value=[
        Signal("lesson", "Mem1", "src", "2026-05-24", 0.7)
    ])

    monkeypatch.setattr(dream_engine, "_gather_from_decisions", mock_dec)
    monkeypatch.setattr(dream_engine, "_gather_from_learning", mock_learn)
    monkeypatch.setattr(dream_engine, "_gather_from_agent_memory", mock_mem)

    signals = await dream_engine._gather_signal()
    assert len(signals) == 3
    # 重要度で降順ソートされていることを確認 (0.9 -> 0.7 -> 0.5)
    assert signals[0].importance == 0.9
    assert signals[1].importance == 0.7
    assert signals[2].importance == 0.5

@pytest.mark.asyncio
async def test_gather_from_agent_memory_dir_not_exists(dream_engine, monkeypatch):
    # 423行目: memory_dir が存在しない場合
    monkeypatch.setattr("agents.dream_engine.DATA_DIR", TEST_DIR / "non_existent_dir")
    signals = await dream_engine._gather_from_agent_memory()
    assert len(signals) == 0

@pytest.mark.asyncio
async def test_gather_from_agent_memory_skip_files(dream_engine):
    # 427行目: verified_facts_index.json や dream_state.json がスキップされること
    mem_dir = TEST_DIR / "agents" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)

    # スキップ対象 of ファイル名で壊れたJSONを書き込む (もし処理されたら JSONDecodeError 等で警告ログが出るか、処理されてしまう)
    (mem_dir / "verified_facts_index.json").write_text("broken json", encoding="utf-8")
    (mem_dir / "dream_state.json").write_text("broken json", encoding="utf-8")
    (mem_dir / "normal.json").write_text(json.dumps({"lessons": [{"text": "Valid Lesson"}]}), encoding="utf-8")

    signals = await dream_engine._gather_from_agent_memory()
    assert len(signals) == 1
    assert signals[0].content == "Valid Lesson"

def test_auto_compress_no_target_phases(dream_engine, monkeypatch):
    # 654行目: target_phases が空の場合
    f1 = VerifiedFact(fact_id="F1", category="progress", content="Phase 1 Sprint 1.1: 5/5 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    
    mock_store = mock.MagicMock()
    mock_store.get_facts_by_category.return_value = [f1]  # 各グループ1件以下しかないため圧縮対象なし
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)

    result = dream_engine._auto_compress_phase_progress(completed_phase="", dry_run=True)
    assert result["original_count"] == 1
    assert "圧縮対象なし" in result["summary"]

def test_auto_compress_continue_on_single_fact_group(dream_engine, monkeypatch):
    # 667行目: 1件しかないグループは continue されてスキップされること
    # Phase 1 は 1件 (スキップ対象), Phase 2 は 2件 (圧縮対象)
    f1 = VerifiedFact(fact_id="F1", category="progress", content="Phase 1 Sprint 1.1: 5/5 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    f2 = VerifiedFact(fact_id="F2", category="progress", content="Phase 2 Sprint 2.1: 8/8 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)
    f3 = VerifiedFact(fact_id="F3", category="progress", content="Phase 2 Sprint 2.2: 10/10 テストPASS", evidence="ev", created_at="2026-05-24", last_verified_at="2026-05-24", confidence=1.0)

    mock_store = mock.MagicMock()
    mock_store.get_facts_by_category.return_value = [f1, f2, f3]
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)

    result = dream_engine._auto_compress_phase_progress(completed_phase="", dry_run=True)
    # 結果として Phase 2 のみが圧縮される
    assert result["phase"] == "Phase 2"
    assert result["original_count"] == 2


# ============================================================
# 12. 改善されたエラーハンドリング（予期せぬ例外とログ出力）の検証テスト
# ============================================================

@pytest.mark.asyncio
async def test_gather_from_decisions_unexpected_exception(dream_engine, monkeypatch):
    # decision_logger モジュールは存在するが、処理中に例外が発生するケース
    mock_dec_logger = mock.MagicMock()
    # decisions プロパティへのアクセスで意図的に TypeError を発生させる
    type(mock_dec_logger).decisions = mock.PropertyMock(side_effect=TypeError("Unexpected database type error"))
    
    import sys
    sys.modules["decision_logger"] = mock.MagicMock(decision_logger=mock_dec_logger)
    
    # logger.error が exc_info=True を伴って呼び出されることを監視
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    try:
        signals = await dream_engine._gather_from_decisions()
        # 例外が発生しても、空リストを返して処理が継続されること
        assert signals == []
        
        # logger.error が呼び出され、exc_info=True が指定されていること
        mock_logger.error.assert_called_once()
        args, kwargs = mock_logger.error.call_args
        assert "Unexpected database type error" in args[0]
        assert kwargs.get("exc_info") is True
    finally:
        sys.modules.pop("decision_logger", None)

@pytest.mark.asyncio
async def test_gather_from_learning_unexpected_exception(dream_engine, monkeypatch):
    # learning_loop モジュールは存在するが、処理中に例外が発生するケース
    mock_learn_loop = mock.MagicMock()
    type(mock_learn_loop).proposals = mock.PropertyMock(side_effect=ValueError("Unexpected config corruption"))
    
    import sys
    sys.modules["learning_loop"] = mock.MagicMock(learning_loop=mock_learn_loop)
    
    # logger.error が exc_info=True を伴って呼び出されることを監視
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    try:
        signals = await dream_engine._gather_from_learning()
        assert signals == []
        
        mock_logger.error.assert_called_once()
        args, kwargs = mock_logger.error.call_args
        assert "Unexpected config corruption" in args[0]
        assert kwargs.get("exc_info") is True
    finally:
        sys.modules.pop("learning_loop", None)

@pytest.mark.asyncio
async def test_prune_and_index_unexpected_exception(dream_engine, monkeypatch):
    # decision_logger._save() で例外が発生した際、警告ログを出力し、かつ全体の処理が失敗しないことの検証
    mock_store = mock.MagicMock()
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)
    
    mock_dec_logger = mock.MagicMock()
    mock_dec_logger.decisions = []
    # _save() で OSError を投げさせる
    mock_dec_logger._save.side_effect = OSError("Write permission denied")
    
    import sys
    sys.modules["decision_logger"] = mock.MagicMock(decision_logger=mock_dec_logger)
    
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    try:
        result = await dream_engine._prune_and_index()
        # エラーが発生しても、prune_resultが正常に返ること
        assert result.entries_summarized == 0
        
        # logger.warning が呼び出され、exc_info=True が指定されていること
        mock_logger.warning.assert_called_once()
        args, kwargs = mock_logger.warning.call_args
        assert "Write permission denied" in args[0]
        assert kwargs.get("exc_info") is True
    finally:
        sys.modules.pop("decision_logger", None)


# ============================================================
# 13. 追加の例外型（KeyErrorなど）に対する検証テスト (L2)
# ============================================================

@pytest.mark.asyncio
async def test_gather_from_decisions_keyerror(dream_engine, monkeypatch):
    mock_dec_logger = mock.MagicMock()
    type(mock_dec_logger).decisions = mock.PropertyMock(side_effect=KeyError("Missing decision dictionary key"))
    
    import sys
    sys.modules["decision_logger"] = mock.MagicMock(decision_logger=mock_dec_logger)
    
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    try:
        signals = await dream_engine._gather_from_decisions()
        assert signals == []
        mock_logger.error.assert_called_once()
        args, kwargs = mock_logger.error.call_args
        assert "Missing decision dictionary key" in args[0]
        assert kwargs.get("exc_info") is True
    finally:
        sys.modules.pop("decision_logger", None)

@pytest.mark.asyncio
async def test_gather_from_learning_keyerror(dream_engine, monkeypatch):
    mock_learn_loop = mock.MagicMock()
    type(mock_learn_loop).proposals = mock.PropertyMock(side_effect=KeyError("Missing learning loop key"))
    
    import sys
    sys.modules["learning_loop"] = mock.MagicMock(learning_loop=mock_learn_loop)
    
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    try:
        signals = await dream_engine._gather_from_learning()
        assert signals == []
        mock_logger.error.assert_called_once()
        args, kwargs = mock_logger.error.call_args
        assert "Missing learning loop key" in args[0]
        assert kwargs.get("exc_info") is True
    finally:
        sys.modules.pop("learning_loop", None)

@pytest.mark.asyncio
async def test_prune_and_index_keyerror(dream_engine, monkeypatch):
    mock_store = mock.MagicMock()
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)
    
    mock_dec_logger = mock.MagicMock()
    mock_dec_logger.decisions = []
    mock_dec_logger._save.side_effect = KeyError("Save config missing key")
    
    import sys
    sys.modules["decision_logger"] = mock.MagicMock(decision_logger=mock_dec_logger)
    
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    try:
        result = await dream_engine._prune_and_index()
        assert result.entries_summarized == 0
        mock_logger.warning.assert_called_once()
        args, kwargs = mock_logger.warning.call_args
        assert "Save config missing key" in args[0]
        assert kwargs.get("exc_info") is True
    finally:
        sys.modules.pop("decision_logger", None)


# ============================================================
# 14. 新規追加された例外ハンドリング（安全ネット）の検証テスト
# ============================================================

@pytest.mark.asyncio
async def test_orient_iterdir_oserror(dream_engine, monkeypatch):
    # memory ディレクトリを確実に作成しておく
    mem_dir = TEST_DIR / "agents" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    
    # iterdir() で OSError を投げさせる
    mock_iterdir = mock.MagicMock(side_effect=OSError("Permission denied"))
    monkeypatch.setattr(Path, "iterdir", mock_iterdir)
    
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    state = await dream_engine._orient()
    assert state.memory_files == []
    mock_logger.warning.assert_called_once()
    assert "Memory directory scan failed" in mock_logger.warning.call_args[0][0]

@pytest.mark.asyncio
async def test_orient_decision_logger_unexpected_exception(dream_engine, monkeypatch):
    mock_dec_logger = mock.MagicMock()
    type(mock_dec_logger).decisions = mock.PropertyMock(side_effect=ValueError("Unexpected orient value error"))
    
    import sys
    sys.modules["decision_logger"] = mock.MagicMock(decision_logger=mock_dec_logger)
    
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    try:
        state = await dream_engine._orient()
        assert state.pending_decisions == 0
        mock_logger.warning.assert_called_once()
        assert "Error accessing decision_logger in Orient" in mock_logger.warning.call_args[0][0]
    finally:
        sys.modules.pop("decision_logger", None)

@pytest.mark.asyncio
async def test_orient_learning_loop_unexpected_exception(dream_engine, monkeypatch):
    mock_learn_loop = mock.MagicMock()
    mock_learn_loop.get_preferences.side_effect = TypeError("Unexpected orient type error")
    
    import sys
    sys.modules["learning_loop"] = mock.MagicMock(learning_loop=mock_learn_loop)
    
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    try:
        state = await dream_engine._orient()
        assert state.active_patterns == {}
        mock_logger.warning.assert_called_once()
        assert "Error accessing learning_loop in Orient" in mock_logger.warning.call_args[0][0]
    finally:
        sys.modules.pop("learning_loop", None)

@pytest.mark.asyncio
async def test_run_dream_cycle_unexpected_exception(dream_engine, monkeypatch):
    dream_engine._state["sessions_since_last_dream"] = 5
    
    # _orient で予期せぬ例外を発生させる
    mock_orient = mock.AsyncMock(side_effect=Exception("Severe system crash"))
    monkeypatch.setattr(dream_engine, "_orient", mock_orient)
    
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    result = await dream_engine.run_dream_cycle()
    assert result.success is False
    assert "Unexpected Error" in result.error
    assert "Severe system crash" in result.error
    mock_logger.error.assert_called_once()
    assert "予期せぬエラー" in mock_logger.error.call_args[0][0]
    assert not dream_engine.lock_path.exists()

@pytest.mark.asyncio
async def test_consolidate_add_fact_oserror_and_exception(dream_engine, monkeypatch):
    mock_store = mock.MagicMock()
    # 1つ目は OSError、2つ目は具体的な RuntimeError、3つ目は正常（None = 追加失敗扱い）
    mock_store.add_fact.side_effect = [
        OSError("Disk write error"),
        RuntimeError("DB crash"),
        None
    ]
    mock_store.get_contradictions.return_value = []
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)
    
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    signals = [
        Signal("decision", "Pref 1", "test", "2026-05-24", 0.8),
        Signal("decision", "Pref 2", "test", "2026-05-24", 0.8),
        Signal("decision", "Pref 3", "test", "2026-05-24", 0.8),
    ]
    
    result = await dream_engine._consolidate(signals)
    assert result.new_facts == 0
    # それぞれのエラーがキャッチされてログ出力されていること
    assert mock_logger.error.call_count == 2
    log_messages = [call[0][0] for call in mock_logger.error.call_args_list]
    assert any("ディスクI/Oエラー" in msg for msg in log_messages)
    assert any("予期せぬエラー" in msg for msg in log_messages)

@pytest.mark.asyncio
async def test_consolidate_contradictions_oserror_and_exception(dream_engine, monkeypatch):
    mock_store = mock.MagicMock()
    mock_store.add_fact.return_value = None
    
    # 1回目は OSError、2回目は具体的 RuntimeError を発生させる
    mock_store.get_contradictions.side_effect = [
        OSError("Read error"),
        RuntimeError("XML parse error")
    ]
    monkeypatch.setattr("agents.memory.verified_facts.verified_facts_store", mock_store)
    
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    signals = [Signal("decision", "Pref 1", "test", "2026-05-24", 0.8)]
    
    # 1回目の検証 (OSError)
    result1 = await dream_engine._consolidate(signals)
    assert result1.contradictions_resolved == 0
    assert any("ディスクI/Oエラー" in call[0][0] for call in mock_logger.error.call_args_list)
    
    mock_logger.reset_mock()
    
    # 2回目の検証 (Exception)
    result2 = await dream_engine._consolidate(signals)
    assert result2.contradictions_resolved == 0
    assert any("予期せぬエラー" in call[0][0] for call in mock_logger.error.call_args_list)

@pytest.mark.asyncio
async def test_consolidate_overall_exception(dream_engine, monkeypatch):
    # 処理全体で例外が発生するケース
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)
    
    # signals にアクセスした段階で例外を発生させる
    class BrokenList(list):
        def __iter__(self):
            raise RuntimeError("Corrupted list iterator")
            
    signals = BrokenList([Signal("decision", "Pref 1", "test", "2026-05-24", 0.8)])
    
    result = await dream_engine._consolidate(signals)
    assert result.new_facts == 0
    assert result.contradictions_resolved == 0
    assert any("全体で予期せぬエラーが発生しました" in call[0][0] for call in mock_logger.error.call_args_list)

@pytest.mark.asyncio
async def test_orient_specific_exceptions(dream_engine, monkeypatch):
    import sys

    # 警告ログのモック
    mock_logger = mock.MagicMock()
    monkeypatch.setattr("agents.dream_engine.logger", mock_logger)

    # decision_logger へのアクセスで AttributeError を発生させるダミークラス
    class MockDecisionLogger:
        @property
        def decisions(self):
            raise AttributeError("Mock AttributeError")
            
    mock_decision_logger_instance = MockDecisionLogger()
    mock_decision_module = mock.MagicMock()
    mock_decision_module.decision_logger = mock_decision_logger_instance
    monkeypatch.setitem(sys.modules, "decision_logger", mock_decision_module)

    # learning_loop 関連もTypeErrorを発生させるダミークラス
    class MockLearningLoop:
        def get_preferences(self):
            raise TypeError("Mock TypeError")
            
    mock_learning_loop_instance = MockLearningLoop()
    mock_learning_module = mock.MagicMock()
    mock_learning_module.learning_loop = mock_learning_loop_instance
    monkeypatch.setitem(sys.modules, "learning_loop", mock_learning_module)

    # _orient を実行
    state = await dream_engine._orient()
    
    # 処理がクラッシュせず正常完了すること
    assert state.pending_decisions == 0
    assert state.active_patterns == {}
    
    # 警告ログが出力されていること
    warning_messages = [call[0][0] for call in mock_logger.warning.call_args_list]
    assert any("Error accessing decision_logger in Orient" in msg for msg in warning_messages)

    assert any("Error accessing learning_loop in Orient" in msg for msg in warning_messages)







