"""
Sprint 4.2.4 是正テスト — C-01〜C-05

設計書: sprint_424_correction_design.md §3
テスト S424-01〜S424-08

是正対象:
- C-01: 哲学統合ロジック空 → Gemini統合提案生成
- C-02: こだわり→哲学候補の自動パスなし → reject_proposal自動生成
- C-03: decision_logger実統合未テスト → 実パス+fallbackパス分離テスト
- C-04: パイプライン完了→sync_all自動発動パスなし → フック追加
- C-05: ファイルロックなし → filelock導入
"""
import asyncio
import json
import logging
import sys
import threading
import time
import uuid
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# backend をパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


# ==================================================================
# Fixtures
# ==================================================================

@pytest.fixture
def tmp_evolution_log(tmp_path):
    """一時的なevolution_log.jsonを作成"""
    log_path = tmp_path / "evolution_log.json"
    return log_path


@pytest.fixture
def evolution_log_with_philosophies(tmp_evolution_log):
    """10件の哲学が入ったevolution_log.json"""
    data = {
        "entries": [],
        "philosophies": [
            {"philosophy": f"哲学{i}", "source": "test"}
            for i in range(10)
        ],
        "decision_insights": [],
        "pending_proposals": [],
        "trust_score": 0.5,
        "trust_history": [],
        "trigger_history": [],
        "session_count": 0,
        "rejection_count": 0,
        "approval_count": 0,
    }
    tmp_evolution_log.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return tmp_evolution_log


@pytest.fixture
def evolution_log_with_pending(tmp_evolution_log):
    """pending_proposalが入ったevolution_log.json"""
    proposal_id = str(uuid.uuid4())
    data = {
        "entries": [],
        "philosophies": [],
        "decision_insights": [],
        "pending_proposals": [
            {
                "proposal_id": proposal_id,
                "content": "テスト哲学提案",
                "source_summary": "テスト",
                "generated_at": datetime.now().isoformat(),
                "status": "pending",
                "user_edit": None,
            }
        ],
    }
    tmp_evolution_log.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return tmp_evolution_log, proposal_id


# ==================================================================
# S424-01: test_philosophy_integration_generates_proposal (C-01)
# ==================================================================

@pytest.mark.asyncio
async def test_philosophy_integration_generates_proposal(
    evolution_log_with_philosophies,
):
    """C-01: philosophies 10件→generate_integration_proposal()
    → pending_proposalsにtype="integration"で追加"""
    from services.philosophy_proposal_service import PhilosophyProposalService

    svc = PhilosophyProposalService(
        evolution_log_path=evolution_log_with_philosophies
    )

    # Gemini応答をモック
    mock_content = "統合された演出哲学: 静寂と動の対比による感動の深化"
    with patch.object(svc, "_call_gemini", new_callable=AsyncMock) as mock_gemini:
        mock_gemini.return_value = mock_content

        # model_registryをモック
        with patch("model_registry.get_model", return_value="gemini-2.0-flash"):
            philosophies = [
                {"philosophy": f"哲学{i}", "source": "test"}
                for i in range(10)
            ]
            proposal = await svc.generate_integration_proposal(philosophies)

    # アサーション
    assert proposal is not None, "統合提案が生成されるべき"
    assert proposal.content == mock_content
    assert proposal.status == "pending"
    assert "統合" in proposal.source_summary
    assert "10件" in proposal.source_summary

    # pending_proposals にtype="integration"で格納されているか確認 (SC-13)
    evo_log = json.loads(
        evolution_log_with_philosophies.read_text(encoding="utf-8")
    )
    integration_proposals = [
        p for p in evo_log.get("pending_proposals", [])
        if p.get("proposal_type") == "integration"
    ]
    assert len(integration_proposals) >= 1, "integration提案がpending_proposalsに存在すべき"
    assert integration_proposals[0]["content"] == mock_content


# ==================================================================
# S424-02: test_philosophy_integration_gemini_timeout (C-01)
# ==================================================================

