#!/usr/bin/env python3
"""テストによる本番ファイル汚染のラチェット（増加を許さない）。

背景:
    テストを流すと本番ファイルが書き換わる。`Human01_Official Artifact/` は
    会話ログを含むため公開時に意図的に除去したものだが、テストが再生成し、
    気づかずコミットすると除去した意味が消える。検出の仕組みは
    `backend/tests/fs_guard.py`（記録のみ・挙動は変えない）。

    汚染源は 2026-07-31〜08-01 に潰し切った。ここから先に必要なのは
    「もう一度増えたときに気付く」こと。Ruff / 絶対パスと同じ順序
    （観測 → 修正 → **増加を禁じる**）の最後の段。

なぜ静的解析ではないか:
    書き込み先は実行時にしか分からない。`open()` の引数がその場の文字列とは
    限らず、アトミック書き込み（一時ファイル + `os.replace`）のように
    経路が分かれるものもある。だから入力はテスト実行の実測
    （`fs-guard-records.jsonl`）で、このスクリプトはその判定だけを持つ。

なぜファイルの不在を成功にしないか:
    「検出ゼロ」と「計測が走らなかった」を取り違えると、テストが
    落ちて fs_guard が動かなかった回に黙って緑になる。fs_guard は
    検出ゼロでも空のファイルを必ず作る。**不在は失敗**として扱う。

判定の粒度:
    パスごとに「何テストがそこへ書いたか」を数える。合計だけを見ていると、
    片方を減らしたぶんでもう片方の増加を相殺できてしまう（絶対パス
    ラチェットで分類を分けたのと同じ理由）。パス単位ならその余地が無い。

    ただし**そのままのパスは鍵にできない**。2026-08-01 の実測では、
    汚染先の名前に実行ごとの識別子が入るものが多数あった。

        Human01_Official Artifact/受信トレイ/session_complete_report_20260801_021840_UTC.md
        backend/temp_thumbnails/pipeline_status_thumb_task.c16930fad4c8….tmp
        backend/tests/performance/worker_perf_<uuid>.json
        backend/migration_backups/backup_20260801_104305/

    これらは実行のたびに別のパスになるので、素の文字列で数えるとベースラインに
    無い鍵が毎回生まれ、ラチェットが恒常的に赤くなる（＝誰も見なくなる）。
    揺れる部分だけを伏せ字にしてから数える。normalize() がその処理。

運用:
    ベースラインは .github/fs-guard-baseline.json。減らしたら
    `python .github/scripts/fs_guard_ratchet.py --update` で更新する
    （下げる方向のみ許可）。

    ベースラインは **CI(Linux) の実測**で作る。手元(Windows)とは通る経路が
    違ううえ、CI が流すのは testpaths の中だけなので、ローカルの全掃引で
    作ると CI が一度も出さない鍵が並ぶ。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / ".github" / "fs-guard-baseline.json"
RECORDS = ROOT / "fs-guard-records.jsonl"


# 実行ごとに変わる部分。左から順に当てる（時刻は数字より先に落とす）。
#
# 数字は4桁以上だけを伏せる。`task_001.png` のような固定の連番まで潰すと、
# 別々の汚染先が同じ鍵に畳まれて増加が見えなくなる。実測で揺れていたのは
# 日付(8桁)・時刻(4〜6桁)・PID(4〜5桁)で、いずれも4桁以上だった。
_VOLATILE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\d{8}[_-]\d{6}"), "<TS>"),                     # 20260801_104305
    (re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"), "<UUID>"),
    (re.compile(r"\b[0-9a-fA-F]{12,}\b"), "<HEX>"),
    (re.compile(r"\d{4,}"), "<N>"),
)


def normalize(path: str) -> str:
    """実行ごとに変わる部分を伏せ字にする。

    伏せすぎると別の汚染先が同じ鍵に畳まれ、増加が隠れる。
    伏せなさすぎると毎回「新規」が出てラチェットが機能しない。
    実測で揺れていたものだけを対象にする。
    """
    for pattern, placeholder in _VOLATILE:
        path = pattern.sub(placeholder, path)
    return path


def test_key(node_id: str) -> str:
    """テストの識別子を実行構成に依らない形にする。

    pytest の nodeid は rootdir 相対で、rootdir はバッチの中身で変わる
    （`backend/tests/` だけのバッチでは rootdir が `backend/tests` になり、
    同じテストが `test_x.py::t` とも `backend/tests/test_x.py::t` とも綴られる）。
    先頭のディレクトリを落として揃える。モジュール名の一意性は
    scripts/check_test_module_collisions.py が保証している。
    """
    file, sep, rest = node_id.partition("::")
    return file.replace("\\", "/").rsplit("/", 1)[-1] + sep + rest


def read_records(path: Path) -> dict[str, int]:
    """JSONL を読み、パスごとの「汚したテスト数」に畳む。

    バッチ分割実行ではプロセスごとに追記されるため、同じパスが複数行に
    現れる。テスト名の集合として合流させる — 行数を足すとバッチの
    分割数だけ数字が変わってしまう。
    """
    by_path: dict[str, set[str]] = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            print(f"{path.name}:{lineno} を解析できませんでした", file=sys.stderr)
            return {}
        by_path.setdefault(normalize(item["path"]), set()).update(
            test_key(t) for t in item.get("tests") or []
        )
    return {p: len(t) for p, t in sorted(by_path.items())}


def write_baseline(counts: dict[str, int]) -> None:
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(
        json.dumps(
            {"total_paths": len(counts), "by_path": dict(sorted(counts.items()))},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default=str(RECORDS),
                    help="fs_guard が出力した JSONL（既定: リポジトリ直下）")
    ap.add_argument("--update", action="store_true",
                    help="ベースラインを現在値で更新する（増加方向は拒否）")
    args = ap.parse_args()

    records_path = Path(args.records)
    if not records_path.exists():
        print(f"::error ::{records_path.name} がありません。"
              "fs_guard が動いていない可能性があります"
              "（ANTIGRAVITY_FS_GUARD=0 になっていないか、"
              "テストが1件も収集されなかったか）。")
        return 2

    current = read_records(records_path)

    if not BASELINE.exists():
        write_baseline(current)
        print(f"ベースラインを新規作成しました: {len(current)} パス")
        return 0

    base: dict[str, int] = json.loads(BASELINE.read_text(encoding="utf-8")).get("by_path", {})

    # (パス, 前, 後)。表示用の文字列を後から解析すると壊れるので組で持つ。
    regressions: list[tuple[str, int, int]] = [
        (p, base.get(p, 0), n) for p, n in current.items() if n > base.get(p, 0)
    ]
    fixed = [p for p in base if p not in current]

    print(f"汚染パス: {len(base)} → {len(current)}")
    for path, count in current.items():
        before = base.get(path)
        print(f"  {path}: {'新規' if before is None else before} → {count} テスト")

    if args.update:
        if regressions:
            print("\n汚染が増えているためベースラインを更新できません:")
            for path, before, now in regressions:
                print(f"  {path}: {before} → {now}")
            return 1
        write_baseline(current)
        print("ベースラインを更新しました")
        return 0

    if regressions:
        print(f"\n🚫 ラチェット違反: {len(regressions)} パスで汚染が増加しました")
        for path, before, now in regressions:
            label = "新規" if path not in base else str(before)
            print(f"  ::error ::{path}: {label} → {now} テスト")
        print(
            "\nテストが本番ファイルを書き換えています。書き込み先を "
            "tmp_path か backend/path_resolver.py の writable_path へ寄せてください。"
            "どのテストかは fs-guard-report.txt にあります。"
        )
        return 1

    if fixed:
        print(f"\n✅ 汚染が {len(fixed)} パス減りました。"
              f"--update でベースラインを更新することを推奨します")
    else:
        print("✅ ラチェット維持（汚染の増加なし）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
