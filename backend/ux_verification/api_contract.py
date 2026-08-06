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
# 経路の実在だけを見た判定と、返り値の中身まで見た判定を証拠の上で区別する。
# 同じラベルにすると「何を確かめて PASS にしたのか」が後から追えない。
FIELD_METHOD = "static_response_scan"

_HTTP_METHODS = ("get", "post", "put", "delete", "patch", "head", "options")
_EXCLUDED_DIRS = {"__pycache__", "node_modules"}
# 返り値の索引を作るときに読まないもの。テストと過去版スナップショットは
# 本番の返り値とは無関係で、同名関数の和集合を汚す。
_INDEX_EXCLUDED_DIRS = _EXCLUDED_DIRS | {
    "tests", "test", "archives", "scratch", "e2e",
    "antigravity_phase18_stable_v1", "antigravity_phase19_experimental_v1",
}


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
             app_files: list[Path] | None = None,
             callee_dirs: list[Path] | None = None) -> EndpointRegistry:
        routers_dir = Path(routers_dir)
        reg = cls()
        # ハンドラの返り値を一段展開するための索引。渡さなければ展開しない
        # （ルーターの return だけを読む従来の挙動）。
        callees = _function_index([Path(d) for d in callee_dirs]) if callee_dirs else {}

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
            for method, route, line, fields in _routes(tree, callees):
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
        # 返り値を組み立てているのはハンドラではなくサービス層・プラグイン層・
        # backend 直下のマネージャ群。ここを索引しないとハンドラは薄い受け皿に
        # しか見えず（`return branding_manager.get_evolution_log()`）、
        # レスポンス内容を判定できない。
        return cls.scan(backend / "routers", app_files=app_files,
                        callee_dirs=[backend] if backend.is_dir() else [])

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
        # 「statusフィールドが存在する」は定義の有無とは別の主張で、
        # 経路が在るだけで PASS にすると偽 PASS が経路の粒度で成立する。
        fields = _declared_fields(item)
        if fields:
            found, missing = {}, []
            for wanted in fields:
                hit = _match_path(wanted, site.fields)
                if hit is None:
                    missing.append(wanted)
                else:
                    found[wanted] = hit
            if missing:
                return ContractResult(
                    **common, verdict=Verdict.FAIL, reason="field_not_found",
                    evidence=(
                        f"{FIELD_METHOD}: {site.file}:{site.line} の"
                        f" {site.method} {site.path} は存在するが、返り値に"
                        f" {'・'.join(missing)} が現れない"
                        f"（拾えたパス {len(site.fields)} 本）。"
                    ),
                )
            return ContractResult(
                **common, verdict=Verdict.PASS, reason="field_found",
                evidence=(
                    f"{FIELD_METHOD}: {site.file}:{site.line}"
                    f" {site.method} {site.path} が"
                    f" {'・'.join(sorted(found.values()))} を返す"
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


def _routes(tree: ast.Module, callees: dict | None = None):
    """`@router.get("/x")` を (METHOD, "/x", 行番号, フィールドのパス集合) で返す。"""
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
                fields = _handler_fields(node, module_dicts, callees)
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


def _handler_fields(node, module_dicts: dict | None = None,
                    callees: dict | None = None) -> frozenset:
    """ハンドラが返しうるフィールドを **パス** の集合で返す。

    ルーターの `return` を読むだけでは足りない。実測すると本番のハンドラは
    ほとんどが薄い受け皿で、中身はサービス層が組み立てている:

        status = service.get_evolution_status()
        return status                      # ← ここだけ見ても 0 フィールド

        return {"recommendation": smart_cut.get_recommendation()}
                            # ← success と recommendation しか見えない

    そこで (1) ハンドラ内のローカル代入を辿り、(2) 呼び先の関数を
    リポジトリ全体の索引から引いて**一段だけ**展開する。
    結果は `recommendation.recommended_segments.score` のような
    ドット区切りのパスで持つ。どこで見つけたかを証拠に書けるようにするため。
    """
    module_dicts = module_dicts or {}
    callees = callees or {}
    locals_ = _local_assignments(node)

    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Return) and sub.value is not None:
            _collect_paths(sub.value, "", out, 0, module_dicts, callees, locals_)
    return frozenset(out)


def _local_assignments(node) -> dict:
    """ハンドラ内の `x = <式>` を {変数名: 式} で返す。

    同じ名前に複数回代入していたら**最初の1つだけ**を使う。どれが返るかは
    静的には決まらないので、後の代入で上書きして「見つかったことにする」のを避ける。
    """
    out: dict = {}
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            for target in sub.targets:
                if isinstance(target, ast.Name) and target.id not in out:
                    out[target.id] = sub.value
    return out


def _collect_paths(node, prefix: str, out: set, depth: int,
                   module_dicts: dict, callees: dict, locals_: dict) -> None:
    if depth > 6:
        return

    def add(name: str) -> str:
        path = f"{prefix}.{name}" if prefix else name
        out.add(path)
        return path

    if isinstance(node, ast.Name):
        for key in module_dicts.get(node.id, ()):
            add(key)
        target = locals_.get(node.id)
        if target is not None and depth < 4:
            # 自己参照（x = f(x)）で止まらなくなるのを防ぐため、辿った変数は外す
            _collect_paths(target, prefix, out, depth + 1, module_dicts, callees,
                           {k: v for k, v in locals_.items() if k != node.id})
        return
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                child = add(key.value)
                _collect_paths(value, child, out, depth + 1,
                               module_dicts, callees, locals_)
            else:
                _collect_paths(value, prefix, out, depth + 1,
                               module_dicts, callees, locals_)
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        # 配列の要素は同じ階層として扱う。「候補に type フィールドが存在する」は
        # candidates[].type を candidates.type と言っているのと同じ粒度の主張。
        for elt in node.elts:
            _collect_paths(elt, prefix, out, depth + 1, module_dicts, callees, locals_)
    elif isinstance(node, ast.Call):
        for path in _callee_fields(node.func, callees):
            out.add(f"{prefix}.{path}" if prefix else path)
        for kw in node.keywords:
            if kw.arg:
                add(kw.arg)
        for arg in node.args:
            _collect_paths(arg, prefix, out, depth + 1, module_dicts, callees, locals_)
    elif isinstance(node, (ast.ListComp, ast.GeneratorExp)):
        _collect_paths(node.elt, prefix, out, depth + 1, module_dicts, callees, locals_)
    elif isinstance(node, ast.IfExp):
        _collect_paths(node.body, prefix, out, depth + 1,
                       module_dicts, callees, locals_)
        _collect_paths(node.orelse, prefix, out, depth + 1,
                       module_dicts, callees, locals_)
    elif isinstance(node, ast.Await):
        _collect_paths(node.value, prefix, out, depth + 1,
                       module_dicts, callees, locals_)


def _function_index(search_dirs: list[Path]) -> dict:
    """リポジトリ内の関数が返す辞書のパスを {関数名: パス集合} で索引する。

    ハンドラから**一段だけ**展開するための材料。呼び先の中でさらに呼んでいる
    関数は辿らない（辿り始めると呼び出しグラフ全体になり、どこで見つけたのかを
    証拠として書けなくなる）。
    """
    out: dict[str, set[str]] = {}
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            if _INDEX_EXCLUDED_DIRS & set(path.parts) or path.name.startswith("test_"):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, ValueError):
                continue
            module_dicts = _module_dicts(tree)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                paths = _handler_fields(node, module_dicts, callees={})
                if paths:
                    out.setdefault(node.name, set()).update(paths)
    return {name: frozenset(paths) for name, paths in out.items()}


