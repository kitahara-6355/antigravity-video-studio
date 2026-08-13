"""UI と API の接続（P4 C-1 / C-2）。

**このテストの主眼は「緑になること」ではなく「緑にできないこと」。**
P3 で 26回破られた型（書き方の違いで判定が弱くなる／照合が1箇所にしか
掛かっていない）を、ここでも先に潰しておく。
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backend.ux_verification.api_contract import EndpointRegistry
from backend.ux_verification.ui_api import (
    VERDICT_SEMANTICS,
    UiApiExecutor,
    Verdict,
    _assignments,
    _resolve_method,
    _resolve_url,
    _version_mounts,
)

# --- 足場 ---------------------------------------------------------------------


def _routers(tmp_path: Path, body: str) -> Path:
    routers = tmp_path / "backend" / "routers"
    routers.mkdir(parents=True)
    (routers / "__init__.py").write_text(
        "from .demo import router as demo_router\n", encoding="utf-8")
    (routers / "demo.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return routers


_DEMO_ROUTER = """
    from fastapi import APIRouter

    router = APIRouter(prefix="/api/demo")

    @router.get("/status")
    async def status():
        return {"ok": True}

    @router.put("/entries/{entry_id}")
    async def update(entry_id: str):
        return {"ok": True}
"""


def _frontend(tmp_path: Path, source: str, extra: dict | None = None) -> Path:
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "main.jsx").write_text(
        'import App from "./App";\n', encoding="utf-8")
    (src / "App.jsx").write_text(textwrap.dedent(source), encoding="utf-8")
    for name, text in (extra or {}).items():
        target = src / name
        # 呼び出し口は `api/` の下に置く。サブディレクトリを作れないと
        # 閉包側のテストが1つも書けない。
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text), encoding="utf-8")
    return src


def _run(tmp_path: Path, source: str, *, router_body: str = _DEMO_ROUTER,
         app_file: Path | None = None, extra: dict | None = None,
         mount_v1: bool = True):
    routers = _routers(tmp_path, router_body)
    app = tmp_path / "backend" / "main.py"
    app.write_text(
        "from routers import demo_router\n"
        "app.include_router(demo_router)\n"
        + ("app.include_router(v1_router)\n" if mount_v1 else ""),
        encoding="utf-8")
    registry = EndpointRegistry.scan(routers, app_files=[app])
    prefix, modules = (_version_mounts(app_file, routers, main_files=[app])
                       if app_file else ("", set()))
    src = _frontend(tmp_path, source, extra)
    return UiApiExecutor(src, registry, entry=src / "main.jsx",
                         version_prefix=prefix, version_modules=modules).run()


def _verdicts(report) -> list[Verdict]:
    return [s.verdict for s in report.sites]


# --- 突き合う形 ---------------------------------------------------------------


def test_a_template_literal_with_a_base_constant_matches(tmp_path):
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          fetch(`${API_BASE}/api/demo/status`);
        }
    """)

    assert _verdicts(report) == [Verdict.MATCHED]
    assert report.sites[0].path == "/api/demo/status"
    assert report.sites[0].method == "GET"


def test_a_plain_string_literal_matches(tmp_path):
    report = _run(tmp_path, """
        export default function App() {
          fetch('http://localhost:8000/api/demo/status');
        }
    """)

    assert _verdicts(report) == [Verdict.MATCHED]


def test_a_path_parameter_matches_by_shape_not_by_name(tmp_path):
    """フロントは `entryId`、FastAPI は `{entry_id}`。名前で落とさない。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App(entryId) {
          fetch(`${API_BASE}/api/demo/entries/${entryId}`, { method: 'PUT' });
        }
    """)

    assert _verdicts(report) == [Verdict.MATCHED]
    assert report.sites[0].path == "/api/demo/entries/{}"


def test_a_query_string_is_not_part_of_the_judgement(tmp_path):
    """`?` 以降は確かめない。そこに式があっても解決できない理由にしない。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App(t) {
          fetch(`${API_BASE}/api/demo/status?t=${t}`);
        }
    """)

    assert _verdicts(report) == [Verdict.MATCHED]
    assert report.sites[0].path == "/api/demo/status"


def test_a_url_bound_once_is_followed(tmp_path):
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          const url = `${API_BASE}/api/demo/status`;
          fetch(url);
        }
    """)

    assert _verdicts(report) == [Verdict.MATCHED]


# --- 突き合わない形（ここが本題） ---------------------------------------------


def test_an_undeclared_path_fails(tmp_path):
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          fetch(`${API_BASE}/api/demo/nope`);
        }
    """)

    assert _verdicts(report) == [Verdict.NOT_DECLARED]


def test_the_wrong_method_fails_even_though_the_path_exists(tmp_path):
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App(entryId) {
          fetch(`${API_BASE}/api/demo/entries/${entryId}`, { method: 'DELETE' });
        }
    """)

    assert _verdicts(report) == [Verdict.METHOD_MISMATCH]


def test_a_router_that_is_not_included_fails(tmp_path):
    """宣言があっても include_router されていなければ呼べば 404。"""
    routers = _routers(tmp_path, _DEMO_ROUTER)
    app = tmp_path / "backend" / "main.py"
    app.write_text("app = None\n", encoding="utf-8")  # include_router していない
    registry = EndpointRegistry.scan(routers, app_files=[app])
    src = _frontend(tmp_path, """
        export default function App() {
          fetch('http://localhost:8000/api/demo/status');
        }
    """)

    report = UiApiExecutor(src, registry, entry=src / "main.jsx").run()

    assert _verdicts(report) == [Verdict.NOT_REGISTERED]


def test_a_variable_url_that_is_bound_twice_is_unresolved(tmp_path):
    """どちらの値で叩くのか静的に決まらないものを PASS にしない。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App(flag) {
          let url = `${API_BASE}/api/demo/status`;
          url = `${API_BASE}/api/demo/nope`;
          fetch(url);
        }
    """)

    # 呼び出しは読めない。加えて、再代入側の URL はどの呼び出しにも
    # 紐づかないので残余として出る。どちらも PASS ではない。
    assert Verdict.UNRESOLVED_URL in _verdicts(report)
    assert Verdict.UNATTRIBUTED in _verdicts(report)
    assert not any(s.passed for s in report.sites)


def test_a_computed_url_is_unresolved(tmp_path):
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App(name) {
          fetch(API_BASE + '/api/demo/' + name);
        }
    """)

    assert _verdicts(report) == [Verdict.UNRESOLVED_URL]


def test_an_expression_inside_a_segment_is_unresolved(tmp_path):
    """`/entries/pre${id}` はセグメント全体ではない。パラメータに化けさせない。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App(id) {
          fetch(`${API_BASE}/api/demo/entries/pre${id}`, { method: 'PUT' });
        }
    """)

    assert _verdicts(report) == [Verdict.UNRESOLVED_URL]


