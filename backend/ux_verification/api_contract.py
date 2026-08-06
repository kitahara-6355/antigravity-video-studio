"""API 契約（エンドポイント実在）の実行系。

Phase 1 で L1 の 122項目を判定した結果、**86項目は照合先の testid を持たず、
その全部が DOM ではなく API・データ契約の主張**だと分かった
（`docs/ux_l1_triage_20260802.md`）。「SmartCut初期化APIが正常応答を返す」
「statusフィールドが存在する」を DOM 存在確認で測ることはできない。
形だけ `data-testid` を足して PASS にすれば偽 PASS が構造的に成立する。

そこで判定手段の側を足す。FastAPI のルーター定義を静的に走査し、
ストーリーが宣言したエンドポイントが**実在し、かつアプリに登録されているか**を見る。

    python -m backend.ux_verification.api_contract --persona owner

## 判定方法とその限界

サーバは起動しない。ルーター定義を AST で読むだけなので**無料**で、CI でそのまま
回り、実行のたびに同じ答えを返す。代わりに「実際に 200 を返すか」は保証しない
——実装が例外を投げるかどうかまでは分からない。この限界を隠さないため、
すべての結果の evidence に `static_route_scan` と刻む。

偽 PASS への歯止め: **定義があってもアプリに `include_router` されていなければ
呼んでも 404 になる。** これを `unregistered` として FAIL にする。
DOM 側の `unreachable` と同じ考え方。
"""
from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

METHOD = "static_route_scan"

_HTTP_METHODS = ("get", "post", "put", "delete", "patch", "head", "options")
_EXCLUDED_DIRS = {"__pycache__", "node_modules"}


