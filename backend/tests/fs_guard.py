"""テストが本番ファイルへ書き込むのを検出する（記録のみ・挙動は変えない）。

## なぜ必要か

テストを流すと本番ファイルが書き換わる。2026-07-28 実測で以下が生成・改変された。

    README.md（ダッシュボード本文）
    Human01_Official Artifact/ 一式
    backend/usage_tracker/usage_data.json
    backend/agents/orchestration/resource_state.json(.bak)
    backend/agents/orchestration/harness_audit_log.jsonl
    backend/branding/evolution_log.json

`Human01_Official Artifact/` は会話ログを含むため公開時に意図的に除去したもの。
テストが再生成し、気づかずコミットすると除去した意味が消える。

## なぜ「記録のみ」か

当初は一時ディレクトリへ振り向ける案だった。しかし**テストは書いたファイルを
読み返す**ため、書き込みだけ振り向けると読み返しが壊れる。透過的にやるには
コピーオンライトのオーバーレイが要り、9,212 テストに入れるには機構が大きすぎる。

記録だけなら挙動を一切変えないので、既存のテストを壊さない。得られる情報
（どのテストが何を汚すか）は同じで、そこから個別に直せる。

Ruff / 絶対パスラチェットと同じ順序を採る。**観測 → 修正 → 増加を禁じる。**
遮断に切り替えるのは、汚染源を潰し切ってから。

## 使い方

conftest から `install()` / `uninstall()` を呼ぶ。記録は `report()` で取れる。
`ANTIGRAVITY_FS_GUARD=0` で無効化する。
"""

from __future__ import annotations

import builtins
import io
import os
from pathlib import Path

# 監視対象の根。ここから外への書き込みは見ない（tmp_path 等は対象外になる）。
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# 本番ファイルではないので無視するディレクトリ。パスの構成要素として一致を見る。
# 部分文字列で判定すると、ディレクトリ自身の作成（末尾に区切りが付かない）を
# 取りこぼす。実際 `__pycache__` の mkdir が検出に混じった。
_IGNORED_DIRS = frozenset({
    ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
    "node_modules", ".venv", "venv", "temp_raw_videos", ".mypy_cache",
})

# 検出そのものやカバレッジが作るファイル。自分の書き込みを数えない。
_IGNORED_NAMES = frozenset({"fs-guard-report.txt", "fs-guard-records.jsonl", ".coverage"})

# 名前に実行ごとの識別子が入るため、完全一致では拾えない生成物。
# 前方一致で落とす。ここに漏れがあると「本番ファイルへの書き込み」の
# 件数がテスト基盤自身の生成物で嵩上げされ、残件が読めなくなる。
_IGNORED_PREFIXES = (
    "pytest-cache-files-",   # pytest 自身（キャッシュ無効時の一時ディレクトリ）
    ".junit_batch_",         # scripts/run_test_batches.py の JUnit 出力
)

# 書き込みを伴うモード。"r" だけのときは見ない。
_WRITE_FLAGS = frozenset("wax+")

_records: list[dict[str, str]] = []
_current_test: str = "(不明)"
_saved: dict = {}
_installed: dict = {}


def set_current_test(node_id: str) -> None:
    """いま走っているテストを記録側に伝える。"""
    global _current_test
    _current_test = node_id


def _is_watched(path) -> bool:
    """本番ファイルへの書き込みか判定する。安い順に落とす。"""
    if not isinstance(path, (str, bytes, os.PathLike)):
        return False  # ファイルディスクリプタ等
    try:
        p = os.path.abspath(os.fspath(path))
    except (TypeError, ValueError):
        return False
    if not p.startswith(_REPO_ROOT):
        return False
    if os.path.basename(p) in _IGNORED_NAMES:
        return False
    parts = os.path.relpath(p, _REPO_ROOT).split(os.sep)
    if any(part in _IGNORED_DIRS for part in parts):
        return False
    # 前方一致の除外は構成要素すべてに当てる。生成物そのものだけでなく、
    # その中に作られるファイルも落とす必要がある。
    return not any(part.startswith(_IGNORED_PREFIXES) for part in parts)


