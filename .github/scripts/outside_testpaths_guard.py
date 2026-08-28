#!/usr/bin/env python3
"""**pytest.ini の testpaths の外にあるテストの退行を検知する**（2026-08-28 ユーザー決定）。

## なぜ要るか

`pytest.ini` の testpaths に載っているのは **444 ファイル**で、リポジトリには
**887 ファイル**の `test_*.py` がある。**残り 443 ファイルを CI は一度も
走らせていない。**

R1.5 では、この盲点で**同じクラスの取りこぼしが4度**起きた:

| 周 | 落ちたもの |
|---|---|
| C4 1周目 | `tests/test_youtube_uploader_service.py`（投稿の旧契約） |
| C4 2周目 | `backend/tests/test_shared/test_cov_admin_channel_router.py`（チャンネル統計の旧契約） |
| C4 3周目 | `backend/tests/test_shared/test_report_generator_plugin_robustness.py`（品質スコア 0.0 の旧契約） |
| 総当たり | ほか 13 ファイル 16 テスト（モデル ID を直書きした期待値） |

いずれも「本番を直した → 旧契約を固定したテストが赤くなった → CI が見ていないので
気づかない」という同じ形だった。**人が1つずつ思い出すのをやめて機械に任せる。**

## どう検知するか

**基準となる版（既定 `origin/main`）と、いまの版で、同じテストを走らせて比べる。**

1. 変更された本番ファイル（`git diff --name-only <base>...HEAD`）を拾う
2. そのモジュール名に触れている「testpaths の外の」テストファイルを探す
3. 両方の版で**1ファイルずつ**走らせ、失敗したテスト ID の集合を取る
4. **いまの版にしか無い失敗**があれば違反（exit 1）

**ベースラインをファイルに固定しない。** 固定すると腐るし、「元から赤い」の
一覧を人が保守することになる。基準の版で実際に走らせて比べるので、
**元から赤いテストは自動的に無視される。**

1ファイルずつ走らせるのは、`pytest.ini` の外にあるテストにファイル間の
順序依存があるため（まとめると別の場所で落ちる）。変更に触れるファイルだけに
絞るので、通常の PR では数分で終わる。

## 使い方

    python .github/scripts/outside_testpaths_guard.py                 # origin/main と比較
    python .github/scripts/outside_testpaths_guard.py --base 8eef716  # 版を指定
    python .github/scripts/outside_testpaths_guard.py --list          # 対象を出すだけ
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 走査に入れないディレクトリ。過去版のスナップショットと第三者コードは対象外。
SKIP_DIRS = frozenset({
    "node_modules", ".venv", "venv", ".git", "__pycache__", "archives",
    "_deprecated", "antigravity_phase18_stable_v1",
    "antigravity_phase19_experimental_v1", ".next", "dist", "build",
})

# **e2e は実サーバが要る**ので、この検知の対象にしない（CI では起動していない）。
SKIP_TEST_DIRS = frozenset({"e2e"})

# 本番として扱わないもの。テスト自身の変更で自分を回しても意味が無い。
NOT_PRODUCTION = re.compile(
    r"(^|/)(tests?|docs|\.github|\.claude|scratch)/"
    r"|(^|/)test_[^/]*\.py$"
    r"|(^|/)conftest\.py$"
)

# 1ファイルあたりの上限（秒）。超えたら「判定不能」として違反にはしない。
PER_FILE_TIMEOUT = 240

# 対象が多すぎるときの上限。**黙って切らずに必ず報告する。**
MAX_FILES = 160


def _run(args: list[str], cwd: Path | None = None) -> str:
    r = subprocess.run(args, cwd=str(cwd or ROOT), capture_output=True, check=False,
                       text=True, encoding="utf-8", errors="replace")
    return r.stdout


def testpaths() -> set[str]:
    """`pytest.ini` の testpaths に載っているファイル。"""
    out: set[str] = set()
    ini = ROOT / "pytest.ini"
    if not ini.is_file():
        return out
    中 = False
    for line in ini.read_text(encoding="utf-8").splitlines():
        if line.startswith("testpaths"):
            中 = True
            continue
        if 中:
            if line and not line[0].isspace():
                break
            s = line.strip()
            if s.endswith(".py"):
                out.add(s)
    return out


def outside_tests() -> list[str]:
    """testpaths の外にあるテストファイル。"""
    載っている = testpaths()
    out: list[str] = []
    for p in sorted(ROOT.rglob("test_*.py")):
        parts = set(p.parts)
        if parts & SKIP_DIRS or parts & SKIP_TEST_DIRS:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel not in 載っている:
            out.append(rel)
    return out


def changed_production(base: str) -> list[str]:
    """基準の版から変わった**本番**ファイル。"""
    merge_base = _run(["git", "merge-base", base, "HEAD"]).strip() or base
    diff = _run(["git", "diff", "--name-only", merge_base, "HEAD"])
    out = []
    for line in diff.splitlines():
        rel = line.strip()
        if not rel or NOT_PRODUCTION.search(rel):
            continue
        if rel.endswith((".py", ".json", ".yaml", ".yml")):
            out.append(rel)
    return out


def _参照形(rel: str) -> list[str]:
    """本番ファイル1つを指しうる書き方を並べる。

    **裸の語では照合しない。** `generator` のような一般的な語を素の部分一致で
    拾うと、無関係なテストが山ほど当たる（実測 180 → 誤ヒット多数）。
    import の形か、パス／ファイル名として書かれているものだけを見る。
    """
    p = Path(rel)
    parts = list(p.parts)
    if parts and parts[0] == "backend":
        parts = parts[1:]
    if not parts:
        return []
    if p.suffix != ".py":
        # 設定データはファイル名で参照される
        return [p.name]
    mod = ".".join(parts)[: -len(".py")]
    末尾 = mod.rsplit(".", 1)[-1]
    親 = mod.rsplit(".", 1)[0] if "." in mod else ""
    形 = [
        f"import {mod}",           # import a.b.c / from a.b.c import x
        f"backend.{mod}",          # from backend.a.b.c import x
        f'"{mod}"',                # patch("a.b.c.foo")
        f"'{mod}'",
        mod.replace(".", "/") + ".py",   # パスで指している
    ]
    if 親:
        形 += [f"from {親} import {末尾}", f"from .{末尾} import"]
    else:
        形 += [f"from {末尾} import", f"import {末尾}"]
    return 形


def targets(changed: list[str]) -> dict[str, list[str]]:
    """変更に触れている testpaths 外のテスト（ファイル → 触れているモジュール）。"""
    形 = {c: _参照形(c) for c in changed}
    hits: dict[str, list[str]] = {}
    for rel in outside_tests():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        ref = sorted(c for c, fs in 形.items() if any(f in text for f in fs))
        if ref:
            hits[rel] = [Path(x).stem for x in ref]
    return hits


_FAIL = re.compile(r"^(FAILED|ERROR) (\S+)")


def failures(rel: str, cwd: Path) -> tuple[set[str], bool]:
    """1ファイルを単独で走らせ、失敗したテスト ID の集合を返す。

    第2要素は「判定できたか」。タイムアウトや収集エラーは**違反にしない**
    （確かめられなかったことを、退行としても正常としても扱わない）。
    """
    env = dict(os.environ)
    env["GOOGLE_API_KEY"] = "dummy_key_for_ci"
    env["PYTHONPATH"] = str(cwd / "backend")
    env["ANTIGRAVITY_DISABLE_AUTO_COMMIT"] = "1"
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", rel, "-q", "--no-cov",
             "-p", "no:cacheprovider"],
            cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=PER_FILE_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return set(), False
    ids = set()
    for line in r.stdout.splitlines():
        m = _FAIL.match(line.strip())
        if m:
            ids.add(m.group(2).replace("\\", "/").split(" - ")[0])
    return ids, True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main",
                    help="比較する基準の版（既定 origin/main）")
    ap.add_argument("--list", action="store_true", help="対象を出して終わる")
    args = ap.parse_args()

    changed = changed_production(args.base)
    print(f"基準: {args.base}")
    print(f"変わった本番ファイル: {len(changed)} 件")
    if not changed:
        print("\n✅ 本番ファイルの変更がありません。")
        return 0

    hits = targets(changed)
    print(f"それに触れている **testpaths 外** のテスト: {len(hits)} ファイル")
    if not hits:
        print("\n✅ testpaths の外に、この変更へ触れるテストはありません。")
        return 0

    files = sorted(hits)
    切った = []
    if len(files) > MAX_FILES:
        # **黙って切らない。** 切った分は必ず名前を出す
        切った = files[MAX_FILES:]
        files = files[:MAX_FILES]

    if args.list:
        for f in files:
            print(f"  {f}   <- {', '.join(hits[f][:4])}")
        if 切った:
            print(f"  … 上限 {MAX_FILES} を超えたので {len(切った)} 件を見ていません:")
            for f in 切った:
                print(f"      {f}")
        return 0

    # 基準の版を別のワークツリーに展開する（いまの作業ツリーには触れない）
    tmp = Path(tempfile.mkdtemp(prefix="outside-testpaths-base-"))
    base_wt = tmp / "wt"
    merge_base = _run(["git", "merge-base", args.base, "HEAD"]).strip() or args.base
    add = subprocess.run(["git", "worktree", "add", "--detach", str(base_wt), merge_base],
                         cwd=str(ROOT), capture_output=True, text=True, check=False,
                         encoding="utf-8", errors="replace")
    if add.returncode != 0:
        print(f"\n⚠ 基準の版を展開できませんでした: {add.stderr.strip()[:300]}")
        print("**確かめられなかったので、退行なしとは言いません。**")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    新規: dict[str, list[str]] = {}
    確かめられず: list[str] = []
    基準に無い: list[str] = []
    try:
        for i, rel in enumerate(files, 1):
            print(f"  [{i}/{len(files)}] {rel}", flush=True)
            now, ok_now = failures(rel, ROOT)
            if not ok_now:
                確かめられず.append(f"{rel}（いまの版がタイムアウト）")
                continue
            if not (base_wt / rel).is_file():
                # R1.5 で新しく作ったテスト。基準に無いので比べられない
                if now:
                    基準に無い.append(f"{rel}: {len(now)} 件失敗（基準に存在しないファイル）")
                continue
            was, ok_was = failures(rel, base_wt)
            if not ok_was:
                確かめられず.append(f"{rel}（基準の版がタイムアウト）")
                continue
            増えた = sorted(now - was)
            if 増えた:
                新規[rel] = 増えた
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(base_wt)],
                       cwd=str(ROOT), capture_output=True, check=False)
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if 切った:
        print(f"⚠ 対象が上限 {MAX_FILES} を超えたので {len(切った)} ファイルを見ていません:")
        for f in 切った:
            print(f"    {f}")
        print()
    if 確かめられず:
        print(f"⚠ 確かめられなかったもの（{len(確かめられず)} 件・退行として数えていません）:")
        for m in 確かめられず:
            print(f"    {m}")
        print()
    if 基準に無い:
        print(f"⚠ 基準に存在しないファイルの失敗（{len(基準に無い)} 件・退行として数えていません）:")
        for m in 基準に無い:
            print(f"    {m}")
        print()

    if 新規:
        件数 = sum(len(v) for v in 新規.values())
        print(f"🚫 **testpaths の外で新しく赤くなったテストがあります**"
              f"（{件数} 件 / {len(新規)} ファイル）:")
        for rel, ids in sorted(新規.items()):
            print(f"    {rel}")
            for t in ids:
                print(f"        {t}")
        print()
        print("  CI は pytest.ini の testpaths しか走らせないので、"
              "ここが赤くても本体のテストジョブは緑のままです。")
        print("  旧い契約を固定しているテストなら、**期待値を正典から引き直して**"
              "ください（モデル ID や既定値の直書きをやめる）。")
        return 1

    print(f"✅ testpaths の外に新しい赤はありません（{len(files)} ファイルを"
          f"基準 {merge_base[:8]} と突き合わせました）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
