"""どの工程がどのモデルで動くか（見える化）と、その場での昇格（ユーザー指示）。

**ユーザー要件（2026-08-15）**:

1. **適用モデルの見える化を徹底する。** どの提案・自動処理結果が、どのモデルで
   出たのかが常に分かること
2. **結果に不満なら、すぐグレードアップを指示できること。** 工程単位で段を
   上げ、その場でやり直せる体制をマストにする

## 既存の仕組みとの関係

段（tier）は既に `backend/model_config.json` の `text_generation.tiers` にある
（premium / standard / batch）。**新しい台帳は作らない**（憲法第5条・正典は1つ）。
ここが足すのは2つだけ:

- **上書き**（`model_overrides.json`）— ユーザーが工程ごとに段を指定した記録
- **履歴**（`.claude/model_escalations.jsonl`）— いつ・どの工程を・なぜ上げたか

`model_governance` は**エラー時に降格**する仕組み（fallback）で、向きが逆。
こちらは**結果への不満で意図的に昇格**する。混ぜない。

## 使い方

    python -m backend.model_policy --show                # 全工程の現在地（一覧）
    python -m backend.model_policy --why telop_suggestion
    python -m backend.model_policy --up telop_suggestion --reason "テロップが硬い"
    python -m backend.model_policy --down semantic_chunker --reason "十分な品質"
    python -m backend.model_policy --pin director premium --reason "ここは落とさない"
    python -m backend.model_policy --reset telop_suggestion

コードからは:

    from model_policy import resolve
    decision = resolve("telop_suggestion")
    decision.model   # 実際に使うモデル
    decision.tier    # premium / standard / batch
    decision.source  # "user_override" / "task_mapping" / "tier_default"
"""
from __future__ import annotations

import argparse
import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).parent / "model_config.json"
OVERRIDES_PATH = Path(__file__).parent / "config" / "model_overrides.json"
HISTORY_PATH = REPO_ROOT / ".claude" / "model_escalations.jsonl"

# 段の並びは **`model_config.json` が正典**（`text_generation.tier_order`）。
# ここに持つと台帳が2つになる（憲法第5条）。読めないときだけこの既定を使う。
_FALLBACK_TIER_ORDER = ("batch", "standard", "premium", "pro")


def tier_order() -> tuple[str, ...]:
    """段の並び。**左が下、右が上。**"""
    declared = (_load_config().get("text_generation") or {}).get("tier_order")
    if declared:
        return tuple(declared)
    return _FALLBACK_TIER_ORDER

_lock = threading.Lock()


class UnknownTier(ValueError):
    """存在しない段を指定した。**黙って既定値に落とさない。**"""


@dataclass(frozen=True)
class Decision:
    """この工程がどのモデルで動くか、**なぜそうなのか**。"""
    task: str
    model: str
    tier: str
    source: str        # user_override / task_mapping / tier_default
    reason: str = ""   # ユーザーが上書きしたときの理由
    changed_at: str = ""

    @property
    def can_upgrade(self) -> bool:
        return self.tier != tier_order()[-1]

    def label(self) -> str:
        mark = "👤" if self.source == "user_override" else "  "
        return f"{mark} {self.task:24s} {self.tier:9s} {self.model}"


# **入替トリガー（ユーザー承認 2026-08-16）。**
# モデル選定を「一度の決定」から「維持される方針」に変えるための4条件。
# これが無かったので、2.5 系が2ヶ月後に終了する状態まで誰も気づかなかった。
REPLACEMENT_TRIGGERS = {
    "price_change": (
        "**価格が変わった。** ただし導入価格の値上げは想定内なので、それ自体では"
        "外さない。**値上げの結果、無料枠から外れたら**見直す"),
    "better_free_model": (
        "**いまの組み合わせより高品質で、無料枠のある新モデルが出た。** "
        "判定はベンチマークの数字ではなく、**このパイプラインの成果物で不満が"
        "減ったか**。候補を検知 → 1工程で試す → 良ければ広げる"),
    "free_tier_change": (
        "**無料枠の条件が変わった**（枠から外れた・RPD/RPM が絞られた）。"
        "P3 は無料枠を前提にしているので、**ここが崩れると戦略ごと崩れる**。"
        "実績として Pro は 2026-04-01 に無料枠から外れている"),
    "obsolescence": (
        "**陳腐化。** 提供終了の予告が出た、モデル ID が実在しなくなった、"
        "後継世代が出て現行が preview のまま取り残された、など"),
}


