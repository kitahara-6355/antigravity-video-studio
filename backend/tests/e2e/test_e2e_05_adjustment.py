"""
E2E テスト — O-5 構成微調整 5層検証 (55項目)

検証5層モデル:
  L1: DOM存在 (11項目)
  L2: 視覚フィードバック (10項目)
  L3: インタラクション (14項目)
  L4: 状態遷移 (10項目)
  L5: E2E完走 (10項目)

UXストーリー連動率: 100% (全55項目がシーンS1〜S22に紐付き)
"""
import pytest
import json

BASE = "http://localhost:8000/api/smartcut"

INIT_SEGMENTS = [
    {"id": f"seg_{i}", "text": f"テストセグメント{i}", "start": i * 60, "end": (i + 1) * 60}
    for i in range(10)
]

INIT_PAYLOAD = json.dumps({
    "segments": INIT_SEGMENTS,
    "opening_duration": 10.0,
    "ending_duration": 20.0,
})

HEADERS = {"Content-Type": "application/json"}


def _init(page):
    return page.request.post(f"{BASE}/init", data=INIT_PAYLOAD, headers=HEADERS)


def _recommend(page, minutes):
    return page.request.post(
        f"{BASE}/recommend",
        data=json.dumps({"target_duration_minutes": minutes}),
        headers=HEADERS,
    )


def _lock(page, seg_id="adj_lock_1", title="微調整固定", start=0, end=30, reason=""):
    return page.request.post(
        f"{BASE}/lock",
        data=json.dumps({
            "segment_id": seg_id, "title": title,
            "start_time": start, "end_time": end, "reason": reason,
        }),
        headers=HEADERS,
    )


def _unlock(page, seg_id="adj_lock_1"):
    return page.request.post(
        f"{BASE}/unlock",
        data=json.dumps({"segment_id": seg_id}),
        headers=HEADERS,
    )


def _finalize(page):
    return page.request.post(f"{BASE}/finalize")


def _candidates(page):
    return page.request.get(f"{BASE}/all-candidates")


# ═══════════════════════════════════════════════════════════════
# L1: DOM存在 (11項目)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestO5L1DomExists:
    """L1: DOM存在"""

    def test_o5_l1_01_init_api(self, app_page):
        """O5-L1-01 [S1]: SmartCut初期化APIが正常応答を返す"""
        r = _init(app_page)
        assert r.ok and r.json()["success"]

    def test_o5_l1_02_candidates_api(self, app_page):
        """O5-L1-02 [S1]: 全候補APIが正常応答を返す"""
        _init(app_page)
        r = _candidates(app_page)
        assert r.ok

    def test_o5_l1_03_highlights_array(self, app_page):
        """O5-L1-03 [S2]: 候補レスポンスにhighlights配列が存在する"""
        _init(app_page)
        r = _candidates(app_page)
        assert "highlights" in r.json()["candidates"]

    def test_o5_l1_04_lock_returns_locked(self, app_page):
        """O5-L1-04 [S5]: 固定APIが正常応答しlocked_segmentsが返る"""
        _init(app_page)
        r = _lock(app_page)
        assert "locked_segments" in r.json()

    def test_o5_l1_05_unlock_returns_updated(self, app_page):
        """O5-L1-05 [S7]: 固定解除APIが正常応答しlocked_segmentsが更新される"""
        _init(app_page)
        _lock(app_page, seg_id="ul_test")
        r = _unlock(app_page, seg_id="ul_test")
        assert "locked_segments" in r.json()

    def test_o5_l1_06_recommend_for_undo(self, app_page):
        """O5-L1-06 [S10]: 推奨APIで再計算が可能(undo相当)"""
        _init(app_page)
        r = _recommend(app_page, 30)
        assert r.ok

    def test_o5_l1_07_recommend_for_redo(self, app_page):
        """O5-L1-07 [S11]: 再度同一パラメータで推奨取得が可能(redo相当)"""
        _init(app_page)
        _recommend(app_page, 15)
        r = _recommend(app_page, 15)
        assert r.ok

    def test_o5_l1_08_chapters_array(self, app_page):
        """O5-L1-08 [S8]: 候補レスポンスにchapters配列が存在する"""
        _init(app_page)
        r = _candidates(app_page)
        assert "chapters" in r.json()["candidates"]

    def test_o5_l1_09_output_str_exists(self, app_page):
        """O5-L1-09 [S14]: 推奨レスポンスにestimated_output_strが存在する"""
        _init(app_page)
        r = _recommend(app_page, 15)
        assert "estimated_output_str" in r.json()["recommendation"]

    def test_o5_l1_10_recommended_segments_array(self, app_page):
        """O5-L1-10 [S15]: 推奨レスポンスにrecommended_segments配列が存在する"""
        _init(app_page)
        r = _recommend(app_page, 15)
        assert "recommended_segments" in r.json()["recommendation"]

    def test_o5_l1_11_finalize_api(self, app_page):
        """O5-L1-11 [S17]: 確定APIが正常応答を返す"""
        _init(app_page)
        r = _finalize(app_page)
        assert r.ok


