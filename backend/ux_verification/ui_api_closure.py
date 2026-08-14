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
    _display_path,
)

BASELINE_DIR = Path(__file__).parent / "snapshots"
BASELINE = BASELINE_DIR / "ui_api_closure_baseline.json"

# 扉に置いてよいファイル。**ここに無いファイルは第2の扉**なので違反にする。
ALLOWLIST_REL = f"{GATEWAY_DIR}/external_urls.json"
GATEWAY_FILES = (CATALOGUE_REL, CLIENT_REL, ALLOWLIST_REL)

# 扉の外で禁止する呼び出しの形。**`ui_api` の検出器をそのまま借りる** —
# 別に書き起こすと、片方を緩めてももう片方が気づかない。
#
# ただし「合成された URL」だけは外す。`String.fromCharCode(` / `atob(` /
# `decodeURIComponent(` / `].join(` は**文字列を作る形であって呼び出しの形では
# ない**。`ui_api` では、作った文字列が実際の呼び出しに渡りうるので検出対象に
# する意味がある。閉包では呼び出しの形そのものを1つ残らず禁止しているので、
# 合成された文字列を**渡す先が無い**。ここに入れておくと、URL と無関係な
# `String.fromCharCode(65 + i)` のような表示コードが落ちるだけで、
# 保護は1つも増えない（実測で1件当たった）。
#
# **URL 属性は禁止の対象外**（`src={expr}` はデータ由来のことがある）。
# したがって「式で作った URL を属性に入れる」経路はここでは確かめていない —
# CLOSURE_SEMANTICS の『確かめないこと』に書いてある。
_NOT_A_CALL_FORM = ("合成された URL",)
FORBIDDEN_FORMS: dict[str, re.Pattern] = {
    "fetch": _FETCH_RE,
    "new WebSocket": _WEBSOCKET_RE,
    "window.open": _WINDOW_OPEN_RE,
    **{name: pattern for name, pattern in UNSCANNED_FORMS.items()
       if name not in _NOT_A_CALL_FORM},
}

# 絶対 URL。スキームがあるものは全部。**backend も外部も区別しない** —
# 区別した瞬間「backend かどうか」の判定が要り、そこが精度を要求する場所になる。
_ABSOLUTE_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s'\"`)<>]*")

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