def _load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def tiers() -> dict[str, dict]:
    """段の定義。**正典は `model_config.json`。** ここでは持たない。"""
    return (_load_config().get("text_generation") or {}).get("tiers") or {}


def model_of_tier(tier: str) -> str:
    table = tiers()
    if tier not in table:
        raise UnknownTier(
            f"知らない段です: {tier}（使えるのは {', '.join(sorted(table))}）")
    return table[tier]["model"]


def tier_of_model(model: str) -> str | None:
    for name, row in tiers().items():
        if row.get("model") == model:
            return name
    return None


def load_overrides() -> dict[str, dict]:
    if not OVERRIDES_PATH.is_file():
        return {}
    payload = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    return payload.get("tasks") or {}


def _save_overrides(tasks: dict[str, dict]) -> None:
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_comment": ("**ユーザーが工程ごとに指定した段。** 段の定義そのものは "
                     "backend/model_config.json が正典で、ここはその上書きだけ。"
                     "`python -m backend.model_policy --up <task> --reason \"…\"` "
                     "で増える。手で編集してもよいが、理由は必ず書くこと"),
        "tasks": dict(sorted(tasks.items())),
    }
    with open(OVERRIDES_PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def known_tasks() -> list[str]:
    """既知の工程。`task_mapping` と上書きの和。"""
    mapping = _load_config().get("task_mapping") or {}
    return sorted(set(mapping) | set(load_overrides()))


def resolve(task: str) -> Decision:
    """この工程が**いまどのモデルで動くか**と、その根拠を返す。

    優先順位は 1) ユーザーの上書き 2) task_mapping 3) 既定の段。
    **どれで決まったかを `source` に残す**（見える化のため）。
    """
    override = load_overrides().get(task)
    if override:
        tier = override["tier"]
        return Decision(task, model_of_tier(tier), tier, "user_override",
                        override.get("reason", ""), override.get("changed_at", ""))

    config = _load_config()
    mapped = (config.get("task_mapping") or {}).get(task)
    if mapped:
        # **工程は段（tier）に紐づけるのが正。** モデル名の直書きは、入替の
        # たびに全工程を書き換えることになり、実際それで
        # `gemini-3-flash-preview` が14工程に居座って腐った（2026-08-16）。
        # 直書きも読めるようにしておくが、それは段の外として表示する。
        if mapped in tiers():
            return Decision(task, model_of_tier(mapped), mapped, "task_mapping")
        return Decision(task, mapped, tier_of_model(mapped) or "(段の外)",
                        "task_mapping")

    default = (config.get("text_generation") or {}).get("default_model")
    if not default:
        raise UnknownTier(f"既定モデルが設定にありません（task={task}）")
    return Decision(task, default, tier_of_model(default) or "(段の外)",
                    "tier_default")


def _record(task: str, before: Decision, after: Decision, reason: str,
            action: str) -> None:
    """**いつ・どの工程を・なぜ動かしたか。** あとで効果を検証するために残す。"""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({
            "at": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "task": task,
            "from": {"tier": before.tier, "model": before.model},
            "to": {"tier": after.tier, "model": after.model},
            "reason": reason,
        }, ensure_ascii=False) + "\n")


