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
from unittest.mock import AsyncMock, patch

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
    """**ハーネスと後処理は止めて走らせる。**

    `_init_harness` はセッションとトレースを `backend/data/` へ書く
    （本番ファイル汚染ラチェットが増加を検出する）。ここで見たいのは
    実行記録と失敗の伝播であって、ハーネスの配線ではない。
    既存の `test_workers/test_pipeline_coordinator.py` も同じ形で止めている。
    """
    ctx = PipelineContext(video_path=str(tmp_path / "入力.mp4"),
                          session_id="test-session")
    with patch.object(coordinator, "_init_harness", return_value=None),             patch.object(coordinator, "_run_retention_analysis",
                         new=AsyncMock(return_value=None)):
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
    # 品質ゲートは規則ベース。**AI だと偽らない**（R1.5-C3 で本当に効かせる）
    assert by_name["quality_gate"]["model"] == "local:rule-based"


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


def test_記録が開けなくても失敗は握り潰さない(tmp_path, monkeypatch):
    """**記録が壊れたら偽の success に戻る**、という穴が空いていた。

    `_open_recorder` は記録を開けなくても実行を続ける（記録の失敗で
    実行を落とさないため）。だが `_execute_worker` はそのとき
    `worker.execute()` をそのまま返すだけで、失敗を数えていなかった。
    結果、**最終レンダリングが落ちても `completed`** に戻ってしまう
    （2026-08-26・gate-verifier の指摘）。
    """
    def 開けない(*a, **kw):
        raise OSError("記録を開けません")

    monkeypatch.setattr(
        "agents.pipeline_coordinator.RunRecorder", 開けない)

    result = _run(_coordinator(tmp_path, 落ちる={"RenderWorker"}), tmp_path)

    assert result["status"] == "error", (
        "記録が開けないときに偽の success へ戻っています: "
        f"status={result['status']}")
    assert not (tmp_path / "runs").exists() or not list(
        (tmp_path / "runs").glob("*/run.json"))


# --- 動かなかった工程を成功に数えない（R1.5-C1b・2026-08-27）-------------------


def test_pre_hookが例外でも工程を成功に数えない(tmp_path):
    """**載っていないものは数えられない。**

    `_fire_pre_hook` は try の外にあり、そこで例外が出ると
    `asyncio.gather(return_exceptions=True)` がログ1行に変えて捨てていた。
    工程は `_outcomes` に載らず、`_settle_outcomes` は載っているものしか
    見ないので、**プレビュー・メタデータ・品質ゲートが1つも動いていない
    のに `completed`** になった（gate-verifier の指摘 N-2）。
    """
    c = _coordinator(tmp_path)
    # **品質ゲートは外しておく。** あれが落ちると改善ループが同じ工程を
    # 回し直し、**最後の試行が通る**ので「一度も動いていない」の検査に
    # ならない（リトライで通ったものを失敗に数えないのは C1b の別の柱）。
    爆ぜる工程 = {"PreviewWorker", "YouTubeOptWorker"}
    元のpre_hook = c._fire_pre_hook

    async def _爆ぜる(harness, worker, ctx):
        if type(worker).__name__ in 爆ぜる工程:
            raise RuntimeError("governance boom")
        return await 元のpre_hook(harness, worker, ctx)

    c._fire_pre_hook = _爆ぜる

    result = _run(c, tmp_path)

    assert result["status"] != "completed", result["status"]
    落ちた = set(result["health"]["skipped_features"])
    assert {"preview", "youtube_opt"} <= 落ちた, 落ちた
    # **記録からも追えること**
    assert set(_run_json(tmp_path)["health"]["skipped_features"]) >= {
        "preview", "youtube_opt"}


def test_落ちた工程が実行記録にも残る(tmp_path):
    """**記録だけを見て「何が落ちたか」が分かること。**

    `status: degraded` は残っていたが、**何が落ちたのかは残っていなかった**
    （`health` は API の戻り値にしかなく、`run.json` には無かった）。
    記録は再開材料であって、状態の一言ではない。
    """
    c = _coordinator(tmp_path, 落ちる={"YouTubeOptWorker"})

    result = _run(c, tmp_path)

    assert result["status"] == "degraded", result["status"]
    rec = _run_json(tmp_path)
    assert rec["status"] == "degraded"
    assert "youtube_opt" in rec["health"]["skipped_features"], rec.get("health")


