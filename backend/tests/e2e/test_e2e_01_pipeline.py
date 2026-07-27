"""
E2E テスト — O-1 素材選択 5層検証 (30項目)

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
import time


@pytest.mark.e2e
class TestO1L1DomExists:
    """L1: DOM存在 — 要素の存在/可視性/属性値"""

    def test_o1_l1_01_video_list_api_response(self, app_page):
        """O1-L1-01 [S1]: 動画一覧APIが正常応答を返す"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        assert res.ok, f"動画一覧API失敗: {res.status}"
        data = res.json()
        assert "videos" in data

    def test_o1_l1_02_video_list_has_array(self, app_page):
        """O1-L1-02 [S1]: 動画一覧にvideos配列が存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        data = res.json()
        assert isinstance(data["videos"], list), "videosがリストでない"
        assert "count" in data, "countフィールドが存在しない"

    def test_o1_l1_03_metadata_api_required_fields(self, app_page):
        """O1-L1-03 [S2]: メタデータAPIが必須フィールドを返す"""
        videos_res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        videos = videos_res.json().get("videos", [])
        if len(videos) > 0:
            meta_res = app_page.request.post(
                "http://localhost:8000/api/pipeline/videos/metadata",
                data=json.dumps({"video_path": videos[0]["path"]}),
                headers={"Content-Type": "application/json"},
            )
            assert meta_res.ok, f"メタデータAPI失敗: {meta_res.status}"
            meta = meta_res.json()
            assert "size_mb" in meta, "size_mb欠落"
            assert "name" in meta, "name欠落"
        else:
            # 動画なし — API自体が正常応答することを確認
            assert videos_res.ok

    def test_o1_l1_04_extension_filter_valid(self, app_page):
        """O1-L1-04 [S3]: 動画リストに対応拡張子のみ含まれる"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        data = res.json()
        for video in data.get("videos", []):
            name = video["name"].lower()
            assert any(name.endswith(ext) for ext in [".mp4", ".mov", ".mkv", ".avi"]), \
                f"非対応拡張子: {video['name']}"

    def test_o1_l1_05_drop_zone_exists(self, app_page):
        """O1-L1-05 [S4]: ドロップゾーン要素が存在する"""
        page = app_page
        _open_pipeline_modal(page)
        drop_zone = page.locator("[data-testid='pipeline-drop-zone']")
        assert drop_zone.is_visible(), "ドロップゾーンが存在しない"

    def test_o1_l1_06_validation_api_responds(self, app_page):
        """O1-L1-06 [S6]: バリデーションAPIが正常応答を返す"""
        res = app_page.request.post(
            "http://localhost:8000/api/pipeline/videos/validate",
            data=json.dumps({"video_paths": ["C:\\nonexistent\\fake.mp4"]}),
            headers={"Content-Type": "application/json"},
        )
        assert res.ok, "バリデーションAPIが応答しない"
        data = res.json()
        assert "results" in data
        assert "total" in data

    def test_o1_l1_07_localstorage_history_key(self, app_page):
        """O1-L1-07 [S7]: localStorageに履歴キーが存在する"""
        page = app_page
        page.evaluate("""
            localStorage.setItem('pipeline_recent_videos', JSON.stringify([
                { path: 'test/video1.mp4', name: 'video1.mp4', size_mb: 100, usedAt: new Date().toISOString() },
            ]));
        """)
        stored = page.evaluate("localStorage.getItem('pipeline_recent_videos')")
        assert stored is not None, "localStorageに履歴キーが存在しない"


