"""API 契約（エンドポイント実在）の実行系のテスト。

L1 の 86項目は `dom_exists` と宣言されているが、実際は
「○○APIが正常応答を返す」「statusフィールドが存在する」という
**API・データ契約の主張**だった。DOM 存在では原理的に判定できない。

ここでは FastAPI のルーター定義を静的に走査して、宣言された
エンドポイントが実在し、かつアプリに登録されているかを判定する。
サーバは起動しないので無料で、CI でそのまま回る。
"""
import textwrap

import pytest

from backend.ux_verification.api_contract import (
    ApiContractExecutor,
    EndpointRegistry,
    Verdict,
)


def _write(root, rel, body):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return path


# --- レジストリ: ルーター定義からエンドポイントを拾う ------------------------


def test_registry_joins_prefix_and_path(tmp_path):
    _write(tmp_path, "routers/quota.py", """
        router = APIRouter(prefix="/api/admin/quota", tags=["Quota"])

        @router.get("/status")
        async def get_status():
            return {"ok": True}
    """)
    reg = EndpointRegistry.scan(tmp_path / "routers")

    site = reg.resolve("/api/admin/quota/status")

    assert site is not None
    assert site.method == "GET"
    assert site.file.endswith("quota.py")


def test_registry_records_the_http_method(tmp_path):
    _write(tmp_path, "routers/x.py", """
        router = APIRouter(prefix="/api/x")

        @router.post("/create")
        def create():
            return {}
    """)
    reg = EndpointRegistry.scan(tmp_path / "routers")

    assert reg.resolve("/api/x/create", method="POST") is not None
    assert reg.resolve("/api/x/create", method="GET") is None


def test_registry_handles_router_without_prefix(tmp_path):
    _write(tmp_path, "routers/bare.py", """
        router = APIRouter()

        @router.get("/health")
        def health():
            return {}
    """)
    reg = EndpointRegistry.scan(tmp_path / "routers")

    assert reg.resolve("/health") is not None


def test_registry_normalises_double_slashes(tmp_path):
    _write(tmp_path, "routers/x.py", """
        router = APIRouter(prefix="/api/x/")

        @router.get("/y")
        def y():
            return {}
    """)
    reg = EndpointRegistry.scan(tmp_path / "routers")

    assert reg.resolve("/api/x/y") is not None


def test_registry_keeps_path_parameters(tmp_path):
    _write(tmp_path, "routers/x.py", """
        router = APIRouter(prefix="/api/x")

        @router.get("/{item_id}")
        def one(item_id: str):
            return {}
    """)
    reg = EndpointRegistry.scan(tmp_path / "routers")

    assert reg.resolve("/api/x/{item_id}") is not None


def test_registry_ignores_non_router_decorators(tmp_path):
    _write(tmp_path, "routers/x.py", """
        router = APIRouter(prefix="/api/x")

        @functools.lru_cache()
        def helper():
            return {}
    """)
    reg = EndpointRegistry.scan(tmp_path / "routers")

    assert reg.endpoints == {}


def test_registry_survives_a_file_it_cannot_parse(tmp_path):
    """1ファイルが壊れていても、残りの走査を諦めない。"""
    _write(tmp_path, "routers/broken.py", "def (((")
    _write(tmp_path, "routers/ok.py", """
        router = APIRouter(prefix="/api/ok")

        @router.get("/x")
        def x():
            return {}
    """)
    reg = EndpointRegistry.scan(tmp_path / "routers")

    assert reg.resolve("/api/ok/x") is not None
    assert "broken.py" in reg.unparsable[0]


# --- 登録: アプリに include されていないルーターを PASS にしない --------------


def _package(tmp_path, init_body, app_body):
    _write(tmp_path, "routers/__init__.py", init_body)
    _write(tmp_path, "main.py", app_body)


def test_endpoint_of_an_unregistered_router_is_marked(tmp_path):
    _write(tmp_path, "routers/live.py", """
        router = APIRouter(prefix="/api/live")

        @router.get("/a")
        def a():
            return {}
    """)
    _write(tmp_path, "routers/dead.py", """
        router = APIRouter(prefix="/api/dead")

        @router.get("/b")
        def b():
            return {}
    """)
    _package(
        tmp_path,
        "from .live import router as live_router\n"
        "from .dead import router as dead_router\n",
        "app.include_router(live_router)\n",
    )

    reg = EndpointRegistry.scan(tmp_path / "routers", app_files=[tmp_path / "main.py"])

    assert reg.resolve("/api/live/a").registered is True
    assert reg.resolve("/api/dead/b").registered is False


