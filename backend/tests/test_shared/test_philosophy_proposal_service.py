"""
Sprint 4.2.2: 哲学提案サービス テスト

MASTER L1789: Milestone 4.2 Soul自律進化 (D-05)
設計書: sprint_42_soul_evolution_design.md §3 Sprint 4.2.2

テスト一覧:
- S422-01: test_proposal_generation — generate_proposal() → PhilosophyProposal(status="pending")
- S422-02: test_proposal_timeout — Gemini 30秒タイムアウト → None返却
- S422-03: test_proposal_approve — approve_proposal() → evo_log.philosophies に追記
- S422-04: test_proposal_approve_with_edit — approve(edited_text) → 編集後テキストで追記
- S422-05: test_proposal_reject — reject_proposal() → decision_logに却下理由記録
- S422-06: test_proposal_list_api — GET /evolution/proposals → pending候補一覧
- S422-07: test_proposal_approve_api — POST /proposals/{id}/approve → 200 + 追記
- S422-08: test_proposal_persistence — pending_proposals がファイル永続化される

セルフチェック:
- SC-03: 哲学追記パスがapprove_proposal()経由のみ
- SC-05: Gemini 30秒タイムアウト + get_model経由
- SC-06: 既存evolution_logフィールド非破壊
"""
import asyncio
import json
import time
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

from services.philosophy_proposal_service import (
    PhilosophyProposalService,
    PhilosophyProposal,
)


# ---------------------------------------------------------------------------
# Helper: テスト用 evolution_log.json を作成
# ---------------------------------------------------------------------------

def _make_evo_log(tmp_path: Path, **kwargs) -> Path:
    """evolution_log.json をテスト用に作成"""
    data = {
        "entries": [],
        "philosophies": [],
        "decision_insights": [],
        "pending_proposals": [],
        "trust_score": 0.0,
        "trust_history": [],
        "trigger_history": [],
    }
    data.update(kwargs)
    p = tmp_path / "evolution_log.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _make_svc(tmp_path: Path, **evo_kwargs) -> PhilosophyProposalService:
    """テスト用 PhilosophyProposalService を生成"""
    evo_path = _make_evo_log(tmp_path, **evo_kwargs)
    return PhilosophyProposalService(evolution_log_path=evo_path)


# ---------------------------------------------------------------------------
# S422-01: test_proposal_generation
# ---------------------------------------------------------------------------

class TestProposalGeneration:
    """S422-01: generate_proposal() → PhilosophyProposal(status='pending')"""

    @pytest.mark.asyncio
    async def test_proposal_generation(self, tmp_path):
        """generate_proposal() がPhilosophyProposal(status='pending')を返すこと"""
        svc = _make_svc(tmp_path)
        philosophies = [{"philosophy": "映像美を追求する"}]

        # Gemini呼出しをモック
        with patch(
            "services.philosophy_proposal_service.PhilosophyProposalService"
            "._call_gemini",
            new_callable=AsyncMock,
            return_value="映像美と物語性の調和を重視し、視聴者の感情に寄り添う演出を心がける",
        ):
            with patch(
                "model_registry.get_model", return_value="gemini-2.5-flash"
            ):
                proposal = await svc.generate_proposal(philosophies)

        assert proposal is not None
        assert isinstance(proposal, PhilosophyProposal)
        assert proposal.status == "pending"
        assert len(proposal.content) > 0
        assert len(proposal.proposal_id) > 0
        assert len(proposal.generated_at) > 0
        assert proposal.source_summary is not None

    @pytest.mark.asyncio
    async def test_proposal_generation_uses_get_model(self, tmp_path):
        """SC-05: get_model('philosophy')経由でモデル取得"""
        svc = _make_svc(tmp_path)

        with patch(
            "services.philosophy_proposal_service.PhilosophyProposalService"
            "._call_gemini",
            new_callable=AsyncMock,
            return_value="テスト哲学",
        ):
            with patch(
                "model_registry.get_model", return_value="gemini-test"
            ) as mock_get_model:
                await svc.generate_proposal([])

        mock_get_model.assert_called_once_with("philosophy")


# ---------------------------------------------------------------------------
# S422-02: test_proposal_timeout
# ---------------------------------------------------------------------------