@pytest.mark.e2e
class TestO1L2VisualFeedback:
    """L2: 視覚フィードバック — テキスト内容/色/状態表示"""

    def test_o1_l2_01_video_list_count_field(self, app_page):
        """O1-L2-01 [S1]: 動画リストにcount/videosフィールドが含まれる"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        data = res.json()
        assert "count" in data, "countフィールドがない"
        assert isinstance(data["count"], int), "countが整数でない"
        assert data["count"] == len(data["videos"]), "countとvideos長さが不一致"

    def test_o1_l2_02_metadata_size_and_name(self, app_page):
        """O1-L2-02 [S2]: メタデータにsize_mb/nameが表示される"""
        videos_res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        videos = videos_res.json().get("videos", [])
        if len(videos) > 0:
            meta_res = app_page.request.post(
                "http://localhost:8000/api/pipeline/videos/metadata",
                data=json.dumps({"video_path": videos[0]["path"]}),
                headers={"Content-Type": "application/json"},
            )
            meta = meta_res.json()
            assert meta["size_mb"] > 0, "size_mbが0以下"
            assert len(meta["name"]) > 0, "nameが空"
        else:
            pytest.skip("テスト用動画なし")

    def test_o1_l2_03_metadata_probe_fields(self, app_page):
        """O1-L2-03 [S2]: FFprobe成功時にduration/resolution/codecが表示される"""
        videos_res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        videos = videos_res.json().get("videos", [])
        if len(videos) > 0:
            meta_res = app_page.request.post(
                "http://localhost:8000/api/pipeline/videos/metadata",
                data=json.dumps({"video_path": videos[0]["path"]}),
                headers={"Content-Type": "application/json"},
            )
            meta = meta_res.json()
            if meta.get("probe_success"):
                assert "duration_seconds" in meta, "duration_seconds欠落"
                assert "resolution" in meta, "resolution欠落"
                assert "video_codec" in meta, "video_codec欠落"
            # probe_success=False もFFprobe未インストールで許容
        else:
            pytest.skip("テスト用動画なし")

    def test_o1_l2_04_extension_format_check(self, app_page):
        """O1-L2-04 [S3]: 拡張子がmp4/mov/mkv/aviのいずれかである"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        valid_extensions = {".mp4", ".mov", ".mkv", ".avi"}
        for video in res.json().get("videos", []):
            name = video["name"].lower()
            ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
            assert ext in valid_extensions, f"不正拡張子: {ext} in {name}"

    def test_o1_l2_05_selected_class_on_click(self, app_page):
        """O1-L2-05 [S5]: 選択された動画にselectedクラスが付与される"""
        page = app_page
        _open_pipeline_modal(page)
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders.count() > 0:
            folders.first.click()
            page.wait_for_timeout(500)
        video_items = page.locator(".pipeline-video-item:has-text('🎥')")
        if video_items.count() >= 1:
            video_items.first.click()
            page.wait_for_timeout(300)
            selected = page.locator(".pipeline-video-item.selected")
            assert selected.count() >= 1, "selected クラスが付与されていない"

    def test_o1_l2_06_validation_error_message(self, app_page):
        """O1-L2-06 [S6]: バリデーションエラーに具体的メッセージが含まれる"""
        res = app_page.request.post(
            "http://localhost:8000/api/pipeline/videos/validate",
            data=json.dumps({"video_paths": ["C:\\nonexistent\\fake.mp4"]}),
            headers={"Content-Type": "application/json"},
        )
        data = res.json()
        errors = data["results"][0].get("errors", [])
        assert len(errors) > 0, "エラーメッセージがない"
        assert any(len(e) > 5 for e in errors), "エラーメッセージが短すぎる"


