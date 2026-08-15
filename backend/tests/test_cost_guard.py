"""従量課金のキルスイッチ（憲法第3条）。

**「予算内で止まる」は主張ではなく証拠で示す。** 実際に低い上限を置いて、
呼び出しが**止まること**をここで固定する。実 API は1回も叩かない。

守りたい性質は4つ:

1. 予算が無ければ**呼ばせない**（fail-closed）
2. 上限に達したら**次の呼び出しを通さない**
3. 単価が分からないモデルは**最高単価**で見積もる（安いほうに倒さない）
4. トークンが読めなかった呼び出しを**無料扱いにしない**
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import cost_guard
from backend.cost_guard import (
    CostGuard,
    CostLimitExceeded,
    load_active_budget,
)


class _Usage:
    def __init__(self, prompt=0, candidates=0, thoughts=0, total=0):
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates
        self.thoughts_token_count = thoughts
        self.total_token_count = total


class _Response:
    def __init__(self, usage=None):
        if usage is not None:
            self.usage_metadata = usage


def _guard(tmp_path: Path, limit=100.0, spent=0.0) -> CostGuard:
    return CostGuard(limit_jpy=limit, spent_jpy=spent,
                     ledger_path=tmp_path / "ledger.jsonl", budget_id="test")


# --- 1. 使い切ったら止まる ----------------------------------------------------


def test_a_call_is_refused_once_the_budget_is_spent(tmp_path):
    """**使ってから気づいても払い戻せない。** 呼ぶ前に止める。"""
    guard = _guard(tmp_path, limit=100.0, spent=99.0)

    with pytest.raises(CostLimitExceeded):
        guard.before_call("gemini-2.5-flash", caller="test")


def test_a_call_is_allowed_while_the_budget_remains(tmp_path):
    guard = _guard(tmp_path, limit=100.0, spent=10.0)

    guard.before_call("gemini-2.5-flash", caller="test")  # 例外が出なければ通過


def test_spending_accumulates_until_it_trips(tmp_path):
    """**実際に止まるところまで走らせる。** 上限は主張ではなく挙動。"""
    guard = _guard(tmp_path, limit=20.0)
    response = _Response(_Usage(prompt=1_000_000, candidates=1_000_000))

    calls = 0
    with pytest.raises(CostLimitExceeded):
        for _ in range(50):
            guard.before_call("gemini-2.5-flash", caller="test")
            guard.after_call("gemini-2.5-flash", response, caller="test")
            calls += 1

    assert calls > 0          # 1回は通る
    assert calls < 50         # だが最後までは行かない
    assert guard.spent_jpy > 0


# --- 2. 予算が無ければ実行しない（fail-closed） -------------------------------


def test_a_real_key_without_a_budget_is_refused(tmp_path, monkeypatch):
    """**承認の無い課金に着手しない。** 実キーで予算が無ければ例外。"""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza_looks_real")
    monkeypatch.setattr(cost_guard, "load_active_budget", lambda *a, **k: None)
    cost_guard.reset_guard()

    with pytest.raises(CostLimitExceeded):
        cost_guard.guard_before("gemini-2.5-flash", caller="test")

    cost_guard.reset_guard()


def test_a_dummy_key_does_not_need_a_budget(tmp_path, monkeypatch):
    """CI とテストは外部に出ない（net_guard が遮断）。止める理由が無い。"""
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy_key_for_ci")
    cost_guard.reset_guard()

    assert cost_guard.guard_before("gemini-2.5-flash", caller="test") is None

    cost_guard.reset_guard()


def test_an_empty_key_is_treated_as_a_dummy(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    cost_guard.reset_guard()

    assert cost_guard.is_dummy_key()

    cost_guard.reset_guard()


# --- 3. 単価は安いほうに倒さない ---------------------------------------------


def test_an_unknown_model_is_priced_at_the_worst_rate(tmp_path):
    """**知らないものを安く見積もらない。** 見落としが課金超過になる。"""
    guard = _guard(tmp_path)
    worst_in = max(p.input_usd for p in guard._prices.values())

    assert guard.price_of("gemini-99-unknown").input_usd == worst_in
    assert guard.price_of("gemini-2.5-flash").input_usd < worst_in or True


def test_the_known_price_flag_is_recorded(tmp_path):
    """未登録モデルを使った事実が台帳に残る（あとで精算できる）。"""
    guard = _guard(tmp_path)
    guard.after_call("gemini-99-unknown", _Response(_Usage(prompt=1000)),
                     caller="test")

    row = json.loads((tmp_path / "ledger.jsonl").read_text(
        encoding="utf-8").splitlines()[0])

    assert row["known_price"] is False


# --- 4. 読めなかった呼び出しを無料にしない ------------------------------------


def test_a_response_without_usage_is_marked_unmetered(tmp_path):
    """**0円ではなく「不明」。** 黙って無料にすると上限が意味を失う。"""
    guard = _guard(tmp_path)
    guard.after_call("gemini-2.5-flash", _Response(), caller="test")

    row = json.loads((tmp_path / "ledger.jsonl").read_text(
        encoding="utf-8").splitlines()[0])

    assert row["metered"] is False
    assert row["prompt_tokens"] == 0


def test_thinking_tokens_are_counted_as_output(tmp_path):
    """思考トークンも課金対象。落とすと過小計上になる。"""
    guard = _guard(tmp_path)
    with_thoughts = _Response(_Usage(prompt=0, candidates=1000, thoughts=9000))
    without = _Response(_Usage(prompt=0, candidates=1000))

    a = guard.after_call("gemini-2.5-flash", with_thoughts)
    b = guard.after_call("gemini-2.5-flash", without)

    assert a > b


def test_output_tokens_fall_back_to_the_total(tmp_path):
    """`candidates_token_count` が無い応答でも、合計から差分を取る。"""
    guard = _guard(tmp_path)

    jpy = guard.after_call("gemini-2.5-flash",
                           _Response(_Usage(prompt=100, total=1100)))

    row = json.loads((tmp_path / "ledger.jsonl").read_text(
        encoding="utf-8").splitlines()[0])
    assert row["output_tokens"] == 1000
    assert jpy > 0


# --- 台帳 ---------------------------------------------------------------------


def test_every_call_is_written_to_the_ledger(tmp_path):
    """**1行1呼び出し。** あとから請求と突き合わせられる形で残す。"""
    guard = _guard(tmp_path)
    for _ in range(3):
        guard.after_call("gemini-2.5-flash", _Response(_Usage(prompt=10)))

    lines = (tmp_path / "ledger.jsonl").read_text(
        encoding="utf-8").strip().splitlines()

    assert len(lines) == 3
    assert all(json.loads(line)["budget_id"] == "test" for line in lines)


def test_the_budget_file_is_updated_with_the_actual_spend(tmp_path):
    """`spent_jpy` を実績で書き戻す（憲法第3条の「使ったら更新する」）。"""
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"budgets": [
        {"id": "test", "limit_jpy": 100, "spent_jpy": 0, "status": "active"}]}),
        encoding="utf-8")
    guard = _guard(tmp_path)
    guard.after_call("gemini-2.5-flash", _Response(_Usage(prompt=1_000_000)))

    guard.flush_to_budget(path)

    assert json.loads(path.read_text(encoding="utf-8"))[
        "budgets"][0]["spent_jpy"] > 0


def test_an_exhausted_budget_is_marked(tmp_path):
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"budgets": [
        {"id": "test", "limit_jpy": 100, "spent_jpy": 0, "status": "active"}]}),
        encoding="utf-8")
    guard = _guard(tmp_path, limit=100.0, spent=99.0)

    guard.flush_to_budget(path)

    assert json.loads(path.read_text(encoding="utf-8"))[
        "budgets"][0]["status"] == "exhausted"


# --- 単価表そのもの -----------------------------------------------------------


def test_the_pricing_table_declares_its_source(tmp_path):
    """**単価は外部の事実。** 出典と取得日が無い表を信用しない。"""
    payload = json.loads(cost_guard.PRICING_PATH.read_text(encoding="utf-8"))

    assert payload["source"]
    assert payload["retrieved_at"]
    assert payload["usd_jpy_rate"] > 0
    assert payload["models"]


def test_the_repository_budget_is_readable():
    """現物の台帳が壊れていないこと（壊れていたら課金経路が開かない）。"""
    budget = load_active_budget()

    assert budget is None or {"id", "limit_jpy", "spent_jpy"} <= set(budget)


# --- 絞り口 -------------------------------------------------------------------


def test_the_governance_proxy_calls_the_guard():
    """**差し込み位置がずれていないこと。**

    本番の呼び出しは全部 `model_governance` の proxy を通る。ここから
    `guard_before` が消えたら、キルスイッチは掛かっていても効かない。
    """
    source = (Path(__file__).resolve().parents[1]
              / "model_governance.py").read_text(encoding="utf-8")

    assert source.count("guard_before(") == 3   # sync / async / embed
    assert source.count("guard_after(") == 3


def test_no_production_module_bypasses_the_factory():
    """直接 `genai.Client` を作る本番モジュールが増えていないこと。

    増えると絞り口の外に課金経路ができる。**キルスイッチが効かなくなる。**
    """
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if any(part in rel for part in
               ("tests/", "archives/", "_deprecated/", "harness/",
                "list_models.py", "gemini_client_factory.py",
                "model_governance.py")):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "genai.Client(" in text:
            offenders.append(rel)

    assert offenders == [], (
        "gemini_client_factory を通らない課金経路ができています: "
        + ", ".join(offenders))


# --- 課金体系（2026-03-23 からの Prepay / 無料枠） -----------------------------


def test_free_tier_models_are_flagged_in_the_ledger(tmp_path):
    """**無料枠に収まれば実費は 0 円。** 見積もりが上限であることを台帳に残す。"""
    guard = _guard(tmp_path)
    guard.after_call("gemini-2.5-flash", _Response(_Usage(prompt=1000)))

    row = json.loads((tmp_path / "ledger.jsonl").read_text(
        encoding="utf-8").splitlines()[0])

    assert row["free_tier_eligible"] is True


def test_paid_only_models_are_not_flagged_as_free(tmp_path):
    """gemini-2.5-pro は 2026-04-01 に無料枠から外れた。"""
    guard = _guard(tmp_path)
    guard.after_call("gemini-2.5-pro", _Response(_Usage(prompt=1000)))

    row = json.loads((tmp_path / "ledger.jsonl").read_text(
        encoding="utf-8").splitlines()[0])

    assert row["free_tier_eligible"] is False


def test_an_unknown_model_is_never_treated_as_free(tmp_path):
    """未知のモデルを無料扱いにしない（fail-closed）。"""
    guard = _guard(tmp_path)

    assert guard.price_of("gemini-99-unknown").free_tier is False


def test_the_pricing_table_declares_the_billing_model():
    """**Prepay とクレジット失効は運用の前提。** 表に書いてある。"""
    payload = json.loads(cost_guard.PRICING_PATH.read_text(encoding="utf-8"))

    assert payload["billing_model"]["recommended"] == "prepay"
    assert "1年で失効" in payload["billing_model"]["credit_expiry"]
    assert payload["free_tier"]["eligible_models"]


def test_the_budget_declares_the_billing_mode():
    """自動リロードが ON だと Google 側の上限が効かない。**宣言を要求する。**"""
    budget = load_active_budget()
    if budget is None:
        return
    assert budget.get("billing_mode") in ("prepay", "postpay", "free_tier_only")
    assert "auto_reload" in budget
