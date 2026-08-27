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
    check_run_status,
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


# --- 判定は最新の1本。過去は書庫 ------------------------------------------------


def _write_run(runs_dir: Path, run_id: str, *, unverified: bool) -> None:
    stage = {"name": "quality_gate", "status": "success",
             "model": "gemini-3.7-flash"}
    if unverified:
        stage["model_unverified"] = True
    d = runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.json").write_text(json.dumps({
        "run_id": run_id, "started_at": "2026-08-26T00:00:00Z",
        "stages": [stage], "models_used": ["gemini-3.7-flash"],
        "artifacts": [],
    }), encoding="utf-8")


def test_過去の欠陥ではゲートを落とさない(tmp_path):
    """**直せない過去で永久に落ちない。**

    「あの実行は宣言だけで API を呼んでいなかった」はその日の事実で、
    実装を直しても記録からは消えない。全件を判定対象にすると、
    一度でも駄目な実行をした時点でゲートが二度と緑にならない。
    """
    _write_run(tmp_path, "20260826T100000000000-0000", unverified=True)
    _write_run(tmp_path, "20260826T110000000000-0000", unverified=False)

    findings = check_runs(load_runs(tmp_path))

    assert not findings, f"最新が綺麗なら通ること: {findings}"


def test_過去の欠陥は黙って消さない(tmp_path):
    """判定には使わないが、**見えなくもしない。**"""
    from backend.revenue.artifact_gate import history_findings

    _write_run(tmp_path, "20260826T100000000000-0000", unverified=True)
    _write_run(tmp_path, "20260826T110000000000-0000", unverified=False)

    history = history_findings(load_runs(tmp_path))

    assert _kinds(history) == {"model_unverified"}


def test_最新が駄目ならゲートは落ちる(tmp_path):
    """**過去を免責にしたぶん、最新には厳しくする。**"""
    _write_run(tmp_path, "20260826T100000000000-0000", unverified=False)
    _write_run(tmp_path, "20260826T110000000000-0000", unverified=True)

    findings = check_runs(load_runs(tmp_path))

    assert _kinds(findings) == {"model_unverified"}


def test_resume_checkは検査した範囲だけを数える(tmp_path, capsys, monkeypatch):
    """**検査していないものを「再開できます」に含めない。**

    判定を最新の1本に絞ったのに、件数は全件ぶん出していた。
    「実行記録 6 件 / 失敗した工程 12 件。いずれも再開できます」は、
    実際には最新1本しか見ていないので嘘になる
    （2026-08-26・gate-verifier の指摘）。
    """
    from backend.revenue import artifact_gate

    for i, unverified in enumerate([True, False]):
        rid = f"2026082{i}T000000000000-0000"
        d = tmp_path / rid
        d.mkdir(parents=True)
        (d / "run.json").write_text(json.dumps({
            "run_id": rid, "started_at": "2026-08-26T00:00:00Z",
            "stages": [{"name": "render", "status": "failed",
                        "model": "local:ffmpeg", "error": "落ちた",
                        "input": {"video_path": "x.mp4"}}],
            "models_used": ["local:ffmpeg"], "artifacts": [],
        }), encoding="utf-8")

    monkeypatch.setattr(artifact_gate, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(artifact_gate, "load_runs",
                        lambda runs_dir=tmp_path: artifact_gate.load_runs.__wrapped__(tmp_path)
                        if hasattr(artifact_gate.load_runs, "__wrapped__")
                        else [json.loads((p).read_text(encoding="utf-8"))
                              for p in sorted(tmp_path.glob("*/run.json"))])

    assert artifact_gate.main(["--resume-check"]) == 0
    out = capsys.readouterr().out

    assert "最新の実行記録" in out, out
    assert "過去 1 件は検査していません" in out, out
    assert "6 件" not in out


# --- 赤い実走を落とせること（R1.5-C1c・2026-08-27）-----------------------------
#
# **「ゲートが PASS する」を条件にすると、ゲートを弱くするのが最短の達成手段に
# なる。** 実際そうなっていた — `--gate` は run の `status` を一度も見ておらず、
# きちんと書式の整った全滅の記録に対して exit 0 を返した。動画も全 run から
# 集めていたので、1本前の実走が残した mp4 が永久に緑を作っていた。
#
# 条件は「PASS すること」ではなく「**赤を落とせること**」。


def _gate_run(runs_dir: Path, run_id: str, *, status: str,
              artifacts: list | None = None) -> None:
    """**書式は完全で、状態だけが違う記録。** 書式で落ちては検査にならない。"""
    d = runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.json").write_text(json.dumps({
        "run_id": run_id, "started_at": "2026-08-27T00:00:00Z",
        "status": status,
        "stages": [{"name": "render", "status": "success",
                    "model": "local:ffmpeg"}],
        "models_used": ["local:ffmpeg"],
        "artifacts": artifacts or [],
    }), encoding="utf-8")


