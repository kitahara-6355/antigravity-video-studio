import os
import sys
import json
import uuid
import time
import asyncio
import logging
import importlib
import pytest
from pathlib import Path
from unittest import mock
from dataclasses import dataclass

from services.evolution_trigger_service import (
    EvolutionTriggerService,
    TriggerRule,
    TriggerResult,
)
import services.evolution_trigger_service as ets_module

# ログ無効化（テスト実行時のログノイズ低減）
logging.disable(logging.CRITICAL)


def test_dataclass_initialization():
    """TriggerRule と TriggerResult の基本的なインスタンス化を検証"""
    rule = TriggerRule(
        rule_id="test_rule",
        trigger_type="session_count",
        threshold=5,
        action="upgrade_trust",
        max_delta=0.10,
    )
    assert rule.rule_id == "test_rule"
    assert rule.trigger_type == "session_count"
    assert rule.threshold == 5
    assert rule.action == "upgrade_trust"
    assert rule.max_delta == 0.10

    result = TriggerResult(
        rule_id="test_rule",
        fired=True,
        action="upgrade_trust",
        detail={"status": "ok"},
    )
    assert result.rule_id == "test_rule"
    assert result.fired is True
    assert result.action == "upgrade_trust"
    assert result.detail == {"status": "ok"}
    assert isinstance(result.timestamp, str)


def test_cooldown_seconds_env_fallback():
    """環境変数 EVOLUTION_COOLDOWN_SECONDS が不正な場合にデフォルトの 86400 秒になることを検証"""
    # 正常な値の場合
    with mock.patch.dict(os.environ, {"EVOLUTION_COOLDOWN_SECONDS": "500"}):
        importlib.reload(ets_module)
        assert ets_module._COOLDOWN_SECONDS == 500

    # 不正な値（ValueError）の場合
    with mock.patch.dict(os.environ, {"EVOLUTION_COOLDOWN_SECONDS": "invalid_int"}):
        with mock.patch("services.evolution_trigger_service.logger.warning") as mock_warn:
            importlib.reload(ets_module)
            assert ets_module._COOLDOWN_SECONDS == 86400
            mock_warn.assert_called_once_with(
                "Invalid EVOLUTION_COOLDOWN_SECONDS environment variable. Using default 86400."
            )

    # 後続テストのためにリロードして戻す
    importlib.reload(ets_module)


def test_service_init(tmp_path):
    """EvolutionTriggerService の初期化処理とデフォルト値設定を検証"""
    log_path = tmp_path / "evolution_log.json"
    const_path = tmp_path / "constitution.json"

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
        cooldown_seconds=100,
    )
    assert service._evolution_log_path == log_path
    assert service._constitution_path == const_path
    assert service._cooldown_seconds == 100
    assert len(service._rules) == 4
    assert isinstance(service._background_tasks, set)


def test_get_current_value():
    """各 trigger_type に応じた現在値の取得ロジック（正常系および異常系フォールバック）を検証"""
    service = EvolutionTriggerService()

    # ダミーの evolution_log
    evo_log = {
        "session_count": 12,
        "philosophies": [{"id": 1}, {"id": 2}],
        "rejection_count": 3,
        "approval_count": 4,
    }

    # 1. session_count
    assert service._get_current_value("session_count", evo_log) == 12

    # 2. philosophy_count
    assert service._get_current_value("philosophy_count", evo_log) == 2

    # 3. rejection_count (decision_logger 正常系)
    mock_prefs_rejection = {"こだわり（却下傾向）": {}, "却下パターン": {"pattern1": 2, "pattern2": 5}}
    with mock.patch("decision_logger.decision_logger.get_director_preferences", return_value=mock_prefs_rejection):
        assert service._get_current_value("rejection_count", evo_log) == 5

    # 4. rejection_count (decision_logger 空パターン)
    mock_prefs_empty = {"却下パターン": {}}
    with mock.patch("decision_logger.decision_logger.get_director_preferences", return_value=mock_prefs_empty):
        assert service._get_current_value("rejection_count", evo_log) == 0

    # 5. rejection_count (decision_logger 例外フォールバック)
    with mock.patch("decision_logger.decision_logger.get_director_preferences", side_effect=Exception("mock error")):
        assert service._get_current_value("rejection_count", evo_log) == 3

    # 6. approval_count (decision_logger 正常系)
    mock_prefs_approval = {"好み（承認数）": {"keyword1": 3, "keyword2": 6}}
    with mock.patch("decision_logger.decision_logger.get_director_preferences", return_value=mock_prefs_approval):
        assert service._get_current_value("approval_count", evo_log) == 6

    # 7. approval_count (decision_logger 空パターン)
    mock_prefs_app_empty = {"好み（承認数）": {}}
    with mock.patch("decision_logger.decision_logger.get_director_preferences", return_value=mock_prefs_app_empty):
        assert service._get_current_value("approval_count", evo_log) == 0

    # 8. approval_count (decision_logger 例外フォールバック)
    with mock.patch("decision_logger.decision_logger.get_director_preferences", side_effect=Exception("mock error")):
        assert service._get_current_value("approval_count", evo_log) == 4

    # 9. 不明な trigger_type
    with mock.patch("services.evolution_trigger_service.logger.warning") as mock_warn:
        assert service._get_current_value("unknown_type", evo_log) == 0
        mock_warn.assert_called_once_with("[EvolutionTrigger] Unknown trigger_type: unknown_type")