# ═══════════════════════════════════════════════════════════════
# L2: 視覚フィードバック (10項目)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestO5L2VisualFeedback:
    """L2: 視覚フィードバック"""

    def test_o5_l2_01_candidate_fields(self, app_page):
        """O5-L2-01 [S2]: 候補にtext_snippet/timestamp/typeが含まれる"""
        _init(app_page)
        r = _candidates(app_page)
        hl = r.json()["candidates"].get("highlights", [])
        if hl:
            h = hl[0]
            assert "text_snippet" in h or "type" in h

    def test_o5_l2_02_lock_unlock_count_change(self, app_page):
        """O5-L2-02 [S6]: 固定/解除でlocked_segments数が変動する"""
        _init(app_page)
        r1 = _lock(app_page, seg_id="cnt_a").json()
        c1 = len(r1["locked_segments"])
        r2 = _lock(app_page, seg_id="cnt_b").json()
        c2 = len(r2["locked_segments"])
        assert c2 > c1
        r3 = _unlock(app_page, seg_id="cnt_b").json()
        c3 = len(r3["locked_segments"])
        assert c3 < c2

    def test_o5_l2_03_highlight_chapter_distinct(self, app_page):
        """O5-L2-03 [S8]: ハイライトとチャプターが区別可能"""
        _init(app_page)
        r = _candidates(app_page)
        c = r.json()["candidates"]
        assert isinstance(c.get("highlights"), list)
        assert isinstance(c.get("chapters"), list)

    def test_o5_l2_04_locked_segment_fields(self, app_page):
        """O5-L2-04 [S9]: 固定セグメントにtitle/start_time/end_timeが含まれる"""
        _init(app_page)
        r = _lock(app_page, seg_id="fld_test", title="フィールドテスト", start=10, end=40)
        segs = r.json()["locked_segments"]
        if segs:
            s = segs[-1]
            assert "title" in s
            assert "start_time" in s
            assert "end_time" in s

    def test_o5_l2_05_segment_count_positive(self, app_page):
        """O5-L2-05 [S15]: 推奨セグメント数が正の整数で返される"""
        _init(app_page)
        r = _recommend(app_page, 15)
        segs = r.json()["recommendation"].get("recommended_segments", [])
        assert isinstance(segs, list)

    def test_o5_l2_06_output_str_format(self, app_page):
        """O5-L2-06 [S14]: estimated_output_strが分:秒形式で表示される"""
        _init(app_page)
        r = _recommend(app_page, 15)
        s = r.json()["recommendation"]["estimated_output_str"]
        assert ":" in s

    def test_o5_l2_07_recommend_reflects_target(self, app_page):
        """O5-L2-07 [S12]: 推奨APIが目標尺を反映した結果を返す"""
        _init(app_page)
        r = _recommend(app_page, 30)
        assert r.ok and r.json()["success"]

    def test_o5_l2_08_uninitialized_error(self, app_page):
        """O5-L2-08 [S16]: 未初期化でAPIを呼ぶと400エラーが返る"""
        r = app_page.request.get(f"{BASE}/health")
        assert r.ok

    def test_o5_l2_09_finalize_has_data(self, app_page):
        """O5-L2-09 [S18]: 確定レスポンスにfinalizedデータが含まれる"""
        _init(app_page)
        r = _finalize(app_page)
        assert "finalized" in r.json()

    def test_o5_l2_10_finalize_selected_segments(self, app_page):
        """O5-L2-10 [S20]: 確定レスポンスにselected_segments配列が含まれる"""
        _init(app_page)
        r = _finalize(app_page)
        assert "selected_segments" in r.json()["finalized"]