def test_a_non_literal_method_is_unresolved(tmp_path):
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App(verb) {
          fetch(`${API_BASE}/api/demo/status`, { method: verb });
        }
    """)

    assert _verdicts(report) == [Verdict.UNRESOLVED_METHOD]


def test_a_method_hidden_in_a_spread_is_unresolved(tmp_path):
    """`{...opts}` の中に method が入っていれば読めない。GET と決めつけない。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App(opts) {
          fetch(`${API_BASE}/api/demo/status`, { ...opts });
        }
    """)

    assert _verdicts(report) == [Verdict.UNRESOLVED_METHOD]


def test_a_window_fetch_is_scanned_not_dropped(tmp_path):
    """`window.fetch` を見落とすと、呼び出しが**列挙から黙って消える**。"""
    report = _run(tmp_path, """
        export default function App() {
          window.fetch('http://localhost:8000/api/demo/nope');
          globalThis.fetch('http://localhost:8000/api/demo/status');
        }
    """)

    assert _verdicts(report) == [Verdict.NOT_DECLARED, Verdict.MATCHED]


def test_an_unknown_receiver_is_not_silently_dropped(tmp_path):
    """`res.fetch(` がネットワーク呼び出しかは静的に決まらない。素通りさせない。"""
    report = _run(tmp_path, """
        export default function App(client) {
          client.fetch('http://localhost:8000/api/demo/status');
        }
    """)

    assert _verdicts(report) == [Verdict.UNRESOLVED_URL]


@pytest.mark.parametrize("rebind", [
    "API_BASE += '/wrong';",
    "API_BASE ||= '/wrong';",
    "[API_BASE] = ['/wrong'];",
])
def test_a_compound_or_destructured_rebind_is_not_followed(tmp_path, rebind):
    """素の `=` だけ見ていると、古い値のまま matched に混ざる。"""
    report = _run(tmp_path, f"""
        const API_BASE = "http://localhost:8000";
        {rebind}
        export default function App() {{
          fetch(`${{API_BASE}}/api/demo/status`);
        }}
    """)

    assert _verdicts(report) == [Verdict.UNRESOLVED_URL]


def test_a_name_shadowed_by_a_parameter_is_not_followed(tmp_path):
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App(API_BASE) {
          fetch(`${API_BASE}/api/demo/status`);
        }
    """)

    assert _verdicts(report) == [Verdict.UNRESOLVED_URL]


@pytest.mark.parametrize("form,call", [
    ("axios", "axios.post('/api/demo/status', {});"),
    ("XMLHttpRequest", "const x = new XMLHttpRequest();"),
    ("EventSource", "const e = new EventSource('/api/demo/status');"),
    ("sendBeacon", "navigator.sendBeacon('/api/demo/status');"),
])
def test_a_form_we_cannot_scan_is_reported_not_ignored(tmp_path, form, call):
    """『対応していないから見えない』を『問題なし』に混ぜない。"""
    report = _run(tmp_path, f"""
        export default function App() {{
          {call}
        }}
    """)

    assert _verdicts(report) == [Verdict.UNSCANNED_FORM]
    assert report.sites[0].reason.startswith(form)


def test_a_websocket_is_matched_against_its_declaration(tmp_path):
    report = _run(tmp_path, """
        const WS_BASE = "ws://localhost:8000";
        export default function App() {
          const ws = new WebSocket(`${WS_BASE}/api/demo/live`);
        }
    """, router_body=_DEMO_ROUTER + """
    @router.websocket("/live")
    async def live(ws):
        return None
""")

    assert _verdicts(report) == [Verdict.MATCHED]
    assert report.sites[0].method == "WEBSOCKET"


@pytest.mark.parametrize("call", [
    "client?.fetch('http://localhost:8000/api/demo/status');",
    "client\n            .fetch('http://localhost:8000/api/demo/status');",
])
def test_an_unknown_receiver_survives_optional_chaining_and_newlines(tmp_path, call):
    """`?.` や改行を跨げないと、未知の受け側が素の呼び出しに化ける。"""
    report = _run(tmp_path, f"""
        export default function App(client) {{
          {call}
        }}
    """)

    assert _verdicts(report) == [Verdict.UNRESOLVED_URL]


@pytest.mark.parametrize("call", [
    "const f = window.fetch; f('/api/demo/status');",
    "api['fetch']('/api/demo/status');",
])
def test_fetch_reached_without_a_call_site_is_reported(tmp_path, call):
    """別名束縛・計算メンバは呼び出し地点に `fetch(` が現れず、走査から消える。"""
    report = _run(tmp_path, f"""
        export default function App(api) {{
          {call}
        }}
    """)

    assert Verdict.UNSCANNED_FORM in _verdicts(report)


def test_a_jsx_url_attribute_hitting_the_backend_is_judged(tmp_path):
    """ブラウザは `<a href>` にも GET を投げる。fetch だけ見て全部見たと言わない。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          return <a href={`${API_BASE}/api/demo/status`}>x</a>;
        }
    """)

    assert _verdicts(report) == [Verdict.MATCHED]


