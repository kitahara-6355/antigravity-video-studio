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
        (src / name).write_text(textwrap.dedent(text), encoding="utf-8")
    return src


def _run(tmp_path: Path, source: str, *, router_body: str = _DEMO_ROUTER,
         app_file: Path | None = None, extra: dict | None = None):
    routers = _routers(tmp_path, router_body)
    app = tmp_path / "backend" / "main.py"
    app.write_text(
        "from routers import demo_router\n"
        "app.include_router(demo_router)\n", encoding="utf-8")
    registry = EndpointRegistry.scan(routers, app_files=[app])
    prefix, modules = (_version_mounts(app_file, routers) if app_file
                       else ("", set()))
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

    assert _verdicts(report) == [Verdict.UNRESOLVED_URL]


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
