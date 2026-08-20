"""実行記録（R1）。**「動いた」「どこで落ちた」を後から読める形で残す。**

成果物ゲートは `output/runs/<run_id>/run.json` を読んで判定するが、
**その run.json を書くものが無かった。** ここがその書き手。

守りたい性質は5つ:

1. 書いた記録が**そのまま成果物ゲートを通る**（別々の形を作らない）
2. 工程ごとに**どのモデルで動いたか**が残る（見える化・ユーザー要件）
3. モデルは宣言だけでなく**実際に呼ばれたもの**が台帳から拾われる
4. 失敗した工程から**再開できる**（工程名・原因・入力が残る）
5. 途中で落ちても記録が残る（**工程ごとに書き出す**。最後にまとめて書かない）
"""
from __future__ import annotations

import json

import pytest

from backend.revenue import artifact_gate
from backend.revenue.run_record import RunRecorder, failed_stage, load_run


def _recorder(tmp_path, **kw) -> RunRecorder:
    return RunRecorder(runs_dir=tmp_path / "runs",
                       ledger_path=tmp_path / "ledger.jsonl", **kw)


def _ledger_row(path, model, caller="test"):
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"model": model, "caller": caller,
                             "jpy": 0.1, "metered": True}) + "\n")


# --- 1. ゲートと同じ形 --------------------------------------------------------


def test_a_recorded_run_passes_the_artifact_gate(tmp_path):
    """**書き手と読み手が同じ形を指していること。**

    ここがずれると、記録は残っているのにゲートが FAIL する。
    """
    rec = _recorder(tmp_path)
    with rec.stage("transcribe", model="local:whisper"):
        pass
    with rec.stage("script", model="gemini-3.6-flash"):
        # **実際に呼ばれた証拠を置く。** 宣言だけで台帳に実測が無い工程は
        # 「スタブが答えたかもしれない」ので、ゲートが model_unverified を
        # 出す（2026-08-20 に本物の 503 で踏んだ）。
        _ledger_row(rec.ledger_path, "gemini-3.6-flash")
    rec.finish()

    assert artifact_gate.check_runs(
        artifact_gate.load_runs(tmp_path / "runs")) == []


def test_the_record_has_every_key_the_gate_requires(tmp_path):
    rec = _recorder(tmp_path)
    with rec.stage("script", model="gemini-3.6-flash"):
        pass
    rec.finish()

    run = load_run(rec.path)

    assert set(artifact_gate.REQUIRED_RUN_KEYS) <= set(run)


# --- 2. 工程ごとのモデル ------------------------------------------------------


def test_a_stage_records_the_model_resolved_from_policy(tmp_path):
    """**段から引く。** モデル名を直書きすると入替のたびに全工程を触ることになる。"""
    from backend import model_policy

    rec = _recorder(tmp_path)
    with rec.stage("テロップ提案", task="telop_suggestion"):
        pass
    rec.finish()

    stage = load_run(rec.path)["stages"][0]
    expected = model_policy.resolve("telop_suggestion")

    assert stage["model"] == expected.model
    assert stage["tier"] == expected.tier
    assert stage["model_source"] == expected.source
    assert stage["task"] == "telop_suggestion"


def test_an_unmapped_task_is_visible_as_such(tmp_path):
    """**綴り違いを黙って既定モデルにしない。**

    `resolve()` は未知の工程を既定に落とす。落ちたこと自体は
    `model_source` に出るので、記録を読めば気づける。
    """
    rec = _recorder(tmp_path)
    with rec.stage("s", task="存在しない工程"):
        pass
    rec.finish()

    stage = load_run(rec.path)["stages"][0]

    assert stage["model_source"] == "tier_default"
    assert stage["task"] == "存在しない工程"


def test_a_stage_without_a_declared_model_fails_the_gate(tmp_path):
    """**宣言し忘れを緑にしない。** 上げる先が決められなくなる。"""
    rec = _recorder(tmp_path)
    with rec.stage("mystery"):
        pass
    rec.finish()

    kinds = {f.kind for f in
             artifact_gate.check_runs(artifact_gate.load_runs(tmp_path / "runs"))}

    assert "model_not_recorded" in kinds


def test_models_used_is_the_union_over_stages(tmp_path):
    rec = _recorder(tmp_path)
    with rec.stage("a", model="gemini-3.6-flash"):
        pass
    with rec.stage("b", model="gemini-3.1-pro"):
        pass
    with rec.stage("c", model="gemini-3.6-flash"):
        pass
    rec.finish()

    assert sorted(load_run(rec.path)["models_used"]) == [
        "gemini-3.1-pro", "gemini-3.6-flash"]


