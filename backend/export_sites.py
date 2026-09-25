"""R2-C1 の書き出し口の台帳と点検（2026-09-25）— **早期警報であって保証ではない**。

**C1 の保証は `approval_gate --gate` の置き場の監査**（`final/`・`shorts/` の完成品が
1本残らず承認に辿れること）。こちらは静的な走査なので、**書き方を列挙している以上、
網羅は原理的に保証できない**（2026-09-25 の gate-verifier 3周目が `subprocess.run`・
`open().write`・`os.replace`・`Path.rename` で書く関数を置いて、ゲートを緑のまま通した）。
役目は「承認を通さない書き出し口が**増えそうなとき**に早めに気づくこと」。
正典の limits にもそう宣言してある。

## なぜ要るか

**2周続けて「同じ実装への別入口」で崩れた。** gate-verifier は1周目に
`POST /api/shorts/render` で、2周目に `POST /api/video/process/start` で、
承認を1件も作らずに完成動画を実生成した。どちらも私が手で grep して塞いだ
つもりの経路の**隣**にあった。

手で探す限り3度目が起きる。**動画を書きうる本番の関数を機械が列挙し、
台帳と突き合わせる。** 台帳に無い候補が出たら FAIL。これは R1.5-C4 の
`c4_inventory` と同じ作りで、あちらは「数字を作る関数」を、ここは
「動画を書く関数」を掃く。

## 何を「書き出し」と呼ぶか

正典（`vision_backlog.json` の R2-C1）の定義に従う:

    **投稿できる完成品を作ること**（`vault-outputs/final`・`vault-outputs/shorts`
    への出力、または手動投稿用サイドカーを伴う出力）。プレビュー・中間生成物
    （merged / edited / 色補正の試作）は含まない。

したがって候補の抽出は広く取り（動画を書きうる関数をすべて拾う）、**完成品か
中間物かの判定は台帳の `status` で人が宣言する。** 判定を機械に持たせると、
「中間物だと機械が思い込んだ完成品」が静かに素通りする。

## 台帳の status

| status | 意味 |
|---|---|
| `gated` | 承認の門を引いている（`export_allowed` を呼ぶ／門の内側にある） |
| `refuses` | 承認を通さないので断る（閉じた経路。409 や例外） |
| `intermediate` | 完成品ではない（プレビュー・中間物・試作）。**理由が要る** |
| `out_of_scope` | 凍結・非推奨・開発用スクリプトなど、正典の limits で宣言済み。**理由が要る** |
| `unreachable` | **完成品の置き場に書く**が、本番から到達しない（呼び口を閉じた）。**理由が要る** |

使い方:

    python -m backend.export_sites --scan    # いまのソースから候補を出す
    python -m backend.export_sites --show    # 台帳の一覧
    python -m backend.export_sites --gate    # 台帳と実態を突き合わせる（違反で exit 1）
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = Path(__file__).resolve().parent / "config" / "export_sites.json"

# 掃く範囲。テストと過去版は本番ではない
除外 = ("backend/tests/", "backend/harness/test_", "tests/", "archives/",
        "antigravity_phase18", "antigravity_phase19", "__pycache__",
        "backend/agents/orchestration/")

# 動画を書きうる呼び出し。**広く取る** — 完成品かどうかは台帳で宣言する
書き出しの道具 = (
    "run_command",      # FFmpegEditor.run_command
    "Popen", "call", "check_output", "check_call",
    "copy", "copy2", "copyfile", "move",
    "write_bytes",
)
# 書き出しに至る既知の入口（他所の書き出し関数を呼ぶもの）
書き出しを頼む先 = (
    "process_video", "apply_preset", "generate_preview", "render_batch",
    "execute_ffmpeg_render", "_execute_ffmpeg_render",
    "_render_production_quality", "render_video", "export_video",
    # 他所の書き出し関数を呼ぶ口。**ここに足すのは「実際に動画を書く関数」の名前だけ。**
    # `create_final_video` を入れていなかったので `POST /editor/create-final` を
    # 取りこぼした（2026-09-25。走査の1回目で気づいた）
    "create_final_video", "create_final", "create_prefinal",
    "fix_and_concat", "render_smart_cut", "compose", "add_bgm",
)
動画の匂い = (".mp4", ".mov", ".mkv", ".webm", "VAULT_OUTPUTS_DIR",
             "video_output", "output/final", "output/shorts", "vault-outputs",
             # **出力先を引数で受け取る関数**は拡張子の literal を持たない。
             # `routers/shorts.py::_execute_ffmpeg_render` がこれで漏れていた（2026-09-25）
             "output_path", "final_path", "out_file", "output_file", "out_path")

REQUIRED = ("id", "file", "symbol", "status", "reason")
STATUSES = ("gated", "refuses", "intermediate", "out_of_scope", "unreachable")


def _production_py(root: Path = ROOT) -> list[Path]:
    files = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        if any(rel.startswith(x) or x in rel for x in 除外):
            continue
        if rel.startswith(("backend/", "tools/")) or rel.count("/") == 0:
            files.append(p)
    return sorted(files)


def _呼び出しの名前(node: ast.AST) -> list[str]:
    names = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                names.append(f.attr)
            elif isinstance(f, ast.Name):
                names.append(f.id)
    return names


def _関数を歩く(tree: ast.AST):
    """ネストしたクラス・関数も含めて (修飾名, ノード) を返す。"""
    def 降りる(node, 親: list[str]):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                名 = ".".join(親 + [child.name])
                yield 名, child
                yield from 降りる(child, 親 + [child.name])
            elif isinstance(child, ast.ClassDef):
                yield from 降りる(child, 親 + [child.name])
            else:
                yield from 降りる(child, 親)
    yield from 降りる(tree, [])


def scan(root: Path = ROOT) -> list[dict]:
    """いまのソースから「動画を書きうる関数」を拾う。`root` はテストで差し替える。"""
    出た = []
    for path in _production_py(root):
        try:
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        rel = path.relative_to(root).as_posix()
        for 名, fn in _関数を歩く(tree):
            body = ast.get_source_segment(src, fn) or ""
            呼び = _呼び出しの名前(fn)
            道具 = sorted({c for c in 呼び if c in 書き出しの道具})
            頼み = sorted({c for c in 呼び if c in 書き出しを頼む先})
            匂う = any(s in body for s in 動画の匂い)
            # 「動画の匂いがある + 書き出しの道具を使う」か「書き出しを頼む」
            if not ((匂う and 道具) or 頼み):
                continue
            出た.append({
                "id": f"{rel}::{名}",
                "file": rel,
                "symbol": 名,
                "line": fn.lineno,
                "tools": 道具 + 頼み,
            })
    return 出た


def load_ledger(path: Path | None = None) -> dict:
    path = path or LEDGER
    if not path.is_file():
        return {"criterion": "R2-C1", "sites": []}
    return json.loads(path.read_text(encoding="utf-8"))


def check_entries(sites: list[dict]) -> list[str]:
    """台帳そのものの不備。**理由の無い宣言を通さない。**"""
    問題 = []
    for s in sites:
        欠け = [k for k in REQUIRED if not s.get(k)]
        if 欠け:
            問題.append(f"{s.get('id', '(id なし)')}: 項目が欠けています {欠け}")
            continue
        if s["status"] not in STATUSES:
            問題.append(f"{s['id']}: status が {s['status']}（{'/'.join(STATUSES)} のいずれか）")
        if s["status"] in ("intermediate", "out_of_scope", "unreachable") and len(s["reason"]) < 20:
            問題.append(f"{s['id']}: {s['status']} は理由を書いてください（いまの理由は {len(s['reason'])} 文字）")
    ids = [s.get("id") for s in sites]
    重複 = {i for i in ids if ids.count(i) > 1}
    問題 += [f"台帳に重複した id があります: {i}" for i in sorted(重複)]
    return 問題


def audit(sites: list[dict], 実態: list[dict] | None = None) -> tuple[list[str], list[str]]:
    """台帳と実態を突き合わせる。違反と情報を返す。"""
    実態 = scan() if 実態 is None else 実態
    台帳 = {s["id"]: s for s in sites}
    いま = {c["id"]: c for c in 実態}

    違反 = [
        f"台帳に無い書き出し口: {c['id']}（L{c['line']} / {', '.join(c['tools'])}）"
        for cid, c in sorted(いま.items()) if cid not in 台帳
    ]
    情報 = [
        f"台帳にあるがソースに無い（消えたか改名された）: {sid}"
        for sid in sorted(台帳) if sid not in いま
    ]
    return 違反, 情報


def _format(ledger: dict, 実態: list[dict]) -> str:
    sites = ledger.get("sites", [])
    行 = ["R2-C1 書き出し口の台帳", "",
          f"  台帳: {len(sites)} 件 / いまのソースの候補: {len(実態)} 件", ""]
    for status in STATUSES:
        該当 = [s for s in sites if s.get("status") == status]
        行.append(f"  [{status}] {len(該当)} 件")
        for s in sorted(該当, key=lambda x: x["id"]):
            行.append(f"      {s['id']}")
    return "\n".join(行)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="R2-C1 の書き出し口の台帳と点検")
    ap.add_argument("--show", action="store_true", help="一覧を出す")
    ap.add_argument("--gate", action="store_true", help="点検する（違反があれば exit 1）")
    ap.add_argument("--scan", action="store_true", help="いまのソースから候補を出す（台帳は書き換えない）")
    args = ap.parse_args(argv)

    実態 = scan()
    if args.scan:
        for c in 実態:
            print(f"{c['id']}  L{c['line']}  {', '.join(c['tools'])}")
        print(f"\n{len(実態)} 件")
        return 0

    ledger = load_ledger()
    if args.show or not args.gate:
        print(_format(ledger, 実態))
        return 0

    sites = ledger.get("sites", [])
    不備 = check_entries(sites)
    違反, 情報 = audit(sites, 実態)
    if 情報:
        print(f"  ℹ 台帳の掃除ができます（{len(情報)} 件・違反ではありません）:")
        for i in 情報:
            print(f"      - {i}")
        print()
    if 不備 or 違反:
        print(f"🚫 **動画の書き出し口が台帳と食い違っています**（{len(不備) + len(違反)} 件）:")
        for x in 不備 + 違反:
            print(f"    - {x}")
        print()
        print("  「台帳に無い書き出し口」は**掃引の漏れ**です。1件ずつ見て、")
        print("  承認の門を引かせる（gated）か、断る（refuses）か、")
        print("  完成品ではない理由（intermediate）か、対象外の理由（out_of_scope）を台帳に書いてください。")
        print("  **判定を機械に持たせない** — 中間物だと機械が思い込んだ完成品が素通りするため。")
        return 1

    print(f"✅ 動画を書きうる本番の関数 {len(実態)} 件は、すべて台帳にあります"
          f"（門を引く {sum(1 for s in sites if s['status'] == 'gated')} 件 / "
          f"断る {sum(1 for s in sites if s['status'] == 'refuses')} 件 / "
          f"完成品ではない {sum(1 for s in sites if s['status'] == 'intermediate')} 件 / "
          f"対象外 {sum(1 for s in sites if s['status'] == 'out_of_scope')} 件 / "
          f"到達しない {sum(1 for s in sites if s['status'] == 'unreachable')} 件）"
          "\n  ※ 静的な走査は**早期警報**で、網羅は保証しません。"
          "C1 の保証は `python -m backend.revenue.approval_gate --gate` の置き場の監査です")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
