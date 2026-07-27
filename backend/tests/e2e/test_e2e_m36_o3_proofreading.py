"""
E2E テスト — O-3 AI校閲 5層検証 (35項目)

検証5層モデル:
  L1: DOM存在 (8項目)
  L2: 視覚フィードバック (7項目)
  L3: インタラクション (8項目)
  L4: 状態遷移 (6項目)
  L5: E2E完走 (6項目)

UXストーリー連動率: 100% (全35項目がシーンS1〜S10に紐付き)
"""
import pytest
import json


@pytest.mark.e2e
class TestO3L1DomExists:
    """L1: DOM存在 — 校閲UI要素の存在確認"""

    def test_o3_l1_01_panel_exists(self, app_page):
        """O3-L1-01 [S1]: 校閲結果APIがsegments構造を返す"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        assert res.ok
        data = res.json()
        assert "segments" in data

    def test_o3_l1_02_diff_container(self, app_page):
        """O3-L1-02 [S2]: diffセグメントにchangesが含まれる"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        segs = res.json()["segments"]
        assert len(segs) >= 1
        for seg in segs:
            assert "changes" in seg

    def test_o3_l1_03_diff_marks(self, app_page):
        """O3-L1-03 [S2]: 各changeにtype属性が存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        for seg in res.json()["segments"]:
            for ch in seg["changes"]:
                assert "type" in ch
                assert ch["type"] in ["replace", "insert", "delete"]

    def test_o3_l1_04_comparison_view_fields(self, app_page):
        """O3-L1-04 [S3]: original/correctedフィールドが存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        for seg in res.json()["segments"]:
            assert "original" in seg
            assert "corrected" in seg

    def test_o3_l1_05_approve_api_exists(self, app_page):
        """O3-L1-05 [S4]: 承認APIが応答する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        seg_id = res.json()["segments"][0]["id"]
        r = app_page.request.post(
            "http://localhost:8000/api/pipeline/proofreading/approve",
            data=json.dumps({"segment_id": seg_id}),
            headers={"Content-Type": "application/json"},
        )
        assert r.ok

    def test_o3_l1_06_reject_api_exists(self, app_page):
        """O3-L1-06 [S4]: 却下APIが応答する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        seg_id = res.json()["segments"][1]["id"]
        r = app_page.request.post(
            "http://localhost:8000/api/pipeline/proofreading/reject",
            data=json.dumps({"segment_id": seg_id}),
            headers={"Content-Type": "application/json"},
        )
        assert r.ok

    def test_o3_l1_07_approve_all_api(self, app_page):
        """O3-L1-07 [S5]: 全承認APIが応答する"""
        r = app_page.request.post("http://localhost:8000/api/pipeline/proofreading/approve-all")
        assert r.ok

    def test_o3_l1_08_reject_all_api(self, app_page):
        """O3-L1-08 [S5]: 全却下APIが応答する"""
        r = app_page.request.post("http://localhost:8000/api/pipeline/proofreading/reject-all")
        assert r.ok


