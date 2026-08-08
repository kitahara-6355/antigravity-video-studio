"""UI と API の接続（呼び出し先の実在）の実行系。

`ui_api_connection` 軸の値 85 は 2026-05-18 の目視のままで
`confidence=not_measured`。だが「フロントが叩く URL に対応するハンドラが
backend に宣言されているか」は、**サーバもブラウザも起動せず静的に判定できる**。

    python -m backend.ux_verification.ui_api --gate

## 判定方法とその限界

frontend/src のエントリから到達できるソースだけを走査し、`fetch(...)` の
**第1引数（URL）と第2引数の `method`** を読む。読んだ呼び出し先を
`api_contract.EndpointRegistry`（ルーター定義の AST 走査）と突き合わせる。

**確かめるのは『そのパスとメソッドのハンドラが宣言され、アプリに登録されている』
ことだけ。** 実行時に実際に呼ばれるか、レスポンスをフロントが正しく使えているか、
ベース URL が本番で正しいか、リクエスト/レスポンスのスキーマが噛み合うかは
**確かめない**。「突き合わせが取れた＝繋がっている」は偽である。

## 自然言語ではなく URL 式を閉じる

P3 の C-3 で学んだとおり、書き方の揺れを「検出」しようとすると必ず負ける。
ここでも **解決できる URL の形をテンプレートで閉じ、外れたものは
`unresolved_url` として必ず FAIL に落とす**（fail-closed）。閉じた形は3つだけ:

1. 文字列リテラル（`'http://localhost:8000/api/x'` / `'/api/x'`）
2. テンプレートリテラルで、`${...}` が
   (a) **そのファイルで1度しか代入されていない**名前に解決できる、または
   (b) パスの1セグメント全体を占める（`/tasks/${taskId}` → パスパラメータ）
3. 上記の後ろに付いたクエリ文字列（`?` 以降は判定に使わない）

名前を辿るのは「1度しか代入されていない」ときだけ。2度以上代入される名前は
`fetch` の時点でどちらの値かが決まらないので解決しない。文字列連結・
関数呼び出し・未知の識別子もすべて `unresolved_url`。
**「読めなかった」を「問題なし」に混ぜない。**

メソッドも同じ。第2引数が無ければ GET（fetch の既定）、`method:` が
文字列リテラルならその値、リテラルでない・スプレッドで隠れているなら
`unresolved_method` で FAIL にする。
"""
from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from backend.ux_verification.api_contract import (
    EndpointRegistry,
    _callee_name,
    _normalise,
    _router_aliases,
)
from backend.ux_verification.executor import (
    _display_path,
    _iter_source_files,
    _project_root,
    _reachable_files,
)

METHOD = "static_fetch_scan"

# パスパラメータの置き場所。フロントの `${taskId}` と
# ルーターの `{task_id}` を**構造だけ**で突き合わせる。名前は一致を要求しない
# （フロントの命名規約と FastAPI の命名規約は別物で、名前で落とすと
# 実在するのに FAIL になる）。ただし**プレースホルダはプレースホルダとしか
# 一致しない** — リテラルのセグメントに化けさせない。
_PARAM = "{}"

# backend とみなすホスト。これ以外の絶対 URL は外部サービスへの呼び出しで、
# このゲートの対象外だと**明示的に**分かるように別カテゴリにする。
# SKIP にはしない（確かめていないものを緑にしない）。
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")

_FETCH_RE = re.compile(r"(?<![\w.$])fetch\s*\(")
# `const API_BASE = "http://localhost:8000";` と
# `const url = ` + backtick + `${API_BASE}/api/segments?t=${t}` + backtick + `;`。
# **ファイル内で1度しか代入されていない名前だけ**を辞書に入れる。
# 2度以上代入される名前は、どちらの値で叩くのか静的に決まらないので解決しない。
_ASSIGN_RE = re.compile(
    r"(?<![\w.$])(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?P<value>'[^'\n]*'|\"[^\"\n]*\"|`[^`]*`)",
)
# 上の形以外での再代入。1つでもあればその名前は解決しない（fail-closed）。
_REBIND_RE = re.compile(r"(?<![\w.$])(?P<name>[A-Za-z_$][\w$]*)\s*=(?!=)")
# `${...}` を1段解いた先がさらに名前を含むことがあるので、有限回で打ち切る。
_MAX_DEPTH = 4
_METHOD_RE = re.compile(
    r"(?<![\w.$])method\s*:\s*(?P<quote>['\"`])(?P<value>[A-Za-z]+)(?P=quote)"
)
# `method:` があるのにリテラルで書かれていない形。`...opts` も同じ扱い。
_METHOD_KEY_RE = re.compile(r"(?<![\w.$])method\s*:")
_SPREAD_RE = re.compile(r"\.\.\.")


