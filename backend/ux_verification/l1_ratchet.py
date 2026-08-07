"""L1 判定結果のラチェット — 項目ごとの非退行を保証する。

集計値だけを見るラチェットは「1件 PASS が消えて別の1件が PASS になった」を
見逃す。PASS 数は変わらないのに、保証していたはずの UX が1つ失われている。
ここでは**項目ごと**にベースラインと突き合わせ、PASS だった項目が FAIL に
なることと、項目そのものが消えることを違反として扱う。

    python -m backend.ux_verification.executor --persona owner --ratchet
    python -m backend.ux_verification.executor --persona owner --update-baseline

ベースラインは `backend/ux_verification/snapshots/l1_{persona}_baseline.json`。
判定が静的走査で環境に依存しないため、fs-guard のベースラインと違って
手元の実行値をそのまま使ってよい。

## 何を固定するか（3層）

1. **verdict** — PASS だった項目が FAIL に戻らない
2. **判定理由** — 内容まで見て判定していた項目が、経路の実在だけの判定に
   戻らない（`weakened`）
3. **宣言内容** — 項目が「何を測ると言っているか」そのもの（`substituted`）

3層目が P3 C-4 で足りていなかった。1・2 は宣言の**削除**を捕まえるが、
**差し替え**を素通りさせる。`response_field` を `hook_score` → `success` の
ような**実在するが別のフィールド**に付け替えると、`field_not_found` の FAIL が
`field_found` の PASS になり、理由コードは強いままなので違反ゼロ・
**改善1件**として記録される。description は変わっていないので、その項目が
要求する内容だけが静かに緩む（gate-verifier 5回目の指摘）。

宣言を変えること自体は禁じない。**黙って変えられないようにする。**
`--redeclare "理由"` で理由と before/after を履歴に残して締め直す。

## 記録の不在は「変化なし」ではない

3層はどれもベースラインの記録との比較なので、**記録を消せば比較が消える。**
`items` / `reasons` / `declarations` のどれか1冊から1行消すだけで、その項目の
退行・弱化・差し替えがまとめて見えなくなる。だから**いま在る項目が3冊すべてに
ピンされていること**を不変条件にする。

- **一部の冊にだけ残っている** → `tampered`。記録を間引いた跡で、何が失われたかを
  もう言えない。`--redeclare` も `--update-baseline` も受け付けない。git から戻す
- **3冊すべてに無く、集計欄も整合している** → `unpinned_new`。まだピンしていない
  新しい項目なので `--update-baseline` で通す。**何をピンしたかは `pins` に残す**
- **集計欄（`total` / `pass` / `fail`）が items と合わない、または欄ごと無い**
  → `tampered`。「無い＝照合しない」にすると、3行消すだけで検出器が丸ごと消える

締め直しの3つは役割を分ける。`--tighten` は判定を厳しくしたことによる PASS の
減少だけ、`--redeclare` は宣言の差し替えだけ（理由必須・before/after を記録）、
`--update-baseline` は新しい項目のピンだけ。**どれも他の種類の違反が1件でも
混じっていたら書かない。**

## 守れる範囲の端（正確に書く）

ここまでで守っているのは**記録の存在**であって、**記録の内容**ではない。
ベースラインは平文でリポジトリに置く記録なので、書き換えられること自体は
原理的に防げない。何が守られていないかを名指ししておく。

- **`reasons` / `declarations` の値は照合していない。** ベースライン側の
  `reasons` を1つ `field_found` → `found` に書き換えれば、集計欄にも員数にも
  触れずに違反ゼロで通り、その項目の `weakened` 検出器が恒久的に無効になる。
  **集計欄の辻褄合わせは要らない**（当初「端」をそう書いていたが、実態より
  緩い見積もりだった。gate-verifier 9回目）
- **履歴（`tightenings` / `redeclarations` / `pins`）は `check()` が一度も
  読まない。** 3つとも丸ごと消しても違反ゼロ。履歴は「検出の記録を人が
  差分で読むためのもの」であって、検出そのものには効いていない
- 集計欄まで辻褄を合わせた書き換えも当然通る

いずれも**このファイルを手で書き換える**ことが前提で、書き換えた事実は必ず
PR の差分に現れる。ベースラインを丸ごと消すのと同じ扱いで、**差分に出ることを
もって歯止めとする**。ここを機械で閉じるには、リポジトリの外か履歴（git）に
アンカーを置く必要があり、それはこのモジュールの範囲を超える。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .executor import L1Report

BASELINE_DIR = Path(__file__).parent / "snapshots"

# 「判定を厳しくしたから PASS が減った」と認めてよい**新しい**理由。
# これ以外の理由で PASS が減っていれば、それは実装の退行。
TIGHTENING_REASONS = (
    "field_not_found", "value_not_found", "request_field_not_found",
    "storage_key_not_found",
    # 「静的には判定できない」と結論した結果の FAIL。判定していないものを
    # PASS に逃がさない側の変更なので、厳格化として受け入れる。
    "unjudgeable",
)

# 前回すでに内容まで判定して PASS だった理由。ここから field_not_found に
# 落ちたのは「判定を厳しくした」ではなく**レスポンスからフィールドが消えた**。
# 新しい理由コードだけを見ていると、この2つが同じ顔で出てくる。
VERIFIED_PASS_REASONS = (
    "field_found", "value_found", "request_field_found", "storage_key_found",
)

# 「レスポンス内容まで見て判定した」ことを示す理由コード。PASS でも FAIL でも、
# ここから外れたら判定の強さが落ちたということ。
CONTENT_JUDGED_REASONS = (
    "field_found", "field_not_found",
    "value_found", "value_not_found",
    "request_field_found", "request_field_not_found",
    "storage_key_found", "storage_key_not_found",
    # 判定できないと結論した状態も「主張に向き合った」側。ここから
    # 経路の実在だけの found へ戻るのは、向き合うのをやめたということ。
    "unjudgeable",
)


def _is_content_judged(reason: str | None) -> bool:
    return reason in CONTENT_JUDGED_REASONS


def _render_declaration(declaration: dict | None) -> str:
    if not declaration:
        return "（宣言なし）"
    return " ".join(
        f"{k}={json.dumps(v, ensure_ascii=False)}" if not isinstance(v, str) else f"{k}={v}"
        for k, v in sorted(declaration.items())
    )


def baseline_path(persona: str) -> Path:
    return BASELINE_DIR / f"l1_{persona}_baseline.json"


def write_baseline(report: L1Report, path: Path,
                   tightenings: list | None = None,
                   redeclarations: list | None = None,
                   pins: list | None = None) -> Path:
    """判定を項目ごとに書き出す。

    タイムスタンプは入れない。毎回書き換わる欄があると、実質的な変化が
    差分に埋もれて読めなくなる。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "persona": report.persona,
        "layer": 1,
        "method": report.method,
        "total": report.total,
        "pass": report.pass_count,
        "fail": report.fail_count,
        "items": {r.item_id: r.verdict.value for r in report.results},
        # 判定理由も残す。PASS/FAIL だけでは「経路の実在で PASS」と
        # 「内容まで見て PASS」を区別できず、--tighten が内容の退行を
        # 厳格化として受理してしまう。
        "reasons": {r.item_id: r.reason for r in report.results},
        # 宣言内容も残す。理由コードは「何を測ったか」の**種類**しか持たず、
        # 「どれを測ったか」を持たない。差し替えはここでしか見えない。
        "declarations": {r.item_id: r.declaration for r in report.results},
    }
    if tightenings:
        # 判定を厳しくして PASS が減った履歴。消すと「昔は緑だった」が
        # 見えなくなり、退行と区別が付かなくなる。
        payload["tightenings"] = tightenings
    if redeclarations:
        # 宣言を差し替えた履歴。理由と before/after を残す。
        payload["redeclarations"] = redeclarations
    if pins:
        # 新しくピンした項目の履歴。理由は要らないが記録は要る——記録を消して
        # 「新しい項目」に化けさせたものを、履歴ゼロで締め直せなくするため。
        payload["pins"] = pins
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    return path