def test_window_open_hitting_the_backend_is_judged(tmp_path):
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          window.open(`${API_BASE}/api/demo/nope`, '_blank');
        }
    """)

    assert _verdicts(report) == [Verdict.NOT_DECLARED]


def test_an_unreadable_url_attribute_is_not_assumed_to_be_a_local_asset(tmp_path):
    """**読めないものを「backend ではない」と決めつけない。**

    ここで黙って落とすと、走査すると宣言した形が実際には走査されず、
    SCANNED_FORMS の申告が実際の走査範囲より広くなる。
    """
    report = _run(tmp_path, """
        export default function App(scene) {
          return <img src={scene.image} />;
        }
    """)

    assert _verdicts(report) == [Verdict.UNRESOLVED_URL]


def test_a_resolved_non_backend_url_is_not_a_call(tmp_path):
    """解決できて backend でないと**分かった**ものだけ対象から外す。"""
    report = _run(tmp_path, """
        export default function App() {
          return <img src="/assets/logo.png" />;
        }
    """)

    assert report.sites == []


def test_a_plain_string_url_attribute_is_scanned(tmp_path):
    """`<a href="/api/x">` は波括弧が無いだけで、ブラウザは GET を投げる。"""
    report = _run(tmp_path, """
        export default function App() {
          return <a href="/api/demo/nope">x</a>;
        }
    """)

    assert _verdicts(report) == [Verdict.NOT_DECLARED]


@pytest.mark.parametrize("snippet", [
    "fetch.call(null, '/api/demo/status');",
    "fetch.apply(null, ['/api/demo/status']);",
    "location.assign('/api/demo/status');",
    "location.href = '/api/demo/status';",
    "import('/api/demo/status');",
    "navigator.serviceWorker.register('/api/demo/status');",
])
def test_a_navigation_or_indirect_call_does_not_vanish(tmp_path, snippet):
    """`fetch(` に当たらない呼び出しが、走査からも一覧からも消えないこと。"""
    report = _run(tmp_path, f"""
        export default function App() {{
          {snippet}
        }}
    """)

    assert Verdict.UNSCANNED_FORM in _verdicts(report)


def test_an_mjs_module_is_scanned(tmp_path):
    """`.mjs` は到達可能と判定されるのに走査対象から漏れていた。"""
    report = _run(tmp_path, """
        import './helper.mjs';
        export default function App() { return null; }
    """, extra={"helper.mjs": """
        fetch('http://localhost:8000/api/demo/nope');
    """})

    assert _verdicts(report) == [Verdict.NOT_DECLARED]


def test_a_css_file_is_scanned(tmp_path):
    """`CSS の url()` を「走査できない形」と宣言しながら CSS を開いていなかった。"""
    report = _run(tmp_path, """
        export default function App() { return null; }
    """, extra={"index.css": "body { background: url(/api/demo/status); }"})

    assert _verdicts(report) == [Verdict.UNSCANNED_FORM]


def test_the_entry_html_is_scanned(tmp_path):
    """`index.html` はアプリのエントリなのに一度も開かれていなかった。"""
    src = _frontend(tmp_path, "export default function App() { return null; }")
    (src.parent / "index.html").write_text(
        '<a href="/api/demo/nope">x</a>\n', encoding="utf-8")
    routers = _routers(tmp_path, _DEMO_ROUTER)
    app = tmp_path / "backend" / "main.py"
    app.write_text("from routers import demo_router\n"
                   "app.include_router(demo_router)\n", encoding="utf-8")

    report = UiApiExecutor(src, EndpointRegistry.scan(routers, app_files=[app]),
                           entry=src / "main.jsx").run()

    assert _verdicts(report) == [Verdict.NOT_DECLARED]


@pytest.mark.parametrize("snippet,expected", [
    ("new window.WebSocket('ws://localhost:8000/api/demo/nope');",
     Verdict.NOT_DECLARED),
    ("document.location = '/api/demo/status';", Verdict.UNSCANNED_FORM),
    ("new Worker('/api/demo/status');", Verdict.UNSCANNED_FORM),
    ("open('/api/demo/status');", Verdict.UNSCANNED_FORM),
    ("el.setAttribute('src', '/api/demo/status');", Verdict.UNSCANNED_FORM),
])
def test_a_navigation_form_inside_a_scanned_file_does_not_vanish(
        tmp_path, snippet, expected):
    """走査しているファイルの中でも、走査も申告もされない形があった。"""
    report = _run(tmp_path, f"""
        export default function App(el) {{
          {snippet}
        }}
    """)

    assert expected in _verdicts(report)


@pytest.mark.parametrize("snippet,expected", [
    # `fetch` は SCANNED_FORMS が「走査する」と宣言している当の形。
    ("fetch?.('http://localhost:8000/api/demo/nope');", Verdict.NOT_DECLARED),
    ('return <video poster="/api/demo/nope" />;', Verdict.NOT_DECLARED),
    ("window.location = '/api/demo/status';", Verdict.UNSCANNED_FORM),
    ("top.location = '/api/demo/status';", Verdict.UNSCANNED_FORM),
    ('return <button formAction="/api/demo/status" />;', Verdict.UNSCANNED_FORM),
    ("el.setAttribute('poster', '/api/demo/status');", Verdict.UNSCANNED_FORM),
])
def test_a_url_bearing_form_does_not_vanish(tmp_path, snippet, expected):
    """走査にも unresolved にも unscanned_form にも出ない形を作らない。"""
    report = _run(tmp_path, f"""
        export default function App(el) {{
          {snippet}
        }}
    """)

    assert expected in _verdicts(report), snippet


def test_an_inline_style_url_with_an_expression_is_reported(tmp_path):
    """`url(${BASE}/api/x)` は `url(` の直後が `/api/` ではない。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          return <div style={{ backgroundImage: `url(${API_BASE}/api/demo/status)` }} />;
        }
    """)

    assert Verdict.UNSCANNED_FORM in _verdicts(report)


def test_every_form_in_an_unreachable_file_is_counted(tmp_path):
    """到達不能にすれば消える、を塞ぐ。**走査するすべての形を数える。**

    fetch と WebSocket だけを数えていたので、URL 属性・window.open・
    走査できない形は unreachable にすら計上されず無痕跡で消えていた。
    """
    report = _run(tmp_path, """
        export default function App() { return null; }
    """, extra={"Orphan.jsx": """
        export const O = () => {
          window.open('/api/demo/status');
          axios.get('/api/demo/status');
          return <a href="/api/demo/status">x</a>;
        };
    """})

    assert report.sites == []
    assert len(report.unreachable) >= 3
    assert all("Orphan.jsx" in entry for entry in report.unreachable)


@pytest.mark.parametrize("snippet", [
    "const P = (el, k) => el.setAttribute(k, '/api/demo/nope');",
    "const P = () => Object.assign(window.location, {href: '/api/demo/nope'});",
    "const WS = WebSocket; const P = () => new WS('ws://localhost:8000/api/x');",
    "const api = { get: fetch }; const P = () => api.get('/api/demo/nope');",
    "const [g] = [fetch]; const P = () => g('/api/demo/nope');",
])
def test_the_residual_catches_what_no_detector_matched(tmp_path, snippet):
    """**補集合を無検査にしない。**

    走査する形と走査できない形の2集合だけで閉包を作ると、その補集合は
    常に無検査で痕跡も残らない。残余の受け皿がその構造を閉じる。
    """
    report = _run(tmp_path, f"""
        export default function App() {{ return null; }}
        {snippet}
    """)

    assert Verdict.UNATTRIBUTED in _verdicts(report), snippet


def test_a_base_constant_declaration_is_not_a_residual(tmp_path):
    """`const API_BASE = "http://localhost:8000"` は宣言であって呼び出しではない。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          fetch(`${API_BASE}/api/demo/status`);
        }
    """)

    assert _verdicts(report) == [Verdict.MATCHED]


def test_a_url_inside_a_comment_is_not_judged_as_a_call(tmp_path):
    """コメントは実行されないので**突き合わせない**。

    ただし黙って落としもしない。コメント除去で消えた検出対象は
    comment_masked として出る（11回目の指摘への対応）。
    """
    report = _run(tmp_path, """
        // fetch('/api/demo/nope') はもう使っていない
        /* '/api/demo/nope' も同様 */
        export default function App() { return null; }
    """)

    assert report.mismatched == []
    assert all(s.verdict is Verdict.COMMENT_MASKED for s in report.sites)


def test_a_double_slash_inside_a_url_is_not_a_comment(tmp_path):
    """`"http://localhost:8000"` の `//` をコメント開始と誤読すると、
    以降の引用符の対応が総崩れになる。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          fetch(`${API_BASE}/api/demo/status`);
        }
    """)

    assert _verdicts(report) == [Verdict.MATCHED]


@pytest.mark.parametrize("second_arg", [
    "opts", "buildOpts('POST')", "init || {}",
])
def test_a_method_that_cannot_be_read_is_not_assumed_to_be_get(
        tmp_path, second_arg):
    """**第2引数がオブジェクトリテラルでなければ GET と断定しない。**

    実体が DELETE でも GET の宣言に当たって matched になっていた。
    URL 側は解決できなければ必ず unresolved に落とすのに、
    メソッド側だけ既定値を主張していた。
    """
    report = _run(tmp_path, f"""
        const API_BASE = "http://localhost:8000";
        const opts = {{ method: 'DELETE' }};
        export default function App(init, buildOpts) {{
          fetch(`${{API_BASE}}/api/demo/status`, {second_arg});
        }}
    """)

    assert Verdict.UNRESOLVED_METHOD in _verdicts(report), second_arg


def test_no_second_argument_still_means_get(tmp_path):
    """第2引数が無いときだけが fetch の既定。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          fetch(`${API_BASE}/api/demo/status`);
        }
    """)

    assert report.sites[0].method == "GET"


def test_a_regex_literal_does_not_swallow_the_rest_of_the_line(tmp_path):
    """`/https?:\\/\\//` の `//` をコメント開始と読むと、**同じ行の本物の
    呼び出しまで消える**。コメント除去は正規表現リテラルを識別すること。"""
    report = _run(tmp_path, r"""
        export default function App() {
          const re = /https?:\/\//;
          return fetch('/api/demo/nope', { method: 'POST' });
        }
    """)

    assert Verdict.NOT_DECLARED in _verdicts(report)


def test_a_double_slash_in_jsx_text_does_not_hide_a_call(tmp_path):
    report = _run(tmp_path, """
        export default function App() {
          return <div>see http://example.com</div>;
        }
        const Probe = () => fetch('/api/demo/nope');
    """)

    assert Verdict.NOT_DECLARED in _verdicts(report)


@pytest.mark.parametrize("snippet", [
    "const u = '/api/demo/nope'; const P = () => sink(u);",
    "const tpl = `/api/demo/nope`; const P = () => sink(tpl);",
    "const u = 'http://127.0.0.1:8000/health'; const P = (el) => { el.dataset.x = u; };",
    "const P = () => sink('api/demo/nope');",
    "const P = () => sink('/API/demo/nope');",
])
def test_a_url_that_never_reaches_a_known_sink_is_residual(tmp_path, snippet):
    """宣言を無条件に残余から外すと、変数を1つ挟むだけで消える。

    **解決の過程で実際に引かれた名前の宣言だけ**を残余から外す。
    """
    report = _run(tmp_path, f"""
        export default function App() {{ return null; }}
        {snippet}
    """)

    assert Verdict.UNATTRIBUTED in _verdicts(report), snippet


def test_a_shorthand_method_key_is_not_read_as_get(tmp_path):
    """`{ method }` は値が書かれていない。GET と断定しない。"""
    from backend.ux_verification.ui_api import _resolve_method

    assert _resolve_method("{ method }")[0] is None


def test_a_method_nested_in_the_body_is_not_mistaken_for_the_method():
    """`{ body: JSON.stringify({method:'GET'}), method: 'POST' }` は POST。

    全体検索だと先頭一致の GET を採ってしまう。トップレベルのキーだけ見る。
    """
    from backend.ux_verification.ui_api import _resolve_method

    arg = "{ body: JSON.stringify({method:'GET'}), method: 'POST' }"

    assert _resolve_method(arg)[0] == "POST"


def test_two_top_level_method_keys_are_unresolved():
    from backend.ux_verification.ui_api import _resolve_method

    assert _resolve_method("{ method: 'GET', method: 'POST' }")[0] is None


@pytest.mark.parametrize("before", [
    "const isAbs = (u) => /^https?:\\/\\//.test(u);",
    "function f(u) { return /^https?:\\/\\//.test(u); }",
    "const b = 1 > 2; const r = /a\\/\\/b/;",
    "const c = 2 * 3; const r = /x\\/\\/y/;",
    "const t = typeof /a\\/\\/b/;",
])
def test_a_regex_literal_in_any_context_does_not_swallow_the_line(
        tmp_path, before):
    """許可リストで文脈を数え上げると、必ず数え漏れた文脈で穴が残る。

    除算になり得るのは直前が「値の終わり」のときだけ、と**除外**で書く。
    """
    report = _run(tmp_path, f"""
        {before}
        export default function App() {{
          fetch('/api/demo/nope', {{ method: 'DELETE' }});
        }}
    """)

    assert Verdict.NOT_DECLARED in _verdicts(report), before


def test_a_division_is_not_mistaken_for_a_regex():
    from backend.ux_verification.ui_api import _strip_comments

    stripped = _strip_comments("const r = a / b / c; // 消える")

    assert stripped.startswith("const r = a / b / c;")
    assert "消える" not in stripped


def test_a_declared_route_outside_api_is_judged(tmp_path):
    """backend の判定を `/api` 決め打ちにすると、実在する他のルートが
    解決できているのに黙って捨てられる。**宣言から導く。**"""
    report = _run(tmp_path, """
        export default function App() {
          return <a href="/demo/nope">x</a>;
        }
    """, router_body="""
    from fastapi import APIRouter

    router = APIRouter(prefix="/demo")

    @router.get("/status")
    async def status():
        return {"ok": True}