class Verdict(Enum):
    """突き合わせの結果。**PASS は `MATCHED` だけ。**"""

    MATCHED = "matched"
    NOT_DECLARED = "not_declared"
    METHOD_MISMATCH = "method_mismatch"
    NOT_REGISTERED = "not_registered"
    UNRESOLVED_URL = "unresolved_url"
    UNRESOLVED_METHOD = "unresolved_method"
    EXTERNAL_HOST = "external_host"


# 各判定が「何を確かめ、何を確かめないか」。CLAIM_SEMANTICS と同じ形で
# 機械可読に持つ。ここに書いていない Verdict を作れないことはテストで縛る。
VERDICT_SEMANTICS: dict[Verdict, dict[str, str]] = {
    Verdict.MATCHED: {
        "確かめること": "そのパスとメソッドのハンドラがルーターに宣言され、"
                        "include_router でアプリに登録されている",
        "確かめないこと": "実行時にこの呼び出しが実際に発火するか / "
                          "レスポンスをフロントが正しく使えているか / "
                          "ベース URL が本番環境で正しいか / "
                          "リクエスト・レスポンスのスキーマが噛み合うか",
        "PASS": "yes",
    },
    Verdict.NOT_DECLARED: {
        "確かめること": "そのパスのハンドラがどのルーターにも宣言されていない",
        "確かめないこと": "リバースプロキシや静的配信で別のサーバが応えている可能性",
        "PASS": "no",
    },
    Verdict.METHOD_MISMATCH: {
        "確かめること": "パスは宣言されているが、そのメソッドでは宣言されていない",
        "確かめないこと": "同上",
        "PASS": "no",
    },
    Verdict.NOT_REGISTERED: {
        "確かめること": "宣言はあるが include_router されておらず、呼べば 404 になる",
        "確かめないこと": "動的に登録される経路（実行時にしか分からない）",
        "PASS": "no",
    },
    Verdict.UNRESOLVED_URL: {
        "確かめること": "URL が閉じた文法で解決できず、呼び出し先を静的に特定できない",
        "確かめないこと": "その呼び出しが実際にどこを叩くか（解決できていない）",
        "PASS": "no",
    },
    Verdict.UNRESOLVED_METHOD: {
        "確かめること": "HTTP メソッドが静的に読めず、どの宣言と突き合わせるか決まらない",
        "確かめないこと": "同上",
        "PASS": "no",
    },
    Verdict.EXTERNAL_HOST: {
        "確かめること": "backend 以外のホストを叩いており、このゲートの対象外である",
        "確かめないこと": "その外部サービスが実在するか・応答するか",
        "PASS": "no",
    },
}


@dataclass(frozen=True)
class FetchSite:
    """フロントの `fetch` 呼び出し1箇所。"""

    file: str
    line: int
    raw_url: str
    # 解決できた backend 相対パス。解決できなければ None。
    path: str | None
    method: str | None
    verdict: Verdict
    reason: str = ""
    # 突き合わった宣言の場所（PASS の証拠）。
    declared_at: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict is Verdict.MATCHED

    def as_evidence(self) -> str:
        return f"{METHOD}: {self.file}:{self.line} {self.method or '?'} " \
               f"{self.path or self.raw_url}"


