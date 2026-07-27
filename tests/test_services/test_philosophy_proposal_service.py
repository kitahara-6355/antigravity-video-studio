"""
PhilosophyProposalService の全コードパスを網羅するテストスイート。
目標: カバレッジ 100%
"""
import sys
import os
import json
import asyncio
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# backend をパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from services.philosophy_proposal_service import (
    PhilosophyProposalService,
    PhilosophyProposal
)


@pytest.mark.asyncio
async def test_init_path_casting(tmp_path):
    # evolution_log_path が文字列の場合のキャスト
    log_str = str(tmp_path / "evo_log.json")
    svc = PhilosophyProposalService(evolution_log_path=log_str)
    assert isinstance(svc._evolution_log_path, Path)
    
    # None の場合
    svc_default = PhilosophyProposalService(evolution_log_path=None)
    assert svc_default._evolution_log_path.name == "evolution_log.json"


@pytest.mark.asyncio
async def test_load_evolution_log_edge_cases(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)
    
    # ファイルが存在しない場合
    data = svc._load_evolution_log()
    assert isinstance(data, dict)
    assert "pending_proposals" in data

    # 破損ファイル（jsonパースエラー）
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("invalid json")
    data = svc._load_evolution_log()
    assert data["pending_proposals"] == []

    # 辞書型以外が返る場合
    with patch("utils.json_safe_io.safe_load_json", return_value="string_data"):
        data = svc._load_evolution_log()
        assert data["pending_proposals"] == []

    # load時例外発生
    with patch("utils.json_safe_io.safe_load_json", side_effect=Exception("load error")), \
         patch("services.philosophy_proposal_service.logger") as mock_logger:
        data = svc._load_evolution_log()
        assert data["pending_proposals"] == []
        mock_logger.warning.assert_called_once_with(
            "[PhilosophyProposal] evolution_log読込失敗", exc_info=True
        )


@pytest.mark.asyncio
async def test_load_evolution_log_type_forcing(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)
    
    # 全てのリスト項目が不正な型（文字列）の場合のキャスト
    bad_data = {
        "pending_proposals": "bad",
        "philosophies": "bad",
        "decision_insights": "bad",
        "rejection_history": "bad"
    }
    with patch("utils.json_safe_io.safe_load_json", return_value=bad_data):
        data = svc._load_evolution_log()
        assert data["pending_proposals"] == []
        assert data["philosophies"] == []
        assert data["decision_insights"] == []
        assert data["rejection_history"] == []


@pytest.mark.asyncio
async def test_save_evolution_log_edge_cases(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)
    
    # 辞書型でないデータを保存しようとする場合
    svc._save_evolution_log("string_data")
    assert not log_path.exists()

    # 例外が発生する場合
    with patch("utils.json_safe_io.safe_save_json", side_effect=Exception("save error")), \
         patch("services.philosophy_proposal_service.logger") as mock_logger:
        svc._save_evolution_log({"test": "data"})  # ログ出力のみで正常終了
        mock_logger.exception.assert_called_once_with(
            "[PhilosophyProposal] evolution_log保存失敗"
        )


@pytest.mark.asyncio
async def test_generate_proposal_invalid_philosophies(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)
    
    # list 以外の型を渡す
    with patch("model_registry.get_model", return_value="gemini-test"),          patch.object(svc, "_call_gemini", new_callable=AsyncMock, return_value=""):
        res = await svc.generate_proposal(philosophies="not a list")
        assert res is None


@pytest.mark.asyncio
async def test_generate_proposal_gemini_timeout(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)

    # タイムアウト
    with patch("model_registry.get_model", return_value="gemini-test"),          patch.object(svc, "_call_gemini", side_effect=asyncio.TimeoutError):
        res = await svc.generate_proposal([])
        assert res is None


@pytest.mark.asyncio
async def test_generate_proposal_gemini_exception(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)

    # 一般例外
    with patch("model_registry.get_model", return_value="gemini-test"), \
         patch.object(svc, "_call_gemini", side_effect=RuntimeError("Gemini error")), \
         patch("services.philosophy_proposal_service.logger") as mock_logger:
        res = await svc.generate_proposal([])
        assert res is None
        mock_logger.exception.assert_called_once_with("[PhilosophyProposal] Gemini呼出失敗")


