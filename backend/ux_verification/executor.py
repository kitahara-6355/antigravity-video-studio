"""L1（DOM存在）検証項目の実行系。

UX 検証項目は 1,045件あるが、判定を出す仕組みが無かったため大半が SKIP のまま
放置されていた。ここでは第1層（`test_method: dom_exists`）だけを対象に、
**コマンド1つで全項目に PASS/FAIL を付けきる**ことを引き受ける。

    python -m backend.ux_verification.executor --persona owner

## 判定方法とその限界

frontend のソースを静的に走査し、ストーリーが要求する `testid` が
`data-testid` として書かれているかを見る。**ブラウザもサーバも起動しない**ので
無料で、CI でそのまま回り、実行のたびに同じ答えを返す。

代わりに「実行時に本当に描画されるか」は保証しない。書いてあるが条件分岐で
一度も描画されない要素は PASS になりうる。この限界を隠さないため、
すべての結果の evidence に `static_source_scan` と刻む。

偽 PASS を減らすための歯止めを1つだけ入れてある: アプリのエントリ
（`src/main.jsx`）から import を辿って到達できないファイルの `data-testid` は
PASS にせず `unreachable` で FAIL にする。マウントされないコンポーネントに
書かれた testid は、UX を何も保証しないため。

## SKIP を出さない理由

SKIP は「判定していない」、FAIL は「判定した結果、保証されていない」。
`dom_exists` と宣言しながら照合先の `testid` を持たない項目は、
照合するまでもなく UX が保証されていないので FAIL にする。
SKIP に逃がすと、実行率だけが上がって充足率が動かない状態が固定される。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .snapshot import UXVerificationSnapshot, VerificationItem

METHOD = "static_source_scan"
STORAGE_METHOD = "static_storage_scan"

# 走査対象の拡張子と、除外するディレクトリ
_SOURCE_SUFFIXES = (".jsx", ".js", ".tsx", ".ts")
_EXCLUDED_DIRS = {"node_modules", "dist", "build", "__pycache__", ".vite"}

# data-testid の書き方は4通りある。どれにも当てはまらない
# `data-testid={someVar}` は静的には値が決まらないので拾わない。
_TESTID_RE = re.compile(
    r"data-testid\s*=\s*(?:"
    r'"(?P<dq>[^"]*)"'
    r"|'(?P<sq>[^']*)'"
    r"|\{\s*`(?P<tpl>[^`]*)`\s*\}"
    r'|\{\s*"(?P<bdq>[^"]*)"\s*\}'
    r"|\{\s*'(?P<bsq>[^']*)'\s*\}"
    r")"
)

# localStorage / sessionStorage のキー。「履歴キーが存在する」は DOM の主張では
# ないので data-testid では測れない。読み書きしている実体を直接見る。
_STORAGE_RE = re.compile(
    r"""(?:local|session)Storage\.(?:get|set|remove)Item\s*\(\s*['"`]([^'"`]+)['"`]"""
)

# import 文と動的 import。相対指定のものだけを到達可能性の辺として使う。
_IMPORT_RE = re.compile(
    r"""(?:^|\s)(?:import\s[^'"]*from\s*|import\s*|export\s[^'"]*from\s*)"""
    r"""['"](?P<spec>[^'"]+)['"]"""
    r"""|(?:import|require)\s*\(\s*['"](?P<dyn>[^'"]+)['"]\s*\)""",
    re.MULTILINE,
)


def iter_l1_items(stories_dir: Path, prefix: str = "O"):
    """L1 の検証項目を (ux_id, item) で列挙する。**判定側と監査側で共有する。**

    以前は実行系と `claim_audit` が別々に列挙していた。実行系は `*.json` を
    ux_id の接頭辞で選び、監査は `o*.json` を ID の `-L1-` で選んでいたため、
    **監査の走査範囲が実行系より狭かった。** その隙間に置いた claim 無しの項目は
    実行系では PASS になるのに監査には現れず、3つのゲートすべてが緑のまま
    偽 PASS が通った（P2 で3回指摘された「走査範囲の外のポケット」と同型）。

    列挙をここ1箇所に集約する。どちらかだけを直しても、もう片方は追随する。
    """
    for story_path in sorted(Path(stories_dir).glob("*.json")):
        try:
            story = json.loads(story_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        ux_id = story.get("ux_id", "")
        if not ux_id.startswith(prefix):
            continue
        for item in story.get("verification_items", []):
            if item.get("layer") != 1:
                continue
            yield ux_id, item


class Verdict(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class TestIdSite:
    """testid が書かれている場所。PASS の証拠になる。"""

    testid: str
    file: str
    line: int
    kind: str  # "literal" | "prefix"
    reachable: bool | None = None  # None = エントリ未指定で判定していない

    def as_evidence(self) -> str:
        return f"{METHOD}: {self.file}:{self.line} data-testid={self.testid}"


@dataclass
class TestIdRegistry:
    """frontend ソースに書かれている data-testid の索引。"""

    # 名前が Test で始まるので、pytest がテストクラスと誤認しないようにする
    __test__ = False

    literals: dict[str, TestIdSite] = field(default_factory=dict)
    prefixes: dict[str, TestIdSite] = field(default_factory=dict)
    files_scanned: int = 0
    entry: Path | None = None

    # --- 構築 ---------------------------------------------------------------

    @classmethod
    def scan(cls, src_dir: Path, entry: Path | None = None) -> TestIdRegistry:
        src_dir = Path(src_dir)
        reachable_files = _reachable_files(entry) if entry else None

        reg = cls(entry=entry)
        for path in _iter_source_files(src_dir):
            reg.files_scanned += 1
            rel = _display_path(path, src_dir)
            is_reachable = (
                None if reachable_files is None else path.resolve() in reachable_files
            )
            for line_no, raw in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                for match in _TESTID_RE.finditer(raw):
                    cls._record(reg, match, rel, line_no, is_reachable)
        return reg

    @staticmethod
    def _record(reg, match, rel, line_no, is_reachable) -> None:
        template = match.group("tpl")
        if template is not None:
            if "${" in template:
                prefix = template.split("${", 1)[0]
                if prefix:
                    reg._add(
                        reg.prefixes, prefix,
                        TestIdSite(prefix, rel, line_no, "prefix", is_reachable),
                    )
                return
            value = template
        else:
            value = next(
                (match.group(g) for g in ("dq", "sq", "bdq", "bsq")
                 if match.group(g) is not None),
                None,
            )
        if value:
            reg._add(
                reg.literals, value,
                TestIdSite(value, rel, line_no, "literal", is_reachable),
            )

    @staticmethod
    def _add(bucket: dict[str, TestIdSite], key: str, site: TestIdSite) -> None:
        """同じ testid が複数箇所にあるときは、到達できる方を証拠に採る。"""
        existing = bucket.get(key)
        if existing is None or (existing.reachable is False and site.reachable):
            bucket[key] = site

    # --- 解決 ---------------------------------------------------------------

    def resolve(self, testid: str) -> TestIdSite | None:
        """ストーリーが要求する testid をレジストリに突き合わせる。

        末尾 `*` は「この接頭辞で始まる要素が繰り返し描画される」という意味。
        `*` を伴わない要求は、部分一致では充足しない。
        """
        if not testid:
            return None
        hits = list(self._candidates(testid))
        if not hits:
            return None
        return next((h for h in hits if h.reachable), hits[0])

    def _candidates(self, testid: str) -> Iterable[TestIdSite]:
        if testid.endswith("*"):
            stem = testid[:-1]
            for value, site in self.literals.items():
                if value.startswith(stem) and value != stem:
                    yield site
            for prefix, site in self.prefixes.items():
                # テンプレートが生む id は必ず prefix で始まる。要求を満たすのは
                # prefix 自身が stem で始まるときだけ。逆向き（stem が prefix で
                # 始まる）を許すと、`foo-${x}` という雑なテンプレート1つで
                # `foo-bar-*` も `foo-baz-*` も通ってしまう。
                if prefix.startswith(stem):
                    yield site
            return

        if testid in self.literals:
            yield self.literals[testid]
        for prefix, site in self.prefixes.items():
            if testid.startswith(prefix) and testid != prefix:
                yield site


@dataclass
class L1Result:
    """検証項目1件の判定。"""

    item_id: str
    ux_story: str
    story_scene: str
    description: str
    testid: str
    verdict: Verdict
    reason: str  # "found" | "not_found" | "no_testid" | "unreachable"
    evidence: str

    @property
    def passed(self) -> bool | None:
        if self.verdict is Verdict.PASS:
            return True
        if self.verdict is Verdict.FAIL:
            return False
        return None


@dataclass
class L1Report:
    persona: str
    results: list[L1Result] = field(default_factory=list)
    method: str = METHOD
    files_scanned: int = 0

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.verdict is Verdict.PASS)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.verdict is Verdict.FAIL)

    @property
    def skip_count(self) -> int:
        return sum(1 for r in self.results if r.verdict is Verdict.SKIP)

    @property
    def pass_rate(self) -> float:
        return round(self.pass_count / self.total * 100, 2) if self.total else 0.0

    def by_story(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in self.results:
            row = out.setdefault(r.ux_story, {"total": 0, "pass": 0, "fail": 0})
            row["total"] += 1
            if r.verdict is Verdict.PASS:
                row["pass"] += 1
            elif r.verdict is Verdict.FAIL:
                row["fail"] += 1
        return out

    def by_reason(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.results:
            out[r.reason] = out.get(r.reason, 0) + 1
        return out

    def to_snapshot(self, version: str) -> UXVerificationSnapshot:
        return UXVerificationSnapshot(
            version=version,
            items=[
                VerificationItem(
                    id=r.item_id,
                    ux_story=r.ux_story,
                    layer=1,
                    description=r.description,
                    story_scene=r.story_scene,
                    test_method="dom_exists",
                    passed=r.passed,
                    evidence=r.evidence,
                )
                for r in self.results
            ],
        )

    def to_dict(self) -> dict:
        return {
            "persona": self.persona,
            "layer": 1,
            "method": self.method,
            "files_scanned": self.files_scanned,
            "total": self.total,
            "pass": self.pass_count,
            "fail": self.fail_count,
            "skip": self.skip_count,
            "pass_rate": self.pass_rate,
            "by_story": self.by_story(),
            "by_reason": self.by_reason(),
            "results": [
                {
                    "id": r.item_id,
                    "ux_story": r.ux_story,
                    "story_scene": r.story_scene,
                    "testid": r.testid,
                    "verdict": r.verdict.value,
                    "reason": r.reason,
                    "evidence": r.evidence,
                }
                for r in self.results
            ],
        }


_PERSONA_PREFIX = {"owner": "O-", "admin": "A-"}


class L1Executor:
    """ストーリー定義と frontend ソースを突き合わせ、L1 を判定する。"""

    def __init__(self, stories_dir: Path, frontend_src: Path,
                 entry: Path | None = None, contract=None):
        self.stories_dir = Path(stories_dir)
        self.frontend_src = Path(frontend_src)
        if entry is None:
            candidate = self.frontend_src / "main.jsx"
            entry = candidate if candidate.exists() else None
        self.entry = entry
        # API 契約の判定器。L1 の項目のうち testid ではなく endpoint を
        # 宣言しているものはこちらに回す（P2）。None なら回さない。
        self.contract = contract
        self._storage_cache: dict | None = None

    @classmethod
    def for_repo(cls) -> L1Executor:
        """このリポジトリの実データを見る実行系。"""
        from .api_contract import ApiContractExecutor, EndpointRegistry

        root = _project_root()
        return cls(
            stories_dir=root / "backend" / "ux_verification" / "stories",
            frontend_src=root / "frontend" / "src",
            contract=ApiContractExecutor(EndpointRegistry.for_repo()),
        )

    def run(self, persona: str = "owner") -> L1Report:
        prefix = _PERSONA_PREFIX.get(persona.lower())
        if prefix is None:
            raise ValueError(
                f"未知のペルソナ: {persona}（owner / admin のいずれか）"
            )

        self._storage_cache = None
        registry = TestIdRegistry.scan(self.frontend_src, entry=self.entry)
        report = L1Report(persona=persona.lower(), files_scanned=registry.files_scanned)

        for ux_id, item in iter_l1_items(self.stories_dir, prefix):
            report.results.append(self._route(ux_id, item, registry))

        report.results.sort(key=lambda r: _item_sort_key(r.item_id))
        return report

    def _storage_keys(self) -> dict:
        """エントリから到達できるソースにある localStorage キーを集める。"""
        if self._storage_cache is None:
            reachable = _reachable_files(self.entry) if self.entry else None
            found: dict[str, tuple[str, int]] = {}
            for path in _iter_source_files(self.frontend_src):
                if reachable is not None and path.resolve() not in reachable:
                    continue  # マウントされない場所のキーは UX を保証しない
                rel = _display_path(path, self.frontend_src)
                for line_no, raw in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(),
                    start=1,
                ):
                    for match in _STORAGE_RE.finditer(raw):
                        found.setdefault(match.group(1), (rel, line_no))
            self._storage_cache = found
        return self._storage_cache

    def _judge_storage(self, ux_id: str, item: dict) -> L1Result:
        key = (item.get("storage_key") or "").strip()
        common = {
            "item_id": item.get("id", ""),
            "ux_story": ux_id,
            "story_scene": item.get("story_scene", ""),
            "description": item.get("description", ""),
            "testid": "",
        }
        hit = self._storage_keys().get(key)
        if hit is None:
            return L1Result(
                **common, verdict=Verdict.FAIL, reason="storage_key_not_found",
                evidence=(
                    f"{STORAGE_METHOD}: localStorage キー {key} の読み書きが"
                    "到達可能な frontend ソースのどこにも無い。"
                ),
            )
        return L1Result(
            **common, verdict=Verdict.PASS, reason="storage_key_found",
            evidence=f"{STORAGE_METHOD}: {hit[0]}:{hit[1]} localStorage キー {key}",
        )

    @staticmethod
    def _judge_unjudgeable(ux_id: str, item: dict) -> L1Result:
        """静的には判定できないと**結論した**主張。PASS には逃がさない。

        判定していないものを緑にするのが、P2 で3回潰した偽 PASS そのもの。
        """
        claim = (item.get("claim") or "").strip()
        return L1Result(
            item_id=item.get("id", ""), ux_story=ux_id,
            story_scene=item.get("story_scene", ""),
            description=item.get("description", ""), testid="",
            verdict=Verdict.FAIL, reason="unjudgeable",
            evidence=(
                f"{METHOD}: 主張の種類 {claim} は静的走査では判定できない。"
                "実行時の応答を見る層が要る（判定していないものを PASS にしない）。"
            ),
        )

    def _route(self, ux_id: str, item: dict, registry: TestIdRegistry) -> L1Result:
        """項目が宣言している照合先に応じて判定器を選ぶ。

        L1 は名目上すべて `dom_exists` だが、実際には 86件が API・データ契約の
        主張だった（`docs/ux_l1_triage_20260802.md`）。`test_method` は
        書き換えず、項目が持つ照合先（testid / endpoint）で振り分ける。
        """
        claim = (item.get("claim") or "").strip()
        if claim:
            # claim があれば**主張の種類**で振り分ける。宣言の有無で振り分けると、
            # 経路の主張なのに testid しか持たない項目が DOM 判定に流れ、
            # 要素の実在だけで PASS する（P2 で3回見落とした型）。
            from .claim_audit import UNJUDGEABLE_CLAIMS

            if claim in UNJUDGEABLE_CLAIMS:
                return self._judge_unjudgeable(ux_id, item)
            if claim == "storage_key":
                return self._judge_storage(ux_id, item)
            if claim != "dom_exists" and self.contract is not None:
                return _from_contract(self.contract.judge(ux_id, item))
            return self._judge(ux_id, item, registry)

        if not (item.get("testid") or "").strip() and (item.get("endpoint") or "").strip():
            if self.contract is None:
                return self._judge(ux_id, item, registry)
            return _from_contract(self.contract.judge(ux_id, item))
        return self._judge(ux_id, item, registry)

    @staticmethod
    def _judge(ux_id: str, item: dict, registry: TestIdRegistry) -> L1Result:
        testid = (item.get("testid") or "").strip()
        common = {
            "item_id": item.get("id", ""),
            "ux_story": ux_id,
            "story_scene": item.get("story_scene", ""),
            "description": item.get("description", ""),
            "testid": testid,
        }

        if not testid:
            return L1Result(
                **common, verdict=Verdict.FAIL, reason="no_testid",
                evidence=(
                    f"{METHOD}: 項目が dom_exists を宣言しているが testid を持たない。"
                    "照合先が無いため保証されていない。"
                ),
            )

        site = registry.resolve(testid)
        if site is None:
            return L1Result(
                **common, verdict=Verdict.FAIL, reason="not_found",
                evidence=(
                    f"{METHOD}: data-testid={testid} は frontend ソース"
                    f"{registry.files_scanned}ファイルのどこにも無い。"
                ),
            )

        if site.reachable is False:
            return L1Result(
                **common, verdict=Verdict.FAIL, reason="unreachable",
                evidence=(
                    f"{METHOD}: {site.file}:{site.line} に data-testid={testid} は"
                    "あるが、エントリから import を辿って到達できない"
                    "（マウントされないため UX を保証しない）。"
                ),
            )

        return L1Result(
            **common, verdict=Verdict.PASS, reason="found",
            evidence=site.as_evidence(),
        )


# --- ここから下はファイル走査のこまごました部分 -------------------------------


def _from_contract(result) -> L1Result:
    """API 契約の判定を L1 の結果に載せ替える。

    verdict と evidence はそのまま持ち越す。evidence には判定器側の
    `static_route_scan` が刻まれているので、どちらで測ったかは失われない。
    """
    return L1Result(
        item_id=result.item_id,
        ux_story=result.ux_story,
        story_scene=result.story_scene,
        description=result.description,
        testid=result.endpoint,
        verdict=Verdict[result.verdict.name],
        reason=result.reason,
        evidence=result.evidence,
    )


def _project_root() -> Path:
    """path_resolver に合わせる。import できない文脈でも動くよう退避路を持つ。"""
    try:
        from backend.path_resolver import project_root  # type: ignore

        return Path(project_root())
    except (ImportError, OSError, ValueError):
        return Path(__file__).resolve().parents[2]


def _iter_source_files(src_dir: Path) -> Iterable[Path]:
    if not src_dir.exists():
        return
    for path in sorted(src_dir.rglob("*")):
        if path.suffix not in _SOURCE_SUFFIXES or not path.is_file():
            continue
        if _EXCLUDED_DIRS & set(path.parts):
            continue
        yield path


def _display_path(path: Path, src_dir: Path) -> str:
    try:
        return path.relative_to(src_dir.parent).as_posix()
    except ValueError:
        return path.as_posix()


def _reachable_files(entry: Path) -> set:
    """エントリから相対 import を辿って到達できるファイルの集合。"""
    entry = Path(entry).resolve()
    if not entry.exists():
        return set()

    seen = {entry}
    queue = [entry]
    while queue:
        current = queue.pop()
        try:
            text = current.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _IMPORT_RE.finditer(text):
            spec = match.group("spec") or match.group("dyn")
            if not spec or not spec.startswith("."):
                continue  # 外部パッケージ
            target = _resolve_specifier(current.parent, spec)
            if target and target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def _resolve_specifier(base: Path, spec: str) -> Path | None:
    raw = (base / spec).resolve()
    if raw.is_file():
        return raw
    for suffix in _SOURCE_SUFFIXES:
        candidate = raw.with_name(raw.name + suffix)
        if candidate.is_file():
            return candidate
    for suffix in _SOURCE_SUFFIXES:
        candidate = raw / f"index{suffix}"
        if candidate.is_file():
            return candidate
    return None


def _item_sort_key(item_id: str):
    """O1-L1-02 を O1-L1-10 より前に置く。"""
    parts = re.findall(r"\d+", item_id)
    return (item_id.split("-")[0][:1], [int(p) for p in parts], item_id)


# --- CLI ---------------------------------------------------------------------


def _format_report(report: L1Report) -> str:
    methods = sorted({
        r.evidence.split(":", 1)[0] for r in report.results if ":" in r.evidence
    })
    lines = [
        f"UX 検証 L1 — persona={report.persona} 判定方法={' + '.join(methods) or report.method}",
        "  ※ いずれも静的走査。実行時に描画される / 200 を返すことは保証しない",
        f"  走査: frontend ソース {report.files_scanned} ファイル",
        (
            f"  判定: {report.total}件 / PASS {report.pass_count}"
            f" / FAIL {report.fail_count} / SKIP {report.skip_count}"
            f"（充足率 {report.pass_rate}%）"
        ),
        "",
        "  ストーリー別:",
    ]
    for ux_id, row in sorted(report.by_story().items(), key=lambda kv: _story_key(kv[0])):
        lines.append(
            f"    {ux_id:<5} {row['pass']:>3} PASS / {row['fail']:>3} FAIL"
            f"  (計 {row['total']})"
        )
    lines += ["", "  FAIL の理由:"]
    labels = {
        "no_testid": "testid が定義されていない",
        "not_found": "testid が frontend に存在しない",
        "unreachable": "存在するがエントリから到達できない",
        "found": "（PASS）",
    }
    for reason, count in sorted(report.by_reason().items(), key=lambda kv: -kv[1]):
        lines.append(f"    {count:>3}件  {reason:<12} {labels.get(reason, '')}")
    return "\n".join(lines)


def _story_key(ux_id: str):
    parts = re.findall(r"\d+", ux_id)
    return (ux_id[:1], int(parts[0]) if parts else 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="UX 検証項目の L1（DOM存在）を判定する",
    )
    parser.add_argument("--persona", default="owner", choices=["owner", "admin"])
    parser.add_argument("--json", dest="json_out", metavar="PATH",
                        help="判定結果を JSON で書き出す")
    parser.add_argument("--snapshot", metavar="VERSION",
                        help="スナップショットとして保存する（例 v9_l1_owner）")
    parser.add_argument("--fail-under", type=float, metavar="RATE",
                        help="充足率がこの値未満なら exit 1")
    parser.add_argument("--ratchet", action="store_true",
                        help="ベースラインと項目ごとに突き合わせ、退行があれば exit 1")
    parser.add_argument("--update-baseline", action="store_true",
                        help="ラチェットのベースラインを現在値で締め直す")
    parser.add_argument("--tighten", metavar="理由",
                        help="判定を厳しくしたことによる PASS の減少だけを"
                             "受け入れて締め直す。理由はベースラインに残る")
    args = parser.parse_args(argv)

    report = L1Executor.for_repo().run(persona=args.persona)
    print(_format_report(report))

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"\n  JSON: {out}")

    if args.snapshot:
        from .snapshot import SnapshotStore

        path = SnapshotStore().save(report.to_snapshot(version=args.snapshot))
        print(f"  スナップショット: {path}")

    if args.ratchet or args.update_baseline or args.tighten:
        from .l1_ratchet import L1Ratchet, baseline_path, load_baseline

        path = baseline_path(report.persona)
        if args.update_baseline or args.tighten:
            try:
                if args.tighten:
                    L1Ratchet().tighten(report, path, args.tighten)
                else:
                    L1Ratchet().update(report, path)
            except ValueError as exc:
                print(f"\n{exc}", file=sys.stderr)
                return 1
            print(f"\nベースラインを更新しました: {path}")
        else:
            result = L1Ratchet().check(report, load_baseline(path))
            print(f"\n{result.to_text()}")
            # ベースラインが無いこと自体を失敗にする。緑にしてしまうと、
            # ファイルを消すだけでラチェットを無効化できてしまう。
            if result.baseline_missing or not result.valid:
                return 1

    if args.fail_under is not None and report.pass_rate < args.fail_under:
        print(f"\n充足率 {report.pass_rate}% < {args.fail_under}%", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
