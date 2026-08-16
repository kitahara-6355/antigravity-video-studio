"""成果物ゲート（R1）。**「動いた」を成果物で判定する。**

守りたい性質:

1. **確かめられないときは FAIL**（ffprobe が無い環境を緑にしない）
2. **0件を緑にしない**（実行記録が無い＝動いていない）
3. 失敗した工程は、**再開できる情報が無ければ違反**
4. 実費が未計測・単価不明なら、それが**見える**
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.revenue.artifact_gate import (
    ARTIFACT_SEMANTICS,
    check_cost,
    check_models,
    check_runs,
    check_video,
    load_runs,
    run_gate,
)


def _kinds(findings) -> set[str]:
    return {f.kind for f in findings}


def _run(tmp_path: Path, **over) -> Path:
    run = {"run_id": "r1", "started_at": "2026-08-15T00:00:00Z",
           "stages": [{"name": "script", "status": "ok",
                       "model": "gemini-3-flash-preview"}],
           "models_used": ["gemini-2.5-flash"],
           "artifacts": []}
    run.update(over)
    d = tmp_path / "r1"
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.json").write_text(json.dumps(run), encoding="utf-8")
    return tmp_path


# --- 1. 確かめられないなら FAIL ----------------------------------------------


def test_a_missing_prober_is_a_failure(tmp_path, monkeypatch):
    """**ffprobe が無い環境を緑にしない。** 判定できないことは合格ではない。"""
    monkeypatch.setattr("shutil.which", lambda name: None)

    _, findings = check_video(tmp_path / "x.mp4")

    assert "no_prober" in _kinds(findings)


def test_a_missing_file_is_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffprobe")

    _, findings = check_video(tmp_path / "does_not_exist.mp4")

    assert "missing" in _kinds(findings)


# --- 2. 0件を緑にしない -------------------------------------------------------


def test_no_run_record_is_a_violation(tmp_path):
    """記録が無ければ、動いたかどうかも分からない。"""
    assert "no_run" in _kinds(check_runs([]))


def test_a_broken_run_record_is_a_violation(tmp_path):
    d = tmp_path / "r1"
    d.mkdir()
    (d / "run.json").write_text("{壊れている", encoding="utf-8")

    assert "broken_run" in _kinds(check_runs(load_runs(tmp_path)))


def test_an_incomplete_run_record_is_a_violation(tmp_path):
    """必要な項目が欠けた記録を通さない。"""
    _run(tmp_path, models_used=None)
    (tmp_path / "r1" / "run.json").write_text(
        json.dumps({"run_id": "r1", "stages": []}), encoding="utf-8")

    assert "incomplete_run" in _kinds(check_runs(load_runs(tmp_path)))


# --- 3. 再開できるか ----------------------------------------------------------


def test_a_failed_stage_without_resume_info_is_a_violation(tmp_path):
    """**失敗を記録するだけでは足りない。** そこから再開できる情報が要る。"""
    _run(tmp_path, stages=[{"name": "tts", "status": "failed",
                            "model": "gemini-3-flash-preview"}])

    findings = check_runs(load_runs(tmp_path))

    assert "not_resumable" in _kinds(findings)


def test_a_failed_stage_with_resume_info_passes(tmp_path):
    _run(tmp_path, stages=[{"name": "tts", "status": "failed",
                            "model": "gemini-3-flash-preview",
                            "error": "429 rate limited",
                            "input": "script.json"}])

    assert check_runs(load_runs(tmp_path)) == []


def test_a_successful_run_passes(tmp_path):
    assert check_runs(load_runs(_run(tmp_path))) == []


# --- 4. 実費 ------------------------------------------------------------------


def test_a_missing_cost_ledger_is_a_violation(tmp_path, monkeypatch):
    from backend import cost_guard
    monkeypatch.setattr(cost_guard, "LEDGER_PATH", tmp_path / "none.jsonl")

    assert "no_cost_ledger" in _kinds(check_cost([]))


def test_unmetered_calls_are_surfaced(tmp_path, monkeypatch):
    """**「無料だった」を疑う。** 読めなかった呼び出しは不明として出す。"""
    from backend import cost_guard
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(
        {"metered": False, "known_price": True}) + "\n", encoding="utf-8")
    monkeypatch.setattr(cost_guard, "LEDGER_PATH", ledger)

    assert "unmetered_calls" in _kinds(check_cost([]))


def test_unknown_price_models_are_surfaced(tmp_path, monkeypatch):
    from backend import cost_guard
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(
        {"metered": True, "known_price": False}) + "\n", encoding="utf-8")
    monkeypatch.setattr(cost_guard, "LEDGER_PATH", ledger)

    assert "unknown_price_models" in _kinds(check_cost([]))


# --- 5. モデルの記録（2026-10-16 の終了に備える） -----------------------------


def test_models_must_be_recorded():
    assert "no_models_recorded" in _kinds(check_models([{"run_id": "r1"}]))


def test_recorded_models_pass():
    assert check_models([{"models_used": ["gemini-2.5-flash"]}]) == []


# --- 6. 動画が無ければ R1 は未達 ----------------------------------------------


def test_the_gate_fails_without_a_video(tmp_path, monkeypatch):
    """**R1 の終了条件は『動画が1本ある』こと。** 他では代替できない。"""
    from backend import cost_guard
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(
        {"metered": True, "known_price": True}) + "\n", encoding="utf-8")
    monkeypatch.setattr(cost_guard, "LEDGER_PATH", ledger)

    report = run_gate(video=None, runs_dir=_run(tmp_path))

    assert "no_video" in _kinds(report.findings)
    assert not report.ok


# --- 7. 意味表 ----------------------------------------------------------------


def test_the_semantics_do_not_claim_quality(tmp_path):
    """**尺と音声の有無しか見ていない。** 良い動画だとは言わない。"""
    not_checked = "".join(ARTIFACT_SEMANTICS["確かめないこと"])

    assert "良い動画かどうか" in not_checked
    assert "収益化に適格かどうか" in not_checked
    assert "再現性" in not_checked


def test_the_semantics_admit_fail_closed():
    assert "fail-closed" in ARTIFACT_SEMANTICS["判定の性質"]


# --- 8. 見える化（ユーザー要件・2026-08-15） ----------------------------------


def test_a_stage_without_a_model_is_a_violation(tmp_path):
    """**どの結果がどのモデルで出たか**が残っていなければ FAIL。

    残っていないと、不満があっても**どこを上げればいいか決められない**。
    """
    _run(tmp_path, stages=[{"name": "telop", "status": "ok"}])

    assert "model_not_recorded" in _kinds(check_runs(load_runs(tmp_path)))


def test_a_stage_with_a_model_passes(tmp_path):
    _run(tmp_path, stages=[{"name": "telop", "status": "ok",
                            "model": "gemini-3-flash-preview"}])

    assert check_runs(load_runs(tmp_path)) == []


def test_the_semantics_promise_per_stage_visibility():
    checked = "".join(ARTIFACT_SEMANTICS["確かめること"])

    assert "工程ごとに、どのモデルで動いたかが残ること" in checked
