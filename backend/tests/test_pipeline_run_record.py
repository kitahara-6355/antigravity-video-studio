"""パイプラインが実行記録（run.json）を残すこと。R1-C1/C4/C5/C6。

`RunRecorder` は 2026-08-15 から存在したが、**どの工程にも被さって
いなかった。** そのため 2026-08-19 の実走は 10/10 完走して mp4 も
出たのに、`artifact_gate --gate` は `no_run` で FAIL したままだった。
成果物があることと、動いた証拠が残ることは別物。

ここで固定するのは4つ:

- 工程ごとに **どのモデルで動いたか** が残る（R1-C6）。空の宣言を作らない
- LLM を使わない工程は `local:` で**「使っていない」と宣言する**。
  宣言し忘れと区別がつかないと、抜けていても気づけない
- 失敗した工程が特定でき、**その入力が残る**（R1-C4）
- 完成した mp4 が `artifacts` に載る（R1-C1）

記録先は明示的に渡したときだけ書く。既定で `output/runs/` に書くと、
**既存のパイプラインテストが本番ディレクトリを汚す。**
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.video_pipeline.pipeline_coordinator import (
    STAGE_ORDER,
    PipelineCoordinator,
)
from backend.revenue.run_record import LOCAL_PREFIX


def _fake_stage_output(stage_name: str, input_data: dict) -> dict:
    """`_execute_stage` の代わり。ffmpeg も Whisper も呼ばない。"""
    job_dir = input_data.get("job_dir", "")
    if stage_name == "compose":
        return {"output_path": str(Path(job_dir) / "composed_output.mp4")}
    if stage_name == "thumbnail":
        return {"thumbnail_path": str(Path(job_dir) / "thumb.jpg")}
    if stage_name == "quality_gate":
        return {"quality_score": 89.1, "quality_gate_passed": True}
    return {f"{stage_name}_done": True}


def _run(tmp_path: Path, runs_dir: Path | None, fail_at: str | None = None):
    def execute(stage_name, input_data):
        if stage_name == fail_at:
            raise RuntimeError("わざと落とす")
        return _fake_stage_output(stage_name, input_data)

    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir,
    )
    with patch.object(PipelineCoordinator, "_execute_stage",
                      side_effect=execute, autospec=False):
        return coordinator.run_pipeline("input.mp4")


def _load_only_run(runs_dir: Path) -> dict:
    runs = sorted(runs_dir.glob("*/run.json"))
    assert len(runs) == 1, f"実行記録が1件ではない: {runs}"
    return json.loads(runs[0].read_text(encoding="utf-8"))


# --- 記録が残る ---------------------------------------------------------------

def test_完走すると実行記録が1件書かれる(tmp_path):
    runs_dir = tmp_path / "runs"
    result = _run(tmp_path, runs_dir)

    assert result.success is True
    run = _load_only_run(runs_dir)
    assert run["status"] == "completed"
    assert [s["name"] for s in run["stages"]] == STAGE_ORDER


def test_所要時間が記録される(tmp_path):
    """R1-C2 の後半。1本あたりの所要時間はここに残る。"""
    runs_dir = tmp_path / "runs"
    _run(tmp_path, runs_dir)

    run = _load_only_run(runs_dir)
    assert run["duration_sec"] > 0
    assert all("duration_sec" in s for s in run["stages"])


def test_入力が記録される(tmp_path):
    runs_dir = tmp_path / "runs"
    _run(tmp_path, runs_dir)

    assert _load_only_run(runs_dir)["inputs"]["source"] == "input.mp4"


# --- モデルの見える化（R1-C5 / C6） -------------------------------------------

def test_全工程にモデルの宣言がある(tmp_path):
    """**空の宣言を1つでも作らない。** 成果物ゲートが FAIL する仕様。"""
    runs_dir = tmp_path / "runs"
    _run(tmp_path, runs_dir)

    run = _load_only_run(runs_dir)
    undeclared = [s["name"] for s in run["stages"] if not s.get("model")]
    assert undeclared == [], f"モデルが宣言されていない工程: {undeclared}"


def test_LLMを使わない工程はlocalと宣言する(tmp_path):
    """「使っていない」ことも宣言事項。宣言し忘れと区別できるように。"""
    runs_dir = tmp_path / "runs"
    _run(tmp_path, runs_dir)

    models = {s["name"]: s["model"] for s in _load_only_run(runs_dir)["stages"]}
    for name in ("ingest", "smart_cut", "audio_extract", "transcribe",
                 "subtitle_gen", "telop_render", "compose", "quality_gate",
                 "thumbnail"):
        assert models[name].startswith(LOCAL_PREFIX), (
            f"{name} が local: で宣言されていない: {models[name]}"
        )


def test_soul_feedbackは段から引く(tmp_path):
    """直書きしない。段が入れ替わったら記録も一緒に動くこと。"""
    from backend import model_policy

    runs_dir = tmp_path / "runs"
    _run(tmp_path, runs_dir)

    stage = next(s for s in _load_only_run(runs_dir)["stages"]
                 if s["name"] == "soul_feedback")
    decision = model_policy.resolve("director")
    assert stage["model"] == decision.model
    assert stage["tier"] == decision.tier
    assert stage["task"] == "director"


def test_使ったモデルが実行全体にも残る(tmp_path):
    """R1-C5。2.5 系への依存を見るために要る。"""
    runs_dir = tmp_path / "runs"
    _run(tmp_path, runs_dir)

    assert _load_only_run(runs_dir)["models_used"], "models_used が空"


# --- 失敗と再開（R1-C4） ------------------------------------------------------

def test_落ちた工程と原因と入力が残る(tmp_path):
    runs_dir = tmp_path / "runs"
    result = _run(tmp_path, runs_dir, fail_at="compose")

    assert result.success is False
    run = _load_only_run(runs_dir)
    assert run["status"] == "failed"

    failed = [s for s in run["stages"] if s["status"] == "failed"]
    assert [s["name"] for s in failed] == ["compose"]
    assert "わざと落とす" in failed[0]["error"]
    assert failed[0]["input"], "再開に要る入力が残っていない"


def test_落ちた工程より前は成功として残る(tmp_path):
    runs_dir = tmp_path / "runs"
    _run(tmp_path, runs_dir, fail_at="compose")

    run = _load_only_run(runs_dir)
    done = [s["name"] for s in run["stages"] if s["status"] == "success"]
    assert done == STAGE_ORDER[:STAGE_ORDER.index("compose")]


def test_落ちた後の工程は記録に現れない(tmp_path):
    """走っていない工程を「記録なし」で並べない。"""
    runs_dir = tmp_path / "runs"
    _run(tmp_path, runs_dir, fail_at="compose")

    names = [s["name"] for s in _load_only_run(runs_dir)["stages"]]
    assert "quality_gate" not in names
    assert "thumbnail" not in names


# --- 成果物（R1-C1） ----------------------------------------------------------

def test_完成したmp4が成果物に載る(tmp_path):
    runs_dir = tmp_path / "runs"
    result = _run(tmp_path, runs_dir)

    artifacts = _load_only_run(runs_dir)["artifacts"]
    assert result.output_path in artifacts


def test_落ちたら成果物は載らない(tmp_path):
    runs_dir = tmp_path / "runs"
    _run(tmp_path, runs_dir, fail_at="compose")

    assert _load_only_run(runs_dir)["artifacts"] == []


# --- 既定では書かない ---------------------------------------------------------

def test_runs_dirを渡さなければ何も書かない(tmp_path):
    """既存のパイプラインテストが `output/runs/` を汚さないこと。"""
    result = _run(tmp_path, None)

    assert result.success is True
    assert not (tmp_path / "runs").exists()


def test_記録の失敗でパイプラインを止めない(tmp_path, monkeypatch):
    """記録は付帯物。**書けなかったからといって動画を作るのを諦めない。**"""
    from backend.video_pipeline import pipeline_coordinator as mod

    def boom(*args, **kwargs):
        raise OSError("記録先が書けない")

    monkeypatch.setattr(mod, "RunRecorder", boom)
    result = _run(tmp_path, tmp_path / "runs")

    assert result.success is True


@pytest.mark.parametrize("fail_at", ["ingest", "transcribe", "thumbnail"])
def test_どの工程で落ちても記録は残る(tmp_path, fail_at):
    runs_dir = tmp_path / "runs"
    _run(tmp_path, runs_dir, fail_at=fail_at)

    run = _load_only_run(runs_dir)
    assert run["status"] == "failed"
    assert [s["name"] for s in run["stages"] if s["status"] == "failed"] == [
        fail_at]


# --- JSON にできない入力 -------------------------------------------------------
#
# 2026-08-19 の実走で踏んだ。`transcribe` の出力 `TranscriptResult` が
# 次の工程の `stage_input` に入り、`json.dump` が TypeError。記録の
# 書き出しが transcribe 以降すべて失敗し、**run.json は 4 工程・
# status=running のまま**残った。10/10 完走した実行の記録が、途中で
# 止まった実行に見えていた。


class _NotJsonable:
    def __repr__(self):
        return "<TranscriptResult segments=42>"


def test_JSONにできない入力があっても記録は完走する(tmp_path):
    runs_dir = tmp_path / "runs"

    def execute(stage_name, input_data):
        out = _fake_stage_output(stage_name, input_data)
        if stage_name == "transcribe":
            out["transcript"] = _NotJsonable()
        return out

    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir,
    )
    with patch.object(PipelineCoordinator, "_execute_stage",
                      side_effect=execute, autospec=False):
        result = coordinator.run_pipeline("input.mp4")

    assert result.success is True
    run = _load_only_run(runs_dir)
    assert run["status"] == "completed", "記録が途中で止まっている"
    assert [s["name"] for s in run["stages"]] == STAGE_ORDER


def test_JSONにできない値は型が分かる形で残る(tmp_path):
    """**黙って消さない。** 何が入っていたのか読めること。"""
    runs_dir = tmp_path / "runs"

    def execute(stage_name, input_data):
        out = _fake_stage_output(stage_name, input_data)
        if stage_name == "transcribe":
            out["transcript"] = _NotJsonable()
        return out

    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir,
    )
    with patch.object(PipelineCoordinator, "_execute_stage",
                      side_effect=execute, autospec=False):
        coordinator.run_pipeline("input.mp4")

    stage = next(s for s in _load_only_run(runs_dir)["stages"]
                 if s["name"] == "subtitle_gen")
    assert "_NotJsonable" in str(stage["input"]["transcript"])


def test_記録そのものがJSONにできない値を受けても壊れない(tmp_path):
    """`RunRecorder` 側の最後の一枚。1つの値で記録全体を失わない。"""
    from backend.revenue.run_record import RunRecorder

    rec = RunRecorder(runs_dir=tmp_path / "runs",
                      inputs={"bad": _NotJsonable()})
    with rec.stage("x", model="local:test"):
        pass
    rec.finish()

    run = json.loads(rec.path.read_text(encoding="utf-8"))
    assert run["status"] == "completed"
    assert "_NotJsonable" in str(run["inputs"]["bad"])
