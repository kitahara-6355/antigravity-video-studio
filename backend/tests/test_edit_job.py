"""backend/edit_job.py — 1本の自動編集を手順どおりに通す（スキル interview-edit の本体・2026-10-18）。

守りたい性質:

1. job ファイルが壊れていれば、何も始めずに止まる
2. 無料枠は米国太平洋時間の0時から数える。キャッシュ無しの書き出しに足りなければ、API を1回も呼ばずに止まる
3. 落ちた手順は記録して止まり、もう一度 `run` すると済んだ手順を飛ばして続きから進む
4. 書き出しは本線のコマンドをそのまま動かし、実行の記録（run.json）と AI の呼び出しを工程ライブに出す
5. 書き出しが書き換える実行時のファイルは、走らせる前に手つかずか確かめ、走った後に戻す
6. 残す資産（AI の出力・字幕データ・記録）は役目と sha256 つきで写す。作り直せる物（映像の切り替わり・音声）は写さない

API も Drive も呼ばない（書き出しは小さな偽のコマンドで代える）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import textwrap

import pytest

from backend import edit_job

UTC = dt.timezone.utc
TIERS = {"standard": {"model": "gemini-std", "rpd": 20}, "batch": {"model": "gemini-lite", "rpd": 500}}


def _job(tmp_path, **over):
    job = {"name": "raw4_test", "label": "テスト", "material": "joined.mp4",
           "raw": {"folder": None, "parts": ["a.mp4", "b.mp4"]},
           "versions": [{"key": "zero", "label": "ゼロからの版"},
                        {"key": "ledger", "label": "朱を足した版", "review": "reviews/x.json"}],
           "out": str(tmp_path / "out")}
    job.update(over)
    return job


def _write_job(tmp_path, job):
    path = tmp_path / "job.json"
    path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    return path


def _call(at, model):
    return {"at": at, "model": model, "caller": "gemini_client_factory", "jpy": 0.05,
            "spent_jpy": 10.0, "budget_id": "plan-T"}


def _budget(tmp_path, limit=1500, spent=500):
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"budgets": [{"id": "plan-T", "status": "active",
                                             "limit_jpy": limit, "spent_jpy": spent}]}), encoding="utf-8")
    return path


def _runner(tmp_path, job=None, now=None, **kw):
    job = job or _job(tmp_path)
    clock = now or (lambda: dt.datetime(2026, 10, 18, 12, 0, tzinfo=UTC))
    kw.setdefault("ledger", tmp_path / "ledger.jsonl")
    if "budget" not in kw:
        kw["budget"] = _budget(tmp_path)
    kw.setdefault("runs_dir", tmp_path / "runs")
    kw.setdefault("tiers", TIERS)
    kw.setdefault("free_bytes", lambda _: 50 * 1024 ** 3)
    return edit_job.Runner(job, work=tmp_path / "work", now=clock, **kw)


# --- 1. job ファイル ----------------------------------------------------------------


@pytest.mark.parametrize("change, why", [
    ({"raw": {"parts": []}}, "parts"),
    ({"raw": {"parts": ["a.mp4", "a.mp4"]}}, "parts"),
    ({"versions": [{"key": "zero"}, {"key": "zero"}]}, "versions"),
    ({"versions": []}, "versions"),
    ({"name": "../outside"}, "name"),
    ({"out": ""}, "out"),
])
def test_a_broken_job_file_is_refused_before_anything_runs(tmp_path, change, why):
    path = _write_job(tmp_path, _job(tmp_path, **change))

    with pytest.raises(edit_job.JobError) as exc:
        edit_job.load_job(path)

    assert why in str(exc.value)


def test_the_steps_follow_the_versions_in_order(tmp_path):
    job = _job(tmp_path, approved=str(tmp_path / "approved.subtitles.json"))

    keys = [s["key"] for s in edit_job.plan_steps(job)]

    assert keys == ["check", "fetch", "join",
                    "edit:zero", "review:zero", "compare:zero",
                    "edit:ledger", "review:ledger", "compare:ledger", "keep"]


def test_without_a_yardstick_nothing_is_compared(tmp_path):
    keys = [s["key"] for s in edit_job.plan_steps(_job(tmp_path))]

    assert not [k for k in keys if k.startswith("compare")]


# --- 2. 無料枠 -----------------------------------------------------------------------


def test_calls_are_counted_from_midnight_in_the_pacific_time_zone():
    rows = [_call("2026-10-18T06:59:00+00:00", "gemini-lite"),   # 太平洋時間の前の日（夏時間は 07:00 UTC が0時）
            _call("2026-10-18T07:01:00+00:00", "gemini-lite"),
            _call("2026-10-18T08:00:00+00:00", "gemini-std"),
            {"kind": "fallback", "at": "2026-10-18T08:00:00+00:00", "model": "gemini-lite"},
            {"kind": "run_summary", "at": "2026-10-18T09:00:00+00:00", "calls": 3}]

    used = edit_job.calls_today(rows, dt.datetime(2026, 10, 18, 12, 0, tzinfo=UTC))

    assert used == {"gemini-lite": 1, "gemini-std": 1}


def test_the_day_starts_an_hour_later_in_winter():
    now = dt.datetime(2026, 12, 1, 12, 0, tzinfo=UTC)

    assert edit_job.day_start(now) == dt.datetime(2026, 12, 1, 8, 0, tzinfo=UTC)
    assert edit_job.next_reset(now) == dt.datetime(2026, 12, 2, 8, 0, tzinfo=UTC)


def test_free_capacity_adds_up_what_is_left_in_each_tier():
    now = dt.datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    rows = ([_call("2026-10-18T08:00:00+00:00", "gemini-std")] * 20
            + [_call("2026-10-18T09:00:00+00:00", "gemini-lite")] * 300)

    left, detail = edit_job.free_capacity(rows, now, TIERS)

    assert left == 200
    assert [(d["tier"], d["used"], d["left"]) for d in detail] == [("standard", 20, 0), ("batch", 300, 200)]


def test_a_cacheless_export_stops_before_calling_when_the_free_tier_is_short(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("".join(json.dumps(_call("2026-10-18T09:00:00+00:00", "gemini-lite")) + "\n"
                              for _ in range(300)), encoding="utf-8")
    runner = _runner(tmp_path, ledger=ledger)

    with pytest.raises(edit_job.JobError) as exc:
        runner.check_quota(cacheless=True)

    assert "無料枠" in str(exc.value)
    assert "16:00" in str(exc.value)  # 枠が戻るのは日本時間 10-19 16:00


def test_an_export_with_caches_next_to_the_material_needs_only_a_few_calls(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("".join(json.dumps(_call("2026-10-18T09:00:00+00:00", "gemini-lite")) + "\n"
                              for _ in range(300)), encoding="utf-8")

    _runner(tmp_path, ledger=ledger).check_quota(cacheless=False)


def test_an_export_stops_when_the_budget_is_nearly_used_up(tmp_path):
    runner = _runner(tmp_path, budget=_budget(tmp_path, limit=1500, spent=1490))

    with pytest.raises(edit_job.JobError) as exc:
        runner.check_budget(cacheless=True)

    assert "予算" in str(exc.value)


# --- 3. 手順の記録と再開 -------------------------------------------------------------


def test_a_failed_step_is_recorded_and_the_next_run_starts_from_it(tmp_path):
    runner = _runner(tmp_path)
    done = []

    def ok(step):
        done.append(step["key"])
        return {"note": "ok"}

    def broken(step):
        raise RuntimeError("Drive に届かない")

    runner.handlers = {k: ok for k in runner.handlers}
    runner.handlers["fetch"] = broken

    assert runner.run() == 1
    status = json.loads((tmp_path / "out" / "live" / "status.json").read_text(encoding="utf-8"))
    fetch = next(s for s in status["steps"] if s["key"] == "fetch")
    assert fetch["state"] == "failed" and "Drive に届かない" in fetch["error"]
    assert status["state"] == "failed"

    again = _runner(tmp_path)
    again.handlers = {k: ok for k in again.handlers}
    done.clear()

    assert again.run() == 0
    assert done[:2] == ["check", "fetch"]  # 確かめは毎回やり直す。つなぐ手前の取得から続ける
    assert "join" in done
    status = json.loads((tmp_path / "out" / "live" / "status.json").read_text(encoding="utf-8"))
    assert status["state"] == "done"
    journal = (tmp_path / "out" / "live" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(line)["kind"] == "fail" for line in journal)


def test_redo_undoes_a_step_and_the_ones_after_it_and_keeps_the_earlier_files(tmp_path):
    # コードを直した後に同じ素材で書き出し直す。作業場（AI の出力）はそのまま、前の確認用ファイルは残す
    runner = _runner(tmp_path)
    done = []

    def ok(step):
        done.append(step["key"])
        return {}

    runner.handlers = {k: ok for k in runner.handlers}
    assert runner.run() == 0
    (tmp_path / "out" / "zero").mkdir(parents=True)
    (tmp_path / "out" / "zero" / "first3.mp4").write_bytes(b"old")

    undone = runner.redo("edit:zero", "字幕の欠落を直したので書き出し直す")

    assert undone[0] == "edit:zero" and undone[-1] == "keep" and "join" not in undone
    assert not (tmp_path / "out" / "zero").exists()
    kept = list((tmp_path / "out" / "previous").glob("*/zero/first3.mp4"))
    assert len(kept) == 1 and kept[0].read_bytes() == b"old"
    journal = [json.loads(line) for line in
               (tmp_path / "out" / "live" / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert journal[-1]["kind"] == "redo" and journal[-1]["text"] == "字幕の欠落を直したので書き出し直す"

    again = _runner(tmp_path)
    again.handlers = {k: ok for k in again.handlers}
    done.clear()
    assert again.run() == 0
    assert done == ["check"] + undone


def test_redo_refuses_a_step_the_job_does_not_have(tmp_path):
    with pytest.raises(edit_job.JobError, match="手順はありません"):
        _runner(tmp_path).redo("edit:nope", "x")


def test_a_note_goes_into_the_journal_and_the_live_status(tmp_path):
    runner = _runner(tmp_path)

    runner.note("3.6-flash は 503 が続くので flash-lite に任せる")

    status = json.loads((tmp_path / "out" / "live" / "status.json").read_text(encoding="utf-8"))
    assert status["notes"][-1]["text"] == "3.6-flash は 503 が続くので flash-lite に任せる"


# --- 4. 書き出し ---------------------------------------------------------------------


FAKE_COORDINATOR = textwrap.dedent("""
    import json, os, pathlib, sys, time
    video = sys.argv[1]
    runs = pathlib.Path(os.environ["AVS_RUNS_DIR"])
    ledger = pathlib.Path(os.environ["FAKE_LEDGER"])
    run_dir = runs / "20261018T120000000000-0000"
    run_dir.mkdir(parents=True)
    run = {"run_id": run_dir.name, "started_at": "2026-10-18T12:00:01+00:00", "status": "running",
           "inputs": {"video_path": video}, "stages": [
               {"name": "transcribe", "status": "running", "started_at": "2026-10-18T12:00:01+00:00",
                "model": "gemini-std", "tier": "standard"}]}
    (run_dir / "run.json").write_text(json.dumps(run))
    with open(ledger, "a") as f:
        f.write(json.dumps({"at": "2026-10-18T12:00:02+00:00", "model": "gemini-lite",
                            "caller": "gemini_client_factory", "jpy": 0.05}) + "\\n")
        f.write(json.dumps({"kind": "fallback", "at": "2026-10-18T12:00:02+00:00", "requested": "gemini-std",
                            "model": "gemini-lite", "reason": "503:サーバー混雑"}) + "\\n")
    print("  ✅ チャンク 1/2: 3 セグメント (gemini-lite)", flush=True)
    time.sleep(0.4)
    run["stages"][0].update(status="success", calls=1, finished_at="2026-10-18T12:00:03+00:00")
    run["status"] = "awaiting_approval"
    (run_dir / "run.json").write_text(json.dumps(run))
    pathlib.Path("backend/branding/proper_nouns.json").write_text("{\\"learned\\": 1}")
    print()
    print("  状態      : awaiting_approval")
    print("  所要      : 2.1 秒")
    print("  成果物    : (無し)")
    print("  プレビュー: /work/preview_x.mp4")
    print("  品質      : 91")
    sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
