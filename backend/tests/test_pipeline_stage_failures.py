"""工程が「何もしていない」まま success を返さないこと。

2026-08-20 に音声トラックの無い素材で実走したら、**10/10 完走・
success=True・所要 8.9 秒**で終わり、成果物は入力とバイト一致だった。
`subtitles.srt` は作られてすらいない。

原因は個別のバグではなく**型**だった。`_execute_stage` は各サービスの
戻り値から必要なフィールドだけ取り出し、**`success` を一度も読んで
いなかった。**

    result = generator.generate_srt(transcript, srt_path)
    return {"subtitle_path": result.output_path, ...}   # ← success を捨てる

そのため:

- `SubtitleGenerator` は「セグメントが空」で success=False を返していたのに
  工程は成功扱い。存在しない SRT のパスが下流に流れた
- `compose` は 2026-08-19 の `e78f686` で「字幕が焼けなければ success=False」に
  直したのに、**呼び出し側が戻り値を捨てているのでその修正は効いていなかった**

個別に潰すのではなく、**`success` を持つ戻り値は必ず見る**という形で閉じる。
`success` を持たない戻り値（従来どおり）と、モックされた戻り値は通す。
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from backend.video_pipeline.pipeline_coordinator import PipelineCoordinator


@dataclass
class _Result:
    """`success` を持つ戻り値。"""
    success: bool = False
    error: str = ""
    # 各工程が読むフィールドをまとめて生やしておく（工程ごとに使う物が違う）
    normalized_path: str = "n.mp4"
    format_info: dict = None
    duration_seconds: float = 1.0
    audio_path: str = "a.wav"
    segments: tuple = ()
    output_path: str = "out.srt"
    entry_count: int = 0
    image_path: str = "t.jpg"
    overall_score: float = 0.0
    passed: bool = False


# (工程名, patch 先, 呼ばれるメソッド名, 追加の入力)
_SERVICES = [
    ("ingest",
     "backend.video_pipeline.ingest_service.IngestService", "ingest", {}),
    ("audio_extract",
     "backend.video_pipeline.audio_extractor.AudioExtractor", "extract", {}),
    ("transcribe",
     "backend.video_pipeline.transcription_service.TranscriptionService",
     "transcribe", {}),
    ("subtitle_gen",
     "backend.video_pipeline.subtitle_generator.SubtitleGenerator",
     "generate_srt", {"transcript": _Result(success=True)}),
    ("compose",
     "backend.video_pipeline.video_composer.VideoComposer", "compose", {}),
    ("thumbnail",
     "backend.video_pipeline.thumbnail_generator.ThumbnailGenerator",
     "generate", {}),
]


def _execute(stage_name, target, method, extra, result, tmp_path):
    coordinator = PipelineCoordinator(work_dir=str(tmp_path))
    data = {"input_path": "in.mp4", "job_dir": str(tmp_path),
            "job_id": "job", **extra}
    with patch(target) as cls:
        getattr(cls.return_value, method).return_value = result
        return coordinator._execute_stage(stage_name, data)


@pytest.mark.parametrize("stage_name,target,method,extra", _SERVICES,
                         ids=[s[0] for s in _SERVICES])
def test_サービスが失敗を返したら工程も失敗する(stage_name, target, method,
                                                extra, tmp_path):
    """**戻り値を捨てない。** これを捨てていたので「何もせず成功」が通った。"""
    with pytest.raises(Exception) as exc:
        _execute(stage_name, target, method, extra,
                 _Result(success=False, error="わざと失敗"), tmp_path)

    assert stage_name in str(exc.value)


@pytest.mark.parametrize("stage_name,target,method,extra", _SERVICES,
                         ids=[s[0] for s in _SERVICES])
def test_サービスが成功を返したら工程は通る(stage_name, target, method,
                                            extra, tmp_path):
    out = _execute(stage_name, target, method, extra,
                   _Result(success=True), tmp_path)

    assert isinstance(out, dict)


def test_successを持たない戻り値は通す(tmp_path):
    """`success` を持たないサービス（quality_gate 等）の従来動作を変えない。"""

    class _NoSuccess:
        overall_score = 88.0
        passed = True

    coordinator = PipelineCoordinator(work_dir=str(tmp_path))
    with patch("backend.video_pipeline.quality_gate.QualityGate") as cls:
        cls.return_value.evaluate.return_value = _NoSuccess()
        out = coordinator._execute_stage(
            "quality_gate", {"output_path": "x.mp4", "job_dir": str(tmp_path)})

    assert out["quality_score"] == 88.0


def test_モックされた戻り値は失敗にしない(tmp_path):
    """`MagicMock().success` は Mock であって False ではない。

    既存のパイプラインテストは戻り値を MagicMock で作る。**`is False` で
    見る**ので、これを失敗に倒さない。
    """
    coordinator = PipelineCoordinator(work_dir=str(tmp_path))
    with patch("backend.video_pipeline.ingest_service.IngestService") as cls:
        cls.return_value.ingest.return_value = MagicMock()
        out = coordinator._execute_stage(
            "ingest", {"input_path": "in.mp4", "job_dir": str(tmp_path)})

    assert isinstance(out, dict)


def test_失敗した工程は実行記録に残る(tmp_path):
    """落ちた工程が run.json で特定できること（R1-C4 との接続）。"""
    import json

    runs_dir = tmp_path / "runs"
    coordinator = PipelineCoordinator(
        work_dir=str(tmp_path / "work"), runs_dir=runs_dir)

    with patch("backend.video_pipeline.ingest_service.IngestService") as cls:
        cls.return_value.ingest.return_value = _Result(
            success=False, error="取り込めない")
        result = coordinator.run_pipeline("in.mp4", stages=["ingest"])

    assert result.success is False
    run = json.loads(next(runs_dir.glob("*/run.json")).read_text(
        encoding="utf-8"))
    assert [s["name"] for s in run["stages"] if s["status"] == "failed"] == [
        "ingest"]


# --- compose が中身の無いファイルを成果物にしない -----------------------------

def test_中身の無いダミーを成果物として返さない(tmp_path):
    """元動画が無いとき 21 バイトのテキストを書いて success=True にしていた。

    ffprobe が読めないので成果物ゲートは fail-closed で捕まえるが、
    **パイプラインは 10/10 完走・品質ゲート PASS で緑になる。**
    """
    from backend.video_pipeline.video_composer import VideoComposer

    composer = VideoComposer(output_dir=str(tmp_path))
    out = tmp_path / "out.mp4"

    result = composer.compose(
        video_path=str(tmp_path / "存在しない.mp4"),
        output_path=str(out),
    )

    assert result.success is False, "中身の無いファイルを成功にしている"
    assert not out.exists() or out.stat().st_size > 1024


# --- 記録が実態と食い違わないこと ---------------------------------------------
#
# 2026-08-20 の再開実走で本物の 503 を踏んだ。soul_feedback は
# gemini-3.7-flash に2回再試行してから諦め、**スタブにフォールバックして
# success を返した。** run.json には `model: gemini-3.7-flash` と書かれた
# まま、`models_observed` は空。
#
# 読み手は「提案は gemini-3.7-flash が出した」と読む。実際は誰も出して
# いない。R1-C6 の見える化が嘘になる型で、`6520f77` で直した
# 「--show の表示と実際の呼び出しが食い違う」のと同じ。


def test_宣言したモデルが一度も動いていなければ印が付く(tmp_path):
    from backend.revenue.run_record import RunRecorder

    rec = RunRecorder(runs_dir=tmp_path / "runs",
                      ledger_path=tmp_path / "ledger.jsonl")
    with rec.stage("soul_feedback", model="gemini-3.7-flash"):
        pass  # API は1回も成功していない
    run = rec.finish()

    stage = run["stages"][0]
    assert stage["model_unverified"] is True, (
        "呼ばれていないモデルを、動いたかのように記録している"
    )


def test_ローカル工程には印を付けない(tmp_path):
    """`local:` は台帳に出ないのが正常。**これを異常にしない。**"""
    from backend.revenue.run_record import RunRecorder

    rec = RunRecorder(runs_dir=tmp_path / "runs",
                      ledger_path=tmp_path / "ledger.jsonl")
    with rec.stage("compose", model="local:ffmpeg"):
        pass
    run = rec.finish()

    assert run["stages"][0]["model_unverified"] is False


def test_実際に呼ばれていれば印は付かない(tmp_path):
    import json as _json

    from backend.revenue.run_record import RunRecorder

    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    rec = RunRecorder(runs_dir=tmp_path / "runs", ledger_path=ledger)
    with rec.stage("soul_feedback", model="gemini-3.7-flash"):
        with open(ledger, "a", encoding="utf-8") as fh:
            fh.write(_json.dumps({"model": "gemini-3.7-flash", "jpy": 0.6})
                     + "\n")
    run = rec.finish()

    assert run["stages"][0]["model_unverified"] is False


def test_成果物ゲートが未検証のモデルを指摘する(tmp_path):
    from backend.revenue.artifact_gate import check_runs

    findings = check_runs([{
        "run_id": "r", "started_at": "t", "models_used": ["gemini-3.7-flash"],
        "stages": [{"name": "soul_feedback", "status": "success",
                    "model": "gemini-3.7-flash", "models_observed": [],
                    "model_unverified": True}],
    }])

    assert [f.kind for f in findings] == ["model_unverified"]


def test_失敗が0件のときに再開できると言い切らない(capsys):
    """**不在を成功にしない。** 「確かめられていない」と「大丈夫」は違う。"""
    from backend.revenue import artifact_gate

    run = {"run_id": "r", "started_at": "t", "models_used": ["local:ffmpeg"],
           "stages": [{"name": "compose", "status": "success",
                       "model": "local:ffmpeg", "models_observed": []}]}
    with patch.object(artifact_gate, "load_runs", return_value=[run]):
        code = artifact_gate.main(["--resume-check"])

    out = capsys.readouterr().out
    assert code == 0
    assert "失敗した工程はありません" in out
    assert "再開できます" not in out, "確かめていないことを確かめたと言っている"


def test_失敗があって再開できるなら件数を出す(capsys):
    from backend.revenue import artifact_gate

    run = {"run_id": "r", "started_at": "t", "models_used": ["local:ffmpeg"],
           "stages": [{"name": "compose", "status": "failed",
                       "model": "local:ffmpeg", "models_observed": [],
                       "error": "落ちた", "input": {"a": 1}}]}
    with patch.object(artifact_gate, "load_runs", return_value=[run]):
        code = artifact_gate.main(["--resume-check"])

    out = capsys.readouterr().out
    assert code == 0
    assert "1 件" in out


def test_成果物ゲートは要約行を呼び出しに数えない(tmp_path, monkeypatch):
    """要約に metered が無いのを「トークンを読めなかった」と読ませない。

    実際に本番台帳へ 40 行の要約が混ざったとき、成果物ゲートが
    「トークンを読めなかった呼び出し 40 / 47 件」と誤検知した。
    """
    import json as _json

    from backend import cost_guard
    from backend.revenue import artifact_gate

    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("".join(_json.dumps(r) + "\n" for r in [
        {"model": "m", "jpy": 0.1, "metered": True, "known_price": True},
        {"kind": "run_summary", "run_id": "r", "status": "completed",
         "duration_sec": 1.0, "calls": 1, "cost_jpy": 0.1},
    ]), encoding="utf-8")
    monkeypatch.setattr(cost_guard, "LEDGER_PATH", ledger)

    findings = artifact_gate.check_cost([])

    assert [f.kind for f in findings] == []
