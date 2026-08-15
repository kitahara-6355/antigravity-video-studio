"""従量課金のキルスイッチと実費台帳（憲法第3条）。

**予算が無い有料利用に着手しない。** これまで課金経路には計測が1つも無く
（`usage_metadata` を読んでいる箇所がゼロだった）、「1回走らせるといくらか」
を誰も知らないまま実行層を閉じていた。**測れないものは止められない。**

## 設計

1. **絞り口は1つ。** 本番の 40 モジュールはすべて `gemini_client_factory`
   経由で、`model_governance` の proxy が全呼び出しを通る。そこに挟む。
   直接 `genai` を叩く本番モジュールは実測で0件（archives と tests を除く）
2. **fail-closed。** 単価が分からないモデルは**表の最高単価**で見積もる。
   台帳が壊れていたら実行しない。予算が無ければ実行しない
3. **呼ぶ前に止める。** 使ってから気づいても遅い。残高が予約額を割ったら
   `CostLimitExceeded` を上げ、**以降の呼び出しを一切通さない**
4. **単価は外部の事実なので、出典と取得日を持つデータにする。**
   コードに埋め込まない（`backend/config/gemini_pricing.json`）

## 使い方

    from cost_guard import get_guard

    guard = get_guard()          # .claude/budget.json から上限を読む
    guard.before_call("gemini-2.5-flash", caller="director")
    ...                          # 実際の API 呼び出し
    guard.after_call("gemini-2.5-flash", response, caller="director")

台帳は `.claude/cost_ledger.jsonl`（1行1呼び出し）に追記され、
合計は `.claude/budget.json` の `spent_jpy` に反映される。

    python -m backend.cost_guard --status     # 残高と内訳
    python -m backend.cost_guard --gate       # 予算超過なら exit 1
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUDGET_PATH = REPO_ROOT / ".claude" / "budget.json"
LEDGER_PATH = REPO_ROOT / ".claude" / "cost_ledger.jsonl"
PRICING_PATH = Path(__file__).parent / "config" / "gemini_pricing.json"

# 1回の呼び出しで使いうる額の予約。**残高がこれを割ったら呼ばせない。**
# 呼ぶ前に出力トークン数は分からないので、上振れを見込んで予約する。
DEFAULT_RESERVE_JPY = 5.0


class CostLimitExceeded(RuntimeError):
    """予算の上限に達した。**握りつぶさないこと。**"""


class PricingUnavailable(RuntimeError):
    """単価表が読めない。fail-closed で実行しない。"""


@dataclass(frozen=True)
class Price:
    """百万トークンあたりの単価（USD）。"""
    input_usd: float
    output_usd: float
    # **無料枠の対象か。** Flash 系には無料枠が残っている（1,500 RPD 程度）。
    # 枠内なら実費は 0 円なので、**見積もりは上限**でしかない。
    # Pro 系は 2026-04-01 に無料枠から外れた。
    free_tier: bool = False


def _load_pricing() -> tuple[dict[str, Price], dict]:
    """単価表と、その出典。**無ければ実行しない。**"""
    if not PRICING_PATH.is_file():
        raise PricingUnavailable(
            f"単価表がありません: {PRICING_PATH}。"
            "課金額を見積もれないので実行しません")
    payload = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    prices = {
        name: Price(float(row["input_usd_per_1m"]),
                    float(row["output_usd_per_1m"]),
                    bool(row.get("free_tier", False)))
        for name, row in payload["models"].items()
    }
    if not prices:
        raise PricingUnavailable("単価表が空です")
    return prices, payload


class CostGuard:
    """使う前に止める。使ったら記録する。"""

    def __init__(self, limit_jpy: float, spent_jpy: float = 0.0,
                 ledger_path: Path = LEDGER_PATH,
                 budget_id: str = "", reserve_jpy: float = DEFAULT_RESERVE_JPY):
        self.limit_jpy = float(limit_jpy)
        self.spent_jpy = float(spent_jpy)
        self.ledger_path = Path(ledger_path)
        self.budget_id = budget_id
        self.reserve_jpy = float(reserve_jpy)
        self.calls = 0
        self._lock = threading.Lock()
        self._prices, self._pricing_meta = _load_pricing()
        # 未知のモデルは**最高単価**で見積もる（fail-closed）。
        self._worst = Price(
            max(p.input_usd for p in self._prices.values()),
            max(p.output_usd for p in self._prices.values()),
            False)  # 未知のモデルを無料扱いにしない

    # --- 残高 ---------------------------------------------------------------

    @property
    def remaining_jpy(self) -> float:
        return self.limit_jpy - self.spent_jpy

    def _usd_to_jpy(self) -> float:
        return float(self._pricing_meta.get("usd_jpy_rate", 160.0))

    # --- 呼ぶ前 -------------------------------------------------------------

    def before_call(self, model: str, caller: str = "") -> None:
        """**残高が予約額を割っていたら呼ばせない。**

        使ってから気づいても払い戻せないので、必ず呼び出しの前に通す。
        """
        if self.remaining_jpy < self.reserve_jpy:
            raise CostLimitExceeded(
                f"予算を使い切りました（上限 {self.limit_jpy:.0f}円 / "
                f"実績 {self.spent_jpy:.2f}円 / 残 {self.remaining_jpy:.2f}円）。"
                f"model={model} caller={caller} は実行しません。"
                "続けるには .claude/budget.json の承認を取り直してください")

    # --- 呼んだ後 -----------------------------------------------------------

    def price_of(self, model: str) -> Price:
        """単価。**知らないモデルは最高単価**として扱う（fail-closed）。"""
        return self._prices.get(model, self._worst)

    @staticmethod
    def _tokens(response) -> tuple[int, int]:
        """`usage_metadata` から実トークンを読む。読めなければ 0 を返す。

        **0 を返した事実は台帳に残す。** 黙って無料扱いにしない。
        """
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return 0, 0
        prompt = getattr(usage, "prompt_token_count", 0) or 0
        # 思考トークンは出力側に含めて数える（課金対象なので落とさない）。
        out = getattr(usage, "candidates_token_count", 0) or 0
        out += getattr(usage, "thoughts_token_count", 0) or 0
        total = getattr(usage, "total_token_count", 0) or 0
        if not out and total > prompt:
            out = total - prompt
        return int(prompt), int(out)

    def after_call(self, model: str, response, caller: str = "") -> float:
        """実費を計上して台帳に追記する。計上した円を返す。"""
        prompt, out = self._tokens(response)
        price = self.price_of(model)
        known = model in self._prices
        usd = (prompt * price.input_usd + out * price.output_usd) / 1_000_000
        jpy = usd * self._usd_to_jpy()
        with self._lock:
            self.spent_jpy += jpy
            self.calls += 1
            spent = self.spent_jpy
        self._append({
            "at": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "caller": caller,
            "prompt_tokens": prompt,
            "output_tokens": out,
            "known_price": known,
            # 無料枠の対象モデルか。**枠内なら実費 0 円**なので、
            # ここが True の行は「上限としての見積もり」でしかない。
            "free_tier_eligible": price.free_tier,
            "usd": round(usd, 6),
            "jpy": round(jpy, 4),
            "spent_jpy": round(spent, 4),
            "limit_jpy": self.limit_jpy,
            "budget_id": self.budget_id,
            # トークンが読めなかった呼び出しは**無料ではなく不明**。
            "metered": bool(prompt or out),
        })
        return jpy

    def _append(self, row: dict) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # --- 台帳への反映 -------------------------------------------------------

    def flush_to_budget(self, path: Path = BUDGET_PATH) -> None:
        """`.claude/budget.json` の `spent_jpy` を実績で更新する。"""
        path = Path(path)
        if not path.is_file():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        for budget in payload.get("budgets", []):
            if budget.get("id") == self.budget_id:
                budget["spent_jpy"] = round(self.spent_jpy, 2)
                if self.remaining_jpy < self.reserve_jpy:
                    budget["status"] = "exhausted"
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")


# --- 予算台帳から組み立てる ---------------------------------------------------


def load_active_budget(path: Path = BUDGET_PATH) -> dict | None:
    """`status == "active"` の予算を1つ返す。無ければ None。"""
    path = Path(path)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    for budget in payload.get("budgets", []):
        if budget.get("status") == "active":
            return budget
    return None


_guard: CostGuard | None = None
_guard_lock = threading.Lock()


def get_guard() -> CostGuard | None:
    """有効な予算があればガードを返す。**無ければ None**。

    None は「課金してよい」の意味ではない。呼び出し側（proxy）は
    None のときテスト用のダミーキーかどうかを見て、実キーなら止める。
    """
    global _guard
    with _guard_lock:
        if _guard is not None:
            return _guard
        budget = load_active_budget()
        if budget is None:
            return None
        _guard = CostGuard(
            limit_jpy=float(budget.get("limit_jpy", 0)),
            spent_jpy=float(budget.get("spent_jpy", 0)),
            budget_id=str(budget.get("id", "")))
        return _guard


def reset_guard() -> None:
    """テスト用。プロセス内のキャッシュを捨てる。"""
    global _guard
    with _guard_lock:
        _guard = None


def is_dummy_key() -> bool:
    """CI やテストのダミーキーか。**実キーと同じ扱いにしない。**"""
    key = os.environ.get("GOOGLE_API_KEY", "")
    return (not key) or key.startswith(("dummy", "test"))


# --- proxy から呼ぶ入口 -------------------------------------------------------


def guard_before(model: str, caller: str = "") -> CostGuard | None:
    """課金する前に必ず通す。**予算が無い実行を止める。**"""
    if is_dummy_key():
        return None  # 外部に出ない（net_guard が遮断している）
    guard = get_guard()
    if guard is None:
        raise CostLimitExceeded(
            "承認済みの予算がありません（.claude/budget.json に active な"
            "予算がない）。憲法第3条により、予算の無い有料利用には着手しません。"
            f"model={model} caller={caller}")
    guard.before_call(model, caller)
    return guard


def guard_after(guard: CostGuard | None, model: str, response,
                caller: str = "") -> None:
    if guard is None:
        return
    guard.after_call(model, response, caller)


# --- CLI ----------------------------------------------------------------------


def _format_status() -> str:
    budget = load_active_budget()
    lines = ["従量課金の残高", ""]
    if budget is None:
        lines.append("  有効な予算がありません（課金する実行はできません）。")
        return "\n".join(lines)
    limit = float(budget.get("limit_jpy", 0))
    spent = float(budget.get("spent_jpy", 0))
    lines += [
        f"  予算 ID : {budget.get('id')}",
        f"  用途    : {budget.get('purpose')}",
        f"  上限    : {limit:,.0f} 円",
        f"  実績    : {spent:,.2f} 円",
        f"  残り    : {limit - spent:,.2f} 円",
        "",
    ]
    mode = budget.get("billing_mode", "(未宣言)")
    lines.append(f"  課金方式: {mode}")
    if mode == "prepay" and budget.get("auto_reload") != "off":
        lines.append("  ⚠ **自動リロードが OFF だと宣言されていません。**"
                     "ON のままだと Google 側の上限が効きません"
                     "（budget.json の auto_reload を \"off\" にする）")
    if budget.get("credits_expire_at"):
        lines.append(f"  クレジット失効: {budget['credits_expire_at']}（1年で失効）")
    lines.append("")
    if LEDGER_PATH.is_file():
        rows = [json.loads(line) for line in
                LEDGER_PATH.read_text(encoding="utf-8").splitlines() if line]
        lines.append(f"  呼び出し: {len(rows)} 件")
        unmetered = sum(1 for r in rows if not r.get("metered"))
        if unmetered:
            lines.append(f"  ⚠ トークンを読めなかった呼び出し: {unmetered} 件"
                         "（無料ではなく不明）")
        unknown = sum(1 for r in rows if not r.get("known_price"))
        if unknown:
            lines.append(f"  ⚠ 単価が未登録のモデル: {unknown} 件"
                         "（最高単価で見積もっています）")
        free = sum(1 for r in rows if r.get("free_tier_eligible"))
        if free:
            lines.append(f"  ℹ 無料枠の対象モデル: {free} 件。"
                         "**枠内に収まっていれば実費は 0 円**なので、"
                         "上の実績は上限としての見積もりです"
                         "（一次情報の請求額と突き合わせてください）")
    else:
        lines.append("  呼び出し: 0 件（台帳なし）")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="従量課金のキルスイッチ")
    parser.add_argument("--status", action="store_true", help="残高と内訳を出す")
    parser.add_argument("--gate", action="store_true",
                        help="予算を使い切っていれば exit 1")
    args = parser.parse_args(argv)

    print(_format_status())

    if args.gate:
        budget = load_active_budget()
        if budget is None:
            print("\n🚫 有効な予算がありません。")
            return 1
        remaining = float(budget.get("limit_jpy", 0)) - float(
            budget.get("spent_jpy", 0))
        if remaining < DEFAULT_RESERVE_JPY:
            print(f"\n🚫 残高が予約額（{DEFAULT_RESERVE_JPY:.0f}円）を"
                  "下回っています。課金する実行は止まります。")
            return 1
        print("\n✅ 予算の範囲内です。")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
