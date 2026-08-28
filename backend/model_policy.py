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
import re
import threading
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
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


def _resolver_disagreements() -> tuple[list[tuple[str, str, str]], str]:
    """**答えが2種類ある工程**を挙げる（R1.5-C2）。

    `model_config.json` の `task_mapping` は段の名前を持つ。段として解かずに
    生で返すと、それがモデル ID として API に渡って 404 になる:

        404 NOT_FOUND: models/standard is not found for API version v1beta

    比べるのは**宣言**（`_resolve_declared`）であって、枠枯渇による降格後の値では
    ない。降格は食い違いではなく、設計どおりの動きなので。

    Returns:
        (食い違い, 確かめられなかった理由)
    """
    try:
        from model_governance import model_governance as engine
    except ImportError:
        try:
            from backend.model_governance import model_governance as engine
        except ImportError as e:  # pragma: no cover — 経路が壊れたときだけ
            return [], f"model_governance を読み込めませんでした: {e}"

    resolve_declared = getattr(engine, "_resolve_declared", None)
    if resolve_declared is None:
        return [], ("model_governance に `_resolve_declared` がありません"
                    "（解決器が一本化されていない可能性があります）")

    # **宣言だけでは足りない。** `_resolve_model()` は宣言のあとに
    # deprecated 差替（`validate_and_correct`）を通す。ここに1行足すだけで、
    # API に渡るモデルは `model_policy` の答えと変わる。**C6（2.5系サンセット）で
    # まさに触る所**なので、差替まで含めて突き合わせる。
    # （枠枯渇による降格は設計どおりの動きなので、ここでは見ない。
    #   実際に何で動いたかは実行記録の `models_observed` に残る）
    correct = getattr(engine, "validate_and_correct", None)

    disagreements = []
    for task in known_tasks():
        mine = resolve(task).model
        try:
            theirs = resolve_declared(task)
            if correct is not None:
                theirs = correct(theirs, f"audit:{task}")
        except Exception as e:  # noqa: BLE001 — 解決できないこと自体が食い違い
            theirs = f"(解決できません: {e})"
        if mine != theirs:
            disagreements.append((task, mine, theirs))
    return disagreements, ""


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

    # **解決器が2つあると答えも2つになる**（R1.5-C2）。
    # 段の名前がモデル ID として API に渡ると 404 で、実走では
    # 「21工程登録されているのに1回しか呼ばれない」という形で出た。
    disagreements, resolver_why_not = _resolver_disagreements()
    for task, mine, theirs in disagreements:
        findings.append(AuditFinding(
            "resolver_split", task, theirs,
            f"**解決器が2つあります。** model_policy は `{mine}`、"
            f"model_governance は `{theirs}` と答えます。"
            "段の名前がモデル ID として API に渡ると 404 になります"))
    if resolver_why_not:
        findings.append(AuditFinding(
            "resolver_unverified", "(全工程)", "(未確認)",
            f"**解決器が一致しているか確かめられませんでした**: {resolver_why_not}"))

    return findings, why_not


def format_audit(findings: list["AuditFinding"], why_not: str) -> str:
    """点検の結果を、**何と照合したのかが分かる形で**返す。

    1周目の gate-verifier の指摘（2026-08-20）:

    > audit が緑になったのは保存済みブール値だけを根拠にしている。
    > ダミーキーでは live_model_ids() が空集合を返し、obsolescence 照合は
    > スキップされる

    実際には実キーなら `models.list` に届いている（実測 50 件）。
    **届いたのか飛ばしたのかが出力に出ていなかった**ので、そこを出す。
    """
    table = tiers()
    lines = ["モデルの点検", ""]
    lines.append("  段: " + " → ".join(
        f"{t}({table[t]['model']})" for t in tier_order() if t in table))

    live, _ = live_model_ids()
    if live:
        lines.append(f"  一次情報との照合: 実 API の models.list **{len(live)} 件**"
                     "と突き合わせました")
    else:
        lines.append("  一次情報との照合: ⚠ **照合できていません**"
                     f"（{why_not or '理由の記録なし'}）。"
                     "廃止の検知はこの実行では効いていません")
    lines.append("")

    if not findings:
        lines.append("  ✅ 入替トリガーに当たっているものはありません。")
        return "\n".join(lines)
    for finding in findings:
        lines.append(f"    {finding}")
    lines.append(f"\n  🚫 {len(findings)} 件。"
                 "`--triggers` でトリガーの定義を確認してください。")
    return "\n".join(lines)


