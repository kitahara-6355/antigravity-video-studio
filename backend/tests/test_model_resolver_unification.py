"""モデル解決器は1つであること。R1.5-C2。

**解決器が2つあって、全工程で食い違っていた**（2026-08-26 に実走で発覚）。

`model_config.json` の `task_mapping` は**段の名前**（`"standard"` / `"premium"`）を持つ。
`model_policy.resolve()` はこれを段として解決するが、
`model_governance._resolve_model()` は**生のまま返していた**。返った値がモデル ID として
API に渡り、こうなる:

    404 NOT_FOUND: models/standard is not found for API version v1beta

`soul_feedback` 以外の製品の LLM 呼び出しはほぼ全部これで落ちていた。
「21工程登録されているのに実走で1回しか呼ばれない」の原因。

**ここで固定するのは「解決結果が一致すること」であって、実装の中身ではない。**
`model_governance` が内部にマッピングを持つこと自体は禁じない（テストが注入する）。
禁じるのは**答えが2種類あること**。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import model_policy  # noqa: E402
from model_governance import model_governance  # noqa: E402


@pytest.fixture(autouse=True)
def 正典の設定に戻す():
    """**シングルトンは他のテストに汚される。**

    `test_shared/test_model_governance.py` が `_task_mapping` を直接差し替えるので、
    同じバッチに入ると解決結果が変わる。前後で正典から読み直す。
    """
    model_governance.reload()
    yield
    model_governance.reload()


@pytest.fixture
def 枠は空いている():
    """枠枯渇による自動降格を止める。**ここで見たいのは解決であって降格ではない。**"""
    with patch("usage_tracker.tracker.usage_tracker.can_make_request",
               return_value=True):
        yield


def test_全工程で解決結果が一致する(枠は空いている):
    """R1.5-C2 の本体。**食い違いが1つでもあれば FAIL。**"""
    食い違い = []
    for task in sorted(model_policy.known_tasks()):
        policy = model_policy.resolve(task).model
        governance = model_governance._resolve_model(task)
        if policy != governance:
            食い違い.append(f"{task}: policy={policy} / governance={governance}")

    assert not 食い違い, (
        "モデル解決器が2つあります（段の名前がモデル ID として API に渡ります）:\n  "
        + "\n  ".join(食い違い))


def test_段の名前がモデルidとして漏れない(枠は空いている):
    """`models/standard is not found` を二度と出さない。"""
    段の名前 = set(model_policy.tiers())
    漏れ = [f"{task} -> {model_governance._resolve_model(task)}"
            for task in sorted(model_policy.known_tasks())
            if model_governance._resolve_model(task) in 段の名前]

    assert not 漏れ, f"段の名前がモデル ID として返っています: {漏れ}"


def test_知らない工程でも段の名前を返さない(枠は空いている):
    """`task_mapping` に無い工程は既定モデルへ落ちる。段の名前ではない。"""
    resolved = model_governance._resolve_model("存在しない工程")

    assert resolved not in set(model_policy.tiers())
    assert resolved == model_policy.resolve("存在しない工程").model


def test_ユーザーの昇格が両方に効く(tmp_path, 枠は空いている, monkeypatch):
    """**`--up` は片方だけに効いてはいけない。**

    上書きは `model_policy` 側のファイルに書かれる。`model_governance` が
    自前のマッピングだけを見ていると、昇格したのに古い段で走り続ける。
    """
    monkeypatch.setattr(model_policy, "OVERRIDES_PATH",
                        tmp_path / "model_overrides.json")
    monkeypatch.setattr(model_policy, "HISTORY_PATH",
                        tmp_path / "escalations.jsonl")

    前 = model_governance._resolve_model("director")
    model_policy.escalate("director", reason="テスト（品質に不満）")
    後 = model_governance._resolve_model("director")

    assert 後 != 前, "昇格が model_governance 側に伝わっていません"
    assert 後 == model_policy.resolve("director").model


def test_明示指定は従来どおり優先する(枠は空いている):
    """呼び出し側がモデルを名指ししたら、それが勝つ（既存の挙動）。"""
    assert model_governance._resolve_model(
        "quality_gate", model="gemini-3.5-flash-lite") == "gemini-3.5-flash-lite"


def test_段のモデルは直書きの工程を壊さない(枠は空いている):
    """imagen / veo は段の外。**段として解こうとして壊さないこと。**"""
    for task in ("thumbnail", "opening_video"):
        assert model_governance._resolve_model(task) == \
            model_policy.resolve(task).model


def test_注入されたマッピングは尊重される():
    """**model_governance の自前マッピングを消さない。**

    テストや実験が `_task_mapping` を差し替える使い方は残す。禁じるのは
    「段の名前を生で返すこと」であって、注入そのものではない。
    """
    from model_governance import ModelGovernanceEngine

    engine = ModelGovernanceEngine()
    元 = dict(engine._task_mapping)
    try:
        engine._task_mapping = {"quality_gate": "gemini-3.5-flash-lite"}
        with patch("usage_tracker.tracker.usage_tracker.can_make_request",
                   return_value=True):
            assert engine._resolve_model("quality_gate") == "gemini-3.5-flash-lite"
    finally:
        engine._task_mapping = 元


# --- 点検が本当に落ちるか（R1.5-C2 の verify は --audit） -----------------------


def test_解決器が食い違ったら点検が落ちる(monkeypatch, 枠は空いている):
    """**緑になったことより、赤にできることを確かめる。**

    食い違いを作って `--audit` が拾うことを見ないと、
    「一致していたから緑」なのか「見ていないから緑」なのか区別できない。
    """
    monkeypatch.setattr(model_governance, "_resolve_declared",
                        lambda task: "standard")

    findings, _ = model_policy.audit()
    split = [f for f in findings if f.trigger == "resolver_split"]

    assert split, "解決器の食い違いを点検が拾っていません"
    assert any("standard" in f.model for f in split)


def test_解決器を確かめられなければ点検が落ちる(monkeypatch, 枠は空いている):
    """**確かめられないことを緑にしない。**"""
    monkeypatch.delattr(model_governance, "_resolve_declared", raising=False)
    monkeypatch.setattr(type(model_governance), "_resolve_declared", None,
                        raising=False)

    findings, _ = model_policy.audit()

    assert [f for f in findings if f.trigger == "resolver_unverified"], \
        "解決器を確かめられなかったのに、点検が緑のままです"


def test_一致しているときは点検に出ない(枠は空いている):
    findings, _ = model_policy.audit()

    assert not [f for f in findings
                if f.trigger in ("resolver_split", "resolver_unverified")]
