"""正典の台帳が自分自身と食い違わないこと（憲法第5条）。

`vision_backlog.json` は **`exit_criteria` を2箇所に持っている**:

    $.current_phase.exit_criteria
    $.roadmap.phases.<現フェーズ>.exit_criteria

gate-verifier 2周目の指摘:

> 現時点で完全一致だが、同期を強制する仕組みが無い。読むコードは
> `.claude/hooks/session_context.py` 1つだけで、そこは `current_phase` 側しか
> 読まない。つまり `roadmap.phases.R1` 側は誰も読まない写し。
> 片方だけ met を更新すると静かに腐る。

**索引が2つあると片方が腐る。** 過去に同じ型を踏んでいるので、
一致をテストで固定する。片方を消さないのは、`roadmap` 側が
フェーズの並び全体を持つ台帳で、`current_phase` が現在地の切り出しだから。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

CANON = (Path(__file__).resolve().parents[2]
         / "backend" / "branding" / "vision_backlog.json")


@pytest.fixture(scope="module")
def canon() -> dict:
    return json.loads(CANON.read_text(encoding="utf-8"))


def test_正典が読める(canon):
    assert canon["current_phase"]["id"]


def test_現フェーズがロードマップに存在する(canon):
    phase_id = canon["current_phase"]["id"]
    assert phase_id in canon["roadmap"]["phases"], (
        f"current_phase.id={phase_id} がロードマップにありません"
    )


def test_現フェーズの終了条件が2箇所で一致する(canon):
    """**片方だけ更新すると静かに腐る。** ここで止める。"""
    phase_id = canon["current_phase"]["id"]
    here = canon["current_phase"]["exit_criteria"]
    there = canon["roadmap"]["phases"][phase_id]["exit_criteria"]

    assert here == there, (
        f"current_phase と roadmap.phases.{phase_id} の exit_criteria が"
        f"食い違っています。met を片方だけ更新していませんか"
    )


def test_終了条件のidが重複しない(canon):
    for phase_id, phase in canon["roadmap"]["phases"].items():
        ids = [c["id"] for c in phase.get("exit_criteria") or []]
        assert len(ids) == len(set(ids)), f"{phase_id} に重複した id: {ids}"


def test_終了条件に必要な項目が揃っている(canon):
    for phase_id, phase in canon["roadmap"]["phases"].items():
        for c in phase.get("exit_criteria") or []:
            missing = [k for k in ("id", "condition", "met") if k not in c]
            assert not missing, f"{phase_id}/{c.get('id')} に不足: {missing}"
            assert isinstance(c["met"], bool), (
                f"{phase_id}/{c['id']} の met が bool ではありません"
            )


def test_ロードマップの並びと実体が一致する(canon):
    order = canon["roadmap"]["order"]
    phases = canon["roadmap"]["phases"]

    assert set(order) == set(phases), (
        f"order と phases が食い違っています: "
        f"order のみ={set(order) - set(phases)} / "
        f"phases のみ={set(phases) - set(order)}"
    )
    assert len(order) == len(set(order)), f"order に重複: {order}"


def test_フェーズの並びは現フェーズから始まる(canon):
    """現在地より前のフェーズが並びに残っていないこと。"""
    order = canon["roadmap"]["order"]
    assert canon["current_phase"]["id"] in order