@dataclass
class UiApiReport:
    sites: list[FetchSite] = field(default_factory=list)
    files_scanned: int = 0
    endpoints_scanned: int = 0
    # エントリから到達できないファイルにある fetch。判定の対象にしていないが、
    # **黙って落とさない** — ここが増えるのは「ファイルを到達不能にすれば
    # ゲートを避けられる」経路なので、数を出して見えるようにする。
    unreachable: list[str] = field(default_factory=list)

    @property
    def mismatched(self) -> list[FetchSite]:
        """突き合わなかったもの。**ゼロになることが P4 C-2 の終了条件。**"""
        return [s for s in self.sites if not s.passed]

    def by_verdict(self) -> dict[Verdict, int]:
        counts: dict[Verdict, int] = {}
        for site in self.sites:
            counts[site.verdict] = counts.get(site.verdict, 0) + 1
        return counts


# --- URL の解決 ---------------------------------------------------------------


def _assignments(text: str) -> dict[str, str]:
    """ファイル内で**1度しか代入されていない**名前だけを拾う。

    2度以上代入される名前は、`fetch` の時点でどちらの値かが静的に決まらない。
    数えるのは宣言だけでなく素の再代入（`url = ...`）も含める——
    「宣言が1つだから確定」は、あとから代入を足されたときに黙って破れる。
    """
    values: dict[str, str] = {}
    counts: dict[str, int] = {}
    for m in _ASSIGN_RE.finditer(text):
        name = m.group("name")
        counts[name] = counts.get(name, 0) + 1
        values[name] = m.group("value")
    for m in _REBIND_RE.finditer(text):
        name = m.group("name")
        if name in counts and not _is_declaration_at(text, m.start()):
            counts[name] += 1
    return {n: v for n, v in values.items() if counts.get(n) == 1}


def _is_declaration_at(text: str, name_start: int) -> bool:
    """その代入が `const/let/var` の宣言かどうか。"""
    head = text[max(0, name_start - 12):name_start]
    return bool(re.search(r"(?:const|let|var)\s+$", head))


def _match_args(text: str, open_index: int) -> str | None:
    """`fetch(` の `(` から対応する `)` までの中身を返す。"""
    depth = 0
    quote: str | None = None
    escaped = False
    for i in range(open_index, len(text)):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in "'\"`":
            quote = ch
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return text[open_index + 1:i]
    return None


def _split_top_level(args: str) -> list[str]:
    """トップレベルのカンマだけで分ける。"""
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    escaped = False
    current: list[str] = []
    for ch in args:
        if quote:
            current.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in "'\"`":
            quote = ch
            current.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts]


def _resolve_url(expr: str, env: dict[str, str],
                 depth: int = 0) -> tuple[str | None, str]:
    """URL 式を閉じた文法で解決する。解決できなければ (None, 理由)。

    返すのは**クエリ文字列を落としたパス**。`?` 以降は判定対象にしていない
    （VERDICT_SEMANTICS の「確かめないこと」）ので、そこに式があっても
    解決できない理由にはしない。
    """
    expr = expr.strip()
    if not expr:
        return None, "引数が空"
    if depth > _MAX_DEPTH:
        return None, "名前の解決が深すぎる"

    if len(expr) >= 2 and expr[0] == expr[-1] and expr[0] in "'\"":
        if expr[0] in expr[1:-1]:
            return None, "文字列リテラルの外に式がある"
        return _cut_query(expr[1:-1]), ""

    if not (expr.startswith("`") and expr.endswith("`")):
        # 単なる名前なら、1度しか代入されていないものに限って辿る。
        if re.fullmatch(r"[A-Za-z_$][\w$]*", expr):
            bound = env.get(expr)
            if bound is None:
                return None, f"1度しか代入されていない名前ではない（{_short(expr)}）"
            return _resolve_url(bound, env, depth + 1)
        return None, f"閉じた文法に無い形（{_short(expr)}）"
    body = expr[1:-1]
    if "`" in body:
        return None, "テンプレートリテラルの外に式がある"

    out: list[str] = []
    i = 0
    while i < len(body):
        if body.startswith("${", i):
            end = _closing_brace(body, i + 1)
            if end is None:
                return None, "${ が閉じていない"
            inner = body[i + 2:end].strip()
            bound = env.get(inner)
            if bound is not None:
                nested, why = _resolve_url(bound, env, depth + 1)
                if nested is None:
                    return None, why
                out.append(nested)
            else:
                # セグメント全体を占める `${...}` だけをパスパラメータと読む。
                # 途中に混ざる式（`/x${suffix}/y`）は解決しない。
                after = body[end + 1:]
                if not "".join(out).endswith("/"):
                    return None, f"パスの途中に式がある（${{{_short(inner)}}}）"
                if after and not after.startswith(("/", "?", "#")):
                    return None, f"セグメントの途中に式がある（${{{_short(inner)}}}）"
                out.append(_PARAM)
            i = end + 1
            continue
        if body[i] in "?#":
            break  # ここから先はクエリ。判定対象にしていない
        out.append(body[i])
        i += 1
    return "".join(out), ""