# ============================================================
# 2.5 系の終了（2026-10-16）への依存を数える
# ============================================================

SUNSET_DATE = date(2026, 10, 16)
SUNSET_PREFIX = "gemini-2.5"


@dataclass(frozen=True)
class SunsetReport:
    """2.5 系への依存の棚卸し。"""
    days_left: int
    tiers_at_risk: dict[str, str]
    runs_at_risk: dict[str, list[str]]
    source_hits: dict[str, int]
    run_count: int = 0

    @property
    def source_total(self) -> int:
        return sum(self.source_hits.values())


# 数に入れない場所。テストは「2.5 系を使っている」のではなく
# 「2.5 系の扱いを検査している」ので対象外。node_modules / .venv を
# 数えると件数が意味を失う。
#
# **除くのはディレクトリだけで、ファイル名では除かない**（R1.5-C6・
# gate-verifier 2周目の指摘）。`path.name.startswith("test_")` でも
# 落としていたため、`backend/harness/test_adk_gemini.py`（実 API を
# `gemini-2.5-flash` で叩くスクリプト）と `test_model_registry.py` が
# **本番にも到達不能にも計上されず、数から消えていた。**
# テストディレクトリの外にある `test_*` はテスト群ではなくスクリプト。
_SCAN_SKIP_DIRS = frozenset({
    "tests", "test", "__pycache__", "archives", "_deprecated",
    "node_modules", ".venv", "venv", ".git", ".next", "dist", "build",
    "antigravity_phase18_stable_v1", "antigravity_phase19_experimental_v1",
})


def scan_sunset_references(root: Path | None = None) -> dict[str, int]:
    """ソースに残っている 2.5 系の参照を数える。

    **実行記録だけでは依存は見えない。** 実走で通らなかった経路にも
    埋まっているので、静的にも数える。

    既定の走査根は**リポジトリ直下**。`backend/` だけを見ていた頃は
    `agents/orchestration/orchestrator.py`・`.claude/hooks/billing_gate.py`・
    `scratch/run_weakness_orchestrator.py` の**6箇所が数から漏れていた**
    （gate-verifier 2周目の指摘）。
    """
    hits: dict[str, int] = {}
    root = Path(root if root is not None else Path(__file__).resolve().parents[1])
    自分 = Path(__file__).resolve()
    for path in sorted(root.rglob("*.py")):
        if set(path.parts) & _SCAN_SKIP_DIRS:
            continue
        # **走査器自身の目印（`SUNSET_PREFIX`）は依存ではない。**
        # これを数えると、2.5 系を全部消しても件数が 1 のまま残る
        if path.resolve() == 自分:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        count = text.count(SUNSET_PREFIX)
        if count:
            hits[path.relative_to(root).as_posix()] = count
    return hits


# 本線の入口。**「本番かどうか」を人の感覚で決めない**（R1.5-C6）。
# ここから import を辿れるものを本番とする。
_MAINLINE_ENTRIES = ("agents.pipeline_coordinator", "main")


def _module_path(name: str, root: Path) -> Path | None:
    parts = name.split(".")
    for base in (root / "backend", root):
        p = base.joinpath(*parts)
        if p.with_suffix(".py").is_file():
            return p.with_suffix(".py")
        if (p / "__init__.py").is_file():
            return p / "__init__.py"
    return None


def _package_of(name: str, path: Path) -> str:
    """相対 import の基準になるパッケージ名。

    `__init__.py` なら自分自身がパッケージ、そうでなければ親。
    """
    if path.name == "__init__.py":
        return name
    return name.rpartition(".")[0]