def test_evaluate_triggers_no_fire(tmp_path):
    """現在値が閾値未満のとき、トリガーが発火しないことを検証"""
    log_path = tmp_path / "evolution_log.json"
    const_path = tmp_path / "constitution.json"

    # 全ての値が閾値未満の初期データ
    evo_log_data = {
        "session_count": 2,          # threshold = 5
        "philosophies": [{"id": 1}],  # threshold = 10
        "rejection_count": 1,        # threshold = 3
        "approval_count": 2,         # threshold = 5
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(evo_log_data, f)
    with open(const_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )

    # 期待されるのは何も発火しないこと
    with mock.patch("decision_logger.decision_logger.get_director_preferences", side_effect=Exception("no logger")):
        result = service.evaluate_triggers()

    assert result["total_fired"] == 0
    assert len(result["fired"]) == 0
    assert len(result["skipped"]) == 4


def test_evaluate_triggers_in_cooldown(tmp_path):
    """トリガー条件を満たしているが、クールダウン期間中のため発火がスキップされることを検証"""
    log_path = tmp_path / "evolution_log.json"
    const_path = tmp_path / "constitution.json"

    # すでに発火履歴があり、現在時刻に非常に近い (cooldown_seconds = 100)
    now = time.time()
    evo_log_data = {
        "session_count": 10,  # 閾値超え
        "trigger_history": [
            {
                "rule_id": "trust_upgrade",
                "fired_at": now - 10,  # 10秒前 (クールダウン中)
                "iso_time": "some_time",
                "detail": {},
            }
        ],
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(evo_log_data, f)
    with open(const_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    # ルールを trust_upgrade だけに限定する
    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
        cooldown_seconds=100,
    )
    service._rules = [
        TriggerRule(
            rule_id="trust_upgrade",
            trigger_type="session_count",
            threshold=5,
            action="upgrade_trust",
            max_delta=0.10,
        )
    ]

    result = service.evaluate_triggers()
    assert result["total_fired"] == 0
    assert "trust_upgrade" in result["skipped"]


def test_evaluate_and_execute_rule_fire_policy(tmp_path):
    """却下3回以上で content_policy アクションが発火し、正常に追加・重複排除されることを検証"""
    log_path = tmp_path / "evolution_log.json"
    const_path = tmp_path / "constitution.json"

    # 初期設定
    evo_log_data = {"rejection_count": 3}
    constitution_data = {"content_policy": ["Avoid 'existing_pattern' adjustments; conflicts with director's preferences."]}
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(evo_log_data, f)
    with open(const_path, "w", encoding="utf-8") as f:
        json.dump(constitution_data, f)

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )
    service._rules = [
        TriggerRule(
            rule_id="reject_policy",
            trigger_type="rejection_count",
            threshold=3,
            action="add_content_policy",
            max_delta=0.0,
        )
    ]

    # 却下パターン: 既存のもの、新規のもの(3回)、閾値未満のもの(2回)
    mock_prefs = {
        "却下パターン": {
            "existing_pattern": 3,
            "new_pattern": 3,
            "ignored_pattern": 2,
        }
    }

    with mock.patch("decision_logger.decision_logger.get_director_preferences", return_value=mock_prefs):
        result = service.evaluate_triggers()

    assert result["total_fired"] == 1
    fired_detail = result["fired"][0]
    assert fired_detail["rule_id"] == "reject_policy"
    assert fired_detail["action"] == "add_content_policy"
    assert "new_pattern" in fired_detail["detail"]["added_policies"]
    assert "existing_pattern" not in fired_detail["detail"]["added_policies"]

    # 保存されたファイルを読み込んで検証
    with open(const_path, "r", encoding="utf-8") as f:
        saved_const = json.load(f)
    assert len(saved_const["content_policy"]) == 2
    assert "Avoid 'new_pattern' adjustments; conflicts with director's preferences." in saved_const["content_policy"]


def test_evaluate_and_execute_rule_fire_keyword(tmp_path):
    """承認5回以上で brand_personality.keywords に正常に追加・重複排除されることを検証"""
    log_path = tmp_path / "evolution_log.json"
    const_path = tmp_path / "constitution.json"

    # 初期設定 (content_policyはなし, brand_personality.keywordsはリストあり)
    evo_log_data = {"approval_count": 5}
    constitution_data = {
        "brand_personality": {
            "keywords": ["existing_keyword"]
        }
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(evo_log_data, f)
    with open(const_path, "w", encoding="utf-8") as f:
        json.dump(constitution_data, f)

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )
    service._rules = [
        TriggerRule(
            rule_id="approve_keyword",
            trigger_type="approval_count",
            threshold=5,
            action="add_keyword",
            max_delta=0.0,
        )
    ]

    # 承認数: 既存のもの(5回), 新規のもの(5回), 閾値未満のもの(4回)
    mock_prefs = {
        "好み（承認数）": {
            "existing_keyword": 5,
            "new_keyword": 5,
            "ignored_keyword": 4,
        }
    }

    with mock.patch("decision_logger.decision_logger.get_director_preferences", return_value=mock_prefs):
        result = service.evaluate_triggers()

    assert result["total_fired"] == 1
    fired_detail = result["fired"][0]
    assert fired_detail["rule_id"] == "approve_keyword"
    assert "new_keyword" in fired_detail["detail"]["added_keywords"]
    assert "existing_keyword" not in fired_detail["detail"]["added_keywords"]

    with open(const_path, "r", encoding="utf-8") as f:
        saved_const = json.load(f)
    assert len(saved_const["brand_personality"]["keywords"]) == 2
    assert "new_keyword" in saved_const["brand_personality"]["keywords"]


def test_evaluate_and_execute_rule_fire_trust(tmp_path):
    """trust_upgrade アクションで trust_score が正常に加算されること、上限1.0、および型エラー時リセットを検証"""
    log_path = tmp_path / "evolution_log.json"
    const_path = tmp_path / "constitution.json"

    # 初期設定 (正常系: 0.85 + 0.10 -> 0.95)
    evo_log_data = {"session_count": 5, "trust_score": 0.85}
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(evo_log_data, f)
    with open(const_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )
    service._rules = [
        TriggerRule(
            rule_id="trust_upgrade",
            trigger_type="session_count",
            threshold=5,
            action="upgrade_trust",
            max_delta=0.10,
        )
    ]

    result = service.evaluate_triggers()
    assert result["total_fired"] == 1
    assert result["fired"][0]["detail"]["new_trust"] == 0.95

    # 上限1.0の検証 (0.95 + 0.10 -> 1.0)
    # クールダウンを回避するため rules_status から再度評価か、ファイルを書き換えて再ロード
    evo_log_data = {"session_count": 5, "trust_score": 0.95}
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(evo_log_data, f)

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )
    service._rules = [
        TriggerRule(
            rule_id="trust_upgrade",
            trigger_type="session_count",
            threshold=5,
            action="upgrade_trust",
            max_delta=0.10,
        )
    ]
    result = service.evaluate_triggers()
    assert result["total_fired"] == 1
    assert result["fired"][0]["detail"]["new_trust"] == 1.0

    # 不正な型の検証 (文字列 "invalid" -> 0.0 + 0.10 -> 0.10)
    evo_log_data = {"session_count": 5, "trust_score": "invalid"}
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(evo_log_data, f)

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )
    service._rules = [
        TriggerRule(
            rule_id="trust_upgrade",
            trigger_type="session_count",
            threshold=5,
            action="upgrade_trust",
            max_delta=0.10,
        )
    ]
    result = service.evaluate_triggers()
    assert result["total_fired"] == 1
    assert result["fired"][0]["detail"]["new_trust"] == 0.10