def _cut_query(url: str) -> str:
    return url.split("?", 1)[0].split("#", 1)[0]


def _closing_brace(text: str, open_index: int) -> int | None:
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _resolve_method(arg: str | None) -> tuple[str | None, str]:
    """第2引数から HTTP メソッドを読む。読めなければ (None, 理由)。"""
    if arg is None or not arg.strip():
        return "GET", ""  # fetch の既定
    if _SPREAD_RE.search(arg):
        return None, "スプレッドに隠れてメソッドを静的に読めない"
    hit = _METHOD_RE.search(arg)
    if hit:
        return hit.group("value").upper(), ""
    if _METHOD_KEY_RE.search(arg):
        return None, "method がリテラルで書かれていない"
    return "GET", ""


def _strip_origin(url: str) -> tuple[str | None, str]:
    """絶対 URL からホストを落とす。外部ホストなら (None, 理由)。"""
    if not url.startswith(("http://", "https://")):
        return url, ""
    rest = url.split("://", 1)[1]
    host, _, tail = rest.partition("/")
    hostname = host.split(":", 1)[0]
    if hostname not in _LOCAL_HOSTS:
        return None, f"backend 以外のホスト（{host}）"
    return "/" + tail, ""


def _short(text: str, limit: int = 40) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _param_shape(path: str) -> str:
    """`/a/{task_id}` も `/a/{}` も同じ形にする。**構造だけで突き合わせる。**"""
    return re.sub(r"\{[^/]*\}", _PARAM, path)


# --- バージョン付きマウント ---------------------------------------------------


def _version_mounts(app_file: Path,
                    routers_dir: Path | None = None) -> tuple[str, set[str]]:
    """`APIRouter(prefix="/api/v1")` 配下に再マウントされたルーターを読む。

    EndpointRegistry はルーター自身の prefix しか見ないので、
    `/api/v1/themes/recommend` は「宣言が無い」に見える。実際には在る。

    **プレフィクス付きの APIRouter がこのファイルに1つのときだけ**解決する。
    2つ以上（v1 と v2 など）あればどちらに載ったか静的に決まらないので
    何も返さない——推測して緑にするより、宣言が無いものとして FAIL に落とす。
    """
    if not app_file.exists():
        return "", set()
    try:
        tree = ast.parse(app_file.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return "", set()

    prefixes = {
        kw.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node.func) == "APIRouter"
        for kw in node.keywords
        if kw.arg == "prefix" and isinstance(kw.value, ast.Constant)
        and isinstance(kw.value.value, str) and kw.value.value
    }
    if len(prefixes) != 1:
        return "", set()
    prefix = _normalise(prefixes.pop())

    # `from routers import quality_router` の quality_router がどのモジュールを
    # 指すかは routers/__init__.py にしか書いていない。そこを読まずに別名を
    # モジュール名とみなすと、載せていないルーターを載っていることにしてしまう。
    alias_to_module = {
        alias: module
        for module, alias in _router_aliases(
            (routers_dir or app_file.parent / "routers") / "__init__.py").items()
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module.split(".")[-1]
            for alias in node.names:
                if alias.name == "router" and alias.asname:
                    alias_to_module[alias.asname] = module

    mounted = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if _callee_name(node.func) != "include_router":
            continue
        # `app.include_router(...)` は素のマウント。ここで見たいのは
        # プレフィクス付きルータへの再マウントのほう。
        if isinstance(node.func, ast.Attribute) and \
                isinstance(node.func.value, ast.Name) and \
                node.func.value.id == "app":
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Name):
            mounted.add(alias_to_module.get(arg.id, arg.id))
    return prefix, mounted


