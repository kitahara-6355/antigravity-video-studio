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


def _mainline_stage_names() -> set[str]:
    """**本線の工程名は実装不足ではない。** 落ちたのは工程であって機能ではない。

    実行記録には3種類が同じ顔で出る — 工程が落ちた（`quality_gate`）／
    意図して止めている（`dream_learning`）／実装が足りていない
    （`BGMミキシング(ファイルなし)`）。**区別しないと点検が誤検知する。**
    """
    try:
        from agents.pipeline_coordinator import STAGE_RECORD
    except ImportError:  # PYTHONPATH=./backend が無いとき
        from backend.agents.pipeline_coordinator import STAGE_RECORD
    return {v[0] for v in STAGE_RECORD.values()}


def surfaced_in(run: dict) -> list[str]:
    """実行記録に「やっていない」として出たものを重複なく並べる。"""
    health = run.get("health") or {}
    出たもの = (list(health.get("skipped_features") or [])
                + list(health.get("failed_stages") or []))
    return list(dict.fromkeys(出たもの))


def unknown_from_record(run: dict, gaps: list[dict]) -> list[str]:
    """**台帳にも本線の工程名にも無いもの。** 新しい実装漏れがこれで出る。"""
    既知 = _mainline_stage_names()
    印 = [g.get("surfaces_as") for g in gaps if g.get("surfaces_as")]
    return [名 for 名 in surfaced_in(run)
            if 名 not in 既知 and not any(s and s in 名 for s in 印)]
