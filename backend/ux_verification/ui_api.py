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

# 走査するファイル。executor の `_SOURCE_SUFFIXES` は .jsx/.js/.tsx/.ts だけで、
# `.mjs` は到達可能と判定されるのに走査から漏れていた。`index.html` と CSS は
# 一度も開かれていなかった（gate-verifier 4回目の指摘）。
SCANNED_SUFFIXES = (".jsx", ".js", ".tsx", ".ts", ".mjs", ".cjs",
                     ".css", ".html")
# import で辿れないので到達可能性の対象外にするもの。**常に走査する。**
_NON_MODULE_SUFFIXES = (".css", ".html")
_EXCLUDED_DIRS = {"node_modules", "dist", "build", "__pycache__", ".vite"}

# `fetch(` と `window.fetch(` / `globalThis.fetch(` / `self.fetch(`。
# 素の `fetch` だけを見ていると `window.fetch('/api/x')` が走査から**黙って消える**
# （gate-verifier 1回目の指摘）。受け側を閉じた集合にし、それ以外の `X.fetch(` は
# 素通りさせず unresolved_url として出す。
_FETCH_RE = re.compile(r"(?<![\w$])fetch\s*(?:\?\.)?\s*\(")
# `fetch(` の直前にある受け側（`window.` など）を読む。`?.` と改行も跨ぐ——
# `client?.fetch(...)` や改行を挟んだ `.fetch(` を見落とすと、未知の受け側が
# 素の呼び出しに化ける（gate-verifier 2回目の指摘）。
_RECEIVER_RE = re.compile(r"([\w$]+(?:\s*\??\.\s*[\w$]+)*)\s*\??\.\s*$", re.DOTALL)
_GLOBAL_RECEIVERS = ("window", "globalThis", "self")
# WebSocket も UI から backend を叩く経路。`@router.websocket` の宣言と
# 突き合わせる。`fetch` だけ見て「全部見た」と言わない。
_WEBSOCKET_RE = re.compile(
    r"(?<![\w.$])new\s+(?:(?:window|globalThis|self)\s*\.\s*)?WebSocket\s*\(")

# 走査している呼び出しの形。**機械可読にする** — ここに無い形は
# 「確かめていない」であって「無い」ではない（gate-verifier 1回目の指摘）。
SCANNED_FORMS = ("fetch", "window.fetch", "globalThis.fetch", "self.fetch",
                 "new WebSocket", "window.open",
                 "src={...}", "href={...}", "poster={...}",
                 'src="..."', 'href="..."', 'poster="..."')
# 走査できない形。実在したら unscanned_form として FAIL にする。
# 「対応していないから見えない」を「問題なし」に混ぜない。
UNSCANNED_FORMS = {
    "axios": re.compile(r"(?<![\w.$])axios\s*[.(]"),
    "XMLHttpRequest": re.compile(r"(?<![\w.$])new\s+XMLHttpRequest\s*\("),
    "EventSource": re.compile(r"(?<![\w.$])new\s+EventSource\s*\("),
    "sendBeacon": re.compile(r"(?<![\w.$])navigator\.sendBeacon\s*\("),
    # `const f = window.fetch` のような別名束縛と `api['fetch']`。
    # どちらも呼び出し地点に `fetch(` が現れないので走査から消える。
    "fetch の別名束縛": re.compile(
        r"=\s*(?:window|globalThis|self)?\.?\s*fetch\s*(?![\s(])"),
    "計算メンバでの fetch": re.compile(r"\[\s*['\"]fetch['\"]\s*\]"),
    # `fetch.call(null, url)` / `fetch.apply(...)`。`fetch(` に当たらないので
    # 走査からも別名束縛からも漏れる（gate-verifier 3回目の指摘）。
    "fetch.call / fetch.apply": re.compile(
        r"(?<![\w$])fetch\s*\.\s*(?:call|apply|bind)\s*\("),
    # ブラウザ遷移。backend のパスを渡せば GET が飛ぶ。
    # 受け側（window/top/parent/document/self）の有無と、代入・メソッドの
    # どちらでも当たるようにする。`window.location =` と
    # `document.location =` を別々の正規表現で書くと隙間ができる
    # （gate-verifier 5回目の指摘）。
    "location 遷移": re.compile(
        r"(?<![\w$])(?:(?:window|globalThis|self|top|parent|document)\s*\.\s*)?"
        r"location\s*(?:\.\s*(?:assign|replace)\s*\(|\.\s*href\s*=(?!=)|=(?!=))"),
    "動的 import": re.compile(r"(?<![\w.$])import\s*\(\s*['\"`]"),
    "Service Worker": re.compile(r"serviceWorker\s*\.\s*register\s*\("),
    # URL を運ぶが走査していない属性・記法。
    "form action": re.compile(r"(?<![\w$])(?:form)?[Aa]ction\s*=\s*[{'\"]"),
    # `<object data=...>` だけ。素の `data={...}` は React の props で URL ではない。
    "object の data": re.compile(r"<object\b[^>]*?\bdata\s*=\s*[{'\"]", re.DOTALL),
    "srcSet": re.compile(r"(?<![\w$])srcSet\s*=\s*[{'\"]"),
    # `url(${API_BASE}/api/x)` のように途中に式が挟まる形も拾う。
    "CSS の url()": re.compile(r"url\s*\(\s*[^)\n]*?/api/"),
    "DOM への URL 代入": re.compile(r"\.\s*(?:href|src)\s*=\s*[`'\"]"),
    "$.ajax / ky / superagent": re.compile(
        r"(?<![\w.$])(?:\$\s*\.\s*ajax|ky\s*[.(]|superagent\s*\.)"),
    # 4回目の指摘。走査もされず「走査できない形」にも入っていなかった5形。
    "new Worker": re.compile(
        r"(?<![\w.$])new\s+(?:Shared)?Worker\s*\("),
    "素の open()": re.compile(r"(?<![\w.$])open\s*\(\s*['\"`]"),
    "setAttribute で URL": re.compile(
        r"setAttribute\s*\(\s*['\"]"
        r"(?:src|href|action|formaction|data|poster|srcset|content|ping)['\"]",
        re.IGNORECASE),
}