def test_最新の実走が失敗ならゲートは落ちる(tmp_path):
    """**赤い実走を緑にしない。** 記録の書式が完全でも、落ちたものは落ちた。"""
    _gate_run(tmp_path, "20260827T100000000000-0000", status="failed")

    assert "run_failed" in _kinds(check_run_status(load_runs(tmp_path)))


def test_終わっていない実走も緑にしない(tmp_path):
    """プロセスが死ぬと記録は `running` のまま残る。**未完は成功ではない。**"""
    _gate_run(tmp_path, "20260827T100000000000-0000", status="running")

    assert "run_failed" in _kinds(check_run_status(load_runs(tmp_path)))


def test_状態が記録されていなければ判定できない(tmp_path):
    """**「確かめられなかった」を「問題なし」にしない**（fail-closed）。"""
    d = tmp_path / "20260827T100000000000-0000"
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({
        "run_id": "20260827T100000000000-0000",
        "started_at": "2026-08-27T00:00:00Z",
        "stages": [{"name": "render", "status": "success",
                    "model": "local:ffmpeg"}],
        "models_used": ["local:ffmpeg"], "artifacts": [],
    }), encoding="utf-8")

    assert "run_status_missing" in _kinds(check_run_status(load_runs(tmp_path)))


def test_degradedは落とさない(tmp_path):
    """**動画は出来ている。** 完走ではないが、赤ではない（2026-08-27 ユーザー決定）。

    ここを落とすと、`quality_gate` が直るまでゲートが二度と緑にならない。
    見えなくするわけではない — `_format` が最新の実走の状態を必ず出す。
    """
    _gate_run(tmp_path, "20260827T100000000000-0000", status="degraded")

    assert check_run_status(load_runs(tmp_path)) == []
    assert check_runs(load_runs(tmp_path)) == []


def test_最新の実走の状態が出力に出る(tmp_path, monkeypatch):
    from backend import cost_guard
    from backend.revenue import artifact_gate as ag
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(
        {"metered": True, "known_price": True}) + "\n", encoding="utf-8")
    monkeypatch.setattr(cost_guard, "LEDGER_PATH", ledger)
    runs = tmp_path / "runs"
    _gate_run(runs, "20260827T100000000000-0000", status="degraded",
              artifacts=["out.mp4"])
    monkeypatch.setattr(ag, "check_video", lambda p: (None, []))

    out = ag._format(ag.run_gate(video=None, runs_dir=runs))

    assert "degraded" in out


def test_過去の動画で緑にしない(tmp_path, monkeypatch):
    """**動画も最新の1本で見る。** 1本前の mp4 が永久に緑を作っていた。"""
    from backend import cost_guard
    from backend.revenue import artifact_gate as ag
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(
        {"metered": True, "known_price": True}) + "\n", encoding="utf-8")
    monkeypatch.setattr(cost_guard, "LEDGER_PATH", ledger)
    runs = tmp_path / "runs"
    _gate_run(runs, "20260827T100000000000-0000", status="completed",
              artifacts=["old.mp4"])
    _gate_run(runs, "20260827T110000000000-0000", status="completed",
              artifacts=[])
    # 動画そのものの検査は別軸。**どの run の成果物を見るか**だけを問う
    monkeypatch.setattr(ag, "check_video", lambda p: (None, []))

    report = ag.run_gate(video=None, runs_dir=runs)

    assert "no_video" in _kinds(report.findings)
    assert not report.ok


def test_過去のモデル記録で最新を免責しない(tmp_path):
    """**`produced` と同じ穴が `check_models` にもあった。**

    全 run から集めていたので、1本前の実走が何かを記録していれば
    最新が何も記録していなくても通った。判定は最新の1本（R1.5-C1c）。
    """
    過去 = {"run_id": "old", "models_used": ["gemini-3.6-flash"]}
    最新 = {"run_id": "new", "models_used": []}

    assert "no_models_recorded" in _kinds(check_models([過去, 最新]))


# --- 実装不足項目の台帳（R1.5・2026-08-27 ユーザー決定）------------------------
#
# **実装が足りていない機能を1箇所に集める。** 分かっている7件のうち3件は正典の
# 条件文に散らばって書かれ、残り4件はどこにも書かれていなかった（実走ログと
# 品質ゲートの出力にしか現れない）。**一覧が無ければ思い出せない。**
#
# 技術負債の台帳（1,463件）とは別物。あれは `file_path:line_number` を持つ
# 既存コードの負債で、**存在しない機能は行番号を持てない**。


