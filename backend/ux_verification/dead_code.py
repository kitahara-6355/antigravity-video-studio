"""死蔵コードの棚卸しとラチェット（P2 C-5）。

L1 の判定は「ストーリーが要求したものが在るか」を見る。裏返しの問い——
**在るのに誰からも呼ばれないものが、どれだけ積まれているか**——は誰も見ていない。

死蔵コードは緑のまま腐る。`review_router` は 21件のテストが通り、
カバレッジにも計上されているが、`routers/__init__.py` に載っておらず
`include_router` もされていないので、本番では 7 本すべてが 404 を返す。
**テストが通っていることは、そのコードが到達可能であることを意味しない。**
frontend も同じで、`data-testid` を持たない到達不能コンポーネントは
L1 の `unreachable` 判定にすら現れない。

そこで既にある2つの走査を裏側から使う:

- `api_contract.EndpointRegistry` — `include_router` されていないルーターの
  エンドポイント（呼べば 404）
- `executor._reachable_files` — `src/main.jsx` から import を辿って
  到達できないソースファイル（バンドルに入らない）

    python -m backend.ux_verification.dead_code
    python -m backend.ux_verification.dead_code --ratchet
    python -m backend.ux_verification.dead_code --update-baseline

判定は静的走査だけなのでサーバもブラウザも要らず、課金も発生しない。

## 何を「扱いを決めた」ことにするか

削除するか結線するかは製品判断で、この実行系の領分ではない。ここが引き受けるのは
**増やさないこと**——現状を項目ごとにベースラインへ固定し、新しい死蔵が
生まれたら CI で落とす。件数の合計ではなく項目ごとに突き合わせるのは、
1件が結線され別の1件が死蔵化しても合計が動かないため（`l1_ratchet` と同じ理由）。

## 判定の限界

- **WebSocket は見ていない。** 走査は `@router.get` 等の HTTP 動詞だけを拾う。
  `@router.websocket` のルートは死蔵判定の対象外
- **動的な `include_router` は追えない。** ループや条件分岐で登録するコードを
  書くと、登録済みでも未登録と出る
- **到達可能性は相対 import だけで辿る。** エイリアス（`@/components/...`）を
  導入すると、到達しているのに死蔵と出る
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from .api_contract import EndpointRegistry
from .executor import _iter_source_files, _project_root, _reachable_files

BASELINE_DIR = Path(__file__).parent / "snapshots"


def baseline_path() -> Path:
    return BASELINE_DIR / "dead_code_baseline.json"


@dataclass(frozen=True)
class DeadEndpoint:
    """定義はあるがアプリに登録されていないエンドポイント。呼べば 404。"""

    method: str
    path: str
    file: str
    line: int
    module: str

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"

    def as_evidence(self) -> str:
        return f"{self.key}   {self.file}:{self.line}"


@dataclass(frozen=True)
class DeadComponent:
    """エントリから import を辿って到達できないソースファイル。"""

    file: str  # リポジトリ相対
    size_bytes: int = 0

    @property
    def key(self) -> str:
        return self.file

    def as_evidence(self) -> str:
        return f"{self.file}   {self.size_bytes:,} バイト"


@dataclass
class DeadCodeInventory:
    endpoints: list[DeadEndpoint] = field(default_factory=list)
    components: list[DeadComponent] = field(default_factory=list)
    endpoints_scanned: int = 0
    components_scanned: int = 0

    # 計測器が仕事をしなかったことを示す旗。ゼロ件と区別する。
    entry_missing: bool = False
    routers_missing: bool = False
    registration_unknown: bool = False

    @property
    def blind(self) -> list[str]:
        """走査が成立していない理由。空でなければ結果を信用してはいけない。"""
        reasons = []
        if self.routers_missing:
            reasons.append("ルーターディレクトリを走査できませんでした")
        if self.registration_unknown:
            reasons.append("アプリ定義が見つからず、登録状況を判定できませんでした")
        if self.entry_missing:
            reasons.append("frontend のエントリが見つかりませんでした")
        return reasons

    @property
    def total(self) -> int:
        return len(self.endpoints) + len(self.components)

    def keys(self) -> dict[str, list[str]]:
        return {
            "endpoints": sorted(e.key for e in self.endpoints),
            "components": sorted(c.key for c in self.components),
        }

    # --- 構築 ---------------------------------------------------------------

    @classmethod
    def collect(cls, routers_dir: Path, app_files: list[Path],
                frontend_src: Path, entry: Path,
                project_root: Path) -> DeadCodeInventory:
        inv = cls()
        inv._collect_endpoints(Path(routers_dir), [Path(p) for p in app_files])
        inv._collect_components(Path(frontend_src), Path(entry), Path(project_root))
        return inv

    @classmethod
    def for_repo(cls) -> DeadCodeInventory:
        root = _project_root()
        backend = root / "backend"
        app_files = [p for p in (backend / "main.py", backend / "api_versioning.py")
                     if p.exists()]
        src = root / "frontend" / "src"
        return cls.collect(
            routers_dir=backend / "routers", app_files=app_files,
            frontend_src=src, entry=src / "main.jsx", project_root=root,
        )

    def _collect_endpoints(self, routers_dir: Path, app_files: list[Path]) -> None:
        if not routers_dir.is_dir():
            self.routers_missing = True
            return

        registry = EndpointRegistry.scan(routers_dir, app_files=app_files or None)
        self.endpoints_scanned = len(registry.endpoints)

        if registry.registered_modules is None:
            # 登録状況が分からない状態で「全部未登録」と言えば全件が死蔵になる。
            self.registration_unknown = True
            return

        self.endpoints = sorted(
            (
                DeadEndpoint(method, path, site.file, site.line, site.module)
                for (method, path), site in registry.endpoints.items()
                if site.registered is False
            ),
            key=lambda e: e.key,
        )

    def _collect_components(self, src: Path, entry: Path, root: Path) -> None:
        sources = list(_iter_source_files(src))
        self.components_scanned = len(sources)

        if not entry.is_file():
            # エントリを見失うと全ファイルが到達不能になる。件数を出さない。
            self.entry_missing = True
            return

        reachable = _reachable_files(entry)
        self.components = sorted(
            (
                DeadComponent(_relative(path, root), path.stat().st_size)
                for path in sources
                if path.resolve() not in reachable
            ),
            key=lambda c: c.key,
        )


# --- ベースライン -------------------------------------------------------------


def write_baseline(inventory: DeadCodeInventory, path: Path) -> Path:
    """項目ごとに書き出す。タイムスタンプは入れない（差分が読めなくなる）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(inventory.keys(), f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def load_baseline(path: Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class DeadCodeViolation:
    kind: str  # "endpoint" | "component"
    key: str

    def __str__(self) -> str:
        label = "未登録エンドポイント" if self.kind == "endpoint" else "到達不能ファイル"
        return f"[新規] {label}: {self.key}"


@dataclass
class DeadCodeRatchetResult:
    valid: bool
    violations: list[DeadCodeViolation] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    baseline_missing: bool = False
    blind: list[str] = field(default_factory=list)
    before: int = 0
    after: int = 0

    def to_text(self) -> str:
        if self.blind:
            lines = ["🚫 死蔵コードを走査できませんでした:"]
            lines += [f"    {r}" for r in self.blind]
            lines.append(
                "\n  走査できなかったことを 0 件として通すと、計測器を壊すだけで"
                "ラチェットを黙らせられます。"
            )
            return "\n".join(lines)
        if self.baseline_missing:
            return (
                "🚫 ベースラインがありません。--update-baseline で作成してください"
                f"（現在 {self.after} 件）。\n"
                "  ベースラインが無い状態を緑にすると、ファイルを消すだけで"
                "ラチェットを無効化できてしまうため失敗として扱います。"
            )
        head = f"死蔵コードラチェット: {self.before} → {self.after} 件"
        if self.valid:
            if self.removed:
                head += f"（解消 {len(self.removed)} 件）"
            return f"✅ {head}"
        lines = [f"🚫 {head}", f"  {len(self.violations)} 件の新規死蔵:"]
        lines += [f"    {v}" for v in self.violations]
        lines.append(
            "\n  誰からも呼ばれないコードが増えています。結線するか消すかを"
            "決めてください。意図して残すなら --update-baseline で締め直します。"
        )
        return "\n".join(lines)


class DeadCodeRatchet:
    """死蔵コードが増えていないことを、項目ごとに検証する。"""

    def check(self, inventory: DeadCodeInventory,
              baseline: dict | None) -> DeadCodeRatchetResult:
        if inventory.blind:
            return DeadCodeRatchetResult(
                valid=False, blind=inventory.blind, after=inventory.total
            )

        now = inventory.keys()
        if baseline is None:
            return DeadCodeRatchetResult(
                valid=False, baseline_missing=True, after=inventory.total
            )

        violations: list[DeadCodeViolation] = []
        removed: list[str] = []
        before = 0

        for kind, field_name in (("endpoint", "endpoints"), ("component", "components")):
            was = set(baseline.get(field_name, []))
            is_now = set(now[field_name])
            before += len(was)
            violations += [DeadCodeViolation(kind, k) for k in sorted(is_now - was)]
            removed += sorted(was - is_now)

        return DeadCodeRatchetResult(
            valid=not violations,
            violations=violations,
            removed=removed,
            before=before,
            after=inventory.total,
        )

    def update(self, inventory: DeadCodeInventory, path: Path) -> Path:
        """現在値で締め直す。増えたまま緩めれば、増えたことが無かったことになる。"""
        if inventory.blind:
            raise ValueError(
                "走査が成立していないためベースラインを更新できません:\n"
                + "\n".join(f"  {r}" for r in inventory.blind)
            )
        baseline = load_baseline(path)
        if baseline is not None:
            result = self.check(inventory, baseline)
            if not result.valid:
                raise ValueError(
                    "死蔵が増えているためベースラインを更新できません:\n"
                    + "\n".join(f"  {v}" for v in result.violations)
                )
        return write_baseline(inventory, path)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# --- CLI ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="死蔵コード（未登録エンドポイント・到達不能ファイル）を棚卸しする",
    )
    parser.add_argument("--ratchet", action="store_true",
                        help="ベースラインと突き合わせ、増えていれば異常終了する")
    parser.add_argument("--update-baseline", action="store_true",
                        help="現在値でベースラインを締め直す")
    parser.add_argument("--json", action="store_true", help="項目だけを JSON で出す")
    args = parser.parse_args(argv)

    inventory = DeadCodeInventory.for_repo()

    if args.json:
        print(json.dumps(inventory.keys(), ensure_ascii=False, indent=2))
        return 0

    if args.update_baseline:
        try:
            written = DeadCodeRatchet().update(inventory, baseline_path())
        except ValueError as exc:
            print(f"🚫 {exc}")
            return 1
        print(f"✅ ベースラインを更新しました: {written}（{inventory.total} 件）")
        return 0

    if args.ratchet:
        result = DeadCodeRatchet().check(inventory, load_baseline(baseline_path()))
        print(result.to_text())
        return 0 if result.valid else 1

    print("死蔵コードの棚卸し — method=static_route_scan + static_import_scan")
    print(f"  走査: エンドポイント {inventory.endpoints_scanned} 件"
          f" / frontend ソース {inventory.components_scanned} ファイル")
    for reason in inventory.blind:
        print(f"  ⚠️ {reason}")

    print(f"\n  未登録エンドポイント（呼べば 404）: {len(inventory.endpoints)} 件")
    for endpoint in inventory.endpoints:
        print(f"    {endpoint.as_evidence()}")

    print(f"\n  到達不能ファイル（バンドルに入らない）: {len(inventory.components)} 件")
    for component in inventory.components:
        print(f"    {component.as_evidence()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