@pytest.mark.asyncio
async def test_generate_proposal_empty_content(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)

    # コンテンツが空
    with patch("model_registry.get_model", return_value="gemini-test"),          patch.object(svc, "_call_gemini", new_callable=AsyncMock, return_value=""):
        res = await svc.generate_proposal([])
        assert res is None


@pytest.mark.asyncio
async def test_generate_proposal_conflict_rules(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)
    
    # 既存の哲学と矛盾（速い ↔ 遅い）
    existing = [{"philosophy": "速い演出を好む"}]
    with patch("model_registry.get_model", return_value="gemini-test"),          patch.object(svc, "_call_gemini", new_callable=AsyncMock, return_value="遅いテンポの演出を提案"):
        res = await svc.generate_proposal(existing)
        assert res is not None
        assert res.status == "pending_review"

        # 保存されたデータに conflict フィールドがあることを確認
        evo = svc._load_evolution_log()
        assert "conflict" in evo["pending_proposals"][0]


@pytest.mark.asyncio
async def test_generate_proposal_conflict_prefix(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)
    
    # [CONFLICT] プレフィックス付きのレスポンス
    with patch("model_registry.get_model", return_value="gemini-test"),          patch.object(svc, "_call_gemini", new_callable=AsyncMock, return_value="[CONFLICT: 重複のため] 演出はシンプルにする"):
        res = await svc.generate_proposal([])
        assert res is not None
        assert res.content == "演出はシンプルにする"
        
        evo = svc._load_evolution_log()
        assert evo["pending_proposals"][0]["conflict"] == "重複のため"


@pytest.mark.asyncio
async def test_generate_integration_proposal(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)
    
    # 正常系
    with patch("model_registry.get_model", return_value="gemini-test"),          patch.object(svc, "_call_gemini", new_callable=AsyncMock, return_value="統合された演出理論"):
        res = await svc.generate_integration_proposal([{"philosophy": "A"}, {"philosophy": "B"}])
        assert res is not None
        assert res.status == "pending"
        
        evo = svc._load_evolution_log()
        assert evo["pending_proposals"][0]["proposal_type"] == "integration"

    # philosophies がリストでない場合
    with patch("model_registry.get_model", return_value="gemini-test"),          patch.object(svc, "_call_gemini", new_callable=AsyncMock, return_value="統合された演出理論"):
        res = await svc.generate_integration_proposal("not a list")
        assert res is not None

    # タイムアウト
    with patch("model_registry.get_model", return_value="gemini-test"),          patch.object(svc, "_call_gemini", side_effect=asyncio.TimeoutError):
        res = await svc.generate_integration_proposal([])
        assert res is None

    # 例外
    with patch("model_registry.get_model", return_value="gemini-test"), \
         patch.object(svc, "_call_gemini", side_effect=RuntimeError("error")), \
         patch("services.philosophy_proposal_service.logger") as mock_logger:
        res = await svc.generate_integration_proposal([])
        assert res is None
        mock_logger.exception.assert_called_once_with("[PhilosophyProposal] 統合生成失敗")

    # 空レスポンス
    with patch("model_registry.get_model", return_value="gemini-test"),          patch.object(svc, "_call_gemini", new_callable=AsyncMock, return_value=""):
        res = await svc.generate_integration_proposal([])
        assert res is None


@pytest.mark.asyncio
async def test_get_pending_proposals_edge_cases(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)

    # pending_proposals がリストでない場合
    svc._save_evolution_log({"pending_proposals": "not a list"})
    assert svc.get_pending_proposals() == []

    # 辞書でない要素が含まれている、またはキーが不足している場合
    svc._save_evolution_log({"pending_proposals": [
        "invalid_element",
        {"status": "pending"} # proposal_id, content 欠落
    ]})
    res = svc.get_pending_proposals()
    assert len(res) == 1
    assert isinstance(res[0], PhilosophyProposal)