""")

    assert _verdicts(report) == [Verdict.NOT_DECLARED]


def test_a_same_named_token_elsewhere_does_not_consume_a_declaration(tmp_path):
    """covered 全体から名前を拾うと、第2引数に同名のキーを足すだけで
    宣言が残余から外れる。**URL が書かれる位置だけ**で判断する。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        const endpoint = '/api/demo/nope';
        export default function App() {
          fetch(`${API_BASE}/api/demo/status`, { headers: { endpoint: '1' } });
        }
    """)

    assert Verdict.UNATTRIBUTED in _verdicts(report)


def test_a_react_data_prop_is_not_mistaken_for_an_object_url(tmp_path):
    """`<RadarChart data={...}>` は URL ではない。過検出で FAIL を作らない。"""
    report = _run(tmp_path, """
        export default function App(radarData) {
          return <RadarChart data={radarData} />;
        }
    """)

    assert report.sites == []


def test_a_literal_segment_matches_a_declared_path_parameter(tmp_path):
    """`/entries/abc` は `/entries/{entry_id}` で実際に応答する。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          fetch(`${API_BASE}/api/demo/entries/abc`, { method: 'PUT' });
        }
    """)

    assert _verdicts(report) == [Verdict.MATCHED]


def test_a_placeholder_still_never_matches_a_literal_segment(tmp_path):
    """逆向きは許さない。プレースホルダはリテラルに化けない。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App(name) {
          fetch(`${API_BASE}/api/demo/${name}`);
        }
    """)

    assert _verdicts(report) == [Verdict.NOT_DECLARED]


def test_the_root_mount_is_checked_separately_from_the_version_mount(tmp_path):
    """v1 に載っているだけでは /api/... で呼べない。片方で緑にしない。"""
    app_file = _versioning(tmp_path, """
        from fastapi import APIRouter
        from routers import demo_router

        v1_router = APIRouter(prefix="/api/v1")
        v1_router.include_router(demo_router)
    """)
    routers = _routers(tmp_path, _DEMO_ROUTER)
    app = tmp_path / "backend" / "main.py"
    # v1 だけ載せ、ルート直下には載せない
    app.write_text("app.include_router(v1_router)\n", encoding="utf-8")
    registry = EndpointRegistry.scan(routers, app_files=[app, app_file])
    prefix, modules = _version_mounts(app_file, routers, main_files=[app])
    src = _frontend(tmp_path, """
        export default function App() {
          fetch('http://localhost:8000/api/demo/status');
        }
    """)

    report = UiApiExecutor(src, registry, entry=src / "main.jsx",
                          version_prefix=prefix, version_modules=modules,
                          root_modules=set()).run()

    assert _verdicts(report) == [Verdict.NOT_REGISTERED]


def test_the_report_separates_mismatches_from_unreadable_calls(tmp_path):
    """読めない書き方に逃がすだけで『ゼロ』にできてはいけない。"""
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App(url) {
          fetch(`${API_BASE}/api/demo/nope`);
          fetch(url);
        }
    """)

    assert [s.verdict for s in report.mismatched] == [Verdict.NOT_DECLARED]
    assert [s.verdict for s in report.unresolved] == [Verdict.UNRESOLVED_URL]