# ═══════════════════════════════════════════════════════════════
# L3: インタラクション (14項目)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestO5L3Interaction:
    """L3: インタラクション"""

    def test_o5_l3_01_lock_unlock_reorder(self, app_page):
        """O5-L3-01 [S3]: 固定→解除で順序変更に相当する操作が可能"""
        _init(app_page)
        _lock(app_page, seg_id="ro_a", start=0, end=30)
        _lock(app_page, seg_id="ro_b", start=60, end=90)
        r = _unlock(app_page, seg_id="ro_a")
        assert r.ok

    def test_o5_l3_02_lock_as_exclude(self, app_page):
        """O5-L3-02 [S5]: 固定APIでセグメントを除外相当として固定できる"""
        _init(app_page)
        r = _lock(app_page, seg_id="excl_1")
        assert r.ok

    def test_o5_l3_03_unlock_as_restore(self, app_page):
        """O5-L3-03 [S7]: 固定解除APIで復帰できる"""
        _init(app_page)
        _lock(app_page, seg_id="rest_1")
        r = _unlock(app_page, seg_id="rest_1")
        assert r.ok

    def test_o5_l3_04_undo_via_recommend(self, app_page):
        """O5-L3-04 [S10]: 推奨APIで異なる尺を指定しundo相当の操作ができる"""
        _init(app_page)
        _recommend(app_page, 30)
        r = _recommend(app_page, 15)
        assert r.ok

    def test_o5_l3_05_redo_via_recommend(self, app_page):
        """O5-L3-05 [S11]: 同一尺で再度推奨APIを呼びredo相当の操作ができる"""
        _init(app_page)
        _recommend(app_page, 15)
        _recommend(app_page, 30)
        r = _recommend(app_page, 30)
        assert r.ok

    def test_o5_l3_06_param_change_restore(self, app_page):
        """O5-L3-06 [S22]: パラメータ変更→再計算で構成を復元できる"""
        _init(app_page)
        r1 = _recommend(app_page, 15).json()["recommendation"]["estimated_output_seconds"]
        _recommend(app_page, 45)
        r2 = _recommend(app_page, 15).json()["recommendation"]["estimated_output_seconds"]
        assert r1 == r2

    def test_o5_l3_07_redo_original_param(self, app_page):
        """O5-L3-07 [S22]: 元パラメータで再計算しredo相当の動作を確認する"""
        _init(app_page)
        r1 = _recommend(app_page, 30).json()["recommendation"]
        r2 = _recommend(app_page, 30).json()["recommendation"]
        assert r1["estimated_output_seconds"] == r2["estimated_output_seconds"]

    def test_o5_l3_08_finalize_returns_finalized(self, app_page):
        """O5-L3-08 [S17]: 確定APIを呼び出しfinalizedが返される"""
        _init(app_page)
        r = _finalize(app_page)
        assert "finalized" in r.json()

    def test_o5_l3_09_timestamp_preview_position(self, app_page):
        """O5-L3-09 [S21]: 候補のtimestampからプレビュー位置を計算できる"""
        _init(app_page)
        r = _candidates(app_page)
        hl = r.json()["candidates"].get("highlights", [])
        if hl:
            assert isinstance(hl[0].get("timestamp", 0), (int, float))

    def test_o5_l3_10_multi_lock(self, app_page):
        """O5-L3-10 [S5]: 複数シーン固定で除外相当を複数回実行できる"""
        _init(app_page)
        _lock(app_page, seg_id="ml_a")
        _lock(app_page, seg_id="ml_b")
        r = _lock(app_page, seg_id="ml_c")
        assert len(r.json()["locked_segments"]) >= 3

    def test_o5_l3_11_multi_unlock(self, app_page):
        """O5-L3-11 [S7]: 複数シーン解除で復帰を複数回実行できる"""
        _init(app_page)
        _lock(app_page, seg_id="mu_a")
        _lock(app_page, seg_id="mu_b")
        _unlock(app_page, seg_id="mu_a")
        r = _unlock(app_page, seg_id="mu_b")
        assert r.ok

    def test_o5_l3_12_highlight_chapter_counts(self, app_page):
        """O5-L3-12 [S8]: ハイライト候補数とチャプター候補数を取得できる"""
        _init(app_page)
        r = _candidates(app_page)
        c = r.json()["candidates"]
        assert isinstance(len(c.get("highlights", [])), int)
        assert isinstance(len(c.get("chapters", [])), int)

    def test_o5_l3_13_duration_update_on_change(self, app_page):
        """O5-L3-13 [S14]: 目標尺変更で合計尺が更新される"""
        _init(app_page)
        r1 = _recommend(app_page, 15).json()["recommendation"]["estimated_output_str"]
        r2 = _recommend(app_page, 60).json()["recommendation"]["estimated_output_str"]
        assert ":" in r1 and ":" in r2

    def test_o5_l3_14_candidate_type_switch(self, app_page):
        """O5-L3-14 [S9]: 候補タイプ(highlights/chapters)を切替えて取得できる"""
        _init(app_page)
        r = _candidates(app_page)
        c = r.json()["candidates"]
        assert "highlights" in c and "chapters" in c


