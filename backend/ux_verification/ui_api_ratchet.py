"""UI と API の接続のラチェット（P4 C-4）。

`ui_api --gate` は「いま突き合わないものがゼロか」しか見ない。**呼び出しを
消せばゼロのまま緑になる。** ゲートだけでは判定の弱化を止められないので、
呼び出し先の一覧をベースラインに固定し、次の5つを落とす:

1. **走査0件で緑** — ベースラインが無い / 呼び出しを1件も読めない
2. **呼び出しの削除** — ベースラインにある呼び出しが消えた（`removed`）。
   呼び出し口への移行（P5）だけは `--migrate` で受理するが、**受理するのは
   「同じ backend の宣言にカタログ経由でいまも届いている」ものだけ**で、
   届いていない削除は受理しない。受理した分は `migrations` に理由つきで残り、
   PR の差分に必ず出る
3. **unresolved の握りつぶし** — 2経路ある。PASS する判定を `matched` 以外に
   広げる（`semantics_widened`）と、**走査の閉包そのものを緩める**
   （`scan_widened`）。後者は判定表の外なので、判定表だけ見ていると通る
4. **宣言の差し替え** — 同じ呼び出しが別の宣言に当たるようになった
   （`substituted`）。パスもメソッドも変えずに、当たり先だけ入れ替わる
5. **判定の対象から外す** — ファイルを到達不能にする（`unreachable_grew`）

P3 の C-4 が残した穴（集計欄と本体を突き合わせていない）はここでは作らない。
**照合しない欄はそもそも書かない。** ベースラインに載っているのは
`DECLARATION_KEYS` の5つだけで、その全部を check() が読む。

## 守れない範囲（隠さずに書く）

- **同じファイルから同じメソッド・同じパスを何度呼んでも1件として数える。**
  固定しているのは「フロントがどの宣言を呼んでいるか」であって、
  何回呼んでいるかではない。7箇所あるうち6箇所を消しても違反にならない
- **ベースラインを手で書き換えれば通る。** ただし書き換えた事実は必ず
  PR の差分に出る。ベースラインを消すのと同じ扱いで、差分に出ることをもって
  歯止めとする（P3 C-4 と同じ限界。機械で閉じるにはリポジトリの外に
  アンカーが要る）

    python -m backend.ux_verification.ui_api_ratchet --ratchet
    python -m backend.ux_verification.ui_api_ratchet --update-baseline
    python -m backend.ux_verification.ui_api_ratchet --redeclare "理由"
    python -m backend.ux_verification.ui_api_ratchet --migrate "理由"
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from backend.ux_verification.ui_api import (
    _GLOBAL_RECEIVERS,
    CATALOGUE_REL,
    MISMATCH_VERDICTS,
    SCANNED_FORMS,
    SCANNED_SUFFIXES,
    UNSCANNED_FORMS,
    VERDICT_SEMANTICS,
    UiApiExecutor,
    UiApiReport,
    Verdict,
)

BASELINE_DIR = Path(__file__).parent / "snapshots"
BASELINE = BASELINE_DIR / "ui_api_baseline.json"

# ベースラインに固定するキー。ここに無い欄は check() が読まない＝守られない。
# 欄を足したら必ずここにも足す。**足し忘れをテストで禁じる。**
DECLARATION_KEYS = ("sites", "declarations", "unreachable", "passing_verdicts",
                    "scan_boundary")


def site_key(site) -> str:
    """呼び出し1件を指す鍵。行番号は入れない（無関係な編集で全件動く）。"""
    return f"{site.file}|{site.method or '?'}|{site.path or site.raw_url}"


def passing_verdicts() -> list[str]:
    """いま PASS 扱いになっている判定。**広がったらそれ自体が違反。**"""
    return sorted(v.value for v, m in VERDICT_SEMANTICS.items()
                  if m["PASS"] == "yes")


def _render(value) -> str:
    if isinstance(value, dict):
        return "/".join(sorted(value))
    if isinstance(value, (list, tuple, set)):
        return "/".join(sorted(str(v) for v in value))
    return str(value)


def scan_boundary() -> dict:
    """走査の閉包そのもの。**緩めたらそれ自体が違反。**

    受け側の集合を広げる・走査できない形の一覧から1つ落とす、だけで
    unresolved を matched に変えられる。判定の弱化は判定表の外にもある
    （gate-verifier 2回目の指摘）。
    """
    return {
        "scanned_files": sorted(SCANNED_SUFFIXES),
        "scanned_forms": sorted(SCANNED_FORMS),
        # **正規表現の本体まで固定する。** キー名だけを固定していると、
        # パターンを絶対に当たらないものに差し替えるだけで、その形の検出が
        # 黙って無効になる（gate-verifier 4回目の指摘）。
        "unscanned_forms": {name: pattern.pattern
                            for name, pattern in sorted(UNSCANNED_FORMS.items())},
        "global_receivers": sorted(_GLOBAL_RECEIVERS),
        "mismatch_verdicts": sorted(v.value for v in MISMATCH_VERDICTS),
    }


def write_baseline(report: UiApiReport, path: Path,
                   redeclarations: list | None = None,
                   migrations: list | None = None,
                   resolutions: list | None = None) -> Path:
    """呼び出しごとに書き出す。タイムスタンプは入れない。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "method": "static_fetch_scan",
        "sites": {site_key(s): s.verdict.value for s in report.sites},
        # どの宣言に当たったか。パスとメソッドが同じままでも当たり先は変わる。
        "declarations": {site_key(s): s.declared_at for s in report.sites},
        # 到達不能なファイルにある fetch。増えるのは「到達不能にすれば
        # ゲートを避けられる」経路そのもの。
        "unreachable": sorted(report.unreachable),
        # PASS 扱いの判定。ここが広がることが「unresolved の握りつぶし」。
        "passing_verdicts": passing_verdicts(),
        # 走査の閉包。緩めれば読めなかったものが読めたことになる。
        "scan_boundary": scan_boundary(),
    }
    if redeclarations:
        payload["redeclarations"] = redeclarations
    if migrations:
        # 呼び出し口への移行で消えた呼び出しの履歴。**差分に必ず出す。**
        payload["migrations"] = migrations
    if resolutions:
        # 読めなかった記述を直して消した履歴。**差分に必ず出す。**
        payload["resolutions"] = resolutions
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    return path


