"""
全機能テスト — ハーネス ToolRegistry 経由 / GPU処理優先

同一RAW動画で全7ツールを tool_registry.execute() で実行。
Hook発火・Governance・Session を全て通過させる。
API依存ステージは 429 を graceful に処理。
"""
import asyncio
import json
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

VIDEO = r"C:\Users\PC_User\Desktop\script\video-automation\vault-outputs\merged\merged_20260405_202804.mp4"
TARGET_MINUTES = 20


def parse_result(r):
    """ToolResult (dataclass) からデータを取得"""
    try:
        text = r.content[0]["text"] if r.content else "{}"
        return json.loads(text), r.is_error
    except Exception:
        return {"raw": str(r.content)}, r.is_error


async def main():
    from harness.tool_registry import tool_registry
    from harness.pipeline_tools import register_pipeline_tools

    register_pipeline_tools()
    tools = tool_registry.list_tools()
    print("=" * 60)
    print(f"🔬 ハーネス全機能テスト — GPU処理優先")
    print(f"   ToolRegistry: {len(tools)} tools")
    print(f"   動画: 43min / 1049MB")
    print("=" * 60)

    results = {}
    total_start = time.time()

    # Stage 1: 文字起こし (GPU: Whisper)
    print(f"\n{'─'*60}")
    print(f"  🎤 Stage 1: 文字起こし [GPU: Whisper]")
    print(f"{'─'*60}")
    t0 = time.time()
    try:
        r1 = await tool_registry.execute("transcribe_video", {
            "video_path": VIDEO, "target_minutes": TARGET_MINUTES,
        })
        dt = time.time() - t0
        data, is_err = parse_result(r1)
        succ = data.get("success", False) and not is_err
        print(f"  {'✅' if succ else '⚠️'} segs={data.get('total_segments',0)} ({dt:.1f}s)")
        results["1_transcribe"] = {"status": "PASS" if succ else "PARTIAL", "time": dt, "segments": data.get("total_segments", 0)}
        from agents.pipeline_coordinator import PipelineContext, TranscribeWorker
        ctx = PipelineContext(video_path=VIDEO, target_minutes=TARGET_MINUTES)
        await TranscribeWorker().execute(ctx)
        segments = ctx.segments or []
    except Exception as e:
        dt = time.time() - t0
        print(f"  ❌ ({dt:.1f}s): {str(e)[:120]}")
        results["1_transcribe"] = {"status": "FAIL", "time": dt}
        segments = []
    if not segments:
        segments = [{"start": 0, "end": 60, "text": "ダミー1"}, {"start": 60, "end": 120, "text": "ダミー2"}, {"start": 120, "end": 300, "text": "ダミー3"}]

    # Stage 2: AI校閲
    print(f"\n{'─'*60}")
    print(f"  📝 Stage 2: AI校閲 [API]")
    print(f"{'─'*60}")
    t0 = time.time()
    r2 = await tool_registry.execute("proofread_subtitles", {"video_path": VIDEO, "segments": segments})
    dt = time.time() - t0
    data, is_err = parse_result(r2)
    is_429 = "429" in str(data) or "RESOURCE_EXHAUSTED" in str(data)
    if is_429:
        print(f"  ⏭️ API クォータ枯渇 ({dt:.1f}s)")
        results["2_proofread"] = {"status": "SKIP_429", "time": dt}
    else:
        print(f"  {'✅' if not is_err else '⚠️'} ({dt:.1f}s)")
        results["2_proofread"] = {"status": "PASS" if not is_err else "PARTIAL", "time": dt}

    # Stage 3: SmartCut (ローカル処理)
    print(f"\n{'─'*60}")
    print(f"  ✂️ Stage 3: SmartCut [Local]")
    print(f"{'─'*60}")
    t0 = time.time()
    r3 = await tool_registry.execute("propose_smart_cut", {"video_path": VIDEO, "segments": segments, "target_minutes": TARGET_MINUTES})
    dt = time.time() - t0
    data, is_err = parse_result(r3)
    sc_count = data.get("selected_count", 0)
    sc_detail = data.get("detail", "")
    print(f"  {'✅' if not is_err else '⚠️'} {sc_detail} ({dt:.1f}s)")
    results["3_smartcut"] = {"status": "PASS" if not is_err else "PARTIAL", "time": dt, "selected": sc_count}

    # SmartCut結果のselected_segmentsをWorkerから取得
    from agents.pipeline_coordinator import SmartCutWorker, PipelineContext as _PC
    _ctx3 = _PC(video_path=VIDEO, target_minutes=TARGET_MINUTES)
    _ctx3.segments = segments
    await SmartCutWorker().execute(_ctx3)
    selected = _ctx3.selected_segments or segments
    print(f"  → 選定: {len(selected)}/{len(segments)} セグメント")

    # Stage 4: プレビュー生成 (GPU: FFmpeg)
    print(f"\n{'─'*60}")
    print(f"  🎬 Stage 4: プレビュー生成 [GPU: FFmpeg]")
    print(f"{'─'*60}")
    t0 = time.time()
    r4 = await tool_registry.execute("generate_preview", {"video_path": VIDEO, "selected_segments": selected})
    dt = time.time() - t0
    data, is_err = parse_result(r4)
    preview_path = data.get("preview_path", "")
    succ = data.get("success", False)
    print(f"  {'✅' if succ else '⚠️'} ({dt:.1f}s)")
    if preview_path and os.path.exists(str(preview_path)):
        print(f"  → {os.path.basename(preview_path)} ({os.path.getsize(preview_path)/1048576:.1f}MB)")
    results["4_preview"] = {"status": "PASS" if succ else "FAIL", "time": dt}

    # Stage 5: YouTube最適化
    print(f"\n{'─'*60}")
    print(f"  📊 Stage 5: YouTube最適化 [API]")
    print(f"{'─'*60}")
    t0 = time.time()
    r5 = await tool_registry.execute("optimize_youtube", {"video_path": VIDEO, "segments": segments})
    dt = time.time() - t0
    data, is_err = parse_result(r5)
    is_429 = "429" in str(data) or "RESOURCE_EXHAUSTED" in str(data)
    if is_429:
        print(f"  ⏭️ API クォータ枯渇 ({dt:.1f}s)")
        results["5_youtube"] = {"status": "SKIP_429", "time": dt}
    else:
        print(f"  {'✅' if not is_err else '⚠️'} ({dt:.1f}s)")
        results["5_youtube"] = {"status": "PASS" if not is_err else "PARTIAL", "time": dt}

    # YouTube結果からmetadataを取得（品質チェックに渡す）
    yt_metadata = data.get("data", {}).get("metadata", data.get("metadata", {}))
    # フォールバック: Workerから直接取得
    if not yt_metadata:
        from agents.pipeline_coordinator import YouTubeOptWorker, PipelineContext as _PC5
        _ctx5 = _PC5(video_path=VIDEO, target_minutes=TARGET_MINUTES)
        _ctx5.segments = segments
        await YouTubeOptWorker().execute(_ctx5)
        yt_metadata = _ctx5.metadata or {}
    print(f"  → メタデータ: titles={len(yt_metadata.get('titles',[]))} tags={len(yt_metadata.get('tags',[]))}")

    # Stage 6: 品質チェック (Local)
    print(f"\n{'─'*60}")
    print(f"  ✅ Stage 6: 品質チェック [Local]")
    print(f"{'─'*60}")
    t0 = time.time()
    r6 = await tool_registry.execute("check_quality", {
        "video_path": VIDEO, "preview_path": preview_path or VIDEO,
        "segments": segments, "selected_segments": selected, "metadata": yt_metadata,
    })
    dt = time.time() - t0
    data, is_err = parse_result(r6)
    score = data.get("score", 0)
    rank = data.get("rank", "?")
    print(f"  {'✅' if not is_err else '⚠️'} score={score}/100 rank={rank} ({dt:.1f}s)")
    results["6_quality"] = {"status": "PASS" if not is_err else "PARTIAL", "time": dt, "score": score}

    # Stage 7: 最終レンダリング (GPU: FFmpeg)
    print(f"\n{'─'*60}")
    print(f"  🎞️ Stage 7: 最終レンダリング [GPU: FFmpeg]")
    print(f"{'─'*60}")
    render_src = preview_path if preview_path and os.path.exists(str(preview_path)) else VIDEO
    t0 = time.time()
    r7 = await tool_registry.execute("render_final", {"video_path": VIDEO, "preview_path": render_src})
    dt = time.time() - t0
    data, is_err = parse_result(r7)
    final_path = data.get("final_path", "")
    succ = data.get("success", False)
    print(f"  {'✅' if succ else '⚠️'} ({dt:.1f}s)")
    if final_path and os.path.exists(str(final_path)):
        print(f"  → {os.path.basename(str(final_path))} ({os.path.getsize(final_path)/1048576:.1f}MB)")
    results["7_render"] = {"status": "PASS" if succ else "FAIL", "time": dt}

    # ToolRegistry 統計
    print(f"\n{'─'*60}")
    print(f"  📈 ToolRegistry 統計")
    print(f"{'─'*60}")
    stats = tool_registry.get_stats()
    for name, ts in stats["tools"].items():
        if ts["calls"] > 0:
            print(f"  {name}: calls={ts['calls']} errs={ts['errors']} avg={ts['avg_duration_s']}s")

    # サマリー
    total = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"📊 ハーネス全機能テスト サマリー")
    print(f"{'='*60}")
    pass_c = sum(1 for r in results.values() if r["status"] == "PASS")
    part_c = sum(1 for r in results.values() if r["status"] in ("PARTIAL", "SKIP_429"))
    fail_c = sum(1 for r in results.values() if r["status"] == "FAIL")
    for key, r in results.items():
        name = key.split("_", 1)[1]
        icon = {"PASS": "✅", "PARTIAL": "⚠️", "SKIP_429": "⏭️", "FAIL": "❌"}.get(r["status"], "?")
        extra = f" score={r['score']}" if "score" in r else ""
        extra += f" segs={r['segments']}" if "segments" in r else ""
        print(f"  {icon} {name:12s} {r['status']:10s} {r['time']:6.1f}s{extra}")
    print(f"\n  総時間: {total:.1f}s ({total/60:.1f}min)")
    print(f"  PASS={pass_c} PARTIAL/SKIP={part_c} FAIL={fail_c}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