def test_an_external_host_is_not_silently_passed(tmp_path):
    report = _run(tmp_path, """
        export default function App() {
          fetch('https://api.example.com/v1/things');
        }
    """)

    assert _verdicts(report) == [Verdict.EXTERNAL_HOST]


# --- バージョン付きマウント ---------------------------------------------------


def _versioning(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "backend" / "api_versioning.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_a_path_under_the_version_prefix_resolves_to_the_remounted_router(tmp_path):
    app_file = _versioning(tmp_path, """
        from fastapi import APIRouter
        from routers import demo_router

        v1_router = APIRouter(prefix="/api/v1")
        v1_router.include_router(demo_router)
    """)
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          fetch(`${API_BASE}/api/v1/api/demo/status`);
        }
    """, app_file=app_file)

    assert _verdicts(report) == [Verdict.MATCHED]


def test_the_version_prefix_does_not_cover_routers_it_never_mounted(tmp_path):
    """prefix を剥がして当たれば通す、にしない。載せていないものは 404。"""
    app_file = _versioning(tmp_path, """
        from fastapi import APIRouter

        v1_router = APIRouter(prefix="/api/v1")
    """)
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          fetch(`${API_BASE}/api/v1/api/demo/status`);
        }
    """, app_file=app_file)

    assert _verdicts(report) == [Verdict.NOT_DECLARED]


def test_the_version_router_must_itself_be_mounted_on_the_app(tmp_path):
    """`app.include_router(v1_router)` を外せば配下は全部 404。緑にしない。"""
    app_file = _versioning(tmp_path, """
        from fastapi import APIRouter
        from routers import demo_router

        v1_router = APIRouter(prefix="/api/v1")
        v1_router.include_router(demo_router)
    """)
    report = _run(tmp_path, """
        const API_BASE = "http://localhost:8000";
        export default function App() {
          fetch(`${API_BASE}/api/v1/api/demo/status`);
        }
    """, app_file=app_file, mount_v1=False)

    assert _verdicts(report) == [Verdict.NOT_DECLARED]


def test_two_version_prefixes_resolve_nothing(tmp_path):
    """v1 と v2 があればどちらに載ったか決まらない。推測して緑にしない。"""
    app_file = _versioning(tmp_path, """
        from fastapi import APIRouter
        from routers import demo_router

        v1_router = APIRouter(prefix="/api/v1")
        v2_router = APIRouter(prefix="/api/v2")
        v1_router.include_router(demo_router)
    """)

    assert _version_mounts(app_file) == ("", set())


# --- 走査そのものを守る -------------------------------------------------------


def test_a_fetch_in_an_unreachable_file_is_reported_not_dropped(tmp_path):
    """到達不能にすればゲートを避けられる、を黙らせない。"""
    report = _run(tmp_path, """
        export default function App() {
          fetch('http://localhost:8000/api/demo/status');
        }
    """, extra={"Orphan.jsx": """
        export function Orphan() {
          fetch('http://localhost:8000/api/demo/nope');
        }
    """})

    assert _verdicts(report) == [Verdict.MATCHED]
    assert len(report.unreachable) == 1
    assert "Orphan.jsx" in report.unreachable[0]


def test_a_frontend_with_no_fetch_yields_no_sites(tmp_path):
    """0件は『問題なし』ではない。CLI 側で exit 1 にするための入力。"""
    report = _run(tmp_path, """
        export default function App() { return null; }
    """)

    assert report.sites == []


def test_the_gate_fails_when_nothing_was_scanned(tmp_path, monkeypatch, capsys):
    from backend.ux_verification import ui_api

    empty = ui_api.UiApiReport(files_scanned=0, endpoints_scanned=0)
    monkeypatch.setattr(ui_api.UiApiExecutor, "for_repo",
                        classmethod(lambda cls: _Stub(empty)))

    assert ui_api.main(["--gate"]) == 1
    assert "1件も読み取れませんでした" in capsys.readouterr().out


class _Stub:
    def __init__(self, report):
        self._report = report

    def run(self):
        return self._report


# --- 網羅を網羅として固定する -------------------------------------------------


def test_every_verdict_declares_what_it_checks_and_what_it_does_not():
    """判定を足して意味を書き忘れる、を禁じる（P3 CLAIM_SEMANTICS と同じ）。"""
    assert set(VERDICT_SEMANTICS) == set(Verdict)
    for verdict, meaning in VERDICT_SEMANTICS.items():
        assert set(meaning) == {"確かめること", "確かめないこと", "PASS"}, verdict
        assert meaning["確かめること"].strip(), verdict
        assert meaning["確かめないこと"].strip(), verdict
        assert meaning["PASS"] in ("yes", "no"), verdict


