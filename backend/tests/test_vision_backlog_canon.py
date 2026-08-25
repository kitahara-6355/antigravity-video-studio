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


# --- 幹（invariants）が腐らないこと ---------------------------------------------
#
# 2026-08-21 にロードマップを2層に分けた。`invariants` は新事実で変えない層で、
# `roadmap.phases` は手段なので変えてよい。**参照が切れると2層に分けた意味が消える**
# ので、繋がりをここで固定する。


def test_幹が存在する(canon):
    gates = canon["invariants"]["gates"]
    assert [g["id"] for g in gates] == ["G1", "G2", "G3", "G4"]
    for g in gates:
        assert g["condition"] and g["why"], f"{g['id']} に条件か理由が無い"


def test_幹に手段を書かない(canon):
    """**幹は「何が言えるようになるか」で書く。** ファイル名やコマンドが出たら枝。"""
    forbidden = (".py", ".json", "python -m", "backend/", "http")
    for g in canon["invariants"]["gates"]:
        for word in forbidden:
            assert word not in g["condition"], (
                f"{g['id']} の条件に実装詳細が入っている: {word}"
            )


def test_全フェーズが幹を指す(canon):
    """どの関門に効くのか分からないフェーズを作らない。"""
    known = {g["id"] for g in canon["invariants"]["gates"]}
    for pid, phase in canon["roadmap"]["phases"].items():
        if pid == canon["current_phase"]["id"]:
            continue  # 完了済みの現フェーズは対象外
        gates = phase.get("gates")
        assert gates, f"{pid} が幹を指していない"
        unknown = [g for g in gates if g not in known]
        assert not unknown, f"{pid} が知らない幹を指している: {unknown}"


def test_本線が実在するファイルを指す(canon):
    """**本線の宣言が腐らないこと。** 消えたファイルを指していたら気づけるように。"""
    from pathlib import Path

    mainline = canon["invariants"]["mainline"]["choice"]
    path = CANON.parents[2] / mainline
    assert path.is_file(), f"本線が実在しない: {mainline}"


def test_外部期日が残っている(canon):
    """期日は幹。消えたら逆算ができなくなる。"""
    deadlines = {d["at"] for d in canon["invariants"]["deadlines"]}
    assert "2026-10-16" in deadlines
    assert "2027-02-01" in deadlines


def test_前提が宣言されている(canon):
    """**未着手フェーズは assumptions を持つこと。**

    前提を書いておくと、新事実が出たときに「どのフェーズが影響を受けるか」が
    予測できる。R1 で「実測原価が本番を代表している」という前提を誰も書いて
    いなかったので、それが崩れたときに R4 への波及が見えなかった。
    """
    for pid in ("R1.5", "R5"):
        phase = canon["roadmap"]["phases"][pid]
        assert phase.get("assumptions"), f"{pid} が賭けている前提を宣言していない"