@pytest.mark.asyncio
async def test_evaluate_and_execute_rule_fire_integrate_async(tmp_path):
    """イベントループ実行中に philosophy_integration アクションが呼ばれ、非同期タスクが正常にキューされることを検証"""
    log_path = tmp_path / "evolution_log.json"
    const_path = tmp_path / "constitution.json"

    philosophies = [{"id": i} for i in range(10)]
    evo_log_data = {"philosophies": philosophies}
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(evo_log_data, f)
    with open(const_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )
    service._rules = [
        TriggerRule(
            rule_id="philosophy_integration",
            trigger_type="philosophy_count",
            threshold=10,
            action="integrate",
            max_delta=0.0,
        )
    ]

    # PhilosophyProposalService のモック
    mock_proposal_svc_instance = mock.MagicMock()
    # 非同期メソッドのモック
    async def dummy_generate(*args):
        return mock.MagicMock(proposal_id="proposal_123")
    mock_proposal_svc_instance.generate_integration_proposal = mock.Mock(side_effect=dummy_generate)

    with mock.patch("services.philosophy_proposal_service.PhilosophyProposalService", return_value=mock_proposal_svc_instance):
        result = service.evaluate_triggers()

    assert result["total_fired"] == 1
    detail = result["fired"][0]["detail"]
    assert detail["integration_triggered"] is True
    assert detail["integration_status"] == "async_queued"
    assert len(service._background_tasks) == 1

    # タスクの終了を待つ
    task = list(service._background_tasks)[0]
    await task
    assert len(service._background_tasks) == 0