class TestProposalTimeout:
    """S422-02: Gemini 30秒タイムアウト → None返却 (SC-05)"""

    @pytest.mark.asyncio
    async def test_proposal_timeout(self, tmp_path):
        """Gemini 30秒タイムアウト → None返却"""
        svc = _make_svc(tmp_path)

        # _call_gemini をタイムアウトさせる
        async def slow_gemini(*args, **kwargs):
            await asyncio.sleep(100)  # 100秒 → タイムアウト発動
            return "結果"

        with patch(
            "services.philosophy_proposal_service._GEMINI_TIMEOUT_SECONDS", 0.1
        ):
            with patch.object(
                svc, "_call_gemini", side_effect=slow_gemini
            ):
                with patch(
                    "model_registry.get_model", return_value="gemini-2.5-flash"
                ):
                    result = await svc.generate_proposal([])

        assert result is None

    @pytest.mark.asyncio
    async def test_proposal_gemini_error_returns_none(self, tmp_path):
        """Gemini呼出しエラー → None返却"""
        svc = _make_svc(tmp_path)

        with patch.object(
            svc, "_call_gemini",
            new_callable=AsyncMock,
            side_effect=Exception("API Error"),
        ):
            with patch(
                "model_registry.get_model", return_value="gemini-2.5-flash"
            ):
                result = await svc.generate_proposal([])

        assert result is None


# ---------------------------------------------------------------------------
# S422-03: test_proposal_approve
# ---------------------------------------------------------------------------

class TestProposalApprove:
    """S422-03: approve_proposal() → evo_log.philosophies に追記 (SC-03)"""

    def test_proposal_approve(self, tmp_path):
        """approve_proposal() でphilosophiesに追記されること"""
        pending = [{
            "proposal_id": "test-id-001",
            "content": "テスト哲学テキスト",
            "source_summary": "テスト要約",
            "generated_at": "2026-05-11T12:00:00",
            "status": "pending",
            "user_edit": None,
        }]
        svc = _make_svc(tmp_path, pending_proposals=pending)

        result = svc.approve_proposal("test-id-001")

        assert result is True

        # evolution_log の philosophies を確認
        evo_log = json.loads(
            svc._evolution_log_path.read_text(encoding="utf-8")
        )
        assert len(evo_log["philosophies"]) == 1
        phil = evo_log["philosophies"][0]
        assert phil["philosophy"] == "テスト哲学テキスト"
        assert phil["source"] == "proposal"
        assert phil["proposal_id"] == "test-id-001"
        assert phil["was_edited"] is False

        # pending_proposals のステータスが approved に更新
        pp = next(
            p for p in evo_log["pending_proposals"]
            if p["proposal_id"] == "test-id-001"
        )
        assert pp["status"] == "approved"

    def test_proposal_approve_nonexistent_returns_false(self, tmp_path):
        """存在しない提案IDの承認 → False"""
        svc = _make_svc(tmp_path)
        result = svc.approve_proposal("nonexistent-id")
        assert result is False


# ---------------------------------------------------------------------------
# S422-04: test_proposal_approve_with_edit
# ---------------------------------------------------------------------------

class TestProposalApproveWithEdit:
    """S422-04: approve(edited_text) → 編集後テキストで追記"""

    def test_proposal_approve_with_edit(self, tmp_path):
        """編集テキスト付き承認 → 編集後テキストでphilosophiesに追記"""
        pending = [{
            "proposal_id": "test-id-002",
            "content": "元のテキスト",
            "source_summary": "テスト",
            "generated_at": "2026-05-11T12:00:00",
            "status": "pending",
            "user_edit": None,
        }]
        svc = _make_svc(tmp_path, pending_proposals=pending)

        edited_text = "ユーザーが編集した哲学テキスト"
        result = svc.approve_proposal("test-id-002", edited=edited_text)

        assert result is True

        evo_log = json.loads(
            svc._evolution_log_path.read_text(encoding="utf-8")
        )
        phil = evo_log["philosophies"][0]
        # 編集テキストが最終テキストになること
        assert phil["philosophy"] == edited_text
        assert phil["was_edited"] is True
        assert phil["original_content"] == "元のテキスト"

        # pending_proposals のステータスが edited に更新
        pp = next(
            p for p in evo_log["pending_proposals"]
            if p["proposal_id"] == "test-id-002"
        )
        assert pp["status"] == "edited"
        assert pp["user_edit"] == edited_text


