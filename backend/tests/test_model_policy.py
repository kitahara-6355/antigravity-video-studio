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


# --- 5. 工程は段に紐づける（2026-08-16） --------------------------------------


def test_a_task_mapped_to_a_tier_resolves_through_it(sandbox, monkeypatch):
    """**モデル名の直書きをやめる。**

    直書きだと入替のたびに全工程を書き換えることになり、実際それで
    `gemini-3-flash-preview` が14工程に居座って腐った。
    """
    config = json.loads(sandbox.joinpath("model_config.json").read_text())
    config["task_mapping"]["telop"] = "premium"
    sandbox.joinpath("model_config.json").write_text(json.dumps(config))

    decision = resolve("telop")

    assert decision.tier == "premium"
    assert decision.model == "m-premium"


def test_swapping_a_tier_model_moves_every_task_on_it(sandbox):
    """**入替は段の1行で済む。** これがトリガー運用を現実的にする。"""
    path = sandbox / "model_config.json"
    config = json.loads(path.read_text())
    config["task_mapping"] = {"a": "premium", "b": "premium"}
    config["text_generation"]["tiers"]["premium"]["model"] = "m-newer"
    path.write_text(json.dumps(config))

    assert resolve("a").model == "m-newer"
    assert resolve("b").model == "m-newer"


# --- 6. 入替トリガーと点検 ----------------------------------------------------


def test_the_four_replacement_triggers_are_declared():
    """**4件そろっていること。** 無料枠の変更は P3 の土台なので外せない。"""
    assert set(model_policy.REPLACEMENT_TRIGGERS) == {
        "price_change", "better_free_model", "free_tier_change", "obsolescence"}


def test_the_free_tier_trigger_explains_why_it_matters():
    text = model_policy.REPLACEMENT_TRIGGERS["free_tier_change"]

    assert "無料枠" in text


def test_an_unverified_model_fails_the_audit(sandbox, monkeypatch):
    """**「確かめられなかった」を緑にしない。**

    一次情報と突き合わせるまで、段のモデルは未検証として落ちる。
    """
    monkeypatch.setattr(model_policy, "live_model_ids",
                        lambda: (set(), "キーがありません"))
    findings, _ = model_policy.audit()

    assert any(f.trigger == "unverified" for f in findings)


def test_a_model_missing_from_the_live_list_is_flagged(sandbox, monkeypatch):
    """**実在しない ID を段に載せたままにしない**（gemini-3-flash-preview の再発防止）。"""
    path = sandbox / "model_config.json"
    config = json.loads(path.read_text())
    for tier in config["text_generation"]["tiers"].values():
        tier["verified"] = True
    path.write_text(json.dumps(config))
    monkeypatch.setattr(model_policy, "live_model_ids",
                        lambda: ({"m-batch", "m-standard", "m-premium"}, ""))

    findings, _ = model_policy.audit()

    assert any(f.trigger == "obsolescence" and f.model == "m-pro"
               for f in findings)


def test_a_verified_and_live_ladder_raises_no_obsolescence(sandbox, monkeypatch):
    """検証済み＆実在するなら、未検証・陳腐化の指摘は出ない。

    単価の指摘はここでは見ない（この足場のモデル名は現物の単価表に無いので
    必ず出る。単価の観点は `test_a_model_missing_from_the_pricing_table` 側）。
    """
    path = sandbox / "model_config.json"
    config = json.loads(path.read_text())
    for tier in config["text_generation"]["tiers"].values():
        tier["verified"] = True
    path.write_text(json.dumps(config))
    monkeypatch.setattr(model_policy, "live_model_ids",
                        lambda: ({"m-batch", "m-standard", "m-premium", "m-pro"}, ""))

    findings, _ = model_policy.audit()

    assert not [f for f in findings
                if f.trigger in ("unverified", "obsolescence")]


def test_a_model_missing_from_the_pricing_table_is_flagged(sandbox, monkeypatch):
    """**単価が無ければ実費を見積もれない。** 最高単価に倒れるのでズレる。"""
    path = sandbox / "model_config.json"
    config = json.loads(path.read_text())
    for tier in config["text_generation"]["tiers"].values():
        tier["verified"] = True
    path.write_text(json.dumps(config))
    monkeypatch.setattr(model_policy, "live_model_ids",
                        lambda: ({"m-batch", "m-standard", "m-premium", "m-pro"}, ""))

    findings, _ = model_policy.audit()

    assert any(f.trigger == "price_change" for f in findings)


def test_the_real_ladder_is_the_approved_pattern():
    """現物が P3（承認された組み合わせ）であること。"""
    table = tiers()

    assert table["premium"]["model"] == "gemini-3.7-flash"
    assert table["standard"]["model"] == "gemini-3.6-flash"
    assert table["batch"]["model"] == "gemini-3.5-flash-lite"
    assert table["pro"]["model"] == "gemini-3.1-pro"
    assert table["pro"]["free_tier"] is False


def test_the_real_ladder_is_not_yet_verified():
    """**未検証であることを、テストでも明示しておく。**

    一次情報がプロキシで遮断されていて突き合わせできなかった（2026-08-16）。
    実キー投入後に `--audit` が通ったら、`verified` を true にしてこの
    テストを反転させる。
    """
    table = tiers()

    assert all(not row.get("verified") for row in table.values()), (
        "検証が済んだなら、このテストを『verified であること』に反転させてください")