def test_evaluate_and_execute_rule_fire_integrate_sync(tmp_path):
    """イベントループがない環境で philosophy_integration アクションが呼ばれ、同期的に実行が完了することを検証"""
    log_path = tmp_path / "evolution_log.json"
    const_path = tmp_path / "constitution.json"

    philosophies = [{"id": i} for i in range(10)]
    evo_log_data = {"philosophies": philosophies}
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(evo_log_data, f)
    with open(const_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )
    service._rules = [
        TriggerRule(
            rule_id="philosophy_integration",
            trigger_type="philosophy_count",
            threshold=10,
            action="integrate",
            max_delta=0.0,
        )
    ]

    # PhilosophyProposalService のモック
    mock_proposal_svc_instance = mock.MagicMock()
    async def dummy_generate(*args):
        proposal = mock.MagicMock()
        proposal.proposal_id = "proposal_123"
        return proposal
    mock_proposal_svc_instance.generate_integration_proposal = mock.Mock(side_effect=dummy_generate)

    # get_running_loop() が例外を発生させる状況をモックし、loop.run_until_completeも動かないように loop = None にする
    with mock.patch("services.philosophy_proposal_service.PhilosophyProposalService", return_value=mock_proposal_svc_instance):
        with mock.patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            result = service.evaluate_triggers()

    assert result["total_fired"] == 1
    detail = result["fired"][0]["detail"]
    assert detail["integration_triggered"] is True
    assert detail["integration_status"] == "completed"
    assert detail["proposal_id"] == "proposal_123"