# JSX の URL 属性と `window.open`。ブラウザはこれも backend に GET を投げる。
# `fetch` だけ見て「全部見た」と言わない（gate-verifier 2回目の指摘）。
_URL_ATTR_RE = re.compile(r"(?<![\w$])(?:src|href|poster)\s*=\s*\{")
# 波括弧なしの素の文字列（`<a href="/api/x">`）。これも走査から消えていた。
_URL_ATTR_STR_RE = re.compile(
    r"(?<![\w$])(?:src|href|poster)\s*=\s*(?P<q>['\"])(?P<value>(?P=q)|[^'\"]*)(?P=q)")
_WINDOW_OPEN_RE = re.compile(r"(?<![\w$])window\.open\s*\(")

# **残余の受け皿。** SCANNED（構文で開く）と UNSCANNED（正規表現で検出）の
# 2つだけで閉包を作ると、その補集合は常に無検査で、しかも痕跡が残らない。
# 5回連続で同じ型に破られたのはこの構造が原因（gate-verifier 6回目の指摘）。
# 走査ファイル中の「backend の URL らしき記述」を先に全部数え、どの呼び出しにも
# 紐づかなかったものを `unattributed` として必ず出す。
_URL_LITERAL_RE = re.compile(
    r"""(['"`])(?P<value>(?:(?!\1)[^\\]|\\.)*?)\1""", re.DOTALL)
_BACKEND_URL_HINT = re.compile(r"(?:^|[^\w])/api/|ws://|wss://|http://localhost")
# 残余を数えるときコメントは外す。コメントは実行されないので呼び出しではない。
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# `const API_BASE = "http://localhost:8000";` と
# `const url = ` + backtick + `${API_BASE}/api/segments?t=${t}` + backtick + `;`。
# **ファイル内で1度しか代入されていない名前だけ**を辞書に入れる。
# 2度以上代入される名前は、どちらの値で叩くのか静的に決まらないので解決しない。
_ASSIGN_RE = re.compile(
    r"(?<![\w.$])(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?P<value>'[^'\n]*'|\"[^\"\n]*\"|`[^`]*`)",
)
# 上の形以外での再代入。1つでもあればその名前は解決しない（fail-closed）。
# 複合代入（`+=` `||=` `??=` …）も再代入。素の `=` だけ見ていると
# `BASE += '/x'` が素通りして**古い値のまま matched に混ざる**
# （gate-verifier 1回目の指摘）。
_REBIND_RE = re.compile(
    r"(?<![\w.$])(?P<name>[A-Za-z_$][\w$]*)\s*(?:\*\*|[+\-*/%&|^]|<<|>>>?|\|\||&&|\?\?)?=(?!=)")