class Verdict(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class EndpointSite:
    """エンドポイントが定義されている場所。PASS の証拠になる。"""

    path: str
    method: str
    file: str
    line: int
    module: str
    registered: bool | None = None  # None = アプリ定義を渡しておらず未判定
    # ハンドラが返しうるフィールド名。レスポンス内容の主張を判定するのに使う。
    fields: frozenset[str] = frozenset()

    def as_evidence(self) -> str:
        return f"{METHOD}: {self.file}:{self.line} {self.method} {self.path}"


@dataclass
class EndpointRegistry:
    """ルーター定義から拾ったエンドポイントの索引。"""

    endpoints: dict[tuple[str, str], EndpointSite] = field(default_factory=dict)
    files_scanned: int = 0
    unparsable: list[str] = field(default_factory=list)
    registered_modules: set[str] | None = None

    # --- 構築 ---------------------------------------------------------------

    @classmethod
    def scan(cls, routers_dir: Path,
             app_files: list[Path] | None = None) -> EndpointRegistry:
        routers_dir = Path(routers_dir)
        reg = cls()

        aliases = _router_aliases(routers_dir / "__init__.py")
        if app_files:
            included = set()
            for app_file in app_files:
                included |= _included_aliases(Path(app_file))
            reg.registered_modules = {
                mod for mod, alias in aliases.items() if alias in included
            }

        for path in _iter_router_files(routers_dir):
            reg.files_scanned += 1
            module = path.stem
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                reg.unparsable.append(path.name)
                continue

            prefix = _router_prefix(tree)
            registered = (
                None if reg.registered_modules is None
                else module in reg.registered_modules
            )
            for method, route, line, fields in _routes(tree):
                full = _join(prefix, route)
                site = EndpointSite(full, method, _display(path, routers_dir),
                                    line, module, registered, fields)
                reg.endpoints.setdefault((method, full), site)
        return reg

    @classmethod
    def for_repo(cls) -> EndpointRegistry:
        root = _project_root()
        backend = root / "backend"
        app_files = [p for p in (backend / "main.py", backend / "api_versioning.py")
                     if p.exists()]
        return cls.scan(backend / "routers", app_files=app_files)

    # --- 解決 ---------------------------------------------------------------

    def resolve(self, path: str, method: str | None = None) -> EndpointSite | None:
        if not path:
            return None
        path = _normalise(path)
        if method:
            return self.endpoints.get((method.upper(), path))
        for m in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            hit = self.endpoints.get((m, path))
            if hit:
                return hit
        return None


@dataclass
class ContractResult:
    item_id: str
    ux_story: str
    story_scene: str
    description: str
    endpoint: str
    verdict: Verdict
    reason: str  # found / not_found / unregistered / no_endpoint / field_not_found
    evidence: str

    @property
    def passed(self) -> bool | None:
        if self.verdict is Verdict.PASS:
            return True
        if self.verdict is Verdict.FAIL:
            return False
        return None


class ApiContractExecutor:
    """ストーリーが宣言したエンドポイントを、ルーター定義に突き合わせる。"""

    def __init__(self, registry: EndpointRegistry):
        self.registry = registry

    def judge(self, ux_id: str, item: dict) -> ContractResult:
        declared = (item.get("endpoint") or "").strip()
        common = {
            "item_id": item.get("id", ""),
            "ux_story": ux_id,
            "story_scene": item.get("story_scene", ""),
            "description": item.get("description", ""),
            "endpoint": declared,
        }

        if not declared:
            return ContractResult(
                **common, verdict=Verdict.FAIL, reason="no_endpoint",
                evidence=(
                    f"{METHOD}: 項目が API 契約を主張しているが endpoint を持たない。"
                    "照合先が無いため保証されていない。"
                ),
            )

        method, path = _split_endpoint(declared)
        site = self.registry.resolve(path, method)
        if site is None:
            return ContractResult(
                **common, verdict=Verdict.FAIL, reason="not_found",
                evidence=(
                    f"{METHOD}: {method} {path} に対応する定義が"
                    f"ルーター{self.registry.files_scanned}ファイルのどこにも無い。"
                ),
            )

        if site.registered is False:
            return ContractResult(
                **common, verdict=Verdict.FAIL, reason="unregistered",
                evidence=(
                    f"{METHOD}: {site.file}:{site.line} に定義はあるが、"
                    f"ルーター {site.module} がアプリに include_router されていない"
                    "（呼んでも 404 になる）。"
                ),
            )

        # レスポンス内容の主張は、エンドポイントの実在では検証できない。
        # 宣言されたフィールドがハンドラの返り値に現れるかまで見る。
        field = (item.get("response_field") or "").strip()
        if field:
            if field not in site.fields:
                return ContractResult(
                    **common, verdict=Verdict.FAIL, reason="field_not_found",
                    evidence=(
                        f"{METHOD}: {site.file}:{site.line} の {site.method} {site.path} は"
                        f"存在するが、返り値に {field} が現れない"
                        f"（拾えたフィールド {len(site.fields)} 個）。"
                    ),
                )
            return ContractResult(
                **common, verdict=Verdict.PASS, reason="found",
                evidence=(
                    f"{METHOD}: {site.file}:{site.line} {site.method} {site.path}"
                    f" が {field} を返す"
                ),
            )

        return ContractResult(
            **common, verdict=Verdict.PASS, reason="found",
            evidence=site.as_evidence(),
        )


# --- AST のこまごました部分 ---------------------------------------------------


def _iter_router_files(routers_dir: Path):
    if not routers_dir.exists():
        return
    for path in sorted(routers_dir.rglob("*.py")):
        if path.name == "__init__.py" or _EXCLUDED_DIRS & set(path.parts):
            continue
        yield path


def _router_prefix(tree: ast.Module) -> str:
    """`router = APIRouter(prefix="/api/x")` の prefix を取る。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and _callee_name(call.func) == "APIRouter"):
            continue
        for kw in call.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value or "")
        return ""
    return ""


def _routes(tree: ast.Module):
    """`@router.get("/x")` を (METHOD, "/x", 行番号, フィールド集合) で返す。"""
    models = _response_models(tree)
    module_dicts = _module_dicts(tree)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_METHODS:
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "router":
                continue
            if dec.args and isinstance(dec.args[0], ast.Constant):
                fields = _handler_fields(node, module_dicts)
                for kw in dec.keywords:
                    if kw.arg == "response_model" and isinstance(kw.value, ast.Name):
                        fields |= models.get(kw.value.id, frozenset())
                yield func.attr.upper(), str(dec.args[0].value), dec.lineno, fields


def _module_dicts(tree: ast.Module) -> dict:
    """モジュール直下の `X = {...}` を {変数名: キー集合} で返す。

    ハンドラが `return {"settings": _render_settings.copy()}` のように
    モジュール変数を返す形が多く、参照を辿らないと中身を見落とす。
    """
    out: dict[str, frozenset] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        keys = {k.value for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        for target in node.targets:
            if isinstance(target, ast.Name) and keys:
                out[target.id] = frozenset(keys)
    return out


def _handler_fields(node, module_dicts: dict | None = None) -> frozenset:
    """ハンドラが返しうるフィールド名を集める。

    `return {"status": ...}` の文字列キーを拾う。入れ子の辞書も辿るのは、
    「推奨セグメントに score フィールドが存在する」のような
    一段深い主張があるため。値の型までは見ない。
    """
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Return) and sub.value is not None:
            _collect_keys(sub.value, out, 0, module_dicts or {})
    return frozenset(out)


def _collect_keys(node, out: set, depth: int = 0, module_dicts: dict | None = None) -> None:
    module_dicts = module_dicts or {}
    if depth > 6:
        return
    if isinstance(node, ast.Name):
        out |= module_dicts.get(node.id, frozenset())
        return
    if isinstance(node, ast.Attribute):
        _collect_keys(node.value, out, depth + 1, module_dicts)
        return
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                out.add(key.value)
            _collect_keys(value, out, depth + 1, module_dicts)
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for elt in node.elts:
            _collect_keys(elt, out, depth + 1, module_dicts)
    elif isinstance(node, ast.Call):
        _collect_keys(node.func, out, depth + 1, module_dicts)
        for kw in node.keywords:
            if kw.arg:
                out.add(kw.arg)
        for arg in node.args:
            _collect_keys(arg, out, depth + 1, module_dicts)
    elif isinstance(node, (ast.ListComp, ast.GeneratorExp)):
        _collect_keys(node.elt, out, depth + 1, module_dicts)
    elif isinstance(node, ast.IfExp):
        _collect_keys(node.body, out, depth + 1, module_dicts)
        _collect_keys(node.orelse, out, depth + 1, module_dicts)


def _response_models(tree: ast.Module) -> dict:
    """モジュール内のクラス定義から、注釈付き属性名を集める。"""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            names = {
                b.target.id for b in node.body
                if isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name)
            }
            if names:
                out[node.name] = frozenset(names)
    return out


def _router_aliases(init_path: Path) -> dict[str, str]:
    """`from .quota import router as quota_router` を {module: alias} で返す。"""
    out: dict[str, str] = {}
    if not init_path.exists():
        return out
    try:
        tree = ast.parse(init_path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        module = node.module.split(".")[-1]
        for alias in node.names:
            if alias.name == "router" and alias.asname:
                out[module] = alias.asname
    return out


def _included_aliases(app_file: Path) -> set[str]:
    """`app.include_router(quota_router)` の引数名を集める。"""
    out: set[str] = set()
    if not app_file.exists():
        return out
    try:
        tree = ast.parse(app_file.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _callee_name(node.func) != "include_router" or not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Name):
            out.add(arg.id)
    return out


def _callee_name(func) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _join(prefix: str, route: str) -> str:
    return _normalise(f"{prefix}/{route}")


def _normalise(path: str) -> str:
    path = "/" + re.sub(r"/{2,}", "/", path).strip("/")
    return path if path != "/" else "/"


def _split_endpoint(declared: str) -> tuple[str, str]:
    """"GET /api/x" と "/api/x" のどちらも受ける。省略時は GET。"""
    parts = declared.split(None, 1)
    if len(parts) == 2 and parts[0].upper() in [m.upper() for m in _HTTP_METHODS]:
        return parts[0].upper(), _normalise(parts[1])
    return "GET", _normalise(declared)


def _display(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base.parent).as_posix()
    except ValueError:
        return path.as_posix()


def _project_root() -> Path:
    try:
        from backend.path_resolver import project_root

        return Path(project_root())
    except (ImportError, OSError, ValueError):
        return Path(__file__).resolve().parents[2]


# --- CLI ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="UX 検証項目の API 契約（エンドポイント実在）を判定する",
    )
    parser.add_argument("--persona", default="owner", choices=["owner", "admin"])
    parser.add_argument("--list-endpoints", action="store_true",
                        help="走査で見つかったエンドポイントを列挙して終わる")
    args = parser.parse_args(argv)

    registry = EndpointRegistry.for_repo()
    print(f"API 契約 — method={METHOD}")
    print(f"  走査: ルーター {registry.files_scanned} ファイル"
          f" / エンドポイント {len(registry.endpoints)} 件")
    if registry.unparsable:
        print(f"  ⚠️ 解析できないファイル: {', '.join(registry.unparsable)}")

    if registry.registered_modules is not None:
        unregistered = sorted({
            s.module for s in registry.endpoints.values() if s.registered is False
        })
        print(f"  アプリ未登録のルーター: {len(unregistered)} 件"
              + (f"（{', '.join(unregistered[:6])}…）" if unregistered else ""))

    if args.list_endpoints:
        for (m, p), site in sorted(registry.endpoints.items()):
            mark = "  " if site.registered else "✗ "
            print(f"  {mark}{m:<7} {p}   {site.file}:{site.line}")
        return 0

    print("\n（判定にはストーリー側の endpoint 記入が要ります。P2 C-2 で入れます）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