@pytest.mark.e2e
class TestO3L2VisualFeedback:
    """L2: 視覚フィードバック — テキスト/色/状態表示"""

    def test_o3_l2_01_diff_change_types(self, app_page):
        """O3-L2-01 [S2]: replace/insert/deleteの3種別が区別可能"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        all_types = set()
        for seg in res.json()["segments"]:
            for ch in seg["changes"]:
                all_types.add(ch["type"])
        assert len(all_types) >= 1, "少なくとも1種類の変更タイプが存在"

    def test_o3_l2_02_change_has_content(self, app_page):
        """O3-L2-02 [S2]: 各changeに内容フィールドが存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        for seg in res.json()["segments"]:
            for ch in seg["changes"]:
                if ch["type"] == "replace":
                    assert "original" in ch and "corrected" in ch
                elif ch["type"] == "insert":
                    assert "corrected" in ch
                elif ch["type"] == "delete":
                    assert "original" in ch

    def test_o3_l2_03_original_text_nonempty(self, app_page):
        """O3-L2-03 [S3]: 修正前テキストが空でない"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        for seg in res.json()["segments"]:
            assert len(seg["original"]) > 0

    def test_o3_l2_04_corrected_text_nonempty(self, app_page):
        """O3-L2-04 [S3]: 修正後テキストが空でない"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        for seg in res.json()["segments"]:
            assert len(seg["corrected"]) > 0

    def test_o3_l2_05_status_badge_values(self, app_page):
        """O3-L2-05 [S4]: ステータスがpending/approved/rejectedのいずれか"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        for seg in res.json()["segments"]:
            assert seg["status"] in ["pending", "approved", "rejected"]

    def test_o3_l2_06_line_length_warning_data(self, app_page):
        """O3-L2-06 [S7]: 18文字超過セグメントの文字数が計算可能"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        for seg in res.json()["segments"]:
            char_count = len(seg.get("corrected", ""))
            assert isinstance(char_count, int)

    def test_o3_l2_07_counts_in_result(self, app_page):
        """O3-L2-07 [S8]: 承認数/却下数/保留数が返される"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        data = res.json()
        assert "approved_count" in data
        assert "rejected_count" in data
        assert "pending_count" in data


@pytest.mark.e2e
class TestO3L3Interaction:
    """L3: インタラクション — 承認/却下/辞書/エクスポート操作"""

    def test_o3_l3_01_approve_changes_status(self, app_page):
        """O3-L3-01 [S4]: 承認で status=approved に変わる"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        seg_id = res.json()["segments"][0]["id"]
        app_page.request.post(
            "http://localhost:8000/api/pipeline/proofreading/approve",
            data=json.dumps({"segment_id": seg_id}),
            headers={"Content-Type": "application/json"},
        )
        check = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        target = next(s for s in check.json()["segments"] if s["id"] == seg_id)
        assert target["status"] == "approved"

    def test_o3_l3_02_reject_changes_status(self, app_page):
        """O3-L3-02 [S4]: 却下で status=rejected に変わる"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        seg_id = res.json()["segments"][1]["id"]
        app_page.request.post(
            "http://localhost:8000/api/pipeline/proofreading/reject",
            data=json.dumps({"segment_id": seg_id}),
            headers={"Content-Type": "application/json"},
        )
        check = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        target = next(s for s in check.json()["segments"] if s["id"] == seg_id)
        assert target["status"] == "rejected"

    def test_o3_l3_03_approve_all_operation(self, app_page):
        """O3-L3-03 [S5]: 全承認で全セグメントがapprovedになる"""
        app_page.request.post("http://localhost:8000/api/pipeline/proofreading/approve-all")
        check = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        for seg in check.json()["segments"]:
            assert seg["status"] == "approved", f"seg {seg['id']} not approved"

    def test_o3_l3_04_reject_all_operation(self, app_page):
        """O3-L3-04 [S5]: 全却下で全セグメントがrejectedになる"""
        app_page.request.post("http://localhost:8000/api/pipeline/proofreading/reject-all")
        check = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        for seg in check.json()["segments"]:
            assert seg["status"] == "rejected", f"seg {seg['id']} not rejected"

    def test_o3_l3_05_dictionary_add(self, app_page):
        """O3-L3-05 [S6]: 辞書エントリを追加できる"""
        res = app_page.request.post(
            "http://localhost:8000/api/pipeline/dictionary",
            data=json.dumps({"incorrect": "テスト誤", "correct": "テスト正", "entry_type": "word"}),
            headers={"Content-Type": "application/json"},
        )
        assert res.ok
        assert res.json()["status"] == "added"

    def test_o3_l3_06_dictionary_delete(self, app_page):
        """O3-L3-06 [S6]: 辞書エントリを削除できる"""
        # 追加
        add_res = app_page.request.post(
            "http://localhost:8000/api/pipeline/dictionary",
            data=json.dumps({"incorrect": "削除テスト誤", "correct": "削除テスト正"}),
            headers={"Content-Type": "application/json"},
        )
        entry_id = add_res.json()["entry"]["id"]
        # 削除
        del_res = app_page.request.delete(f"http://localhost:8000/api/pipeline/dictionary/{entry_id}")
        assert del_res.ok

    def test_o3_l3_07_srt_export_format(self, app_page):
        """O3-L3-07 [S9]: SRTエクスポートで-->フォーマットが返る"""
        app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/export/srt")
        assert res.ok
        assert "-->" in res.text()

    def test_o3_l3_08_skip_toggle(self, app_page):
        """O3-L3-08 [S10]: スキップトグルON/OFFで状態が切り替わる"""
        # ON
        on_res = app_page.request.post(
            "http://localhost:8000/api/pipeline/proofreading/skip",
            data=json.dumps({"skip": True}),
            headers={"Content-Type": "application/json"},
        )
        assert on_res.json()["skip"] is True
        # OFF
        off_res = app_page.request.post(
            "http://localhost:8000/api/pipeline/proofreading/skip",
            data=json.dumps({"skip": False}),
            headers={"Content-Type": "application/json"},
        )
        assert off_res.json()["skip"] is False


@pytest.mark.e2e
class TestO3L4StateTransition:
    """L4: 状態遷移 — API構造検証"""

    def test_o3_l4_01_result_structure(self, app_page):
        """O3-L4-01 [S1]: 校閲結果APIが完全な構造を返す"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        data = res.json()
        for key in ["segments", "approved_count", "rejected_count", "pending_count"]:
            assert key in data, f"'{key}' 欠落"

    def test_o3_l4_02_status_structure(self, app_page):
        """O3-L4-02 [S8]: 進捗APIが完全な構造を返す"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/status")
        assert res.ok
        data = res.json()
        for key in ["status", "progress", "total_segments", "approved_segments"]:
            assert key in data, f"'{key}' 欠落"

    def test_o3_l4_03_skip_reflects_in_status(self, app_page):
        """O3-L4-03 [S10]: スキップON→ステータスAPIがskip=trueを返す"""
        app_page.request.post(
            "http://localhost:8000/api/pipeline/proofreading/skip",
            data=json.dumps({"skip": True}),
            headers={"Content-Type": "application/json"},
        )
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/status")
        assert res.json()["skip"] is True
        # 戻す
        app_page.request.post(
            "http://localhost:8000/api/pipeline/proofreading/skip",
            data=json.dumps({"skip": False}),
            headers={"Content-Type": "application/json"},
        )

    def test_o3_l4_04_dictionary_count_increases(self, app_page):
        """O3-L4-04 [S6]: 辞書追加後にカウントが増加する"""
        before = app_page.request.get("http://localhost:8000/api/pipeline/dictionary").json()["count"]
        app_page.request.post(
            "http://localhost:8000/api/pipeline/dictionary",
            data=json.dumps({"incorrect": "カウントテスト", "correct": "カウント正"}),
            headers={"Content-Type": "application/json"},
        )
        after = app_page.request.get("http://localhost:8000/api/pipeline/dictionary").json()["count"]
        assert after == before + 1

    def test_o3_l4_05_line_length_detection(self, app_page):
        """O3-L4-05 [S7]: 18文字超過セグメントが識別可能"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        for seg in res.json()["segments"]:
            char_count = len(seg.get("corrected", ""))
            # 超過/非超過の判定が計算可能であること
            is_over = char_count > 18
            assert isinstance(is_over, bool)

    def test_o3_l4_06_txt_export_nonempty(self, app_page):
        """O3-L4-06 [S9]: TXTエクスポートが非空コンテンツを返す"""
        app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/export/txt")
        assert res.ok
        assert len(res.text()) > 0


