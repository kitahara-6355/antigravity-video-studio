"""実装不足項目の台帳と点検（2026-08-27 ユーザー決定）。

**実装が足りていない機能を1箇所に集め、新しい漏れと片付け忘れを機械が見つける。**

分かっていた7件のうち3件は正典 `vision_backlog.json` の条件文に散らばって書かれ、
残り4件は**どこにも書かれていなかった**（実走ログと品質ゲートの出力にしか出ない）。

証拠は**実行記録**に取る。ソース走査だと「書いてあるが動かない」を実装済みと
誤認する（`placeholder_video_id` がその実例）。

    python -m backend.feature_gaps --show                 # 一覧
    python -m backend.feature_gaps --audit                # 点検（実行記録も見る）
    python -m backend.feature_gaps --audit --static-only  # CI 用（実走できないので）

設計: `docs/specs/2026-08-27-feature-gaps-design.md`
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GAPS_PATH = REPO_ROOT / "backend" / "config" / "feature_gaps.json"

REQUIRED = ("id", "title", "kind", "why", "done_when")
VALID_KINDS = ("gap", "intentional")


def load_gaps(path: Path | None = None) -> list[dict]:
    p = Path(path or GAPS_PATH)
    if not p.is_file():
        raise FileNotFoundError(f"台帳がありません: {p}")
    return json.loads(p.read_text(encoding="utf-8"))["gaps"]


def check_entries(gaps: list[dict]) -> list[str]:
    """**記載不備。**「あとで書く」を許さない。理由の無い項目は思い出せない。"""
    出た: list[str] = []
    見た: set[str] = set()
    for g in gaps:
        rid = g.get("id") or "(id なし)"
        欠け = [k for k in REQUIRED if not g.get(k)]
        # **`gap` はどこで直すかが要る。** `intentional` は直さないので要らない
        if g.get("kind") == "gap" and not g.get("handled_in"):
            欠け.append("handled_in")
        if 欠け:
            出た.append(f"{rid}: 項目が欠けています: {', '.join(欠け)}")
        if g.get("kind") and g["kind"] not in VALID_KINDS:
            出た.append(f"{rid}: kind は {' / '.join(VALID_KINDS)} のどちらか"
                        f"（いまは {g['kind']}）")
        if rid in 見た:
            出た.append(f"{rid}: id が重複しています")
        見た.add(rid)
    return 出た