def test_台帳の全項目に理由と判定条件がある():
    """**「あとで書く」を許さない。** 理由の無い項目は思い出せない。"""
    from backend.feature_gaps import check_entries, load_gaps

    assert check_entries(load_gaps()) == []


def test_理由が無ければ不備として出る():
    from backend.feature_gaps import check_entries

    不備 = check_entries([{"id": "x", "title": "何か", "kind": "gap",
                           "handled_in": "将来",
                           "done_when": {"kind": "run_record_clean"}}])

    assert any("why" in m for m in 不備), 不備


def test_gapには行先が要る():
    """`intentional` には要らないが、`gap` は**どこで直すか**が要る。"""
    from backend.feature_gaps import check_entries

    不備 = check_entries([{"id": "x", "title": "何か", "kind": "gap",
                           "why": "理由", "done_when": {"kind": "run_record_clean"}}])

    assert any("handled_in" in m for m in 不備), 不備


def _記録(**over) -> dict:
    run = {"run_id": "r", "status": "degraded",
           "health": {"skipped_features": [], "failed_stages": []}}
    run["health"].update(over)
    return run


def test_記録に出た未知の項目を見つける():
    """**新しい実装漏れが黙って増えない。**"""
    from backend.feature_gaps import unknown_from_record

    出た = unknown_from_record(_記録(skipped_features=["字幕の焼き込み"]), [])

    assert 出た == ["字幕の焼き込み"]


def test_本線の工程名は実装漏れではない():
    """`quality_gate` が落ちたのは**工程の失敗**であって実装不足ではない。"""
    from backend.feature_gaps import unknown_from_record

    assert unknown_from_record(
        _記録(failed_stages=["quality_gate"], skipped_features=["quality_gate"]), []) == []


def test_台帳に載っていれば実装漏れではない():
    from backend.feature_gaps import unknown_from_record

    gaps = [{"id": "bgm", "surfaces_as": "BGMミキシング", "kind": "gap"}]

    assert unknown_from_record(_記録(skipped_features=["BGMミキシング(ファイルなし)"]), gaps) == []


def test_意図して止めているものも実装漏れではない():
    """**実行記録には gap と intentional が同じ顔で出る。** 区別しないと誤検知する。"""
    from backend.feature_gaps import unknown_from_record

    gaps = [{"id": "dream", "surfaces_as": "dream_learning", "kind": "intentional"}]

    assert unknown_from_record(_記録(skipped_features=["dream_learning"]), gaps) == []


def test_記録から消えたら実装済みとみなす():
    """**片付け忘れが残らない。** 直したのに台帳に残っていたら FAIL する。"""
    from backend.feature_gaps import is_done

    gap = {"id": "bgm", "surfaces_as": "BGMミキシング",
           "done_when": {"kind": "run_record_clean"}}

    assert is_done(gap, _記録(skipped_features=[])) is True
    assert is_done(gap, _記録(skipped_features=["BGMミキシング(ファイルなし)"])) is False


def test_成果物が出たら実装済みとみなす():
    from backend.feature_gaps import is_done

    gap = {"id": "thumb",
           "done_when": {"kind": "artifact_present", "suffixes": [".png", ".jpg"]}}

    assert is_done(gap, {"artifacts": ["out.mp4"], "health": {}}) is False
    assert is_done(gap, {"artifacts": ["out.mp4", "t.png"], "health": {}}) is True


def test_印が残っている間は未実装(tmp_path):
    """**印が消えても実装済みの証拠にはならない**（弱い証拠）。

    `placeholder_video_id` が「書いてあるが動かない」の実例。だから実行記録で
    判定できる項目にはこの種類を使わない。
    """
    from backend.feature_gaps import is_done

    f = tmp_path / "x.py"
    f.write_text("video_id = 'placeholder_video_id'", encoding="utf-8")
    gap = {"id": "up", "done_when": {"kind": "marker_gone",
                                     "path": str(f), "marker": "placeholder_video_id"}}

    assert is_done(gap, None) is False
    f.write_text("video_id = resp['id']", encoding="utf-8")
    assert is_done(gap, None) is True


def test_記録が無ければ確かめていないと言う():
    """**「確かめられなかった」を「問題なし」にしない。**"""
    from backend.feature_gaps import is_done

    gap = {"id": "bgm", "surfaces_as": "BGM", "done_when": {"kind": "run_record_clean"}}

    assert is_done(gap, None) is None


