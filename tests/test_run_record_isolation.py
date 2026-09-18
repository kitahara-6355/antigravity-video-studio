"""`tests/` のテストが本番の `output/runs/` に実行記録を書かないこと。

2026-08-28〜09-18 に、`tests/test_pipeline_coordinator.py` の4件が走るたびに
本番の `output/runs/` へ記録を書き、**68件積もった**（実走の記録は2件）。
成果物ゲート（`python -m backend.revenue.artifact_gate --gate`）は最新の1本で
判定するので、テストが書いた記録で赤くなっていた。
隔離（`AVS_RUNS_DIR`）は `backend/tests/conftest.py` にしか無かった。
"""
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.resolve())
backend_dir = str(Path(__file__).parent.parent.resolve() / "backend")
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# tests/test_pipeline_coordinator.py と同じ名前で引く（別名で引くと別のモジュールになる）
import agents.pipeline_coordinator as pc  # noqa: E402
from agents.pipeline_types import PipelineContext  # noqa: E402

本番の置き場 = (Path(project_root) / "output" / "runs").resolve()


def test_コーディネータの実行記録は本番の_output_runs_に置かれない(monkeypatch, tmp_path):
    # 本物の RunRecorder は作った時点でディレクトリを掘る。赤のときに本番を汚さないよう代役で受ける
    渡された: dict = {}

    class 記録器の代役:
        def __init__(self, **kwargs):
            渡された.update(kwargs)
            self.path = "（代役）"

    monkeypatch.setattr(pc, "RunRecorder", 記録器の代役)
    pc.PipelineCoordinator()._open_recorder(
        PipelineContext(video_path=str(tmp_path / "dummy.mp4")))

    assert "runs_dir" in 渡された, (
        "置き場を指定せずに記録器を作りました。既定は本番の output/runs/ です"
        "（tests/conftest.py の隔離が効いていません）")
    置き場 = Path(渡された["runs_dir"]).resolve()
    assert not 置き場.is_relative_to(本番の置き場), 置き場
