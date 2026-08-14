"""呼び出し口の閉包（P5 C-1・C-2・C-3・C-4・C-5）。

**主眼は「緑にできないこと」。** 閉包は「扉の外に呼び出しが無い」という禁止
なので、緑にする方法は2つしかない — 本当に無いか、**禁止をすり抜けるか**。
後者を1つずつ塞ぐ。

現物のツリーに対する弱化の実測は PR 本文にある。ここでは同じ型を
合成したツリーで固定して、**あとから壊せないように**する。
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from backend.ux_verification.api_contract import EndpointRegistry
from backend.ux_verification.ui_api import UNSCANNED_FORMS, UiApiExecutor
from backend.ux_verification.ui_api_closure import (
    _NOT_A_CALL_FORM,
    CLOSURE_SEMANTICS,
    DECLARATION_KEYS,
    FORBIDDEN_FORMS,
    ClosureExecutor,
    check_ratchet,
    load_baseline,
    snapshot,
    write_baseline,
)

# --- 足場 ---------------------------------------------------------------------

_ROUTER = """
    from fastapi import APIRouter

    router = APIRouter(prefix="/api/demo")

    @router.get("/status")
    async def status():
        return {"ok": True}
"""

_CLIENT = """
    import { ENDPOINTS } from './endpoints.js';

    const HTTP_ORIGIN = 'http://localhost:8000';

    export function apiUrl(name) {
      return HTTP_ORIGIN + ENDPOINTS[name].path;
    }

    export function apiFetch(name) {
      return fetch(apiUrl(name), { method: ENDPOINTS[name].method });
    }
"""

_CATALOGUE = ("export const ENDPOINTS = {\n"
              "  getStatus: { method: 'GET', path: '/api/demo/status' },\n"
              "};\n")

_APP = """
    import { apiFetch } from '../gateway/client.js';

    export default function App() {
      return apiFetch('getStatus');
    }
