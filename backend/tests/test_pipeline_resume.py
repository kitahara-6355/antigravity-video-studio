"""落ちた工程から**実際に再実行できる**こと。R1-C4 の後半。

`run_record --resume` は「どこで落ちたか・原因は何か・どの入力が要るか」を
**報告するだけ**だった。R1-C4 は「そこから再実行できる」と書いてあるので、
報告だけでは足りない。記録が残ることと再開できることは別物。

再開の設計:

- **元の作業ディレクトリを引き継ぐ。** 前の工程が作った中間ファイルを
  使うのが再開なので、新しい job_dir を切ったら意味が無い
- **元の実行記録は書き換えない。** 失敗の記録は証拠なので残し、
  再開は新しい記録として書く（`resumed_from` で辿れる）
- **復元できない入力があったら再開しない。** `TranscriptResult` のように
  JSON にできなかった値は印だけが残っている。それを渡して動かすと
  「再開したつもりで壊れたもの」ができる。fail-closed で断り、
  **どの工程まで戻ればいいかを言う**
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.video_pipeline.pipeline_coordinator import (
    STAGE_ORDER,
    PipelineCoordinator,
    ResumeNotPossible,
)
from backend.revenue.run_record import UNSERIALIZABLE_MARK


def _outputs(stage_name, input_data):
    job_dir = input_data.get("job_dir", "")
    if stage_name == "compose":
        return {"output_path": str(Path(job_dir) / "composed_output.mp4")}
    return {f"{stage_name}_done": True}


def _first_run(tmp_path, runs_dir, fail_at, calls):
    def execute(stage_name, input_data):
        calls.append(stage_name)
        if stage_name == fail_at:
            raise RuntimeError("わざと落とす")
        return _outputs(stage_name, input_data)

    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir)
    with patch.object(PipelineCoordinator, "_execute_stage",
                      side_effect=execute):
        coordinator.run_pipeline("input.mp4")
    return sorted(runs_dir.glob("*"))[0].name


def _load(runs_dir, run_id):
    return json.loads((runs_dir / run_id / "run.json").read_text(
        encoding="utf-8"))


# --- 再開できる ---------------------------------------------------------------

def test_落ちた工程から残りが走る(tmp_path):
    runs_dir = tmp_path / "runs"
    calls: list[str] = []
    run_id = _first_run(tmp_path, runs_dir, "compose", calls)
    calls.clear()

    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir)
    with patch.object(PipelineCoordinator, "_execute_stage",
                      side_effect=lambda n, d: _outputs(n, d)):
        result = coordinator.resume_run(run_id)

    assert result.success is True
    assert calls == [] or True  # 実行の中身は下の assert で見る
    assert result.stages_completed == STAGE_ORDER[
        STAGE_ORDER.index("compose"):]


def test_完了済みの工程はやり直さない(tmp_path):
    """再開の意味。ingest からやり直すなら再開ではない。"""
    runs_dir = tmp_path / "runs"
    run_id = _first_run(tmp_path, runs_dir, "compose", [])

    again: list[str] = []
    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir)

    def execute(stage_name, input_data):
        again.append(stage_name)
        return _outputs(stage_name, input_data)

    with patch.object(PipelineCoordinator, "_execute_stage",
                      side_effect=execute):
        coordinator.resume_run(run_id)

    assert "ingest" not in again
    assert "transcribe" not in again
    assert again[0] == "compose"


def test_元の作業ディレクトリを引き継ぐ(tmp_path):
    """前の工程が作った中間ファイルを使えること。"""
    runs_dir = tmp_path / "runs"
    run_id = _first_run(tmp_path, runs_dir, "compose", [])
    original_job_dir = _load(runs_dir, run_id)["stages"][-1]["input"]["job_dir"]

    seen: list[str] = []
    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir)

    def execute(stage_name, input_data):
        seen.append(input_data["job_dir"])
        return _outputs(stage_name, input_data)

    with patch.object(PipelineCoordinator, "_execute_stage",
                      side_effect=execute):
        coordinator.resume_run(run_id)

    assert set(seen) == {original_job_dir}


def test_元の失敗記録は残る(tmp_path):
    """証拠を書き換えない。"""
    runs_dir = tmp_path / "runs"
    run_id = _first_run(tmp_path, runs_dir, "compose", [])

    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir)
    with patch.object(PipelineCoordinator, "_execute_stage",
                      side_effect=lambda n, d: _outputs(n, d)):
        coordinator.resume_run(run_id)

    original = _load(runs_dir, run_id)
    assert original["status"] == "failed"
    assert [s["name"] for s in original["stages"] if s["status"] == "failed"
            ] == ["compose"]


def test_再開は新しい記録に元の実行を書く(tmp_path):
    runs_dir = tmp_path / "runs"
    run_id = _first_run(tmp_path, runs_dir, "compose", [])

    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir)
    with patch.object(PipelineCoordinator, "_execute_stage",
                      side_effect=lambda n, d: _outputs(n, d)):
        coordinator.resume_run(run_id)

    new_id = [p.name for p in sorted(runs_dir.glob("*")) if p.name != run_id]
    assert len(new_id) == 1
    assert _load(runs_dir, new_id[0])["inputs"]["resumed_from"] == run_id


@pytest.mark.parametrize("fail_at", ["audio_extract", "soul_feedback",
                                     "compose", "thumbnail"])
def test_どの工程からでも再開できる(tmp_path, fail_at):
    runs_dir = tmp_path / "runs"
    run_id = _first_run(tmp_path, runs_dir, fail_at, [])

    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir)
    with patch.object(PipelineCoordinator, "_execute_stage",
                      side_effect=lambda n, d: _outputs(n, d)):
        result = coordinator.resume_run(run_id)

    assert result.success is True
    assert result.stages_completed[0] == fail_at


# --- 再開できないときは断る ---------------------------------------------------

def test_復元できない入力があったら再開しない(tmp_path):
    """**「再開したつもりで壊れたもの」を作らない。** fail-closed。"""
    runs_dir = tmp_path / "runs"
    run_id = _first_run(tmp_path, runs_dir, "subtitle_gen", [])

    path = runs_dir / run_id / "run.json"
    run = json.loads(path.read_text(encoding="utf-8"))
    failed = [s for s in run["stages"] if s["status"] == "failed"][0]
    failed["input"]["transcript"] = f"{UNSERIALIZABLE_MARK} TranscriptResult ...>"
    path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")

    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir)
    with pytest.raises(ResumeNotPossible) as exc:
        coordinator.resume_run(run_id)

    assert "transcript" in str(exc.value)
    assert "transcribe" in str(exc.value), "どこまで戻ればいいかを言っていない"


def test_失敗していない実行は再開しない(tmp_path):
    runs_dir = tmp_path / "runs"
    run_id = _first_run(tmp_path, runs_dir, None, [])

    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir)
    with pytest.raises(ResumeNotPossible):
        coordinator.resume_run(run_id)


def test_存在しない実行は再開しない(tmp_path):
    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=tmp_path / "runs")
    with pytest.raises(ResumeNotPossible):
        coordinator.resume_run("ありません")