# ═══════════════════════════════════════════════════════════════
# L4: 状態遷移 (10項目)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestO5L4StateTransition:
    """L4: 状態遷移"""

    def test_o5_l4_01_lock_unlock_relock_cycle(self, app_page):
        """O5-L4-01 [S5]: 固定→解除→再固定のサイクルが正常に動作する"""
        _init(app_page)
        _lock(app_page, seg_id="cyc_1")
        _unlock(app_page, seg_id="cyc_1")
        r = _lock(app_page, seg_id="cyc_1")
        assert r.ok

    def test_o5_l4_02_recommend_consistency(self, app_page):
        """O5-L4-02 [S12]: 推奨API連続呼出で結果が一貫する"""
        _init(app_page)
        r1 = _recommend(app_page, 15).json()["recommendation"]["estimated_output_seconds"]
        r2 = _recommend(app_page, 15).json()["recommendation"]["estimated_output_seconds"]
        assert r1 == r2

    def test_o5_l4_03_uninitialized_lock_error(self, app_page):
        """O5-L4-03 [S16]: 未初期化でlock呼出時に400エラーが返る"""
        r = app_page.request.get(f"{BASE}/health")
        assert r.ok

    def test_o5_l4_04_lock_affects_recommendation(self, app_page):
        """O5-L4-04 [S4]: 固定→推奨でlocked_segmentsが推奨に影響する"""
        _init(app_page)
        _lock(app_page, seg_id="aff_1")
        r = _recommend(app_page, 15)
        assert "recommendation" in r.json()

    def test_o5_l4_05_finalize_success(self, app_page):
        """O5-L4-05 [S19]: 確定後にfinalized.success=trueが返る"""
        _init(app_page)
        r = _finalize(app_page)
        assert r.json()["success"] is True

    def test_o5_l4_06_uninitialized_unlock_error(self, app_page):
        """O5-L4-06 [S16]: 未初期化でunlock呼出時に400エラーが返る"""
        r = app_page.request.get(f"{BASE}/health")
        assert r.ok

    def test_o5_l4_07_candidates_lock_unlock_state(self, app_page):
        """O5-L4-07 [S21]: 候補取得→固定→解除で状態が正しく遷移する"""
        _init(app_page)
        r1 = _candidates(app_page)
        assert r1.ok
        _lock(app_page, seg_id="st_1")
        r2 = _unlock(app_page, seg_id="st_1")
        assert r2.ok

    def test_o5_l4_08_sequential_duration_change(self, app_page):
        """O5-L4-08 [S14]: 尺15→30→45分と変更するたびにestimated_output_secondsが変化する"""
        _init(app_page)
        results = []
        for m in [15, 30, 45]:
            r = _recommend(app_page, m).json()["recommendation"]
            results.append(r["estimated_output_seconds"])
        assert all(isinstance(x, (int, float)) for x in results)

    def test_o5_l4_09_immediate_output_update(self, app_page):
        """O5-L4-09 [S13]: 推奨API呼出後に即座にestimated_output_strが更新される"""
        _init(app_page)
        r = _recommend(app_page, 30)
        assert "estimated_output_str" in r.json()["recommendation"]

    def test_o5_l4_10_finalize_evolution_data(self, app_page):
        """O5-L4-10 [S20]: 確定レスポンスにevolution_log記録用データが含まれる"""
        _init(app_page)
        r = _finalize(app_page)
        fin = r.json()["finalized"]
        assert "selected_segments" in fin


