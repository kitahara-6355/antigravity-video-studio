"""L1（DOM存在）検証項目の実行系のテスト。

判定は frontend ソースの静的走査で行う。ブラウザもサーバも起動しないので
無料で、CI でそのまま回る。代わりに「実行時に本当に描画されるか」は保証しない
——その限界は evidence の method に明記される。
"""
import json
import textwrap

import pytest

from backend.ux_verification.executor import (
    L1Executor,
    TestIdRegistry,
    Verdict,
)

# --- TestIdRegistry: frontend ソースから testid を拾う ------------------------


def _write(root, rel, body):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_registry_picks_up_double_quoted_testid(tmp_path):
    _write(tmp_path, "src/App.jsx", """
        export default function App() {
          return <div data-testid="video-list" />
        }
    """)
    reg = TestIdRegistry.scan(tmp_path / "src")

    assert "video-list" in reg.literals
    assert reg.literals["video-list"].file.endswith("App.jsx")
    assert reg.literals["video-list"].line == 3


def test_registry_picks_up_single_quoted_and_braced_testid(tmp_path):
    _write(tmp_path, "src/App.jsx", """
        const a = <div data-testid='single-quoted' />
        const b = <div data-testid={"braced"} />
    """)
    reg = TestIdRegistry.scan(tmp_path / "src")

    assert "single-quoted" in reg.literals
    assert "braced" in reg.literals


def test_registry_turns_template_literal_into_prefix_pattern(tmp_path):
    _write(tmp_path, "src/App.jsx", """
        const row = <div data-testid={`segment-item-${seg.id}`} />
    """)
    reg = TestIdRegistry.scan(tmp_path / "src")

    assert "segment-item-" in reg.prefixes
    assert "segment-item-${seg.id}" not in reg.literals


def test_registry_ignores_fully_dynamic_testid(tmp_path):
    """data-testid={someVar} は何になるか静的には分からない。拾わない。"""
    _write(tmp_path, "src/App.jsx", """
        const x = <div data-testid={someVar} />
    """)
    reg = TestIdRegistry.scan(tmp_path / "src")

    assert reg.literals == {}
    assert reg.prefixes == {}


def test_registry_scans_nested_directories_and_tsx(tmp_path):
    _write(tmp_path, "src/components/Deep/Panel.tsx", """
        const p = <div data-testid="deep-panel" />
    """)
    reg = TestIdRegistry.scan(tmp_path / "src")

    assert "deep-panel" in reg.literals


def test_registry_skips_node_modules(tmp_path):
    _write(tmp_path, "src/node_modules/pkg/index.jsx", """
        const x = <div data-testid="vendor-thing" />
    """)
    reg = TestIdRegistry.scan(tmp_path / "src")

    assert "vendor-thing" not in reg.literals


# --- 解決: ストーリー側の testid をレジストリに突き合わせる --------------------


def test_resolve_exact_literal(tmp_path):
    _write(tmp_path, "src/App.jsx", '<div data-testid="video-list" />')
    reg = TestIdRegistry.scan(tmp_path / "src")

    hit = reg.resolve("video-list")

    assert hit is not None
    assert hit.line == 1


def test_resolve_wildcard_matches_template_pattern(tmp_path):
    _write(tmp_path, "src/App.jsx", '<div data-testid={`segment-item-${id}`} />')
    reg = TestIdRegistry.scan(tmp_path / "src")

    assert reg.resolve("segment-item-*") is not None


def test_resolve_wildcard_matches_literal_with_same_prefix(tmp_path):
    """テンプレートではなく個別に書かれていても、前方一致すれば充足とみなす。"""
    _write(tmp_path, "src/App.jsx", '<div data-testid="diff-mark-3" />')
    reg = TestIdRegistry.scan(tmp_path / "src")

    assert reg.resolve("diff-mark-*") is not None


def test_wildcard_does_not_match_a_broader_template(tmp_path):
    """雑なテンプレート1つで、別々の要求をまとめて通してはいけない。

    `segment-${x}` は segment-approve-btn-1 を生むとは限らない。
    テンプレートが生む id は必ずその接頭辞で始まるので、要求を満たすのは
    接頭辞の側が要求で始まるときだけ。
    """
    _write(tmp_path, "src/App.jsx", '<div data-testid={`segment-${id}`} />')
    reg = TestIdRegistry.scan(tmp_path / "src")

    assert reg.resolve("segment-approve-btn-*") is None
    assert reg.resolve("segment-*") is not None