@pytest.mark.asyncio
async def test_approve_proposal_edge_cases(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)

    # proposal_id が無効（不正な型、空文字）
    assert not svc.approve_proposal(None)
    assert not svc.approve_proposal("")
    assert not svc.approve_proposal("id", edited=123)

    # 提案が存在しない
    svc._save_evolution_log({"pending_proposals": [{"proposal_id": "other_id", "status": "pending"}]})
    assert not svc.approve_proposal("id")

    # 正常承認（編集なし）
    svc._save_evolution_log({"pending_proposals": [
        {"proposal_id": "id", "content": "テスト哲学", "status": "pending"}
    ]})
    assert svc.approve_proposal("id")
    evo = svc._load_evolution_log()
    assert evo["philosophies"][0]["philosophy"] == "テスト哲学"
    assert evo["pending_proposals"][0]["status"] == "approved"

    # 正常承認（編集あり）
    svc._save_evolution_log({
        "pending_proposals": [
            {"proposal_id": "id2", "content": "テスト哲学2", "status": "pending"}
        ],
        "philosophies": []
    })
    assert svc.approve_proposal("id2", edited="編集された哲学")
    evo = svc._load_evolution_log()
    assert evo["philosophies"][0]["philosophy"] == "編集された哲学"
    assert evo["pending_proposals"][0]["status"] == "edited"
    assert evo["pending_proposals"][0]["user_edit"] == "編集された哲学"

    # content が str 以外の場合のフォールバック
    svc._save_evolution_log({
        "pending_proposals": [
            {"proposal_id": "id3", "content": 12345, "status": "pending"}
        ],
        "philosophies": []
    })
    assert svc.approve_proposal("id3")
    evo = svc._load_evolution_log()
    assert evo["philosophies"][0]["philosophy"] == "12345"


@pytest.mark.asyncio
async def test_reject_proposal_edge_cases(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)

    # 引数エラー
    assert not svc.reject_proposal(None, "reason")
    assert not svc.reject_proposal("id", None)
    assert not svc.reject_proposal("", "reason")
    assert not svc.reject_proposal("id", "")

    # 対象不在
    svc._save_evolution_log({"pending_proposals": [{"proposal_id": "other_id", "status": "pending"}]})
    assert not svc.reject_proposal("id", "reason")

    # 正常却下（自動派生あり）
    svc._save_evolution_log({"pending_proposals": [
        {"proposal_id": "id", "content": "却下対象の哲学", "status": "pending"}
    ]})
    assert svc.reject_proposal("id", "長すぎる")
    evo = svc._load_evolution_log()
    assert evo["pending_proposals"][0]["status"] == "rejected"
    assert evo["decision_insights"][0]["reason"] == "長すぎる"
    assert evo["rejection_history"][0]["reason"] == "長すぎる"
    
    # 派生したこだわり提案の存在を確認
    rejection_insights = [p for p in evo["pending_proposals"] if p.get("proposal_type") == "rejection_insight"]
    assert len(rejection_insights) == 1
    assert "長すぎる" in rejection_insights[0]["content"]

    # content が str 以外の場合のフォールバック
    svc._save_evolution_log({"pending_proposals": [
        {"proposal_id": "id2", "content": None, "status": "pending"}
    ]})
    assert svc.reject_proposal("id2", "不要")
    evo = svc._load_evolution_log()
    assert evo["decision_insights"][-1]["original_content"] == ""


@pytest.mark.asyncio
async def test_trim_pending_proposals_edge_cases(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)

    # 上限以内の場合
    svc._save_evolution_log({"pending_proposals": [{"proposal_id": f"p-{i}"} for i in range(10)]})
    svc._trim_pending_proposals()
    evo = svc._load_evolution_log()
    assert len(evo["pending_proposals"]) == 10

    # 上限(50件)を超える場合、解決済み（approved/rejected/edited）から優先削除される
    proposals = []
    # 30件の pending
    for i in range(30):
        proposals.append({"proposal_id": f"pending-{i}", "status": "pending"})
    # 30件の approved (解決済み)
    for i in range(30):
        proposals.append({"proposal_id": f"approved-{i}", "status": "approved"})
    
    svc._save_evolution_log({"pending_proposals": proposals})
    svc._trim_pending_proposals() # 60件 → 50件にトリミング
    
    evo = svc._load_evolution_log()
    assert len(evo["pending_proposals"]) == 50
    # 解決済みが10件削られ、pending 30件 + approved 20件 になっているはず
    statuses = [p["status"] for p in evo["pending_proposals"]]
    assert statuses.count("pending") == 30
    assert statuses.count("approved") == 20

    # 解決済みだけでは足りない場合、pendingも古い順に削られる
    proposals2 = []
    for i in range(60):
        proposals2.append({"proposal_id": f"p-{i}", "status": "pending"})
    
    svc._save_evolution_log({"pending_proposals": proposals2})
    svc._trim_pending_proposals()
    evo2 = svc._load_evolution_log()
    assert len(evo2["pending_proposals"]) == 50
    assert evo2["pending_proposals"][0]["proposal_id"] == "p-10"