# 分割代入（`[BASE] = [...]` / `({BASE} = ...)`）と関数の仮引数。
# どちらもその名前を別の値に束ね直すので、辿ってはいけない。
_DESTRUCTURE_RE = re.compile(r"[\[{]([^\]}]*)[\]}]\s*=(?!=)")
_PARAMS_RE = re.compile(
    r"(?:function\s*[\w$]*\s*\(([^)]*)\)|\(([^)]*)\)\s*=>|(?<![\w.$])([A-Za-z_$][\w$]*)\s*=>)")
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
    UNSCANNED_FORM = "unscanned_form"
    UNATTRIBUTED = "unattributed"


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
    Verdict.UNSCANNED_FORM: {
        "確かめること": f"走査できない形（{'・'.join(UNSCANNED_FORMS)}）で "
                        "backend を叩いている",
        "確かめないこと": "その呼び出し先が実在するか（読めていない）",
        "PASS": "no",
    },
    Verdict.UNATTRIBUTED: {
        "確かめること": "backend の URL らしき記述があるのに、"
                        "どの呼び出しにも紐づけられなかった",
        "確かめないこと": "それが実際に呼ばれるか・どの形で呼ばれるか",
        "PASS": "no",
    },
}

# C-2 が名指しする「突き合わない」3型。**ここがゼロになることが終了条件。**
# 「読めなかった」（unresolved_*・unscanned_form・external_host）は別枠にする——
# 同じ袋に入れると、読めない書き方に逃がすだけでゼロにできてしまう。
MISMATCH_VERDICTS = frozenset({
    Verdict.NOT_DECLARED, Verdict.METHOD_MISMATCH, Verdict.NOT_REGISTERED,
})