def set_tier(task: str, tier: str, reason: str, action: str = "pin") -> Decision:
    """工程の段を固定する。**理由が要る。**"""
    if not reason.strip():
        raise ValueError("理由を書いてください（あとで効果を検証できなくなります）")
    if tier not in tiers():
        raise UnknownTier(f"知らない段です: {tier}")
    with _lock:
        before = resolve(task)
        tasks = load_overrides()
        tasks[task] = {
            "tier": tier,
            "reason": reason.strip(),
            "changed_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_overrides(tasks)
        after = resolve(task)
    _record(task, before, after, reason.strip(), action)
    return after


def escalate(task: str, reason: str) -> Decision:
    """**1段上げる。** 結果に不満があったときの受け口。"""
    current = resolve(task)
    order = tier_order()
    if current.tier not in order:
        # 段の外のモデルが当たっている。上げ先が決められないので最上段にする。
        return set_tier(task, order[-1], reason, action="escalate")
    index = order.index(current.tier)
    if index >= len(order) - 1:
        raise ValueError(
            f"{task} は既に最上段（{current.tier} / {current.model}）です。"
            "これ以上は上げられません — 段の定義そのものを見直してください"
            "（backend/model_config.json）")
    return set_tier(task, order[index + 1], reason, action="escalate")


def de_escalate(task: str, reason: str) -> Decision:
    """1段下げる（コスト最適化）。"""
    current = resolve(task)
    order = tier_order()
    index = order.index(current.tier) if current.tier in order else 0
    if index <= 0:
        raise ValueError(f"{task} は既に最下段（{current.tier}）です")
    return set_tier(task, order[index - 1], reason, action="de_escalate")


def reset(task: str) -> Decision:
    """上書きを外して既定に戻す。"""
    with _lock:
        tasks = load_overrides()
        if task in tasks:
            before = resolve(task)
            del tasks[task]
            _save_overrides(tasks)
            after = resolve(task)
            _record(task, before, after, "上書きを解除", "reset")
            return after
    return resolve(task)


def history(task: str | None = None) -> list[dict]:
    if not HISTORY_PATH.is_file():
        return []
    rows = [json.loads(line) for line in
            HISTORY_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if task is None or r.get("task") == task]


# --- 点検（入替トリガーの検知） -----------------------------------------------


@dataclass(frozen=True)
class AuditFinding:
    trigger: str      # REPLACEMENT_TRIGGERS のキー、または "unverified"
    tier: str
    model: str
    what: str

    def __str__(self) -> str:
        return f"[{self.trigger}] {self.tier} / {self.model}\n      — {self.what}"


def live_model_ids() -> tuple[set[str], str]:
    """**実 API のモデル一覧。** これが一次情報。

    取得は無料（`models.list`）。キーが無ければ空集合と理由を返す。
    **「確かめられなかった」を「問題なし」にしない** — 呼び出し側が FAIL にする。
    """
    # **`backend.` を付ける。** 裸の `cost_guard` は PYTHONPATH=./backend でしか
    # 解決せず、CLAUDE.md が案内している `python -m backend.model_policy --audit`
    # をリポジトリ直下で叩くと ModuleNotFoundError で落ちていた（2026-08-16）。
    from backend.cost_guard import is_dummy_key

    if is_dummy_key():
        return set(), ("実 API キーがありません（ダミーキー）。"
                       "モデルの実在を確かめられません")
    try:
        from gemini_client_factory import get_gemini_client
        client = get_gemini_client()
        if client is None:
            return set(), "クライアントを作れませんでした"
        names = set()
        for model in client.models.list():
            name = getattr(model, "name", "") or ""
            names.add(name.split("/")[-1])
        return names, ""
    except Exception as e:  # noqa: BLE001 — 何で落ちても「未確認」に倒す
        return set(), f"モデル一覧を取得できませんでした: {e}"


def audit() -> tuple[list[AuditFinding], str]:
    """入替トリガーに当たっていないかを点検する。

    **人力に頼らない。** トリガーを定義しても誰も見ていなければ、前回と同じで
    モデルが死ぬまで気づかない。定期実行して差分だけ見る。
    """
    findings: list[AuditFinding] = []
    table = tiers()
    live, why_not = live_model_ids()

    for tier in tier_order():
        row = table.get(tier)
        if row is None:
            findings.append(AuditFinding(
                "obsolescence", tier, "(未定義)",
                "段の並びに載っているのに定義がありません"))
            continue
        model = row.get("model", "")
        if not row.get("verified"):
            findings.append(AuditFinding(
                "unverified", tier, model,
                "モデル ID が**一次情報と突き合わせられていません**"
                f"（{why_not or 'models.list と照合してください'}）"))
        if live and model not in live:
            findings.append(AuditFinding(
                "obsolescence", tier, model,
                "**この ID は実 API のモデル一覧にありません。**"
                "廃止されたか、名前が違います"))

    # 単価表に載っていない段のモデルは、実費を見積もれない。
    try:
        from backend.cost_guard import CostGuard, PricingUnavailable
        priced = set(CostGuard(limit_jpy=0)._prices)
    except (PricingUnavailable, OSError, ValueError):
        # 単価表が無い・壊れている。**点検そのものは続ける** — ここで落ちると
        # 段の実在確認（上のループ）まで巻き添えになる。
        priced = set()
    for tier in tier_order():
        model = (table.get(tier) or {}).get("model", "")
        if model and priced and model not in priced:
            findings.append(AuditFinding(
                "price_change", tier, model,
                "単価表（backend/config/gemini_pricing.json）に**単価がありません**。"
                "最高単価で見積もられるので、実費とズレます"))

    return findings, why_not


# --- CLI ----------------------------------------------------------------------


def _format_show() -> str:
    lines = ["どの工程がどのモデルで動くか（👤 = ユーザー指定）", ""]
    table = tiers()
    lines.append("  段: " + " → ".join(
        f"{t}({table[t]['model']})" for t in tier_order() if t in table))
    lines.append("")
    for task in known_tasks():
        decision = resolve(task)
        lines.append("  " + decision.label())
        if decision.source == "user_override":
            lines.append(f"       理由: {decision.reason}"
                         f"（{decision.changed_at[:10]}）")
    lines += ["", "  不満があったら:",
              "    python -m backend.model_policy --up <工程> --reason \"何が不満か\""]
    return "\n".join(lines)


def _format_why(task: str) -> str:
    decision = resolve(task)
    reasons = {
        "user_override": "**あなたが指定した**段です",
        "task_mapping": "model_config.json の task_mapping で決まっています",
        "tier_default": "この工程は個別指定が無いので既定モデルです",
    }
    lines = [
        f"{task}",
        f"  モデル : {decision.model}",
        f"  段     : {decision.tier}",
        f"  根拠   : {reasons.get(decision.source, decision.source)}",
    ]
    if decision.reason:
        lines.append(f"  理由   : {decision.reason}（{decision.changed_at[:10]}）")
    lines.append(f"  昇格   : {'できます' if decision.can_upgrade else '既に最上段です'}")
    past = history(task)
    if past:
        lines += ["", f"  これまでの変更 {len(past)} 件:"]
        for row in past[-5:]:
            lines.append(f"    {row['at'][:10]} {row['action']}: "
                         f"{row['from']['tier']} → {row['to']['tier']}"
                         f" — {row['reason']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="適用モデルの見える化と、工程ごとの昇格")
    parser.add_argument("--show", action="store_true", help="全工程の現在地")
    parser.add_argument("--why", metavar="工程", help="なぜそのモデルなのか")
    parser.add_argument("--up", metavar="工程", help="1段上げる（要 --reason）")
    parser.add_argument("--down", metavar="工程", help="1段下げる（要 --reason）")
    parser.add_argument("--pin", nargs=2, metavar=("工程", "段"),
                        help="段を固定する（要 --reason）")
    parser.add_argument("--reset", metavar="工程", help="上書きを外す")
    parser.add_argument("--reason", default="", help="なぜそうするのか")
    parser.add_argument("--audit", action="store_true",
                        help="入替トリガーに当たっていないか点検する（要 exit 0）")
    parser.add_argument("--triggers", action="store_true",
                        help="入替トリガーの定義を出す")
    parser.add_argument("--json", action="store_true", help="機械可読で出す")
    args = parser.parse_args(argv)

    try:
        if args.up:
            after = escalate(args.up, args.reason)
            print(f"⬆ {args.up}: {after.tier} / {after.model} に上げました")
            print("  次に同じ工程を走らせるとこのモデルが使われます。"
                  "戻すときは --reset")
            return 0
        if args.down:
            after = de_escalate(args.down, args.reason)
            print(f"⬇ {args.down}: {after.tier} / {after.model} に下げました")
            return 0
        if args.pin:
            after = set_tier(args.pin[0], args.pin[1], args.reason)
            print(f"📌 {args.pin[0]}: {after.tier} / {after.model} に固定しました")
            return 0
        if args.reset:
            after = reset(args.reset)
            print(f"↩ {args.reset}: 既定に戻しました（{after.tier} / {after.model}）")
            return 0
        if args.why:
            if args.json:
                print(json.dumps(asdict(resolve(args.why)), ensure_ascii=False,
                                 indent=2))
            else:
                print(_format_why(args.why))
            return 0
    except (ValueError, UnknownTier) as e:
        print(f"🚫 {e}")
        return 1

    if args.triggers:
        print("入替トリガー（当たったらモデルの組み替えを検討する）\n")
        for key, text in REPLACEMENT_TRIGGERS.items():
            print(f"  ▸ {key}\n      {text}\n")
        return 0

    if args.audit:
        findings, _ = audit()
        table = tiers()
        print("モデルの点検\n")
        print("  段: " + " → ".join(
            f"{t}({table[t]['model']})" for t in tier_order() if t in table))
        print()
        if not findings:
            print("  ✅ 入替トリガーに当たっているものはありません。")
            return 0
        for finding in findings:
            print(f"    {finding}")
        print(f"\n  🚫 {len(findings)} 件。"
              "`--triggers` でトリガーの定義を確認してください。")
        return 1

    if args.json:
        print(json.dumps([asdict(resolve(t)) for t in known_tasks()],
                         ensure_ascii=False, indent=2))
    else:
        print(_format_show())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