@pytest.mark.asyncio
async def test_check_conflict_rules_edge_cases(tmp_path):
    svc = PhilosophyProposalService(evolution_log_path=tmp_path / "evo_log.json")
    
    # 引数異常
    assert svc._check_conflict_rules(None, []) is None
    assert svc._check_conflict_rules("速い", "not a list") is None

    # existing 内の不正型やキー欠落
    existing = [
        "string_element",
        {"no_philosophy_key": "val"},
        {"philosophy": 1234}, # 文字列以外のphilosophy値
        {"philosophy": "控えめな演出"},
        {"text": "遅い演出"}
    ]
    # "派手" ↔ "控えめ"
    res = svc._check_conflict_rules("派手な画面構成", existing)
    assert "方向性の矛盾" in res

    # "速い" ↔ "遅い" (textキーのパス)
    res2 = svc._check_conflict_rules("速い演出", existing)
    assert "方向性の矛盾" in res2


@pytest.mark.asyncio
async def test_check_similar_rejection_edge_cases(tmp_path):
    svc = PhilosophyProposalService(evolution_log_path=tmp_path / "evo_log.json")

    # 引数不正
    assert svc._check_similar_rejection(None) is None

    # 正常一致
    content = "却下される哲学"
    import hashlib
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    
    rejections = [
        "not a dict",
        {"content_hash": "other_hash"},
        {"content_hash": content_hash, "reason": "テスト用"}
    ]
    with patch.object(svc, "_get_past_rejections", return_value=rejections):
        res = svc._check_similar_rejection(content)
        assert res is not None
        assert res["reason"] == "テスト用"


@pytest.mark.asyncio
async def test_gemini_client_fail(tmp_path):
    svc = PhilosophyProposalService(evolution_log_path=tmp_path / "evo_log.json")
    
    # client 取得失敗
    with patch("gemini_client_factory.get_gemini_client", return_value=None):
        res = await svc._call_gemini("model", "prompt")
        assert res is None

    # レスポンスの text パース失敗
    mock_client = MagicMock()
    # response.text を参照した際に AttributeError や TypeError を出すようにする
    mock_client.models.generate_content.return_value = MagicMock(text=None)
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        res = await svc._call_gemini("model", "prompt")
        assert res is None


@pytest.mark.asyncio
async def test_build_proposal_prompt_with_past_rejections(tmp_path):
    svc = PhilosophyProposalService(evolution_log_path=tmp_path / "evo_log.json")
    
    # 過去却下理由が正しく注入されるケース
    rejections = [
        {"reason": "演出が速すぎる"},
        {"reason": "メッセージ性が弱い"},
        "invalid_rejection"
    ]
    with patch.object(svc, "_get_past_rejections", return_value=rejections):
        # philosophies に辞書でない要素（文字列など）が含まれている場合も含める
        prompt = svc._build_proposal_prompt([{"philosophy": "A"}, "string_philosophy"])
        assert "演出が速すぎる" in prompt
        assert "A" in prompt
        assert "string_philosophy" in prompt


@pytest.mark.asyncio
async def test_build_integration_prompt_non_dict_philosophy(tmp_path):
    svc = PhilosophyProposalService(evolution_log_path=tmp_path / "evo_log.json")
    
    # philosophies に辞書でない要素（文字列など）が含まれている場合
    prompt = svc._build_integration_prompt([{"philosophy": "A"}, "string_philosophy"])
    assert "A" in prompt
    assert "string_philosophy" in prompt


@pytest.mark.asyncio
async def test_auto_generate_from_rejection_type_casting(tmp_path):
    svc = PhilosophyProposalService(evolution_log_path=tmp_path / "evo_log.json")
    
    # rejection_reason と original_content が str 以外の場合のキャスト
    svc._auto_generate_from_rejection(1234, None)
    evo = svc._load_evolution_log()
    insight = evo["pending_proposals"][0]
    assert "1234" in insight["content"]
    assert "None" in insight["source_summary"]