CLOSURE_SEMANTICS = {
    "確かめること": [
        ("呼び出し口（frontend/" + GATEWAY_DIR + "/）の外に、"
         "ネットワーク呼び出しの形が1件も無い（コメント内も含む）"),
        "呼び出し口の外に、backend のパスで始まる文字列リテラルが1件も無い",
        "呼び出し口の外に、宣言していない絶対 URL が1件も無い",
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

    @classmethod
    def for_repo(cls) -> ClosureExecutor:
        return cls(UiApiExecutor.for_repo())

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
        if not value.startswith("/"):
            return False
        head = value.strip("/").split("/", 1)[0].split("?", 1)[0]
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
        for hit in _ABSOLUTE_URL_RE.finditer(raw):
            url = hit.group(0)
            if (rel, url) in allowed:
                continue
            findings.append(Finding(
                "external_url", rel, _line_of(raw, hit.start()), url[:70],
                "宣言していない絶対 URL です"
                f"（{ALLOWLIST_REL} に理由つきで宣言してください）"))
        for hit in _URL_LITERAL_RE.finditer(raw):
            value = hit.group("value").strip()
            if self._is_backend_path(value):
                findings.append(Finding(
                    "backend_url", rel, _line_of(raw, hit.start()), value[:70],
                    "backend のパスを呼び出し口の外に書けません"))
        return findings

    # --- 使用（C-3） --------------------------------------------------------

    def _check_usage(self, raw: str, rel: str,
                     entries: dict[str, str]) -> tuple[list[str], list[Finding]]:
        findings: list[Finding] = []
        names: list[str] = []
        for number, line in enumerate(raw.split("\n"), start=1):
            if _GATEWAY_MENTION not in line or not _IMPORTS_SOMETHING_RE.search(line):
                continue
            hit = _GATEWAY_IMPORT_RE.search(line)
            if not hit:
                # `import * as api from '../gateway/client.js'` など。
                # 別名を許すと、使用の検出が名前の追跡になる。
                findings.append(Finding(
                    "bad_import", rel, number, line.strip()[:70],
                    "扉の import は `import { … } from '…/client.js'` の形だけです"))
                continue
            for piece in hit.group("names").split(","):
                piece = piece.strip()
                if not piece:
                    continue
                if not _IMPORT_NAME_RE.match(piece):
                    findings.append(Finding(
                        "bad_import", rel, number, piece,
                        "扉からの import は名前つきのみ（別名・`import *` は不可）"))
                    continue
                names.append(piece)

        used: list[str] = []
        for name in names:
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
        return sorted(set(used)), findings

    # --- 実行 ---------------------------------------------------------------

    def run(self) -> ClosureReport:
        report = ClosureReport()
        allowlist, findings = self._allowlist()
        report.allowlist = allowlist
        report.findings += findings
        allowed = {(e["file"], e["url"]) for e in allowlist
                   if isinstance(e.get("file"), str)
                   and isinstance(e.get("url"), str)}
        hit_allowed: set[tuple[str, str]] = set()

        gateway_seen: set[str] = set()
        for path in self.executor._iter_files():
            rel = _display_path(path, self.executor.frontend_src).replace("\\", "/")
            raw = path.read_text(encoding="utf-8", errors="replace")
            report.files_scanned += 1
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
            for url in {m.group(0) for m in _ABSOLUTE_URL_RE.finditer(raw)}:
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
        for path in self.executor._iter_files():
            rel = _display_path(path, self.executor.frontend_src).replace("\\", "/")
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
                    "allowlist", "usages", "entries")


def declaration() -> dict:
    """**判定そのもの。** 緩めればそれ自体が違反。"""
    return {
        "forbidden_forms": {name: pattern.pattern
                            for name, pattern in sorted(FORBIDDEN_FORMS.items())},
        "gateway_files": sorted(GATEWAY_FILES),
        "scanned_suffixes": sorted(SCANNED_SUFFIXES),
    }


def snapshot(report: ClosureReport) -> dict:
    payload = declaration()
    payload["allowlist"] = sorted(
        f"{e.get('file')}|{e.get('url')}" for e in report.allowlist)
    payload["usages"] = {rel: sorted(keys)
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
    for key in ("forbidden_forms", "gateway_files", "scanned_suffixes"):
        if baseline[key] != now[key]:
            violations.append(
                f"[判定が動いた] {key}: {_render(baseline[key])} → {_render(now[key])}"
                "（禁止語彙・扉の構成・走査範囲は緩めても締めても差分に出す）")
    # 許可リストが増えるのは例外が増えるということ。
    for item in sorted(set(now["allowlist"]) - set(baseline["allowlist"])):
        violations.append(f"[例外が増えた] 許可リストに {item} が足された")
    # 使用が消えるのは「呼ばなくなった」。カタログに項目が残るので
    # ui_api のラチェットでは気づけない。**ここが受け皿。**
    for rel, keys in baseline["usages"].items():
        now_keys = now["usages"].get(rel, [])
        for key in keys:
            if key not in now_keys:
                violations.append(
                    f"[使用が消えた] {rel} が {key} を呼ばなくなりました")
    for key, value in baseline["entries"].items():
        if key not in now["entries"]:
            violations.append(f"[項目が消えた] カタログから {key} が消えました")
        elif now["entries"][key] != value:
            violations.append(
                f"[項目が差し替わった] {key}: {value} → {now['entries'][key]}")
    return violations


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
        print("\n✅ 呼び出し口の外に、呼び出しの形も backend の URL も"
              "宣言していない絶対 URL もありません。")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