@pytest.mark.asyncio
async def test_philosophy_integration_gemini_timeout(
    evolution_log_with_philosophies,
):
    """C-01: 統合生成30秒タイムアウト→None返却→既存哲学非破壊"""
    from services.philosophy_proposal_service import PhilosophyProposalService

    svc = PhilosophyProposalService(
        evolution_log_path=evolution_log_with_philosophies
    )

    # 既存哲学のスナップショットを保存
    evo_log_before = json.loads(
        evolution_log_with_philosophies.read_text(encoding="utf-8")
    )
    philosophies_before = evo_log_before["philosophies"]

    # Geminiをタイムアウトさせる
    async def slow_gemini(*args, **kwargs):
        raise asyncio.TimeoutError("30s timeout")

    with patch.object(svc, "_call_gemini", side_effect=slow_gemini):
        with patch("model_registry.get_model", return_value="gemini-2.0-flash"):
            result = await svc.generate_integration_proposal(
                philosophies_before
            )

    # アサーション: None返却
    assert result is None, "タイムアウト時はNoneを返すべき"

    # 既存哲学が非破壊であることを確認
    evo_log_after = json.loads(
        evolution_log_with_philosophies.read_text(encoding="utf-8")
    )
    assert len(evo_log_after["philosophies"]) == len(philosophies_before), \
        "タイムアウト時に既存哲学が変更されてはならない"


# ==================================================================
# S424-03: test_rejection_auto_generates_philosophy (C-02)
# ==================================================================

def test_rejection_auto_generates_philosophy(evolution_log_with_pending):
    """C-02: reject_proposal()→pending_proposalsに
    type="rejection_insight"で自動追加"""
    from services.philosophy_proposal_service import PhilosophyProposalService

    log_path, proposal_id = evolution_log_with_pending
    svc = PhilosophyProposalService(evolution_log_path=log_path)

    # 提案を却下
    reason = "テンポが遅すぎる"
    result = svc.reject_proposal(proposal_id, reason)
    assert result is True, "reject_proposalはTrueを返すべき"

    # evo_logを再読み込み
    evo_log = json.loads(log_path.read_text(encoding="utf-8"))

    # rejection_insightタイプの提案が自動追加されているか
    rejection_insights = [
        p for p in evo_log.get("pending_proposals", [])
        if p.get("proposal_type") == "rejection_insight"
    ]
    assert len(rejection_insights) >= 1, \
        "reject_proposal後にrejection_insight提案が自動生成されるべき"

    insight = rejection_insights[0]
    assert insight["status"] == "pending"
    assert reason in insight["content"], \
        "却下理由が提案内容に反映されるべき"
    assert "rejection_insight" in insight.get("source_summary", ""), \
        "source_summaryにrejection_insightが含まれるべき"


# ==================================================================
# S424-04: test_decision_logger_real_path (C-03)
# ==================================================================

def test_decision_logger_real_path(tmp_evolution_log):
    """C-03: decision_loggerが利用可能時に
    _count_rejection_patternsが実データを返す"""
    from services.evolution_trigger_service import EvolutionTriggerService

    # evolution_logを初期化
    data = {
        "entries": [],
        "philosophies": [],
        "rejection_count": 99,  # fallback値
    }
    tmp_evolution_log.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    svc = EvolutionTriggerService(evolution_log_path=tmp_evolution_log)
    evo_log = svc._load_evolution_log()

    # decision_loggerをモック（実パス: get_director_preferences が値を返す）
    mock_dl = MagicMock()
    mock_dl.get_director_preferences.return_value = {
        "却下パターン": {"テンポ調整": 5, "色補正": 2},
    }

    with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
        count = svc._count_rejection_patterns(evo_log)

    # 実データのmax値(5)を返すべき。fallback(99)ではない
    assert count == 5, \
        f"decision_logger実パスでは却下パターンの最大値(5)を返すべき, got {count}"


# ==================================================================
# S424-05: test_decision_logger_fallback_path (C-03)
# ==================================================================

def test_decision_logger_fallback_path(tmp_evolution_log):
    """C-03: decision_logger ImportError時にevo_log fallback値を返す"""
    from services.evolution_trigger_service import EvolutionTriggerService

    fallback_count = 7
    data = {
        "entries": [],
        "philosophies": [],
        "rejection_count": fallback_count,
    }
    tmp_evolution_log.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    svc = EvolutionTriggerService(evolution_log_path=tmp_evolution_log)
    evo_log = svc._load_evolution_log()

    # decision_loggerがImportErrorを発生させる
    with patch.dict("sys.modules", {"decision_logger": None}):
        count = svc._count_rejection_patterns(evo_log)

    assert count == fallback_count, \
        f"fallbackパスではevo_logのrejection_count({fallback_count})を返すべき, got {count}"


# ==================================================================
# S424-06: test_pipeline_completion_triggers_sync (C-04)
# ==================================================================

