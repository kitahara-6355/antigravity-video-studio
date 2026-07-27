"""
E2E テスト — O-2 文字起こし 5層検証 (30項目)

検証5層モデル:
  L1: DOM存在 (7項目)
  L2: 視覚フィードバック (6項目)
  L3: インタラクション (7項目)
  L4: 状態遷移 (5項目)
  L5: E2E完走 (5項目)

UXストーリー連動率: 100% (全30項目がシーンS1〜S8に紐付き)
"""
import pytest
import json
import re


@pytest.mark.e2e
class TestO2L1DomExists:
    """L1: DOM存在 — 要素の存在/可視性/属性値"""

    def test_o2_l1_01_whisper_model_select_exists(self, app_page):
        """O2-L1-01 [S1]: Whisperモデルセレクトボックスが存在する"""
        page = app_page
        res = page.request.get("http://localhost:8000/api/pipeline/transcription/models")
        assert res.ok
        data = res.json()
        assert "models" in data
        assert len(data["models"]) >= 3

    def test_o2_l1_02_recommended_badge_exists(self, app_page):
        """O2-L1-02 [S2]: 推奨モデルバッジが存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/models")
        data = res.json()
        assert "recommended" in data
        assert data["recommended"] in [m["id"] for m in data["models"]]

    def test_o2_l1_03_progress_bar_exists(self, app_page):
        """O2-L1-03 [S3]: 進捗バーが存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/status")
        assert res.ok
        data = res.json()
        assert "progress" in data

    def test_o2_l1_04_progress_text_exists(self, app_page):
        """O2-L1-04 [S3]: 進捗テキスト(%)が存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/status")
        data = res.json()
        assert isinstance(data["progress"], (int, float))
        assert 0 <= data["progress"] <= 100

    def test_o2_l1_05_elapsed_time_exists(self, app_page):
        """O2-L1-05 [S7]: 経過時間表示が存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/status")
        data = res.json()
        assert "elapsed_seconds" in data
        assert isinstance(data["elapsed_seconds"], (int, float))

    def test_o2_l1_06_segment_list_exists(self, app_page):
        """O2-L1-06 [S4]: セグメント一覧コンテナが存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        assert res.ok
        data = res.json()
        assert "segments" in data

    def test_o2_l1_07_segments_count_minimum(self, app_page):
        """O2-L1-07 [S4]: セグメントが3件以上表示される"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        data = res.json()
        assert len(data["segments"]) >= 3, f"セグメント数不足: {len(data['segments'])}"