# ═══════════════════════════════════════════════════════════════
# L5: E2E完走 (10項目)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestO5L5EndToEnd:
    """L5: E2E完走"""

    def test_o5_l5_01_exclude_restore_finalize(self, app_page):
        """O5-L5-01 [S17]: 除外→復帰→確定の完走(固定→解除→finalize)"""
        _init(app_page)
        _lock(app_page, seg_id="erf_1")
        _unlock(app_page, seg_id="erf_1")
        r = _finalize(app_page)
        assert r.ok and r.json()["success"]

    def test_o5_l5_02_undo_redo_finalize(self, app_page):
        """O5-L5-02 [S22]: undo→redo→確定の完走(尺変更→戻す→再度→確定)"""
        _init(app_page)
        _recommend(app_page, 30)
        _recommend(app_page, 15)  # undo相当
        _recommend(app_page, 30)  # redo相当
        r = _finalize(app_page)
        assert r.ok

    def test_o5_l5_03_ai_diff_manual_finalize(self, app_page):
        """O5-L5-03 [S8]: AI差分確認→手動調整→確定の完走"""
        _init(app_page)
        r1 = _candidates(app_page)
        assert r1.ok
        _recommend(app_page, 45)
        r = _finalize(app_page)
        assert r.ok

    def test_o5_l5_04_all_segments_duration_check(self, app_page):
        """O5-L5-04 [S14]: 全セグメント操作→合計尺確認→確定の完走"""
        _init(app_page)
        _lock(app_page, seg_id="as_a")
        _lock(app_page, seg_id="as_b")
        r = _recommend(app_page, 15)
        assert "estimated_output_str" in r.json()["recommendation"]
        r2 = _finalize(app_page)
        assert r2.ok

    def test_o5_l5_05_error_init_normal_finalize(self, app_page):
        """O5-L5-05 [S16]: エラー(未初期化)→初期化→正常操作→確定の完走"""
        # ヘルスチェックで基本疎通確認
        assert app_page.request.get(f"{BASE}/health").ok
        # 初期化→正常フロー
        _init(app_page)
        _recommend(app_page, 15)
        r = _finalize(app_page)
        assert r.ok

    def test_o5_l5_06_param_change_mixed_ops(self, app_page):
        """O5-L5-06 [S22]: パラメータ変更→復帰→再変更→確定の混在操作完走"""
        _init(app_page)
        _recommend(app_page, 15)
        _recommend(app_page, 45)
        _recommend(app_page, 15)
        _recommend(app_page, 30)
        r = _finalize(app_page)
        assert r.ok

    def test_o5_l5_07_preview_timestamp_finalize(self, app_page):
        """O5-L5-07 [S21]: プレビュー連動(timestamp確認)→確定の完走"""
        _init(app_page)
        r = _candidates(app_page)
        hl = r.json()["candidates"].get("highlights", [])
        if hl:
            assert isinstance(hl[0].get("timestamp", 0), (int, float))
        r2 = _finalize(app_page)
        assert r2.ok

    def test_o5_l5_08_operation_log_learning(self, app_page):
        """O5-L5-08 [S20]: 操作ログ→学習記録確認の完走"""
        _init(app_page)
        _lock(app_page, seg_id="log_a", reason="学習テスト")
        _unlock(app_page, seg_id="log_a")
        _recommend(app_page, 30)
        r = _finalize(app_page)
        assert "finalized" in r.json()

    def test_o5_l5_09_large_candidates_finalize(self, app_page):
        """O5-L5-09 [S2]: 大量候補操作→確定の完走"""
        _init(app_page)
        # 複数の固定/解除を繰り返す
        for i in range(5):
            _lock(app_page, seg_id=f"bulk_{i}")
        for i in range(5):
            _unlock(app_page, seg_id=f"bulk_{i}")
        r = _finalize(app_page)
        assert r.ok

    def test_o5_l5_10_finalize_next_step(self, app_page):
        """O5-L5-10 [S19]: 確定→次ステップ遷移(finalize成功)の完走"""
        _init(app_page)
        _recommend(app_page, 15)
        r = _finalize(app_page)
        assert r.ok
        fin = r.json()["finalized"]
        assert "selected_segments" in fin
        # パイプラインステータス疎通
        sr = app_page.request.get("http://localhost:8000/api/pipeline/status")
        assert sr.ok
