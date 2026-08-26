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

ENV_PATH = Path(__file__).parent / ".env"
_env_loaded = False


def load_env() -> None:
    """`backend/.env` を環境変数に読み込む（1回だけ）。

    `main.py` は import 時に読んでいるが、**CLI は誰も読んでいなかった。**
    そのため実キーを置いても `--status` / `--audit` / `verify_account` が
    「ダミーキーです」と言い続ける（2026-08-16 に発覚）。

    **既存の環境変数は上書きしない。** CI が渡す `dummy_key_for_ci` や
    テストの monkeypatch が勝つ。
    """
    global _env_loaded
    if _env_loaded or not ENV_PATH.is_file():
        _env_loaded = True
        return
    _env_loaded = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ENV_PATH, override=False)


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

    def flush_to_budget(self, path: Path | None = None) -> None:
        """`.claude/budget.json` の `spent_jpy` を実績で更新する。

        **既定値を束縛せずに毎回モジュール変数を見る。** 既定引数に
        `BUDGET_PATH` を焼き込むと、テストの monkeypatch が効かない。
        """
        path = Path(path if path is not None else BUDGET_PATH)
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


def load_active_budget(path: Path | None = None) -> dict | None:
    """`status == "active"` の予算を1つ返す。無ければ None。

    既定値に `BUDGET_PATH` を焼き込まない（束縛されるとテストの
    monkeypatch が届かず、実物の台帳を読んでしまう）。
    """
    path = Path(path if path is not None else BUDGET_PATH)
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
    # **呼び出しごとに budget.json へ書き戻す。**
    # 書き戻さないと、新しいプロセスが spent_jpy=0 から始まってしまい、
    # 上限が「1プロセスあたり ¥3,000」になる。キルスイッチはプロセスを
    # 跨いで効かなければ意味が無い（2026-08-19 の実走で発覚）。
    guard.flush_to_budget()


# --- 台帳から予算を復元する ---------------------------------------------------


def _ledger_rows() -> list[dict]:
    """台帳を読む。無ければ空。**壊れた行は落とさず例外にする**（黙って
    件数が減ると「使っていない」に見えるため）。"""
    path = Path(LEDGER_PATH)
    if not path.is_file():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def reconcile_ledger() -> float:
    """台帳を正として `budget.json` の `spent_jpy` を作り直す。

    書き戻しが本番から呼ばれていなかった時期（〜2026-08-19）の行が
    台帳に残っている。**台帳が正**なので、そこから合計を作り直す。

    Returns:
        active な予算に計上された合計（円）。予算が無ければ 0.0。
    """
    budget = load_active_budget()
    if budget is None:
        return 0.0
    budget_id = str(budget.get("id", ""))
    # **要約の行は足さない。** 1本ぶんの合計を持っているので、呼び出しの行と
    # 一緒に足すと二重計上になり、budget.json に倍の額を書く。
    total = sum(float(row.get("jpy", 0)) for row in _ledger_rows()
                if row.get("budget_id") == budget_id
                and row.get("kind") != "run_summary")

    path = Path(BUDGET_PATH)
    if not path.is_file():
        return total
    payload = json.loads(path.read_text(encoding="utf-8"))
    for entry in payload.get("budgets", []):
        if entry.get("id") == budget_id:
            entry["spent_jpy"] = round(total, 2)
            remaining = float(entry.get("limit_jpy", 0)) - total
            if remaining < DEFAULT_RESERVE_JPY:
                entry["status"] = "exhausted"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return total


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
        lines.append(f"  クレジット失効: {budget['credits_expire_at']}"
                     "（1年で失効。Postpay 移行以外で閉じると没収）")
    # **Google 側の上限が本命。** cost_guard は推定でしか止められないので、
    # ここが空なら「二重の歯止め」は掛かっていない。
    cap = budget.get("spend_cap_usd")
    if cap:
        lines.append(f"  Google 側の上限: ${cap}/月 "
                     f"（プロジェクト {budget.get('spend_cap_project') or '(未記録)'}"
                     "・反映に約10分の遅れ）")
    else:
        lines.append("  ⚠ **AI Studio の Monthly spend cap が設定されていません。**"
                     "cost_guard は推定でしか止められないので、"
                     "確実な上限は Google 側に置いてください"
                     "（設定したら budget.json の spend_cap_usd と "
                     "spend_cap_project を埋める）")
    lines.append("")
    if Path(LEDGER_PATH).is_file():
        all_rows = _ledger_rows()
        # **要約の行は課金の行ではない。** 呼び出し件数にも未計測件数にも
        # 原価の合計にも入れない。入れると回数が水増しされ、`cost_jpy` を
        # 二重計上して台帳と budget.json が食い違って見える。
        summaries = [r for r in all_rows if r.get("kind") == "run_summary"]
        rows = [r for r in all_rows if r.get("kind") != "run_summary"]
        lines.append(f"  呼び出し: {len(rows)} 件")
        # **0 件でも必ず出す。** 黙っていると「出ていない」のか
        # 「0 だった」のか読み手に区別がつかず、不在が「問題なし」に
        # 化ける。R1-C2 が件数を要求しているのもここ。
        unmetered = sum(1 for r in rows if not r.get("metered"))
        mark = "⚠" if unmetered else "・"
        lines.append(f"  {mark} トークンを読めなかった呼び出し: {unmetered} 件"
                     "（無料ではなく不明）")
        unknown = sum(1 for r in rows if not r.get("known_price"))
        mark = "⚠" if unknown else "・"
        lines.append(f"  {mark} 単価が未登録のモデル: {unknown} 件"
                     "（最高単価で見積もっています）")
        free = sum(1 for r in rows if r.get("free_tier_eligible"))
        if free:
            # **文言を正典の条件文と揃える。** R1-C2 は 2026-08-21 に
            # 「原価はトークン実測にもとづく上限見積もり」に改めた。無料枠では
            # 突き合わせる請求額が構造的に存在しないので、ここで突き合わせを
            # 迫ると**検証コマンド自身が条件文と食い違う**（1周目の
            # gate-verifier が not_met にした理由がこれ）。
            lines.append(f"  ℹ 無料枠の対象モデル: {free} 件。"
                         "**枠内に収まっていれば実費は 0 円。** "
                         "上の実績は**トークン実測にもとづく上限見積もり**です"
                         "（請求額との突き合わせは pro 昇格で課金運用に"
                         "移ってから行います）")
        ledger_total = sum(float(r.get("jpy", 0)) for r in rows
                           if r.get("budget_id") == budget.get("id"))
        if abs(ledger_total - spent) > 0.01:
            lines.append(
                f"  ⚠ **台帳と budget.json が食い違っています**"
                f"（台帳 {ledger_total:,.2f} 円 / 予算 {spent:,.2f} 円）。"
                "`--reconcile` で台帳を正として書き直してください")

        # **1本あたり。** R1-C2 が要求しているのは総額ではなく1本の原価と
        # 所要時間。総額しか出さないと、何日ぶん・何本ぶんが混ざった数字
        # なのかが読み手に分からない。
        lines.append("")
        lines += _format_per_run(summaries)
    else:
        lines.append("  呼び出し: 0 件（台帳なし）")
    return "\n".join(lines)