@pytest.mark.asyncio
async def test_pipeline_completion_triggers_sync():
    """C-04: _run_pipeline_background完了後にsync_all()が呼ばれる"""
    # pipeline_routerのインポートは重いので、ソースコードの静的検証で確認
    import importlib.util

    router_path = Path(__file__).parent.parent.parent / "routers" / "pipeline_router.py"
    assert router_path.exists(), f"pipeline_router.py が存在すべき: {router_path}"

    source = router_path.read_text(encoding="utf-8")

    # SC-10: EvolutionSyncService().sync_all() が存在するか
    assert "EvolutionSyncService" in source, \
        "pipeline_router.pyにEvolutionSyncServiceのインポートが必要"
    assert "sync_all()" in source, \
        "pipeline_router.pyにsync_all()呼出しが必要"
    assert "§12.5" in source, \
        "pipeline_router.pyに§12.5参照コメントが必要"

    # sync_allが_run_pipeline_background内にあることを確認
    # (pipeline_complete broadcastの後に配置されているか)
    broadcast_pos = source.find("pipeline_complete")
    sync_pos = source.find("sync_all()")
    assert broadcast_pos < sync_pos, \
        "sync_all()はpipeline_complete通知の後に配置されるべき"


# ==================================================================
# S424-07: test_filelock_concurrent_write (C-05)
# ==================================================================

def test_filelock_concurrent_write(tmp_evolution_log):
    """C-05: 2スレッドから同時にsave_evolution_logしても
    データ破損しない"""
    from utils.json_safe_io import safe_save_json, safe_load_json

    # 初期データ
    initial_data = {"entries": [], "counter": 0}
    safe_save_json(tmp_evolution_log, initial_data)

    errors = []
    iterations_per_thread = 20

    def writer(thread_id):
        """各スレッドがカウンターをインクリメントして書き込む"""
        try:
            for _ in range(iterations_per_thread):
                data = safe_load_json(tmp_evolution_log)
                data["counter"] = data.get("counter", 0) + 1
                data.setdefault("writers", []).append(f"thread-{thread_id}")
                safe_save_json(tmp_evolution_log, data)
        except Exception as e:
            errors.append(f"thread-{thread_id}: {e}")

    # 2スレッド同時実行
    t1 = threading.Thread(target=writer, args=(1,))
    t2 = threading.Thread(target=writer, args=(2,))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"スレッドエラー: {errors}"

    # 結果検証: JSONが破損していないこと
    final_data = safe_load_json(tmp_evolution_log)
    assert isinstance(final_data, dict), "最終データは辞書であるべき"
    assert "counter" in final_data, "counterフィールドが存在すべき"
    assert final_data["counter"] > 0, "counterは0より大きいはず"

    # JSONとしてパース可能か再確認
    raw = tmp_evolution_log.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert isinstance(parsed, dict), "最終ファイルは有効なJSONであるべき"


# ==================================================================
# S424-08: test_filelock_read_during_write (C-05)
# ==================================================================

def test_filelock_read_during_write(tmp_evolution_log):
    """C-05: 書込み中の読込みが破損JSONを返さない"""
    from utils.json_safe_io import safe_save_json, safe_load_json

    # 初期データ
    data = {
        "entries": [{"id": i, "value": f"entry-{i}"} for i in range(100)],
        "philosophies": [
            {"philosophy": f"哲学{i}"} for i in range(50)
        ],
    }
    safe_save_json(tmp_evolution_log, data)

    read_results = []
    write_errors = []
    read_errors = []

    def writer():
        """連続的に書き込みを行う"""
        try:
            for i in range(30):
                current = safe_load_json(tmp_evolution_log)
                current["entries"].append({"id": 100 + i, "value": f"new-{i}"})
                safe_save_json(tmp_evolution_log, current)
        except Exception as e:
            write_errors.append(str(e))

    def reader():
        """連続的に読み込みを行い、結果を検証"""
        try:
            for _ in range(50):
                result = safe_load_json(tmp_evolution_log)
                read_results.append(result)
                # 読み込み結果が必ず有効な辞書であること
                assert isinstance(result, dict), "読込結果は辞書であるべき"
                assert "entries" in result, "entriesフィールドが必須"
        except Exception as e:
            read_errors.append(str(e))

    # Writer/Reader を同時実行
    tw = threading.Thread(target=writer)
    tr = threading.Thread(target=reader)
    tw.start()
    tr.start()
    tw.join(timeout=30)
    tr.join(timeout=30)

    assert not write_errors, f"書込みエラー: {write_errors}"
    assert not read_errors, f"読込みエラー: {read_errors}"
    assert len(read_results) == 50, "全読込みが完了すべき"

    # 全読込み結果が有効なJSON辞書であること
    for i, result in enumerate(read_results):
        assert isinstance(result, dict), f"読込み{i}: 辞書でない"
        assert "entries" in result, f"読込み{i}: entriesなし"