# --- 致命的失敗でも記録から追えること（R1.5-C1b・2周目の指摘）-----------------


def _拒否する(*工程):
    async def _hook(harness, worker, ctx):
        if type(worker).__name__ in 工程:
            return True, "governance が禁止しました"
        return False, None
    return _hook


def test_致命工程が断られても記録から追える(tmp_path):
    """**落ちた工程が記録から消えていた。**

    `_close_recorder(ctx, "failed")` は `_settle_outcomes` より**前**に
    呼ばれるので `ctx.skipped_features` は空。しかも致命工程は
    `_execute_worker` に入る前に return するので `stages` にも残らない。
    結果、記録は `status: failed` なのに
    **`all_features_active: true`・失敗した工程ゼロ**になり、
    `run_record --resume` が「失敗した工程はありません」と exit 0 を返した
    （gate-verifier の指摘1）。
    """
    from backend.revenue.run_record import failed_stage

    c = _coordinator(tmp_path)
    c._fire_pre_hook = _拒否する("SmartCutWorker")

    result = _run(c, tmp_path)

    assert result["status"] == "error", result["status"]
    rec = _run_json(tmp_path)
    assert rec["status"] == "failed"
    assert "smart_cut" in [s.get("name") for s in rec["stages"]], rec["stages"]
    assert "smart_cut" in rec["health"]["failed_stages"], rec["health"]
    assert rec["health"]["all_features_active"] is False
    # **記録だけで再開材料が引ける**（`--resume` が exit 1 を返す条件）
    assert failed_stage(rec) is not None


def test_致命工程の事前フックが例外でも記録から追える(tmp_path):
    """断られた場合と同じ。落ちたことが記録に残らなければ追えない。"""
    c = _coordinator(tmp_path)

    async def _爆ぜる(harness, worker, ctx):
        if type(worker).__name__ == "TranscribeWorker":
            raise RuntimeError("governance boom")
        return False, None

    c._fire_pre_hook = _爆ぜる

    result = _run(c, tmp_path)

    assert result["status"] == "error", result["status"]
    rec = _run_json(tmp_path)
    assert "transcribe" in [s.get("name") for s in rec["stages"]], rec["stages"]
    assert "transcribe" in rec["health"]["failed_stages"], rec["health"]


def test_断られた工程を改善ループが動かさない(tmp_path):
    """**ガバナンスが禁じた工程を、改善ループが迂回して実行していた。**

    `_quality_improvement_loop` は `_execute_worker` を直接呼んでおり、
    `_fire_pre_hook` を通さない。拒否で False にした `_outcomes` が
    **成功で上書きされ**、`completed` に戻ったうえ、記録には拒否の痕跡が
    1つも残らなかった（gate-verifier の指摘2）。
    """
    c = _coordinator(tmp_path)
    c._fire_pre_hook = _拒否する("QualityGateWorker")

    result = _run(c, tmp_path)

    assert result["status"] != "completed", result["status"]
    rec = _run_json(tmp_path)
    assert "quality_gate" in rec["health"]["failed_stages"], rec["health"]


def test_結果を返さない工程を成功に数えない(tmp_path):
    """**`None` は成功ではない。** C1b の条件文が名指ししている「工程が結果を
    返さない」がこれ。

    記録側は `result is not None and not result.success` を見ていたので
    **`None` だと `success` と書かれ**、`_outcomes` は失敗という食い違いが
    起きていた。直列側はさらに `result.retries` で AttributeError になり、
    **実行ごと落ちて記録が閉じられなかった**（`status: running` のまま）。
    """
    c = _coordinator(tmp_path)

    async def _何も返さない(ctx):
        return None

    for w in c.workers:
        if type(w).__name__ == "YouTubeOptWorker":
            w.execute = _何も返さない

    result = _run(c, tmp_path)

    assert result["status"] != "completed", result["status"]
    rec = _run_json(tmp_path)
    youtube = [s for s in rec["stages"] if s.get("name") == "youtube_opt"]
    assert youtube, rec["stages"]
    assert all(s["status"] == "failed" for s in youtube), youtube
    assert "youtube_opt" in rec["health"]["failed_stages"], rec["health"]