def _台帳(**over) -> list[dict]:
    g = {"id": "bgm", "kind": "gap", "title": "BGM", "why": "理由",
         "handled_in": "将来", "surfaces_as": "BGM",
         "done_when": {"kind": "run_record_clean"}}
    g.update(over)
    return [g]


def test_静的点検は確かめなかった検査を列挙する():
    """**黙って飛ばさない。**

    `model_policy --audit` がダミーキーで exit 0 を返す問題と同じ形なので、
    ここで同じ間違いを繰り返さない。CI は実走できない（実キーも実行記録も
    無い）ので、評価しなかった検査は必ず名前を出す。
    """
    from backend.feature_gaps import audit

    違反, 未確認 = audit(None, _台帳(), static_only=True)

    assert 違反 == []
    assert any("bgm" in m for m in 未確認), 未確認


def test_点検が新しい実装漏れで落ちる():
    from backend.feature_gaps import audit

    違反, _ = audit(_記録(skipped_features=["字幕の焼き込み"]), _台帳())

    assert any("字幕の焼き込み" in m for m in 違反), 違反


def test_点検が片付け忘れで落ちる():
    from backend.feature_gaps import audit

    違反, _ = audit(_記録(skipped_features=[]), _台帳())

    assert any("bgm" in m and "実装" in m for m in 違反), 違反


def test_showは落ちない():
    from backend import feature_gaps

    assert feature_gaps.main(["--show"]) == 0


def _品質ctx(tmp_path):
    """品質ゲートに渡す最小のコンテキスト。"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agents.pipeline_types import PipelineContext

    preview = tmp_path / "preview.mp4"
    preview.write_bytes(b"0" * 2048)
    ctx = PipelineContext(video_path=str(tmp_path / "src.mp4"), session_id="t")
    ctx.preview_path = str(preview)
    ctx.segments = [{"start": 0.0, "end": 3.0, "text": "あ", "score": 0.8}]
    ctx.selected_segments = list(ctx.segments)
    return ctx


def test_台帳に載っている機能は減点しない(tmp_path):
    """**構成上どうやっても届かない減点を止める。**

    本線にサムネイル工程は無い。無い工程を減点し続けると品質ゲートは
    **原理的に閾値へ到達できない**（実測: 物理 -20 / プラグイン -15 /
    完走チェック -5）。台帳に載っている間は減点せず、「やっていない」として
    `skipped_features` に出す。**実装したら台帳から消え、その瞬間から
    ゲートが本気で見はじめる。**
    """
    from agents.workers.quality_gate_worker import QualityGateWorker

    ctx = _品質ctx(tmp_path)
    ctx.declared_gaps = {"thumbnail"}

    結果 = QualityGateWorker()._thumbnail_physical_check(ctx)

    assert 結果["failures"] == [], 結果
    assert any("サムネイル" in s for s in ctx.skipped_features), ctx.skipped_features


def test_台帳に無ければ従来どおり減点する(tmp_path):
    from agents.workers.quality_gate_worker import QualityGateWorker

    ctx = _品質ctx(tmp_path)
    ctx.declared_gaps = set()

    assert QualityGateWorker()._thumbnail_physical_check(ctx)["failures"]


def test_宣言した能力のプラグインは回さない(tmp_path):
    from quality_gate_plugins import run_all_plugins

    ctx = _品質ctx(tmp_path)
    ctx.declared_gaps = {"thumbnail"}

    結果 = run_all_plugins(ctx, None)

    assert "thumbnail_quality_check" not in 結果["plugin_results"], 結果["plugin_results"].keys()
    assert not any("サムネイル" in f for f in 結果["feedback"]), 結果["feedback"]


def test_床打ちした素点が見える(tmp_path):
    """**0点は「どれくらい悪いか」を何も言わない。**

    実測では減点合計が -134（素点 -34）でも表示は 0 点だった。改善しても
    数字が動かないので、改善ループが効いているかを判断できない
    （実際、品質改善ループ3周がまったく動かなかった）。

    `ctx.quality_score` の 0〜100 の範囲は変えない（消費側が多い）。
    素点は detail と記録に残す。
    """
    import asyncio
    from agents.workers.quality_gate_worker import QualityGateWorker

    ctx = _品質ctx(tmp_path)
    ctx.declared_gaps = set()
    ctx.target_minutes = 20      # 30秒未満の素材に対して QV-01 が -50 を打つ

    r = asyncio.run(QualityGateWorker().execute(ctx))

    assert ctx.quality_score >= 0
    assert "素点" in r.detail, r.detail
    assert (ctx.quality_gate_report or {}).get("raw_score") is not None
