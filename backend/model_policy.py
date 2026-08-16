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

    if args.json:
        print(json.dumps([asdict(resolve(t)) for t in known_tasks()],
                         ensure_ascii=False, indent=2))
    else:
        print(_format_show())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
