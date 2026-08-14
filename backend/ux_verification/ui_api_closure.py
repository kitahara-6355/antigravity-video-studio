"""呼び出し口の閉包（P5 C-1・C-2・C-3・C-4・C-5）。

`ui_api` は「フロントが叩いている先が実在するか」を測る。それだけでは
**見落とした呼び出し**を止められない。P4 は14回破られ、9回目以降の指摘は
すべて `_strip_comments`（JavaScript をスキャナで読む部分）に集中した。
原因は構造的で、散らばった呼び出しの URL を1件ずつ**正しく解決する**という
仕事が**精度を要求する**ことにある。精度を要求する判定は、読み違いが黙って
PASS になる。

**禁止は精度を要求しない。** 呼び出しを1つの扉（`frontend/src/gateway/`）に
集約し、外側は「呼び出しが1件も無い」という禁止にする。誤検出しても FAIL が
増えるだけ（fail-closed）なので、**コメント除去のような前処理が要らない** —
コメント内に書いてあっても落とす。

## 見ているもの

1. **閉包**（C-1）— 扉の外に、呼び出しの形も backend の URL も絶対 URL も
   1件も無い。**コメントを除去せず、生テキストのまま**判定する。
   例外は宣言済みの許可リストだけで、**使われていない許可も違反**にする
2. **カタログの文法**（C-2）— `endpoints.js` は1行1項目の閉じた文法だけ。
   ここから外れた行は項目にならず、行そのものが違反になる。
   突き合わせ（宣言が実在するか）は `ui_api` の担当
3. **使用の解決**（C-3）— 扉の関数を呼ぶとき、宛先はリテラルのキーでなければ
   ならない。カタログに無いキー・計算されたキーは違反。
   **どこからも使われていないカタログ項目も違反**（死蔵の宣言を隠さない）
4. **扉そのものの境界**（C-1）— 扉のファイルは3つだけ。`client.js` に
   書ける URL リテラルは**パスを持たない素のオリジンだけ**

## 確かめないこと（C-4）

`CLOSURE_SEMANTICS` に機械可読で置く。要点は
**「移行した＝正しく繋がっている」ではない**こと。コンポーネントが正しい項目を
選んでいるか・実行時に呼ばれるか・レスポンスを正しく使えているかは
静的には決まらない。ビルドと lint が通ることも動作の保証ではない。

## 守れない範囲（隠さずに書く）

- **トークンを途中で割る難読化は捕まらない。** `globalThis['fet'+'ch']` の
  ように呼び出しの形も URL リテラルも残らない書き方は、禁止語彙が存在検出で
  ある以上ここでも通る（P4 の limits と同じ。**P5 はこれを解決しない**）
- **ベースラインを手で書き換えれば通る。** 書き換えた事実が差分に出ることを
  もって歯止めとする（P3 C-4・P4 と同じ限界）

    python -m backend.ux_verification.ui_api_closure --gate
    python -m backend.ux_verification.ui_api_closure --ratchet
    python -m backend.ux_verification.ui_api_closure --update-baseline
    python -m backend.ux_verification.ui_api_closure --semantics
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.ux_verification.ui_api import (
    _CATALOGUE_ENTRY_RE,
    _EXCLUDED_DIRS,
    _FETCH_RE,
    _PURE_ORIGIN_RE,
    _URL_LITERAL_RE,
    _WEBSOCKET_RE,
    _WINDOW_OPEN_RE,
    CATALOGUE_REL,
    CLIENT_REL,
    GATEWAY_DIR,
    SCANNED_SUFFIXES,
    UNSCANNED_FORMS,
    UiApiExecutor,
)

BASELINE_DIR = Path(__file__).parent / "snapshots"
BASELINE = BASELINE_DIR / "ui_api_closure_baseline.json"

# **走査は frontend/ の全体。** `ui_api._iter_files()` は `frontend/src` と
# index.html / vite.config.* / public/** に固定されているので、
# `frontend/lib/api.js` のように src の外に置いたファイルは、src から import
# されていて実際に実行されるのに**1行も読まれない**まま緑になっていた
# （gate-verifier 3回目の実測反例。4ゲートすべて exit 0）。
# 拡張子でも絞らない — `.mts` が抜けていて同じ穴になっていた。
#
# 読まない場所は**宣言してベースラインに固定する**。ここに1つ足せば
# ラチェットが落ちる。
# **frontend からの相対パスの完全一致**で宣言する。ディレクトリ名で
# 任意階層に効かせていたので、`frontend/src/components/build/` を作るだけで
# そこが無検査になっていた（gate-verifier 5回目の実測反例。**コードも
# ベースラインも一切触らずに**4ゲート全緑、vite build も成功して
# dist に生の fetch が出た）。
#
# 足せばラチェット（`closure_excluded`）が落とす。実在しない名前を足すことも
# 同じく落ちるので、「実在しない除外は違反」という判定は置かない
# （`node_modules` / `dist` は gitignore 対象で CI に存在せず、偽の赤になる）。
CLOSURE_EXCLUDED = frozenset({"node_modules", "dist"})
# ファイル単位の除外。**ソースとして実行されないもの**だけ。
CLOSURE_EXCLUDED_FILES = frozenset({"package-lock.json"})
# **バイナリとして宣言した拡張子。** 中身は走査しないが、**本当にその形式で
# あることを先頭バイトで確かめる。**
#
# もともとは「読まない拡張子」を綴りで並べ、そこに JS を書いてコードに戻す道
# （`?raw` / `new Function`）を綴りで禁止していた。**これは綴りのいたちごっこで、
# `import.meta.glob({as:'raw'})` と素の `Function(` の2点だけで破られた**
# （gate-verifier 6回目の実測。vite build が通り dist に生の fetch が出た）。
#
# 綴りを増やすのをやめ、**除外の正当性そのものを検証する**。
# 「バイナリだから読まない」のなら、バイナリであることを確かめればよい。
# JS を書いた `.png` はマジックバイトに合わないので違反になり、
# 中身を取り出す道が何であっても成立しない。
#
# ここに拡張子を足すにはマジックバイトも書く必要がある。ベースラインに固定
# してあるので、足せばラチェットが落ちる。
CLOSURE_BINARY_SUFFIXES = frozenset({".png"})
# 許すマジックバイト。**拡張子ではなく実体で確かめる。**
# このリポジトリの `*.png` は中身が JPEG（JFIF）だった — 拡張子は嘘をつく。
# 画像であることさえ確かめられれば、そこに JS を書いて取り出す道は成立しない。
CLOSURE_BINARY_MAGICS: dict[str, str] = {
    "PNG": "89504e470d0a1a0a",
    "JPEG": "ffd8ff",
    "GIF87a": "474946383761",
    "GIF89a": "474946383961",
    "WEBP": "52494646",
}

# 扉に置いてよいファイル。**ここに無いファイルは第2の扉**なので違反にする。
ALLOWLIST_REL = f"{GATEWAY_DIR}/external_urls.json"
GATEWAY_FILES = (CATALOGUE_REL, CLIENT_REL, ALLOWLIST_REL)

# 扉の外で禁止する呼び出しの形。**`ui_api` の検出器をそのまま借りる** —
# 別に書き起こすと、片方を緩めてももう片方が気づかない。
#
# **1つも外さない。** かつて「合成された URL」（`String.fromCharCode(` /
# `atob(` / `decodeURIComponent(` / `].join(`）を「文字列を作る形であって
# 呼び出しの形ではない。閉包では呼び出しの形を1つ残らず禁止しているので
# 渡す先が無い」という理由で外していたが、**この理由は誤りだった**。
#
# 渡す先はある — **URL 属性**（`src={expr}`）は禁止の対象外なので、
# `<img src={['', 'api', 'tasks'].join('/')} />` は実際に backend へ GET を
# 投げるのに、外した状態では閉包ゲートを素通りした（gate-verifier 1回目の
# 実測反例 A1）。外したことで検出は確かに1つ減っていた。
#
# 誤検出（URL と無関係な `String.fromCharCode(65 + i)` など）は起きるが、
# **それは FAIL が増えるだけで沈黙にはならない。** 禁止をすり抜ける方が重い。
_NOT_A_CALL_FORM: tuple[str, ...] = ()

# 閉包にだけある禁止。**走査から外した中身を、コードに戻す道を塞ぐ。**
# `.png` を読まない宣言をしたので、そこに JS を書いて
# `import payload from './x.png?raw'` + `new Function(payload)` で実行できた
# （gate-verifier 5回目の実測反例。vite build が通り dist に fetch が出た）。
# 除外した拡張子を読むようにすると誤検出だらけになるので、
# **中身を文字列として持ち出す道と、文字列をコードにする道**を禁止する。
_CLOSURE_ONLY_FORMS: dict[str, re.Pattern] = {
    "?raw インポート": re.compile(r"\?raw(?![\w])"),
    # `new` の有無を問わない。素の `Function(` で回避されていた（6回目）。
    "文字列をコードにする": re.compile(
        r"(?<![\w.$])(?:new\s+)?(?:Function|eval)\s*\("),
    "文字列を実行する遅延": re.compile(
        r"(?<![\w.$])set(?:Timeout|Interval)\s*\(\s*['\"`]"),
}
FORBIDDEN_FORMS: dict[str, re.Pattern] = {
    "fetch": _FETCH_RE,
    "new WebSocket": _WEBSOCKET_RE,
    "window.open": _WINDOW_OPEN_RE,
    **UNSCANNED_FORMS,
    **_CLOSURE_ONLY_FORMS,
}

# 絶対 URL。スキームがあるものは全部。**backend も外部も区別しない** —
# 区別した瞬間「backend かどうか」の判定が要り、そこが精度を要求する場所になる。
_ABSOLUTE_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s'\"`)<>]*")
# `//localhost:8000/api/x`。スキームを省いた絶対 URL で、ブラウザはページと
# 同じスキームで解決する。**スキーム必須にしていたので素通りしていた**
# （gate-verifier 3回目の指摘）。行コメント `// foo` は直後が空白なので当たらない。
_PROTOCOL_RELATIVE_RE = re.compile(
    r"(?<![:\w])//[\w.\-]+(?::\d+)?/[^\s'\"`)<>]*")

# `'/' + 'api' + '/tasks'`。**リテラルだけを `+` でつないだ並び**を丸ごと取る。
# 変数が混ざったら（`'/ap' + kind`）その時点で並びが切れる — 結合できないものを
# 結合したことにしない。
_ONE_LITERAL_RE = re.compile(r"""(['"])((?:(?!\1)[^\\]|\\.)*)\1""")
_JOINED_LITERALS_RE = re.compile(
    r"""(['"])(?:(?!\1)[^\\]|\\.)*\1(?:\s*\+\s*(['"])(?:(?!\2)[^\\]|\\.)*\2)+""")

# カタログの文法。項目行・開始行・終了行・行コメント・空行だけを許す。
_CATALOGUE_OPEN = "export const ENDPOINTS = {"
_CATALOGUE_CLOSE = "};"
_LINE_COMMENT_ONLY = re.compile(r"^\s*//")

# 扉から import する形。**名前つき import だけ。** `import *` や別名を許すと、
# 使用の検出が名前の追跡になり、そこが精度を要求する場所になる。
_GATEWAY_IMPORT_RE = re.compile(
    r"import\s*\{(?P<names>[^}]*)\}\s*from\s*'(?P<spec>(?:\.\./|\./)*"
    + re.escape(GATEWAY_DIR.split('/')[-1]) + r"/client\.js)'")
# 扉に言及する import 行。**行単位で見る。** 位置で突き合わせると、先頭の
# `[^\w]` が直前の改行を食って行番号が1つずれる（実測で見つけた）。
_IMPORTS_SOMETHING_RE = re.compile(r"(?<![\w$])(?:import|require)(?![\w$])")
_GATEWAY_MENTION = GATEWAY_DIR.split("/")[-1] + "/"
_IMPORT_NAME_RE = re.compile(r"^[A-Za-z_$][\w$]*$")

# 扉の関数の呼び出し。第1引数がシングルクォートのリテラルなら宛先が決まる。
def _usage_re(name: str) -> re.Pattern:
    return re.compile(rf"(?<![\w$.]){re.escape(name)}\s*\(\s*(?P<arg>[^),]*)")


# 名前の出現そのもの（呼び出しかどうかを問わない）。**呼ぶ以外の使い方**を
# 見つけるために要る — 変数に束ね直されると使用が判定から消える。
def _bare_name_re(name: str) -> re.Pattern:
    return re.compile(rf"(?<![\w$.]){re.escape(name)}(?![\w$])")


_CALL_AFTER_RE = re.compile(r"\s*\(")


CLOSURE_SEMANTICS = {
    "確かめること": [
        ("呼び出し口（frontend/" + GATEWAY_DIR + "/）の外に、"
         "ネットワーク呼び出しの形が1件も無い（コメント内も含む）"),
        ("呼び出し口の外に、backend のプレフィクスから始まる文字列リテラルが"
         "1件も無い（`/api/x` と `api/x` の両方。**`/` を含まない単語1つは"
         "対象外** — 宣言済みプレフィクスには health / soul / themes のような"
         "普通の英単語が並ぶため）"),
        ("呼び出し口の外に、リテラルを `+` でつないで作った backend の URL が"
         "1件も無い（`'/' + 'api' + '/x'`。**変数を挟んだものは結合できない**）"),
        "呼び出し口の外に、宣言していない絶対 URL が1件も無い",
        ("呼び出し口の関数が、呼び出す以外の使われ方をしていない"
         "（変数に束ね直す・引数として渡す、は使用が判定から消えるので違反）"),
        ("**frontend/ の下を全部読んでいる。** 読むかどうかは**場所と拡張子だけ**で"
         "決めており、**中身では決めない**。読まないのは frontend 直下の "
         "`node_modules` と `dist`（**相対パスの完全一致**。ディレクトリ名で"
         "任意階層に効かせていたので `src/components/build/` を作るだけで"
         "無検査になっていた）、`package-lock.json`、`.md` と `.png`。"
         "宣言はベースラインに固定してあり、1つ足せばラチェットが落ちる"),
        ("frontend/ の下に symlink が無い（走査が降りないので、"
         "あれば違反にする）"),
        ("**走査から外したファイルが、本当に画像である**"
         "（先頭バイトを既知の画像マジックと突き合わせる）。"
         "拡張子は嘘をつくので、外している根拠のほうを確かめる"),
        ("走査したファイルの一覧が固定されている"
         "（走査から外せば、そこの呼び出しは何も出ない）"),
        ("扉の関数の使用が**回数まで**固定されている"
         "（同じキーを何度も呼んでいるとき、何本消しても最後の1本で"
         "黙らないようにするため）"),
        "カタログが1行1項目の閉じた文法だけでできている",
        "呼び出し口の関数の宛先が、すべてカタログのリテラルのキーである",
        "カタログのどの項目も、どこかから使われている",
        "呼び出し口のファイルが宣言した3つだけである",
        "client.js に書かれた URL リテラルが、パスを持たない素のオリジンだけである",
    ],
    "確かめないこと": [
        ("**コンポーネントが正しいカタログ項目を選んでいるか**"
         "（キーが実在することしか見ていない。取り違えは静的には決まらない）"),
        "その呼び出しが実行時に発火するか",
        "レスポンスをフロントが正しく使えているか",
        "リクエスト・レスポンスのスキーマが噛み合うか",
        "ベース URL が本番環境で正しいか",
        ("**URL 属性の式が何を指すか**（`src={thumb.path}` のように "
         "backend のレスポンス由来のことがある。宛先を選んでいるのは "
         "コンポーネントではない）。式の中に backend の URL リテラルが "
         "あれば落ちるが、式そのものは追わない"),
        "カタログの項目が実在する宣言に当たるか（ui_api --gate の担当）",
        ("**ビルドと lint が通ること**（構文と参照解決の保証であって"
         "動作の保証ではない。フロントには CI が無く、手元実行が唯一の証拠）"),
        ("トークンを途中で割る難読化（`globalThis['fet'+'ch']` など）。"
         "**捕まらない。P5 はこれを解決しない**"),
        ("**変数を挟んで組み立てた URL**（`'/ap' + kind` など）。"
         "字句上つながっていないので結合できない。**捕まらない**"),
        ("**実行時に組み立てたコードの実行。** `?raw` インポート・"
         "`Function` / `eval`・文字列を渡す `setTimeout` は禁止しているが、"
         "これは綴りの列挙にすぎない（`import.meta.glob({as:'raw'})` と"
         "素の `Function(` で一度破られた）。**閉包を支えているのは"
         "「全部読む・バイナリは実体を検証する」ほうで、この禁止は"
         "そこに足した保険**。綴りを変えられれば通る"),
        ("`/` を含まない単語1つの相対 URL。普通の英単語と区別が付かないので"
         "対象外にしてある"),
        ("**frontend/ の外**（backend が配信する静的ファイルなど）。"
         "この判定は frontend/ の中しか読まない"),
        ("**宣言した拡張子の中身**（`.md`・`.png`）。走査から外してあること"
         "自体はベースラインに固定してあるので、黙って増やせない"),
    ],
    "判定の性質": "禁止であって解決ではない。誤検出は FAIL を増やすだけで"
                  "沈黙にならないので、コメント除去のような前処理を持たない",
}


@dataclass(frozen=True)
class Finding:
    kind: str
    file: str
    line: int
    excerpt: str
    reason: str

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        return f"[{self.kind}] {where}  {self.excerpt}\n      — {self.reason}"


@dataclass
class ClosureReport:
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    entries: dict[str, str] = field(default_factory=dict)
    # ファイル -> 使っているカタログのキー
    usages: dict[str, list[str]] = field(default_factory=dict)
    allowlist: list[dict] = field(default_factory=list)
    # 実際に読んだファイル。**走査から外れたことを直接見る**ために持つ。
    scanned_files: list[str] = field(default_factory=list)
    # backend URL を見つける検出器の本体。差し替えを検出するために持つ。
    backend_token_pattern: str = ""

    @property
    def closed(self) -> bool:
        return not self.findings

    def used_keys(self) -> set[str]:
        return {key for keys in self.usages.values() for key in keys}


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


class ClosureExecutor:
    """扉の外に呼び出しが無いことを、生テキストの禁止として判定する。"""

    def __init__(self, executor: UiApiExecutor):
        self.executor = executor
        self.frontend = executor.frontend_src.parent
        self.prefixes = executor.backend_prefixes
        self._token_re: re.Pattern | None = None

    @classmethod
    def for_repo(cls) -> ClosureExecutor:
        return cls(UiApiExecutor.for_repo())

    # --- 走査範囲 -----------------------------------------------------------

    def _rel(self, path: Path) -> str:
        """`frontend/` からの相対パス。表示にもベースラインの鍵にも使う。"""
        return path.relative_to(self.frontend).as_posix()

    def _iter_files(self):
        """**frontend/ の下を全部読む。**

        `ui_api._iter_files()` は `frontend/src` と index.html / vite.config.* /
        public/** に固定されている。そこを借りていたので、
        `frontend/lib/api.js` のように src の外に置いたファイルは、src から
        import されていて実際に実行されるのに**1行も読まれない**まま緑だった
        （gate-verifier 3回目の実測反例。4ゲートすべて exit 0）。
        拡張子でも絞らない — `.mts` が抜けていて同じ穴になっていた。

        読まない場所は `CLOSURE_EXCLUDED` / `CLOSURE_EXCLUDED_FILES` に宣言し、
        ベースラインに固定する。**1つ足せばラチェットが落ちる。**
        """
        for path in sorted(self.frontend.rglob("*")):
            rel = self._rel(path)
            if any(rel == name or rel.startswith(name + "/")
                   for name in CLOSURE_EXCLUDED):
                continue
            if not path.is_file():
                continue
            if path.name in CLOSURE_EXCLUDED_FILES:
                continue
            if path.suffix.lower() in CLOSURE_BINARY_SUFFIXES:
                continue  # 実体は _boundary_findings が確かめる
            yield path

    def _boundary_findings(self) -> list[Finding]:
        """走査範囲そのものの異常。**読まなかった事実を残す。**"""
        findings: list[Finding] = []
        # symlink は降りない（Path.rglob の既定）。降りないなら**違反にする** —
        # 黙って読み飛ばすと、リンク先に何を置いても見えない
        # （gate-verifier 5回目の実測反例）。
        for path in sorted(self.frontend.rglob("*")):
            rel = self._rel(path)
            if any(rel == name or rel.startswith(name + "/")
                   for name in CLOSURE_EXCLUDED):
                continue
            if path.is_symlink():
                findings.append(Finding(
                    "symlinked_path", rel, 0, "",
                    "frontend/ の下に symlink があります。走査が降りないので"
                    "リンク先が無検査になります"))
        # **バイナリと宣言した拡張子が、本当にその形式か。**
        # ここが「読まない」ことの唯一の根拠なので、根拠のほうを確かめる。
        # JS を書いた `.png` はここで落ちる（gate-verifier 6回目の反例）。
        for path in sorted(self.frontend.rglob("*")):
            rel = self._rel(path)
            if any(rel == name or rel.startswith(name + "/")
                   for name in CLOSURE_EXCLUDED):
                continue
            if path.suffix.lower() not in CLOSURE_BINARY_SUFFIXES:
                continue
            if not path.is_file():
                continue
            head = path.read_bytes()[:16]
            if not any(head.startswith(bytes.fromhex(magic))
                       for magic in CLOSURE_BINARY_MAGICS.values()):
                findings.append(Finding(
                    "not_really_binary", rel, 0, head[:8].hex(),
                    "バイナリとして走査から外しているのに、既知の画像では"
                    "ありません（中身をコードとして取り出せます）"))

        # **「実在しない除外は違反」は入れない。** 一度入れたが、
        # `node_modules` と `dist` は gitignore 対象で CI には存在しないため
        # 偽の赤になる（実測）。除外を1つ足すことはラチェットの
        # `closure_excluded` が既に落とすので、保護は減らない。
        return findings

    # --- 許可リスト ---------------------------------------------------------

    def _allowlist(self) -> tuple[list[dict], list[Finding]]:
        path = self.frontend / ALLOWLIST_REL
        if not path.is_file():
            return [], [Finding("allowlist_missing", ALLOWLIST_REL, 0, "",
                                "許可リストがありません。"
                                "無い状態を緑にすると、消すだけで例外が"
                                "無制限になります")]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return [], [Finding("allowlist_broken", ALLOWLIST_REL, 0, str(e),
                                "許可リストを読めません")]
        declared = payload.get("declared")
        if not isinstance(declared, list):
            return [], [Finding("allowlist_broken", ALLOWLIST_REL, 0, "",
                                "`declared` が配列ではありません")]
        findings = []
        for entry in declared:
            if not all(isinstance(entry.get(k), str) and entry.get(k)
                       for k in ("url", "file", "why")):
                findings.append(Finding(
                    "allowlist_broken", ALLOWLIST_REL, 0, str(entry)[:60],
                    "url / file / why のいずれかが欠けています"))
        return declared, findings

    # --- 扉の中 -------------------------------------------------------------

    def _check_catalogue(self, raw: str, rel: str) -> tuple[dict[str, str],
                                                            list[Finding]]:
        """1行1項目の閉じた文法だけ。**外れた行は行そのものが違反。**"""
        entries: dict[str, str] = {}
        findings: list[Finding] = []
        seen_open = seen_close = False
        for number, line in enumerate(raw.split("\n"), start=1):
            stripped = line.strip()
            if not stripped or _LINE_COMMENT_ONLY.match(line):
                continue
            if stripped == _CATALOGUE_OPEN:
                seen_open = True
                continue
            if stripped == _CATALOGUE_CLOSE:
                seen_close = True
                continue
            hit = _CATALOGUE_ENTRY_RE.match(line)
            if not hit:
                findings.append(Finding(
                    "catalogue_grammar", rel, number, stripped[:70],
                    "1行1項目の閉じた文法から外れています"
                    "（method / path はシングルクォートのリテラルだけ）"))
                continue
            key = hit.group("key")
            if key in entries:
                findings.append(Finding(
                    "catalogue_duplicate", rel, number, key,
                    "同じキーが2度宣言されています"))
                continue
            entries[key] = f"{hit.group('method')} {hit.group('path')}"
        if not seen_open or not seen_close:
            findings.append(Finding(
                "catalogue_grammar", rel, 0, "",
                "`export const ENDPOINTS = {` と `};` が揃っていません"))
        if not entries:
            findings.append(Finding(
                "catalogue_empty", rel, 0, "",
                "カタログが空です。**0件を緑にしない** — "
                "全部消すだけでゲートが無効になります"))
        return entries, findings

    def _check_client(self, raw: str, rel: str) -> list[Finding]:
        """扉の中で許す URL リテラルは、パスを持たない素のオリジンだけ。"""
        findings = []
        for hit in _URL_LITERAL_RE.finditer(raw):
            value = hit.group("value").strip()
            if not value:
                continue
            if _PURE_ORIGIN_RE.match(value):
                continue
            if _ABSOLUTE_URL_RE.match(value) or self._is_backend_path(value):
                findings.append(Finding(
                    "client_path_literal", rel, _line_of(raw, hit.start()),
                    value[:70],
                    "扉の中に書けるのはパスを持たない素のオリジンだけです"
                    "（パスを書けると、カタログが『叩ける先の全部』でなくなる）"))
        return findings

    def _is_backend_path(self, value: str) -> bool:
        """backend のパスを指すリテラルか。

        **先頭の `/` を要求しない。** `<img src="api/tasks" />` はブラウザが
        相対解決して backend に GET を投げるのに、`/` で始まらないという
        理由だけで素通りしていた（gate-verifier 1回目の実測反例 A3）。

        ただし `/` を1つも含まない単語（`'health'` `'soul'` `'themes'`）は
        対象にしない。宣言済みプレフィクスには普通の英単語が並んでいるので、
        単語1つで落とすと無関係な文字列が大量に FAIL になる。
        **この非対称は穴なので `CLOSURE_SEMANTICS` に書いてある。**
        """
        stripped = value.strip()
        if "/" not in stripped:
            return False
        head = stripped.lstrip("/").split("/", 1)[0].split("?", 1)[0]
        return head in self.prefixes

    # --- 扉の外 -------------------------------------------------------------

    def _check_outside(self, raw: str, rel: str,
                       allowed: set[tuple[str, str]]) -> list[Finding]:
        """**生テキストのまま**判定する。コメントも除去しない。"""
        findings = []
        for name, pattern in sorted(FORBIDDEN_FORMS.items()):
            for hit in pattern.finditer(raw):
                findings.append(Finding(
                    "forbidden_form", rel, _line_of(raw, hit.start()), name,
                    f"呼び出しの形（{name}）は呼び出し口の外に書けません"))
        for pattern in (_ABSOLUTE_URL_RE, _PROTOCOL_RELATIVE_RE):
            for hit in pattern.finditer(raw):
                url = hit.group(0)
                if (rel, url) in allowed:
                    continue
                findings.append(Finding(
                    "external_url", rel, _line_of(raw, hit.start()), url[:70],
                    "宣言していない絶対 URL です"
                    f"（{ALLOWLIST_REL} に理由つきで宣言してください）"))
        # **引用符の対応付けに頼らない。** 文字列リテラルとして拾おうとすると、
        # ファイル内のどこかにあるアポストロフィ1つで対応がずれ、
        # `src="api/tasks"` が巨大な「文字列」の中に飲まれて先頭が
        # backend プレフィクスでなくなる（gate-verifier 1回目の反例 A3 が
        # 素通りした本当の原因はこれだった）。**字句そのものを見る。**
        for hit in self._backend_token_re().finditer(raw):
            findings.append(Finding(
                "backend_url", rel, _line_of(raw, hit.start()),
                hit.group(0)[:70],
                "backend のパスを呼び出し口の外に書けません"))
        findings += self._check_joined_literals(raw, rel)
        return findings

    def _backend_token_re(self) -> re.Pattern:
        """宣言済みプレフィクスで始まるパスの**字句**。

        `/api/x` も `api/x` も拾う。直前が識別子・`.`・`/`・`-` のときは
        拾わない（`foo/api/bar` や `../gateway/` は backend のパスではない）。
        判定基準はプレフィクスの宣言側から導く（P4 の教訓）。
        """
        if self._token_re is None:
            names = "|".join(sorted(re.escape(p) for p in self.prefixes))
            self._token_re = re.compile(
                # 先頭に `/` があるなら、プレフィクス1つで完結していてもよい
                # （`/health` は実在の登録済みエンドポイント）。
                # **`/` を後ろに必須にしていたので `/health` を取りこぼした** —
                # 直前のコミットでは捕まえていたものを、修正が黙って見えなく
                # していた（gate-verifier 2回目の実測反例）。
                # `./api/x` `../api/x` も相対の backend パス。1本の
                # 先読みで書くと `.` に潰されて拾えなかった（3回目の指摘）。
                rf"(?:(?<![\w\-])\.{{0,2}}/(?:{names})(?![\w\-])"
                # 先頭に `/` が無いなら、後ろに `/` を要求する。
                # `health` `soul` `themes` は普通の英単語なので、単語1つでは
                # 落とさない（この非対称は CLOSURE_SEMANTICS に書いてある）。
                # 先頭に `/` が無いなら後ろに `/` を要求する。ただしここは
                # `foo/api/bar` を拾わないよう `/` も先読みで塞ぐ。
                rf"|(?<![\w./\-])(?:{names})/)[\w\-./{{}}]*")
        return self._token_re

    def _check_joined_literals(self, raw: str, rel: str) -> list[Finding]:
        """**リテラルを `+` で割って組み立てた URL。**

        `'/' + 'api' + '/tasks'` は、どの1つを取っても backend のパスに
        見えないので、リテラル単体の禁止をすり抜ける（gate-verifier 1回目の
        実測反例 A2。4ゲートすべてを素通りした）。

        隣り合うリテラルを `+` でつないだ**字句上の**並びだけを結合して判定する。
        変数を挟んだもの（`'/ap' + kind`）は結合できないので**捕まらない** —
        それは `CLOSURE_SEMANTICS` の『確かめないこと』に書いてある。
        字句だけなので誤検出しても FAIL が増えるだけで、沈黙にはならない。
        """
        findings = []
        for hit in _JOINED_LITERALS_RE.finditer(raw):
            pieces = _ONE_LITERAL_RE.findall(hit.group(0))
            if len(pieces) < 2:
                continue
            joined = "".join(piece for _, piece in pieces)
            if self._is_backend_path(joined) or _ABSOLUTE_URL_RE.match(joined):
                findings.append(Finding(
                    "joined_backend_url", rel, _line_of(raw, hit.start()),
                    joined[:70],
                    "リテラルを `+` でつないで backend の URL を作っています"))
        return findings

    # --- 使用（C-3） --------------------------------------------------------

    def _check_usage(self, raw: str, rel: str,
                     entries: dict[str, str]) -> tuple[list[str], list[Finding]]:
        findings: list[Finding] = []
        names: list[str] = []

        # **行単位で見ない。** prettier が標準で折る複数行 import
        #     import {
        #         apiFetch,
        #     } from '../gateway/client.js';
        # を「import 行ではない」と判定してしまい、そのファイルの使用判定が
        # 丸ごと走らなかった（gate-verifier 2回目の実測反例。未知のキーでも
        # 変数キーでも4ゲート全緑だった）。**本文全体に対して照合する。**
        import_spans: set[int] = set()
        for hit in _GATEWAY_IMPORT_RE.finditer(raw):
            import_spans |= set(range(hit.start(), hit.end()))
            for piece in hit.group("names").split(","):
                piece = piece.strip()
                if not piece:
                    continue
                if not _IMPORT_NAME_RE.match(piece):
                    findings.append(Finding(
                        "bad_import", rel, _line_of(raw, hit.start()), piece,
                        "扉からの import は名前つきのみ（別名・`import *` は不可）"))
                    continue
                names.append(piece)

        # **扉に言及してよいのは、正当な import の内側だけ。**
        # `export { apiFetch } from '../gateway/client.js'` のような再輸出は
        # `import` という語を含まないので import の検査を素通りし、
        # 別ファイル経由の呼び出しを作れていた（同じく2回目の実測反例）。
        # コメントでの言及も違反にする — 例外を作れば、そこが精度を要求する。
        for hit in re.finditer(re.escape(_GATEWAY_MENTION), raw):
            if hit.start() in import_spans:
                continue
            findings.append(Finding(
                "bad_import", rel, _line_of(raw, hit.start()),
                raw[hit.start():hit.start() + 60].split("\n")[0],
                "呼び出し口への言及は `import { … } from '…/client.js'` の"
                "形だけです（再輸出・別名・コメントでの言及も不可）"))

        used: list[str] = []
        for name in names:
            # **扉の関数は「呼ぶ」以外に使えない。**
            # `const call = apiFetch; call(key)` と束ね直すと、呼び出し地点に
            # 扉の名前が現れないので使用そのものが判定から消える
            # （gate-verifier 1回目の実測反例。4ゲートすべて素通りした）。
            # 引数として渡す・プロパティに入れる・再代入する、も同じ形。
            # 呼び出し位置（直後が `(`）以外の出現は1つ残らず違反にする。
            for hit in _bare_name_re(name).finditer(raw):
                if _CALL_AFTER_RE.match(raw, hit.end()):
                    continue  # 呼び出し。これだけが許される使い方
                if hit.start() in import_spans:
                    continue  # import 文そのもの
                findings.append(Finding(
                    "escaped_gateway_name", rel, _line_of(raw, hit.start()), name,
                    f"{name} は呼び出す以外に使えません"
                    "（変数に束ね直す・引数として渡すと、使用が判定から消える）"))
            for hit in _usage_re(name).finditer(raw):
                arg = hit.group("arg").strip()
                line = _line_of(raw, hit.start())
                key_hit = re.fullmatch(r"'([A-Za-z_$][\w$]*)'", arg)
                if not key_hit:
                    findings.append(Finding(
                        "computed_key", rel, line, arg[:70] or "（引数なし）",
                        f"{name} の宛先はカタログのキーのリテラルでなければ"
                        "なりません（変数・計算・省略は不可）"))
                    continue
                key = key_hit.group(1)
                if key not in entries:
                    findings.append(Finding(
                        "unknown_key", rel, line, key,
                        "カタログに無いキーです"))
                    continue
                used.append(key)
        # **回数まで返す。** `set` に潰すと、同じファイルで同じキーを5回
        # 呼んでいるうち3回を消しても最後の1本が残る限りラチェットが黙る
        # （C-5(b)「使用の削除で緑」がそのまま成立していた。3回目の実測反例）。
        return sorted(used), findings

    # --- 実行 ---------------------------------------------------------------

    def run(self) -> ClosureReport:
        report = ClosureReport(
            backend_token_pattern=self._backend_token_re().pattern)
        allowlist, findings = self._allowlist()
        report.allowlist = allowlist
        report.findings += findings
        allowed = {(e["file"], e["url"]) for e in allowlist
                   if isinstance(e.get("file"), str)
                   and isinstance(e.get("url"), str)}
        hit_allowed: set[tuple[str, str]] = set()

        report.findings += self._boundary_findings()

        gateway_seen: set[str] = set()
        for path in self._iter_files():
            rel = self._rel(path)
            raw = path.read_text(encoding="utf-8", errors="replace")
            report.files_scanned += 1
            report.scanned_files.append(rel)
            if rel.startswith(GATEWAY_DIR + "/"):
                gateway_seen.add(rel)
                if rel == CATALOGUE_REL:
                    entries, found = self._check_catalogue(raw, rel)
                    report.entries = entries
                    report.findings += found
                elif rel == CLIENT_REL:
                    report.findings += self._check_client(raw, rel)
                elif rel != ALLOWLIST_REL:
                    report.findings.append(Finding(
                        "extra_gateway_file", rel, 0, "",
                        "呼び出し口に置けるのは宣言した3つだけです"
                        "（増やせば第2の扉になる）"))
                continue
            report.findings += self._check_outside(raw, rel, allowed)
            urls = {m.group(0) for m in _ABSOLUTE_URL_RE.finditer(raw)}
            urls |= {m.group(0) for m in _PROTOCOL_RELATIVE_RE.finditer(raw)}
            for url in urls:
                if (rel, url) in allowed:
                    hit_allowed.add((rel, url))

        missing = [rel for rel in GATEWAY_FILES if rel not in gateway_seen]
        for rel in missing:
            report.findings.append(Finding(
                "gateway_missing", rel, 0, "",
                "呼び出し口のファイルがありません。"
                "**無い状態を緑にしない** — 消すだけでゲートが無効になります"))

        # 走査0件で緑にしない。ファイルを1つも読めなければ違反が出るはずもない。
        if report.files_scanned == 0:
            report.findings.append(Finding(
                "nothing_scanned", "frontend", 0, "",
                "走査したファイルが0件です"))

        # 使用の解決は、カタログを読んだあとでないと判定できない。
        for path in self._iter_files():
            rel = self._rel(path)
            if rel.startswith(GATEWAY_DIR + "/"):
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            used, found = self._check_usage(raw, rel, report.entries)
            report.findings += found
            if used:
                report.usages[rel] = used

        for key in sorted(set(report.entries) - report.used_keys()):
            report.findings.append(Finding(
                "unused_entry", CATALOGUE_REL, 0, key,
                "どこからも使われていないカタログ項目です"
                "（死蔵の宣言を PASS で隠さない）"))

        for entry in allowlist:
            pair = (entry.get("file"), entry.get("url"))
            if pair not in hit_allowed:
                report.findings.append(Finding(
                    "dead_allowlist", ALLOWLIST_REL, 0, str(pair),
                    "許可したのに実在しません"
                    "（使われていない許可は、あとで何かを黙って通す）"))
        return report


# --- ラチェット（C-5） --------------------------------------------------------

DECLARATION_KEYS = ("forbidden_forms", "gateway_files", "scanned_suffixes",
                    "excluded_dirs", "closure_excluded",
                    "closure_excluded_files", "closure_binary_suffixes",
                    "closure_binary_magics",
                    "detectors", "scanned_files",
                    "allowlist", "usages", "entries")


def declaration() -> dict:
    """**判定そのもの。** 緩めればそれ自体が違反。"""
    return {
        "forbidden_forms": {name: pattern.pattern
                            for name, pattern in sorted(FORBIDDEN_FORMS.items())},
        "gateway_files": sorted(GATEWAY_FILES),
        "scanned_suffixes": sorted(SCANNED_SUFFIXES),
        # **走査から外す場所。** ここに1つ足すだけで、そのディレクトリの
        # 生 fetch がゲートにもラチェットにも出なくなる。C-5 が名指しした
        # 「除外ディレクトリの追加」がこれで、固定していなかったので
        # 4ゲート＋テストのすべてを素通りしていた（gate-verifier 1回目）。
        "excluded_dirs": sorted(_EXCLUDED_DIRS),
        # 閉包自身の走査範囲。**ここに1つ足せば、その場所が無検査になる。**
        "closure_excluded": sorted(CLOSURE_EXCLUDED),
        "closure_excluded_files": sorted(CLOSURE_EXCLUDED_FILES),
        "closure_binary_suffixes": sorted(CLOSURE_BINARY_SUFFIXES),
        "closure_binary_magics": dict(sorted(CLOSURE_BINARY_MAGICS.items())),
        # **このモジュール自身の検出器の本体。** `_backend_token_re` を
        # 絶対に当たらないパターンに差し替えるだけで backend URL の検出が
        # 丸ごと無効になるのに、ラチェットは何も言わなかった
        # （gate-verifier 2回目の実測。落ちたのはテストだけで、
        # そのテストは testpaths に無く CI で走っていなかった）。
        # P4 で `unscanned_forms` に適用した「正規表現の本体まで固定する」を
        # 自分自身にも適用する。
        "detectors": {
            "absolute_url": _ABSOLUTE_URL_RE.pattern,
            "protocol_relative": _PROTOCOL_RELATIVE_RE.pattern,
            "joined_literals": _JOINED_LITERALS_RE.pattern,
            "one_literal": _ONE_LITERAL_RE.pattern,
            "catalogue_entry": _CATALOGUE_ENTRY_RE.pattern,
            "gateway_import": _GATEWAY_IMPORT_RE.pattern,
            "call_after": _CALL_AFTER_RE.pattern,
        },
    }


def snapshot(report: ClosureReport) -> dict:
    payload = declaration()
    # **実際に読んだファイルの一覧。** 除外ディレクトリを固定しても、
    # 走査範囲を狭める道は他にもある（拡張子・到達可能性・rglob の起点）。
    # 「前は読んでいたのに読まなくなった」を直接見る。
    payload["scanned_files"] = sorted(report.scanned_files)
    payload["detectors"] = dict(payload["detectors"])
    payload["detectors"]["backend_token"] = report.backend_token_pattern
    payload["allowlist"] = sorted(
        f"{e.get('file')}|{e.get('url')}" for e in report.allowlist)
    # **回数まで固定する。** キーの集合だけだと、同じファイルで同じキーを
    # 5回呼んでいるうち3回を消しても最後の1本が残る限り気づけない
    # （C-5(b)「使用の削除で緑」がそのまま成立していた）。
    payload["usages"] = {
        rel: {key: keys.count(key) for key in sorted(set(keys))}
        for rel, keys in sorted(report.usages.items())}
    payload["entries"] = dict(sorted(report.entries.items()))
    return payload


def write_baseline(report: ClosureReport, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(snapshot(report), fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def load_baseline(path: Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def check_ratchet(report: ClosureReport, baseline: dict | None) -> list[str]:
    """弱化を並べる。空なら弱化していない。"""
    if baseline is None:
        return [("ベースラインがありません。--update-baseline で作ってください。"
                 "**無い状態を緑にしない** — 消すだけでラチェットが無効になります")]
    violations: list[str] = []
    for key in DECLARATION_KEYS:
        if key not in baseline:
            violations.append(f"[記録の欠落] {key} がベースラインにありません")
    if violations:
        return violations

    now = snapshot(report)
    # 判定の本体。**どちらに動いても違反。** 増やすのも「見えていたものが
    # 見えなくなる」経路（正規表現の差し替え）になりうる。
    # 前は読んでいたのに読まなくなったファイル。**除外ディレクトリの追加**が
    # ここに出る（C-5 が名指しした弱化。1回目の検証で素通りしていた）。
    for rel in baseline["scanned_files"]:
        if rel not in now["scanned_files"]:
            violations.append(
                f"[走査から外れた] {rel} を読まなくなりました"
                "（除外ディレクトリ・拡張子・到達可能性のどれかが狭まった）")
    for key in ("forbidden_forms", "gateway_files", "scanned_suffixes",
                "excluded_dirs", "closure_excluded", "closure_excluded_files",
                "closure_binary_suffixes", "closure_binary_magics", "detectors"):
        if baseline[key] != now[key]:
            violations.append(
                f"[判定が動いた] {key}: {_diff(baseline[key], now[key])}"
                "（禁止語彙・扉の構成・走査範囲は緩めても締めても差分に出す）")
    # 許可リストが増えるのは例外が増えるということ。
    for item in sorted(set(now["allowlist"]) - set(baseline["allowlist"])):
        violations.append(f"[例外が増えた] 許可リストに {item} が足された")
    # 使用が消えるのは「呼ばなくなった」。カタログに項目が残るので
    # ui_api のラチェットでは気づけない。**ここが受け皿。**
    for rel, counts in baseline["usages"].items():
        now_counts = now["usages"].get(rel, {})
        for key, before in counts.items():
            after = now_counts.get(key, 0)
            if after < before:
                violations.append(
                    f"[使用が減った] {rel} の {key} が {before} → {after} 回に"
                    "なりました")
    for key, value in baseline["entries"].items():
        if key not in now["entries"]:
            violations.append(f"[項目が消えた] カタログから {key} が消えました")
        elif now["entries"][key] != value:
            violations.append(
                f"[項目が差し替わった] {key}: {value} → {now['entries'][key]}")
    return violations


def _diff(before, after) -> str:
    """**何が動いたかを言う。** キー名だけを並べると、本体を差し替えたときに
    両辺が同じ文字列になって「動いた」としか読めない（3回目の指摘）。"""
    if isinstance(before, dict) and isinstance(after, dict):
        changed = [f"{k}: {before.get(k, '（無し）')} → {after.get(k, '（無し）')}"
                   for k in sorted(set(before) | set(after))
                   if before.get(k) != after.get(k)]
        return " / ".join(changed) or "（差分なし）"
    return f"{_render(before)} → {_render(after)}"


def _render(value) -> str:
    if isinstance(value, dict):
        return "/".join(sorted(value))
    if isinstance(value, (list, tuple, set)):
        return "/".join(sorted(str(v) for v in value))
    return str(value)


# --- CLI ----------------------------------------------------------------------


def _format(report: ClosureReport) -> str:
    lines = [
        (f"呼び出し口の閉包 — frontend {report.files_scanned} ファイル / "
         f"カタログ {len(report.entries)} 項目 / "
         f"使用 {sum(len(v) for v in report.usages.values())} 箇所 / "
         f"許可 {len(report.allowlist)} 件"),
        "",
    ]
    if report.closed:
        lines.append("  違反 0 件。呼び出し口の外に呼び出しはありません。")
        return "\n".join(lines)
    kinds: dict[str, int] = {}
    for finding in report.findings:
        kinds[finding.kind] = kinds.get(finding.kind, 0) + 1
    for kind, count in sorted(kinds.items()):
        lines.append(f"  ⛔ {kind:22s} {count:3d} 件")
    lines.append("")
    for finding in report.findings:
        lines.append(f"    {finding}")
    return "\n".join(lines)


def _format_semantics() -> str:
    lines = ["呼び出し口の閉包 — 確かめること／確かめないこと", ""]
    for label in ("確かめること", "確かめないこと"):
        lines.append(f"  {label}:")
        lines += [f"    - {item}" for item in CLOSURE_SEMANTICS[label]]
        lines.append("")
    lines.append(f"  判定の性質: {CLOSURE_SEMANTICS['判定の性質']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="呼び出し口の閉包")
    parser.add_argument("--gate", action="store_true",
                        help="違反が1件でもあれば exit 1")
    parser.add_argument("--ratchet", action="store_true",
                        help="判定・使用・許可の弱化を検出して exit 1")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--semantics", action="store_true",
                        help="確かめること／確かめないことを出す")
    args = parser.parse_args(argv)

    if args.semantics:
        print(_format_semantics())
        return 0

    report = ClosureExecutor.for_repo().run()

    if args.update_baseline:
        if not report.closed:
            print("🚫 違反が残っているのでベースラインを更新できません。")
            print(_format(report))
            return 1
        print(f"✅ ベースラインを更新しました: "
              f"{write_baseline(report, BASELINE)}")
        return 0

    if args.ratchet:
        violations = check_ratchet(report, load_baseline(BASELINE))
        if violations:
            print(f"🚫 呼び出し口ラチェット: {len(violations)} 件の弱化")
            for violation in violations:
                print(f"    {violation}")
            return 1
        print(f"✅ 呼び出し口ラチェット: カタログ {len(report.entries)} 項目 / "
              f"使用 {sum(len(v) for v in report.usages.values())} 箇所（弱化なし）")
        return 0

    print(_format(report))
    if args.gate and not report.closed:
        return 1
    if args.gate:
        # **測ったことしか言わない。** 「呼び出しは無い」と言い切ると、
        # 確かめていない経路（変数を挟んだ URL・データ由来の URL 属性）まで
        # 保証したことになる（gate-verifier 1回目の指摘）。
        print("\n✅ 禁止した呼び出しの形・backend の URL リテラル・"
              "宣言していない絶対 URL は、呼び出し口の外に1件もありません"
              "（--semantics に確かめていないものを列挙してあります）。")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