@pytest.mark.asyncio
async def test_add_pending_proposal_type_casting(tmp_path):
    svc = PhilosophyProposalService(evolution_log_path=tmp_path / "evo_log.json")
    
    # proposal_type が str 以外の場合のキャスト
    proposal = PhilosophyProposal(
        proposal_id="id",
        content="content",
        source_summary="source",
        generated_at="2026-05-28",
        status="pending"
    )
    svc._add_pending_proposal(proposal, proposal_type=999)
    evo = svc._load_evolution_log()
    assert evo["pending_proposals"][0]["proposal_type"] == "999"


@pytest.mark.asyncio
async def test_generate_proposal_huge_philosophies(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)
    
    # 1000件の巨大な哲学リスト
    huge_philosophies = [{"philosophy": f"哲学-{i}"} for i in range(1000)]
    
    with patch("model_registry.get_model", return_value="gemini-test"), \
         patch.object(svc, "_call_gemini", new_callable=AsyncMock, return_value="新しい哲学の提案"):
        
        with patch.object(svc, "_build_proposal_prompt", wraps=svc._build_proposal_prompt) as mock_build:
            res = await svc.generate_proposal(huge_philosophies)
            assert res is not None
            assert res.content == "新しい哲学の提案"
            
            mock_build.assert_called_once()
            # _build_proposal_prompt 自体の動作を直接呼んで確かめる
            prompt = svc._build_proposal_prompt(huge_philosophies)
            assert "哲学-999" in prompt
            assert "哲学-980" in prompt
            assert "哲学-979" not in prompt


@pytest.mark.asyncio
async def test_trim_pending_proposals_empty_or_none(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)

    # 空の状態でのトリミング
    svc._save_evolution_log({"pending_proposals": []})
    svc._trim_pending_proposals()
    evo = svc._load_evolution_log()
    assert evo["pending_proposals"] == []

    # 何もデータがない（Noneなど）の場合
    svc._save_evolution_log({"pending_proposals": None})  # None を設定すると、ロード時に [] にフォールバックされる
    svc._trim_pending_proposals()
    evo = svc._load_evolution_log()
    assert evo["pending_proposals"] == []


@pytest.mark.asyncio
async def test_load_evolution_log_all_types_forcing(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)
    
    # さまざまな不正データ型を各フィールドに設定してロード
    bad_data_combinations = [
        {"pending_proposals": 123},
        {"philosophies": {"key": "value"}},
        {"decision_insights": None},
        {"rejection_history": "invalid_string"}
    ]
    for bad_data in bad_data_combinations:
        with patch("utils.json_safe_io.safe_load_json", return_value=bad_data):
            data = svc._load_evolution_log()
            assert isinstance(data.get("pending_proposals"), list)
            assert isinstance(data.get("philosophies"), list)
            assert isinstance(data.get("decision_insights"), list)
            assert isinstance(data.get("rejection_history"), list)


@pytest.mark.asyncio
async def test_check_conflict_rules_all_opposites(tmp_path):
    svc = PhilosophyProposalService(evolution_log_path=tmp_path / "evo_log.json")
    
    opposites = [
        ("速い", "遅い"), 
        ("派手", "控えめ"), 
        ("大胆", "慎重"),
        ("シンプル", "複雑"), 
        ("静か", "激しい"), 
        ("明るい", "暗い"),
    ]
    
    for a, b in opposites:
        # a が新提案で、b が既存
        existing = [{"philosophy": f"演出は{b}であるべき"}]
        res = svc._check_conflict_rules(f"もっと{a}な演出にする", existing)
        assert res is not None
        assert "方向性の矛盾" in res
        
        # b が新提案で、a が既存
        existing_rev = [{"philosophy": f"演出は{a}であるべき"}]
        res_rev = svc._check_conflict_rules(f"もっと{b}な演出にする", existing_rev)
        assert res_rev is not None
        assert "方向性の矛盾" in res_rev


@pytest.mark.asyncio
async def test_approve_proposal_proposal_type_handling(tmp_path):
    log_path = tmp_path / "evo_log.json"
    svc = PhilosophyProposalService(evolution_log_path=log_path)

    # 提案が存在し、かつ proposal_type が指定されている場合
    svc._save_evolution_log({
        "pending_proposals": [
            {
                "proposal_id": "integration-id", 
                "content": "統合された哲学", 
                "status": "pending",
                "proposal_type": "integration"
            }
        ]
    })
    assert svc.approve_proposal("integration-id")
    evo = svc._load_evolution_log()
    assert evo["philosophies"][0]["philosophy"] == "統合された哲学"
    assert evo["philosophies"][0]["proposal_id"] == "integration-id"