def test_evaluate_and_execute_rule_fire_integrate_exception(tmp_path):
    """philosophy_integration 処理中に例外が発生した場合の例外ハンドリングを検証"""
    log_path = tmp_path / "evolution_log.json"
    const_path = tmp_path / "constitution.json"

    philosophies = [{"id": i} for i in range(10)]
    evo_log_data = {"philosophies": philosophies}
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(evo_log_data, f)
    with open(const_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )
    service._rules = [
        TriggerRule(
            rule_id="philosophy_integration",
            trigger_type="philosophy_count",
            threshold=10,
            action="integrate",
            max_delta=0.0,
        )
    ]

    # インポート時に例外を投げるようにモックする
    with mock.patch("services.philosophy_proposal_service.PhilosophyProposalService", side_effect=ImportError("Failed to import")):
        result = service.evaluate_triggers()

    assert result["total_fired"] == 1
    detail = result["fired"][0]["detail"]
    assert detail["integration_triggered"] is True
    assert detail["integration_status"] == "error"
    assert "Failed to import" in detail["error"]


def test_trim_trust_history():
    """trust_history が 100件を超える場合、古いものからトリミングされることを検証"""
    service = EvolutionTriggerService()
    # 105件の履歴
    history = [{"index": i} for i in range(105)]
    evo_log = {"trust_history": history}

    service._trim_trust_history(evo_log)
    assert len(evo_log["trust_history"]) == 100
    # スライスされて最新の100件（インデックス5から104）が保持されること
    assert evo_log["trust_history"][0]["index"] == 5
    assert evo_log["trust_history"][-1]["index"] == 104


def test_emit_notification_fallback():
    """emit_notification 内でのフォーマット文字列変換例外時にフォールバックメッセージが使われることを検証"""
    service = EvolutionTriggerService()
    evo_log = {"notifications": []}

    # キーワード引数展開で例外を起こすため、異常な型の detail を渡す
    # (new_trust に format 変換できない特殊オブジェクトを突っ込む)
    class BrokenFormat:
        def __str__(self):
            raise TypeError("broken format")

    detail = {"new_trust": BrokenFormat()}

    # 例外時に message_template (例: "trust_scoreが{new_trust}に昇格しました") がそのまま message にフォールバックされる
    service._append_trigger_notification("trust_upgrade", detail, evo_log)
    assert len(evo_log["notifications"]) == 1
    notification = evo_log["notifications"][0]
    assert "trust_scoreが{new_trust}に昇格しました" in notification["message"]


def test_update_director_profile_fallback():
    """update_director_profile にて、preferences取得の例外や辞書でない場合でもフォールバック構築されることを検証"""
    service = EvolutionTriggerService()
    evo_log = {"session_count": 8, "director_profile": {}}

    # 1. 辞書でないオブジェクトが返されたときの TypeError 例外ハンドリング
    with mock.patch("decision_logger.decision_logger.get_director_preferences", return_value="not_a_dict"):
        service._update_director_profile(evo_log)
        profile = evo_log["director_profile"]
        assert profile["total_decisions"] == 8
        assert profile["approval_rate"] == 0.0

    # 2. キーの値が不正な型（文字列）の場合のフォールバック
    mock_prefs = {
        "こだわり（却下傾向）": {"p1": 1},
        "好み（承認傾向）": "not_a_dict",
        "承認率": "invalid_float",
        "総判断数": "invalid_int",
    }
    with mock.patch("decision_logger.decision_logger.get_director_preferences", return_value=mock_prefs):
        service._update_director_profile(evo_log)
        profile = evo_log["director_profile"]
        assert profile["rejection_tendencies"] == {"p1": 1}
        assert profile["approval_tendencies"] == {}
        assert profile["approval_rate"] == 0.0
        assert profile["total_decisions"] == 0