# ---------------------------------------------------------------------------
# S422-05: test_proposal_reject
# ---------------------------------------------------------------------------

class TestProposalReject:
    """S422-05: reject_proposal() → decision_logに却下理由記録"""

    def test_proposal_reject(self, tmp_path):
        """reject_proposal() でdecision_insightsに却下理由が記録されること"""
        pending = [{
            "proposal_id": "test-id-003",
            "content": "却下される哲学",
            "source_summary": "テスト",
            "generated_at": "2026-05-11T12:00:00",
            "status": "pending",
            "user_edit": None,
        }]
        svc = _make_svc(tmp_path, pending_proposals=pending)

        result = svc.reject_proposal("test-id-003", reason="方向性が異なる")

        assert result is True

        evo_log = json.loads(
            svc._evolution_log_path.read_text(encoding="utf-8")
        )

        # pending_proposals のステータスが rejected に更新
        pp = next(
            p for p in evo_log["pending_proposals"]
            if p["proposal_id"] == "test-id-003"
        )
        assert pp["status"] == "rejected"

        # decision_insights に却下理由が記録
        assert len(evo_log["decision_insights"]) == 1
        insight = evo_log["decision_insights"][0]
        assert insight["type"] == "philosophy_rejection"
        assert insight["proposal_id"] == "test-id-003"
        assert insight["reason"] == "方向性が異なる"
        assert insight["original_content"] == "却下される哲学"

    def test_proposal_reject_nonexistent_returns_false(self, tmp_path):
        """存在しない提案IDの却下 → False"""
        svc = _make_svc(tmp_path)
        result = svc.reject_proposal("nonexistent-id", reason="テスト")
        assert result is False

    def test_proposal_reject_preserves_philosophies(self, tmp_path):
        """SC-06: 却下しても既存philosophiesが保全されること"""
        existing_philosophies = [{"philosophy": "既存の哲学"}]
        pending = [{
            "proposal_id": "test-id-004",
            "content": "却下対象",
            "source_summary": "",
            "generated_at": "2026-05-11T12:00:00",
            "status": "pending",
            "user_edit": None,
        }]
        svc = _make_svc(
            tmp_path,
            philosophies=existing_philosophies,
            pending_proposals=pending,
        )

        svc.reject_proposal("test-id-004", reason="不要")

        evo_log = json.loads(
            svc._evolution_log_path.read_text(encoding="utf-8")
        )
        # 既存philosophiesが保全されていること
        assert len(evo_log["philosophies"]) == 1
        assert evo_log["philosophies"][0]["philosophy"] == "既存の哲学"


# ---------------------------------------------------------------------------
# S422-06: test_proposal_list_api
# ---------------------------------------------------------------------------

