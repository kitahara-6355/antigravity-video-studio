"""本線（agents）に R1 の保証が効いていること。R1.5-C1。

**R1 で硬化したのは2つあるパイプラインの片方だった。** 2026-08-26 に両方を
実走させて本線を `agents` 側に決めたが、そちらには R1 のガードが1つも無い:

- 実行記録が残らない（`output/runs/<run_id>/run.json` が書かれない）
- **工程が落ちても "completed" を返す。** 直列で中断するのは文字起こしだけで、
  校閲・スマートカットの失敗は握り潰される。並列側は例外すらログだけ
- どのモデルで動いたかが残らない（見える化の要件）

ここで固定するのは「記録が残ること」と「失敗が握り潰されないこと」。
**プレビューの失敗だけは宣言された例外**（T-020b・パイプラインを止めない）。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.pipeline_coordinator import PipelineCoordinator  # noqa: E402
from agents.pipeline_types import PipelineContext, StageResult  # noqa: E402

CLIP = Path(__file__).parent.parent.parent / "output" / "testclips" / "r1_clip30s.mp4"


def _coordinator(tmp_path, 落ちる=(), *, final_path=None):
    """全 worker を差し替えた司令塔。**実際の処理はしない。**

    `落ちる` に入れたクラス名の worker だけ `success=False` を返す。
    """
    c = PipelineCoordinator()
    c.runs_dir = tmp_path / "runs"

    for w in c.workers:
        ok = type(w).__name__ not in 落ちる

        async def _fake(ctx, _w=w, _ok=ok):
            if _ok and type(_w).__name__ == "RenderWorker" and final_path:
                ctx.final_path = str(final_path)
            return StageResult(stage_name=_w.name, success=_ok,
                               detail="やった" if _ok else "落ちた")

        w.execute = _fake
        w.verify = lambda r: r.success
    return c


def _run(coordinator, tmp_path):
    ctx = PipelineContext(video_path=str(tmp_path / "入力.mp4"),
                          session_id="test-session")
    return asyncio.run(coordinator.execute(ctx))


def _run_json(tmp_path):
    runs = sorted((tmp_path / "runs").glob("*/run.json"))
    assert runs, "実行記録が1件も書かれていません"
    return json.loads(runs[-1].read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def 学習の副作用を止める(monkeypatch):
    """**実走のたびに本番の追跡ファイルが書き換わる**（2026-08-26 に1回起こした）。

    比較のため1回走らせただけで `verified_facts_index.json` から138行、
    `VERIFIED_FACTS.md` から28行が消えた。テストでは必ず止める。
    """
    monkeypatch.setenv("AVS_SKIP_LEARNING_SIDE_EFFECTS", "1")


def test_工程ごとに実行記録が残る(tmp_path):
    _run(_coordinator(tmp_path), tmp_path)
    run = _run_json(tmp_path)

    名前 = [s["name"] for s in run["stages"]]
    assert len(名前) == 7, f"7工程ぶん残っていません: {名前}"
    for stage in run["stages"]:
        assert stage["model"], f"{stage['name']} にモデルが記録されていません"


def test_使ったモデルが工程ごとに分かる(tmp_path):
    _run(_coordinator(tmp_path), tmp_path)
    run = _run_json(tmp_path)

    by_name = {s["name"]: s for s in run["stages"]}
    assert by_name["transcribe"]["model"].startswith("local:")
    # 校閲・メタデータ・品質は LLM。**段から引く**（直書きしない）
    assert by_name["proofread"]["tier"] in ("batch", "standard", "premium", "pro")
    assert by_name["youtube_opt"]["tier"]
    assert by_name["quality_gate"]["tier"]


def test_失敗した工程の原因と入力が残る(tmp_path):
    _run(_coordinator(tmp_path, 落ちる={"ProofreadWorker"}), tmp_path)
    run = _run_json(tmp_path)

    落ちた = [s for s in run["stages"] if s["status"] == "failed"]
    assert 落ちた, "失敗した工程が記録されていません"
    assert 落ちた[0]["name"] == "proofread"
    assert 落ちた[0].get("error"), "原因が残っていません"
    assert 落ちた[0].get("input"), "入力が残っていません"


def test_必須工程が落ちたら完走扱いにしない(tmp_path):
    """**「何もしていないのに success」を止める。** R1 で video_pipeline に入れた保証。"""
    result = _run(_coordinator(tmp_path, 落ちる={"RenderWorker"}), tmp_path)

    assert result["status"] != "completed", (
        f"最終レンダリングが落ちたのに status={result['status']}")
    assert _run_json(tmp_path)["status"] == "failed"


def test_校閲の失敗も握り潰さない(tmp_path):
    """直列で中断するのが文字起こしだけだったので、校閲の失敗が消えていた。"""
    result = _run(_coordinator(tmp_path, 落ちる={"ProofreadWorker"}), tmp_path)

    assert result["status"] != "completed"


def test_プレビューの失敗は止めないが完走とも呼ばない(tmp_path):
    """T-020b。**止めないが、成功にもしない。**"""
    result = _run(_coordinator(tmp_path, 落ちる={"PreviewWorker"},
                               final_path=CLIP), tmp_path)
    run = _run_json(tmp_path)

    assert result["status"] == "degraded", "止めないが、完走とも呼ばない"
    assert any("プレビュー" in w for w in result["health"]["warnings"])
    落ちた = [s["name"] for s in run["stages"] if s["status"] == "failed"]
    assert set(落ちた) == {"preview"}, f"失敗そのものは記録に残すこと: {落ちた}"
    # **やり直しも1回ずつ残す。** 「何回粘ったか」が見えないと、
    # たまたま通ったのか安定して通ったのかが区別できない。
    assert len(落ちた) == PipelineCoordinator.MAX_RETRIES


@pytest.mark.skipif(not CLIP.is_file(), reason="検証用クリップがありません")
def test_成果物ゲートが本線の記録の形を認める(tmp_path):
    """R1.5-C1 の verify は `artifact_gate --gate`。

    **ここで見るのは記録の形だけ。** worker を差し替えているので API は
    1回も呼ばれず、段を宣言した工程は `model_unverified` になる。
    **それは正しい指摘**（宣言だけで動いていないモデルを緑にしない）なので、
    ここでは「それ以外の指摘が出ないこと」を確かめる。
    ゲートが本当に通ることは実走で示す。
    """
    from backend.revenue.artifact_gate import check_runs, load_runs

    _run(_coordinator(tmp_path, final_path=CLIP), tmp_path)
    findings = check_runs(load_runs(tmp_path / "runs"))

    それ以外 = [f for f in findings if f.kind != "model_unverified"]
    assert not それ以外, f"本線の実行記録がゲートを通りません: {それ以外}"