def test_file_io_error_handling(tmp_path):
    """ファイルの読み書き処理において例外が発生した際のフォールバックおよびエラーハンドリングを検証"""
    log_path = tmp_path / "broken_log.json"
    const_path = tmp_path / "broken_constitution.json"

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )

    # 1. _load_evolution_log でファイルが破損している (JSONDecodeError 等) 際のデフォルト辞書返却
    with open(log_path, "w") as f:
        f.write("invalid json")
    data = service._load_evolution_log()
    assert isinstance(data, dict)
    assert data["trust_score"] == 0.0
    assert len(data["philosophies"]) == 0

    # 2. _load_constitution でファイルが破損している際の空辞書返却
    with open(const_path, "w") as f:
        f.write("invalid json")
    data_const = service._load_constitution()
    assert data_const == {}

    # 3. _load_constitution でファイルが存在しない際の空辞書返却
    if const_path.exists():
        const_path.unlink()
    data_const_missing = service._load_constitution()
    assert data_const_missing == {}

    # 4. _save_evolution_log において保存処理例外が発生してもクラッシュしないこと
    with mock.patch("utils.json_safe_io.safe_save_json", side_effect=OSError("Disk Full")):
        with mock.patch("services.evolution_trigger_service.logger.error") as mock_err:
            service._save_evolution_log({"some": "data"})
            mock_err.assert_called_once_with("[EvolutionTrigger] evolution_log 保存失敗: Disk Full")

    # 5. _save_constitution において保存処理例外が発生してもクラッシュしないこと
    with mock.patch("builtins.open", side_effect=OSError("Permission Denied")):
        with mock.patch("services.evolution_trigger_service.logger.error") as mock_err:
            service._save_constitution({"some": "data"})
            mock_err.assert_called_once()
            assert "constitution 保存失敗" in mock_err.call_args[0][0]


def test_execute_action_exception():
    """_execute_action 内部でアクション実行中に予期せぬ例外が発生しても、クラッシュせず結果にエラー詳細が格納されることを検証"""
    service = EvolutionTriggerService()
    # 存在しない未知のアクションやバグを模擬するため、アクションのメソッド自体をモックで例外にする
    rule = TriggerRule(
        rule_id="broken_rule",
        trigger_type="session_count",
        threshold=5,
        action="broken_action",
        max_delta=0.10,
    )
    evo_log = {}
    constitution = {}

    with mock.patch.object(service, "_upgrade_trust_score", side_effect=RuntimeError("critical error")):
        # アクションが不明な場合
        result = service._execute_action(rule, evo_log, constitution)
        assert result.rule_id == "broken_rule"
        assert result.detail == {"error": "unknown action: broken_action"}

        # アクションメソッドが例外を投げる場合
        rule.action = "upgrade_trust"
        result_err = service._execute_action(rule, evo_log, constitution)
        assert result_err.rule_id == "broken_rule"
        assert result_err.detail == {"error": "critical error"}


def test_get_trigger_status():
    """get_trigger_status が全トリガーの現在値、閾値、進行率、クールダウン状況を正しく返すことを検証"""
    service = EvolutionTriggerService()
    # ダミーデータ
    evo_log = {
        "session_count": 2,  # threshold = 5, progress = 0.4
        "trigger_history": [
            {
                "rule_id": "reject_policy",
                "fired_at": time.time(), # cooldown
                "iso_time": "some_time",
                "detail": {},
            }
        ]
    }

    # 各カウントのモック
    with mock.patch.object(service, "_load_evolution_log", return_value=evo_log):
        with mock.patch.object(service, "_get_max_rejection_count", return_value=0):
            with mock.patch.object(service, "_get_max_approval_count", return_value=0):
                status = service.get_trigger_status()

    rules = status["rules"]
    assert len(rules) == 4

    # reject_policy (cooldownチェック)
    reject_rule = next(r for r in rules if r["rule_id"] == "reject_policy")
    assert reject_rule["in_cooldown"] is True

    # trust_upgrade
    trust_rule = next(r for r in rules if r["rule_id"] == "trust_upgrade")
    assert trust_rule["current_value"] == 2
    assert trust_rule["threshold"] == 5
    assert trust_rule["progress_pct"] == 0.4
    assert trust_rule["in_cooldown"] is False


def test_action_add_content_policy_missing_keys_and_exception(tmp_path):
    """constitution に content_policy がない場合の初期化と、preferences取得例外時のフォールバックを検証"""
    import json
    from unittest import mock
    from services.evolution_trigger_service import EvolutionTriggerService
    log_path = tmp_path / "evolution_log.json"
    const_path = tmp_path / "constitution.json"

    # content_policy キーがない constitution
    with open(const_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )

    # preferences 例外発生時
    with mock.patch("decision_logger.decision_logger.get_director_preferences", side_effect=Exception("mock error")):
        result = service._append_content_policy_to_constitution(constitution={})
        assert result["added_policies"] == []
        assert result["total_policies"] == 0

    # 正常に constitution["content_policy"] が初期化されることを検証
    constitution = {}
    with mock.patch("decision_logger.decision_logger.get_director_preferences", return_value={"却下パターン": {"pattern1": 3}}):
        result = service._append_content_policy_to_constitution(constitution)
        assert result["added_policies"] == ["pattern1"]
        assert constitution["content_policy"] == [
            "Avoid 'pattern1' adjustments; conflicts with director's preferences."
        ]