def _record(operation: str, path) -> None:
    try:
        rel = os.path.relpath(os.path.abspath(os.fspath(path)), _REPO_ROOT)
    except (TypeError, ValueError, OSError):
        rel = str(path)
    _records.append({"test": _current_test, "operation": operation, "path": rel})


def _wrap_open(real, label):
    """`open` 系。書き込みモードのときだけ記録する。"""

    def wrapper(file, mode="r", *args, **kwargs):
        if _WRITE_FLAGS & set(mode) and _is_watched(file):
            _record(f"{label}({mode})", file)
        return real(file, mode, *args, **kwargs)

    return wrapper


def _wrap_path(real, label, index=0):
    """パスを引数に取る関数。`index` 番目の引数を対象として記録する。

    `os.replace(src, dst)` のように**書き込み先が第2引数**のものがあるため
    位置を指定できるようにしている。ここを取りこぼすとアトミック書き込み
    （一時ファイル + os.replace）が丸ごと見えなくなる。実際 usage_data.json は
    この経路で書かれており、`open` の監視だけでは検出できなかった。
    """

    def wrapper(*args, **kwargs):
        if len(args) > index and _is_watched(args[index]):
            _record(label, args[index])
        return real(*args, **kwargs)

    return wrapper


def install() -> None:
    """検出を開始する。挙動は変えない — 記録して本物へ委譲する。"""
    if os.environ.get("ANTIGRAVITY_FS_GUARD") == "0" or _installed:
        return

    import shutil

    # (保存キー, 対象オブジェクト, 属性名, ラッパ生成)
    targets = [
        ("open", builtins, "open", lambda f: _wrap_open(f, "open")),
        ("io_open", io, "open", lambda f: _wrap_open(f, "open")),
        ("makedirs", os, "makedirs", lambda f: _wrap_path(f, "makedirs")),
        ("mkdir", Path, "mkdir", lambda f: _wrap_path(f, "mkdir")),
        # 書き込み先が第2引数のもの
        ("replace", os, "replace", lambda f: _wrap_path(f, "os.replace", 1)),
        ("rename", os, "rename", lambda f: _wrap_path(f, "os.rename", 1)),
        ("copyfile", shutil, "copyfile", lambda f: _wrap_path(f, "shutil.copyfile", 1)),
        ("copy", shutil, "copy", lambda f: _wrap_path(f, "shutil.copy", 1)),
        ("copy2", shutil, "copy2", lambda f: _wrap_path(f, "shutil.copy2", 1)),
        ("move", shutil, "move", lambda f: _wrap_path(f, "shutil.move", 1)),
        ("p_replace", Path, "replace", lambda f: _wrap_path(f, "Path.replace", 1)),
        ("p_rename", Path, "rename", lambda f: _wrap_path(f, "Path.rename", 1)),
        # 削除も汚染。本番ファイルが消えるのは書き換えより深刻なことがある
        ("remove", os, "remove", lambda f: _wrap_path(f, "os.remove")),
        ("unlink", os, "unlink", lambda f: _wrap_path(f, "os.unlink")),
        ("p_unlink", Path, "unlink", lambda f: _wrap_path(f, "Path.unlink")),
        ("rmtree", shutil, "rmtree", lambda f: _wrap_path(f, "shutil.rmtree")),
    ]

    # 差し替える前の値を控える。他のテストが patch している最中でもそこへ戻せる
    # ようにする（無条件に import 時の値へ戻すと、その patch を壊す）。net_guard と同じ。
    for key, obj, attr, make in targets:
        real = getattr(obj, attr)
        wrapped = make(real)
        _saved[key] = (obj, attr, real)
        setattr(obj, attr, wrapped)
        _installed[key] = wrapped


def uninstall() -> None:
    """検出を解除する。

    自分が置いた関数のままの場合だけ戻す。テスト側が後から patch していた場合に
    その patch を上書きしないため（上書きすると、相手の後始末で監視が復活し続ける）。
    net_guard と同じ考え方。
    """
    if not _installed:
        return
    for key, (obj, attr, real) in _saved.items():
        if getattr(obj, attr, None) is _installed.get(key):
            setattr(obj, attr, real)
    _installed.clear()
    _saved.clear()


def records() -> list[dict[str, str]]:
    return list(_records)


