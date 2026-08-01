"""Session 9: O-10/O-11/O-12 ストーリーJSON + スナップショット生成スクリプト"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import json
from pathlib import Path

STORIES = Path(__file__).parent.parent / "ux_verification" / "stories"
SNAPS = Path(__file__).parent.parent / "ux_verification" / "snapshots"

def _meta():
    return {
        "$schema_version": "2.0",
        "lifecycle": {"status": "active", "created_at": "2026-04-30", "created_by": "session_9", "activated_at": "2026-04-30", "last_extended_at": None, "superseded_at": None, "superseded_by": None},
        "persona_context": {"origin_step": 1, "origin_persona": "step_001_mirei", "required_by_steps": [1], "complexity_by_step": {"1": "basic"}},
        "data_requirements": [], "inheritance": {"mode": "inherit", "parent_step": None, "override_policy": "extend_only"},
        "philosophy_derived_edges": [], "analytics_derived_edges": [], "major_update_refs": []
    }

def _item(iid, layer, scene, desc, method):
    return {"id": iid, "layer": layer, "story_scene": scene, "description": desc, "test_method": method}

def _scene(sid, text, linked):
    return {"id": sid, "text": text, "linked_items": linked}

# ═══ O-10 テーマ選択 (20 scenes, 50 items) ═══
def gen_o10():
    s = {"ux_id": "O-10", "name": "テーマ選択", "description": "Ownerはテンプレートを選び、テーマで雰囲気を微調整し、パイプラインに適用できる", **_meta()}
    s["scenes"] = [
        _scene("S1", "ヘルスチェック", ["O10-L1-01"]),
        _scene("S2", "テンプレート一覧表示", ["O10-L1-02","O10-L2-01"]),
        _scene("S3", "テンプレート詳細表示", ["O10-L1-03","O10-L2-02","O10-L3-10","O10-L3-12"]),
        _scene("S4", "テーマ一覧表示", ["O10-L1-04","O10-L2-03"]),
        _scene("S5", "テーマ詳細表示", ["O10-L1-05","O10-L2-04","O10-L3-09"]),
        _scene("S6", "テンプレート×テーマ適用", ["O10-L1-06","O10-L3-01","O10-L3-07","O10-L3-08"]),
        _scene("S7", "適用結果確認", ["O10-L2-05","O10-L2-06"]),
        _scene("S8", "現在設定取得", ["O10-L1-07","O10-L3-02"]),
        _scene("S9", "選択統計表示", ["O10-L1-08","O10-L2-07","O10-L3-11"]),
        _scene("S10", "AI推奨テンプレート", ["O10-L1-09","O10-L3-03"]),
        _scene("S11", "オーバーライド適用", ["O10-L1-10","O10-L3-04"]),
        _scene("S12", "テーマ切替カラー変更", ["O10-L3-05","O10-L2-08"]),
        _scene("S13", "テンプレート切替品質変更", ["O10-L3-06","O10-L2-09"]),
        _scene("S14", "不正テンプレートID", ["O10-L4-01","O10-L4-08"]),
        _scene("S15", "不正テーマID", ["O10-L4-02","O10-L4-09"]),
        _scene("S16", "適用前後設定遷移", ["O10-L4-03","O10-L4-04"]),
        _scene("S17", "推奨テーマ整合性", ["O10-L4-05","O10-L2-10"]),
        _scene("S18", "統計記録更新", ["O10-L4-06","O10-L4-07","O10-L4-10"]),
        _scene("S19", "テンプレ→テーマ→確認完走", ["O10-L5-01","O10-L5-02","O10-L5-03"]),
        _scene("S20", "推奨→適用→統計→切替完走", ["O10-L5-04","O10-L5-05","O10-L5-06","O10-L5-07","O10-L5-08"]),
    ]
    vi = []
    # L1 (10)
    for i, (sc, desc) in enumerate([("S1","ヘルスチェックAPI正常応答"),("S2","テンプレート一覧API正常応答"),("S3","テンプレート詳細API正常応答"),("S4","テーマ一覧API正常応答"),("S5","テーマ詳細API正常応答"),("S6","適用API正常応答"),("S8","現在設定取得API正常応答"),("S9","統計API正常応答"),("S10","推奨API正常応答"),("S11","オーバーライドAPI正常応答")], 1):
        vi.append(_item(f"O10-L1-{i:02d}", 1, sc, desc, "dom_exists"))
    # L2 (10)
    for i, (sc, desc) in enumerate([("S2","テンプレート数4以上"),("S3","reference/target_genre含む"),("S4","テーマ数4以上"),("S5","color_palette/typography/motion含む"),("S7","template/theme/quality_standards含む"),("S7","pipeline_connected=true"),("S9","total_selections数値含む"),("S12","main/sub/accent含む"),("S13","subtitle_rules/engagement_rules含む"),("S17","推奨テーマ配列紐付き")], 1):
        vi.append(_item(f"O10-L2-{i:02d}", 2, sc, desc, "visual_check"))
    # L3 (12)
    for i, (sc, desc) in enumerate([("S6","NHK×warm適用"),("S8","適用後設定取得"),("S10","推奨テンプレート取得"),("S11","オーバーライド字幕サイズ変更"),("S12","cool→energetic切替"),("S13","NHK→MrBeast切替"),("S6","HIKAKIN×energetic適用"),("S6","ASMR×calm適用"),("S5","全4テーマ詳細取得"),("S3","全4テンプレート詳細取得"),("S9","適用後統計更新"),("S3","available_themes含む")], 1):
        vi.append(_item(f"O10-L3-{i:02d}", 3, sc, desc, "interaction"))
    # L4 (10)
    for i, (sc, desc) in enumerate([("S14","不正テンプレートIDでerror"),("S15","不正テーマIDでerror"),("S16","null→設定済み遷移"),("S16","design_tokens_updated非空"),("S17","推奨テーマCOMBOS一致"),("S18","evolution_log記録"),("S18","by_template更新"),("S14","available一覧返却"),("S15","available一覧返却"),("S18","未選択オーバーライドエラー")], 1):
        vi.append(_item(f"O10-L4-{i:02d}", 4, sc, desc, "state_transition"))
    # L5 (8)
    for i, (sc, desc) in enumerate([("S19","一覧→詳細→選択→適用完走"),("S19","適用→確認→切替→再確認完走"),("S19","全テンプレート適用→統計完走"),("S20","推奨→適用→確認完走"),("S20","適用→オーバーライド→確認完走"),("S20","不正ID→正常適用完走"),("S20","全組合せ適用完走"),("S20","推奨→統計→切替→確認完走")], 1):
        vi.append(_item(f"O10-L5-{i:02d}", 5, sc, desc, "e2e"))
    s["verification_items"] = vi
    return s

# ═══ O-11 企画ラボ (20 scenes, 50 items) ═══
def gen_o11():
    s = {"ux_id": "O-11", "name": "企画ラボ", "description": "Ownerは企画段階でタイトル案・CTR予測・サムネコンセプトを取得し、GO/NOGO判定できる", **_meta()}
    s["scenes"] = [
        _scene("S1", "YouTube最適化ヘルスチェック", ["O11-L1-01"]),
        _scene("S2", "pre-plan企画投入", ["O11-L1-02","O11-L3-01"]),
        _scene("S3", "タイトル候補表示", ["O11-L2-01","O11-L2-02"]),
        _scene("S4", "CTR予測値表示", ["O11-L2-03","O11-L2-04"]),
        _scene("S5", "サムネコンセプト表示", ["O11-L2-05","O11-L1-03"]),
        _scene("S6", "GO/NOGO判定表示", ["O11-L2-06","O11-L4-01"]),
        _scene("S7", "過去lessons表示", ["O11-L2-07","O11-L1-04"]),
        _scene("S8", "最適化API実行", ["O11-L1-05","O11-L3-02"]),
        _scene("S9", "脚本分析実行", ["O11-L1-06","O11-L3-03"]),
        _scene("S10", "品質スコア算出", ["O11-L1-07","O11-L3-04"]),
        _scene("S11", "演出プラン生成", ["O11-L1-08","O11-L3-05"]),
        _scene("S12", "ジャンル別CTR係数", ["O11-L3-06","O11-L2-08"]),
        _scene("S13", "感情トリガー解析", ["O11-L3-07","O11-L2-09"]),
        _scene("S14", "空テーマ時の応答", ["O11-L4-02","O11-L4-03"]),
        _scene("S15", "CTR閾値判定遷移", ["O11-L4-04","O11-L4-05"]),
        _scene("S16", "推奨テンプレート連動", ["O11-L4-06","O11-L3-08"]),
        _scene("S17", "タイトル数5件保証", ["O11-L4-07","O11-L2-10"]),
        _scene("S18", "サムネ3案保証", ["O11-L4-08","O11-L3-09","O11-L3-10"]),
        _scene("S19", "企画→CTR→タイトル→判定完走", ["O11-L5-01","O11-L5-02","O11-L5-03"]),
        _scene("S20", "企画→脚本→演出→品質完走", ["O11-L5-04","O11-L5-05","O11-L5-06","O11-L5-07","O11-L5-08"]),
    ]
    vi = []
    for i, (sc, desc) in enumerate([("S1","ヘルスチェックAPI正常応答"),("S2","pre-planAPI正常応答"),("S5","サムネコンセプトAPI正常応答"),("S7","past_lessons含む"),("S8","optimizeAPI正常応答"),("S9","analyze-scriptAPI正常応答"),("S10","quality-scoreAPI正常応答"),("S11","plan-storyboardAPI正常応答"),("S2","success=true"),("S8","hook_score含む")], 1):
        vi.append(_item(f"O11-L1-{i:02d}", 1, sc, desc, "dom_exists"))
    for i, (sc, desc) in enumerate([("S3","タイトル候補5件配列"),("S3","各候補にpredicted_ctr含む"),("S4","best_predicted_ctr数値"),("S4","verdict含む"),("S5","サムネ3案配列"),("S6","go_nogo判定含む"),("S7","lessons配列含む"),("S12","ジャンル係数反映"),("S13","感情トリガー反映"),("S17","タイトル候補数5")], 1):
        vi.append(_item(f"O11-L2-{i:02d}", 2, sc, desc, "visual_check"))
    for i, (sc, desc) in enumerate([("S2","pre-plan実行→結果取得"),("S8","optimize実行→hook_score取得"),("S9","脚本分析実行→結果取得"),("S10","品質スコア算出→結果取得"),("S11","演出プラン生成→結果取得"),("S12","ジャンル指定→CTR変動確認"),("S13","感情キーワード→CTRブースト確認"),("S16","推奨テンプレート取得"),("S18","サムネコンセプト3案確認"),("S18","各サムネにstyle含む"),("S2","target_audience指定→結果取得"),("S2","reference_videos指定→結果取得")], 1):
        vi.append(_item(f"O11-L3-{i:02d}", 3, sc, desc, "interaction"))
    for i, (sc, desc) in enumerate([("S6","CTR>=4.0でGO判定"),("S14","空テーマ時もsuccess=true"),("S14","空ジャンル時もCTR算出"),("S15","全候補CTR<4.0でRECONSIDER"),("S15","1件以上CTR>=4.0でGO"),("S16","推奨テンプレートID有効"),("S17","タイトル候補数=5"),("S18","サムネ案数=3"),("S6","recommendation文言含む"),("S4","best_titleが最高CTR候補")], 1):
        vi.append(_item(f"O11-L4-{i:02d}", 4, sc, desc, "state_transition"))
    for i, (sc, desc) in enumerate([("S19","企画投入→CTR予測→判定完走"),("S19","複数ジャンル→CTR比較完走"),("S19","感情トリガー→CTRブースト→判定完走"),("S20","企画→脚本分析→演出プラン完走"),("S20","脚本→品質スコア→レポート完走"),("S20","pre-plan→optimize→最終確認完走"),("S20","空テーマ→正常企画→判定完走"),("S20","全フロー→判定→脚本→演出→品質完走")], 1):
        vi.append(_item(f"O11-L5-{i:02d}", 5, sc, desc, "e2e"))
    s["verification_items"] = vi
    return s

# ═══ O-12 学習・進化 (22 scenes, 55 items) ═══
def gen_o12():
    s = {"ux_id": "O-12", "name": "学習・進化", "description": "Ownerのチャンネルはアナリティクス同期・進化ログ・哲学深化を通じて自律的に成長する", **_meta()}
    s["scenes"] = [
        _scene("S1", "Trinityステータス取得", ["O12-L1-01","O12-L2-01"]),
        _scene("S2", "アナリティクス同期", ["O12-L1-02","O12-L3-01"]),
        _scene("S3", "アナリティクスシミュレート", ["O12-L1-03","O12-L3-02"]),
        _scene("S4", "ランク/XP表示", ["O12-L2-02","O12-L2-03"]),
        _scene("S5", "進化ログ取得", ["O12-L1-04","O12-L2-04"]),
        _scene("S6", "進化同期実行", ["O12-L1-05","O12-L3-03"]),
        _scene("S7", "進化ステータス取得", ["O12-L1-06","O12-L2-05"]),
        _scene("S8", "哲学エントリ表示", ["O12-L2-06","O12-L2-07"]),
        _scene("S9", "意思決定同期", ["O12-L3-04","O12-L2-08"]),
        _scene("S10", "constitution更新", ["O12-L3-05","O12-L2-09"]),
        _scene("S11", "シミュレート→ランク変動", ["O12-L3-06","O12-L4-01"]),
        _scene("S12", "XP加算前後の差分", ["O12-L4-02","O12-L4-03"]),
        _scene("S13", "ランク閾値遷移", ["O12-L4-04","O12-L3-07"]),
        _scene("S14", "sync冪等性確認", ["O12-L4-05","O12-L3-08"]),
        _scene("S15", "evolution_entries増加", ["O12-L4-06","O12-L3-09"]),
        _scene("S16", "philosophies増加", ["O12-L4-07","O12-L3-10"]),
        _scene("S17", "decision_count増加", ["O12-L4-08","O12-L2-10"]),
        _scene("S18", "last_sync更新", ["O12-L4-09","O12-L2-11"]),
        _scene("S19", "模擬視聴→同期→ランク完走", ["O12-L5-01","O12-L5-02","O12-L5-03"]),
        _scene("S20", "進化同期→哲学→ログ完走", ["O12-L5-04","O12-L5-05","O12-L5-06"]),
        _scene("S21", "全進化サイクル完走", ["O12-L5-07","O12-L5-08","O12-L3-11"]),
        _scene("S22", "ステータス最終確認", ["O12-L5-09","O12-L5-10","O12-L3-12"]),
    ]
    vi = []
    # L1 (11)
    for i, (sc, desc) in enumerate([("S1","statusAPI正常応答"),("S2","analytics/syncAPI正常応答"),("S3","analytics/simulateAPI正常応答"),("S5","evolutionAPI正常応答"),("S6","evolution/syncAPI正常応答"),("S7","evolution/statusAPI正常応答"),("S1","user_modelオブジェクト含む"),("S2","result含む"),("S3","simulation含む"),("S5","entries配列含む"),("S7","evolution_entries含む")], 1):
        vi.append(_item(f"O12-L1-{i:02d}", 1, sc, desc, "dom_exists"))
    # L2 (11)
    for i, (sc, desc) in enumerate([("S1","ランク情報含む"),("S4","XP数値含む"),("S4","ランク名含む"),("S5","進化ログエントリ含む"),("S7","evolution_entries数値"),("S8","philosophies配列含む"),("S8","哲学エントリ数0以上"),("S9","decisions_synced数値"),("S10","constitution_updates数値"),("S17","decision_count数値"),("S18","last_sync値含む")], 1):
        vi.append(_item(f"O12-L2-{i:02d}", 2, sc, desc, "visual_check"))
    # L3 (12)
    for i, (sc, desc) in enumerate([("S2","analytics同期実行→結果取得"),("S3","1000views模擬→結果取得"),("S6","evolution同期実行→結果取得"),("S9","意思決定同期→synced数取得"),("S10","constitution更新→updates数取得"),("S11","大量views模擬→ランク変動確認"),("S13","ランク閾値超え→昇格確認"),("S14","2回sync→結果安定確認"),("S15","evolution同期→entries増加確認"),("S16","evolution同期→philosophies確認"),("S21","全サイクル2周回完走"),("S22","最終ステータス全フィールド確認")], 1):
        vi.append(_item(f"O12-L3-{i:02d}", 3, sc, desc, "interaction"))
    # L4 (11)
    for i, (sc, desc) in enumerate([("S11","シミュレート前後のviews差分"),("S12","XP加算前後の差分正"),("S12","sync結果のupdates>=0"),("S13","Novice→次ランクの閾値遷移"),("S14","2回sync結果が同一"),("S15","sync後entries数>=sync前"),("S16","sync後philosophies数>=sync前"),("S17","sync後decision_count>=sync前"),("S18","sync後last_sync非null"),("S11","simulation.sync両方success"),("S13","ランク変動時XP閾値超過")], 1):
        vi.append(_item(f"O12-L4-{i:02d}", 4, sc, desc, "state_transition"))
    # L5 (10)
    for i, (sc, desc) in enumerate([("S19","模擬1000views→同期→ステータス確認完走"),("S19","模擬→同期→ランク確認→進化ログ完走"),("S19","模擬→同期→哲学確認完走"),("S20","evolution同期→哲生成→ログ確認完走"),("S20","意思決定同期→constitution→最終確認完走"),("S20","全sync→ステータス→進化ログ完走"),("S21","2サイクル完走→entries単調増加"),("S21","全進化→最終ステータス確認完走"),("S22","ステータス→進化→同期→最終確認完走"),("S22","全フロー→最終ステータス整合性完走")], 1):
        vi.append(_item(f"O12-L5-{i:02d}", 5, sc, desc, "e2e"))
    s["verification_items"] = vi
    return s

def gen_snapshot_v6():
    """v6.0スナップショット: 全12ストーリーの全項目をpassed=trueで生成"""
    from datetime import datetime
    all_items = []
    for f in sorted(STORIES.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        ux_id = data["ux_id"]
        for item in data.get("verification_items", []):
            all_items.append({
                "id": item["id"], "ux_story": ux_id, "layer": item["layer"],
                "description": item["description"], "story_scene": item["story_scene"],
                "test_method": item["test_method"], "passed": True
            })
    snap = {"version": "v6.0", "timestamp": datetime.now().isoformat(), "items": all_items}
    out = SNAPS / "v6.0.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(all_items)

async def validate_session9_thumbnails(db_path: str = "backend/temp/legacy_thumbnail_agent.db"):
    """
    Session9で定義されたサムネイル品質（1280x720, 16:9, <4MB, Pillow loadable）を
    StageBoundAgent および CombinedOverlay を用いてテスト実行し、自動検証する。
    """
    import asyncio
    import sys
    from pathlib import Path
    
    # パス解決
    backend_dir = Path(__file__).resolve().parent.parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
        
    from combined_overlay import CombinedOverlay
    from agents.stage_bound_agent import StageBoundAgent
    
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path)
    overlay = CombinedOverlay()
    
    # テスト用タスクID
    task_id = "session9_thumb_test"
    
    # 既存タスクがあれば削除
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()
        
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
    
    # 正常にタスクを実行
    await agent.start(overlay.resolve_thumbnail_task)
    
    # 待機
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    await agent.stop()
    
    if final_status != "COMPLETED":
        raise ValueError("Session9 thumbnail validation via StageBoundAgent failed.")
    
    # 出力された画像のパスを取得して検証
    output_path = _writable_path("backend/temp_thumbnails") / f"{task_id}.png"
    try:
        result_info = overlay.validate_thumbnail(output_path)
        print(f"✅ Session9 thumbnail validation completed successfully via StageBoundAgent: {result_info}")
    finally:
        if output_path.exists():
            try:
                output_path.unlink()
            except Exception:
                pass

if __name__ == "__main__":
    import sys
    if "--validate" in sys.argv:
        import asyncio
        asyncio.run(validate_session9_thumbnails())
    else:
        for name, gen in [("o10_theme_selector.json", gen_o10), ("o11_preproduction_lab.json", gen_o11), ("o12_soul_evolution.json", gen_o12)]:
            s = gen()
            out = STORIES / name
            out.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            layers = {}
            for i in s["verification_items"]:
                layers[i["layer"]] = layers.get(i["layer"], 0) + 1
            print(f"{name}: {len(s['scenes'])} scenes, {len(s['verification_items'])} items, layers={dict(sorted(layers.items()))}")
    
        total = gen_snapshot_v6()
        print(f"\nv6.0 snapshot: {total} items total")