def load_baseline(path: Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class L1Violation:
    kind: str  # regressed | removed | weakened | substituted
              # | unpinned_new | tampered
    item_id: str
    before: str
    after: str

    def __str__(self) -> str:
        if self.kind == "removed":
            return f"[削除] {self.item_id}: {self.before} → 項目が存在しない"
        if self.kind == "weakened":
            return (
                f"[判定の弱化] {self.item_id}: {self.before} → {self.after}"
                "（レスポンス内容を見なくなった）"
            )
        if self.kind == "substituted":
            return (
                f"[宣言の差し替え] {self.item_id}: {self.before} → {self.after}"
                "（測る対象そのものが変わった）"
            )
        if self.kind == "unpinned_new":
            return (
                f"[未ピン] {self.item_id}: ベースラインに無い新しい項目"
                "（--update-baseline でピンしてください）"
            )
        if self.kind == "tampered":
            return (
                f"[記録の欠落] {self.item_id}: {self.before}"
                "（ピンを間引いた跡。何が失われたか言えないので、"
                "git からベースラインを戻してください）"
            )
        return f"[退行] {self.item_id}: {self.before} → {self.after}"


@dataclass
class L1RatchetResult:
    valid: bool
    violations: list[L1Violation] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    baseline_missing: bool = False
    before_pass: int = 0
    after_pass: int = 0

    def to_text(self) -> str:
        if self.baseline_missing:
            return (
                "🚫 ベースラインがありません。--update-baseline で作成してください"
                f"（現在 PASS {self.after_pass}件）。\n"
                "  ベースラインが無い状態を緑にすると、ファイルを消すだけで"
                "ラチェットを無効化できてしまうため失敗として扱います。"
            )
        head = (
            f"L1 ラチェット: PASS {self.before_pass} → {self.after_pass}"
            f"（改善 {len(self.improvements)} / 新規 {len(self.added)}）"
        )
        if self.valid:
            return f"✅ {head}"
        lines = [f"🚫 {head}", f"  {len(self.violations)}件の違反:"]
        lines += [f"    {v}" for v in self.violations]
        kinds = {v.kind for v in self.violations}
        if kinds - {"substituted", "unpinned_new", "tampered"}:
            lines.append(
                "\n  PASS だった項目が FAIL に戻っています。frontend から "
                "data-testid が消えたか、ストーリー側の testid が書き換わっています。"
                "意図した変更なら --update-baseline で締め直してください。"
            )
        if kinds & {"substituted", "unpinned_new", "tampered"}:
            lines.append(
                "\n  項目が**何を測ると宣言しているか**がベースラインと違います。"
                "verdict と理由コードは同じでも、要求している内容が変わっています。"
                "\n  意図した変更なら --redeclare \"理由\" で締め直してください"
                "（理由と before/after がベースラインに残ります）。"
            )
        return "\n".join(lines)


class L1Ratchet:
    """項目ごとの非退行を検証する。"""

    def check(self, report: L1Report, baseline: dict | None) -> L1RatchetResult:
        if baseline is None:
            return L1RatchetResult(
                valid=True, baseline_missing=True, after_pass=report.pass_count
            )

        before: dict[str, str] = baseline.get("items", {})
        after = {r.item_id: r.verdict.value for r in report.results}
        before_reasons: dict[str, str] = baseline.get("reasons") or {}
        after_reasons = {r.item_id: r.reason for r in report.results}
        before_decls: dict[str, dict] = baseline.get("declarations") or {}
        after_decls = {r.item_id: r.declaration for r in report.results}

        violations: list[L1Violation] = []
        improvements: list[str] = []

        # --- ベースライン自身の整合性 --------------------------------------
        #
        # ここまでの検出はすべて「ベースラインの記録との比較」なので、
        # **記録を消せば比較が消える。** 6回目で3冊のピンを不変条件にしたが、
        # 3冊すべてから同じ項目を消せば「新しい項目」に化け、集計欄
        # （total / pass / fail）はどこからも照合されていなかったため、
        # 消したこと自体が痕跡を残さなかった（7回目）。
        #
        # 集計欄を items と突き合わせる。ピンを1件でも間引けば、必ずここで落ちる。
        #
        # **欄が無いことを「照合しない」にしない。** 値の書き換えだけを見て
        # `recorded is not None` で素通りさせていたので、3つの欄をキーごと消せば
        # 照合が丸ごと消え、間引きが exit 0 で通った（8回目）。無い欄は
        # 「合っている」ではなく「照合できない」。
        tampered: list[tuple[str, str]] = []
        counted = {
            "total": (baseline.get("total"), len(before)),
            "pass": (baseline.get("pass"),
                     sum(1 for v in before.values() if v == "PASS")),
            "fail": (baseline.get("fail"),
                     sum(1 for v in before.values() if v == "FAIL")),
        }
        for name, (recorded, actual) in counted.items():
            if recorded is None:
                tampered.append((name, f"{name} の欄がベースラインに無い"))
            elif recorded != actual:
                tampered.append((name, f"{name}={recorded} だが items は {actual}件"))
        for name, why in tampered:
            violations.append(L1Violation("tampered", f"baseline.{name}", why, "—"))

        # 3冊（items / reasons / declarations）と**現在の項目**が食い違っている
        # ものを洗い出す。記録が無いものは「変化なし」ではなく「分からない」。
        #
        # 既知の項目は3冊の**和**で数える。`items` からだけ消すと、その項目は
        # before に居なくなって比較ループに一度も入らず、退行も差し替えも
        # まとめて消える（6回目の穴1）。和で持てば、どの冊に1行でも残っていれば
        # 「前は在った項目」として扱える。
        known_ids = set(before) | set(before_reasons) | set(before_decls)
        pinned_books = (
            ("verdict がベースラインに無い", before),
            ("前回の判定理由がベースラインに無い", before_reasons),
            ("前回の宣言がベースラインに無い", before_decls),
        )
        # **3冊の一部にだけ残っている状態は「未ピン」ではなく「記録を消した跡」。**
        # 集計欄は items としか突き合わせていないので、reasons と declarations から
        # 消すだけなら集計に触れずに済み、`substituted` が `unpinned` に格下げされて
        # 失った内容が表示されないまま --redeclare が飲み込んだ（8回目）。
        # 3冊が食い違っていること自体を tampered として、締め直しでは直せなくする。
        unpinned_ids: set[str] = set()
        for item_id in sorted(set(after) | known_ids):
            if item_id not in after and item_id in known_ids:
                continue  # 項目そのものの消滅は下のループが removed として出す
            missing = [label for label, book in pinned_books if item_id not in book]
            if not missing:
                continue
            unpinned_ids.add(item_id)
            if len(missing) == len(pinned_books) and not tampered:
                # 3冊すべてに無く、集計も整合している＝**まだピンしていない
                # 新しい項目**。--update-baseline でピンしてよい（何をピンしたかは
                # 履歴に残る）。
                violations.append(L1Violation("unpinned_new", item_id, "—", "—"))
            else:
                violations.append(L1Violation(
                    "tampered", item_id, "・".join(missing), "—"))

        for item_id in sorted(known_ids):
            was = before.get(item_id)
            now = after.get(item_id)
            if now is None:
                violations.append(L1Violation("removed", item_id, was or "?", "—"))
                continue

            # unpinned でも**ここで打ち切らない。** 記録の欠落を退行の目隠しに
            # 使えてしまう（`declarations` から1行消すと unpinned だけが出て
            # 退行が報告されず、--redeclare がそれを受理する）。
            if was == "PASS" and now != "PASS":
                violations.append(L1Violation("regressed", item_id, was, now))
                continue

            # 理由コードは「何を測ったか」の**種類**しか持たない。どれを測ったかは
            # 宣言にしかないので、宣言が変われば同じ理由コードのまま別物を
            # 測っている。FAIL → PASS になっていても、それは実装が良くなった
            # 証拠ではなく、要求を取り替えた結果でしかない。
            if (item_id in before_decls
                    and before_decls[item_id] != after_decls.get(item_id)):
                violations.append(L1Violation(
                    "substituted", item_id,
                    _render_declaration(before_decls[item_id]),
                    _render_declaration(after_decls.get(item_id)),
                ))
                continue

            # verdict だけを見ていると、**判定の強さ**が落ちたことに気づけない。
            # 項目から response_field を消せば field_found → found（PASS のまま）、
            # field_not_found → found（FAIL → PASS で「改善」に見える）。
            # どちらもラチェットは緑で、内容の判定が丸ごと巻き戻る。
            was_content = _is_content_judged(before_reasons.get(item_id))
            if was_content and not _is_content_judged(after_reasons.get(item_id)):
                violations.append(L1Violation(
                    "weakened", item_id,
                    before_reasons.get(item_id, "?"), after_reasons.get(item_id, "?"),
                ))
            elif was != "PASS" and now == "PASS" and item_id not in unpinned_ids:
                improvements.append(item_id)

        added = [i for i in after if i not in before]

        return L1RatchetResult(
            valid=not violations,
            violations=violations,
            improvements=improvements,
            added=added,
            before_pass=int(baseline.get("pass", 0)),
            after_pass=report.pass_count,
        )

    def update(self, report: L1Report, path: Path) -> Path:
        """ベースラインを現在値で締め直す。退行が残っていれば拒否する。

        退行したまま緩めれば、退行が無かったことになる。
        """
        baseline = load_baseline(path)
        result = self.check(report, baseline)
        # まだピンしていない新しい項目だけは、ここで理由なしにピンしてよい。
        # それ以外が1件でも混じっていたら書かない——退行を未ピンに紛れ込ませて
        # 通せるようにすると、締め直しが抜け道になる。
        blocking = [v for v in result.violations if v.kind != "unpinned_new"]
        if blocking:
            raise ValueError(
                "退行が残っているためベースラインを更新できません:\n"
                + "\n".join(f"  {v}" for v in blocking)
            )
        # **何を新しくピンしたかを残す。** 理由は要らないが、記録は要る。
        # 残さないと、記録を消して「新しい項目」に化けさせたものを、履歴ゼロで
        # 締め直せてしまう（8回目の指摘②）。
        pins = list((baseline or {}).get("pins") or [])
        newly = sorted(v.item_id for v in result.violations
                       if v.kind == "unpinned_new")
        if newly:
            after_decls = {r.item_id: r.declaration for r in report.results}
            after_items = {r.item_id: r.verdict.value for r in report.results}
            pins.append({
                "items": {
                    item_id: {
                        "verdict": after_items.get(item_id),
                        "declaration": after_decls.get(item_id),
                    }
                    for item_id in newly
                },
            })
        return write_baseline(report, path,
                              (baseline or {}).get("tightenings"),
                              (baseline or {}).get("redeclarations"),
                              pins)

    def redeclare(self, report: L1Report, path: Path, reason: str) -> Path:
        """**宣言の差し替え**だけを受け入れて締め直す。

        宣言を変えること自体は正当な作業（誤った `response_field` を直す、
        判定手段を足して `claim` を強い側へ移す）。禁じるのは**黙って**
        変えることのほう。理由を必須にし、before/after を履歴に残す。

        受け入れるのは `substituted` だけ。verdict の退行・判定の弱化・
        記録の欠落（`tampered`）が混じっていたら拒否する。差し替えに
        紛れ込ませて通せるようにすると、履歴を残す意味が無くなる。
        とくに `tampered` を受けてはいけない——記録が消えている項目は
        before が `null` になるので、**何が弱くなったかを履歴に書けない。**

        **これは「差し替えを禁止する」機能ではない。** C-4 が求めているのは
        検出であって禁止ではないので、通した記録が永久に残るところまでを
        保証する。FAIL → PASS を買う差し替えも、理由と before/after が
        ベースラインの差分に出る。
        """
        if not reason.strip():
            raise ValueError(
                "差し替えの理由は必須です。何を測る対象に変えたのかを書いてください")

        baseline = load_baseline(path)
        result = self.check(report, baseline)
        before_decls = (baseline or {}).get("declarations") or {}

        illegitimate = [v for v in result.violations if v.kind != "substituted"]
        if illegitimate:
            raise ValueError(
                "宣言の差し替えでは説明できない違反が混じっています:\n"
                + "\n".join(f"  {v}" for v in illegitimate)
                + "\n  退行・判定の弱化は、宣言の差し替えとは分けて扱ってください。"
            )

        after_decls = {r.item_id: r.declaration for r in report.results}
        changed = [v.item_id for v in result.violations]
        history = list((baseline or {}).get("redeclarations") or [])
        history.append({
            "reason": reason.strip(),
            "items": {
                item_id: {
                    "before": before_decls.get(item_id),
                    "after": after_decls.get(item_id),
                }
                for item_id in sorted(changed)
            },
        })
        return write_baseline(report, path,
                              (baseline or {}).get("tightenings"), history,
                              (baseline or {}).get("pins"))

    def tighten(self, report: L1Report, path: Path, reason: str,
                allowed_reasons: tuple = TIGHTENING_REASONS) -> Path:
        """**判定を厳しくしたことによる** PASS の減少だけを受け入れて締め直す。

        ラチェットは「実装が退行していないこと」を守る道具で、
        「測り方を厳しくしてはいけない」という意味ではない。だが両者は
        どちらも PASS の減少として現れるので、機械的に区別できないと
        「厳しくした」と言えば何でも通せてしまう。

        そこで2つの側から絞る。

        1. **新しい判定理由**が厳格化に由来するものだけ。`not_found`（実体が
           消えた）や `unregistered`（登録が外れた）や項目の削除は拒否する
        2. **前回の判定理由**が「内容まで見て PASS」でないこと。
           `field_found` → `field_not_found` は厳格化ではなく、
           **レスポンスからフィールドが消えた**——まさに守りたかった退行そのもの。
           新しい理由コードだけを見ていると、この2つが同じ顔で出てくる

        理由は必須で、ベースラインに履歴として残す。
        """
        if not reason.strip():
            raise ValueError(
                "厳格化の理由は必須です。何を厳しくしたのかを書いてください")

        baseline = load_baseline(path)
        result = self.check(report, baseline)
        reasons = {r.item_id: r.reason for r in report.results}
        before_reasons = (baseline or {}).get("reasons")

        if result.violations and before_reasons is None:
            raise ValueError(
                "ベースラインに判定理由（reasons）が記録されていないため、"
                "厳格化と退行を区別できません。\n"
                "  先に --update-baseline で理由付きのベースラインを作り直して"
                "ください。区別できないものを通すと、--tighten が"
                "何でも受理する抜け道になります。"
            )

        illegitimate = []
        for v in result.violations:
            if v.kind != "regressed" or reasons.get(v.item_id) not in allowed_reasons:
                illegitimate.append((v, reasons.get(v.item_id, "不明")))
            elif v.item_id not in (before_reasons or {}):
                # 辞書ごとの不在だけを見ていると、1項目分の理由を消すだけで
                # ここを素通りできる。項目単位でも「分からない」は通さない。
                illegitimate.append((v, "前回の判定理由がベースラインに無い"))
            elif before_reasons[v.item_id] in VERIFIED_PASS_REASONS:
                illegitimate.append((v, "前回は内容まで見て PASS だった"))
        if illegitimate:
            raise ValueError(
                "厳格化では説明できない退行が混じっています:\n"
                + "\n".join(f"  {v}（{why}）" for v, why in illegitimate)
                + "\n  実装の退行と、判定の厳格化は分けて扱ってください。"
            )

        history = list((baseline or {}).get("tightenings") or [])
        history.append({
            "reason": reason.strip(),
            "items": sorted(v.item_id for v in result.violations),
        })
        return write_baseline(report, path, history,
                              (baseline or {}).get("redeclarations"),
                              (baseline or {}).get("pins"))
