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
           extra: dict | None = None, router: str = _ROUTER) -> ClosureExecutor:
    routers = tmp_path / "backend" / "routers"
    routers.mkdir(parents=True)
    (routers / "__init__.py").write_text(
        "from .demo import router as demo_router\n", encoding="utf-8")
    (routers / "demo.py").write_text(textwrap.dedent(router), encoding="utf-8")
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


def test_nothing_is_excluded_from_the_ban():
    """**禁止語彙から1つも外さない。**

    かつて「合成された URL」を『呼び出しの形ではない』という理由で外していたが、
    URL 属性という渡す先があり、検出が実際に1つ減っていた
    （gate-verifier 1回目の反例 A1）。外すなら名指しで宣言する仕組みは残すが、
    **いまは空でなければならない。**
    """
    assert _NOT_A_CALL_FORM == ()
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
    baseline["usages"]["src/components/App.jsx"] = {"getStatus": 1, "getSpare": 1}

    assert any("使用が減った" in v
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


# --- gate-verifier 1回目の反例（すべて実測で素通りしたもの） -------------------
#
# 修正が新しい沈黙を作らないよう、**破られた形をそのまま**固定する。


def test_a_relative_backend_path_is_a_violation(tmp_path):
    """`src="api/tasks"` は `/` で始まらないが、ブラウザは backend に GET を投げる。

    反例 A3。`/` で始まることを要求していたので素通りしていた。
    """
    report = _build(tmp_path, extra={
        "components/Sneak.jsx": """
            export const Sneak = () => <img alt="" src="api/demo/status" />;
        """}).run()

    assert "backend_url" in _kinds(report)


def test_a_backend_path_is_found_even_when_quotes_drift(tmp_path):
    """**引用符の対応付けに頼らない。**

    A3 が素通りした本当の原因はこれだった。ファイルのどこかにアポストロフィが
    1つあると文字列リテラルの対応がずれ、`src="api/x"` が巨大な「文字列」の
    中に飲まれて先頭が backend プレフィクスでなくなる。字句そのものを見る。
    """
    report = _build(tmp_path, extra={
        "components/Sneak.jsx": """
            // it's a comment with an apostrophe
            export const Sneak = () => <img alt="" src="/api/demo/status" />;
        """}).run()

    assert "backend_url" in _kinds(report)


def test_literals_joined_with_plus_are_a_violation(tmp_path):
    """`'/' + 'api' + '/x'` はどの1つも backend に見えない。反例 A2。"""
    report = _build(tmp_path, extra={
        "components/Sneak.jsx": """
            export const URL = '/' + 'api' + '/demo/status';
        """}).run()

    assert "joined_backend_url" in _kinds(report)


def test_a_literal_joined_with_a_variable_is_not_claimed_to_be_caught(tmp_path):
    """**捕まらないことを固定する。** 結合できないものを結合したことにしない。"""
    report = _build(tmp_path, extra={
        "components/Sneak.jsx": """
            export const make = (kind) => '/ap' + kind;
        """}).run()

    assert "joined_backend_url" not in _kinds(report)
    assert "変数を挟んで組み立てた URL" in "".join(
        CLOSURE_SEMANTICS["確かめないこと"])


def test_a_synthesised_url_form_is_still_banned(tmp_path):
    """反例 A1。`['', 'api', 'x'].join('/')` は URL 属性に入れば GET になる。

    「呼び出しの形ではないから」と禁止語彙から外していたが、
    **URL 属性という渡す先があった**ので外したのは誤りだった。
    """
    report = _build(tmp_path, extra={
        "components/Sneak.jsx": """
            export const Sneak = () => <img alt="" src={['', 'x'].join('/')} />;
        """}).run()

    assert "forbidden_form" in _kinds(report)


def test_the_ban_excludes_nothing_from_ui_api(tmp_path):
    """**1つも外さない。** 外すたびに、その形の検出が実際に減る。"""
    assert _NOT_A_CALL_FORM == ()
    assert set(UNSCANNED_FORMS) <= set(FORBIDDEN_FORMS)


def test_binding_a_gateway_function_to_a_variable_is_a_violation(tmp_path):
    """`const call = apiFetch; call(key)` は使用が判定から消える。C-3 の反例。"""
    report = _build(tmp_path, app="""
        import { apiFetch } from '../gateway/client.js';

        const call = apiFetch;

        export default function App(key) {
          return call(key);
        }
    """).run()

    assert "escaped_gateway_name" in _kinds(report)


def test_passing_a_gateway_function_as_an_argument_is_a_violation(tmp_path):
    report = _build(tmp_path, app="""
        import { apiFetch } from '../gateway/client.js';

        export default function App(run) {
          return run(apiFetch);
        }
    """).run()

    assert "escaped_gateway_name" in _kinds(report)


def test_a_plain_call_is_not_flagged_as_an_escape(tmp_path):
    """過検出で普通の呼び出しを落とさない。"""
    report = _build(tmp_path).run()

    assert "escaped_gateway_name" not in _kinds(report)


def test_excluding_a_directory_is_a_ratchet_violation(tmp_path):
    """**C-5 が名指しした弱化。** 1回目の検証では4ゲートを素通りしていた。"""
    executor = _build(tmp_path, extra={"hooks/useThing.js": "export const x = 1;\n"})
    baseline = _pinned(tmp_path, executor)
    # 除外ディレクトリを増やした状態を模す
    baseline["excluded_dirs"] = [d for d in baseline["excluded_dirs"]] + ["hooks"]

    violations = check_ratchet(executor.run(), baseline)

    assert any("判定が動いた" in v for v in violations)


def test_a_file_dropping_out_of_the_scan_is_a_ratchet_violation(tmp_path):
    """除外ディレクトリ以外の道（拡張子・到達可能性）で狭めても出る。"""
    executor = _build(tmp_path)
    baseline = _pinned(tmp_path, executor)
    baseline["scanned_files"] = sorted(
        baseline["scanned_files"] + ["src/components/Gone.jsx"])

    assert any("走査から外れた" in v
               for v in check_ratchet(executor.run(), baseline))


def test_the_success_message_does_not_claim_more_than_it_measured():
    """**測ったことしか言わない。** 「呼び出しは無い」と言い切らない。"""
    checked = "".join(CLOSURE_SEMANTICS["確かめること"])
    not_checked = "".join(CLOSURE_SEMANTICS["確かめないこと"])

    # PASS 側は「禁止した形が無い」までで、「呼び出しが無い」ではない
    assert "ネットワーク呼び出しの形が1件も無い" in checked
    # すり抜ける道が確かめないことに実在する
    assert "変数を挟んで組み立てた URL" in not_checked
    assert "URL 属性の式" in not_checked


# --- gate-verifier 2回目の反例 -----------------------------------------------
#
# 1回目の修正が**新しい沈黙を3つ作っていた**。同じ型を繰り返さないよう固定する。


def test_a_single_segment_backend_path_is_a_violation(tmp_path):
    """`/health` は登録済みのエンドポイント。**修正前は捕まえていた。**

    字句スキャンに置き換えたとき、プレフィクスの直後に `/` を必須にしたので
    `/health` が黙って見えなくなっていた（2回目の反例）。
    **修正が新しい沈黙を作る**の典型。
    """
    report = _build(tmp_path, router="""
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/health")
        async def health():
            return {"ok": True}

        @router.get("/api/demo/status")
        async def status():
            return {"ok": True}
    """, extra={
        "components/Link.jsx": """
            export const Status = () => <a href="/health">status</a>;
        """}).run()

    assert "backend_url" in _kinds(report)


def test_a_word_that_merely_starts_with_a_prefix_is_not_a_violation(tmp_path):
    """`/healthy` は別のパス。過検出で FAIL を作らない。"""
    report = _build(tmp_path, extra={
        "components/Link.jsx": """
            export const A = () => <a href="/healthy-living">x</a>;
        """}).run()

    assert "backend_url" not in _kinds(report)


def test_a_multiline_gateway_import_is_still_analysed(tmp_path):
    """**prettier が折るだけで使用判定が丸ごと消えていた。**

    行単位で import 行を探していたので、複数行 import のファイルは
    computed_key も unknown_key も一度も評価されなかった（2回目の反例）。
    """
    report = _build(tmp_path, app="""
        import {
            apiFetch,
        } from '../gateway/client.js';

        export default function App(kind) {
          return apiFetch(kind);
        }
    """).run()

    assert "computed_key" in _kinds(report)


def test_a_multiline_import_with_a_literal_key_is_counted_as_a_usage(tmp_path):
    """折られた import でも、正当な使用はちゃんと使用として数える。"""
    report = _build(tmp_path, app="""
        import {
            apiFetch,
        } from '../gateway/client.js';

        export default function App() {
          return apiFetch('getStatus');
        }
    """).run()

    assert report.findings == []
    assert report.usages == {"src/components/App.jsx": ["getStatus"]}


def test_a_re_export_shim_is_a_violation(tmp_path):
    """`export { apiFetch } from '…/client.js'` は `import` 語を含まないので
    import の検査を素通りし、別ファイル経由の呼び出しを作れていた（2回目の反例）。"""
    report = _build(tmp_path, extra={
        "utils/apiShim.js": """
            export { apiFetch } from '../gateway/client.js';
        """}).run()

    assert "bad_import" in _kinds(report)


def test_mentioning_the_gateway_in_a_comment_is_a_violation(tmp_path):
    """例外を作れば、そこが精度を要求する場所になる。**言及も禁止する。**"""
    report = _build(tmp_path, extra={
        "components/Note.jsx": """
            // 詳しくは gateway/endpoints.js を見よ
            export const Note = () => null;
        """}).run()

    assert "bad_import" in _kinds(report)


def test_swapping_a_detector_body_is_a_ratchet_violation(tmp_path):
    """**検出器を無効化しても4ゲートが緑だった**（2回目の反例）。

    落ちるのはテストだけで、そのテストは testpaths に無く CI で走っていなかった。
    P4 で `unscanned_forms` に適用した「正規表現の本体まで固定する」を
    このモジュール自身にも適用する。
    """
    executor = _build(tmp_path)
    baseline = _pinned(tmp_path, executor)
    baseline["detectors"]["backend_token"] = "(?!x)x"

    assert any("判定が動いた" in v
               for v in check_ratchet(executor.run(), baseline))


def test_every_detector_is_pinned(tmp_path):
    """欄を足したら固定も足す。**足し忘れを禁じる。**"""
    taken = snapshot(_build(tmp_path).run())

    assert set(taken["detectors"]) == {
        "absolute_url", "protocol_relative", "backend_token", "call_after",
        "catalogue_entry", "gateway_import", "joined_literals", "one_literal"}


def test_this_file_is_registered_in_testpaths():
    """**テストが CI で走っていることを、テスト自身が要求する。**

    このファイルは追加した当初 `pytest.ini` の testpaths に入っておらず、
    52件が CI で1度も実行されていなかった（gate-verifier 2回目の指摘）。
    ゲートの弱化を止める受け皿がそもそも動いていなかったということ。

    対象は UI-API の系列に絞る。`backend/tests/test_ux_snapshot.py` も
    未登録だが、登録すると1件落ちる（P5 と無関係の既存の負債なので
    バックログに回す）。`backend/tests/test_ux_ratchet.py` は
    `tests/test_ux_ratchet.py` と同内容の重複で、後者が登録済み。
    """
    root = Path(__file__).resolve().parents[2]
    registered = {line.strip()
                  for line in (root / "pytest.ini").read_text(encoding="utf-8")
                  .splitlines() if line.strip().endswith(".py")}

    missing = sorted(
        f"backend/tests/{p.name}"
        for p in (root / "backend" / "tests").glob("test_ux_ui_api*.py")
        if f"backend/tests/{p.name}" not in registered)

    assert missing == [], f"testpaths に無い UI-API 検証テスト: {missing}"


# --- gate-verifier 3回目の反例 -----------------------------------------------
#
# 走査範囲そのものが穴だった。`frontend/src` の外は1行も読まれていなかった。


def test_a_file_outside_src_is_scanned(tmp_path):
    """`frontend/lib/api.js` は src から import されれば実行される。

    借りていた走査は `frontend/src` + index.html + vite.config.* + public/**
    に固定されていたので、ここは**1行も読まれず**4ゲート全緑だった（3回目）。
    """
    executor = _build(tmp_path)
    (executor.frontend / "lib").mkdir()
    (executor.frontend / "lib" / "api.js").write_text(
        "export const go = () => fetch('http://localhost:8000/api/x');\n",
        encoding="utf-8")

    assert "forbidden_form" in _kinds(executor.run())


def test_a_re_export_shim_outside_src_is_a_violation(tmp_path):
    """2回目に塞いだ再輸出シムは、1つ上の階層に置くだけで復活していた。"""
    executor = _build(tmp_path)
    (executor.frontend / "lib").mkdir()
    (executor.frontend / "lib" / "door.js").write_text(
        "export { apiFetch } from '../src/gateway/client.js';\n",
        encoding="utf-8")

    assert "bad_import" in _kinds(executor.run())


def test_an_unlisted_suffix_is_still_scanned(tmp_path):
    """拡張子で絞ると、絞り漏れがそのまま穴になる（`.mts` が抜けていた）。"""
    executor = _build(tmp_path)
    (executor.frontend / "src" / "thing.mts").write_text(
        "export const go = () => fetch('http://localhost:8000/api/x');\n",
        encoding="utf-8")

    assert "forbidden_form" in _kinds(executor.run())


@pytest.mark.parametrize("href", ["./api/demo/status", "../api/demo/status"])
def test_a_dot_relative_backend_path_is_a_violation(tmp_path, href):
    """`./api/x` は先読みが `.` に潰されて拾えていなかった。"""
    report = _build(tmp_path, extra={
        "components/Link.jsx": f'export const L = () => <a href="{href}">x</a>;\n',
    }).run()

    assert "backend_url" in _kinds(report)


def test_a_protocol_relative_url_is_a_violation(tmp_path):
    """`//host/x` はブラウザがページと同じスキームで解決する。

    絶対 URL の検出がスキーム必須だったので素通りしていた。
    """
    report = _build(tmp_path, extra={
        "components/Link.jsx":
            'export const L = () => <a href="//localhost:8000/api/x">y</a>;\n',
    }).run()

    assert "external_url" in _kinds(report)


def test_a_line_comment_is_not_a_protocol_relative_url(tmp_path):
    """`// コメント` を URL と誤検出しない（直後が空白）。"""
    report = _build(tmp_path, extra={
        "components/Note.jsx": "// ふつうの行コメント\nexport const N = null;\n",
    }).run()

    assert "external_url" not in _kinds(report)


def test_dropping_one_of_several_identical_calls_is_a_ratchet_violation(tmp_path):
    """**回数まで固定する。**

    同じファイルで同じキーを何度も呼んでいるとき、集合だけを固定していると
    最後の1本が残る限り何本消しても黙っていた（C-5(b) がそのまま成立）。
    """
    executor = _build(tmp_path, app="""
        import { apiFetch } from '../gateway/client.js';

        export default function App() {
          apiFetch('getStatus');
          apiFetch('getStatus');
          return apiFetch('getStatus');
        }
    """)
    baseline = _pinned(tmp_path, executor)
    assert baseline["usages"]["src/components/App.jsx"]["getStatus"] == 3

    (executor.frontend / "src" / "components" / "App.jsx").write_text(
        "import { apiFetch } from '../gateway/client.js';\n"
        "export default function App() { return apiFetch('getStatus'); }\n",
        encoding="utf-8")

    assert any("使用が減った" in v
               for v in check_ratchet(executor.run(), baseline))


def test_the_scan_boundary_of_the_closure_is_pinned(tmp_path):
    """除外を1つ足せば、その場所が無検査になる。**足したら落ちる。**"""
    executor = _build(tmp_path)
    baseline = _pinned(tmp_path, executor)
    baseline["closure_excluded"] = sorted(
        baseline["closure_excluded"] + ["components"])

    assert any("判定が動いた" in v
               for v in check_ratchet(executor.run(), baseline))


def test_the_ratchet_says_which_detector_moved(tmp_path):
    """「動いた」だけでは何が起きたか分からない（3回目の指摘）。"""
    executor = _build(tmp_path)
    baseline = _pinned(tmp_path, executor)
    baseline["detectors"]["backend_token"] = "(?!x)x"

    message = "\n".join(check_ratchet(executor.run(), baseline))

    assert "backend_token" in message
    assert "(?!x)x" in message


# --- gate-verifier 4回目の反例 -----------------------------------------------
#
# **自分で足した安全弁が唯一の fail-open 分岐になっていた。**
# 「NUL を含むファイルはテキストでないので読まない」という中身の判定は、
# ソースに NUL を1文字混ぜるだけで走査から外せる抜け道だった
# （NUL は JS の文字列リテラルとして合法で、vite はビルドできる）。


def test_a_source_with_a_nul_byte_is_still_scanned(tmp_path):
    """**中身で読むかどうかを決めない。** 決めるのは場所と拡張子だけ。"""
    executor = _build(tmp_path)
    (executor.frontend / "src" / "components" / "Notes.jsx").write_text(
        "const MARKER = 'x\x00y';\n"
        "export const Notes = () => fetch('/api/demo/status');\n",
        encoding="utf-8")

    kinds = _kinds(executor.run())

    assert "forbidden_form" in kinds
    assert "backend_url" in kinds


def test_a_nul_byte_does_not_hide_a_re_export_shim(tmp_path):
    """3回目に塞いだ再輸出シムが、NUL 1文字で完全に復活していた。"""
    executor = _build(tmp_path)
    (executor.frontend / "src" / "components" / "shim.js").write_text(
        "const MARKER = 'x\x00y';\n"
        "export { apiFetch } from '../gateway/client.js';\n",
        encoding="utf-8")

    assert "bad_import" in _kinds(executor.run())


def test_a_nul_byte_does_not_hide_a_comment_url(tmp_path):
    report_files = _build(tmp_path)
    (report_files.frontend / "src" / "components" / "Note.jsx").write_text(
        "// https://unregistered.example.com/collect に送る\n"
        "const M = 'x\x00y';\nexport const N = null;\n", encoding="utf-8")

    assert "external_url" in _kinds(report_files.run())


def test_an_undeclared_binary_suffix_is_read_not_skipped(tmp_path):
    """宣言していない拡張子は、中身が何であろうと読む（fail-closed）。

    誤検出が出るなら**拡張子を宣言する**（そしてラチェットが差分に出す）。
    黙って読み飛ばす道は残さない。
    """
    executor = _build(tmp_path)
    (executor.frontend / "src" / "blob.gif").write_bytes(
        b'GIF89a\x00\x00 fetch("/api/demo/status")')

    assert "forbidden_form" in _kinds(executor.run())


def test_the_excluded_suffixes_are_pinned(tmp_path):
    """読まない拡張子を黙って増やせない。"""
    executor = _build(tmp_path)
    baseline = _pinned(tmp_path, executor)
    baseline["closure_binary_suffixes"] = sorted(
        baseline["closure_binary_suffixes"] + [".jsx"])

    assert any("判定が動いた" in v
               for v in check_ratchet(executor.run(), baseline))


def test_nothing_decides_what_to_read_by_content():
    """**中身を見て読む／読まないを決める分岐が1つも無い**ことを固定する。

    ここに分岐が戻ると、その条件を満たすファイルが走査から消える。
    """
    from backend.ux_verification import ui_api_closure

    source = Path(ui_api_closure.__file__).read_text(encoding="utf-8")

    assert "_BINARY_HINT" not in source
    assert not hasattr(ui_api_closure, "_BINARY_HINT")


# --- gate-verifier 5回目の反例 -----------------------------------------------
#
# 4回目までは「中身」側の穴だった。5回目は**場所**側で、
# しかも**コードもベースラインも一切触らずに**通るものだった。


def test_a_directory_named_like_an_exclusion_is_still_scanned(tmp_path):
    """`src/components/build/` を作るだけで無検査になっていた。

    除外をディレクトリ名で任意階層に効かせていたのが原因。
    **frontend からの相対パスの完全一致**にした。
    """
    executor = _build(tmp_path)
    nested = executor.frontend / "src" / "components" / "build"
    nested.mkdir()
    (nested / "api.js").write_text(
        "export const raw = () => fetch('/api/demo/status');\n", encoding="utf-8")

    assert "forbidden_form" in _kinds(executor.run())


def test_a_top_level_excluded_directory_is_skipped(tmp_path):
    """トップレベルの `dist` は読まない（宣言どおり）。"""
    executor = _build(tmp_path)
    dist = executor.frontend / "dist"
    dist.mkdir()
    (dist / "bundle.js").write_text("fetch('/api/demo/status');\n", encoding="utf-8")

    assert executor.run().findings == []


def test_a_symlink_in_the_frontend_is_a_violation(tmp_path):
    """**降りないなら違反にする。** 黙って読み飛ばすとリンク先が無検査になる。"""
    executor = _build(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.js").write_text(
        "export const r = () => fetch('/api/demo/status');\n", encoding="utf-8")
    try:
        (executor.frontend / "src" / "vendor").symlink_to(
            outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("この環境では symlink を作れない")

    assert "symlinked_path" in _kinds(executor.run())


def test_a_raw_import_is_a_violation(tmp_path):
    """走査から外した拡張子の中身を、文字列として持ち出す道を塞ぐ。"""
    report = _build(tmp_path, extra={
        "loader.js": "import p from './payload.png?raw';\nexport default p;\n",
    }).run()

    assert "forbidden_form" in _kinds(report)


@pytest.mark.parametrize("source", [
    "export const go = (p) => new Function(p)();",
    "export const go = (p) => eval(p);",
])
def test_turning_a_string_into_code_is_a_violation(tmp_path, source):
    """`.png` に書いた JS を実行する道。**除外した中身をコードに戻せない。**"""
    report = _build(tmp_path, extra={"run.js": source + "\n"}).run()

    assert "forbidden_form" in _kinds(report)


def test_an_uppercase_excluded_suffix_is_also_skipped(tmp_path):
    """`.PNG` で宣言をすり抜けられない（大文字小文字を問わない）。"""
    executor = _build(tmp_path)
    (executor.frontend / "src" / "IMAGE.PNG").write_bytes(
        bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 8)

    assert executor.run().findings == []


def test_the_closure_is_green_without_node_modules(tmp_path):
    """**gitignore 対象の除外が実在しなくても緑。**

    「実在しない除外は違反」を一度入れたが、`node_modules` と `dist` は
    CI に存在しないので偽の赤になった。除外の追加はラチェットが落とすので
    保護は減らない。
    """
    executor = _build(tmp_path)  # node_modules も dist も作っていない

    assert executor.run().findings == []


# --- gate-verifier 6回目の反例 -----------------------------------------------
#
# **綴りの列挙で塞ごうとしたのが誤りだった。** `?raw` → `import.meta.glob(
# {as:'raw'})`、`new Function` → 素の `Function(` の2点だけで復活した。
# 閉包を支えるのは「全部読む・バイナリは実体を検証する」ほうにした。


def test_a_markdown_payload_is_scanned(tmp_path):
    """`.md` を走査から外していたので、そこに JS を書いて取り出せた。

    **載せ方（`?raw` でも `import.meta.glob` でも）に関係なく**、
    中身を読んでいれば `fetch` も backend URL もそこで捕まる。
    """
    report = _build(tmp_path, extra={
        "components/payload.md":
            "return fetch('/api/demo/status').then((r) => r.json());\n",
    }).run()

    kinds = _kinds(report)
    assert "forbidden_form" in kinds
    assert "backend_url" in kinds


def test_a_binary_file_that_is_not_an_image_is_a_violation(tmp_path):
    """**外している根拠のほうを確かめる。** 拡張子は嘘をつく。

    走査から外すのは「画像だから」。JS を書いた `.png` はマジックバイトに
    合わないので落ちる。中身の取り出し方が何であっても成立しない。
    """
    executor = _build(tmp_path)
    (executor.frontend / "src" / "payload.png").write_bytes(
        b'return fetch("/api/demo/status");')

    assert "not_really_binary" in _kinds(executor.run())


def test_a_real_image_is_skipped_even_with_a_wrong_extension(tmp_path):
    """このリポジトリの `*.png` は中身が JPEG だった。**実体で判定する。**"""
    executor = _build(tmp_path)
    (executor.frontend / "src" / "photo.png").write_bytes(
        bytes.fromhex("ffd8ff") + b"\x00" * 32)

    assert executor.run().findings == []


@pytest.mark.parametrize("source", [
    "export const go = (p) => Function(p)();",      # `new` 無し
    "export const go = (p) => new Function(p)();",
    "export const go = (p) => eval(p);",
    "export const go = () => setTimeout('x()', 0);",
    "export const go = () => setInterval('x()', 0);",
])
def test_turning_a_string_into_code_stays_banned(tmp_path, source):
    """保険としては残す。**ただしこれで閉じたとは言わない**（意味表に明記）。"""
    report = _build(tmp_path, extra={"run.js": source + "\n"}).run()

    assert "forbidden_form" in _kinds(report)


def test_a_normal_settimeout_is_not_flagged(tmp_path):
    """関数を渡す `setTimeout` は正当。過検出でコードを壊さない。"""
    report = _build(tmp_path, extra={
        "timer.js": "export const go = (f) => setTimeout(f, 0);\n"}).run()

    assert report.findings == []


def test_the_semantics_do_not_claim_the_spelling_ban_closes_it():
    """**綴りの列挙で閉じたと言わない。** 1回目・6回目と同じ型の過剰主張。"""
    not_checked = "".join(CLOSURE_SEMANTICS["確かめないこと"])

    assert "実行時に組み立てたコードの実行" in not_checked
    assert "綴りの列挙" in not_checked


def test_the_binary_declaration_is_pinned(tmp_path):
    """マジックバイトを緩めれば、画像でないものを外せる。"""
    executor = _build(tmp_path)
    baseline = _pinned(tmp_path, executor)
    baseline["closure_binary_magics"] = dict(
        baseline["closure_binary_magics"], ANYTHING="")

    assert any("判定が動いた" in v
               for v in check_ratchet(executor.run(), baseline))


# --- gate-verifier 7回目の反例 -----------------------------------------------
#
# マジックバイトの検証は**先頭8バイトの一致しか見ない**。
# `89504e470d0a1a0a` の後ろに JS を置いたファイルが「本当に画像」と判定され、
# `import.meta.glob({as:'raw'})` + `Blob` + 変数引数の動的 `import()` で
# 実行できた（禁止語彙に1つも触れない）。深さを増やしても PNG の tEXt
# チャンクなどで同じことができるので、**中身そのものを固定する**。


def _binary(executor, name: str, body: bytes) -> None:
    (executor.frontend / name).parent.mkdir(parents=True, exist_ok=True)
    (executor.frontend / name).write_bytes(body)


def test_an_unpinned_binary_is_a_ratchet_violation(tmp_path):
    """マジックだけ本物の偽画像は、**未ピン**として落ちる。"""
    executor = _build(tmp_path)
    _binary(executor, "src/real.png", bytes.fromhex("89504e470d0a1a0a") + b"\x01" * 8)
    baseline = _pinned(tmp_path, executor)

    _binary(executor, "src/payload.png",
            bytes.fromhex("89504e470d0a1a0a")
            + b"export const boom = () => fetch('/api/demo/status');")

    assert any("未ピンのバイナリ" in v
               for v in check_ratchet(executor.run(), baseline))


def test_replacing_a_pinned_binary_is_a_ratchet_violation(tmp_path):
    """既存の画像を JS に差し替えても落ちる。"""
    executor = _build(tmp_path)
    _binary(executor, "src/real.png", bytes.fromhex("89504e470d0a1a0a") + b"\x01" * 8)
    baseline = _pinned(tmp_path, executor)

    _binary(executor, "src/real.png",
            bytes.fromhex("89504e470d0a1a0a") + b"fetch('/api/demo/status')")

    assert any("バイナリが差し替わった" in v
               for v in check_ratchet(executor.run(), baseline))


def test_a_pinned_binary_that_disappears_is_a_ratchet_violation(tmp_path):
    executor = _build(tmp_path)
    _binary(executor, "src/real.png", bytes.fromhex("89504e470d0a1a0a") + b"\x01" * 8)
    baseline = _pinned(tmp_path, executor)

    (executor.frontend / "src" / "real.png").unlink()

    assert any("バイナリが消えた" in v
               for v in check_ratchet(executor.run(), baseline))


def test_an_excluded_file_name_only_matches_at_the_declared_path(tmp_path):
    """`src/components/package-lock.json` を置くだけで無検査になっていた。

    ファイル除外もディレクトリ除外と同じく**相対パスの完全一致**にした。
    """
    executor = _build(tmp_path)
    (executor.frontend / "src" / "components" / "package-lock.json").write_text(
        "fetch('/api/demo/status')\n", encoding="utf-8")

    assert "backend_url" in _kinds(executor.run())


def test_the_declared_lock_file_is_still_skipped(tmp_path):
    """宣言した場所のものは読まない（宣言どおり）。"""
    executor = _build(tmp_path)
    (executor.frontend / "package-lock.json").write_text(
        "https://registry.npmjs.org/x\n", encoding="utf-8")

    assert executor.run().findings == []


def test_the_semantics_say_markdown_is_read():
    """`.md` を読むよう変えたのに意味表が古いままだった（7回目の指摘）。"""
    checked = "".join(CLOSURE_SEMANTICS["確かめること"])
    not_checked = "".join(CLOSURE_SEMANTICS["確かめないこと"])

    assert "**`.md` は読む。**" in checked
    assert ".md" not in not_checked.split("走査から外したバイナリの中身")[1][:80]


def test_the_semantics_do_not_claim_magic_bytes_are_enough():
    """「本当に画像である」という断定は8バイトで抜けた。**後退させる。**"""
    checked = "".join(CLOSURE_SEMANTICS["確かめること"])

    assert "1バイトも変わっていない" in checked
    assert "それだけでは足りない" in checked