def _format_per_run(summaries: list[dict]) -> list[str]:
    """実行1本ごとの所要時間と原価。**無ければ黙らない。**"""
    if not summaries:
        return ["  ⚠ **1本あたりの内訳がありません**"
                "（上の実績は期間全体の合計です）。実行記録が台帳に要約を"
                "書いていないので、1本の原価と所要時間は切り出せません"]

    lines = [f"  1本あたり: {len(summaries)} 本"]
    for row in summaries:
        mark = {"completed": "✅", "degraded": "⚠（一部失敗）",
                "failed": "🚫（失敗）"}.get(row.get("status", ""), "…")
        lines.append(
            f"      {mark} {row.get('run_id', '(id なし)')}  "
            f"{float(row.get('duration_sec') or 0):.1f} 秒 / "
            f"{float(row.get('cost_jpy') or 0):.4f} 円 / "
            f"{int(row.get('calls') or 0)} 回")

    # **一部の工程が落ちた実行（degraded）も動画は出ている。**
    # 時間も原価も現実に使っているので、1本あたりの平均からは外さない。
    # 外すと「うまくいった回だけ」の平均になり、見積もりが甘くなる。
    done = [r for r in summaries
            if r.get("status") in ("completed", "degraded")]
    if done:
        n = len(done)
        avg_sec = sum(float(r.get("duration_sec") or 0) for r in done) / n
        avg_jpy = sum(float(r.get("cost_jpy") or 0) for r in done) / n
        欠け = sum(1 for r in done if r.get("status") == "degraded")
        注 = f"（うち一部失敗 {欠け} 本）" if 欠け else ""
        lines.append(f"      動画が出た {n} 本の平均{注}: "
                     f"{avg_sec:.1f} 秒 / {avg_jpy:.4f} 円")
    return lines


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description="従量課金のキルスイッチ")
    parser.add_argument("--status", action="store_true", help="残高と内訳を出す")
    parser.add_argument("--gate", action="store_true",
                        help="予算を使い切っていれば exit 1")
    parser.add_argument("--reconcile", action="store_true",
                        help="台帳を正として budget.json の spent_jpy を作り直す")
    args = parser.parse_args(argv)

    if args.reconcile:
        total = reconcile_ledger()
        print(f"台帳から実績を作り直しました: {total:,.4f} 円\n")

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