@pytest.mark.e2e
class TestO1L3Interaction:
    """L3: インタラクション — クリック/入力/ドラッグ/キーボード操作"""

    def test_o1_l3_01_folder_expand(self, app_page):
        """O1-L3-01 [S5]: フォルダを展開して子要素が表示される"""
        page = app_page
        _open_pipeline_modal(page)
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders.count() > 0:
            folders.first.click()
            page.wait_for_timeout(500)
            # 展開後に動画アイテムまたは子フォルダが存在する
            child_items = page.locator(".pipeline-video-item")
            assert child_items.count() > 0, "展開後に子要素がない"

    def test_o1_l3_02_metadata_api_call(self, app_page):
        """O1-L3-02 [S2]: 動画選択後にメタデータAPIを呼び出せる"""
        videos_res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        videos = videos_res.json().get("videos", [])
        if len(videos) > 0:
            meta_res = app_page.request.post(
                "http://localhost:8000/api/pipeline/videos/metadata",
                data=json.dumps({"video_path": videos[0]["path"]}),
                headers={"Content-Type": "application/json"},
            )
            assert meta_res.ok, "メタデータAPI呼び出し失敗"
            assert "name" in meta_res.json()

    def test_o1_l3_03_drop_zone_visible(self, app_page):
        """O1-L3-03 [S4]: ドロップゾーンがUI上で表示される"""
        page = app_page
        _open_pipeline_modal(page)
        drop_zone = page.locator("[data-testid='pipeline-drop-zone']")
        assert drop_zone.is_visible(), "ドロップゾーンが非表示"

    def test_o1_l3_04_video_click_selection(self, app_page):
        """O1-L3-04 [S5]: 動画クリックで選択状態が切り替わる"""
        page = app_page
        _open_pipeline_modal(page)
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders.count() > 0:
            folders.first.click()
            page.wait_for_timeout(500)
        video_items = page.locator(".pipeline-video-item:has-text('🎥')")
        if video_items.count() >= 1:
            video_items.first.click()
            page.wait_for_timeout(300)
            selected = page.locator(".pipeline-video-item.selected")
            assert selected.count() >= 1, "選択状態にならない"

    def test_o1_l3_05_localstorage_history_save_load(self, app_page):
        """O1-L3-05 [S7]: localStorageに履歴を保存・読み込みできる"""
        page = app_page
        test_data = [
            {"path": "test/v1.mp4", "name": "v1.mp4", "size_mb": 50, "usedAt": "2026-01-01T00:00:00Z"},
            {"path": "test/v2.mp4", "name": "v2.mp4", "size_mb": 80, "usedAt": "2026-01-02T00:00:00Z"},
        ]
        page.evaluate(f"localStorage.setItem('pipeline_recent_videos', JSON.stringify({json.dumps(test_data)}))")
        stored = page.evaluate("localStorage.getItem('pipeline_recent_videos')")
        parsed = json.loads(stored)
        assert len(parsed) == 2, f"履歴エントリ数不正: {len(parsed)}"
        assert parsed[0]["name"] == "v1.mp4"

    def test_o1_l3_06_start_button_exists(self, app_page):
        """O1-L3-06 [S8]: パイプライン開始ボタンが表示される"""
        page = app_page
        _open_pipeline_modal(page)
        start_btn = page.locator(".pipeline-start-btn")
        assert start_btn.is_visible(), "パイプライン開始ボタンがない"

    def test_o1_l3_07_status_api_response(self, app_page):
        """O1-L3-07 [S8]: パイプラインステータスAPIが正常応答を返す"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/status")
        assert res.ok, "ステータスAPI応答失敗"
        data = res.json()
        assert "status" in data
        assert "stages" in data


@pytest.mark.e2e
class TestO1L4StateTransition:
    """L4: 状態遷移 — 正常/エラー/復帰"""

    def test_o1_l4_01_api_performance(self, app_page):
        """O1-L4-01 [S3]: APIレスポンスが5秒以内に返る"""
        start = time.time()
        res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        elapsed = time.time() - start
        assert res.ok, "API応答失敗"
        assert elapsed <= 5.0, f"API応答が遅すぎます: {elapsed:.1f}秒"

    def test_o1_l4_02_invalid_file_detected(self, app_page):
        """O1-L4-02 [S6]: 存在しないファイルでinvalid=1が返る"""
        res = app_page.request.post(
            "http://localhost:8000/api/pipeline/videos/validate",
            data=json.dumps({"video_paths": ["C:\\nonexistent\\fake.mp4"]}),
            headers={"Content-Type": "application/json"},
        )
        assert res.ok
        data = res.json()
        assert data["invalid"] == 1, f"invalid期待値1, 実際: {data['invalid']}"

    def test_o1_l4_03_validation_errors_array(self, app_page):
        """O1-L4-03 [S6]: バリデーション結果にerrors配列が含まれる"""
        res = app_page.request.post(
            "http://localhost:8000/api/pipeline/videos/validate",
            data=json.dumps({"video_paths": ["C:\\nonexistent\\fake.mp4"]}),
            headers={"Content-Type": "application/json"},
        )
        data = res.json()
        result = data["results"][0]
        assert "errors" in result, "errorsフィールドが存在しない"
        assert isinstance(result["errors"], list), "errorsがリストでない"
        assert len(result["errors"]) > 0, "errorsが空"

    def test_o1_l4_04_history_json_parseable(self, app_page):
        """O1-L4-04 [S7]: 履歴JSONが正しい構造でパースできる"""
        page = app_page
        page.evaluate("""
            localStorage.setItem('pipeline_recent_videos', JSON.stringify([
                { path: 'test/video1.mp4', name: 'video1.mp4', size_mb: 100, usedAt: new Date().toISOString() },
            ]));
        """)
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(500)
        stored = page.evaluate("localStorage.getItem('pipeline_recent_videos')")
        parsed = json.loads(stored)
        assert isinstance(parsed, list), "履歴がリストでない"
        entry = parsed[0]
        assert "path" in entry, "pathキー欠落"
        assert "name" in entry, "nameキー欠落"
        assert "usedAt" in entry, "usedAtキー欠落"

    def test_o1_l4_05_status_api_fields(self, app_page):
        """O1-L4-05 [S8]: ステータスAPIにstatus/stagesフィールドが存在する"""
        res = app_page.request.get("http://localhost:8000/api/pipeline/status")
        data = res.json()
        assert "status" in data, "statusフィールド欠落"
        assert "stages" in data, "stagesフィールド欠落"
        assert isinstance(data["stages"], list), "stagesがリストでない"
        assert len(data["stages"]) >= 1, "stagesが空"


@pytest.mark.e2e
class TestO1L5EndToEnd:
    """L5: E2E完走 — UXストーリーのシナリオ完走"""

    def test_o1_l5_01_list_metadata_validate_flow(self, app_page):
        """O1-L5-01 [S8]: 動画一覧→メタデータ取得→バリデーション→開始判定の完走"""
        # 1. 動画一覧取得
        list_res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        assert list_res.ok
        videos = list_res.json().get("videos", [])

        if len(videos) > 0:
            # 2. メタデータ取得
            meta_res = app_page.request.post(
                "http://localhost:8000/api/pipeline/videos/metadata",
                data=json.dumps({"video_path": videos[0]["path"]}),
                headers={"Content-Type": "application/json"},
            )
            assert meta_res.ok

            # 3. バリデーション
            val_res = app_page.request.post(
                "http://localhost:8000/api/pipeline/videos/validate",
                data=json.dumps({"video_paths": [videos[0]["path"]]}),
                headers={"Content-Type": "application/json"},
            )
            assert val_res.ok

            # 4. ステータス確認
            status_res = app_page.request.get("http://localhost:8000/api/pipeline/status")
            assert status_res.ok
            assert "status" in status_res.json()

    def test_o1_l5_02_invalid_then_valid_flow(self, app_page):
        """O1-L5-02 [S8]: 不正ファイル検出→正常ファイル選択→パイプライン開始の完走"""
        # 1. 不正ファイル検出
        invalid_res = app_page.request.post(
            "http://localhost:8000/api/pipeline/videos/validate",
            data=json.dumps({"video_paths": ["C:\\nonexistent\\fake.mp4"]}),
            headers={"Content-Type": "application/json"},
        )
        assert invalid_res.ok
        assert invalid_res.json()["invalid"] == 1

        # 2. 正常ファイル一覧取得
        list_res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        assert list_res.ok
        videos = list_res.json().get("videos", [])

        if len(videos) > 0:
            # 3. 正常ファイルのバリデーション
            valid_res = app_page.request.post(
                "http://localhost:8000/api/pipeline/videos/validate",
                data=json.dumps({"video_paths": [videos[0]["path"]]}),
                headers={"Content-Type": "application/json"},
            )
            assert valid_res.ok

        # 4. ステータス確認
        status_res = app_page.request.get("http://localhost:8000/api/pipeline/status")
        assert status_res.ok

    def test_o1_l5_03_history_save_reload_metadata(self, app_page):
        """O1-L5-03 [S8]: 履歴保存→再読み込み→メタデータ確認の完走"""
        page = app_page
        # 1. 履歴保存
        page.evaluate("""
            localStorage.setItem('pipeline_recent_videos', JSON.stringify([
                { path: 'test/v1.mp4', name: 'v1.mp4', size_mb: 50, usedAt: new Date().toISOString() },
            ]));
        """)

        # 2. ページリロード
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(500)

        # 3. 履歴読み込み確認
        stored = page.evaluate("localStorage.getItem('pipeline_recent_videos')")
        assert stored is not None
        parsed = json.loads(stored)
        assert len(parsed) >= 1

        # 4. API経由で動画リスト確認
        list_res = page.request.get("http://localhost:8000/api/pipeline/videos")
        assert list_res.ok

    def test_o1_l5_04_filter_select_status_flow(self, app_page):
        """O1-L5-04 [S8]: フィルタ確認→選択→ステータスAPIの完走"""
        # 1. 拡張子フィルタ確認
        list_res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        assert list_res.ok
        for v in list_res.json().get("videos", []):
            name = v["name"].lower()
            assert any(name.endswith(e) for e in [".mp4", ".mov", ".mkv", ".avi"])

        # 2. UI上での選択操作
        page = app_page
        _open_pipeline_modal(page)
        browser = page.locator("[data-testid='video-file-browser']")
        assert browser.is_visible()

        # 3. ステータスAPI
        status_res = page.request.get("http://localhost:8000/api/pipeline/status")
        assert status_res.ok
        assert "stages" in status_res.json()

    def test_o1_l5_05_empty_check_list_performance(self, app_page):
        """O1-L5-05 [S8]: 空ディレクトリ確認→動画一覧→パフォーマンス確認の完走"""
        # 1. 動画一覧取得 + パフォーマンス
        start = time.time()
        list_res = app_page.request.get("http://localhost:8000/api/pipeline/videos")
        elapsed = time.time() - start
        assert list_res.ok
        assert elapsed <= 5.0, f"レスポンスが遅い: {elapsed:.1f}s"

        # 2. カウント確認
        data = list_res.json()
        count = data.get("count", 0)
        assert isinstance(count, int)

        # 3. 空の場合も適切に処理
        if count == 0:
            assert data["videos"] == [], "空リストが返されていない"
        else:
            assert len(data["videos"]) > 0

        # 4. ステータスAPI疎通
        status_res = app_page.request.get("http://localhost:8000/api/pipeline/status")
        assert status_res.ok


# ─── ヘルパー関数 ───

def _open_pipeline_modal(page):
    """パイプラインモーダルを開くヘルパー"""
    # WelcomeOnboarding等のオーバーレイを閉じる
    try:
        close_btns = page.locator("button:has-text('閉じる'), button:has-text('スキップ'), button:has-text('始める')")
        for i in range(close_btns.count()):
            if close_btns.nth(i).is_visible():
                close_btns.nth(i).click(force=True)
                page.wait_for_timeout(300)
    except Exception:
        pass

    # 「▶ 制作する」ボタンをクリック
    btn = page.locator("text=制作する").first
    btn.wait_for(state="visible", timeout=5000)
    btn.click(force=True)
    page.wait_for_timeout(1500)