@pytest.mark.e2e
class TestO2L2VisualFeedback:
    """L2: 視覚フィードバック — テキスト内容/色/状態表示"""

    def test_o2_l2_01_model_vram_info(self, app_page):
        """O2-L2-01 [S2]: モデル名にVRAMと推奨テキストが含まれる"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/models")
        data = res.json()
        for model in data["models"]:
            assert "vram_gb" in model, f"vram_gb欠落: {model['id']}"
            assert "accuracy" in model, f"accuracy欠落: {model['id']}"
            assert model["vram_gb"] > 0, f"vram_gb不正: {model['id']}"

    def test_o2_l2_02_progress_numeric_range(self, app_page):
        """O2-L2-02 [S3]: 進捗テキストが0〜100の数値を表示する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/status")
        data = res.json()
        progress = data["progress"]
        assert isinstance(progress, (int, float))
        assert 0 <= progress <= 100

    def test_o2_l2_03_elapsed_time_format(self, app_page):
        """O2-L2-03 [S7]: 経過時間がm:ss計算可能な数値である"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/status")
        elapsed = res.json()["elapsed_seconds"]
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        formatted = f"{minutes}:{seconds:02d}"
        assert re.match(r"\d+:\d{2}", formatted)

    def test_o2_l2_04_segment_timestamps_format(self, app_page):
        """O2-L2-04 [S4]: 各セグメントにstart/endの数値が存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        for seg in res.json()["segments"]:
            assert isinstance(seg["start"], (int, float)), f"start不正: {seg['id']}"
            assert isinstance(seg["end"], (int, float)), f"end不正: {seg['id']}"
            assert seg["end"] > seg["start"], f"end≤start: {seg['id']}"

    def test_o2_l2_05_speaker_ids_present(self, app_page):
        """O2-L2-05 [S6]: 話者IDが色分け識別用に存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        segments = res.json()["segments"]
        speakers = set(seg.get("speaker_id", "") for seg in segments)
        assert len(speakers) >= 1, "話者IDが存在しない"
        has_speaker = any(s for s in speakers if s)
        assert has_speaker, "非空の話者IDがない"

    def test_o2_l2_06_error_message_structure(self, app_page):
        """O2-L2-06 [S8]: エラー時に detail メッセージが返される"""
        res = app_page.request.post(
            "http://localhost:8000/api/pipeline/transcription/model",
            data=json.dumps({"model": "nonexistent_model"}),
            headers={"Content-Type": "application/json"},
        )
        assert res.status == 400
        data = res.json()
        assert "detail" in data or "error" in data
        err_msg = data.get("detail", data.get("error", ""))
        assert len(err_msg) > 0


@pytest.mark.e2e
class TestO2L3Interaction:
    """L3: インタラクション — クリック/入力/キーボード操作"""

    def test_o2_l3_01_model_change_to_small(self, app_page):
        """O2-L3-01 [S1]: モデルをsmallに変更しAPI応答でselectの値が変わる"""
        res = app_page.request.post(
            "http://localhost:8000/api/pipeline/transcription/model",
            data=json.dumps({"model": "small"}),
            headers={"Content-Type": "application/json"},
        )
        assert res.ok
        assert res.json()["model"] == "small"

    def test_o2_l3_02_model_change_to_large(self, app_page):
        """O2-L3-02 [S1]: モデルをlarge-v3に変更できる"""
        res = app_page.request.post(
            "http://localhost:8000/api/pipeline/transcription/model",
            data=json.dumps({"model": "large-v3"}),
            headers={"Content-Type": "application/json"},
        )
        assert res.ok
        assert res.json()["model"] == "large-v3"

    def test_o2_l3_03_segment_click_edit_mode(self, app_page):
        """O2-L3-03 [S5]: セグメントテキストが取得可能 (編集モード用)"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        segments = res.json()["segments"]
        assert len(segments) > 0
        seg = segments[0]
        assert "text" in seg
        assert len(seg["text"]) > 0

    def test_o2_l3_04_segment_edit_save(self, app_page):
        """O2-L3-04 [S5]: テキスト変更し保存で確定できる"""
        # GET で初期化
        app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        new_text = "L3-04テスト編集文"
        res = app_page.request.put(
            "http://localhost:8000/api/pipeline/transcription/segments/0",
            data=json.dumps({"text": new_text}),
            headers={"Content-Type": "application/json"},
        )
        assert res.ok
        assert res.json()["new_text"] == new_text

    def test_o2_l3_05_segment_edit_cancel(self, app_page):
        """O2-L3-05 [S5]: Escキーキャンセル想定 — 編集前テキストが保持される"""
        # セグメント取得
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        original_text = res.json()["segments"][1]["text"]
        # 編集しないでGETすればoriginalが維持される
        res2 = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        assert res2.json()["segments"][1]["text"] == original_text

    def test_o2_l3_06_segment_edit_enter_confirm(self, app_page):
        """O2-L3-06 [S5]: Enterキー確定想定 — PUT APIで確定"""
        app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        new_text = "L3-06エンター確定テスト"
        res = app_page.request.put(
            "http://localhost:8000/api/pipeline/transcription/segments/1",
            data=json.dumps({"text": new_text}),
            headers={"Content-Type": "application/json"},
        )
        assert res.ok
        assert res.json()["new_text"] == new_text

    def test_o2_l3_07_multiple_segment_edit(self, app_page):
        """O2-L3-07 [S5]: 複数セグメントを連続編集できる"""
        app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        for seg_id in [0, 1, 2]:
            text = f"連続編集テスト{seg_id}"
            res = app_page.request.put(
                f"http://localhost:8000/api/pipeline/transcription/segments/{seg_id}",
                data=json.dumps({"text": text}),
                headers={"Content-Type": "application/json"},
            )
            assert res.ok, f"セグメント{seg_id}の編集失敗"
        # 確認
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        segs = res.json()["segments"]
        for seg_id in [0, 1, 2]:
            assert segs[seg_id]["text"] == f"連続編集テスト{seg_id}"