def test_直列で結果を返さなくても実行は落ちない(tmp_path):
    """**記録が閉じられないのが一番困る。** 落ちた事実ごと消える。"""
    c = _coordinator(tmp_path)

    async def _何も返さない(ctx):
        return None

    for w in c.workers:
        if type(w).__name__ == "ProofreadWorker":
            w.execute = _何も返さない

    result = _run(c, tmp_path)

    assert result["status"] != "completed", result["status"]
    rec = _run_json(tmp_path)
    assert rec["status"] in ("failed", "degraded"), rec["status"]
    assert "proofread" in rec["health"]["failed_stages"], rec["health"]


# --- 目標尺は素材から決める（2026-08-27 ユーザー決定）-------------------------


def test_目標尺を素材の尺から決める():
    """**付け忘れると黙って -50 点**になっていた。

    `--target-minutes` の既定は20分で、30秒の素材に対して品質ゲートの
    QV-01 が「出力尺異常（目標20分, 差19.6分）」で満額の減点を打っていた。
    実測: 目標尺を素材に合わせるだけで **2点 → 52点**。
    """
    from agents import pipeline_coordinator as pc

    assert pc._auto_target_minutes(30.0) == 1       # 30秒 → 1分（0分にしない）
    assert pc._auto_target_minutes(90.0) == 2
    assert pc._auto_target_minutes(1800.0) == 30    # C5 の30分素材


def test_尺が読めなければ既定値にすり替えない():
    """**「確かめられなかった」を「20分だった」にしない。**

    既存の `get_video_duration()` は失敗を 15.0 秒に握り潰す。同じ形にすると
    誤った目標尺が黙って入り、また -50 点が出る。
    """
    from agents import pipeline_coordinator as pc

    assert pc._auto_target_minutes(None) is None
    assert pc._auto_target_minutes(0.0) is None
    assert pc._auto_target_minutes(-1.0) is None


def test_明示した目標尺が自動より優先される(tmp_path, monkeypatch):
    """**狙いがあるときは人が上書きできる。**"""
    from agents import pipeline_coordinator as pc

    video = tmp_path / "素材.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(pc, "_probe_duration_sec", lambda p: 30.0)
    渡された = {}

    def _捕まえる(self, ctx):
        渡された["target_minutes"] = ctx.target_minutes
        raise SystemExit(0)

    monkeypatch.setattr(pc.PipelineCoordinator, "execute", _捕まえる)

    for argv, 期待 in (([str(video)], 1), ([str(video), "--target-minutes", "20"], 20)):
        try:
            pc.main(argv)
        except SystemExit:
            pass
        assert 渡された["target_minutes"] == 期待, argv


# --- 使われていない中間成果物（R1.5-C3）---------------------------------------


def test_中間成果物の使われ方が記録に残る(tmp_path):
    """**AI が金を使って作ったものが捨てられていないか。**

    `youtube_opt` の titles / tags / description は `ctx.metadata` に入るだけで、
    成果物にも実行記録にも残らない（CLI 実行では戻り値ごと消える）。
    消費者である YouTube 投稿が未実装だから。**それを件数で出す。**
    """
    c = _coordinator(tmp_path)
    for w in c.workers:
        if type(w).__name__ == "YouTubeOptWorker":
            async def _メタデータを作る(ctx, _w=w):
                ctx.metadata = {"titles": ["案1"], "tags": ["t"], "description": "d"}
                return StageResult(stage_name=_w.name, success=True, detail="やった")
            w.execute = _メタデータを作る

    _run(c, tmp_path)

    中間 = {i["name"]: i for i in _run_json(tmp_path)["intermediates"]}
    assert 中間["youtube_metadata"]["produced"] is True
    assert 中間["youtube_metadata"]["consumed"] is False
    assert 中間["youtube_metadata"]["consumed_by"] == "youtube_upload"


def test_作られていない中間成果物は捨てられたと言わない(tmp_path):
    """**作られていないものは「捨てられた」ではない。**"""
    c = _coordinator(tmp_path)

    _run(c, tmp_path)

    中間 = {i["name"]: i for i in _run_json(tmp_path)["intermediates"]}
    assert 中間["youtube_metadata"]["produced"] is False