def test_matched_is_the_only_passing_verdict():
    passing = [v for v, m in VERDICT_SEMANTICS.items() if m["PASS"] == "yes"]

    assert passing == [Verdict.MATCHED]


@pytest.mark.parametrize("verdict", list(Verdict))
def test_no_verdict_passes_without_being_matched(verdict):
    from backend.ux_verification.ui_api import FetchSite

    site = FetchSite("a.jsx", 1, "x", "/api/x", "GET", verdict)

    assert site.passed is (verdict is Verdict.MATCHED)


# --- 単体 ---------------------------------------------------------------------


def test_a_name_assigned_twice_is_not_in_the_environment():
    env = _assignments("const a = 'x';\nlet b = 'y';\nb = 'z';\n")

    assert "a" in env
    assert "b" not in env


def test_the_default_method_is_get():
    assert _resolve_method(None) == ("GET", "")
    assert _resolve_method("{ headers: {} }") == ("GET", "")


def test_an_unknown_name_does_not_resolve():
    url, why = _resolve_url("`${MISSING}/api/x`", {})

    assert url is None
    assert why


# --- gate-verifier 9回目 -------------------------------------------------------


@pytest.mark.parametrize("before", [
    'const ratio = `${a}` / total, doc = "https://example.com/guide";',
    'const q = "10" / 2, u = "https://ex.com/x/y";',
    'const C = ({d, t}) => <span>{d} / {t} <a href="https://ex.com/g">g</a></span>;',
])
def test_a_division_after_a_string_does_not_invert_quote_pairing(
        tmp_path, before):
    """`/` を正規表現の開始と誤読すると、前方走査が次の文字列の開き引用符を
    跨いで対応が反転し、以降の `word//` が行コメントになって呼び出しが消える。
    """
    report = _run(tmp_path, f"""
        const a = 1, total = 2;
        {before}
        const note = "step1//step2";
        export default function App() {{
          fetch('/api/demo/nope', {{ method: 'POST' }});
        }}
    """)

    assert Verdict.NOT_DECLARED in _verdicts(report), before


@pytest.mark.parametrize("second_arg,expected", [
    ("{ 'method': 'DELETE', body: '{}' }", "DELETE"),
    ("{ [\"method\"]: 'POST' }", "POST"),
    ("{ method: 'POST' }", "POST"),
    ("{ headers: {} }", "GET"),
])
def test_the_method_is_read_whatever_the_key_looks_like(second_arg, expected):
    """引用符を付けるだけで既定 GET に落ちるのは fail-open。"""
    from backend.ux_verification.ui_api import _resolve_method

    assert _resolve_method(second_arg)[0] == expected, second_arg


def test_a_relative_url_outside_the_declarations_is_not_dropped(tmp_path):
    """`/reports/export` は backend か決められない。**黙って捨てない。**"""
    report = _run(tmp_path, """
        export default function App() {
          return <a href="/reports/export">x</a>;
        }
    """)

    assert _verdicts(report) == [Verdict.NOT_DECLARED]


def test_a_static_asset_is_still_not_a_backend_call(tmp_path):
    report = _run(tmp_path, """
        export default function App() {
          return <img src="/assets/logo.png" />;
        }
    """)

    assert report.sites == []


def test_an_external_host_in_an_attribute_is_classified_as_external(tmp_path):
    report = _run(tmp_path, """
        export default function App() {
          return <link href="https://fonts.googleapis.com/css2" />;
        }
    """)

    assert _verdicts(report) == [Verdict.EXTERNAL_HOST]


# --- gate-verifier 10回目 ------------------------------------------------------


@pytest.mark.parametrize("before", [
    # 引用符を含む本物の正規表現。除算と読むとその引用符が状態を反転させる。
    'const sanitize = (s) => String(s).replace(/["\']/g, "");',
    r'const re = /https?:\/\//;',
    'const a = 1, t = 2; const r = `${a}` / t;',
    'const C = ({d, t}) => <span>{d} / {t}</span>;',
    'const q = x / y / z;',
])
def test_a_slash_never_hides_a_call_on_the_following_line(tmp_path, before):
    """正規表現か除算かの判定を誤ると、直後の `https://` の `//` が
    行コメントになり、同じ行・次の行の呼び出しが無記録で消える。
    """
    report = _run(tmp_path, f"""
        const x = 1, y = 2, z = 3;
        {before}
        const HELP = "https://docs.example.com/help";
        export default function App() {{
          fetch('/api/demo/nope');
        }}
    """)

    assert Verdict.NOT_DECLARED in _verdicts(report), before


@pytest.mark.parametrize("second_arg,expected", [
    ("{ [`method`]: 'DELETE' }", "DELETE"),
    ("{ ['met' + 'hod']: 'DELETE' }", None),
    ("{ [x]: 1 }", None),
])
def test_a_computed_method_key_is_not_assumed_to_be_get(second_arg, expected):
    """読めない計算キーを GET と断定すると、実在のメソッド違いが PASS になる。"""
    from backend.ux_verification.ui_api import _resolve_method

    assert _resolve_method(second_arg)[0] == expected, second_arg


@pytest.mark.parametrize("name,body", [
    ("probe.svg", '<svg><image href="/api/demo/nope" /></svg>'),
    ("probe.json", '{"api": "/api/demo/nope"}'),
])
def test_a_data_file_carrying_a_backend_url_is_scanned(tmp_path, name, body):
    """`.svg` `.json` は走査対象にも「走査できない形」にも無く、無痕跡だった。"""
    report = _run(tmp_path, """
        export default function App() { return null; }
    """, extra={name: body})

    assert report.sites, name
    assert not any(s.passed for s in report.sites)


def test_a_json_extension_does_not_make_a_path_a_static_asset(tmp_path):
    """`/reports/export.json` は backend の応答かもしれない。資産と断定しない。"""
    report = _run(tmp_path, """
        export default function App() {
          return <a href="/reports/export.json">A</a>;
        }
    """)

    assert _verdicts(report) == [Verdict.NOT_DECLARED]


# --- gate-verifier 11回目 ------------------------------------------------------


def test_a_call_hidden_by_a_comment_misjudgement_is_reported(tmp_path):
    """**判定を誤っても沈黙にならないこと。**

    正規表現か除算かの判別は、まともな JS パーサ無しには堅牢にできない。
    9・10・11回目と3回続けて、この判別の誤りが文字列状態を反転させ
    実在の呼び出しを痕跡なく消していた。判別の精度を上げ続けるのではなく、
    **除去前に見えていて除去後に見えないものを FAIL にする**。
    """
    report = _run(tmp_path, """
        export default function App() {
          const opts = { keep: true }
          /["']/.test(String(opts))
          const glob = "assets/*"
          fetch('/api/demo/nope', { method: 'POST' });
          return glob;
        }
    """)

    masked = [s for s in report.sites if s.verdict is Verdict.COMMENT_MASKED]
    assert masked, "判定ミスで消えた呼び出しが報告されていない"
    assert not any(s.passed for s in report.sites)