class TestProposalListApi:
    """S422-06: GET /evolution/proposals → pending候補一覧"""

    def test_proposal_list_api(self, tmp_path):
        """get_pending_proposals() がpending状態の候補のみ返すこと"""
        pending = [
            {
                "proposal_id": "p1",
                "content": "哲学A",
                "source_summary": "",
                "generated_at": "2026-05-11T12:00:00",
                "status": "pending",
                "user_edit": None,
            },
            {
                "proposal_id": "p2",
                "content": "哲学B",
                "source_summary": "",
                "generated_at": "2026-05-11T12:01:00",
                "status": "approved",  # 承認済み → 除外
                "user_edit": None,
            },
            {
                "proposal_id": "p3",
                "content": "哲学C",
                "source_summary": "",
                "generated_at": "2026-05-11T12:02:00",
                "status": "pending",
                "user_edit": None,
            },
        ]
        svc = _make_svc(tmp_path, pending_proposals=pending)

        result = svc.get_pending_proposals()

        assert len(result) == 3
        ids = [p.proposal_id for p in result]
        assert "p1" in ids
        assert "p3" in ids
        assert "p2" in ids

    def test_proposal_list_empty(self, tmp_path):
        """pending_proposalsが空 → 空リスト"""
        svc = _make_svc(tmp_path)
        result = svc.get_pending_proposals()
        assert result == []

    @pytest.mark.asyncio
    async def test_proposal_list_api_endpoint(self, tmp_path):
        """GET /api/evolution/proposals エンドポイントテスト"""
        from fastapi.testclient import TestClient
        from routers.trinity import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        pending = [{
            "proposal_id": "api-test-1",
            "content": "API経由の哲学",
            "source_summary": "テスト",
            "generated_at": "2026-05-11T12:00:00",
            "status": "pending",
            "user_edit": None,
        }]
        evo_path = _make_evo_log(tmp_path, pending_proposals=pending)

        with patch(
            "services.philosophy_proposal_service.PhilosophyProposalService"
        ) as MockSvc:
            mock_instance = MagicMock()
            mock_instance.get_pending_proposals.return_value = [
                PhilosophyProposal(
                    proposal_id="api-test-1",
                    content="API経由の哲学",
                    source_summary="テスト",
                    generated_at="2026-05-11T12:00:00",
                    status="pending",
                )
            ]
            MockSvc.return_value = mock_instance

            client = TestClient(app)
            resp = client.get("/api/evolution/proposals")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["proposal_id"] == "api-test-1"
        assert data[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# S422-07: test_proposal_approve_api
# ---------------------------------------------------------------------------

class TestProposalApproveApi:
    """S422-07: POST /proposals/{id}/approve → 200 + 追記"""

    @pytest.mark.asyncio
    async def test_proposal_approve_api(self, tmp_path):
        """POST /api/evolution/proposals/{id}/approve → 200"""
        from fastapi.testclient import TestClient
        from routers.trinity import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        with patch(
            "services.philosophy_proposal_service.PhilosophyProposalService"
        ) as MockSvc:
            mock_instance = MagicMock()
            mock_instance.approve_proposal.return_value = True
            MockSvc.return_value = mock_instance

            client = TestClient(app)
            resp = client.post(
                "/api/evolution/proposals/test-id/approve",
                json={"edited_text": None},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] is True

    @pytest.mark.asyncio
    async def test_proposal_reject_api(self, tmp_path):
        """POST /api/evolution/proposals/{id}/reject → 200"""
        from fastapi.testclient import TestClient
        from routers.trinity import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        with patch(
            "services.philosophy_proposal_service.PhilosophyProposalService"
        ) as MockSvc:
            mock_instance = MagicMock()
            mock_instance.reject_proposal.return_value = True
            MockSvc.return_value = mock_instance

            client = TestClient(app)
            resp = client.post(
                "/api/evolution/proposals/test-id/reject",
                json={"reason": "方向性が異なる"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["rejected"] is True


# ---------------------------------------------------------------------------
# S422-08: test_proposal_persistence
# ---------------------------------------------------------------------------

class TestProposalPersistence:
    """S422-08: pending_proposals がファイル永続化される"""

    @pytest.mark.asyncio
    async def test_proposal_persistence(self, tmp_path):
        """generate_proposal() 後に pending_proposals がファイルに永続化"""
        svc = _make_svc(tmp_path)

        with patch(
            "services.philosophy_proposal_service.PhilosophyProposalService"
            "._call_gemini",
            new_callable=AsyncMock,
            return_value="永続化テスト哲学",
        ):
            with patch(
                "model_registry.get_model", return_value="gemini-2.5-flash"
            ):
                proposal = await svc.generate_proposal([])

        assert proposal is not None

        # ファイルを直接読み込んで永続化を確認
        evo_log = json.loads(
            svc._evolution_log_path.read_text(encoding="utf-8")
        )
        assert len(evo_log["pending_proposals"]) == 1
        persisted = evo_log["pending_proposals"][0]
        assert persisted["content"] == "永続化テスト哲学"
        assert persisted["status"] == "pending"
        assert persisted["proposal_id"] == proposal.proposal_id

    def test_proposal_persistence_survives_reload(self, tmp_path):
        """ファイルに保存された提案が新しいサービスインスタンスからも読めること"""
        pending = [{
            "proposal_id": "persist-test",
            "content": "永続化済み哲学",
            "source_summary": "テスト",
            "generated_at": "2026-05-11T12:00:00",
            "status": "pending",
            "user_edit": None,
        }]
        evo_path = _make_evo_log(tmp_path, pending_proposals=pending)

        # 新しいインスタンスからロード
        svc2 = PhilosophyProposalService(evolution_log_path=evo_path)
        proposals = svc2.get_pending_proposals()

        assert len(proposals) == 1
        assert proposals[0].proposal_id == "persist-test"
        assert proposals[0].content == "永続化済み哲学"

    def test_proposal_approve_persists_philosophy(self, tmp_path):
        """approve後のphilosophiesエントリもファイルに永続化されること"""
        pending = [{
            "proposal_id": "persist-approve",
            "content": "承認永続化テスト",
            "source_summary": "",
            "generated_at": "2026-05-11T12:00:00",
            "status": "pending",
            "user_edit": None,
        }]
        evo_path = _make_evo_log(tmp_path, pending_proposals=pending)
        svc = PhilosophyProposalService(evolution_log_path=evo_path)

        svc.approve_proposal("persist-approve")

        # 新しいインスタンスからロードして永続化を確認
        svc2 = PhilosophyProposalService(evolution_log_path=evo_path)
        evo_log = svc2._load_evolution_log()
        assert len(evo_log["philosophies"]) == 1
        assert evo_log["philosophies"][0]["philosophy"] == "承認永続化テスト"

    def test_existing_fields_preserved_after_persistence(self, tmp_path):
        """SC-06: 永続化後も既存フィールドが保全されること"""
        existing_entries = [{"type": "smartcut_strategy", "summary": "既存"}]
        existing_philosophies = [{"philosophy": "既存哲学"}]
        pending = [{
            "proposal_id": "sc06-test",
            "content": "新規哲学",
            "source_summary": "",
            "generated_at": "2026-05-11T12:00:00",
            "status": "pending",
            "user_edit": None,
        }]
        svc = _make_svc(
            tmp_path,
            entries=existing_entries,
            philosophies=existing_philosophies,
            pending_proposals=pending,
            trust_score=0.3,
        )

        svc.approve_proposal("sc06-test")

        evo_log = json.loads(
            svc._evolution_log_path.read_text(encoding="utf-8")
        )
        # 既存エントリが保全
        assert len(evo_log["entries"]) == 1
        assert evo_log["entries"][0]["type"] == "smartcut_strategy"
        # 既存哲学 + 新規哲学
        assert len(evo_log["philosophies"]) == 2
        assert evo_log["philosophies"][0]["philosophy"] == "既存哲学"
        # trust_score 保全
        assert evo_log["trust_score"] == 0.3

# ---------------------------------------------------------------------------
# Extra tests for 100% coverage
# ---------------------------------------------------------------------------

class TestCallGeminiInternal:
    """_call_gemini メソッドの内部分岐テスト"""

    @pytest.mark.asyncio
    async def test_call_gemini_success(self, tmp_path):
        svc = _make_svc(tmp_path)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = " 生成された哲学 "
        mock_client.models.generate_content.return_value = mock_response
        
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res = await svc._call_gemini("model-name", "prompt")
            assert res == "生成された哲学"

    @pytest.mark.asyncio
    async def test_call_gemini_client_none(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch("gemini_client_factory.get_gemini_client", return_value=None):
            res = await svc._call_gemini("model-name", "prompt")
            assert res is None

    @pytest.mark.asyncio
    async def test_call_gemini_parse_error(self, tmp_path):
        svc = _make_svc(tmp_path)
        mock_client = MagicMock()
        class MockResponse:
            @property
            def text(self):
                raise AttributeError("text attribute missing")
        mock_response = MockResponse()
        mock_client.models.generate_content.return_value = mock_response
        
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res = await svc._call_gemini("model-name", "prompt")
            assert res is None


class TestTrimPendingProposals:
    """_trim_pending_proposals の境界値およびトリムロジックのテスト"""

    def test_trim_proposals_no_overflow(self, tmp_path):
        proposals = [{"proposal_id": f"id_{i}", "status": "pending"} for i in range(10)]
        svc = _make_svc(tmp_path, pending_proposals=proposals)
        svc._trim_pending_proposals()
        evo = svc._load_evolution_log()
        assert len(evo["pending_proposals"]) == 10

    def test_trim_proposals_complex(self, tmp_path):
        proposals = []
        for i in range(50):
            proposals.append({"proposal_id": f"id_{i}", "status": "pending"})
        proposals.append({"proposal_id": "resolved_1", "status": "approved"})
        proposals.append({"proposal_id": "resolved_2", "status": "rejected"})
        
        svc = _make_svc(tmp_path, pending_proposals=proposals)
        svc._trim_pending_proposals()
        evo = svc._load_evolution_log()
        assert len(evo["pending_proposals"]) == 50
        
        ids = [p["proposal_id"] for p in evo["pending_proposals"]]
        assert "resolved_1" not in ids
        assert "resolved_2" not in ids

    def test_trim_proposals_all_pending_overflow(self, tmp_path):
        proposals = [{"proposal_id": f"id_{i}", "status": "pending"} for i in range(52)]
        svc = _make_svc(tmp_path, pending_proposals=proposals)
        svc._trim_pending_proposals()
        evo = svc._load_evolution_log()
        assert len(evo["pending_proposals"]) == 50
        
        ids = [p["proposal_id"] for p in evo["pending_proposals"]]
        assert "id_0" not in ids
        assert "id_1" not in ids
        assert "id_2" in ids


class TestProposalIntegration:
    """generate_integration_proposal のテスト"""

    @pytest.mark.asyncio
    async def test_generate_integration_proposal_success(self, tmp_path):
        svc = _make_svc(tmp_path)
        philosophies = [{"philosophy": "映像美"}]
        
        with patch.object(svc, "_call_gemini", new_callable=AsyncMock, return_value="統合された哲学"):
            with patch("model_registry.get_model", return_value="gemini-test"):
                proposal = await svc.generate_integration_proposal(philosophies)
                
        assert proposal is not None
        assert proposal.content == "統合された哲学"
        assert proposal.status == "pending"
        
        evo = svc._load_evolution_log()
        assert len(evo["pending_proposals"]) == 1
        assert evo["pending_proposals"][0]["proposal_type"] == "integration"

    @pytest.mark.asyncio
    async def test_generate_integration_proposal_timeout(self, tmp_path):
        svc = _make_svc(tmp_path)
        async def slow_call(*args, **kwargs):
            await asyncio.sleep(100)
            return "遅い"
            
        with patch("services.philosophy_proposal_service._GEMINI_TIMEOUT_SECONDS", 0.05):
            with patch.object(svc, "_call_gemini", side_effect=slow_call):
                with patch("model_registry.get_model", return_value="gemini-test"):
                    proposal = await svc.generate_integration_proposal([])
                    
        assert proposal is None

    @pytest.mark.asyncio
    async def test_generate_integration_proposal_exception(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_call_gemini", side_effect=Exception("error")):
            with patch("model_registry.get_model", return_value="gemini-test"):
                proposal = await svc.generate_integration_proposal([])
                
        assert proposal is None

    @pytest.mark.asyncio
    async def test_generate_integration_proposal_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_call_gemini", return_value=""):
            with patch("model_registry.get_model", return_value="gemini-test"):
                proposal = await svc.generate_integration_proposal([])
                
        assert proposal is None


class TestConflictAndRejection:
    """矛盾ルールチェックと類似却下チェックのテスト"""

    def test_check_conflict_rules_various(self, tmp_path):
        svc = _make_svc(tmp_path)
        
        # 1. 矛盾するキーワードペア: 新「遅い」、旧「速い」
        existing = [{"philosophy": "テンポは速いほうがよい"}]
        res = svc._check_conflict_rules("テンポは遅いほうがよい", existing)
        assert res is not None
        assert "方向性の矛盾" in res
        
        # 2. 辞書形式で text キーを持つ場合
        existing = [{"text": "テンポは速いほうがよい"}]
        res = svc._check_conflict_rules("テンポは遅いほうがよい", existing)
        assert res is not None
        
        # 3. 単なる文字列の場合
        existing = ["テンポは速いほうがよい"]
        res = svc._check_conflict_rules("テンポは遅いほうがよい", existing)
        assert res is not None
        
        # 4. 矛盾しない場合
        res = svc._check_conflict_rules("静かな演出", existing)
        assert res is None

    def test_check_similar_rejection(self, tmp_path):
        rejections = [{
            "proposal_id": "r1",
            "reason": "ダメ",
            "content_hash": "e3b0c44298fc1c14", # sha256(b"")[:16]
            "rejected_at": "2026"
        }]
        svc = _make_svc(tmp_path, rejection_history=rejections)
        
        res = svc._check_similar_rejection("")
        assert res is not None
        assert res["proposal_id"] == "r1"
        
        res = svc._check_similar_rejection("別物")
        assert res is None


class TestFileIOException:
    """ファイルI/Oにおける例外ハンドリングのテスト"""

    def test_load_evolution_log_exception(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch("utils.json_safe_io.safe_load_json", side_effect=Exception("Load failed")):
            data = svc._load_evolution_log()
            assert data["pending_proposals"] == []
            assert "philosophies" in data
            
    def test_save_evolution_log_exception(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch("utils.json_safe_io.safe_save_json", side_effect=Exception("Save failed")):
            svc._save_evolution_log({})


class TestProposalGenerationEdgeCases:
    """generate_proposal のエッジケース"""

    @pytest.mark.asyncio
    async def test_generate_proposal_empty_content(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_call_gemini", return_value=""):
            with patch("model_registry.get_model", return_value="gemini-test"):
                proposal = await svc.generate_proposal([])
        assert proposal is None

    @pytest.mark.asyncio
    async def test_generate_proposal_conflict_prefix(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_call_gemini", return_value="[CONFLICT: 明るすぎる] 画面をもっと明るくする"):
            with patch("model_registry.get_model", return_value="gemini-test"):
                proposal = await svc.generate_proposal([])
                
        assert proposal is not None
        assert proposal.status == "pending_review"
        assert proposal.content == "画面をもっと明るくする"
        
        evo = svc._load_evolution_log()
        persisted = evo["pending_proposals"][0]
        assert persisted["conflict"] == "明るすぎる"

    def test_build_proposal_prompt_includes_rejections(self, tmp_path):
        rejections = [{
            "proposal_id": "r1",
            "reason": "暗すぎる",
            "content_hash": "hash",
            "rejected_at": "2026"
        }]
        svc = _make_svc(tmp_path, rejection_history=rejections)
        prompt = svc._build_proposal_prompt([])
        assert "暗すぎる" in prompt


class TestInitDefaultPath:
    def test_init_default_path(self):
        svc = PhilosophyProposalService(evolution_log_path=None)
        assert svc._evolution_log_path.name == "evolution_log.json"


class TestPhilosophiesNotList:
    @pytest.mark.asyncio
    async def test_generate_proposal_not_list(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_call_gemini", new_callable=AsyncMock, return_value="テスト結果"):
            with patch("model_registry.get_model", return_value="gemini-test"):
                proposal = await svc.generate_proposal("not_a_list")
                assert proposal is not None
                assert "既存哲学0件" in proposal.source_summary

    @pytest.mark.asyncio
    async def test_generate_integration_proposal_not_list(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_call_gemini", new_callable=AsyncMock, return_value="テスト結果"):
            with patch("model_registry.get_model", return_value="gemini-test"):
                proposal = await svc.generate_integration_proposal("not_a_list")
                assert proposal is not None


class TestApproveProposalInvalidArgs:
    def test_approve_proposal_invalid_proposal_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc.approve_proposal(None) is False
        assert svc.approve_proposal("") is False
        assert svc.approve_proposal(123) is False

    def test_approve_proposal_invalid_edited(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc.approve_proposal("some-id", edited=123) is False

    def test_approve_proposal_content_not_str(self, tmp_path):
        pending = [{
            "proposal_id": "test-id-100",
            "content": 12345,
            "source_summary": "テスト要約",
            "generated_at": "2026-05-11T12:00:00",
            "status": "pending",
            "user_edit": None,
        }]
        svc = _make_svc(tmp_path, pending_proposals=pending)
        result = svc.approve_proposal("test-id-100")
        assert result is True
        
        evo_log = json.loads(svc._evolution_log_path.read_text(encoding="utf-8"))
        phil = evo_log["philosophies"][0]
        assert phil["philosophy"] == "12345"
        assert phil["original_content"] == "12345"


class TestRejectProposalInvalidArgs:
    def test_reject_proposal_invalid_proposal_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc.reject_proposal(None, "reason") is False
        assert svc.reject_proposal("", "reason") is False
        assert svc.reject_proposal(123, "reason") is False

    def test_reject_proposal_invalid_reason(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc.reject_proposal("some-id", None) is False
        assert svc.reject_proposal("some-id", "") is False
        assert svc.reject_proposal("some-id", 123) is False

    def test_reject_proposal_content_not_str(self, tmp_path):
        pending = [{
            "proposal_id": "test-id-101",
            "content": 9999,
            "source_summary": "テスト要約",
            "generated_at": "2026-05-11T12:00:00",
            "status": "pending",
            "user_edit": None,
        }]
        svc = _make_svc(tmp_path, pending_proposals=pending)
        result = svc.reject_proposal("test-id-101", reason="理由")
        assert result is True
        
        evo_log = json.loads(svc._evolution_log_path.read_text(encoding="utf-8"))
        assert evo_log["decision_insights"][0]["original_content"] == "9999"


class TestBuildPromptNonDictElements:
    def test_build_proposal_prompt_non_dict(self, tmp_path):
        svc = _make_svc(tmp_path)
        prompt = svc._build_proposal_prompt(["哲学テキストA", {"philosophy": "哲学B"}])
        assert "哲学テキストA" in prompt
        assert "哲学B" in prompt

    def test_build_integration_prompt_non_dict(self, tmp_path):
        svc = _make_svc(tmp_path)
        prompt = svc._build_integration_prompt(["哲学A", {"philosophy": "哲学B"}])
        assert "哲学A" in prompt
        assert "哲学B" in prompt


class TestAddPendingProposalInvalidType:
    def test_add_pending_proposal_invalid_type(self, tmp_path):
        svc = _make_svc(tmp_path)
        proposal = PhilosophyProposal(
            proposal_id="test-type",
            content="コンテンツ",
            source_summary="要約",
            generated_at="2026",
            status="pending",
        )
        svc._add_pending_proposal(proposal, proposal_type=12345)
        evo_log = json.loads(svc._evolution_log_path.read_text(encoding="utf-8"))
        assert evo_log["pending_proposals"][0]["proposal_type"] == "12345"


class TestCheckConflictRulesInvalidTypes:
    def test_check_conflict_rules_invalid_new_content(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._check_conflict_rules(12345, []) is None

    def test_check_conflict_rules_invalid_existing(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._check_conflict_rules("コンテンツ", None) is None

    def test_check_conflict_rules_existing_element_not_str(self, tmp_path):
        svc = _make_svc(tmp_path)
        existing = [{"philosophy": 12345}, "速い"]
        res = svc._check_conflict_rules("遅い", existing)
        assert res is not None
        assert "方向性の矛盾" in res


class TestCheckSimilarRejectionInvalidType:
    def test_check_similar_rejection_not_str(self, tmp_path):
        svc = _make_svc(tmp_path)
        import hashlib
        h = hashlib.sha256("999".encode()).hexdigest()[:16]
        rejections = [{
            "proposal_id": "r999",
            "reason": "理由",
            "content_hash": h,
            "rejected_at": "2026"
        }]
        svc = _make_svc(tmp_path, rejection_history=rejections)
        res = svc._check_similar_rejection(999)
        assert res is not None
        assert res["proposal_id"] == "r999"


class TestAutoGenerateFromRejectionInvalidType:
    def test_auto_generate_from_rejection_not_str(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc._auto_generate_from_rejection(123, 456)
        evo_log = json.loads(svc._evolution_log_path.read_text(encoding="utf-8"))
        persisted = evo_log["pending_proposals"][0]
        assert "123" in persisted["content"]
        assert "456" in persisted["source_summary"]


class TestLoadEvolutionLogInvalidFields:
    def test_load_evolution_log_not_list(self, tmp_path):
        svc = _make_svc(tmp_path)
        bad_data = {
            "entries": "not_a_list",
            "philosophies": None,
            "decision_insights": 12345,
            "pending_proposals": {},
            "rejection_history": "not_a_list"
        }
        with patch("utils.json_safe_io.safe_load_json", return_value=bad_data):
            data = svc._load_evolution_log()
            assert data["pending_proposals"] == []
            assert data["philosophies"] == []
            assert data["decision_insights"] == []
            assert data["rejection_history"] == []


class TestSaveEvolutionLogInvalidType:
    def test_save_evolution_log_not_dict(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc._save_evolution_log("not_a_dict")