# 走査している形も機械可読に持つ。散文にだけ書くと、形が増えたときに
# 「対応していないから見えない」が「問題なし」に混ざる。
# **この3つはラチェットのベースラインに固定する** — 緩めるだけで unresolved を
# matched に変えられてはいけない（gate-verifier 2回目の指摘）。
SCAN_SEMANTICS = {
    "走査するファイル": [f"frontend/src/**/*{s}" for s in SCANNED_SUFFIXES]
                        + ["frontend/index.html", "frontend/vite.config.*",
                           "frontend/public/**"],
    "走査する形": list(SCANNED_FORMS),
    "走査できない形": sorted(UNSCANNED_FORMS),
    "素の呼び出しとして扱う受け側": list(_GLOBAL_RECEIVERS),
    "走査できない形の扱い": "unscanned_form の FAIL にする。PASS にはしない。"
                            "ゲートの exit を決めるのは『突き合わせの対象』の3型で、"
                            "読めなかったものはラチェットが1件ずつ固定する"
                            "（新規に増えれば unpinned_new で CI が落ちる）",
    "突き合わせの対象": sorted(v.value for v in MISMATCH_VERDICTS),
    "残余の扱い": "走査ファイル中の backend URL らしき記述で、どの呼び出しにも"
                  "紐づかなかったものは unattributed の FAIL にする。"
                  "**走査する形と走査できない形の補集合を無検査にしない**",
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
        # 意味表を唯一の出どころにする。ここを独立に持つと、
        # 「PASS 扱いを広げた」がラチェットの監視の外で起きる
        # （gate-verifier 1回目の指摘）。
        return VERDICT_SEMANTICS[self.verdict]["PASS"] == "yes"

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
        """**突き合わせた結果、合わなかったもの。ゼロになることが C-2。**

        「読めなかったもの」は別（`unresolved`）。混ぜると、読めない書き方に
        逃がすだけでゼロにできてしまう。
        """
        return [s for s in self.sites if s.verdict in MISMATCH_VERDICTS]

    @property
    def unresolved(self) -> list[FetchSite]:
        """**読めなかったもの。** PASS ではない。ゼロは要求しないが、
        ラチェットで1件ずつ固定して黙って増減できないようにする。"""
        return [s for s in self.sites
                if not s.passed and s.verdict not in MISMATCH_VERDICTS]

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
    # 分割代入と仮引数は「別の値に束ね直す」。辿れば古い値で解決してしまう。
    rebound = set()
    for m in _DESTRUCTURE_RE.finditer(text):
        rebound |= set(re.findall(r"[A-Za-z_$][\w$]*", m.group(1)))
    for m in _PARAMS_RE.finditer(text):
        group = next((g for g in m.groups() if g), "")
        rebound |= set(re.findall(r"[A-Za-z_$][\w$]*", group))
    return {n: v for n, v in values.items()
            if counts.get(n) == 1 and n not in rebound}


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


def _all_form_hits(text: str):
    """走査対象・走査できない形を問わず、URL を運びうる記述をすべて拾う。

    到達不能ファイルの計上に使う。ここが走査側と別の集合になっていると、
    「到達不能にすれば消える」経路がそのまま残る。
    """
    detectors = [
        ("fetch", _FETCH_RE), ("WebSocket", _WEBSOCKET_RE),
        ("window.open", _WINDOW_OPEN_RE),
        ("URL 属性", _URL_ATTR_RE), ("URL 属性", _URL_ATTR_STR_RE),
        *UNSCANNED_FORMS.items(),
    ]
    seen: set[tuple[str, int]] = set()
    for label, pattern in detectors:
        for hit in pattern.finditer(text):
            if (label, hit.start()) in seen:
                continue
            seen.add((label, hit.start()))
            yield label, hit


def _strip_comments(text: str) -> str:
    """コメントを同じ長さの空白に置き換える。位置はずらさない。

    **文字列の中の `//` をコメント開始と誤読しない。**
    `"http://localhost:8000"` を壊すと、以降の引用符の対応が総崩れになる。
    """
    out = list(text)
    i, n = 0, len(text)
    quote: str | None = None
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            i += 1
            continue
        if text.startswith("//", i):
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            for j in range(i, end):
                if out[j] != "\n":
                    out[j] = " "
            i = end
            continue
        i += 1
    return "".join(out)


def _is_backend_url(url: str) -> bool:
    """backend を叩く URL か。ローカル資産と外部リンクを判定に載せない。"""
    if url.startswith(("http://", "https://", "ws://", "wss://")):
        host = url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
        return host in _LOCAL_HOSTS
    return url.startswith("/api")


def _receiver_before(text: str, index: int) -> str | None:
    """`fetch(` の直前の受け側。素の `fetch(` なら None。"""
    hit = _RECEIVER_RE.search(text[max(0, index - 80):index])
    return hit.group(1) if hit else None


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


def _resolve_method(arg: str | None,
                    env: dict[str, str] | None = None) -> tuple[str | None, str]:
    """第2引数から HTTP メソッドを読む。読めなければ (None, 理由)。

    **オブジェクトリテラルでなければ GET と断定しない。** `fetch(url, opts)` の
    `opts` を読まずに GET を主張すると、実体が DELETE でも GET の宣言に
    当たって matched になる（gate-verifier 6回目の指摘）。URL 側は解決できな
    ければ必ず unresolved に落とすのに、メソッド側だけ既定値を主張していた。
    """
    if arg is None or not arg.strip():
        return "GET", ""  # 第2引数が無いときだけが fetch の既定
    arg = arg.strip()
    if not (arg.startswith("{") and arg.endswith("}")):
        # 名前なら、URL と同じく「1度しか代入されていない」ときだけ辿る。
        bound = (env or {}).get(arg)
        if bound is not None:
            return _resolve_method(bound, None)
        return None, f"第2引数がオブジェクトリテラルでない（{_short(arg)}）"
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
    if not url.startswith(("http://", "https://", "ws://", "wss://")):
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
                    routers_dir: Path | None = None,
                    main_files: list[Path] | None = None) -> tuple[str, set[str]]:
    """`APIRouter(prefix="/api/v1")` 配下に再マウントされたルーターを読む。

    EndpointRegistry はルーター自身の prefix しか見ないので、
    `/api/v1/themes/recommend` は「宣言が無い」に見える。実際には在る。

    **プレフィクス付きの APIRouter がこのファイルに1つのときだけ**解決する。
    2つ以上（v1 と v2 など）あればどちらに載ったか静的に決まらないので
    何も返さない——推測して緑にするより、宣言が無いものとして FAIL に落とす。

    **そのルーター自身がアプリに `include_router` されていることも要求する。**
    ここを見ないと、`app.include_router(v1_router)` を外して全部 404 になっても
    緑のままになる（gate-verifier 1回目の指摘）。ルーターに載せた事実と
    アプリに載せた事実は別で、片方だけ見るのは fail-open。
    """
    if not app_file.exists():
        return "", set()
    try:
        tree = ast.parse(app_file.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return "", set()

    prefixed = {
        node.targets[0].id: kw.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and _callee_name(node.value.func) == "APIRouter"
        for kw in node.value.keywords
        if kw.arg == "prefix" and isinstance(kw.value, ast.Constant)
        and isinstance(kw.value.value, str) and kw.value.value
    }
    if len(set(prefixed.values())) != 1:
        return "", set()
    router_name, raw_prefix = next(iter(prefixed.items()))
    prefix = _normalise(raw_prefix)

    # そのルーターがアプリ本体に載っているか。載っていなければ配下は全部 404。
    if not _mounted_on_app(router_name, main_files or []):
        return "", set()

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


def _app_mounted(main_files: list[Path]) -> set[str]:
    """`app.include_router(x)` の x を集める。**受け側を app に限る。**

    `EndpointSite.registered` は受け側を問わず `*.include_router()` を数えるので、
    `v1.include_router(pipeline_router)` があるだけで「/api/... にも登録済み」に
    なってしまう。`app.include_router(pipeline_router)` を消しても
    /api/pipeline/... が緑のままだった（gate-verifier 2回目の指摘・83件中51件）。
    ルート直下に載っている事実と、バージョン配下に載っている事実は別物。
    """
    mounted: set[str] = set()
    for path in main_files:
        path = Path(path)
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if _callee_name(node.func) != "include_router":
                continue
            if not (isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "app"):
                continue
            if isinstance(node.args[0], ast.Name):
                mounted.add(node.args[0].id)
    return mounted


def _mounted_on_app(router_name: str, main_files: list[Path]) -> bool:
    return router_name in _app_mounted(main_files)


def _module_aliases(routers_dir: Path) -> dict[str, str]:
    """{モジュール名: 別名}。別名でしかマウントを書けないので要る。"""
    return _router_aliases(Path(routers_dir) / "__init__.py")


# --- 走査 ---------------------------------------------------------------------


class UiApiExecutor:
    """frontend の fetch 呼び出しと、ルーター定義の宣言を突き合わせる。"""

    def __init__(self, frontend_src: Path, registry: EndpointRegistry,
                 entry: Path | None = None,
                 version_prefix: str = "", version_modules: set[str] | None = None,
                 root_modules: set[str] | None = None):
        self.frontend_src = Path(frontend_src)
        self.registry = registry
        if entry is None:
            candidate = self.frontend_src / "main.jsx"
            entry = candidate if candidate.exists() else None
        self.entry = entry
        self.version_prefix = version_prefix
        self.version_modules = version_modules or set()
        # ルート直下（/api/...）に載っているモジュール。None なら未判定で、
        # EndpointSite.registered に従う（受け側を問わない緩い判定）。
        self.root_modules = root_modules

    @classmethod
    def for_repo(cls) -> UiApiExecutor:
        root = _project_root()
        backend = root / "backend"
        mains = [backend / "main.py", backend / "api_versioning.py"]
        prefix, modules = _version_mounts(
            backend / "api_versioning.py", backend / "routers", main_files=mains)
        mounted = _app_mounted(mains)
        aliases = _module_aliases(backend / "routers")
        return cls(frontend_src=root / "frontend" / "src",
                   registry=EndpointRegistry.for_repo(),
                   version_prefix=prefix, version_modules=modules,
                   root_modules={module for module, alias in aliases.items()
                                 if alias in mounted})

    def run(self) -> UiApiReport:
        report = UiApiReport(endpoints_scanned=len(self.registry.endpoints))
        reachable = _reachable_files(self.entry) if self.entry else None
        shapes = self._shape_index()

        for path in self._iter_files():
            # **コメントは先に外す。** 検出を生テキストに対して行うと、
            # コメントアウトされた呼び出しを実在の呼び出しとして数える。
            text = _strip_comments(
                path.read_text(encoding="utf-8", errors="replace"))
            rel = _display_path(path, self.frontend_src)
            # モジュールでないもの（index.html・CSS）は import で辿れないので
            # 到達可能性の対象外。**走査しないのではなく、常に走査する。**
            if path.suffix in _NON_MODULE_SUFFIXES:
                report.files_scanned += 1
                for site in self._sites_in(text, _assignments(text), rel, shapes):
                    report.sites.append(site)
                continue
            if reachable is not None and path.resolve() not in reachable:
                # **走査するすべての形を数える。** fetch と WebSocket だけを
                # 数えていたので、到達不能ファイルに置いた URL 属性・
                # window.open・走査できない形は unreachable にすら計上されず
                # 無痕跡で消えていた（gate-verifier 5回目の指摘）。
                for label, hit in _all_form_hits(text):
                    report.unreachable.append(
                        f"{rel}:{text.count(chr(10), 0, hit.start()) + 1}"
                        f"  {label}")
                continue
            report.files_scanned += 1
            for site in self._sites_in(text, _assignments(text), rel, shapes):
                report.sites.append(site)
        return report

    def _iter_files(self):
        """走査するファイル。**executor の走査範囲より広い。**

        `.mjs` は `_reachable_files` が到達可能と判定するのに
        `_iter_source_files` の拡張子リストから漏れて完全に消えていた。
        `index.html` と CSS は一度も開かれておらず、`SCAN_SEMANTICS` が
        「CSS の url() は走査できない形」と宣言しているのに CSS を読んでも
        いなかった（gate-verifier 4回目の指摘）。
        """
        seen = set()
        for suffix in SCANNED_SUFFIXES:
            for path in sorted(self.frontend_src.rglob(f"*{suffix}")):
                if not path.is_file() or _EXCLUDED_DIRS & set(path.parts):
                    continue
                seen.add(path)
                yield path
        # src の外。エントリ HTML・ビルド設定（proxy や define で URL を
        # 注入できる）・public 配下。走査対象でも「走査できない形」でもない
        # 未申告領域を作らない（gate-verifier 5回目の指摘）。
        root = self.frontend_src.parent
        for name in ("index.html", "vite.config.js", "vite.config.ts",
                     "vite.config.mjs", "vite.config.cjs"):
            candidate = root / name
            if candidate.is_file() and candidate not in seen:
                seen.add(candidate)
                yield candidate
        for path in sorted((root / "public").rglob("*")):
            if (path.is_file() and path.suffix in SCANNED_SUFFIXES
                    and not _EXCLUDED_DIRS & set(path.parts)
                    and path not in seen):
                seen.add(path)
                yield path

    def _shape_index(self) -> dict[tuple[str, str], list]:
        """(メソッド, 形) → 宣言。パスパラメータ名の違いを吸収する。"""
        index: dict[tuple[str, str], list] = {}
        for (method, path), endpoint in self.registry.endpoints.items():
            index.setdefault((method, _param_shape(path)), []).append(endpoint)
        return index

    @staticmethod
    def _lookup(shapes: dict, method: str, shape: str) -> list:
        """宣言を探す。**セグメント単位で、非対称に照合する。**

        - フロントのリテラルは、同じリテラルにも宣言のパラメータにも当たる
          （`/stream/preview` は `/stream/{video_type}` で実際に応答する）
        - フロントのプレースホルダは**宣言のパラメータにしか当たらない**。
          リテラルのセグメントには化けさせない

        完全一致を先に見て、無ければパラメータ込みで探す。より具体的な
        （リテラルが多く一致する）宣言を優先する。
        """
        exact = shapes.get((method, shape))
        if exact:
            return exact
        wanted = shape.strip("/").split("/")
        best: tuple[int, list] | None = None
        for (m, candidate), hits in shapes.items():
            if m != method:
                continue
            parts = candidate.strip("/").split("/")
            if len(parts) != len(wanted):
                continue
            literals = 0
            for front, declared in zip(wanted, parts):
                if declared == _PARAM:
                    continue  # 宣言側がパラメータなら何でも受ける
                if front == _PARAM or front != declared:
                    break     # プレースホルダはリテラルに当たらない
                literals += 1
            else:
                if best is None or literals > best[0]:
                    best = (literals, hits)
        return best[1] if best else []

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
        hits = [e for e in self._lookup(shapes, method, bare)
                if e.module in self.version_modules]
        return hits, bare if hits else shape

    def _sites_in(self, text: str, constants: dict[str, str], rel: str,
                  shapes: dict) -> list[FetchSite]:
        found: list[FetchSite] = []
        # どの範囲を「呼び出しとして読んだ」か。残余の判定に使う。
        covered: list[tuple[int, int]] = []

        def line_of(index: int) -> int:
            return text.count("\n", 0, index) + 1

        def cover(start: int, end: int) -> None:
            covered.append((start, end))

        # `const API_BASE = "http://localhost:8000"` は**宣言**であって
        # 呼び出しではない。解決に使われる値なので残余から外す。
        for hit in _ASSIGN_RE.finditer(text):
            cover(hit.start("value"), hit.end("value"))

        for pattern, method in ((_FETCH_RE, None), (_WEBSOCKET_RE, "WEBSOCKET")):
            for hit in pattern.finditer(text):
                open_index = hit.end() - 1
                line = line_of(hit.start())
                receiver = _receiver_before(text, hit.start())
                if receiver is not None and receiver not in _GLOBAL_RECEIVERS:
                    # `res.fetch(` のような未知の受け側。ネットワーク呼び出しか
                    # どうかを静的に決められないので、素通りさせずに出す。
                    args = _match_args(text, open_index)
                    cover(hit.start(),
                          open_index + len(args or "") + 2)
                    found.append(FetchSite(
                        rel, line, f"{receiver}.fetch(", None, None,
                        Verdict.UNRESOLVED_URL, f"受け側が未知（{receiver}.fetch）"))
                    continue
                args = _match_args(text, open_index)
                if args is None:
                    found.append(FetchSite(
                        rel, line, _short(text[hit.start():hit.start() + 60]),
                        None, None, Verdict.UNRESOLVED_URL,
                        "引数の括弧が閉じていない"))
                    continue
                cover(hit.start(), open_index + len(args) + 2)
                parts = _split_top_level(args)
                found.append(self._judge(parts, constants, rel, line, shapes,
                                         forced_method=method,
                                         env=constants))

        # ブラウザが GET を投げる URL 属性と window.open。
        # ローカルの画像などは backend への呼び出しではないので、
        # **backend のパスに解決できたものだけ**を判定に載せる。
        # 解決できないものは「backend かもしれない」ので unresolved に落とす。
        for pattern, arg_open in ((_URL_ATTR_RE, "{"), (_WINDOW_OPEN_RE, "("),
                                  (_URL_ATTR_STR_RE, "s")):
            for hit in pattern.finditer(text):
                line = line_of(hit.start())
                if arg_open == "s":
                    # 引用符ごと渡す。中身だけ渡すと文字列リテラルに見えない。
                    quote = hit.group("q")
                    expr = f"{quote}{hit.group('value')}{quote}"
                    cover(hit.start(), hit.end())
                else:
                    body = _match_args(text, hit.end() - 1)
                    if body is None:
                        continue
                    cover(hit.start(), hit.end() + len(body) + 1)
                    expr = _split_top_level(body)[0] if arg_open == "(" else body
                url, why = _resolve_url(expr, constants)
                if url is None:
                    # **読めないものを「backend ではない」と決めつけない。**
                    # ここで黙って落とすと、SCANNED_FORMS の申告が実際の走査より
                    # 広くなる（gate-verifier 3回目の指摘）。
                    found.append(FetchSite(
                        rel, line, _short(expr), None, None,
                        Verdict.UNRESOLVED_URL, why))
                    continue
                if not _is_backend_url(url):
                    continue  # 解決できて、backend でないと分かったものだけ外す
                found.append(self._judge([expr], constants, rel, line, shapes,
                                         forced_method="GET"))

        # 走査できない形。**実在したら FAIL。**「対応していないから見えない」を
        # 「問題なし」に混ぜない。
        for name, pattern in UNSCANNED_FORMS.items():
            for hit in pattern.finditer(text):
                end_of_line = text.find(chr(10), hit.start())
                cover(hit.start(), end_of_line if end_of_line != -1 else len(text))
                found.append(FetchSite(
                    rel, line_of(hit.start()), name, None, None,
                    Verdict.UNSCANNED_FORM, f"{name} は走査できない"))

        found += self._residual(text, covered, rel, line_of)
        return found

    @staticmethod
    def _residual(text: str, covered: list[tuple[int, int]], rel: str,
                  line_of) -> list[FetchSite]:
        """**どの呼び出しにも紐づかなかった backend の URL。**

        SCANNED と UNSCANNED の2集合だけで閉包を作ると、補集合は常に
        無検査で痕跡も残らない。ここが残余の受け皿（gate-verifier 6回目の指摘）。
        コメントは走査の入口で外してあるので、ここには来ない。
        """
        out: list[FetchSite] = []
        for hit in _URL_LITERAL_RE.finditer(text):
            value = hit.group("value")
            if not _BACKEND_URL_HINT.search(value):
                continue
            start = hit.start()
            if any(lo <= start <= hi for lo, hi in covered):
                continue
            out.append(FetchSite(
                rel, line_of(start), _short(value), None, None,
                Verdict.UNATTRIBUTED,
                "backend の URL らしき記述が、どの呼び出しにも紐づかない"))
        return out

    def _judge(self, parts: list[str], constants: dict[str, str], rel: str,
               line: int, shapes: dict,
               forced_method: str | None = None,
               env: dict[str, str] | None = None) -> FetchSite:
        raw = _short(parts[0]) if parts else ""
        url, why = _resolve_url(parts[0] if parts else "", constants)
        if url is None:
            return FetchSite(rel, line, raw, None, None, Verdict.UNRESOLVED_URL, why)

        stripped, why = _strip_origin(url)
        if stripped is None:
            return FetchSite(rel, line, raw, None, None, Verdict.EXTERNAL_HOST, why)
        path = _normalise(stripped.split("?", 1)[0].split("#", 1)[0])

        if forced_method:
            method, why = forced_method, ""
        else:
            method, why = _resolve_method(
                parts[1] if len(parts) > 1 else None, env)
        if method is None:
            return FetchSite(rel, line, raw, path, None,
                             Verdict.UNRESOLVED_METHOD, why)

        shape = _param_shape(path)
        hits = self._lookup(shapes, method, shape)
        under_version = False
        if not hits:
            hits, shape = self._under_version(shape, method, shapes)
            under_version = bool(hits)
        if not hits:
            other = sorted({m for (m, s) in shapes if s == shape})
            if other:
                return FetchSite(rel, line, raw, path, method,
                                 Verdict.METHOD_MISMATCH,
                                 f"宣言されているのは {'/'.join(other)} のみ")
            return FetchSite(rel, line, raw, path, method, Verdict.NOT_DECLARED,
                             "どのルーターにも宣言が無い")

        registered = [e for e in hits if self._registered(e, under_version)]
        if not registered:
            where = (f"{self.version_prefix} 配下" if under_version else "ルート直下")
            return FetchSite(rel, line, raw, path, method, Verdict.NOT_REGISTERED,
                             f"{hits[0].module} が {where}に登録されていない",
                             hits[0].as_evidence())
        return FetchSite(rel, line, raw, path, method, Verdict.MATCHED, "",
                         registered[0].as_evidence())

    def _registered(self, endpoint, under_version: bool) -> bool:
        """**そのパスで呼べるように登録されているか。**

        `/api/v1/...` は再マウント先に、`/api/...` はルート直下に載っている
        必要がある。どちらか一方に載っていれば良い、にすると
        `app.include_router(pipeline_router)` を消しても
        `/api/pipeline/...` が緑のままになる（gate-verifier 2回目の指摘）。
        """
        if under_version:
            return endpoint.module in self.version_modules
        if self.root_modules is None:
            return endpoint.registered is not False
        return endpoint.module in self.root_modules


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

    def detail(site: FetchSite) -> list[str]:
        return [f"    {site.file}:{site.line}  {site.verdict.value}",
                f"      {site.method or '?'} {site.path or site.raw_url}"
                + (f"  — {site.reason}" if site.reason else "")]

    unread = report.unresolved
    if unread:
        lines.append(f"  読めなかった呼び出し: {len(unread)} 件（PASS にしていない）")
        for site in unread:
            lines += detail(site)
        lines.append("")

    bad = report.mismatched
    lines.append(f"  突き合わない呼び出し: {len(bad)} 件")
    if not bad:
        lines.append("    なし。すべての呼び出し先が、宣言され登録されたハンドラに届いている。")
    for site in bad:
        lines += detail(site)
    return "\n".join(lines)


def _format_list(report: UiApiReport) -> str:
    """**列挙そのものを出す。** 集計だけでは何を測ったか読めない。"""
    lines = [f"呼び出し先 {len(report.sites)} 件", ""]
    for site in sorted(report.sites, key=lambda s: (s.file, s.line)):
        lines.append(
            f"  {site.file}:{site.line:<5} {site.verdict.value:<16} "
            f"{site.method or '?':<9} {site.path or site.raw_url}")
        if site.declared_at:
            lines.append(f"      ← {site.declared_at}")
        elif site.reason:
            lines.append(f"      — {site.reason}")
    if report.unreachable:
        lines += ["", f"到達不能で判定していない: {len(report.unreachable)} 件"]
        lines += [f"  {site}" for site in report.unreachable]
    return "\n".join(lines)


def _format_semantics() -> str:
    lines = ["判定ごとに『確かめること／確かめないこと』", ""]
    for verdict, meaning in VERDICT_SEMANTICS.items():
        lines.append(f"  {verdict.value}  （PASS: {meaning['PASS']}）")
        lines.append(f"    確かめる  : {meaning['確かめること']}")
        lines.append(f"    確かめない: {meaning['確かめないこと']}")
        lines.append("")
    # 走査の境界も出す。持っているだけでどこも読まないなら、
    # 機械可読とは言えない（gate-verifier 2回目の指摘）。
    lines.append("走査の境界")
    for key, value in SCAN_SEMANTICS.items():
        rendered = "・".join(value) if isinstance(value, list) else value
        lines.append(f"    {key}: {rendered}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UI と API の接続を静的に突き合わせる")
    parser.add_argument("--gate", action="store_true",
                        help="突き合わない呼び出しが1件でもあれば exit 1")
    parser.add_argument("--list", action="store_true", dest="list_sites",
                        help="読み取った呼び出し先を1件ずつ列挙する")
    parser.add_argument("--semantics", action="store_true",
                        help="判定ごとの『確かめること／確かめないこと』と走査の境界を出す")
    args = parser.parse_args(argv)

    if args.semantics:
        print(_format_semantics())
        return 0

    report = UiApiExecutor.for_repo().run()
    print(_format_list(report) if args.list_sites else _format(report))

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
        # **「全部 OK」と言わない。** 読めなかったものは突き合わせていない。
        matched = len(report.sites) - len(report.unresolved)
        note = (f"（読めなかった {len(report.unresolved)} 件は突き合わせていない）"
                if report.unresolved else "")
        print(f"\n✅ 読み取れた {matched} 件はすべて宣言と突き合っています{note}。")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