def _resolve_relative(package: str, module: str | None, level: int) -> str | None:
    """`from ..x import y` の `..x` を絶対のモジュール名に直す。

    `level` は先頭のドットの数。1 なら同じパッケージ、2 なら親。
    パッケージの外へ出る指定は解決できないので None を返す。
    """
    parts = [p for p in package.split(".") if p]
    if level - 1 > len(parts):
        return None
    base = parts[:len(parts) - (level - 1)] if level > 1 else parts
    if module:
        base = base + module.split(".")
    return ".".join(base) or None


def _prefixes(name: str) -> list[str]:
    """`a.b.c` を import すると `a` と `a.b` の `__init__.py` も実行される。"""
    parts = name.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts) + 1)]


def reachable_modules(root: Path | None = None) -> set[str]:
    """**本線の入口から静的に辿れるモジュール**（R1.5-C6）。

    実行記録では「その日通らなかった経路」が見えない。import を辿れば
    通りうる経路が分かる。**辿れないものは本番ではない**と言い切れる。

    **相対 import を辿らなかったせいで `routers/**` を丸ごと取り落としていた**
    （gate-verifier 1周目の指摘・2026-08-28）。`backend/routers/__init__.py` は
    全行が相対 import で、`backend/main.py` が `from routers import (...)` で
    実行する。`from pkg import sub` で `pkg` しか積まないのも同じ取りこぼしを生む。
    """
    import ast

    root = Path(root if root is not None else Path(__file__).resolve().parents[1])
    seen: set[str] = set()
    stack = list(_MAINLINE_ENTRIES)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        path = _module_path(name, root)
        if path is None:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        package = _package_of(name, path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    stack.extend(_prefixes(a.name))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    target = _resolve_relative(package, node.module, node.level)
                else:
                    target = node.module
                if not target:
                    continue
                stack.extend(_prefixes(target))
                # `from pkg import sub` の `sub` はモジュールかもしれない。
                # モジュールでなければ `_module_path` が None を返すだけ。
                stack.extend(f"{target}.{a.name}" for a in node.names
                             if a.name != "*")

    out: set[str] = set()
    for name in seen:
        path = _module_path(name, root)
        if path is None:
            continue
        try:
            out.add(path.relative_to(root).as_posix())
        except ValueError:
            continue
    return out


# 設定データの中で「まるごとモデル ID」の値を見つける。
# **散文の中の言及は依存ではない**（`reason` や `note` に 2.5 と書いてあっても、
# それが API に渡るわけではない）。**キーも依存ではない** — `deprecated` や
# `fallback_chain` のキーは「訂正される入力」であって、使うモデルではない。
_CONFIG_SUFFIXES = (".json", ".yaml", ".yml")
# **実行時に書かれるものは設定ではない。** ここを除かないと
# `output/**/run.json` の `models_used` が「設定データの値がそのまま API に
# 渡ります」と誤ラベルされる（gate-verifier 2周目の指摘）。実行記録は
# `runs_at_risk` という別の脚で数える。
_RUNTIME_DIRS = frozenset({
    "output", "vault-outputs", "vault-assets", "pipeline_work", "temp",
    "htmlcov", ".pytest_cache", ".ruff_cache", "coverage",
})
_MODEL_ID_RE = re.compile(
    r"^(?:models/)?" + re.escape(SUNSET_PREFIX) + r"[A-Za-z0-9._-]*$")
_YAML_VALUE_RE = re.compile(
    r"""^\s*(?:-\s*)?(?:[\w.\-]+\s*:\s*)?['"]?([^'"#\s]+)['"]?\s*(?:#.*)?$""")


def _count_json_model_ids(node: object) -> int:
    """JSON の**値**のうち、まるごと 2.5 系のモデル ID のものを数える。"""
    if isinstance(node, str):
        return 1 if _MODEL_ID_RE.match(node.strip()) else 0
    if isinstance(node, dict):
        # キーは数えない。値だけを辿る
        return sum(_count_json_model_ids(v) for v in node.values())
    if isinstance(node, list):
        return sum(_count_json_model_ids(v) for v in node)
    return 0


def scan_config_model_ids(root: Path | None = None) -> dict[str, int]:
    """**設定データに埋まっている 2.5 系のモデル ID を数える**（R1.5-C6）。

    `rglob("*.py")` だけでは設定データを見ていなかった
    （gate-verifier 1周目の指摘・2026-08-28）。`model_config.json` の
    `deprecated[*].replacement` は実行時に `validate_and_correct()` が
    **そのまま返す値**で、2.5 系ならそれが API に渡る。

    設定データは import を辿れないので**到達可能性を静的に判定できない。
    よって全部を本番として扱う**（fail-closed）。数えるのは値だけで、
    キーと散文は数えない。
    """
    root = Path(root if root is not None else Path(__file__).resolve().parents[1])
    hits: dict[str, int] = {}
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in _CONFIG_SUFFIXES or not path.is_file():
            continue
        if set(path.parts) & (_SCAN_SKIP_DIRS | _RUNTIME_DIRS):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if SUNSET_PREFIX not in text:
            continue
        if path.suffix.lower() == ".json":
            try:
                count = _count_json_model_ids(json.loads(text))
            except json.JSONDecodeError:
                # **読めないものは安全側に倒す**（fail-closed）。
                # 素通しすると「見ていない」ことが緑に化ける
                count = text.count(SUNSET_PREFIX)
        else:
            count = 0
            for line in text.splitlines():
                m = _YAML_VALUE_RE.match(line)
                if m and _MODEL_ID_RE.match(m.group(1)):
                    count += 1
        if count:
            hits[path.relative_to(root).as_posix()] = count
    return hits


def split_code_and_doc(path: Path) -> tuple[int, int]:
    """1ファイルの 2.5 系参照を「コード上の値」と「文書」に分ける。

    **docstring の例と、実際に使われる既定値を混ぜない。** 条件文が言う
    「依存」は前者だけで、使い方を説明する文は依存ではない。

    **数え方は「文書の行の集合」を作ってから1回だけ数える**（R1.5-C6・
    gate-verifier 2周目の指摘）。docstring・コメント・`__main__` の中を
    それぞれ独立に足していたため、重なった行が二重に数えられ、
    `文書 > 合計` になって `合計 - 文書` が 0 に潰れた。
    **本番のコード参照を1行のコメントで隠せてしまう。**
    """
    import ast

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0, 0
    合計 = text.count(SUNSET_PREFIX)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # 読めないものは**文書側に倒さない**（fail-closed）
        return 合計, 0

    lines = text.splitlines()
    文書行: set[int] = set()          # 0 始まりの行番号

    def _積む(始1: int, 終1: int) -> None:
        """1 始まりの行範囲（両端含む）を 0 始まりで積む。"""
        文書行.update(range(max(0, 始1 - 1), min(len(lines), 終1)))

    # 1) docstring（モジュール・関数・クラス）
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        先頭 = body[0]
        if (isinstance(先頭, ast.Expr) and isinstance(先頭.value, ast.Constant)
                and isinstance(先頭.value.value, str)):
            _積む(先頭.lineno, getattr(先頭, "end_lineno", 先頭.lineno))

    # 2) 行頭が `#` のコメント（AST に無いので行から拾う）
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            文書行.add(i)

    # 3) **`if __name__ == "__main__":` の中は本番の実行経路ではない。**
    #    `model_governance.py` の自己テストは 2.5 を「訂正される入力」として
    #    渡しており、依存ではない（2026-08-28）。
    for node in tree.body:
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"):
            continue
        if not node.body:
            continue
        始 = node.body[0].lineno
        終 = max(getattr(n, "end_lineno", n.lineno) for n in node.body)
        _積む(始, 終)

    文書 = sum(lines[i].count(SUNSET_PREFIX) for i in 文書行)
    # 集合で数えているので二重計上は起きないが、念のため（fail-closed）
    文書 = min(合計, 文書)
    return 合計 - 文書, 文書


def classify_sunset_references(root: Path | None = None) -> dict[str, dict[str, int]]:
    """2.5 系の参照を**本番／到達不能**と**コード／文書**に分ける（R1.5-C6）。

    分類の合計は走査の合計と必ず一致する（**取りこぼしを作らない**）。
    """
    root = Path(root if root is not None else Path(__file__).resolve().parents[1])
    到達 = reachable_modules(root)
    out: dict[str, dict[str, int]] = {
        "production_code": {}, "production_config": {},
        "production_doc": {}, "unreachable": {}}
    for rel, count in scan_sunset_references(root).items():
        if rel not in 到達:
            out["unreachable"][rel] = count
            continue
        コード, 文書 = split_code_and_doc(root / rel)
        if コード:
            out["production_code"][rel] = コード
        if 文書:
            out["production_doc"][rel] = 文書
    # **設定データは import を辿れないので全部を本番として扱う**（fail-closed）
    out["production_config"] = scan_config_model_ids(root)
    return out


def sunset_gate(分類: dict[str, dict[str, int]],
                report: "SunsetReport | None" = None) -> list[str]:
    """**段・実行記録・本番モジュールのいずれかに 2.5 系が残っていたら違反**（R1.5-C6）。

    文書と到達不能は数えるだけで落とさない。**区別できているからこそ
    落とさずに済む** — 区別できないうちは全部が疑わしいので落とす。

    **`report` を渡さないと段と実行記録の脚を見ない。** 2026-08-28 まで
    `分類` だけを見ており、実行記録に 2.5 が載っていても exit 0 だった
    （報告文には出るのに、判定に繋がっていなかった。gate-verifier 2周目の指摘）。
    """
    残り = [(p, c, "本番の実行経路から辿れます")
            for p, c in (分類.get("production_code") or {}).items()]
    残り += [(p, c, "設定データの値がそのまま API に渡ります")
             for p, c in (分類.get("production_config") or {}).items()]
    違反 = [f"{path}: {count} 箇所（{なぜ}）"
            for path, count, なぜ in sorted(残り, key=lambda x: (-x[1], x[0]))]

    if report is not None:
        for tier, model in sorted(report.tiers_at_risk.items()):
            違反.append(f"段 {tier}: {model}（段に 2.5 系が入っています）")
        for rid, models in sorted(report.runs_at_risk.items()):
            違反.append(f"実走 {rid}: {', '.join(models)}（実走で 2.5 系が動いています）")
        if report.run_count == 0:
            # **確かめていないことを緑にしない。** 条件文は「実行記録にも
            # 2.5 系が無いこと」を求めており、記録が無ければ示せない
            違反.append("実行記録が 0 件です"
                        "（実走で 2.5 系が動いたかどうかを確かめられません）")
    return 違反


def sunset_report(tier_models: dict[str, str] | None = None,
                  runs: list[dict] | None = None,
                  source_hits: dict[str, int] | None = None,
                  today: date | None = None) -> SunsetReport:
    """2.5 系への依存をまとめる（R1-C5）。"""
    if tier_models is None:
        tier_models = {t: (tiers().get(t) or {}).get("model", "")
                       for t in tier_order()}
    if source_hits is None:
        # **走査根を渡さない。** ここで `backend/` を渡していたせいで、
        # `scan_sunset_references` の既定をリポジトリ直下に広げても
        # `--sunset` の件数が変わらなかった（CLI はこの経路を通る）。
        source_hits = scan_sunset_references()
    runs = runs or []
    today = today or date.today()

    at_risk_tiers = {t: m for t, m in tier_models.items()
                     if m.startswith(SUNSET_PREFIX)}
    at_risk_runs: dict[str, list[str]] = {}
    for run in runs:
        used = [m for m in (run.get("models_used") or [])
                if m.startswith(SUNSET_PREFIX)]
        if used:
            at_risk_runs[run.get("run_id", "(id なし)")] = sorted(used)

    return SunsetReport(
        days_left=max(0, (SUNSET_DATE - today).days),
        tiers_at_risk=at_risk_tiers,
        runs_at_risk=at_risk_runs,
        source_hits=dict(source_hits),
        run_count=len(runs),
    )


def format_sunset(report: SunsetReport) -> str:
    """棚卸しを読める形にする。**0 件でも黙らない。**"""
    lines = [
        f"2.5 系の提供終了（{SUNSET_DATE.isoformat()}）への依存",
        "",
        f"  残り: {report.days_left} 日",
        "",
    ]

    if report.tiers_at_risk:
        lines.append(f"  🚫 段に 2.5 系が残っています（{len(report.tiers_at_risk)} 段）:")
        for tier, model in sorted(report.tiers_at_risk.items()):
            lines.append(f"      {tier}: {model}")
    else:
        lines.append("  ✅ 段に 2.5 系はありません。")
    lines.append("")

    # **記録が無いことを「使っていない」と読ませない。**
    if report.run_count == 0:
        lines.append("  ⚠ 実行記録がありません。"
                     "実走で 2.5 系が動いたかどうかは確かめられていません。")
    elif report.runs_at_risk:
        lines.append(f"  🚫 実走で 2.5 系が動いています（{len(report.runs_at_risk)} 実行）:")
        for rid, models in sorted(report.runs_at_risk.items()):
            lines.append(f"      {rid}: {', '.join(models)}")
    else:
        lines.append(f"  ✅ 実行記録 {report.run_count} 件のいずれでも "
                     "2.5 系は動いていません。")
    lines.append("")

    total = report.source_total
    lines.append(f"  ソースに残る 2.5 系の参照: **{total} 箇所** "
                 f"/ {len(report.source_hits)} ファイル")
    if total:
        lines.append("  **実走で通らない経路にも埋まっています。**"
                     "実行記録だけでは見えません。")
        for name, count in sorted(report.source_hits.items(),
                                  key=lambda kv: (-kv[1], kv[0]))[:15]:
            lines.append(f"      {count:3d}  {name}")
        if len(report.source_hits) > 15:
            lines.append(f"      … ほか {len(report.source_hits) - 15} ファイル")
    return "\n".join(lines)


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
    from backend.cost_guard import load_env
    load_env()
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
    parser.add_argument("--sunset", action="store_true",
                        help="2026-10-16 に終了する 2.5 系への依存を数える")
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

    if args.sunset:
        from backend.revenue.artifact_gate import load_runs
        try:
            runs = load_runs()
        except OSError:
            runs = []
        report = sunset_report(runs=runs)
        print(format_sunset(report))

        # **本番と到達不能を区別して数える**（R1.5-C6）。
        # 数えるだけでは条件を満たさない — 条件文は「区別できないうちは
        # FAIL する」と言っている。区別できているからこそ、文書と到達不能を
        # 落とさずに済む。
        分類 = classify_sunset_references()
        print()
        print(f"  本番の実行経路（本線と API から辿れる）: "
              f"**{sum(分類['production_code'].values())} 箇所**")
        print(f"  同・設定データの値（import を辿れないので本番として扱う）: "
              f"**{sum(分類['production_config'].values())} 箇所**")
        print(f"  同・文書（docstring / コメント / __main__ の自己テスト）: "
              f"{sum(分類['production_doc'].values())} 箇所")
        print(f"  到達不能（補助ツール・スクラッチ・フック等）: "
              f"{sum(分類['unreachable'].values())} 箇所 / "
              f"{len(分類['unreachable'])} ファイル")
        違反 = sunset_gate(分類, report)
        if 違反:
            print()
            print(f"🚫 **2.5 系への依存が残っています**（{len(違反)} 件）:")
            for m in 違反:
                print(f"    - {m}")
            return 1
        print()
        print("  ✅ 段・実行記録・本番の実行経路のいずれにも 2.5 系はありません。")
        return 0

    if args.audit:
        findings, why_not = audit()
        print(format_audit(findings, why_not))
        return 1 if findings else 0

    if args.json:
        print(json.dumps([asdict(resolve(t)) for t in known_tasks()],
                         ensure_ascii=False, indent=2))
    else:
        print(_format_show())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