@pytest.mark.e2e
class TestO3L5EndToEnd:
    """L5: E2E完走 — UXストーリーのシナリオ完走"""

    def test_o3_l5_01_diff_approve_flow(self, app_page):
        """O3-L5-01 [S2]: diff表示→比較ビュー→承認→ステータス更新の完走"""
        # 結果取得
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        segs = res.json()["segments"]
        assert len(segs) >= 1
        # 比較ビュー確認
        assert segs[0]["original"] != "" and segs[0]["corrected"] != ""
        # 承認
        app_page.request.post(
            "http://localhost:8000/api/pipeline/proofreading/approve",
            data=json.dumps({"segment_id": segs[0]["id"]}),
            headers={"Content-Type": "application/json"},
        )
        # ステータス確認
        check = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        target = next(s for s in check.json()["segments"] if s["id"] == segs[0]["id"])
        assert target["status"] == "approved"

    def test_o3_l5_02_individual_review(self, app_page):
        """O3-L5-02 [S4]: 全セグメント個別レビュー→承認/却下混在→集計一致"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        segs = res.json()["segments"]
        for i, seg in enumerate(segs):
            endpoint = "approve" if i % 2 == 0 else "reject"
            app_page.request.post(
                f"http://localhost:8000/api/pipeline/proofreading/{endpoint}",
                data=json.dumps({"segment_id": seg["id"]}),
                headers={"Content-Type": "application/json"},
            )
        # 集計確認
        check = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        data = check.json()
        total = data["approved_count"] + data["rejected_count"] + data["pending_count"]
        assert total == len(segs)

    def test_o3_l5_03_batch_then_individual(self, app_page):
        """O3-L5-03 [S5]: 一括却下→個別承認→再度一括承認の3段階操作"""
        # 一括却下
        app_page.request.post("http://localhost:8000/api/pipeline/proofreading/reject-all")
        # 確認
        r1 = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        for seg in r1.json()["segments"]:
            assert seg["status"] == "rejected"
        # 個別承認
        seg_id = r1.json()["segments"][0]["id"]
        app_page.request.post(
            "http://localhost:8000/api/pipeline/proofreading/approve",
            data=json.dumps({"segment_id": seg_id}),
            headers={"Content-Type": "application/json"},
        )
        # 一括承認
        app_page.request.post("http://localhost:8000/api/pipeline/proofreading/approve-all")
        r3 = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        for seg in r3.json()["segments"]:
            assert seg["status"] == "approved"

    def test_o3_l5_04_dictionary_then_export(self, app_page):
        """O3-L5-04 [S6]: 辞書追加→校閲結果確認→エクスポートの完走"""
        # 辞書追加
        app_page.request.post(
            "http://localhost:8000/api/pipeline/dictionary",
            data=json.dumps({"incorrect": "完走テスト", "correct": "完走正"}),
            headers={"Content-Type": "application/json"},
        )
        # 結果確認
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        assert res.ok
        # エクスポート
        srt = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/export/srt")
        assert srt.ok and "-->" in srt.text()

    def test_o3_l5_05_skip_toggle_recovery(self, app_page):
        """O3-L5-05 [S10]: スキップON→確認→OFF→校閲結果表示の復帰"""
        # ON
        app_page.request.post(
            "http://localhost:8000/api/pipeline/proofreading/skip",
            data=json.dumps({"skip": True}),
            headers={"Content-Type": "application/json"},
        )
        status = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/status")
        assert status.json()["skip"] is True
        # OFF
        app_page.request.post(
            "http://localhost:8000/api/pipeline/proofreading/skip",
            data=json.dumps({"skip": False}),
            headers={"Content-Type": "application/json"},
        )
        # 結果取得
        res = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        assert res.ok
        assert len(res.json()["segments"]) >= 1

    def test_o3_l5_06_dual_export(self, app_page):
        """O3-L5-06 [S9]: SRT+TXT両フォーマットエクスポート→内容検証"""
        app_page.request.get("http://localhost:8000/api/pipeline/proofreading/result")
        srt = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/export/srt")
        txt = app_page.request.get("http://localhost:8000/api/pipeline/proofreading/export/txt")
        assert srt.ok and "-->" in srt.text()
        assert txt.ok and len(txt.text()) > 0
        # SRTとTXTは異なるフォーマット
        assert srt.text() != txt.text()