def test_registration_is_unknown_without_app_files(tmp_path):
    """アプリ定義を渡さなければ、全部 True 扱いにはしない。"""
    _write(tmp_path, "routers/x.py", """
        router = APIRouter(prefix="/api/x")

        @router.get("/y")
        def y():
            return {}
    """)
    reg = EndpointRegistry.scan(tmp_path / "routers")

    assert reg.resolve("/api/x/y").registered is None


# --- 判定 --------------------------------------------------------------------


@pytest.fixture
def registry(tmp_path):
    _write(tmp_path, "routers/live.py", """
        router = APIRouter(prefix="/api/live")

        @router.get("/status")
        def status():
            return {}
    """)
    _write(tmp_path, "routers/dead.py", """
        router = APIRouter(prefix="/api/dead")

        @router.get("/b")
        def b():
            return {}
    """)
    _package(
        tmp_path,
        "from .live import router as live_router\n"
        "from .dead import router as dead_router\n",
        "app.include_router(live_router)\n",
    )
    return EndpointRegistry.scan(
        tmp_path / "routers", app_files=[tmp_path / "main.py"]
    )


def _item(item_id, **kw):
    base = {"id": item_id, "layer": 1, "test_method": "api_contract",
            "story_scene": "S1", "description": item_id}
    base.update(kw)
    return base


def test_passes_when_endpoint_exists_and_is_registered(registry):
    result = ApiContractExecutor(registry).judge(
        "O-4", _item("O4-L1-01", endpoint="GET /api/live/status")
    )

    assert result.verdict is Verdict.PASS
    assert result.reason == "found"
    assert "live.py" in result.evidence


def test_fails_when_endpoint_does_not_exist(registry):
    result = ApiContractExecutor(registry).judge(
        "O-4", _item("O4-L1-01", endpoint="GET /api/nope")
    )

    assert result.verdict is Verdict.FAIL
    assert result.reason == "not_found"


def test_fails_when_router_is_not_registered(registry):
    """定義があってもアプリに include されていなければ、呼んでも 404。"""
    result = ApiContractExecutor(registry).judge(
        "O-4", _item("O4-L1-01", endpoint="GET /api/dead/b")
    )

    assert result.verdict is Verdict.FAIL
    assert result.reason == "unregistered"


def test_fails_when_the_item_declares_no_endpoint(registry):
    """照合先が無いなら保証されていない。SKIP には逃がさない。"""
    result = ApiContractExecutor(registry).judge("O-4", _item("O4-L1-01"))

    assert result.verdict is Verdict.FAIL
    assert result.reason == "no_endpoint"


def test_method_defaults_to_get_when_omitted(registry):
    result = ApiContractExecutor(registry).judge(
        "O-4", _item("O4-L1-01", endpoint="/api/live/status")
    )

    assert result.verdict is Verdict.PASS


def test_wrong_method_is_not_found(registry):
    result = ApiContractExecutor(registry).judge(
        "O-4", _item("O4-L1-01", endpoint="POST /api/live/status")
    )

    assert result.verdict is Verdict.FAIL
    assert result.reason == "not_found"


def test_every_result_carries_evidence(registry):
    ex = ApiContractExecutor(registry)
    for item in (_item("a", endpoint="GET /api/live/status"),
                 _item("b", endpoint="GET /api/nope"),
                 _item("c")):
        assert len(ex.judge("O-4", item).evidence.strip()) >= 5


def test_evidence_states_the_method_is_static(registry):
    result = ApiContractExecutor(registry).judge(
        "O-4", _item("O4-L1-01", endpoint="GET /api/live/status")
    )

    assert "static_route_scan" in result.evidence


# --- 実データ ----------------------------------------------------------------


def test_real_repo_registry_finds_the_routers():
    reg = EndpointRegistry.for_repo()

    assert reg.files_scanned >= 30
    assert len(reg.endpoints) >= 400
    assert reg.unparsable == []