def test_action_add_keyword_missing_keys_and_exception(tmp_path):
    """constitution に brand_personality / keywords がない場合の初期化と、preferences取得例外時のフォールバックを検証"""
    from unittest import mock
    from services.evolution_trigger_service import EvolutionTriggerService
    log_path = tmp_path / "evolution_log.json"
    const_path = tmp_path / "constitution.json"

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )

    # preferences 例外発生時
    with mock.patch("decision_logger.decision_logger.get_director_preferences", side_effect=Exception("mock error")):
        result = service._append_keyword_to_constitution(constitution={})
        assert result["added_keywords"] == []

    # 正常に constitution["brand_personality"]["keywords"] が初期化されることを検証
    constitution = {}
    with mock.patch("decision_logger.decision_logger.get_director_preferences", return_value={"好み（承認数）": {"keyword1": 5}}):
        result = service._append_keyword_to_constitution(constitution)
        assert result["added_keywords"] == ["keyword1"]
        assert constitution["brand_personality"]["keywords"] == ["keyword1"]


def test_run_sync_philosophy_proposal_with_non_running_loop(tmp_path):
    """ループは存在するが動いていない（is_closed が False の）状況下での同期実行を検証"""
    import asyncio
    from unittest import mock
    from services.evolution_trigger_service import EvolutionTriggerService
    log_path = tmp_path / "evolution_log.json"
    const_path = tmp_path / "constitution.json"

    service = EvolutionTriggerService(
        evolution_log_path=log_path,
        constitution_path=const_path,
    )

    mock_proposal_svc_instance = mock.MagicMock()
    async def dummy_generate(*args):
        proposal = mock.MagicMock()
        proposal.proposal_id = "proposal_non_running"
        return proposal
    mock_proposal_svc_instance.generate_integration_proposal = mock.Mock(side_effect=dummy_generate)

    mock_loop = mock.MagicMock(spec=asyncio.AbstractEventLoop)
    mock_loop.is_closed.return_value = False
    
    # loop.run_until_complete がモックの proposal を返すように設定
    mock_loop.run_until_complete.side_effect = lambda coro: asyncio.run(coro)

    result = service._run_sync_philosophy_proposal(
        proposal_service=mock_proposal_svc_instance,
        philosophies=[],
        loop=mock_loop,
    )
    assert result["integration_status"] == "completed"
    assert result["proposal_id"] == "proposal_non_running"


def test_is_in_cooldown_with_expired_entry():
    """クールダウン期間が経過した履歴エントリが存在する場合に _is_in_cooldown が False を返すことを検証"""
    import time
    from services.evolution_trigger_service import EvolutionTriggerService
    service = EvolutionTriggerService(cooldown_seconds=100)
    now = time.time()
    evo_log = {
        "trigger_history": [
            {
                "rule_id": "test_rule",
                "fired_at": now - 200,  # 200秒前 (クールダウン切れ)
                "iso_time": "some_time",
                "detail": {},
            }
        ]
    }
    assert service._is_in_cooldown("test_rule", evo_log) is False


def test_load_evolution_log_exception(tmp_path):
    """safe_load_json が例外を投げる状況下での警告ログ出力とデフォルト辞書の構築を検証"""
    from unittest import mock
    from services.evolution_trigger_service import EvolutionTriggerService
    log_path = tmp_path / "broken_log.json"
    service = EvolutionTriggerService(evolution_log_path=log_path)

    with mock.patch("utils.json_safe_io.safe_load_json", side_effect=RuntimeError("read error")):
        with mock.patch("services.evolution_trigger_service.logger.warning") as mock_warn:
            data = service._load_evolution_log()
            mock_warn.assert_called_once()
            assert "read error" in mock_warn.call_args[0][0]
            assert isinstance(data, dict)
            assert data["trust_score"] == 0.0