def test_resolve_returns_none_for_unknown(tmp_path):
    _write(tmp_path, "src/App.jsx", '<div data-testid="video-list" />')
    reg = TestIdRegistry.scan(tmp_path / "src")

    assert reg.resolve("does-not-exist") is None


def test_resolve_does_not_match_prefix_without_wildcard(tmp_path):
    """ストーリーが `segment` を要求しているのに `segment-item-1` で通してはいけない。"""
    _write(tmp_path, "src/App.jsx", '<div data-testid={`segment-item-${id}`} />')
    reg = TestIdRegistry.scan(tmp_path / "src")

    assert reg.resolve("segment") is None


# --- 到達可能性: マウントされないコンポーネントの testid を PASS にしない -------


def test_registry_marks_unreachable_component(tmp_path):
    _write(tmp_path, "src/main.jsx", "import App from './App.jsx'")
    _write(tmp_path, "src/App.jsx", '<div data-testid="mounted" />')
    _write(tmp_path, "src/components/Orphan.jsx", '<div data-testid="orphan" />')

    reg = TestIdRegistry.scan(tmp_path / "src", entry=tmp_path / "src" / "main.jsx")

    assert reg.resolve("mounted").reachable is True
    assert reg.resolve("orphan").reachable is False


def test_reachability_follows_transitive_imports(tmp_path):
    _write(tmp_path, "src/main.jsx", "import App from './App.jsx'")
    _write(tmp_path, "src/App.jsx", "import Panel from './components/Panel.jsx'")
    _write(tmp_path, "src/components/Panel.jsx", '<div data-testid="nested" />')

    reg = TestIdRegistry.scan(tmp_path / "src", entry=tmp_path / "src" / "main.jsx")

    assert reg.resolve("nested").reachable is True


def test_reachability_is_unknown_without_entry(tmp_path):
    """entry を渡さなければ到達判定はしない（全件 True 扱いにしない）。"""
    _write(tmp_path, "src/App.jsx", '<div data-testid="x" />')
    reg = TestIdRegistry.scan(tmp_path / "src")

    assert reg.resolve("x").reachable is None


# --- L1Executor: ストーリーを判定する ----------------------------------------


class StoriesDir:
    """ストーリー JSON を書き足せる一時ディレクトリ。"""

    def __init__(self, path):
        self.path = path
        path.mkdir(parents=True, exist_ok=True)

    def add(self, ux_id, items):
        name = ux_id.lower().replace("-", "")
        (self.path / f"{name}.json").write_text(
            json.dumps({"ux_id": ux_id, "name": ux_id, "verification_items": items},
                       ensure_ascii=False),
            encoding="utf-8",
        )


@pytest.fixture
def stories_dir(tmp_path):
    return StoriesDir(tmp_path / "stories")


@pytest.fixture
def frontend(tmp_path):
    src = tmp_path / "fe" / "src"
    _write(tmp_path, "fe/src/main.jsx", "import App from './App.jsx'")
    _write(tmp_path, "fe/src/App.jsx", '<div data-testid="present" />')
    return src


def test_executor_passes_when_testid_exists(stories_dir, frontend):
    stories_dir.add("O-1", [
        {"id": "O1-L1-01", "layer": 1, "test_method": "dom_exists",
         "testid": "present", "description": "ある要素", "story_scene": "S1"},
    ])

    report = L1Executor(stories_dir.path, frontend).run(persona="owner")

    assert len(report.results) == 1
    r = report.results[0]
    assert r.verdict is Verdict.PASS
    assert r.reason == "found"
    assert "App.jsx" in r.evidence


def test_executor_fails_when_testid_missing_from_frontend(stories_dir, frontend):
    stories_dir.add("O-1", [
        {"id": "O1-L1-01", "layer": 1, "test_method": "dom_exists",
         "testid": "absent", "description": "無い要素", "story_scene": "S1"},
    ])

    report = L1Executor(stories_dir.path, frontend).run(persona="owner")

    assert report.results[0].verdict is Verdict.FAIL
    assert report.results[0].reason == "not_found"


def test_executor_fails_when_item_declares_no_testid(stories_dir, frontend):
    """dom_exists と書いてあるのに testid が無い項目は、SKIP ではなく FAIL。

    SKIP は「判定していない」、FAIL は「判定した結果、保証されていない」。
    照合先が定義されていないなら UX は保証されていないので FAIL が正しい。
    """
    stories_dir.add("O-1", [
        {"id": "O1-L1-01", "layer": 1, "test_method": "dom_exists",
         "description": "testid 未定義", "story_scene": "S1"},
    ])

    report = L1Executor(stories_dir.path, frontend).run(persona="owner")

    assert report.results[0].verdict is Verdict.FAIL
    assert report.results[0].reason == "no_testid"
    assert report.skip_count == 0


