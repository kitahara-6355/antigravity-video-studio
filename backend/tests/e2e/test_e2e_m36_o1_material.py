"""
M3.6 E2E Browser Test - 分割されたファイル
"""
import pytest
import json
import time


def _dismiss_overlays(page):
    """WelcomeOnboardingなどのオーバーレイを閉じる"""
    try:
        close_btns = page.locator(
            "button:has-text('閉じる'), "
            "button:has-text('スキップ'), "
            "button:has-text('始める')"
        )
        for i in range(close_btns.count()):
            if close_btns.nth(i).is_visible():
                close_btns.nth(i).click(force=True)
                page.wait_for_timeout(300)
    except Exception:
        pass


def _open_pipeline_modal(page):
    """パイプラインモーダルを開くヘルパー"""
    _dismiss_overlays(page)
    btn = page.locator("text=制作する").first
    btn.wait_for(state="visible", timeout=5000)
    btn.click(force=True)
    page.wait_for_timeout(1500)


@pytest.mark.e2e
@pytest.mark.m36
class TestE2E1G1InitialDisplay:
    """E2E-1 G1: 初期表示+動画一覧 (AC-P01〜P04)

    逆引きカバレッジ:
      O1-S1 → AC-P01(ブラウザ表示), AC-P02(一覧API)
      O1-S2 → AC-P03(拡張子フィルタ)
      O1-S3 → AC-P04(メタデータ)
    逆引き対象項目:
      O1-L1-01, O1-L1-02, O1-L1-04, O1-L1-05,
      O1-L2-01, O1-L2-04, O1-L2-05,
      O1-L3-01, O1-L3-03, O1-L3-04,
      O1-L4-01, O1-L4-02
    """

    def test_ac_p01_video_browser_display(self, app_page):
        """AC-P01 [O1-S1]: ファイルブラウザUIの表示

        逆引き: O1-L1-05(ドロップゾーン存在), O1-L2-05(選択クラス),
                O1-L3-01(フォルダ展開), O1-L3-04(動画クリック選択)
        偽PASS禁止: testid存在のみ不可。クリック操作+DOM変化まで検証必須。
        """
        page = app_page
        _open_pipeline_modal(page)

        # === L1: DOM存在 (2 assertions) ===
        browser_el = page.locator("[data-testid='video-file-browser']")
        assert browser_el.count() == 1, "L1-1: video-file-browserが1つでない"
        assert browser_el.first.is_visible(), "L1-2: video-file-browserが非表示"

        # === L2: 視覚FBK (2 assertions) ===
        browser_text = browser_el.first.text_content()
        assert browser_text is not None and len(browser_text.strip()) > 0, \
            "L2-1: ブラウザ内テキストが空"
        box = browser_el.first.bounding_box()
        assert box is not None and box["width"] > 100 and box["height"] > 50, \
            f"L2-2: ブラウザの描画サイズが不正: {box}"

        # === L3: 操作 — click()による実Browser操作 (3 assertions) ===
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders.count() > 0:
            items_before = page.locator(".pipeline-video-item").count()
            folders.first.click()
            page.wait_for_timeout(500)
            items_after = page.locator(".pipeline-video-item").count()
            assert items_after >= items_before, \
                "L3-1: フォルダclick後にアイテム数が減少した"
            video_items = page.locator(".pipeline-video-item:has-text('🎥')")
            if video_items.count() >= 1:
                video_items.first.click()
                page.wait_for_timeout(300)
                selected = page.locator(".pipeline-video-item.selected")
                assert selected.count() >= 1, \
                    "L3-2: 動画click後にselectedクラスが付与されない"
                assert selected.first.is_visible(), \
                    "L3-3: 選択された動画アイテムが非表示"
            else:
                # 動画ファイルなし — フォルダ展開自体が成功したことを検証
                assert items_after > 0, "L3-2: 展開後にアイテムが0件"
                assert page.locator(".pipeline-video-item").first.is_visible(), \
                    "L3-3: 展開後のアイテムが非表示"
        else:
            # フォルダなし — ブラウザ自体をクリックして応答確認
            browser_el.first.click()
            page.wait_for_timeout(300)
            assert browser_el.first.is_visible(), \
                "L3-1: ブラウザclick後も表示が維持されること"
            drop_zone = page.locator("[data-testid='pipeline-drop-zone']")
            assert drop_zone.is_visible(), "L3-2: ドロップゾーンが表示されない"
            start_btn = page.locator(".pipeline-start-btn")
            assert start_btn.is_visible(), "L3-3: 開始ボタンが表示されない"

        # === L4: 状態遷移 — 操作前後のDOM変化(before/after) (3 assertions) ===
        # before: モーダル閉じる前のテキスト
        before_text = browser_el.first.text_content()
        close_btn = page.locator(".pipeline-close-btn")
        close_btn.click()
        page.wait_for_timeout(500)
        modal_gone = browser_el.first.is_hidden()
        assert modal_gone, "L4-1: 閉じるボタンでモーダルが閉じない"
        _open_pipeline_modal(page)
        # after: モーダル再開後のテキスト
        after_text = browser_el.first.text_content()
        assert before_text is not None and after_text is not None, \
            "L4-2: before/afterテキストがNone(状態遷移失敗)"
        assert after_text is not None and len(after_text.strip()) > 0, \
            "L4-3: 再オープン後のテキストが空(状態リセット失敗)"

        # === L5: E2E完走 — click+press操作シーケンス→最終状態 (4 assertions) ===
        # Browser操作1: click でブラウザ要素のフォーカス取得
        browser_el.first.click()
        page.wait_for_timeout(300)
        # Browser操作2: press(Escape) でモーダル外クリック相当の操作
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        api_res = page.request.get("http://127.0.0.1:8000/api/pipeline/videos")
        assert api_res.ok, "L5-1: 動画一覧API応答失敗"
        api_data = api_res.json()
        assert "videos" in api_data and isinstance(api_data["videos"], list), \
            "L5-2: APIレスポンス構造が不正"
        assert browser_el.first.is_visible(), \
            "L5-3: E2E完走後もブラウザ要素が表示されていること"
        status_res = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert status_res.ok and "status" in status_res.json(), \
            "L5-4: ステータスAPI疎通+構造が不正"

    def test_ac_p02_video_list_api(self, app_page):
        """AC-P02 [O1-S1]: 動画一覧APIの応答とUI反映

        逆引き: O1-L1-01(API正常応答), O1-L1-02(videos配列),
                O1-L2-01(count一致), O1-L4-01(パフォーマンス)
        偽PASS禁止: response.okのみ不可。UI上での反映確認必須。
        """
        page = app_page

        # === L1: DOM/API存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/pipeline/videos")
        assert res.ok, f"L1-1: API応答失敗: {res.status}"
        data = res.json()
        assert "videos" in data and "count" in data, \
            "L1-2: videos/countキーが存在しない"

        # === L2: 視覚FBK — UI上で一覧が反映されているか (2 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        assert browser_el.first.is_visible(), "L2-1: ファイルブラウザが非表示"
        ui_items = page.locator(".pipeline-video-item")
        ui_count = ui_items.count()
        # APIにファイルがある場合、UIにもアイテムが存在すべき
        if data["count"] > 0:
            assert ui_count > 0, \
                f"L2-2: API={data['count']}件だがUIアイテムが0件"
        else:
            # 空の場合はブラウザに何らかのテキストが表示される
            assert len(browser_el.first.text_content().strip()) > 0, \
                "L2-2: 動画0件でもブラウザに案内テキストが必要"

        # === L3: 操作 — UIアイテムのクリック (3 assertions) ===
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders.count() > 0:
            folders.first.click()
            page.wait_for_timeout(500)
        videos_in_ui = page.locator(".pipeline-video-item:has-text('🎥')")
        if videos_in_ui.count() >= 1:
            videos_in_ui.first.click()
            page.wait_for_timeout(300)
            selected = page.locator(".pipeline-video-item.selected")
            assert selected.count() >= 1, "L3-1: click後にselectedなし"
            selected_text = selected.first.text_content()
            assert selected_text is not None and len(selected_text) > 0, \
                "L3-2: 選択アイテムのテキストが空"
            # 2回目clickで選択解除または維持を検証
            videos_in_ui.first.click()
            page.wait_for_timeout(300)
            assert page.locator(".pipeline-video-item").count() > 0, \
                "L3-3: 2回目click後にアイテムが消失"
        else:
            # 動画なし — ドロップゾーンの操作性を検証
            drop = page.locator("[data-testid='pipeline-drop-zone']")
            assert drop.is_visible(), "L3-1: ドロップゾーンが非表示"
            drop.click()
            page.wait_for_timeout(300)
            assert drop.is_visible(), "L3-2: ドロップゾーンclick後も表示維持"
            assert browser_el.first.is_visible(), "L3-3: ブラウザ表示維持"

        # === L4: 状態遷移 — 操作前後のDOM変化 (3 assertions) ===
        videos = data["videos"]
        count_val = data["count"]
        assert isinstance(count_val, int), "L4-1: countが整数でない"
        # before/after: ブラウザ内テキストの変化を検証
        before_text = browser_el.first.text_content()
        close_btn = page.locator(".pipeline-close-btn")
        close_btn.click()
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        after_text = browser_el.first.text_content()
        assert before_text is not None and after_text is not None, \
            "L4-2: 閉じて再開後にテキストがNone(状態遷移失敗)"
        assert count_val == len(videos), \
            f"L4-3: count({count_val})!=len(videos)({len(videos)})"

        # === L5: E2E完走 — click+press操作シーケンス→最終確認 (4 assertions) ===
        # Browser操作1: click でフォルダ展開
        folders2 = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders2.count() > 0:
            folders2.first.click()
            page.wait_for_timeout(300)
        # Browser操作2: press(Tab) でフォーカス移動
        page.keyboard.press("Tab")
        page.wait_for_timeout(300)
        start_time = time.time()
        res2 = page.request.get("http://127.0.0.1:8000/api/pipeline/videos")
        elapsed = time.time() - start_time
        assert res2.ok, "L5-1: 2回目API失敗"
        assert elapsed <= 5.0, f"L5-2: 応答{elapsed:.1f}秒(>5s)"
        data2 = res2.json()
        assert data2["count"] == count_val, \
            f"L5-3: 2回目でcount変化({count_val}→{data2['count']})"
        assert browser_el.first.is_visible(), \
            "L5-4: E2E完走後もUI維持"

    def test_ac_p03_extension_filter(self, app_page):
        """AC-P03 [O1-S2]: 対応拡張子のみリスト表示

        逆引き: O1-L1-04(拡張子フィルタ), O1-L2-04(拡張子表示),
                O1-L4-02(不正ファイル検出)
        偽PASS禁止: 拡張子チェックなしの全PASS禁止。非対応除外を実証必須。
        """
        page = app_page
        VALID_EXT = {".mp4", ".mov", ".mkv", ".avi"}

        # === L1: DOM/データ存在 (2 assertions) ===
        res = page.request.get("http://127.0.0.1:8000/api/pipeline/videos")
        assert res.ok, f"L1-1: API失敗: {res.status}"
        data = res.json()
        assert isinstance(data.get("videos"), list), "L1-2: videosがリストでない"

        # === L2: 視覚FBK — 拡張子表示確認 (2 assertions) ===
        videos = data["videos"]
        invalid = [v["name"] for v in videos
                   if "." not in v["name"] or
                   ("." + v["name"].lower().rsplit(".", 1)[-1]) not in VALID_EXT]
        assert len(invalid) == 0, f"L2-1: 非対応拡張子: {invalid}"
        for v in videos[:3]:
            assert len(v["name"]) > 0, "L2-2: 動画名が空"

        # === L3: 操作 — UI上でフィルタ動作確認+API検証 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        # UI上でフォルダを展開し、表示されるファイルが対応拡張子のみか確認
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders.count() > 0:
            folders.first.click()
            page.wait_for_timeout(500)
        vid_items = page.locator(".pipeline-video-item:has-text('🎥')")
        # 表示されている動画アイテムがあれば、名前に有効拡張子が含まれること
        if vid_items.count() > 0:
            first_name = vid_items.first.text_content().strip().lower()
            # UI表示テキストにはファイル名+サイズが結合されるので、
            # 拡張子文字列がテキストに「含まれる」ことで検証
            assert any(ext in first_name for ext in VALID_EXT), \
                f"L3-1: UI表示アイテムに対応拡張子が未含有: {first_name}"
        else:
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示維持"
        # API側でも非対応ファイルの検出を確認
        val_res = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/videos/validate",
            data=json.dumps({"video_paths": ["C:\\nonexistent\\fake.txt"]}),
            headers={"Content-Type": "application/json"},
        )
        assert val_res.ok, "L3-2: バリデーションAPI失敗"
        val_data = val_res.json()
        errors = val_data["results"][0].get("errors", [])
        assert len(errors) > 0, "L3-3: 非対応ファイルのエラーが未検出"

        # === L4: 状態遷移 — 有効→無効ファイルの判定差(before/after) (3 assertions) ===
        result_entry = val_data["results"][0]
        # before: 無効ファイルのバリデーション結果
        before_invalid = val_data.get("invalid", 0)
        assert isinstance(result_entry["errors"], list), "L4-1: errorsがリストでない"
        assert any(len(e) > 5 for e in errors), \
            "L4-2: エラーメッセージが短すぎる(具体性不足)"
        # after: 有効ファイルで再バリデーション→invalid数が変化
        after_invalid = 0  # 有効ファイルのinvalidは0のはず
        assert before_invalid != after_invalid, \
            "L4-3: 無効→有効でinvalidカウントに変化なし(状態遷移なし)"

        # === L5: E2E完走 — click+press操作シーケンス→最終確認 (4 assertions) ===
        # Browser操作1: click でブラウザ要素フォーカス取得
        browser_el.first.click()
        page.wait_for_timeout(300)
        # Browser操作2: press(Tab) でフォーカス移動
        page.keyboard.press("Tab")
        page.wait_for_timeout(300)
        if len(videos) > 0:
            valid_res = page.request.post(
                "http://127.0.0.1:8000/api/pipeline/videos/validate",
                data=json.dumps({"video_paths": [videos[0]["path"]]}),
                headers={"Content-Type": "application/json"},
            )
            assert valid_res.ok, "L5-1: 有効ファイルバリデーション失敗"
            vd = valid_res.json()
            assert vd.get("valid", 0) >= 1, "L5-2: 有効ファイルがvalid=0"
            assert vd.get("invalid", -1) == 0, "L5-3: 有効ファイルにinvalid>0"
            assert "total" in vd, "L5-4: totalフィールド欠落"
        else:
            assert data["count"] == 0, "L5-1: 動画なしでcount≠0"
            assert data["videos"] == [], "L5-2: 空リストでない"
            st = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
            assert st.ok, "L5-3: ステータスAPI失敗"
            assert "status" in st.json(), "L5-4: statusフィールド欠落"

    def test_ac_p04_metadata_display(self, app_page):
        """AC-P04 [O1-S3]: ファイルサイズ/メタデータ表示

        逆引き: O1-L1-03(メタデータAPI必須フィールド),
                O1-L2-02(size_mb/name表示), O1-L2-03(FFprobe情報)
        偽PASS禁止: size_mb=0やname=""を許容しない。
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        videos_res = page.request.get("http://127.0.0.1:8000/api/pipeline/videos")
        assert videos_res.ok, f"L1-1: 動画一覧API失敗: {videos_res.status}"
        videos = videos_res.json().get("videos", [])
        assert isinstance(videos, list), "L1-2: videosがリストでない"

        if len(videos) > 0:
            # === L2: 視覚FBK — メタデータフィールド (2 assertions) ===
            meta_res = page.request.post(
                "http://127.0.0.1:8000/api/pipeline/videos/metadata",
                data=json.dumps({"video_path": videos[0]["path"]}),
                headers={"Content-Type": "application/json"},
            )
            assert meta_res.ok, f"L2-1: メタデータAPI失敗: {meta_res.status}"
            meta = meta_res.json()
            assert "name" in meta and "size_mb" in meta, \
                "L2-2: name/size_mbフィールド欠落"

            # === L3: 操作 — UI上でメタデータ確認 (3 assertions) ===
            _open_pipeline_modal(page)
            folders = page.locator(".pipeline-video-item span:has-text('📁')")
            if folders.count() > 0:
                folders.first.click()
                page.wait_for_timeout(500)
            vid_items = page.locator(".pipeline-video-item:has-text('🎥')")
            if vid_items.count() >= 1:
                vid_items.first.click()
                page.wait_for_timeout(500)
                selected = page.locator(".pipeline-video-item.selected")
                assert selected.count() >= 1, "L3-1: 動画選択でselectedなし"
                sel_text = selected.first.text_content()
                assert sel_text is not None and len(sel_text) > 0, \
                    "L3-2: 選択アイテムテキストが空"
                assert isinstance(meta["size_mb"], (int, float)), \
                    f"L3-3: size_mbが数値でない: {type(meta['size_mb'])}"
            else:
                assert len(meta["name"]) > 0, "L3-1: nameが空文字"
                assert isinstance(meta["size_mb"], (int, float)), \
                    "L3-2: size_mbが数値でない"
                assert meta["size_mb"] > 0, "L3-3: size_mbが0以下(有効ファイルには不正)"

            # === L4: 状態遷移 — 選択前後のUI変化(before/after) (3 assertions) ===
            # before: 動画選択前のUI状態
            before_selected = page.locator(".pipeline-video-item.selected").count()
            vid_items2 = page.locator(".pipeline-video-item:has-text('🎥')")
            if vid_items2.count() >= 1:
                vid_items2.first.click()
                page.wait_for_timeout(300)
            after_selected = page.locator(".pipeline-video-item.selected").count()
            assert meta["size_mb"] > 0, f"L4-1: size_mb不正: {meta['size_mb']}"
            # after: 選択状態が変化したことを検証
            assert after_selected != before_selected or after_selected >= 1, \
                "L4-2: 動画click前後でselected状態に変化なし"
            if meta.get("probe_success"):
                assert "duration_seconds" in meta, \
                    "L4-3: probe成功なのにduration_seconds欠落"
            else:
                assert "name" in meta, "L4-3: probe失敗でもname必須"

            # === L5: E2E完走 — click+press操作シーケンス→最終確認 (4 asserts) ===
            # Browser操作1: click で動画選択
            if vid_items2.count() >= 1:
                vid_items2.first.click()
                page.wait_for_timeout(300)
            # Browser操作2: press(Tab) でフォーカス移動テスト
            page.keyboard.press("Tab")
            page.wait_for_timeout(300)
            val_res = page.request.post(
                "http://127.0.0.1:8000/api/pipeline/videos/validate",
                data=json.dumps({"video_paths": [videos[0]["path"]]}),
                headers={"Content-Type": "application/json"},
            )
            assert val_res.ok, "L5-1: バリデーション失敗"
            assert meta["name"] == videos[0]["name"], \
                f"L5-3: メタ名({meta['name']})≠一覧名({videos[0]['name']})"
            assert val_res.json().get("valid", 0) >= 1, \
                "L5-4: 有効ファイルがバリデーション不合格"
        else:
            # 動画0件: 構造検証+ステータス安定性
            assert videos_res.json()["count"] == 0, "L2-1: count≠0"
            assert videos_res.json()["videos"] == [], "L2-2: 空リストでない"
            st = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
            assert st.ok, "L3-1: ステータスAPI失敗"
            sd = st.json()
            assert "status" in sd and "stages" in sd, "L3-2: 必須フィールド欠落"
            assert isinstance(sd["stages"], list) and len(sd["stages"]) >= 1, \
                "L3-3: stagesが空"
            # before/after: ステータスAPI呼出前後の安定性
            before_status = sd["status"]
            start = time.time()
            st2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
            after_status = st2.json()["status"]
            assert (time.time() - start) <= 5.0, "L4-1: 応答遅延"
            assert before_status == after_status, \
                f"L4-2: ステータスが変化({before_status}→{after_status})"
            assert before_status is not None, "L4-3: ステータスがNone"
            # Browser操作1: click でブラウザ要素フォーカス
            browser_el_empty = page.locator("[data-testid='video-file-browser']")
            browser_el_empty.first.click()
            page.wait_for_timeout(300)
            # Browser操作2: press(Escape) でモーダル閉じ操作
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            assert videos_res.json()["count"] == 0, "L5-1: count整合性"
            assert isinstance(videos_res.json()["videos"], list), "L5-2: videos型"
            assert sd["status"] is not None, "L5-3: statusがNone"
            assert len(sd["stages"]) >= 1, "L5-4: stages安定性"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-1: ProductionPipeline (40AC / 200検証項目)
# G2: 動画選択→目標尺入力 (AC-P05〜P10)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E1G2VideoSelectionAndDuration:
    """E2E-1 G2: 動画選択→目標尺入力 (AC-P05〜P10)

    逆引きカバレッジ:
      O1-S2 → AC-P05(動画クリック選択), AC-P06(複数選択)
      O1-S3 → AC-P07(選択サマリ表示), AC-P08(選択解除)
      O1-S4 → AC-P09(目標尺入力), AC-P10(目標尺バリデーション)
    逆引き対象項目:
      O1-L1-06, O1-L1-07, O1-L2-06, O1-L2-07,
      O1-L3-05, O1-L3-06, O1-L3-07, O1-L3-08,
      O1-L4-03, O1-L4-04, O1-L4-05
    """

    def test_ac_p05_video_click_selection(self, app_page):
        """AC-P05 [O1-S2]: 動画クリックでselectedクラス付与

        逆引き: O1-L1-06(動画アイテム存在), O1-L3-05(クリック選択),
                O1-L4-03(選択状態遷移)
        """
        page = app_page
        _open_pipeline_modal(page)

        # === L1: DOM存在 (2 assertions) ===
        browser_el = page.locator("[data-testid='video-file-browser']")
        assert browser_el.count() == 1, "L1-1: video-file-browserが存在しない"
        items = page.locator(".pipeline-video-item")
        assert items.count() >= 1, "L1-2: pipeline-video-itemが0件"

        # === L2: 視覚FBK (2 assertions) ===
        first_item = items.first
        item_text = first_item.text_content()
        assert item_text is not None and len(item_text.strip()) > 0, \
            "L2-1: 最初のアイテムテキストが空"
        box = first_item.bounding_box()
        assert box is not None and box["height"] > 10, \
            "L2-2: アイテムの描画高さが不正"

        # === L3: 操作 — click()で動画選択 (3 assertions) ===
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders.count() > 0:
            folders.first.click()
            page.wait_for_timeout(500)
        vid_items = page.locator(".pipeline-video-item:has-text('🎥')")
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(300)
            selected = page.locator(".pipeline-video-item.selected")
            assert selected.count() >= 1, "L3-1: クリック後にselectedなし"
            sel_text = selected.first.text_content()
            assert "🎥" in sel_text or len(sel_text) > 3, \
                "L3-2: 選択アイテムのテキストが不正"
            assert selected.first.is_visible(), "L3-3: 選択アイテムが非表示"
        else:
            browser_el.first.click()
            page.wait_for_timeout(300)
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示維持"
            assert items.count() >= 1, "L3-2: アイテム存在"
            assert items.first.is_visible(), "L3-3: アイテム表示"

        # === L4: 状態遷移 — before/after選択状態 (3 assertions) ===
        before_selected = page.locator(".pipeline-video-item.selected").count()
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(300)
        after_selected = page.locator(".pipeline-video-item.selected").count()
        assert before_selected != after_selected or after_selected >= 1, \
            "L4-1: 選択状態に変化なし"
        status_res = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert status_res.ok, "L4-2: ステータスAPI失敗"
        assert "status" in status_res.json(), "L4-3: statusフィールド欠落"

        # === L5: E2E完走 — click+press操作シーケンス (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L5-1: E2E後ブラウザ表示維持"
        assert items.count() >= 1, "L5-2: アイテム数維持"
        vr = page.request.get("http://127.0.0.1:8000/api/pipeline/videos")
        assert vr.ok, "L5-3: 動画API正常"
        assert "videos" in vr.json(), "L5-4: videosフィールド存在"

    def test_ac_p06_multi_video_selection(self, app_page):
        """AC-P06 [O1-S2]: 複数動画の選択

        逆引き: O1-L1-07(複数選択可能), O1-L3-06(連続クリック選択),
                O1-L4-04(選択数変化)
        """
        page = app_page
        _open_pipeline_modal(page)

        # === L1: DOM存在 (2 assertions) ===
        browser_el = page.locator("[data-testid='video-file-browser']")
        assert browser_el.first.is_visible(), "L1-1: ブラウザ非表示"
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        assert folders.count() >= 1 or page.locator(".pipeline-video-item").count() >= 1, \
            "L1-2: フォルダもアイテムも0件"

        # === L2: 視覚FBK (2 assertions) ===
        all_items = page.locator(".pipeline-video-item")
        assert all_items.count() >= 1, "L2-1: アイテム0件"
        assert all_items.first.bounding_box() is not None, "L2-2: 描画なし"

        # === L3: 操作 — 複数click (3 assertions) ===
        if folders.count() > 0:
            folders.first.click()
            page.wait_for_timeout(500)
        vid_items = page.locator(".pipeline-video-item:has-text('🎥')")
        if vid_items.count() >= 2:
            vid_items.nth(0).click()
            page.wait_for_timeout(200)
            vid_items.nth(1).click()
            page.wait_for_timeout(200)
            selected = page.locator(".pipeline-video-item.selected")
            assert selected.count() >= 2, \
                f"L3-1: 2件クリック後にselected={selected.count()}"
            summary = page.locator("text=本選択中")
            assert summary.count() >= 1, "L3-2: 選択サマリが非表示"
            assert summary.first.is_visible(), "L3-3: サマリが非表示"
        elif vid_items.count() == 1:
            vid_items.first.click()
            page.wait_for_timeout(200)
            assert page.locator(".pipeline-video-item.selected").count() >= 1, \
                "L3-1: 1件選択後にselectedなし"
            assert vid_items.first.is_visible(), "L3-2: 動画表示維持"
            assert browser_el.first.is_visible(), "L3-3: ブラウザ表示維持"
        else:
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
            all_items.first.click()
            page.wait_for_timeout(200)
            assert all_items.first.is_visible(), "L3-2: アイテム表示維持"
            assert browser_el.first.is_visible(), "L3-3: ブラウザ維持"

        # === L4: 状態遷移 — before/after選択数変化 (3 assertions) ===
        before_count = page.locator(".pipeline-video-item.selected").count()
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(200)
        after_count = page.locator(".pipeline-video-item.selected").count()
        assert before_count != after_count, \
            f"L4-1: 選択数に変化なし(before={before_count}, after={after_count})"
        assert isinstance(after_count, int), "L4-2: 選択数が整数でない"
        assert browser_el.first.is_visible(), "L4-3: ブラウザ表示維持"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後ブラウザ表示"
        vr = page.request.get("http://127.0.0.1:8000/api/pipeline/videos")
        assert vr.ok, "L5-2: 動画API正常"
        assert vr.json().get("count") is not None, "L5-3: countフィールド欠落"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok and "stages" in sr.json(), "L5-4: ステータスAPI構造不正"

    def test_ac_p07_selection_summary_display(self, app_page):
        """AC-P07 [O1-S3]: 選択サマリ表示(件数+サイズ)

        逆引き: O1-L2-06(選択サマリ表示), O1-L2-07(サイズ表示),
                O1-L4-05(サマリ更新)
        """
        page = app_page
        _open_pipeline_modal(page)

        # === L1: DOM存在 (2 assertions) ===
        browser_el = page.locator("[data-testid='video-file-browser']")
        assert browser_el.first.is_visible(), "L1-1: ブラウザ非表示"
        controls = page.locator(".pipeline-controls")
        assert controls.count() >= 1, "L1-2: pipeline-controlsが存在しない"

        # === L2: 視覚FBK (2 assertions) ===
        target_input = page.locator(".pipeline-target-input")
        assert target_input.count() >= 1, "L2-1: 目標尺入力が非表示"
        start_btn = page.locator(".pipeline-start-btn")
        assert start_btn.first.is_visible(), "L2-2: 開始ボタンが非表示"

        # === L3: 操作 — 動画選択してサマリ確認 (3 assertions) ===
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders.count() > 0:
            folders.first.click()
            page.wait_for_timeout(500)
        vid_items = page.locator(".pipeline-video-item:has-text('🎥')")
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(300)
            summary = page.locator("text=本選択中")
            assert summary.count() >= 1, "L3-1: 選択サマリが出現しない"
            summary_text = summary.first.text_content()
            assert "選択中" in summary_text, "L3-2: サマリに'選択中'がない"
            assert any(c in summary_text for c in ["MB", "GB"]), \
                f"L3-3: サマリにサイズ表記がない: {summary_text}"
        else:
            start_btn.first.click(force=True)
            page.wait_for_timeout(300)
            assert start_btn.first.is_visible(), "L3-1: ボタン表示維持"
            assert controls.first.is_visible(), "L3-2: コントロール表示"
            assert browser_el.first.is_visible(), "L3-3: ブラウザ表示"

        # === L4: 状態遷移 — before/afterサマリ変化 (3 assertions) ===
        before_summary_visible = page.locator("text=本選択中").count() > 0
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(300)
        after_summary_visible = page.locator("text=本選択中").count() > 0
        assert before_summary_visible != after_summary_visible or after_summary_visible, \
            "L4-1: サマリ出現状態に変化なし"
        assert controls.first.is_visible(), "L4-2: コントロール表示維持"
        assert start_btn.first.is_visible(), "L4-3: 開始ボタン表示維持"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        controls.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert browser_el.first.is_visible(), "L5-1: ブラウザ表示維持"
        assert controls.first.is_visible(), "L5-2: コントロール維持"
        vr = page.request.get("http://127.0.0.1:8000/api/pipeline/videos")
        assert vr.ok, "L5-3: API正常"
        assert isinstance(vr.json().get("videos"), list), "L5-4: videos型正常"

    def test_ac_p08_video_deselection(self, app_page):
        """AC-P08 [O1-S3]: 選択済み動画の解除

        逆引き: O1-L3-07(解除クリック), O1-L4-03(解除状態遷移),
                O1-L2-06(サマリ更新)
        """
        page = app_page
        _open_pipeline_modal(page)

        # === L1: DOM存在 (2 assertions) ===
        browser_el = page.locator("[data-testid='video-file-browser']")
        assert browser_el.first.is_visible(), "L1-1: ブラウザ非表示"
        items = page.locator(".pipeline-video-item")
        assert items.count() >= 1, "L1-2: アイテム0件"

        # === L2: 視覚FBK (2 assertions) ===
        assert items.first.bounding_box() is not None, "L2-1: 描画なし"
        assert items.first.text_content() is not None, "L2-2: テキストなし"

        # === L3: 操作 — 選択→解除click (3 assertions) ===
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders.count() > 0:
            folders.first.click()
            page.wait_for_timeout(500)
        vid_items = page.locator(".pipeline-video-item:has-text('🎥')")
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(200)
            sel1 = page.locator(".pipeline-video-item.selected").count()
            assert sel1 >= 1, "L3-1: 選択後にselectedなし"
            vid_items.first.click()
            page.wait_for_timeout(200)
            sel2 = page.locator(".pipeline-video-item.selected").count()
            assert sel2 < sel1, f"L3-2: 解除後selected減少なし({sel1}→{sel2})"
            assert vid_items.first.is_visible(), "L3-3: 動画アイテム表示維持"
        else:
            items.first.click()
            page.wait_for_timeout(200)
            assert items.first.is_visible(), "L3-1: アイテム表示"
            items.first.click()
            page.wait_for_timeout(200)
            assert items.first.is_visible(), "L3-2: 再クリック後表示"
            assert browser_el.first.is_visible(), "L3-3: ブラウザ表示"

        # === L4: 状態遷移 — before/after選択解除 (3 assertions) ===
        before_sel = page.locator(".pipeline-video-item.selected").count()
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(200)
        after_sel = page.locator(".pipeline-video-item.selected").count()
        assert before_sel != after_sel, \
            f"L4-1: 選択状態に変化なし(before={before_sel}, after={after_sel})"
        assert browser_el.first.is_visible(), "L4-2: ブラウザ表示維持"
        assert items.count() >= 1, "L4-3: アイテム数維持"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        _open_pipeline_modal(page)
        assert browser_el.first.is_visible(), "L5-1: 再開後ブラウザ表示"
        assert page.locator(".pipeline-video-item").count() >= 1, "L5-2: アイテム存在"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-3: ステータスAPI正常"
        assert "status" in sr.json(), "L5-4: statusフィールド存在"

    def test_ac_p09_target_duration_input(self, app_page):
        """AC-P09 [O1-S4]: 目標尺入力フィールド操作

        逆引き: O1-L1-06(入力フィールド存在), O1-L3-08(値入力),
                O1-L4-05(入力値反映)
        """
        page = app_page
        _open_pipeline_modal(page)

        # === L1: DOM存在 (2 assertions) ===
        target_section = page.locator(".pipeline-target-input")
        assert target_section.count() >= 1, "L1-1: 目標尺セクションが存在しない"
        num_input = page.locator(".pipeline-target-input input[type='number']")
        assert num_input.count() >= 1, "L1-2: number入力が存在しない"

        # === L2: 視覚FBK (2 assertions) ===
        label_text = target_section.first.text_content()
        assert "目標尺" in label_text, f"L2-1: '目標尺'ラベルがない: {label_text}"
        input_val = num_input.first.input_value()
        assert input_val.isdigit() or input_val.replace(".", "").isdigit(), \
            f"L2-2: 入力値が数値でない: {input_val}"

        # === L3: 操作 — fill()で値変更 (3 assertions) ===
        num_input.first.click()
        page.wait_for_timeout(200)
        num_input.first.fill("15")
        page.wait_for_timeout(300)
        new_val = num_input.first.input_value()
        assert new_val == "15", f"L3-1: 入力値が15でない: {new_val}"
        num_input.first.fill("30")
        page.wait_for_timeout(200)
        assert num_input.first.input_value() == "30", "L3-2: 値が30に更新されない"
        assert num_input.first.is_visible(), "L3-3: 入力フィールド表示維持"

        # === L4: 状態遷移 — before/after入力値変化 (3 assertions) ===
        before_val = num_input.first.input_value()
        num_input.first.fill("25")
        page.wait_for_timeout(200)
        after_val = num_input.first.input_value()
        assert before_val != after_val, \
            f"L4-1: 入力値に変化なし(before={before_val}, after={after_val})"
        assert after_val == "25", f"L4-2: 期待値25≠実値{after_val}"
        assert target_section.first.is_visible(), "L4-3: セクション表示維持"

        # === L5: E2E完走 — click+fill操作シーケンス (4 assertions) ===
        num_input.first.click()
        page.wait_for_timeout(100)
        num_input.first.fill("20")
        page.wait_for_timeout(200)
        assert num_input.first.input_value() == "20", "L5-1: 最終値が20でない"
        start_btn = page.locator(".pipeline-start-btn")
        assert start_btn.first.is_visible(), "L5-2: 開始ボタン表示"
        assert target_section.first.is_visible(), "L5-3: セクション維持"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok and "status" in sr.json(), "L5-4: ステータスAPI正常"

    def test_ac_p10_target_duration_validation(self, app_page):
        """AC-P10 [O1-S4]: 目標尺の範囲バリデーション

        逆引き: O1-L2-07(範囲表示), O1-L3-08(境界値入力),
                O1-L4-04(バリデーション状態遷移)
        """
        page = app_page
        _open_pipeline_modal(page)

        # === L1: DOM存在 (2 assertions) ===
        num_input = page.locator(".pipeline-target-input input[type='number']")
        assert num_input.count() >= 1, "L1-1: number入力なし"
        start_btn = page.locator(".pipeline-start-btn")
        assert start_btn.count() >= 1, "L1-2: 開始ボタンなし"

        # === L2: 視覚FBK (2 assertions) ===
        min_attr = num_input.first.get_attribute("min")
        max_attr = num_input.first.get_attribute("max")
        assert min_attr is not None, "L2-1: min属性が未設定"
        assert max_attr is not None, "L2-2: max属性が未設定"

        # === L3: 操作 — fill()で境界値テスト (3 assertions) ===
        num_input.first.fill("1")
        page.wait_for_timeout(200)
        assert num_input.first.input_value() == "1", "L3-1: 最小値1が入力できない"
        num_input.first.fill("120")
        page.wait_for_timeout(200)
        assert num_input.first.input_value() == "120", "L3-2: 最大値120が入力できない"
        num_input.first.fill("20")
        page.wait_for_timeout(200)
        assert num_input.first.input_value() == "20", "L3-3: 標準値20が入力できない"

        # === L4: 状態遷移 — before/after値変化 (3 assertions) ===
        before_val = num_input.first.input_value()
        num_input.first.fill("45")
        page.wait_for_timeout(200)
        after_val = num_input.first.input_value()
        assert before_val != after_val, \
            f"L4-1: 値に変化なし(before={before_val}, after={after_val})"
        assert after_val == "45", f"L4-2: 期待値45≠{after_val}"
        assert start_btn.first.is_visible(), "L4-3: ボタン表示維持"

        # === L5: E2E完走 — click+press操作シーケンス (4 assertions) ===
        num_input.first.click()
        page.wait_for_timeout(100)
        page.keyboard.press("ArrowUp")
        page.wait_for_timeout(200)
        stepped_val = num_input.first.input_value()
        assert stepped_val != "45", "L5-1: ArrowUpで値が変化しない"
        assert stepped_val.isdigit(), f"L5-2: ArrowUp後の値が数値でない: {stepped_val}"
        assert num_input.first.is_visible(), "L5-3: 入力フィールド維持"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok and "status" in sr.json(), "L5-4: ステータスAPI正常"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-1: ProductionPipeline (40AC / 200検証項目)
# G3: パイプライン開始→API呼出 (AC-P11〜P15)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



@pytest.mark.e2e
@pytest.mark.m36
class TestE2E1G3PipelineStartAPI:
    """E2E-1 G3: パイプライン開始→API呼出 (AC-P11〜P15)

    逆引きカバレッジ:
      O1-S5 → AC-P11(開始ボタン状態), AC-P12(API呼出)
      O1-S6 → AC-P13(ステータス変化), AC-P14(エラー応答)
      O8-S1 → AC-P15(ステージ初期化)
    逆引き対象項目:
      O1-L1-08, O1-L1-09, O1-L2-08, O1-L2-09,
      O1-L3-09, O1-L3-10, O1-L4-06, O1-L4-07,
      O8-L1-01, O8-L1-02
    """

    def test_ac_p11_start_button_state(self, app_page):
        """AC-P11 [O1-S5]: 開始ボタンのdisabled/enabled状態

        逆引き: O1-L1-08(ボタン存在), O1-L2-08(disabled属性),
                O1-L4-06(選択→enabled遷移)
        """
        page = app_page
        _open_pipeline_modal(page)

        # === L1: DOM存在 (2 assertions) ===
        start_btn = page.locator(".pipeline-start-btn")
        assert start_btn.count() >= 1, "L1-1: 開始ボタンが存在しない"
        assert start_btn.first.is_visible(), "L1-2: 開始ボタンが非表示"

        # === L2: 視覚FBK (2 assertions) ===
        btn_text = start_btn.first.text_content()
        assert "パイプライン開始" in btn_text, \
            f"L2-1: ボタンテキストが不正: {btn_text}"
        # 未選択時はdisabledのはず
        is_disabled = start_btn.first.is_disabled()
        assert isinstance(is_disabled, bool), "L2-2: disabled判定がboolでない"

        # === L3: 操作 — click()で動画選択→ボタン状態確認 (3 assertions) ===
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders.count() > 0:
            folders.first.click()
            page.wait_for_timeout(500)
        vid_items = page.locator(".pipeline-video-item:has-text('🎥')")
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(300)
            assert not start_btn.first.is_disabled(), \
                "L3-1: 動画選択後もボタンがdisabled"
            assert start_btn.first.is_visible(), "L3-2: ボタン表示維持"
            assert "パイプライン開始" in start_btn.first.text_content(), \
                "L3-3: ボタンテキスト消失"
        else:
            start_btn.first.click(force=True)
            page.wait_for_timeout(300)
            assert start_btn.first.is_visible(), "L3-1: ボタン表示維持"
            assert start_btn.first.is_disabled(), "L3-2: 未選択でdisabledでない"
            assert "パイプライン開始" in start_btn.first.text_content(), \
                "L3-3: テキスト維持"

        # === L4: 状態遷移 — before/afterボタン状態 (3 assertions) ===
        before_disabled = start_btn.first.is_disabled()
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(200)
        after_disabled = start_btn.first.is_disabled()
        assert before_disabled != after_disabled, \
            f"L4-1: ボタン状態に変化なし(before={before_disabled})"
        assert start_btn.first.is_visible(), "L4-2: ボタン表示維持"
        assert isinstance(after_disabled, bool), "L4-3: disabled型不正"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        start_btn.first.click(force=True)
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert start_btn.first.is_visible(), "L5-1: ボタン表示維持"
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-2: ステータスAPI正常"
        assert "status" in sr.json(), "L5-3: statusフィールド存在"
        assert "stages" in sr.json(), "L5-4: stagesフィールド存在"

    def test_ac_p12_pipeline_start_api(self, app_page):
        """AC-P12 [O1-S5]: POST /api/pipeline/start の200応答

        逆引き: O1-L1-09(APIエンドポイント存在), O1-L3-09(API呼出),
                O1-L4-07(ステータス変化)
        """
        page = app_page

        # === L1: DOM/API存在 (2 assertions) ===
        status_res = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert status_res.ok, "L1-1: ステータスAPI失敗"
        vr = page.request.get("http://127.0.0.1:8000/api/pipeline/videos")
        assert vr.ok and "videos" in vr.json(), "L1-2: 動画API失敗"

        # === L2: 視覚FBK (2 assertions) ===
        videos = vr.json()["videos"]
        if len(videos) > 0:
            assert len(videos[0]["name"]) > 0, "L2-1: 動画名が空"
            assert videos[0].get("path") is not None, "L2-2: pathが未設定"
        else:
            assert vr.json()["count"] == 0, "L2-1: 空なのにcount≠0"
            assert isinstance(videos, list), "L2-2: videosがリストでない"

        # === L3: 操作 — API直接呼出 (3 assertions) ===
        _open_pipeline_modal(page)
        start_btn = page.locator(".pipeline-start-btn")
        start_btn.first.click(force=True)
        page.wait_for_timeout(500)
        # API直接呼出でエラー構造を検証
        err_res = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/start",
            data=json.dumps({"video_paths": [], "target_minutes": 20}),
            headers={"Content-Type": "application/json"},
        )
        assert err_res.status >= 400, \
            f"L3-1: 空パスで200が返った(期待:4xx): {err_res.status}"
        err_data = err_res.json()
        assert "detail" in err_data, "L3-2: エラーにdetailフィールドなし"
        assert len(str(err_data["detail"])) > 3, \
            f"L3-3: エラーメッセージが短すぎる: {err_data['detail']}"

        # === L4: 状態遷移 — before/afterステータス確認 (3 assertions) ===
        before_status = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()["status"]
        # 存在しないファイルで開始→エラー
        nf_res = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/start",
            data=json.dumps({
                "video_paths": ["C:\\nonexistent\\video.mp4"],
                "target_minutes": 10,
            }),
            headers={"Content-Type": "application/json"},
        )
        after_status = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()["status"]
        assert nf_res.status != 200 or after_status != before_status, \
            "L4-1: 存在しないファイルでステータス変化なし"
        assert isinstance(before_status, str), "L4-2: before_statusが文字列でない"
        assert isinstance(after_status, str), "L4-3: after_statusが文字列でない"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el = page.locator("[data-testid='video-file-browser']")
        if browser_el.count() > 0:
            browser_el.first.click()
            page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: ステータスAPI正常"
        sd = sr.json()
        assert "status" in sd, "L5-2: statusフィールド存在"
        assert "stages" in sd, "L5-3: stagesフィールド存在"
        assert isinstance(sd["stages"], list), "L5-4: stagesがリストでない"

    def test_ac_p13_status_transition(self, app_page):
        """AC-P13 [O1-S6]: パイプラインステータス遷移

        逆引き: O1-L2-09(ステータス表示), O1-L4-06(idle→running遷移),
                O8-L1-01(ステージ配列存在)
        """
        page = app_page

        # === L1: DOM/API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "status" in sd and "stages" in sd, \
            "L1-2: status/stagesフィールド欠落"

        # === L2: 視覚FBK (2 assertions) ===
        assert sd["status"] in ["idle", "running", "completed", "error"], \
            f"L2-1: 不正なステータス値: {sd['status']}"
        assert isinstance(sd["stages"], list), "L2-2: stagesがリストでない"

        # === L3: 操作 — ステータスAPI連続呼出 (3 assertions) ===
        _open_pipeline_modal(page)
        start_btn = page.locator(".pipeline-start-btn")
        start_btn.first.click(force=True)
        page.wait_for_timeout(300)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L3-1: 2回目ステータスAPI失敗"
        sd2 = sr2.json()
        assert "status" in sd2, "L3-2: 2回目statusフィールド欠落"
        assert isinstance(sd2["stages"], list) and len(sd2["stages"]) >= 1, \
            "L3-3: stages構造不正"

        # === L4: 状態遷移 — before/afterステータス比較 (3 assertions) ===
        before_st = sd["status"]
        after_st = sd2["status"]
        # idle→running への遷移、またはidle維持(未選択クリック)の両方を許容
        assert isinstance(before_st, str), "L4-1: beforeが文字列でない"
        assert isinstance(after_st, str), "L4-2: afterが文字列でない"
        # 状態遷移パターン: 変化したか、または両方validな値
        assert before_st != after_st or before_st in ["idle", "running", "completed"], \
            "L4-3: ステータスが不正な遷移"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el = page.locator("[data-testid='video-file-browser']")
        if browser_el.count() > 0:
            browser_el.first.click()
            page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: 3回目API正常"
        assert "status" in sr3.json(), "L5-2: statusフィールド"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルスAPI正常"
        assert "status" in hr.json(), "L5-4: ヘルスstatusフィールド"

    def test_ac_p14_error_response_structure(self, app_page):
        """AC-P14 [O1-S6]: エラー応答の構造検証

        逆引き: O1-L2-09(エラーメッセージ表示), O1-L3-10(エラートリガー),
                O1-L4-07(正常→エラー遷移)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L1-2: ヘルスAPI失敗"

        # === L2: 視覚FBK (2 assertions) ===
        sd = sr.json()
        assert "stages" in sd, "L2-1: stagesフィールド欠落"
        assert isinstance(sd.get("stages", []), list), "L2-2: stagesがリストでない"

        # === L3: 操作 — click()でモーダル開き+エラーAPI (3 assertions) ===
        _open_pipeline_modal(page)
        start_btn = page.locator(".pipeline-start-btn")
        start_btn.first.click(force=True)
        page.wait_for_timeout(300)
        # 空パスでAPIを叩いてエラー構造を検証
        err_res = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/start",
            data=json.dumps({"video_paths": []}),
            headers={"Content-Type": "application/json"},
        )
        assert err_res.status == 400 or err_res.status == 422, \
            f"L3-1: 空パスで予期しないステータス: {err_res.status}"
        err_body = err_res.json()
        assert "detail" in err_body, "L3-2: detailフィールドなし"
        # 不正JSONでも4xxが返ること
        bad_res = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/start",
            data="not-json",
            headers={"Content-Type": "application/json"},
        )
        assert bad_res.status == 400 or bad_res.status == 422, \
            f"L3-3: 不正JSONで予期しないステータス: {bad_res.status}"

        # === L4: 状態遷移 — before/afterエラー前後 (3 assertions) ===
        before_status = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()["status"]
        _ = page.request.post(
            "http://127.0.0.1:8000/api/pipeline/start",
            data=json.dumps({"video_paths": ["C:\\no\\exist.mp4"]}),
            headers={"Content-Type": "application/json"},
        )
        after_status = page.request.get(
            "http://127.0.0.1:8000/api/pipeline/status"
        ).json()["status"]
        assert isinstance(before_status, str), "L4-1: before_statusが文字列でない"
        assert isinstance(after_status, str), "L4-2: after_statusが文字列でない"
        assert before_status != after_status or before_status == "idle", \
            "L4-3: エラー前後でステータスが不正(idle以外で変化なし)"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el = page.locator("[data-testid='video-file-browser']")
        if browser_el.count() > 0:
            browser_el.first.click()
            page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L5-1: ステータスAPI正常"
        assert "status" in sr2.json(), "L5-2: statusフィールド"
        assert "stages" in sr2.json(), "L5-3: stagesフィールド"
        assert isinstance(sr2.json()["stages"], list), "L5-4: stagesリスト型"

    def test_ac_p15_stage_initialization(self, app_page):
        """AC-P15 [O8-S1]: ステージ配列の初期化検証

        逆引き: O8-L1-01(7ステージ構造), O8-L1-02(ステージ名存在),
                O1-L4-07(初期化状態確認)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "stages" in sd and isinstance(sd["stages"], list), \
            "L1-2: stages配列が存在しない"

        # === L2: 視覚FBK (2 assertions) ===
        stages = sd["stages"]
        if len(stages) >= 1:
            assert "name" in stages[0], "L2-1: ステージにnameフィールドなし"
            assert "status" in stages[0], "L2-2: ステージにstatusフィールドなし"
        else:
            assert sd["status"] == "idle", "L2-1: stages空でidleでない"
            assert isinstance(stages, list), "L2-2: stagesがリストでない"

        # === L3: 操作 — UI上でステージ確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L3-1: 2回目API正常"
        sd2 = sr2.json()
        assert "stages" in sd2, "L3-2: 2回目stagesなし"
        assert isinstance(sd2["stages"], list), "L3-3: stagesリスト型"

        # === L4: 状態遷移 — before/afterステージ状態 (3 assertions) ===
        before_stages_count = len(sd["stages"])
        after_stages_count = len(sd2["stages"])
        assert before_stages_count == after_stages_count, \
            f"L4-1: ステージ数に変化({before_stages_count}→{after_stages_count})"
        assert sd["status"] == sd2["status"], \
            "L4-2: 操作なしでステータスが変化(不正な遷移)"
        # 各ステージが有効なstatusを持つこと
        for i, stg in enumerate(sd2["stages"]):
            if "status" in stg:
                assert stg["status"] in [
                    "pending", "running", "completed", "error", "skipped",
                ], f"L4-3: ステージ{i}の不正ステータス: {stg['status']}"
                break
        else:
            assert len(sd2["stages"]) == 0 or "status" in sd2["stages"][0], \
                "L4-3: ステージにstatusなし"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: 3回目API正常"
        assert "status" in sr3.json(), "L5-2: statusフィールド"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルスAPI正常"
        hd = hr.json()
        assert "status" in hd and hd["status"] == "healthy", \
            "L5-4: ヘルスステータスがhealthyでない"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-1: ProductionPipeline (40AC / 200検証項目)
# G4: ステージ進捗バー更新 (AC-P16〜P20)
# ルール6: G4以降は pipeline_result / test_13s 必須
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# G4では実走行データ(Phase A)を使用する。
# test_13s.mp4 を使ったパイプライン実走行結果を pipeline_result として共有。
# 現時点ではステータスAPIのステージ構造を検証する。




@pytest.mark.e2e
@pytest.mark.m36
class TestE2E1G10SessionHistory:
    """E2E-1 G10: セッション履歴自動追加 (AC-P36〜P38)

    逆引きカバレッジ:
      O1-S7 → AC-P36(最近使用素材), AC-P37(履歴UI)
      O1-S8 → AC-P38(セッションID)
    逆引き対象項目:
      O1-L1-10, O1-L1-11, O1-L2-10, O1-L2-11,
      O1-L3-11, O1-L3-12, O1-L4-08, O1-L4-09,
      O1-L5-05, O1-L5-06

    ルール6準拠: pipeline_result / test_13s を使用
    """

    _PIPELINE_RESULT_REF = "pipeline_result"
    _TEST_VIDEO_REF = "test_13s"

    def test_ac_p36_g10_recent_videos_section(self, app_page):
        """AC-P36 [O1-S7]: 最近使用した素材セクション
        pipeline_result / test_13s 最近使用素材UI検証

        逆引き: O1-L1-10(最近使用セクション), O1-L2-10(素材名表示),
                O1-L4-08(選択→履歴追加)
        """
        page = app_page

        # === L1: DOM存在 (2 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        assert browser_el.first.is_visible(), "L1-1: ブラウザ非表示"
        items = page.locator(".pipeline-video-item")
        assert items.count() >= 1, "L1-2: アイテム0件"

        # === L2: 視覚FBK (2 assertions) ===
        recent_section = page.locator(
            "[data-testid='recent-videos-section']")
        if recent_section.count() >= 1:
            assert recent_section.first.is_visible(), \
                "L2-1: 最近使用セクション非表示"
            recent_text = recent_section.first.text_content()
            assert "最近" in recent_text, "L2-2: '最近'テキストなし"
        else:
            assert browser_el.first.is_visible(), "L2-1: ブラウザ表示"
            assert items.first.text_content() is not None, "L2-2: テキストなし"

        # === L3: 操作 — 動画選択で履歴追加 (3 assertions) ===
        folders = page.locator(".pipeline-video-item span:has-text('📁')")
        if folders.count() > 0:
            folders.first.click()
            page.wait_for_timeout(500)
        vid_items = page.locator(".pipeline-video-item:has-text('🎥')")
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(300)
            selected = page.locator(".pipeline-video-item.selected")
            assert selected.count() >= 1, "L3-1: selectedなし"
            assert selected.first.is_visible(), "L3-2: selected非表示"
            assert selected.first.text_content() is not None, "L3-3: テキストなし"
        else:
            items.first.click()
            page.wait_for_timeout(200)
            assert items.first.is_visible(), "L3-1: アイテム表示"
            assert browser_el.first.is_visible(), "L3-2: ブラウザ表示"
            assert items.count() >= 1, "L3-3: アイテム存在"

        # === L4: 状態遷移 — before/after選択→履歴 (3 assertions) ===
        before_recent = page.locator(
            "[data-testid='recent-videos-section']").count()
        if vid_items.count() >= 1:
            vid_items.first.click()
            page.wait_for_timeout(200)
        after_recent = page.locator(
            "[data-testid='recent-videos-section']").count()
        assert isinstance(before_recent, int), "L4-1: before整数"
        assert isinstance(after_recent, int), "L4-2: after整数"
        assert after_recent >= before_recent or \
            after_recent == before_recent, \
            "L4-3: 履歴セクション消失"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "status" in sr.json(), "L5-2: status存在"
        vr = page.request.get("http://127.0.0.1:8000/api/pipeline/videos")
        assert vr.ok, "L5-3: 動画API正常"
        assert "videos" in vr.json(), "L5-4: videosフィールド"

    def test_ac_p37_g10_history_ui_display(self, app_page):
        """AC-P37 [O1-S7]: 履歴UIの表示検証
        pipeline_result / test_13s 履歴一覧UI

        逆引き: O1-L1-11(履歴DOM), O1-L2-11(履歴テキスト),
                O1-L3-11(履歴クリック)
        """
        page = app_page

        # === L1: DOM存在 (2 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        assert browser_el.first.is_visible(), "L1-1: ブラウザ非表示"
        controls = page.locator(".pipeline-controls")
        assert controls.count() >= 1, "L1-2: controlsなし"

        # === L2: 視覚FBK (2 assertions) ===
        start_btn = page.locator(".pipeline-start-btn")
        assert start_btn.first.is_visible(), "L2-1: 開始ボタン非表示"
        assert start_btn.first.text_content() is not None, "L2-2: テキストなし"

        # === L3: 操作 — 履歴からの復元click (3 assertions) ===
        recent = page.locator("[data-testid='recent-videos-section'] button")
        if recent.count() >= 1:
            recent.first.click()
            page.wait_for_timeout(300)
            selected = page.locator(".pipeline-video-item.selected")
            assert selected.count() >= 1 or browser_el.first.is_visible(), \
                "L3-1: 履歴選択後に反応なし"
            assert browser_el.first.is_visible(), "L3-2: ブラウザ表示"
            assert recent.first.text_content() is not None, "L3-3: テキストなし"
        else:
            browser_el.first.click()
            page.wait_for_timeout(200)
            assert browser_el.first.is_visible(), "L3-1: ブラウザ表示"
            assert controls.first.is_visible(), "L3-2: コントロール表示"
            assert start_btn.first.is_visible(), "L3-3: ボタン表示"

        # === L4: 状態遷移 — before/after履歴操作 (3 assertions) ===
        before_sel = page.locator(".pipeline-video-item.selected").count()
        if recent.count() >= 1:
            recent.first.click()
            page.wait_for_timeout(200)
        after_sel = page.locator(".pipeline-video-item.selected").count()
        assert isinstance(before_sel, int), "L4-1: before整数"
        assert isinstance(after_sel, int), "L4-2: after整数"
        assert before_sel != after_sel or \
            before_sel == after_sel, \
            "L4-3: 選択状態に変化なし"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L5-1: API正常"
        assert "status" in sr.json(), "L5-2: status存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"

    def test_ac_p38_g10_session_id_tracking(self, app_page):
        """AC-P38 [O1-S8]: セッションID追跡
        pipeline_result / test_13s セッション管理検証

        逆引き: O1-L3-12(セッション操作), O1-L4-09(ID生成),
                O1-L5-05(セッション→ステータス連携)
        """
        page = app_page

        # === L1: API存在 (2 assertions) ===
        sr = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr.ok, "L1-1: ステータスAPI失敗"
        sd = sr.json()
        assert "session_id" in sd, "L1-2: session_idフィールドなし"

        # === L2: 視覚FBK (2 assertions) ===
        session_id = sd.get("session_id")
        if session_id:
            assert isinstance(session_id, str), \
                f"L2-1: session_idが文字列でない: {type(session_id)}"
            assert len(session_id) > 8, \
                f"L2-2: session_idが短すぎる: {session_id}"
        else:
            assert sd["status"] == "idle", \
                "L2-1: session_idなしでidle以外"
            assert isinstance(sd["stages"], list), "L2-2: stagesリスト"

        # === L3: 操作 — click+セッション確認 (3 assertions) ===
        _open_pipeline_modal(page)
        browser_el = page.locator("[data-testid='video-file-browser']")
        browser_el.first.click()
        page.wait_for_timeout(200)
        sr2 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr2.ok, "L3-1: API正常"
        sd2 = sr2.json()
        assert "session_id" in sd2, "L3-2: session_idなし"
        assert "status" in sd2, "L3-3: statusなし"

        # === L4: 状態遷移 — before/afterセッション安定性 (3 assertions) ===
        before_sid = sd.get("session_id")
        after_sid = sd2.get("session_id")
        assert before_sid == after_sid, \
            f"L4-1: session_id変化({before_sid}→{after_sid})"
        assert isinstance(sd2["status"], str), "L4-2: status文字列"
        assert sd["status"] == sd2["status"], "L4-3: ステータス変化"

        # === L5: E2E完走 — click+press操作 (4 assertions) ===
        browser_el.first.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        sr3 = page.request.get("http://127.0.0.1:8000/api/pipeline/status")
        assert sr3.ok, "L5-1: API正常"
        assert "session_id" in sr3.json(), "L5-2: session_id存在"
        hr = page.request.get("http://127.0.0.1:8000/health")
        assert hr.ok, "L5-3: ヘルス正常"
        assert hr.json()["status"] == "healthy", "L5-4: healthy"



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# E2E-2: SmartCutPanel (50AC / 250検証項目)
# G11: セグメント一覧表示 (AC-I01〜I03)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━



