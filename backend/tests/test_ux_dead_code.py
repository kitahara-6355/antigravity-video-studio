"""死蔵コードの棚卸しとラチェット（P2 C-5）のテスト。

判定そのものより **計測器が壊れたときに黙って緑にならないこと** を重く見る。
到達可能性の判定は「エントリから import を辿る」ので、エントリを見失うと
全ファイルが到達不能になり、逆に走査対象を見失うと死蔵ゼロになる。
どちらも「実測した結果」の顔をして出てくるため、明示的に落とす。
"""
from __future__ import annotations

import json

import pytest

from backend.ux_verification.dead_code import (
    DeadCodeInventory,
    DeadCodeRatchet,
    load_baseline,
    write_baseline,
)

# --- 足場 --------------------------------------------------------------------


def _routers(tmp_path, *, registered: list[str], orphaned: list[str]):
    """routers/ と main.py を作る。orphaned は __init__.py に載せない。"""
    backend = tmp_path / "backend"
    routers = backend / "routers"
    routers.mkdir(parents=True)

    for module in registered + orphaned:
        (routers / f"{module}.py").write_text(
            "from fastapi import APIRouter\n"
            f'router = APIRouter(prefix="/api/{module}")\n'
            '@router.get("/items")\n'
            "def list_items():\n"
            '    return {"items": []}\n',
            encoding="utf-8",
        )

    init_lines = [
        f"from .{m} import router as {m}_router" for m in registered
    ]
    (routers / "__init__.py").write_text("\n".join(init_lines) + "\n", encoding="utf-8")

    include = [f"    app.include_router({m}_router)" for m in registered]
    (backend / "main.py").write_text(
        "def build():\n" + "\n".join(include or ["    pass"]) + "\n",
        encoding="utf-8",
    )
    return routers, [backend / "main.py"]


def _frontend(tmp_path, *, reachable: list[str], orphaned: list[str]):
    """src/main.jsx から import で辿れるファイルと、辿れないファイルを作る。"""
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)

    imports = [f"import './{name}';" for name in reachable]
    (src / "main.jsx").write_text("\n".join(imports) + "\n", encoding="utf-8")

    for name in reachable + orphaned:
        path = src / f"{name}.jsx"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"export default function {path.stem}() {{ return null; }}\n",
                        encoding="utf-8")
    return src, src / "main.jsx"


def _collect(tmp_path, *, registered=("live",), orphaned_routers=("ghost",),
             reachable=("App",), orphaned_components=("Ghost",)):
    routers, app_files = _routers(
        tmp_path, registered=list(registered), orphaned=list(orphaned_routers)
    )
    src, entry = _frontend(
        tmp_path, reachable=list(reachable), orphaned=list(orphaned_components)
    )
    return DeadCodeInventory.collect(
        routers_dir=routers, app_files=app_files,
        frontend_src=src, entry=entry, project_root=tmp_path,
    )


# --- 棚卸し ------------------------------------------------------------------


def test_未登録ルーターのエンドポイントを死蔵として挙げる(tmp_path):
    inv = _collect(tmp_path)
    assert [e.key for e in inv.endpoints] == ["GET /api/ghost/items"]


def test_登録済みルーターは死蔵に含めない(tmp_path):
    inv = _collect(tmp_path, orphaned_routers=())
    assert inv.endpoints == []


def test_エントリから辿れないコンポーネントを死蔵として挙げる(tmp_path):
    inv = _collect(tmp_path)
    assert [c.key for c in inv.components] == ["frontend/src/Ghost.jsx"]


def test_エントリ自身は死蔵にならない(tmp_path):
    inv = _collect(tmp_path, orphaned_components=())
    assert inv.components == []


def test_走査した総数も持ち帰る(tmp_path):
    inv = _collect(tmp_path)
    # live + ghost = 2 エンドポイント / main.jsx + App + Ghost = 3 ファイル
    assert inv.endpoints_scanned == 2
    assert inv.components_scanned == 3


# --- 計測器の自己防衛 ---------------------------------------------------------


def test_エントリが無ければコンポーネントを死蔵と言わない(tmp_path):
    """エントリを見失うと全ファイルが到達不能になる。ゼロ件と嘘をつくのも同罪。"""
    routers, app_files = _routers(tmp_path, registered=["live"], orphaned=[])
    src, _ = _frontend(tmp_path, reachable=["App"], orphaned=["Ghost"])

    inv = DeadCodeInventory.collect(
        routers_dir=routers, app_files=app_files,
        frontend_src=src, entry=src / "does_not_exist.jsx", project_root=tmp_path,
    )
    assert inv.entry_missing is True
    assert inv.components == []


def test_エントリが無ければラチェットは緑にならない(tmp_path):
    routers, app_files = _routers(tmp_path, registered=["live"], orphaned=[])
    src, _ = _frontend(tmp_path, reachable=["App"], orphaned=["Ghost"])
    inv = DeadCodeInventory.collect(
        routers_dir=routers, app_files=app_files,
        frontend_src=src, entry=src / "does_not_exist.jsx", project_root=tmp_path,
    )
    result = DeadCodeRatchet().check(inv, {"endpoints": [], "components": []})
    assert result.valid is False
    assert "エントリ" in result.to_text()