# --- 3. 宣言ではなく実測 ------------------------------------------------------


def test_the_models_actually_called_are_read_from_the_ledger(tmp_path):
    """**宣言は当てにしない。** 台帳に残った呼び出しが実測。"""
    rec = _recorder(tmp_path)
    with rec.stage("script", model="gemini-3.6-flash"):
        _ledger_row(tmp_path / "ledger.jsonl", "gemini-3.6-flash")
        _ledger_row(tmp_path / "ledger.jsonl", "gemini-3.1-pro")
    rec.finish()

    stage = load_run(rec.path)["stages"][0]

    assert sorted(stage["models_observed"]) == [
        "gemini-3.1-pro", "gemini-3.6-flash"]
    assert stage["calls"] == 2


def test_only_the_calls_made_during_the_stage_are_attributed_to_it(tmp_path):
    """**工程の外の呼び出しを混ぜない。** 開始時点の台帳末尾から読む。"""
    ledger = tmp_path / "ledger.jsonl"
    _ledger_row(ledger, "gemini-2.5-flash")          # 前の工程の呼び出し
    rec = _recorder(tmp_path)
    with rec.stage("script", model="gemini-3.6-flash"):
        _ledger_row(ledger, "gemini-3.6-flash")
    rec.finish()

    stage = load_run(rec.path)["stages"][0]

    assert stage["models_observed"] == ["gemini-3.6-flash"]


def test_a_divergence_between_plan_and_reality_is_flagged(tmp_path):
    """宣言と実測が食い違ったら**その事実を残す**（黙って上書きしない）。"""
    rec = _recorder(tmp_path)
    with rec.stage("script", model="gemini-3.6-flash"):
        _ledger_row(tmp_path / "ledger.jsonl", "gemini-2.5-flash")
    rec.finish()

    stage = load_run(rec.path)["stages"][0]

    assert stage["model_mismatch"] is True
    assert stage["model"] == "gemini-3.6-flash"       # 宣言も残る
    assert stage["models_observed"] == ["gemini-2.5-flash"]


def test_a_stage_with_no_calls_is_not_flagged_as_a_mismatch(tmp_path):
    """ローカル処理（ffmpeg・Whisper）は台帳に出ない。食い違いではない。"""
    rec = _recorder(tmp_path)
    with rec.stage("render", model="local:ffmpeg"):
        pass
    rec.finish()

    assert load_run(rec.path)["stages"][0]["model_mismatch"] is False


# --- 4. 失敗した工程から再開できる --------------------------------------------


def test_a_failing_stage_is_recorded_with_enough_to_resume(tmp_path):
    """**再開に要るのは3つ**: どの工程か・なぜ落ちたか・何を渡したか。"""
    rec = _recorder(tmp_path)
    with pytest.raises(ValueError):
        with rec.stage("smartcut", model="local:ffmpeg",
                       stage_input={"src": "a.mp4"}):
            raise ValueError("入力が壊れています")
    rec.finish()

    stage = load_run(rec.path)["stages"][0]

    assert stage["status"] == "failed"
    assert stage["name"] == "smartcut"
    assert "入力が壊れています" in stage["error"]
    assert stage["input"] == {"src": "a.mp4"}
    assert artifact_gate.check_runs(
        artifact_gate.load_runs(tmp_path / "runs")) == []


def test_the_exception_is_not_swallowed(tmp_path):
    """**記録は例外を握り潰さない。** 落ちた実行を成功に見せない。"""
    rec = _recorder(tmp_path)

    with pytest.raises(RuntimeError, match="boom"):
        with rec.stage("render", model="local:ffmpeg"):
            raise RuntimeError("boom")


def test_a_failed_stage_without_an_input_is_not_resumable(tmp_path):
    """入力を渡さなければ**再開できない**とゲートが言う（fail-closed）。"""
    rec = _recorder(tmp_path)
    with pytest.raises(ValueError):
        with rec.stage("smartcut", model="local:ffmpeg"):
            raise ValueError("x")
    rec.finish()

    kinds = {f.kind for f in
             artifact_gate.check_runs(artifact_gate.load_runs(tmp_path / "runs"))}

    assert "not_resumable" in kinds