""")


def _repo(tmp_path):
    repo = tmp_path / "repo"
    for rel in edit_job.RUNTIME_FILES:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("{}", encoding="utf-8")
    git = ["git", "-C", str(repo)]
    subprocess.run(git[:1] + ["init", "-q", str(repo)], check=True)
    subprocess.run(git + ["add", "."], check=True)
    subprocess.run(git + ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], check=True)
    return repo


def _edit_runner(tmp_path, monkeypatch, exit_code=0):
    repo = _repo(tmp_path)
    script = tmp_path / "fake_coordinator.py"
    script.write_text(FAKE_COORDINATOR, encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    monkeypatch.setenv("FAKE_LEDGER", str(ledger))
    monkeypatch.setenv("FAKE_EXIT", str(exit_code))
    runner = _runner(tmp_path, repo=repo, ledger=ledger, coordinator=[sys.executable, str(script)],
                     poll_sec=0.05)
    runner.material.parent.mkdir(parents=True)
    runner.material.write_bytes(b"material")
    return runner, repo


def test_an_export_runs_the_mainline_command_and_records_the_run(tmp_path, monkeypatch):
    runner, _ = _edit_runner(tmp_path, monkeypatch)
    step = next(s for s in edit_job.plan_steps(runner.job) if s["key"] == "edit:zero")

    result = runner.step_edit(step)

    assert result["run_id"] == "20261018T120000000000-0000"
    assert result["status"] == "awaiting_approval"
    assert result["preview"] == "/work/preview_x.mp4"
    assert result["quality"] == 91
    assert [s["name"] for s in result["run"]["stages"]] == ["transcribe"]
    runner.write_status()
    status = json.loads((tmp_path / "out" / "live" / "status.json").read_text(encoding="utf-8"))
    assert [c["kind"] for c in status["calls"]] == ["call", "fallback"]
    assert status["calls"][1]["reason"] == "503:サーバー混雑"
    assert "チャンク 1/2" in (tmp_path / "work" / "logs" / "zero.log").read_text(encoding="utf-8")


def test_the_export_gets_the_review_ledger_only_for_its_version(tmp_path, monkeypatch):
    runner, _ = _edit_runner(tmp_path, monkeypatch)
    steps = {s["key"]: s for s in edit_job.plan_steps(runner.job)}

    assert "--review" not in runner.export_command(steps["edit:zero"])
    command = runner.export_command(steps["edit:ledger"])
    assert command[command.index("--review") + 1] == "reviews/x.json"
    assert command[command.index("--transcriber") + 1] == "gemini"


def test_files_the_export_rewrites_are_put_back_afterwards(tmp_path, monkeypatch):
    runner, repo = _edit_runner(tmp_path, monkeypatch)
    step = next(s for s in edit_job.plan_steps(runner.job) if s["key"] == "edit:zero")

    runner.step_edit(step)

    assert (repo / "backend/branding/proper_nouns.json").read_text(encoding="utf-8") == "{}"


def test_files_the_export_rewrites_are_put_back_even_when_it_fails(tmp_path, monkeypatch):
    runner, repo = _edit_runner(tmp_path, monkeypatch, exit_code=1)
    step = next(s for s in edit_job.plan_steps(runner.job) if s["key"] == "edit:zero")

    with pytest.raises(edit_job.JobError):
        runner.step_edit(step)

    assert (repo / "backend/branding/proper_nouns.json").read_text(encoding="utf-8") == "{}"


def test_an_export_does_not_start_over_changes_someone_left_in_those_files(tmp_path, monkeypatch):
    runner, repo = _edit_runner(tmp_path, monkeypatch)
    (repo / "backend/usage_tracker/usage_data.json").write_text('{"mine": true}', encoding="utf-8")
    step = next(s for s in edit_job.plan_steps(runner.job) if s["key"] == "edit:zero")

    with pytest.raises(edit_job.JobError) as exc:
        runner.step_edit(step)

    assert "usage_data.json" in str(exc.value)
    assert (repo / "backend/usage_tracker/usage_data.json").read_text(encoding="utf-8") == '{"mine": true}'
    assert not (tmp_path / "runs").exists()  # 書き出しは始めていない


def test_the_mainline_command_gets_its_arguments_as_given(monkeypatch):
    seen = []
    monkeypatch.setattr(edit_job, "run_mainline", lambda args: seen.append(args) or 0)

    edit_job.main(["mainline", "/w/raw4.mp4", "--transcriber", "gemini", "--review", "r.json"])

    assert seen == [["/w/raw4.mp4", "--transcriber", "gemini", "--review", "r.json"]]


def test_the_result_lines_of_the_mainline_are_read():
    text = ("📏 目標尺を素材から決めました: 43 分\n\n"
            "  状態      : awaiting_approval\n  所要      : 1365.5 秒\n  成果物    : (無し)\n"
            "  プレビュー: /x/preview_1.mp4\n  品質      : 91\n  ⚠ ディスク残量注意: 2.7GB\n")

    result = edit_job.parse_result(text)

    assert result == {"status": "awaiting_approval", "duration_sec": 1365.5, "final": None,
                      "preview": "/x/preview_1.mp4", "quality": 91, "warnings": ["ディスク残量注意: 2.7GB"]}


def test_the_latest_progress_line_is_picked_from_the_log():
    text = ("🎤 Gemini 文字起こし: 104 チャンク\n  ✅ チャンク 36/104: 9 セグメント (gemini-lite)\n"
            "  ✅ チャンク 37/104: 12 セグメント (gemini-lite)\nINFO:httpx:HTTP Request: POST ...\n")

    assert edit_job.progress_line(text) == "✅ チャンク 37/104: 12 セグメント (gemini-lite)"


def test_the_chunk_journals_next_to_the_material_show_how_far_transcription_got(tmp_path):
    material = tmp_path / "joined.mp4"
    material.write_bytes(b"video")
    (tmp_path / "_gemini_c30q_94f6cf35.chunks.journal").write_text('{"offset": 0}\n{"offset": 30}\n',
                                                                    encoding="utf-8")

    assert edit_job.chunk_journals(material) == [{"name": "_gemini_c30q_94f6cf35.chunks.journal", "chunks": 2}]


# --- 6. 残す資産 ---------------------------------------------------------------------


def test_the_assets_are_kept_with_their_role_and_sha256(tmp_path):
    material = tmp_path / "material" / "joined.mp4"
    material.parent.mkdir()
    material.write_bytes(b"video")
    for name in ("_gemini_c30q_94f6cf35.jsonl", "_gemini_c30q_94f6cf35.meta.json",
                 "_proofread_94f6cf35.json", "_align_rz_94f6cf35.json",
                 "_shots_94f6cf35.json", "_whisper_audio_x.wav"):
        (material.parent / name).write_text(name, encoding="utf-8")
    captions = tmp_path / "preview.subtitles.json"
    captions.write_text('{"segments": []}', encoding="utf-8")
    run = tmp_path / "run.json"
    run.write_text("{}", encoding="utf-8")

    files = edit_job.collect_assets(material, tmp_path / "assets",
                                    captions={"zero": captions}, records={"zero.run.json": run})

    kept = {f["path"]: f for f in files}
    assert set(kept) == {"ai/_gemini_c30q_94f6cf35.jsonl", "ai/_gemini_c30q_94f6cf35.meta.json",
                         "ai/_proofread_94f6cf35.json", "ai/_align_rz_94f6cf35.json",
                         "captions/zero.subtitles.json", "records/zero.run.json"}
    assert kept["captions/zero.subtitles.json"]["role"] == "caption_data"
    assert kept["ai/_proofread_94f6cf35.json"]["role"] == "ai_output"
    assert kept["records/zero.run.json"]["role"] == "record"
    digest = hashlib.sha256(b"_proofread_94f6cf35.json").hexdigest()
    assert kept["ai/_proofread_94f6cf35.json"]["sha256"] == digest
    assert (tmp_path / "assets" / "ai" / "_proofread_94f6cf35.json").read_text(encoding="utf-8") == \
        "_proofread_94f6cf35.json"


def test_the_live_view_carries_the_quality_notes_of_the_gate():
    """工程ライブの版のカードに、品質の講評（⛔・⚠）を出す。点数だけでは直す所が分からない。"""
    quality = {"score": 74, "rank": "C", "feedback": ["⛔ 字幕にしなかった発話 2行"], "category_scores": {}}
    run = {"stages": [{"name": "proofread", "status": "success"},
                      {"name": "quality_gate", "status": "failed", "quality": quality}]}

    stages = edit_job.run_view(run)["stages"]

    assert "quality" not in stages[0]
    assert stages[1]["quality"] == quality