# --- 走査 ---------------------------------------------------------------------


class UiApiExecutor:
    """frontend の fetch 呼び出しと、ルーター定義の宣言を突き合わせる。"""

    def __init__(self, frontend_src: Path, registry: EndpointRegistry,
                 entry: Path | None = None,
                 version_prefix: str = "", version_modules: set[str] | None = None):
        self.frontend_src = Path(frontend_src)
        self.registry = registry
        if entry is None:
            candidate = self.frontend_src / "main.jsx"
            entry = candidate if candidate.exists() else None
        self.entry = entry
        self.version_prefix = version_prefix
        self.version_modules = version_modules or set()

    @classmethod
    def for_repo(cls) -> UiApiExecutor:
        root = _project_root()
        prefix, modules = _version_mounts(root / "backend" / "api_versioning.py",
                                  root / "backend" / "routers")
        return cls(frontend_src=root / "frontend" / "src",
                   registry=EndpointRegistry.for_repo(),
                   version_prefix=prefix, version_modules=modules)

    def run(self) -> UiApiReport:
        report = UiApiReport(endpoints_scanned=len(self.registry.endpoints))
        reachable = _reachable_files(self.entry) if self.entry else None
        shapes = self._shape_index()

        for path in _iter_source_files(self.frontend_src):
            text = path.read_text(encoding="utf-8", errors="replace")
            rel = _display_path(path, self.frontend_src)
            if reachable is not None and path.resolve() not in reachable:
                for hit in _FETCH_RE.finditer(text):
                    report.unreachable.append(
                        f"{rel}:{text.count(chr(10), 0, hit.start()) + 1}")
                continue
            report.files_scanned += 1
            for site in self._sites_in(text, _assignments(text), rel, shapes):
                report.sites.append(site)
        return report

    def _shape_index(self) -> dict[tuple[str, str], list]:
        """(メソッド, 形) → 宣言。パスパラメータ名の違いを吸収する。"""
        index: dict[tuple[str, str], list] = {}
        for (method, path), endpoint in self.registry.endpoints.items():
            index.setdefault((method, _param_shape(path)), []).append(endpoint)
        return index

    def _under_version(self, shape: str, method: str,
                       shapes: dict) -> tuple[list, str]:
        """`/api/v1/...` を、再マウント元のルーターの宣言として解く。

        **そのプレフィクスに実際に再マウントされたモジュールの宣言だけ**を採る。
        prefix を剥がして当たりさえすれば通す、にすると、v1 に載せていない
        ルーターまで v1 で呼べることにしてしまう。
        """
        prefix = self.version_prefix
        if not prefix or not shape.startswith(prefix + "/"):
            return [], shape
        bare = shape[len(prefix):]
        hits = [e for e in shapes.get((method, bare), [])
                if e.module in self.version_modules]
        return hits, bare if hits else shape

    def _sites_in(self, text: str, constants: dict[str, str], rel: str,
                  shapes: dict) -> list[FetchSite]:
        found: list[FetchSite] = []
        for hit in _FETCH_RE.finditer(text):
            open_index = hit.end() - 1
            args = _match_args(text, open_index)
            line = text.count("\n", 0, hit.start()) + 1
            if args is None:
                found.append(FetchSite(rel, line, _short(text[hit.start():hit.start() + 60]),
                                       None, None, Verdict.UNRESOLVED_URL,
                                       "引数の括弧が閉じていない"))
                continue
            parts = _split_top_level(args)
            found.append(self._judge(parts, constants, rel, line, shapes))
        return found

    def _judge(self, parts: list[str], constants: dict[str, str], rel: str,
               line: int, shapes: dict) -> FetchSite:
        raw = _short(parts[0]) if parts else ""
        url, why = _resolve_url(parts[0] if parts else "", constants)
        if url is None:
            return FetchSite(rel, line, raw, None, None, Verdict.UNRESOLVED_URL, why)

        stripped, why = _strip_origin(url)
        if stripped is None:
            return FetchSite(rel, line, raw, None, None, Verdict.EXTERNAL_HOST, why)
        path = _normalise(stripped.split("?", 1)[0].split("#", 1)[0])

        method, why = _resolve_method(parts[1] if len(parts) > 1 else None)
        if method is None:
            return FetchSite(rel, line, raw, path, None,
                             Verdict.UNRESOLVED_METHOD, why)

        shape = _param_shape(path)
        hits = shapes.get((method, shape))
        if not hits:
            hits, shape = self._under_version(shape, method, shapes)
        if not hits:
            other = sorted({m for (m, s) in shapes if s == shape})
            if other:
                return FetchSite(rel, line, raw, path, method,
                                 Verdict.METHOD_MISMATCH,
                                 f"宣言されているのは {'/'.join(other)} のみ")
            return FetchSite(rel, line, raw, path, method, Verdict.NOT_DECLARED,
                             "どのルーターにも宣言が無い")

        registered = [e for e in hits if e.registered is not False]
        if not registered:
            return FetchSite(rel, line, raw, path, method, Verdict.NOT_REGISTERED,
                             f"{hits[0].module} が include_router されていない",
                             hits[0].as_evidence())
        return FetchSite(rel, line, raw, path, method, Verdict.MATCHED, "",
                         registered[0].as_evidence())