def test_a_commented_out_call_is_reported_not_silently_dropped(tmp_path):
    """コメントアウトされた呼び出しも FAIL に出る。

    「本当にコメント」と「判定ミス」を区別せずに扱う。区別しようとした
    結果が3回分の穴だった。数は増えるが、増えた分は本当のこと。
    """
    report = _run(tmp_path, """
        // fetch('/api/demo/nope') はもう使っていない
        export default function App() { return null; }
    """)

    assert Verdict.COMMENT_MASKED in _verdicts(report)


def test_comment_masked_is_not_a_passing_verdict():
    assert VERDICT_SEMANTICS[Verdict.COMMENT_MASKED]["PASS"] == "no"


# --- gate-verifier 12回目 ------------------------------------------------------


def test_an_apostrophe_in_jsx_text_does_not_hide_a_url(tmp_path):
    """JSX テキストの `Don't` の `'` が文字列状態を開き、直後の
    `'http://…'` の**開き**引用符で閉じると、`http:` の後の `//` が
    行コメントになって行ごと消える（12回目の指摘）。

    スキームの `//` を行コメントと読まないことで、文字列状態の判定を
    誤っても呼び出しが消えない。
    """
    report = _run(tmp_path, """
        export default function App() {
          const label = <p>Don't stop</p>;
          const u = 'http://localhost:8000/api/demo/nope';
          const img = new Image();
          img.src = u;
          return label;
        }
    """)

    assert report.sites, "呼び出しが1件も出ていない"
    assert not any(s.passed for s in report.sites)


def test_a_url_assigned_to_a_dom_property_from_a_variable_is_detected(tmp_path):
    """`img.src = u` は右辺が変数なので検出器に当たらず、残余が消えると
    _masked_away も発火しなかった。右辺を問わず検出する。"""
    report = _run(tmp_path, """
        export default function App(form) {
          const u = '/api/demo/nope';
          form.action = u;
          return null;
        }
    """)

    assert Verdict.UNSCANNED_FORM in _verdicts(report)


_TRAILING_SLASH_BASE = (
    "const B = 'http://localhost:8000/';\n"
    "export default function App() { fetch(`${B}/api/demo/status`); }")
_DOUBLE_SLASH_PATH = (
    "export default function App() { fetch('/api//demo/status'); }")
_CLEAN_BASE = (
    "const B = 'http://localhost:8000';\n"
    "export default function App() { fetch(`${B}/api/demo/status`); }")


@pytest.mark.parametrize("source,expected", [
    (_TRAILING_SLASH_BASE, Verdict.NOT_DECLARED),
    (_DOUBLE_SLASH_PATH, Verdict.NOT_DECLARED),
    (_CLEAN_BASE, Verdict.MATCHED),
])
def test_duplicate_slashes_are_not_collapsed_on_the_frontend_side(
        tmp_path, source, expected):
    """`//api/x` は実行時 404。宣言側の正規化をフロントの生パスに当てると
    404 になるパスが matched になる（FastAPI で 404 を実測済み）。"""
    report = _run(tmp_path, source)

    assert _verdicts(report) == [expected], source


# --- gate-verifier 13回目 ------------------------------------------------------


def test_a_scheme_slash_is_never_read_as_a_line_comment():
    """`http://` の `//` を行コメントと読まない砦。

    12回目に入れたと報告したが**実際には入っていなかった**（置換が無言で
    失敗し、差分で確かめずに完了を報告した）。ここで固定する。
    """
    from backend.ux_verification.ui_api import _strip_comments

    stripped = _strip_comments(
        "<p>Don't</p>\nconst a = 'http://localhost:8000/api/demo/status';")

    assert "/api/demo/status" in stripped


@pytest.mark.parametrize("text", ["Don't forget", "Dont forget"])
def test_an_apostrophe_does_not_change_whether_a_call_is_seen(tmp_path, text):
    """アポストロフィ1文字の有無で FAIL → 沈黙 に変わってはいけない。"""
    report = _run(tmp_path, f"""
        export default function App() {{
          const label = <p>{text}</p>;
          window.open('http://localhost:8000/api/demo/nope');
          return label;
        }}
    """)

    assert _verdicts(report) == [Verdict.NOT_DECLARED], text


def test_an_unclosed_url_attribute_is_reported_not_skipped(tmp_path):
    """fetch 分岐は括弧が閉じないとき unresolved_url を出すのに、
    URL 属性と window.open だけ**黙って continue** していた。"""
    from backend.ux_verification.ui_api import UiApiExecutor

    routers = _routers(tmp_path, _DEMO_ROUTER)
    app = tmp_path / "backend" / "main.py"
    app.write_text("from routers import demo_router\n"
                   "app.include_router(demo_router)\n", encoding="utf-8")
    src = _frontend(tmp_path, "export default function App() { return null; }")
    (src / "broken.jsx").write_text("window.open('/api/demo/nope'\n",
                                    encoding="utf-8")
    (src / "App.jsx").write_text(
        "import './broken.jsx';\nexport default function App() { return null; }",
        encoding="utf-8")

    report = UiApiExecutor(src, EndpointRegistry.scan(routers, app_files=[app]),
                           entry=src / "main.jsx").run()

    assert Verdict.UNRESOLVED_URL in _verdicts(report)


def test_a_react_data_prop_assignment_is_not_a_url(tmp_path):
    """`chart.data = [...]` は URL ではない。過検出で FAIL を作らない。"""
    report = _run(tmp_path, """
        export default function App(chart) {
          chart.data = [1, 2, 3];
          return null;
        }
    """)

    assert report.sites == []


# --- 呼び出し口とカタログ（P5 C-2） -------------------------------------------
#
# **主眼は「カタログを緑にできないこと」。** カタログ専用の甘い判定を作れば、
# そこが唯一の抜け道になる。通常の呼び出しとまったく同じ `_judge` を通ること、
# 文法から外れた書き方が項目にならないこと、呼び出し口を import しなくても
# 判定が消えないことを固定する。


_CATALOGUE_HEAD = "export const ENDPOINTS = {\n"


def _with_catalogue(tmp_path: Path, entries: str, *, source: str = "",
                    client: str = "", extra: dict | None = None):
    """カタログを置いた frontend で走らせる。"""
    files = dict(extra or {})
    files["api/endpoints.js"] = _CATALOGUE_HEAD + entries + "};\n"
    if client:
        files["api/client.js"] = client
    return _run(tmp_path, source or "export default function App() { return null; }",
                extra=files)


def _catalogue_sites(report):
    return [s for s in report.sites if s.file.endswith("api/endpoints.js")]