def load_baseline(path: Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


@dataclass
class Violation:
    kind: str  # removed | weakened | substituted | unpinned_new
               # | unreachable_grew | semantics_widened | scan_widened | tampered
    key: str
    before: str = ""
    after: str = ""

    def __str__(self) -> str:
        if self.kind == "removed":
            return f"[削除] {self.key}: {self.before} → 呼び出しが存在しない"
        if self.kind == "weakened":
            return f"[判定の弱化] {self.key}: {self.before} → {self.after}"
        if self.kind == "substituted":
            return (f"[宣言の差し替え] {self.key}: {self.before} → {self.after}"
                    "（当たり先が変わった。--redeclare で理由を残してください）")
        if self.kind == "unpinned_new":
            return (f"[未ピン] {self.key}: ベースラインに無い呼び出し"
                    "（--update-baseline でピンしてください）")
        if self.kind == "unreachable_grew":
            return (f"[到達不能が増えた] {self.key}"
                    "（判定の対象から外れた。到達可能にするか理由を残してください）")
        if self.kind == "scan_widened":
            return (f"[走査の閉包が緩んだ] {self.key}: {self.before} → {self.after}"
                    "（読めなかったものが読めたことになる）")
        if self.kind == "semantics_widened":
            return (f"[判定の握りつぶし] PASS 扱いの判定が {self.before} から "
                    f"{self.after} に広がった")
        return f"[記録の欠落] {self.key}: {self.before}"


@dataclass
class RatchetResult:
    valid: bool
    violations: list[Violation] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    baseline_missing: bool = False
    before: int = 0
    after: int = 0

    def to_text(self) -> str:
        if self.baseline_missing:
            return (
                "🚫 ベースラインがありません。--update-baseline で作成してください"
                f"（現在 {self.after} 件）。\n"
                "  ベースラインが無い状態を緑にすると、ファイルを消すだけで"
                "ラチェットを無効化できてしまうため失敗として扱います。"
            )
        head = (f"UI-API ラチェット: 呼び出し先 {self.before} → {self.after}"
                f"（新規 {len(self.added)}）")
        if self.valid:
            return f"✅ {head}"
        lines = [f"🚫 {head}", f"  {len(self.violations)}件の違反:"]
        lines += [f"    {v}" for v in self.violations]
        return "\n".join(lines)


class UiApiRatchet:
    def check(self, report: UiApiReport, baseline: dict | None) -> RatchetResult:
        now_pass = sum(1 for s in report.sites if s.passed)
        if baseline is None:
            return RatchetResult(False, baseline_missing=True,
                                 after=len({site_key(s) for s in report.sites}))

        violations: list[Violation] = []

        # 記録が欠けていたら、何が失われたか言えない。無検査にはしない。
        for key in DECLARATION_KEYS:
            if key not in baseline:
                violations.append(Violation("tampered", key,
                                            "ベースラインにこの欄が無い"))
        if violations:
            return RatchetResult(False, violations, after=now_pass)

        # 判定そのものの弱化。**呼び出しを1件も見ずに分かる。**
        before_pass_kinds = list(baseline["passing_verdicts"])
        now_kinds = passing_verdicts()
        if set(now_kinds) - set(before_pass_kinds):
            violations.append(Violation("semantics_widened", "VERDICT_SEMANTICS",
                                        "/".join(before_pass_kinds),
                                        "/".join(now_kinds)))

        # 走査の閉包が緩んでいないか。**呼び出しを1件も見ずに分かる弱化。**
        before_scan = baseline["scan_boundary"]
        now_scan = scan_boundary()
        # 入れ子の欄を1つ消せば、その欄だけ無検査になる。トップレベルの有無だけ
        # 見ていると素通りする（gate-verifier 3回目の指摘）。
        missing = [k for k in now_scan if k not in before_scan]
        if missing:
            violations.append(Violation(
                "tampered", "scan_boundary",
                f"入れ子の欄が無い（{'/'.join(sorted(missing))}）"))
            return RatchetResult(False, violations, after=now_pass)
        for field_name, before_values in before_scan.items():
            after = now_scan.get(field_name)
            # **どちらに動いても違反にする。** 増えれば「読めなかったものが
            # 読めたことになる」、減れば「見えていたものが見えなくなる」。
            # 片方向だけ見ていると、集合を縮める経路が素通りする
            # （gate-verifier 4回目の指摘: mismatch_verdicts の縮小）。
            if before_values != after:
                violations.append(Violation(
                    "scan_widened", field_name, _render(before_values),
                    _render(after)))

        current = {site_key(s): s for s in report.sites}
        base_sites: dict = baseline["sites"]
        base_decls: dict = baseline["declarations"]

        for key, before in base_sites.items():
            site = current.get(key)
            if site is None:
                violations.append(Violation("removed", key, before))
                continue
            if before == Verdict.MATCHED.value and not site.passed:
                violations.append(Violation("weakened", key, before,
                                            site.verdict.value))
                continue
            declared = base_decls.get(key)
            if site.passed and not declared:
                # 空にすれば差し替え検査が消える、を塞ぐ（gate-verifier 1回目）。
                violations.append(Violation("tampered", key,
                                            "PASS なのに宣言の記録が空"))
                continue
            if declared and declared != site.declared_at:
                # 実行側で空にしても差し替え扱いにする。「空＝無検査」を
                # ベースライン側だけ塞いでも、実行側に同じ穴が残る
                # （gate-verifier 3回目の指摘）。
                violations.append(Violation("substituted", key, declared,
                                            site.declared_at or "（記録なし）"))

        added = sorted(set(current) - set(base_sites))
        violations += [Violation("unpinned_new", key) for key in added]

        grew = sorted(set(report.unreachable) - set(baseline["unreachable"]))
        violations += [Violation("unreachable_grew", key) for key in grew]

        return RatchetResult(not violations, violations, added,
                             before=len(base_sites), after=len(current))

    def update(self, report: UiApiReport, path: Path) -> Path:
        """新しい呼び出しをピンする。**退行・差し替えは受理しない。**"""
        baseline = load_baseline(path)
        result = self.check(report, baseline)
        blocking = [v for v in result.violations if v.kind != "unpinned_new"]
        if blocking and not result.baseline_missing:
            raise ValueError(
                "違反が残っているので更新できません:\n"
                + "\n".join(f"  {v}" for v in blocking))
        return write_baseline(report, path,
                              (baseline or {}).get("redeclarations"),
                              migrations=(baseline or {}).get("migrations"),
                              resolutions=(baseline or {}).get("resolutions"))

    def migrate(self, report: UiApiReport, path: Path, reason: str) -> Path:
        """呼び出し口への移行で消えた呼び出しを、理由つきで受理する（P5）。

        **無条件の削除は受理しない。** 受理するのは「同じ backend の宣言に、
        カタログ経由でいまも届いている」ものだけ。届いていないものは移行では
        なく削除なので、`removed` のまま残す。

        判定に使うのはベースラインが持つ `declarations`（当たった宣言の場所）。
        パスの表記は移行で変わる（`/stream/preview` → `/stream/{video_type}`）
        ので、パス文字列で照合すると本当の移行まで弾く。**当たり先で照合する。**
        """
        if not reason.strip():
            raise ValueError("--migrate には理由が要ります")
        baseline = load_baseline(path)
        if baseline is None:
            raise ValueError("ベースラインがありません")
        result = self.check(report, baseline)

        # いまカタログ経由で届いている宣言。ここに載っていない削除は削除。
        reachable = {s.declared_at for s in report.sites
                     if s.passed and s.file.endswith(CATALOGUE_REL.split("/")[-1])
                     and s.declared_at}
        base_decls: dict = baseline.get("declarations") or {}
        moved, lost = [], []
        for violation in result.violations:
            if violation.kind != "removed":
                continue
            (moved if base_decls.get(violation.key) in reachable
             else lost).append(violation)
        if lost:
            raise ValueError(
                "カタログに届いていない削除があります（移行ではありません）:\n"
                + "\n".join(f"  {v}" for v in lost))

        blocking = [v for v in result.violations
                    if v.kind not in ("removed", "unpinned_new")]
        if blocking:
            raise ValueError(
                "移行以外の違反が残っています:\n"
                + "\n".join(f"  {v}" for v in blocking))

        history = list(baseline.get("migrations") or [])
        history += [{"key": v.key, "was": v.before,
                     "now_via": base_decls.get(v.key, ""),
                     "reason": reason.strip()} for v in moved]
        return write_baseline(report, path,
                              (baseline or {}).get("redeclarations"),
                              migrations=history,
                              resolutions=baseline.get("resolutions"))

    def resolve(self, report: UiApiReport, path: Path, reason: str) -> Path:
        """**読めなかった記述を消したことを、理由つきで受理する。**

        `unscanned_form` や `unresolved_url` のサイトは「ここに読めないものが
        ある」という FAIL の印であって、突き合った呼び出しではない。それを
        コードごと直して消すのは**改善**なのに、`removed` として一律に拒むと
        「読めない構文を永久に残す」しか道が無くなる。

        受理するのは**ベースラインで matched でなかったサイトの削除だけ**。
        matched（＝突き合っていた呼び出し）の削除は、いまも `--migrate` で
        「同じ宣言にカタログ経由で届いている」ことを示さない限り通らない。
        受理した分は `resolutions` に残り、PR の差分に必ず出る。
        """
        if not reason.strip():
            raise ValueError("--resolve には理由が要ります")
        baseline = load_baseline(path)
        if baseline is None:
            raise ValueError("ベースラインがありません")
        result = self.check(report, baseline)

        matched_removals = [v for v in result.violations
                            if v.kind == "removed"
                            and v.before == Verdict.MATCHED.value]
        if matched_removals:
            raise ValueError(
                "突き合っていた呼び出しの削除は --resolve では受理しません"
                "（--migrate で移行先を示してください）:\n"
                + "\n".join(f"  {v}" for v in matched_removals))

        blocking = [v for v in result.violations
                    if v.kind not in ("removed", "unpinned_new")]
        if blocking:
            raise ValueError(
                "削除以外の違反が残っています:\n"
                + "\n".join(f"  {v}" for v in blocking))

        history = list(baseline.get("resolutions") or [])
        history += [{"key": v.key, "was": v.before, "reason": reason.strip()}
                    for v in result.violations if v.kind == "removed"]
        return write_baseline(report, path,
                              (baseline or {}).get("redeclarations"),
                              migrations=baseline.get("migrations"),
                              resolutions=history)

    def redeclare(self, report: UiApiReport, path: Path, reason: str) -> Path:
        """当たり先の差し替えを理由つきで受理する。"""
        if not reason.strip():
            raise ValueError("--redeclare には理由が要ります")
        baseline = load_baseline(path)
        if baseline is None:
            raise ValueError("ベースラインがありません")
        result = self.check(report, baseline)
        blocking = [v for v in result.violations
                    if v.kind not in ("substituted", "unpinned_new")]
        if blocking:
            raise ValueError(
                "差し替え以外の違反が残っています:\n"
                + "\n".join(f"  {v}" for v in blocking))
        history = list(baseline.get("redeclarations") or [])
        history += [{"key": v.key, "before": v.before, "after": v.after,
                     "reason": reason.strip()}
                    for v in result.violations if v.kind == "substituted"]
        return write_baseline(report, path, history,
                              migrations=baseline.get("migrations"),
                              resolutions=baseline.get("resolutions"))


# --- CLI ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UI と API の接続のラチェット")
    parser.add_argument("--ratchet", action="store_true",
                        help="ベースラインと突き合わせ、違反があれば exit 1")
    parser.add_argument("--update-baseline", action="store_true",
                        help="新しい呼び出しをピンする")
    parser.add_argument("--redeclare", metavar="理由",
                        help="当たり先の差し替えを理由つきで受理する")
    parser.add_argument("--migrate", metavar="理由",
                        help="呼び出し口への移行で消えた呼び出しを理由つきで受理する"
                             "（カタログ経由で同じ宣言に届いているものだけ）")
    parser.add_argument("--resolve", metavar="理由",
                        help="読めなかった記述を直して消したことを理由つきで受理する"
                             "（matched だったサイトの削除は受理しない）")
    args = parser.parse_args(argv)

    report = UiApiExecutor.for_repo().run()
    ratchet = UiApiRatchet()

    # 走査0件を緑にしない。ラチェットは「変化が無い」ことしか見ないので、
    # 全部消えたときに『変化なし』に見える経路をここで塞ぐ。
    if not report.sites:
        print("🚫 fetch 呼び出しを1件も読み取れませんでした。")
        return 1

    if args.resolve is not None:
        print(f"✅ 解消を受理しました: {ratchet.resolve(report, BASELINE, args.resolve)}")
        return 0
    if args.migrate is not None:
        print(f"✅ 移行を受理しました: {ratchet.migrate(report, BASELINE, args.migrate)}")
        return 0
    if args.redeclare is not None:
        print(f"✅ 差し替えを受理しました: {ratchet.redeclare(report, BASELINE, args.redeclare)}")
        return 0
    if args.update_baseline:
        print(f"✅ ベースラインを更新しました: {ratchet.update(report, BASELINE)}")
        return 0

    result = ratchet.check(report, load_baseline(BASELINE))
    print(result.to_text())
    return 0 if result.valid else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