def test_failed_stage_points_at_where_to_restart(tmp_path):
    rec = _recorder(tmp_path)
    with rec.stage("transcribe", model="local:whisper"):
        pass
    with pytest.raises(ValueError):
        with rec.stage("smartcut", model="local:ffmpeg", stage_input={"n": 1}):
            raise ValueError("x")
    rec.finish()

    stage = failed_stage(load_run(rec.path))

    assert stage["name"] == "smartcut"
    assert stage["input"] == {"n": 1}


def test_a_completed_run_has_no_failed_stage(tmp_path):
    rec = _recorder(tmp_path)
    with rec.stage("a", model="local:ffmpeg"):
        pass
    rec.finish()

    assert failed_stage(load_run(rec.path)) is None


# --- 5. 途中で落ちても残る ----------------------------------------------------


def test_the_record_exists_before_finish_is_called(tmp_path):
    """**プロセスが強制終了しても記録が残ること。**

    最後にまとめて書くと、いちばん知りたい「落ちた実行」の記録が消える。
    """
    rec = _recorder(tmp_path)
    with rec.stage("a", model="local:ffmpeg"):
        pass

    # finish() を呼んでいない
    assert rec.path.is_file()
    assert load_run(rec.path)["stages"][0]["name"] == "a"


def test_the_record_survives_a_stage_that_raises(tmp_path):
    rec = _recorder(tmp_path)
    with pytest.raises(ValueError):
        with rec.stage("a", model="local:ffmpeg", stage_input={}):
            raise ValueError("x")

    assert load_run(rec.path)["stages"][0]["status"] == "failed"


def test_the_run_is_marked_failed_when_a_stage_failed(tmp_path):
    rec = _recorder(tmp_path)
    with pytest.raises(ValueError):
        with rec.stage("a", model="local:ffmpeg", stage_input={}):
            raise ValueError("x")
    rec.finish()

    assert load_run(rec.path)["status"] == "failed"


# --- 成果物 -------------------------------------------------------------------


def test_artifacts_are_recorded_and_found_by_the_gate(tmp_path):
    rec = _recorder(tmp_path)
    with rec.stage("render", model="local:ffmpeg"):
        rec.artifact("output/final/demo.mp4")
    rec.finish()

    assert load_run(rec.path)["artifacts"] == ["output/final/demo.mp4"]


def test_an_artifact_is_recorded_once(tmp_path):
    rec = _recorder(tmp_path)
    rec.artifact("a.mp4")
    rec.artifact("a.mp4")
    rec.finish()

    assert load_run(rec.path)["artifacts"] == ["a.mp4"]


# --- 実行そのもの -------------------------------------------------------------


def test_run_ids_are_unique_and_sort_by_time(tmp_path):
    ids = [_recorder(tmp_path).run_id for _ in range(5)]

    assert len(set(ids)) == 5
    assert ids == sorted(ids)


def test_the_duration_is_measured(tmp_path):
    rec = _recorder(tmp_path)
    with rec.stage("a", model="local:ffmpeg"):
        pass
    rec.finish()

    run = load_run(rec.path)

    assert run["duration_sec"] >= 0
    assert run["stages"][0]["duration_sec"] >= 0
    assert run["finished_at"]


def test_the_record_is_valid_json_after_every_stage(tmp_path):
    """途中の書き出しが**壊れた JSON にならない**こと（原子的に置き換える）。"""
    rec = _recorder(tmp_path)
    for i in range(5):
        with rec.stage(f"s{i}", model="local:ffmpeg"):
            json.loads(rec.path.read_text(encoding="utf-8"))

    assert len(load_run(rec.path)["stages"]) == 5


def test_inputs_are_recorded_for_the_whole_run(tmp_path):
    rec = _recorder(tmp_path, inputs={"source": "vault/raw/a.mp4"})
    rec.finish()

    assert load_run(rec.path)["inputs"] == {"source": "vault/raw/a.mp4"}


def test_the_cost_of_the_run_is_summed_from_the_ledger(tmp_path):
    """**1本あたりの原価**（R1-C2）を実行単位で出す。"""
    rec = _recorder(tmp_path)
    with rec.stage("a", model="gemini-3.6-flash"):
        _ledger_row(tmp_path / "ledger.jsonl", "gemini-3.6-flash")
        _ledger_row(tmp_path / "ledger.jsonl", "gemini-3.6-flash")
    rec.finish()

    run = load_run(rec.path)

    assert run["cost_jpy"] == pytest.approx(0.2)
    assert run["calls"] == 2