"""


def _build(tmp_path: Path, *, app: str = _APP, catalogue: str = _CATALOGUE,
           client: str = _CLIENT, allowlist: list | None = None,
           extra: dict | None = None) -> ClosureExecutor:
    routers = tmp_path / "backend" / "routers"
    routers.mkdir(parents=True)
    (routers / "__init__.py").write_text(
        "from .demo import router as demo_router\n", encoding="utf-8")
    (routers / "demo.py").write_text(textwrap.dedent(_ROUTER), encoding="utf-8")
    app_file = tmp_path / "backend" / "main.py"
    app_file.write_text("from routers import demo_router\n"
                        "app.include_router(demo_router)\n", encoding="utf-8")

    src = tmp_path / "frontend" / "src"
    (src / "components").mkdir(parents=True)
    (src / "gateway").mkdir(parents=True)
    (src / "main.jsx").write_text(
        'import App from "./components/App";\n', encoding="utf-8")
    (src / "components" / "App.jsx").write_text(textwrap.dedent(app),
                                                encoding="utf-8")
    (src / "gateway" / "endpoints.js").write_text(catalogue, encoding="utf-8")
    (src / "gateway" / "client.js").write_text(textwrap.dedent(client),
                                               encoding="utf-8")
    (src / "gateway" / "external_urls.json").write_text(
        json.dumps({"declared": allowlist or []}, ensure_ascii=False),
        encoding="utf-8")
    for name, text in (extra or {}).items():
        target = src / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text), encoding="utf-8")

    executor = UiApiExecutor(
        src, EndpointRegistry.scan(routers, app_files=[app_file]),
        entry=src / "main.jsx")
    return ClosureExecutor(executor)


def _kinds(report) -> list[str]:
    return sorted({f.kind for f in report.findings})


# --- 閉じている状態 -----------------------------------------------------------


def test_a_migrated_tree_is_closed(tmp_path):
    report = _build(tmp_path).run()

    assert report.findings == []
    assert report.closed
    assert report.entries == {"getStatus": "GET /api/demo/status"}
    assert report.usages == {"src/components/App.jsx": ["getStatus"]}


# --- C-1 閉包 -----------------------------------------------------------------


def test_a_raw_fetch_outside_the_gateway_is_a_violation(tmp_path):
    report = _build(tmp_path, app="""
        export default function App() {
          return fetch('/api/demo/status');
        }
    """).run()

    assert "forbidden_form" in _kinds(report)


def test_a_backend_url_in_a_comment_is_a_violation(tmp_path):
    """**ここが P5 の要。** コメントを除去しないので、コメント内も落ちる。

    P4 はコメントを外してから数えるので、この形は「呼び出しではない」として
    素通りしていた。除去が要らなければ、除去の誤りも無い。
    """
    report = _build(tmp_path, app="""
        import { apiFetch } from '../gateway/client.js';

        export default function App() {
          // TODO: '/api/demo/status' を直接叩く
          return apiFetch('getStatus');
        }
    """).run()

    assert "backend_url" in _kinds(report)


def test_a_call_form_in_a_comment_is_a_violation(tmp_path):
    """コメントアウトした呼び出しも落とす。**判定を誤っても沈黙にならない。**"""
    report = _build(tmp_path, app="""
        import { apiFetch } from '../gateway/client.js';

        export default function App() {
          // fetch('/x');
          return apiFetch('getStatus');
        }
    """).run()

    assert "forbidden_form" in _kinds(report)


def test_an_undeclared_absolute_url_is_a_violation(tmp_path):
    report = _build(tmp_path, extra={
        "components/Badge.jsx": """
            export const LOGO = 'https://cdn.example.com/logo.png';
        """}).run()

    assert "external_url" in _kinds(report)


def test_a_declared_absolute_url_is_allowed(tmp_path):
    report = _build(tmp_path, allowlist=[{
        "url": "https://cdn.example.com/logo.png",
        "file": "src/components/Badge.jsx",
        "why": "外部 CDN の画像。backend 呼び出しではない",
    }], extra={
        "components/Badge.jsx": """
            export const LOGO = 'https://cdn.example.com/logo.png';
        """}).run()

    assert report.findings == []


def test_an_allowlist_entry_that_matches_another_file_does_not_cover_it(tmp_path):
    """**許可はファイル単位。** どこか1箇所で許すと全部通る、にしない。"""
    report = _build(tmp_path, allowlist=[{
        "url": "https://cdn.example.com/logo.png",
        "file": "index.html",
        "why": "別のファイル向けの許可",
    }], extra={
        "components/Badge.jsx": """
            export const LOGO = 'https://cdn.example.com/logo.png';
        """}).run()

    assert "external_url" in _kinds(report)


def test_an_unused_allowlist_entry_is_a_violation(tmp_path):
    """使われていない許可は、あとで何かを黙って通す。"""
    report = _build(tmp_path, allowlist=[{
        "url": "https://cdn.example.com/old.png",
        "file": "src/components/App.jsx",
        "why": "もう無い",
    }]).run()

    assert "dead_allowlist" in _kinds(report)


def test_a_missing_allowlist_is_a_violation(tmp_path):
    """**無い状態を緑にしない。** 消すだけで例外が無制限になる。"""
    executor = _build(tmp_path)
    (executor.frontend / "src" / "gateway" / "external_urls.json").unlink()

    assert "allowlist_missing" in _kinds(executor.run())


def test_an_extra_file_in_the_gateway_is_a_violation(tmp_path):
    """扉が2つになれば、片方だけ守っても意味が無い。"""
    executor = _build(tmp_path)
    (executor.frontend / "src" / "gateway" / "other.js").write_text(
        "export const x = 1;\n", encoding="utf-8")

    assert "extra_gateway_file" in _kinds(executor.run())


def test_a_missing_gateway_file_is_a_violation(tmp_path):
    executor = _build(tmp_path)
    (executor.frontend / "src" / "gateway" / "client.js").unlink()

    assert "gateway_missing" in _kinds(executor.run())


# --- C-2 カタログの文法 -------------------------------------------------------


@pytest.mark.parametrize("catalogue", [
    # 変数経由。カタログが「叩ける先の全部」でなくなる。
    "export const ENDPOINTS = {\n  getStatus: { method: 'GET', path: PATH },\n};\n",
    # 連結。
    ("export const ENDPOINTS = {\n"
     "  getStatus: { method: 'GET', path: '/api' + '/demo/status' },\n};\n"),
    # テンプレートリテラル。
    ("export const ENDPOINTS = {\n"
     "  getStatus: { method: 'GET', path: `/api/demo/status` },\n};\n"),
    # 1行に2項目。行単位の列挙から片方が消える。
    ("export const ENDPOINTS = {\n"
     "  a: { method: 'GET', path: '/api/demo/status' }, "
     "b: { method: 'GET', path: '/api/demo/status' },\n};\n"),
    # 途中に別の式。
    ("export const ENDPOINTS = {\n"
     "  ...OTHERS,\n"
     "  getStatus: { method: 'GET', path: '/api/demo/status' },\n};\n"),
])
def test_a_catalogue_line_outside_the_closed_grammar_is_a_violation(
        tmp_path, catalogue):
    report = _build(tmp_path, catalogue=catalogue).run()

    assert "catalogue_grammar" in _kinds(report)


def test_an_empty_catalogue_is_a_violation(tmp_path):
    """**0件を緑にしない。** 全部消すだけでゲートが無効になる。"""
    report = _build(tmp_path, catalogue="export const ENDPOINTS = {\n};\n").run()

    assert "catalogue_empty" in _kinds(report)


def test_a_duplicate_catalogue_key_is_a_violation(tmp_path):
    report = _build(tmp_path, catalogue=(
        "export const ENDPOINTS = {\n"
        "  getStatus: { method: 'GET', path: '/api/demo/status' },\n"
        "  getStatus: { method: 'GET', path: '/api/demo/status' },\n};\n")).run()

    assert "catalogue_duplicate" in _kinds(report)


def test_a_line_comment_in_the_catalogue_is_allowed(tmp_path):
    report = _build(tmp_path, catalogue=(
        "// 叩ける先の全部\n"
        "export const ENDPOINTS = {\n"
        "  getStatus: { method: 'GET', path: '/api/demo/status' },\n};\n")).run()

    assert report.findings == []


# --- C-3 使用の解決 -----------------------------------------------------------


def test_an_unknown_key_is_a_violation(tmp_path):
    report = _build(tmp_path, app="""
        import { apiFetch } from '../gateway/client.js';

        export default function App() {
          return apiFetch('getGhost');
        }
    """).run()

    assert "unknown_key" in _kinds(report)
    # 使用が無くなった項目も出る（片方だけ直して緑、にしない）
    assert "unused_entry" in _kinds(report)


def test_a_computed_key_is_a_violation(tmp_path):
    """**宛先はリテラルでなければならない。** 変数を挟めば静的に決まらない。"""
    report = _build(tmp_path, app="""
        import { apiFetch } from '../gateway/client.js';

        export default function App(name) {
          return apiFetch(name);
        }
    """).run()

    assert "computed_key" in _kinds(report)


def test_a_namespace_import_is_a_violation(tmp_path):
    """`import * as gw` を許すと、使用の検出が名前の追跡になる。"""
    report = _build(tmp_path, app="""
        import * as gw from '../gateway/client.js';

        export default function App() {
          return gw.apiFetch('getStatus');
        }
    """).run()

    assert "bad_import" in _kinds(report)


def test_a_renamed_import_is_a_violation(tmp_path):
    report = _build(tmp_path, app="""
        import { apiFetch as go } from '../gateway/client.js';

        export default function App() {
          return go('getStatus');
        }
    """).run()

    assert "bad_import" in _kinds(report)


def test_an_unused_catalogue_entry_is_a_violation(tmp_path):
    """死蔵の宣言を PASS で隠さない。"""
    report = _build(tmp_path, catalogue=(
        "export const ENDPOINTS = {\n"
        "  getStatus: { method: 'GET', path: '/api/demo/status' },\n"
        "  getSpare: { method: 'GET', path: '/api/demo/status' },\n};\n")).run()

    assert _kinds(report) == ["unused_entry"]


# --- 扉の中の境界 -------------------------------------------------------------


def test_a_path_literal_inside_the_client_is_a_violation(tmp_path):
    """**扉を第2のカタログにしない。**"""
    report = _build(tmp_path, client="""
        export function sneak() {
          return fetch('http://localhost:8000/api/demo/status');
        }
    """).run()

    assert "client_path_literal" in _kinds(report)


def test_a_bare_origin_inside_the_client_is_allowed(tmp_path):
    report = _build(tmp_path).run()

    assert "client_path_literal" not in _kinds(report)


def test_a_relative_backend_path_inside_the_client_is_a_violation(tmp_path):
    report = _build(tmp_path, client="""
        const EXTRA = '/api/demo/status';
        export function sneak() { return fetch(EXTRA); }
    """).run()

    assert "client_path_literal" in _kinds(report)


# --- C-4 意味表 ---------------------------------------------------------------


def test_the_semantics_say_what_is_not_verified():
    """**「移行した＝正しく繋がっている」を PASS に含めない。**"""
    text = "".join(CLOSURE_SEMANTICS["確かめないこと"])

    assert "正しいカタログ項目を選んでいるか" in text
    assert "実行時に" in text
    assert "スキーマ" in text
    assert "ビルドと lint" in text
    assert "難読化" in text


def test_the_ban_covers_every_call_form_that_ui_api_knows():
    """**`ui_api` に形が増えたら、閉包にも自動で増える。**

    片方にだけ足すと、そこが「禁止されていない呼び出しの形」になる。
    外してよいのは呼び出しの形でないものだけで、それは名指しで宣言する。
    """
    expected = set(UNSCANNED_FORMS) - set(_NOT_A_CALL_FORM)

    assert expected <= set(FORBIDDEN_FORMS)
    assert {"fetch", "new WebSocket", "window.open"} <= set(FORBIDDEN_FORMS)


def test_the_excluded_form_is_declared_and_is_not_a_call_form():
    """外した理由が意味表に書いてある（黙って外さない）。"""
    assert _NOT_A_CALL_FORM == ("合成された URL",)
    assert "URL 属性の式" in "".join(CLOSURE_SEMANTICS["確かめないこと"])


# --- C-5 ラチェット -----------------------------------------------------------


def _pinned(tmp_path: Path, executor: ClosureExecutor) -> dict:
    write_baseline(executor.run(), tmp_path / "closure.json")
    return load_baseline(tmp_path / "closure.json")


def test_a_missing_baseline_is_a_violation(tmp_path):
    assert check_ratchet(_build(tmp_path).run(), None)


def test_a_baseline_without_a_declared_field_is_a_violation(tmp_path):
    executor = _build(tmp_path)
    baseline = _pinned(tmp_path, executor)
    for key in DECLARATION_KEYS:
        broken = {k: v for k, v in baseline.items() if k != key}
        assert check_ratchet(executor.run(), broken), key


def test_shrinking_the_ban_is_a_violation(tmp_path):
    executor = _build(tmp_path)
    baseline = _pinned(tmp_path, executor)
    baseline["forbidden_forms"]["でっちあげ"] = "x"

    violations = check_ratchet(executor.run(), baseline)

    assert any("判定が動いた" in v for v in violations)


def test_replacing_a_ban_pattern_is_a_violation(tmp_path):
    """**正規表現の本体まで固定する。** 当たらないものに差し替えれば無効化できる。"""
    executor = _build(tmp_path)
    baseline = _pinned(tmp_path, executor)
    baseline["forbidden_forms"]["fetch"] = "絶対に当たらない^$"

    assert any("判定が動いた" in v
               for v in check_ratchet(executor.run(), baseline))


def test_adding_an_allowlist_entry_is_a_violation(tmp_path):
    """例外が増えるのは弱化。差分に出す。"""
    executor = _build(tmp_path, allowlist=[{
        "url": "https://cdn.example.com/logo.png",
        "file": "src/components/Badge.jsx", "why": "外部 CDN"}],
        extra={"components/Badge.jsx":
               "export const LOGO = 'https://cdn.example.com/logo.png';\n"})
    baseline = _pinned(tmp_path, executor)
    baseline["allowlist"] = []

    assert any("例外が増えた" in v
               for v in check_ratchet(executor.run(), baseline))


def test_dropping_a_usage_is_a_violation(tmp_path):
    """**カタログに項目が残るので ui_api のラチェットでは気づけない。**"""
    executor = _build(tmp_path)
    baseline = _pinned(tmp_path, executor)
    baseline["usages"]["src/components/App.jsx"] = ["getStatus", "getSpare"]

    assert any("使用が消えた" in v
               for v in check_ratchet(executor.run(), baseline))


def test_substituting_a_catalogue_entry_is_a_violation(tmp_path):
    executor = _build(tmp_path)
    baseline = _pinned(tmp_path, executor)
    baseline["entries"]["getStatus"] = "GET /api/demo/other"

    assert any("項目が差し替わった" in v
               for v in check_ratchet(executor.run(), baseline))


def test_removing_a_catalogue_entry_is_a_violation(tmp_path):
    executor = _build(tmp_path)
    baseline = _pinned(tmp_path, executor)
    baseline["entries"]["getGone"] = "GET /api/demo/status"

    assert any("項目が消えた" in v
               for v in check_ratchet(executor.run(), baseline))


def test_an_unchanged_tree_does_not_trip_the_ratchet(tmp_path):
    executor = _build(tmp_path)

    assert check_ratchet(executor.run(), _pinned(tmp_path, executor)) == []


def test_the_snapshot_covers_every_declared_field(tmp_path):
    """欄を足したら `DECLARATION_KEYS` にも足す。**足し忘れを禁じる。**"""
    taken = snapshot(_build(tmp_path).run())

    assert set(taken) == set(DECLARATION_KEYS)