def report() -> str:
    """テスト別・パス別に集計した報告を返す。"""
    if not _records:  # pragma: no cover — 呼び出し側が事前に確認する
        return "本番ファイルへの書き込みは検出されませんでした。"

    by_path: dict[str, set[str]] = {}
    for r in _records:
        by_path.setdefault(r["path"], set()).add(r["test"])

    lines = [f"本番ファイルへの書き込みを {len(by_path)} パスで検出しました。", ""]
    for path in sorted(by_path, key=lambda p: (-len(by_path[p]), p)):
        tests = sorted(by_path[path])
        lines.append(f"{path}  ({len(tests)} テスト)")
        lines.extend(f"    {t}" for t in tests[:5])
        if len(tests) > 5:
            lines.append(f"    … 他 {len(tests) - 5} 件")
    return "\n".join(lines)


# ---------------- pytest フック ----------------
#
# conftest は `backend/tests/` `backend/harness/` `tests/` の3系統に分かれており、
# さらに rootdir がバッチ構成で変わる（`backend/tests/` だけのバッチでは
# rootdir が `backend/tests` になり、リポジトリ直下の conftest.py は読まれない）。
# どこから読まれても同じ動きになるよう、フック本体をここに置いて各 conftest から
# 取り込む。install() と報告はどちらも冪等なので、多重に読まれても害はない。

_reported = False
_REPORT_PATH = os.path.join(_REPO_ROOT, "fs-guard-report.txt")

# 機械可読の出力。人間向けの報告を後から解析すると、書式を変えただけで
# ラチェットが壊れる。判定にはこちらを使う（.github/scripts/fs_guard_ratchet.py）。
_RECORDS_PATH = os.path.join(_REPO_ROOT, "fs-guard-records.jsonl")


def pytest_configure(config):
    install()


def pytest_unconfigure(config):
    uninstall()


def pytest_runtest_setup(item):
    set_current_test(item.nodeid)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """検出結果を表示し、ファイルにも残す。

    バッチ分割実行（scripts/run_test_batches.py）はバッチごとに別プロセスなので、
    追記して全バッチぶんを1ファイルに集める。
    """
    global _reported
    if _reported:
        return
    _reported = True

    # 検出ゼロでも JSONL は必ず作る。「ファイルが無い＝汚染ゼロ」にすると、
    # 計測そのものが走らなかったときにラチェットが黙って通る（fail-open）。
    # ゼロ件は「中身が空のファイル」、未計測は「ファイルが無い」で区別する。
    try:
        with open(_RECORDS_PATH, "a", encoding="utf-8") as fh:
            for line in records_jsonl():
                fh.write(line + "\n")
    except OSError:  # pragma: no cover — 報告の失敗でテストを落とさない
        pass

    if not _records:
        return
    text = report()
    terminalreporter.write_sep("=", "本番ファイルへの書き込み検出", yellow=True)
    terminalreporter.write_line(text)
    try:
        with open(_REPORT_PATH, "a", encoding="utf-8") as fh:
            fh.write(text + "\n\n")
    except OSError:  # pragma: no cover — 報告の失敗でテストを落とさない
        pass


def records_jsonl() -> list[str]:
    """パス単位に畳んだ検出結果を JSON Lines で返す。

    生の記録は同じテストが同じファイルを何度も書くたびに増えるので、
    そのまま出すと件数が実装の都合で揺れる。判定に使うのは
    「どのパスを、どのテストが汚したか」だけなのでそこまで畳む。
    パス区切りは OS 差を消すため posix 形式に揃える。
    """
    import json

    by_path: dict[str, set[str]] = {}
    ops: dict[str, set[str]] = {}
    for r in _records:
        key = r["path"].replace(os.sep, "/")
        by_path.setdefault(key, set()).add(r["test"])
        ops.setdefault(key, set()).add(r["operation"])
    return [
        json.dumps(
            {
                "path": path,
                "tests": sorted(by_path[path]),
                "operations": sorted(ops[path]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for path in sorted(by_path)
    ]


__all__ = [
    "install",
    "pytest_configure",
    "pytest_runtest_setup",
    "pytest_terminal_summary",
    "pytest_unconfigure",
    "records",
    "records_jsonl",
    "report",
    "set_current_test",
    "uninstall",
]