def test_real_repo_marks_registration():
    """登録判定が実際に効いていること（全件 True の空判定になっていない）。"""
    reg = EndpointRegistry.for_repo()
    states = {s.registered for s in reg.endpoints.values()}

    assert True in states, "登録済みと判定されたエンドポイントが1つも無い"
    assert None not in states, "アプリ定義が読めていない"


# --- L1 実行系との振り分け ----------------------------------------------------


def test_l1_executor_routes_endpoint_items_to_the_contract_judge(tmp_path):
    """testid が無く endpoint がある項目は API 契約側で判定される。"""
    import json as _json

    from backend.ux_verification.executor import L1Executor
    from backend.ux_verification.executor import Verdict as L1Verdict

    _write(tmp_path, "routers/live.py", """
        router = APIRouter(prefix="/api/live")

        @router.get("/status")
        def status():
            return {}
    """)
    _write(tmp_path, "routers/__init__.py",
           "from .live import router as live_router\n")
    _write(tmp_path, "main.py", "app.include_router(live_router)\n")
    _write(tmp_path, "fe/src/main.jsx", "import App from './App.jsx'")
    _write(tmp_path, "fe/src/App.jsx", '<div data-testid="present" />')

    stories = tmp_path / "stories"
    stories.mkdir()
    (stories / "o4.json").write_text(_json.dumps({
        "ux_id": "O-4",
        "verification_items": [
            {"id": "O4-L1-01", "layer": 1, "test_method": "dom_exists",
             "story_scene": "S1", "description": "API",
             "endpoint": "GET /api/live/status"},
            {"id": "O4-L1-02", "layer": 1, "test_method": "dom_exists",
             "story_scene": "S1", "description": "DOM", "testid": "present"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    registry = EndpointRegistry.scan(tmp_path / "routers",
                                     app_files=[tmp_path / "main.py"])
    report = L1Executor(stories, tmp_path / "fe" / "src",
                        contract=ApiContractExecutor(registry)).run("owner")

    by_id = {r.item_id: r for r in report.results}
    assert by_id["O4-L1-01"].verdict is L1Verdict.PASS
    assert "static_route_scan" in by_id["O4-L1-01"].evidence
    assert by_id["O4-L1-02"].verdict is L1Verdict.PASS
    assert "static_source_scan" in by_id["O4-L1-02"].evidence


def test_testid_wins_when_an_item_declares_both(tmp_path):
    """両方あるときは DOM 側で判定する（endpoint への逃げ道を作らない）。"""
    import json as _json

    from backend.ux_verification.executor import L1Executor
    from backend.ux_verification.executor import Verdict as L1Verdict

    _write(tmp_path, "routers/live.py", """
        router = APIRouter(prefix="/api/live")

        @router.get("/status")
        def status():
            return {}
    """)
    _write(tmp_path, "routers/__init__.py",
           "from .live import router as live_router\n")
    _write(tmp_path, "main.py", "app.include_router(live_router)\n")
    _write(tmp_path, "fe/src/main.jsx", "import App from './App.jsx'")
    _write(tmp_path, "fe/src/App.jsx", "export default function App(){return null}")

    stories = tmp_path / "stories"
    stories.mkdir()
    (stories / "o4.json").write_text(_json.dumps({
        "ux_id": "O-4",
        "verification_items": [
            {"id": "O4-L1-01", "layer": 1, "test_method": "dom_exists",
             "story_scene": "S1", "description": "both",
             "testid": "absent", "endpoint": "GET /api/live/status"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    registry = EndpointRegistry.scan(tmp_path / "routers",
                                     app_files=[tmp_path / "main.py"])
    report = L1Executor(stories, tmp_path / "fe" / "src",
                        contract=ApiContractExecutor(registry)).run("owner")

    assert report.results[0].verdict is L1Verdict.FAIL
    assert report.results[0].reason == "not_found"


def test_real_owner_l1_still_has_no_skip():
    from backend.ux_verification.executor import L1Executor

    report = L1Executor.for_repo().run("owner")

    assert report.total == 122
    assert report.skip_count == 0
    assert report.pass_count >= 115