def _callee_fields(func, callees: dict) -> frozenset:
    """`service.get_status()` / `build()` の呼び先が返すパスを索引から引く。

    名前だけで引くので、同名の関数が複数あれば**和集合**になる。
    厳密な解決には import の追跡が要り、静的走査の範囲を超える。
    和集合は偽 PASS 側に倒れるため、証拠には呼び先の名前を残す。
    """
    name = func.attr if isinstance(func, ast.Attribute) else (
        func.id if isinstance(func, ast.Name) else ""
    )
    return callees.get(name, frozenset())


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


def _declared_fields(item: dict) -> list[str]:
    """`response_field` を文字列でも配列でも受ける。

    「iteration/max_iterations フィールドが存在する」のように1項目が複数の
    フィールドを主張することがある。片方だけ見て PASS にすると取りこぼす。
    """
    raw = item.get("response_field")
    if not raw:
        return []
    values = raw if isinstance(raw, list) else [raw]
    return [f for f in (str(v).strip() for v in values) if f]


def _match_path(wanted: str, paths: frozenset[str]) -> str | None:
    """宣言されたフィールドが、拾ったパスのどれに当たるかを返す。

    完全一致を先に見る。`recommendation.score` と書けば、その位置にあることまで
    主張したことになる。一致しなければ末端の名前で探す——ストーリーの多くは
    「推奨セグメントに score フィールドが存在する」のように位置を書いておらず、
    レスポンスのどこかに在ることまでしか主張していないため。
    どちらで当たったかは呼び出し側が証拠に書く（パスが返るので区別できる）。
    """
    if wanted in paths:
        return wanted
    hits = sorted(p for p in paths if p.rsplit(".", 1)[-1] == wanted)
    return hits[0] if hits else None


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