def test_ルーターを走査できなければラチェットは緑にならない(tmp_path):
    """走査対象を見失うと死蔵ゼロになる。「改善した」と読めてしまう。"""
    src, entry = _frontend(tmp_path, reachable=["App"], orphaned=[])
    inv = DeadCodeInventory.collect(
        routers_dir=tmp_path / "no_such_dir", app_files=[],
        frontend_src=src, entry=entry, project_root=tmp_path,
    )
    assert inv.routers_missing is True
    result = DeadCodeRatchet().check(inv, {"endpoints": [], "components": []})
    assert result.valid is False


def test_登録状況を判定できなければ未登録と決めつけない(tmp_path):
    """app_files を渡さなければ registered は None。全件を死蔵にしてはいけない。"""
    routers, _ = _routers(tmp_path, registered=["live"], orphaned=["ghost"])
    src, entry = _frontend(tmp_path, reachable=["App"], orphaned=[])
    inv = DeadCodeInventory.collect(
        routers_dir=routers, app_files=[],
        frontend_src=src, entry=entry, project_root=tmp_path,
    )
    assert inv.endpoints == []
    assert inv.registration_unknown is True


# --- ラチェット --------------------------------------------------------------


def test_死蔵が増えたら違反(tmp_path):
    inv = _collect(tmp_path)
    baseline = {"endpoints": [], "components": []}
    result = DeadCodeRatchet().check(inv, baseline)
    assert result.valid is False
    assert len(result.violations) == 2


def test_死蔵が同じなら通る(tmp_path):
    inv = _collect(tmp_path)
    baseline = {
        "endpoints": ["GET /api/ghost/items"],
        "components": ["frontend/src/Ghost.jsx"],
    }
    assert DeadCodeRatchet().check(inv, baseline).valid is True


def test_死蔵が減れば改善として報告する(tmp_path):
    inv = _collect(tmp_path, orphaned_routers=(), orphaned_components=())
    baseline = {
        "endpoints": ["GET /api/ghost/items"],
        "components": ["frontend/src/Ghost.jsx"],
    }
    result = DeadCodeRatchet().check(inv, baseline)
    assert result.valid is True
    assert sorted(result.removed) == [
        "GET /api/ghost/items", "frontend/src/Ghost.jsx",
    ]


def test_件数が同じでも中身が入れ替われば違反(tmp_path):
    """集計値で見ると見逃す。1件消えて別の1件が死蔵化しても総数は動かない。"""
    inv = _collect(tmp_path)
    baseline = {
        "endpoints": ["GET /api/other/items"],
        "components": ["frontend/src/Other.jsx"],
    }
    result = DeadCodeRatchet().check(inv, baseline)
    assert result.valid is False


def test_ベースラインが無ければ緑にしない(tmp_path):
    """ファイルを消すだけでラチェットを無効化できてはいけない。"""
    inv = _collect(tmp_path)
    result = DeadCodeRatchet().check(inv, None)
    assert result.valid is False
    assert result.baseline_missing is True


# --- ベースラインの入出力 -----------------------------------------------------


def test_ベースラインを書いて読み戻せる(tmp_path):
    inv = _collect(tmp_path)
    path = write_baseline(inv, tmp_path / "dead_code_baseline.json")
    loaded = load_baseline(path)
    assert loaded["endpoints"] == ["GET /api/ghost/items"]
    assert loaded["components"] == ["frontend/src/Ghost.jsx"]


def test_ベースラインに時刻を入れない(tmp_path):
    """毎回書き換わる欄があると、実質的な変化が差分に埋もれる。"""
    path = write_baseline(_collect(tmp_path), tmp_path / "b.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert not any("date" in k or "time" in k for k in payload)


def test_増えたまま締め直せない(tmp_path):
    """死蔵が増えたまま --update すれば、増えたことが無かったことになる。"""
    inv = _collect(tmp_path)
    path = write_baseline(
        DeadCodeInventory(endpoints=[], components=[]), tmp_path / "b.json"
    )
    with pytest.raises(ValueError):
        DeadCodeRatchet().update(inv, path)


def test_減った分は締め直せる(tmp_path):
    inv = _collect(tmp_path, orphaned_routers=(), orphaned_components=())
    path = tmp_path / "b.json"
    path.write_text(json.dumps({
        "endpoints": ["GET /api/ghost/items"],
        "components": ["frontend/src/Ghost.jsx"],
    }), encoding="utf-8")
    DeadCodeRatchet().update(inv, path)
    assert load_baseline(path) == {"endpoints": [], "components": []}


def test_ベースラインが未作成なら初回作成できる(tmp_path):
    """初回だけは突き合わせる相手がいない。ここで拒むと作れなくなる。"""
    inv = _collect(tmp_path)
    path = DeadCodeRatchet().update(inv, tmp_path / "new.json")
    assert load_baseline(path) == inv.keys()


# --- 実リポジトリ -------------------------------------------------------------


def test_実リポジトリを走査できる():
    """for_repo() が動き、走査数がゼロでないこと。件数そのものは固定しない。"""
    inv = DeadCodeInventory.for_repo()
    assert inv.entry_missing is False
    assert inv.routers_missing is False
    assert inv.registration_unknown is False
    assert inv.endpoints_scanned > 100
    assert inv.components_scanned > 10


def test_実リポジトリのベースラインが現状と一致する():
    """ラチェットが実際に main で緑であることを、CI 任せにせずここでも見る。"""
    from backend.ux_verification.dead_code import baseline_path

    inv = DeadCodeInventory.for_repo()
    result = DeadCodeRatchet().check(inv, load_baseline(baseline_path()))
    assert result.valid, result.to_text()