# --- CLI ---------------------------------------------------------------------


def _format(report: UiApiReport) -> str:
    headline = (f"UI と API の接続 — fetch 呼び出し {len(report.sites)} 件 / "
                f"frontend {report.files_scanned} ファイル / "
                f"宣言済みエンドポイント {report.endpoints_scanned} 件")
    lines = [headline, ""]
    counts = report.by_verdict()
    for verdict in Verdict:
        if verdict in counts:
            mark = "  " if verdict is Verdict.MATCHED else "⛔"
            lines.append(f"  {mark} {verdict.value:<18} {counts[verdict]:>3} 件")
    lines.append("")

    if report.unreachable:
        lines.append(
            f"  到達不能なファイルにある fetch: {len(report.unreachable)} 件（判定していない）")
        for site in report.unreachable:
            lines.append(f"    {site}")
        lines.append("")

    bad = report.mismatched
    lines.append(f"  突き合わない呼び出し: {len(bad)} 件")
    if not bad:
        lines.append("    なし。すべての呼び出し先が、宣言され登録されたハンドラに届いている。")
    for site in bad:
        lines.append(f"    {site.file}:{site.line}  {site.verdict.value}")
        lines.append(f"      {site.method or '?'} {site.path or site.raw_url}"
                     f"{'  — ' + site.reason if site.reason else ''}")
    return "\n".join(lines)


def _format_semantics() -> str:
    lines = ["判定ごとに『確かめること／確かめないこと』", ""]
    for verdict, meaning in VERDICT_SEMANTICS.items():
        lines.append(f"  {verdict.value}  （PASS: {meaning['PASS']}）")
        lines.append(f"    確かめる  : {meaning['確かめること']}")
        lines.append(f"    確かめない: {meaning['確かめないこと']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UI と API の接続を静的に突き合わせる")
    parser.add_argument("--gate", action="store_true",
                        help="突き合わない呼び出しが1件でもあれば exit 1")
    parser.add_argument("--semantics", action="store_true",
                        help="判定ごとの『確かめること／確かめないこと』を出す")
    args = parser.parse_args(argv)

    if args.semantics:
        print(_format_semantics())
        return 0

    report = UiApiExecutor.for_repo().run()
    print(_format(report))

    # 走査0件を緑にしない。ディレクトリを消せば通る、を塞ぐ。
    if not report.sites:
        print("\n⛔ fetch 呼び出しを1件も読み取れませんでした。走査対象を確認してください。")
        return 1
    if not report.endpoints_scanned:
        print("\n⛔ エンドポイントの宣言を1件も読み取れませんでした。")
        return 1

    if args.gate and report.mismatched:
        print(f"\n⛔ 突き合わない呼び出しが {len(report.mismatched)} 件あります。")
        return 1
    if args.gate:
        print(f"\n✅ {len(report.sites)} 件すべての呼び出し先が宣言と突き合っています。")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