def test_a_catalogue_entry_is_matched_like_any_other_call(tmp_path):
    report = _with_catalogue(
        tmp_path, "  getStatus: { method: 'GET', path: '/api/demo/status' },\n")

    sites = _catalogue_sites(report)
    assert [s.verdict for s in sites] == [Verdict.MATCHED]
    assert (sites[0].method, sites[0].path) == ("GET", "/api/demo/status")


def test_a_catalogue_entry_for_an_undeclared_path_fails_the_gate(tmp_path):
    """**カタログに書けば通る、にしない。** 宣言が無ければ突き合わない。"""
    report = _with_catalogue(
        tmp_path, "  getGhost: { method: 'GET', path: '/api/demo/ghost' },\n")

    assert [s.verdict for s in _catalogue_sites(report)] == [Verdict.NOT_DECLARED]
    assert report.mismatched


def test_a_catalogue_entry_with_the_wrong_method_fails_the_gate(tmp_path):
    report = _with_catalogue(
        tmp_path, "  postStatus: { method: 'POST', path: '/api/demo/status' },\n")

    assert [s.verdict for s in _catalogue_sites(report)] == [Verdict.METHOD_MISMATCH]
    assert report.mismatched


def test_a_catalogue_path_placeholder_matches_a_declared_parameter(tmp_path):
    report = _with_catalogue(
        tmp_path,
        "  putEntry: { method: 'PUT', path: '/api/demo/entries/{entry_id}' },\n")

    assert [s.verdict for s in _catalogue_sites(report)] == [Verdict.MATCHED]


@pytest.mark.parametrize("entry", [
    # 変数経由。カタログが「叩ける先の全部」でなくなる書き方。
    "  getStatus: { method: 'GET', path: PATH },\n",
    # 連結。
    "  getStatus: { method: 'GET', path: '/api/demo' + '/status' },\n",
    # テンプレートリテラル。
    "  getStatus: { method: 'GET', path: `/api/demo/status` },\n",
    # ダブルクォート。閉じた文法はシングルクォートだけ。
    '  getStatus: { method: "GET", path: "/api/demo/status" },\n',
    # 1行に2項目。行単位の列挙から片方が消える書き方。
    ("  a: { method: 'GET', path: '/api/demo/status' }, b: { method: 'GET', "
     "path: '/api/demo/status' },\n"),
])
def test_a_catalogue_entry_outside_the_closed_grammar_is_not_an_entry(tmp_path, entry):
    """**文法から外れた行を項目にしない。**

    項目にならなかった行に URL リテラルがあれば残余（unattributed）が拾う。
    リテラルすら無い形（変数経由）はここでは見えず、ui_api_closure の C-2 が落とす。
    どちらにせよ **matched には決してならない。**
    """
    report = _with_catalogue(tmp_path, entry)

    assert Verdict.MATCHED not in [s.verdict for s in _catalogue_sites(report)]


def test_a_catalogue_line_that_is_not_an_entry_still_shows_its_url(tmp_path):
    """残余の受け皿はカタログにも掛かる。"""
    report = _with_catalogue(
        tmp_path, "  getStatus: { method: 'GET', path: '/api/demo' + '/status' },\n")

    assert Verdict.UNATTRIBUTED in [s.verdict for s in _catalogue_sites(report)]


def test_the_catalogue_is_scanned_even_when_nothing_imports_it(tmp_path):
    """**呼び出し口は常に走査する。**

    到達可能性の対象にすると、`import` を1行消すだけで
    「叩ける先の全部」が判定から丸ごと消える。
    """
    report = _with_catalogue(
        tmp_path, "  getGhost: { method: 'GET', path: '/api/demo/ghost' },\n")

    # App.jsx はカタログを import していない。それでも判定されている。
    assert _catalogue_sites(report)
    assert report.mismatched


def test_a_dispatch_inside_the_gateway_is_not_an_unresolved_url(tmp_path):
    report = _with_catalogue(
        tmp_path, "  getStatus: { method: 'GET', path: '/api/demo/status' },\n",
        client="export function go(name) { return fetch(apiUrl(name)); }\n")

    dispatch = [s for s in report.sites if s.file.endswith("api/client.js")]
    assert [s.verdict for s in dispatch] == [Verdict.GATEWAY_DISPATCH]
    assert dispatch[0].passed is False


def test_gateway_dispatch_never_applies_outside_the_gateway(tmp_path):
    """**閉包の外でこの札を付けない。** 付けば「読めない＝問題なし」に戻る。"""
    report = _run(tmp_path, """
        export default function App(name) {
          fetch(apiUrl(name));
        }
    """)

    assert _verdicts(report) == [Verdict.UNRESOLVED_URL]


def test_a_bare_origin_in_the_gateway_is_not_residual(tmp_path):
    """ベース URL の宣言は呼び出しではない。パスが付けば呼び出しになる。"""
    report = _with_catalogue(
        tmp_path, "  getStatus: { method: 'GET', path: '/api/demo/status' },\n",
        client="const ORIGIN = 'http://localhost:8000';\nexport default ORIGIN;\n")

    assert [s for s in report.sites if s.file.endswith("api/client.js")] == []


def test_an_origin_with_a_path_in_the_gateway_is_residual(tmp_path):
    """**呼び出し口を第2のカタログにしない。** パス付きのリテラルは残余に落ちる。"""
    report = _with_catalogue(
        tmp_path, "  getStatus: { method: 'GET', path: '/api/demo/status' },\n",
        client="const ORIGIN = 'http://localhost:8000/api/demo/ghost';\n"
               "export default ORIGIN;\n")

    inside = [s for s in report.sites if s.file.endswith("api/client.js")]
    assert [s.verdict for s in inside] == [Verdict.UNATTRIBUTED]


def test_a_relative_import_specifier_is_not_a_backend_url(tmp_path):
    """**呼び出し口を import する行を残余で誤検出しない。**

    呼び出し口は `src/api/` にあるので、それを import する行はすべて
    `/api/` を含む。ここを外さないと、移行したファイル1つにつき
    unattributed が1件ずつ増える（実測で見つけた）。
    """
    report = _with_catalogue(
        tmp_path, "  getStatus: { method: 'GET', path: '/api/demo/status' },\n",
        source="""
            import { apiFetch } from '../api/client.js';
            export default function App() { return apiFetch('getStatus'); }
        """,
        client="export function apiFetch(name) { return fetch(apiUrl(name)); }\n")

    assert [s for s in report.sites if s.file.endswith("App.jsx")] == []


def test_an_absolute_specifier_after_from_is_still_residual(tmp_path):
    """**外すのは相対指定子だけ。** `from '/api/x'` は黙って消さない。"""
    report = _run(tmp_path, """
        import thing from '/api/demo/status';
        export default function App() { return thing; }
    """)

    assert _verdicts(report) == [Verdict.UNATTRIBUTED]