def test_executor_fails_when_component_is_unreachable(stories_dir, tmp_path):
    _write(tmp_path, "fe2/src/main.jsx", "import App from './App.jsx'")
    _write(tmp_path, "fe2/src/App.jsx", "export default function App() { return null }")
    _write(tmp_path, "fe2/src/components/Orphan.jsx", '<div data-testid="orphan" />')
    stories_dir.add("O-1", [
        {"id": "O1-L1-01", "layer": 1, "test_method": "dom_exists",
         "testid": "orphan", "description": "孤児", "story_scene": "S1"},
    ])

    report = L1Executor(stories_dir.path, tmp_path / "fe2" / "src").run(persona="owner")

    assert report.results[0].verdict is Verdict.FAIL
    assert report.results[0].reason == "unreachable"


def test_executor_selects_owner_stories_only(stories_dir, frontend):
    stories_dir.add("O-1", [
        {"id": "O1-L1-01", "layer": 1, "test_method": "dom_exists",
         "testid": "present", "story_scene": "S1"},
    ])
    stories_dir.add("A-1", [
        {"id": "A1-L1-01", "layer": 1, "test_method": "dom_exists",
         "testid": "present", "story_scene": "S1"},
    ])

    report = L1Executor(stories_dir.path, frontend).run(persona="owner")

    assert [r.item_id for r in report.results] == ["O1-L1-01"]


def test_executor_selects_layer_1_only(stories_dir, frontend):
    stories_dir.add("O-1", [
        {"id": "O1-L1-01", "layer": 1, "test_method": "dom_exists",
         "testid": "present", "story_scene": "S1"},
        {"id": "O1-L3-01", "layer": 3, "test_method": "interaction",
         "story_scene": "S1"},
    ])

    report = L1Executor(stories_dir.path, frontend).run(persona="owner")

    assert [r.item_id for r in report.results] == ["O1-L1-01"]


def test_executor_report_counts(stories_dir, frontend):
    stories_dir.add("O-1", [
        {"id": "O1-L1-01", "layer": 1, "test_method": "dom_exists",
         "testid": "present", "story_scene": "S1"},
        {"id": "O1-L1-02", "layer": 1, "test_method": "dom_exists",
         "testid": "absent", "story_scene": "S1"},
        {"id": "O1-L1-03", "layer": 1, "test_method": "dom_exists",
         "story_scene": "S1"},
    ])

    report = L1Executor(stories_dir.path, frontend).run(persona="owner")

    assert report.total == 3
    assert report.pass_count == 1
    assert report.fail_count == 2
    assert report.skip_count == 0


def test_every_result_carries_evidence(stories_dir, frontend):
    """PASS も FAIL も、なぜそう判定したかを必ず持つ（証拠主義）。"""
    stories_dir.add("O-1", [
        {"id": "O1-L1-01", "layer": 1, "test_method": "dom_exists",
         "testid": "present", "story_scene": "S1"},
        {"id": "O1-L1-02", "layer": 1, "test_method": "dom_exists",
         "testid": "absent", "story_scene": "S1"},
    ])

    report = L1Executor(stories_dir.path, frontend).run(persona="owner")

    for r in report.results:
        assert len(r.evidence.strip()) >= 5, f"{r.item_id} に証拠が無い"


def test_evidence_states_the_method_is_static(stories_dir, frontend):
    """静的走査であることを証拠に残す。実行時 DOM 確認と取り違えさせない。"""
    stories_dir.add("O-1", [
        {"id": "O1-L1-01", "layer": 1, "test_method": "dom_exists",
         "testid": "present", "story_scene": "S1"},
    ])

    report = L1Executor(stories_dir.path, frontend).run(persona="owner")

    assert report.method == "static_source_scan"
    assert "static_source_scan" in report.results[0].evidence


# --- 実データ: このリポジトリの Owner L1 を判定できる -------------------------


def test_real_owner_l1_is_fully_judged():
    """本物のストーリーと本物の frontend で、122項目に SKIP がゼロであること。"""
    report = L1Executor.for_repo().run(persona="owner")

    assert report.total == 122
    assert report.skip_count == 0
    assert report.pass_count + report.fail_count == 122


def test_real_report_is_convertible_to_snapshot():
    report = L1Executor.for_repo().run(persona="owner")
    snapshot = report.to_snapshot(version="v9_l1_owner")
    snapshot.compute_aggregates()

    assert snapshot.total_items == 122
    assert snapshot.skip_items == 0
    assert all(i.evidence for i in snapshot.items if i.passed is True)