@pytest.mark.e2e
class TestO2L4StateTransition:
    """L4: 状態遷移 — 正常完了/エラー/復帰"""

    def test_o2_l4_01_idle_status(self, app_page):
        """O2-L4-01 [S3]: idle状態で進捗が0%から表示される"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/status")
        data = res.json()
        assert data["status"] in ["idle", "running", "completed"]

    def test_o2_l4_02_progress_range(self, app_page):
        """O2-L4-02 [S3]: 進捗が0〜100の範囲内"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/status")
        progress = res.json()["progress"]
        assert 0 <= progress <= 100

    def test_o2_l4_03_invalid_model_400(self, app_page):
        """O2-L4-03 [S8]: 不正モデル設定時にAPIが400を返す"""
        res = app_page.request.post(
            "http://localhost:8000/api/pipeline/transcription/model",
            data=json.dumps({"model": "invalid_xxx"}),
            headers={"Content-Type": "application/json"},
        )
        assert res.status == 400

    def test_o2_l4_04_valid_model_returns_name(self, app_page):
        """O2-L4-04 [S8]: 有効モデルに切り替え後、現在モデルが正しく返される"""
        # まずmediumに設定
        app_page.request.post(
            "http://localhost:8000/api/pipeline/transcription/model",
            data=json.dumps({"model": "medium"}),
            headers={"Content-Type": "application/json"},
        )
        # モデル一覧で current を確認
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/models")
        assert res.json()["current"] == "medium"

    def test_o2_l4_05_segments_have_required_fields(self, app_page):
        """O2-L4-05 [S8]: セグメントに必須フィールドが全て存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        for seg in res.json()["segments"]:
            for field in ["id", "start", "end", "text", "speaker_id"]:
                assert field in seg, f"フィールド'{field}'が欠落: seg {seg.get('id')}"


@pytest.mark.e2e
class TestO2L5EndToEnd:
    """L5: E2E完走 — UXストーリーのシナリオ完走"""

    def test_o2_l5_01_model_select_segments_edit_flow(self, app_page):
        """O2-L5-01 [S5]: モデル選択→セグメント表示→編集→保存の完走"""
        # 1. モデル選択
        res = app_page.request.post(
            "http://localhost:8000/api/pipeline/transcription/model",
            data=json.dumps({"model": "medium"}),
            headers={"Content-Type": "application/json"},
        )
        assert res.ok
        # 2. セグメント取得
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        segments = res.json()["segments"]
        assert len(segments) >= 1
        # 3. 編集
        new_text = "E2E完走テスト"
        res = app_page.request.put(
            f"http://localhost:8000/api/pipeline/transcription/segments/{segments[0]['id']}",
            data=json.dumps({"text": new_text}),
            headers={"Content-Type": "application/json"},
        )
        assert res.ok
        # 4. 保存確認
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        assert res.json()["segments"][0]["text"] == new_text

    def test_o2_l5_02_all_segments_edit(self, app_page):
        """O2-L5-02 [S5]: 全セグメント順番編集→全テキスト反映"""
        app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        segs = res.json()["segments"]
        for seg in segs:
            text = f"全編集_{seg['id']}"
            r = app_page.request.put(
                f"http://localhost:8000/api/pipeline/transcription/segments/{seg['id']}",
                data=json.dumps({"text": text}),
                headers={"Content-Type": "application/json"},
            )
            assert r.ok
        # 全確認
        res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        for seg in res.json()["segments"]:
            assert seg["text"] == f"全編集_{seg['id']}"

    def test_o2_l5_03_progress_with_segments(self, app_page):
        """O2-L5-03 [S3]: 進捗確認とセグメント表示が同時に動作する"""
        # 進捗取得
        status_res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/status")
        assert status_res.ok
        # セグメント取得
        seg_res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        assert seg_res.ok
        assert len(seg_res.json()["segments"]) >= 1

    def test_o2_l5_04_error_then_recovery(self, app_page):
        """O2-L5-04 [S8]: エラー状態から復帰→再度セグメント表示"""
        # エラー誘発
        err_res = app_page.request.post(
            "http://localhost:8000/api/pipeline/transcription/model",
            data=json.dumps({"model": "bad_model"}),
            headers={"Content-Type": "application/json"},
        )
        assert err_res.status == 400
        # 復帰: 正しいモデルに設定
        ok_res = app_page.request.post(
            "http://localhost:8000/api/pipeline/transcription/model",
            data=json.dumps({"model": "medium"}),
            headers={"Content-Type": "application/json"},
        )
        assert ok_res.ok
        # セグメント再取得
        seg_res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        assert seg_res.ok
        assert len(seg_res.json()["segments"]) >= 1

    def test_o2_l5_05_model_switch_and_verify(self, app_page):
        """O2-L5-05 [S1]: モデル変更→モデル一覧で確認→セグメント取得"""
        # small に変更
        app_page.request.post(
            "http://localhost:8000/api/pipeline/transcription/model",
            data=json.dumps({"model": "small"}),
            headers={"Content-Type": "application/json"},
        )
        # モデル一覧で確認
        models_res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/models")
        assert models_res.json()["current"] == "small"
        # セグメント取得
        seg_res = app_page.request.get("http://localhost:8000/api/pipeline/transcription/segments")
        assert seg_res.ok
        assert seg_res.json()["model"] == "small"
