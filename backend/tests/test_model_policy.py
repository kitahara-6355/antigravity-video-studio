"""適用モデルの見える化と、工程ごとの昇格（ユーザー要件・2026-08-15）。

守りたい性質:

1. **どの工程がどのモデルで動くか、根拠つきで言える**（見える化）
2. **不満なら1段上げられる。** 理由なしには上げられない
3. **自動では上がらない。** 昇格はユーザーの指示だけ（課金が増えるため）
4. 段の並びの正典は `model_config.json` の1か所だけ
"""
from __future__ import annotations

import json

import pytest

from backend import model_policy
from backend.model_policy import (
    Decision,
    UnknownTier,
    resolve,
    tier_order,
    tiers,
)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """現物の設定を触らずに試す。"""
    config = {
        "text_generation": {
            "default_model": "m-standard",
            "tier_order": ["batch", "standard", "premium", "pro"],
            "tiers": {
                "batch": {"model": "m-batch"},
                "standard": {"model": "m-standard"},
                "premium": {"model": "m-premium"},
                "pro": {"model": "m-pro"},
            },
        },
        "task_mapping": {"telop": "m-premium", "chunk": "m-batch"},
    }
    path = tmp_path / "model_config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(model_policy, "CONFIG_PATH", path)
    monkeypatch.setattr(model_policy, "OVERRIDES_PATH",
                        tmp_path / "model_overrides.json")
    monkeypatch.setattr(model_policy, "HISTORY_PATH", tmp_path / "history.jsonl")
    return tmp_path


# --- 1. 見える化 --------------------------------------------------------------


def test_every_task_reports_its_model_and_why(sandbox):
    """**どのモデルで動くかと、その根拠**が必ず言える。"""
    decision = resolve("telop")

    assert decision.model == "m-premium"
    assert decision.tier == "premium"
    assert decision.source == "task_mapping"


def test_an_unmapped_task_falls_back_to_the_default_and_says_so(sandbox):
    decision = resolve("知らない工程")

    assert decision.model == "m-standard"
    assert decision.source == "tier_default"


def test_a_user_override_is_marked_as_such(sandbox):
    """**誰が決めたのかが分かる。** 既定と指定を混ぜない。"""
    model_policy.set_tier("telop", "pro", "硬いので上げた")

    decision = resolve("telop")

    assert decision.source == "user_override"
    assert decision.reason == "硬いので上げた"


def test_all_known_tasks_are_listed(sandbox):
    assert set(model_policy.known_tasks()) == {"telop", "chunk"}


# --- 2. 昇格 ------------------------------------------------------------------


def test_escalation_moves_exactly_one_rung(sandbox):
    """batch → standard。**一気に最上段へ飛ばさない。**"""
    after = model_policy.escalate("chunk", "粗い")

    assert after.tier == "standard"
    assert after.model == "m-standard"


def test_escalation_from_premium_reaches_pro(sandbox):
    """**昇格先が存在すること。** 追加前は premium が天井で上げ先が無かった。"""
    after = model_policy.escalate("telop", "提案が硬い")

    assert after.tier == "pro"


def test_escalation_requires_a_reason(sandbox):
    """理由が無いと、あとで効果を検証できない。"""
    with pytest.raises(ValueError):
        model_policy.escalate("telop", "   ")


def test_escalation_at_the_top_is_refused_with_an_explanation(sandbox):
    model_policy.set_tier("telop", "pro", "上げた")

    with pytest.raises(ValueError, match="最上段"):
        model_policy.escalate("telop", "もっと上げたい")


def test_de_escalation_moves_down(sandbox):
    after = model_policy.de_escalate("telop", "batch で十分")

    assert after.tier == "standard"


def test_reset_returns_to_the_default(sandbox):
    model_policy.set_tier("telop", "pro", "上げた")

    after = model_policy.reset("telop")

    assert after.source == "task_mapping"
    assert after.model == "m-premium"


# --- 3. 履歴（いつ・なぜ動かしたか） ------------------------------------------


def test_every_change_is_recorded_with_its_reason(sandbox):
    model_policy.escalate("telop", "提案が硬い")
    model_policy.de_escalate("telop", "戻す")

    rows = model_policy.history("telop")

    assert [r["action"] for r in rows] == ["escalate", "de_escalate"]
    assert rows[0]["reason"] == "提案が硬い"
    assert rows[0]["from"]["tier"] == "premium"
    assert rows[0]["to"]["tier"] == "pro"


# --- 4. 段の正典は1つ ---------------------------------------------------------


def test_the_tier_order_comes_from_the_config(sandbox):
    """**並びをコード側に持たない**（持つと台帳が2つになる）。"""
    assert tier_order() == ("batch", "standard", "premium", "pro")


def test_an_unknown_tier_is_refused(sandbox):
    """**黙って既定値に落とさない。**"""
    with pytest.raises(UnknownTier):
        model_policy.set_tier("telop", "でっちあげ", "理由")


def test_the_real_config_has_a_rung_above_premium():
    """現物の設定に**昇格先がある**こと。

    2026-08-15 に発見: 全工程が premium に張り付いており、
    「不満なら上げる」の上げ先が存在しなかった。
    """
    order = tier_order()
    table = tiers()

    assert order[-1] in table
    assert order.index("premium") < len(order) - 1, (
        "premium が最上段だと昇格できません。上の段を足してください")


def test_the_real_config_lists_every_pipeline_task():
    """現物で全工程が引けること（見える化の前提）。"""
    for task in model_policy.known_tasks():
        decision = resolve(task)
        assert isinstance(decision, Decision)
        assert decision.model
