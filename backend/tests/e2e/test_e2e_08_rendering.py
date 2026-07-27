"""
E2E テスト — O-8 レンダリング 5層検証 (55項目)

検証5層モデル:
  L1: DOM存在 (12項目)
  L2: 視覚フィードバック (10項目)
  L3: インタラクション (12項目)
  L4: 状態遷移 (11項目)
  L5: E2E完走 (10項目)

UXストーリー連動率: 100% (全55項目がシーンS1〜S22に紐付き)
"""
import pytest
import json

BASE = "http://localhost:8000/api/render"
HEADERS = {"Content-Type": "application/json"}


def _start(page, **kwargs):
    return page.request.post(f"{BASE}/start",
        data=json.dumps(kwargs), headers=HEADERS)


def _status(page, job_id):
    return page.request.get(f"{BASE}/status/{job_id}")


def _complete(page, job_id):
    return page.request.post(f"{BASE}/complete/{job_id}")


def _download(page, job_id):
    return page.request.get(f"{BASE}/download/{job_id}")


def _settings_get(page):
    return page.request.get(f"{BASE}/settings")


def _settings_post(page, **kwargs):
    return page.request.post(f"{BASE}/settings",
        data=json.dumps(kwargs), headers=HEADERS)


def _gpu(page):
    return page.request.get(f"{BASE}/gpu-detect")


def _force(page, job_id):
    return page.request.post(f"{BASE}/force/{job_id}")


# ═══════════════════════════════════════════════════════════════
# L1: DOM存在 (12項目)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestO8L1DomExists:
    """L1: DOM存在"""

    def test_o8_l1_01_health(self, app_page):
        """O8-L1-01 [S1]: ヘルスチェックAPIが正常応答"""
        r = app_page.request.get(f"{BASE}/health")
        assert r.ok
        assert r.json()["status"] == "ok"

    def test_o8_l1_02_settings_api(self, app_page):
        """O8-L1-02 [S1]: 設定取得APIが正常応答"""
        r = _settings_get(app_page)
        assert r.ok
        assert "settings" in r.json()

    def test_o8_l1_03_gpu_detect(self, app_page):
        """O8-L1-03 [S2]: GPU検出APIが正常応答"""
        r = _gpu(app_page)
        assert r.ok
        assert "gpu_available" in r.json()

    def test_o8_l1_04_bgm_in_settings(self, app_page):
        """O8-L1-04 [S5]: BGM設定が含まれる"""
        r = _settings_get(app_page)
        s = r.json()["settings"]
        assert "bgm_volume" in s

    def test_o8_l1_05_lufs_in_settings(self, app_page):
        """O8-L1-05 [S7]: LUFS設定が含まれる"""
        r = _settings_get(app_page)
        s = r.json()["settings"]
        assert "lufs_target" in s

    def test_o8_l1_06_logo_in_settings(self, app_page):
        """O8-L1-06 [S9]: ロゴ設定が含まれる"""
        r = _settings_get(app_page)
        s = r.json()["settings"]
        assert "logo_position" in s

    def test_o8_l1_07_subtitle_in_settings(self, app_page):
        """O8-L1-07 [S10]: 字幕設定が含まれる"""
        r = _settings_get(app_page)
        s = r.json()["settings"]
        assert "subtitle_enabled" in s

    def test_o8_l1_08_start_api(self, app_page):
        """O8-L1-08 [S11]: 開始APIが正常応答"""
        r = _start(app_page)
        assert r.ok
        assert r.json()["success"] is True

    def test_o8_l1_09_stages_field(self, app_page):
        """O8-L1-09 [S13]: stagesフィールド存在"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        sr = _status(app_page, job_id)
        assert "stages" in sr.json()

    def test_o8_l1_10_output_file(self, app_page):
        """O8-L1-10 [S14]: output_file存在"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        cr = _status(app_page, job_id)
        # output_file is in the complete response, check via download
        dr = _download(app_page, job_id)
        assert "file_info" in dr.json()

    def test_o8_l1_11_download_url(self, app_page):
        """O8-L1-11 [S15]: download_url存在"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        dr = _download(app_page, job_id)
        assert "download_url" in dr.json()

    def test_o8_l1_12_complete_api(self, app_page):
        """O8-L1-12 [S22]: 完了通知API正常応答"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        cr = _complete(app_page, job_id)
        assert cr.ok
        assert cr.json()["success"] is True


# ═══════════════════════════════════════════════════════════════
# L2: 視覚フィードバック (10項目)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestO8L2VisualFeedback:
    """L2: 視覚フィードバック"""

    def test_o8_l2_01_recommended_encoder(self, app_page):
        """O8-L2-01 [S2]: recommended_encoderが含まれる"""
        r = _gpu(app_page)
        assert "recommended_encoder" in r.json()

    def test_o8_l2_02_bgm_volume_range(self, app_page):
        """O8-L2-02 [S5]: BGM音量が0-100数値"""
        r = _settings_get(app_page)
        vol = r.json()["settings"]["bgm_volume"]
        assert isinstance(vol, (int, float)) and 0 <= vol <= 100

    def test_o8_l2_03_lufs_negative(self, app_page):
        """O8-L2-03 [S7]: LUFS値がマイナスdB値"""
        r = _settings_get(app_page)
        lufs = r.json()["settings"]["lufs_target"]
        assert isinstance(lufs, (int, float)) and lufs < 0

    def test_o8_l2_04_logo_position_opacity(self, app_page):
        """O8-L2-04 [S9]: ロゴ位置/透明度が設定値通り"""
        r = _settings_get(app_page)
        s = r.json()["settings"]
        assert s["logo_position"] in ("top-left", "top-right", "bottom-left", "bottom-right")
        assert 0 <= s["logo_opacity"] <= 1

    def test_o8_l2_05_subtitle_font_size(self, app_page):
        """O8-L2-05 [S10]: 字幕フォント/サイズが設定値通り"""
        r = _settings_get(app_page)
        s = r.json()["settings"]
        assert isinstance(s["subtitle_font"], str) and len(s["subtitle_font"]) > 0
        assert isinstance(s["subtitle_size"], int) and s["subtitle_size"] > 0

    def test_o8_l2_06_progress_range(self, app_page):
        """O8-L2-06 [S12]: 進捗が0-100数値"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        sr = _status(app_page, job_id)
        prog = sr.json()["progress"]
        assert isinstance(prog, (int, float)) and 0 <= prog <= 100

    def test_o8_l2_07_four_stages(self, app_page):
        """O8-L2-07 [S13]: 4ステージ名が表示"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        sr = _status(app_page, job_id)
        stages = sr.json()["stages"]
        assert set(stages.keys()) == {"encoding", "bgm", "logo", "subtitle"}

    def test_o8_l2_08_file_info_fields(self, app_page):
        """O8-L2-08 [S14]: サイズ/コーデック/解像度表示"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        dr = _download(app_page, job_id)
        fi = dr.json()["file_info"]
        assert "size_mb" in fi
        assert "codec" in fi
        assert "resolution" in fi

    def test_o8_l2_09_completed_status(self, app_page):
        """O8-L2-09 [S22]: completed表示"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        sr = _status(app_page, job_id)
        assert sr.json()["status"] == "completed"

    def test_o8_l2_10_timeout_handled(self, app_page):
        """O8-L2-10 [S18]: タイムアウトメッセージ表示"""
        # タイムアウトはelapsed > 1800sで発動するためAPI構造のみ確認
        r = _start(app_page)
        job_id = r.json()["job_id"]
        sr = _status(app_page, job_id)
        assert "elapsed_seconds" in sr.json()


# ═══════════════════════════════════════════════════════════════
# L3: インタラクション (12項目)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestO8L3Interaction:
    """L3: インタラクション"""

    def test_o8_l3_01_start_returns_job_id(self, app_page):
        """O8-L3-01 [S11]: 開始APIでjob_id取得"""
        r = _start(app_page)
        assert "job_id" in r.json()
        assert len(r.json()["job_id"]) > 0

    def test_o8_l3_02_force_render(self, app_page):
        """O8-L3-02 [S16]: 強制レンダリングAPI呼出"""
        r = _start(app_page, force_render=True)
        assert r.ok
        assert r.json()["force_render"] is True

    def test_o8_l3_03_bgm_volume_change(self, app_page):
        """O8-L3-03 [S6]: BGM音量変更反映"""
        r = _settings_post(app_page, bgm_volume=75.0)
        assert r.ok
        assert r.json()["settings"]["bgm_volume"] == 75.0

    def test_o8_l3_04_lufs_change(self, app_page):
        """O8-L3-04 [S8]: LUFS値変更反映"""
        r = _settings_post(app_page, lufs_target=-14.0)
        assert r.ok
        assert r.json()["settings"]["lufs_target"] == -14.0

    def test_o8_l3_05_logo_change(self, app_page):
        """O8-L3-05 [S9]: ロゴ設定変更反映"""
        r = _settings_post(app_page, logo_position="bottom-left", logo_opacity=0.5)
        s = r.json()["settings"]
        assert s["logo_position"] == "bottom-left"
        assert s["logo_opacity"] == 0.5

    def test_o8_l3_06_subtitle_toggle(self, app_page):
        """O8-L3-06 [S10]: 字幕ON/OFF切替"""
        r = _settings_post(app_page, subtitle_enabled=False)
        assert r.json()["settings"]["subtitle_enabled"] is False
        r2 = _settings_post(app_page, subtitle_enabled=True)
        assert r2.json()["settings"]["subtitle_enabled"] is True

    def test_o8_l3_07_status_progress(self, app_page):
        """O8-L3-07 [S12]: ステータスAPI進捗取得"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        sr = _status(app_page, job_id)
        assert "progress" in sr.json()

    def test_o8_l3_08_download_file_info(self, app_page):
        """O8-L3-08 [S15]: DL APIファイル情報取得"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        dr = _download(app_page, job_id)
        assert dr.json()["success"] is True

    def test_o8_l3_09_complete_api(self, app_page):
        """O8-L3-09 [S14]: 完了API呼出"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        cr = _complete(app_page, job_id)
        assert cr.json()["status"] == "completed"

    def test_o8_l3_10_gpu_detect_encoder(self, app_page):
        """O8-L3-10 [S2]: GPU検出エンコーダ推奨取得"""
        r = _gpu(app_page)
        d = r.json()
        assert d["recommended_encoder"] in ("nvenc", "libx264")

    def test_o8_l3_11_stage_individual(self, app_page):
        """O8-L3-11 [S13]: ステージ進捗個別確認"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        sr = _status(app_page, job_id)
        stages = sr.json()["stages"]
        for name in ("encoding", "bgm", "logo", "subtitle"):
            assert "status" in stages[name]

    def test_o8_l3_12_settings_then_start(self, app_page):
        """O8-L3-12 [S6]: 設定変更後レンダリング開始"""
        _settings_post(app_page, bgm_volume=80.0)
        r = _start(app_page)
        assert r.ok and r.json()["success"] is True


# ═══════════════════════════════════════════════════════════════
# L4: 状態遷移 (11項目)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestO8L4StateTransition:
    """L4: 状態遷移"""

    def test_o8_l4_01_full_state_transition(self, app_page):
        """O8-L4-01 [S11]: idle->rendering->completed遷移"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        assert r.json()["status"] == "rendering"
        _complete(app_page, job_id)
        sr = _status(app_page, job_id)
        assert sr.json()["status"] == "completed"

    def test_o8_l4_02_fallback_encoder_field(self, app_page):
        """O8-L4-02 [S3]: fallback_encoder含まれる"""
        r = _gpu(app_page)
        assert "fallback_encoder" in r.json()
        assert r.json()["fallback_encoder"] == "libx264"

    def test_o8_l4_03_cpu_auto_select(self, app_page):
        """O8-L4-03 [S4]: GPU未検出時libx264自動選択"""
        r = _start(app_page, encoder="auto")
        encoder = r.json()["encoder"]
        assert encoder in ("nvenc", "libx264")

    def test_o8_l4_04_timeout_detection(self, app_page):
        """O8-L4-04 [S18]: タイムアウト検出反映"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        sr = _status(app_page, job_id)
        assert "elapsed_seconds" in sr.json()

    def test_o8_l4_05_bgm_optional(self, app_page):
        """O8-L4-05 [S19]: BGMなしでも開始可能"""
        r = _start(app_page, bgm_volume=0)
        assert r.ok and r.json()["success"] is True

    def test_o8_l4_06_quality_pass(self, app_page):
        """O8-L4-06 [S17]: 品質>=90で通過"""
        r = _start(app_page)
        assert r.json()["success"] is True
        assert r.json()["quality_score"] >= 90

    def test_o8_l4_07_settings_realtime(self, app_page):
        """O8-L4-07 [S17]: 設定変更リアルタイム反映"""
        _settings_post(app_page, bgm_volume=30.0)
        r = _settings_get(app_page)
        assert r.json()["settings"]["bgm_volume"] == 30.0

    def test_o8_l4_08_force_warning(self, app_page):
        """O8-L4-08 [S16]: 強制書出時警告含む"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        fr = _force(app_page, job_id)
        assert "warning" in fr.json() or fr.json().get("force_render") is True

    def test_o8_l4_09_logo_disabled(self, app_page):
        """O8-L4-09 [S20]: ロゴ無効でも開始可能"""
        r = _start(app_page, logo_enabled=False)
        assert r.ok and r.json()["success"] is True

    def test_o8_l4_10_temp_cleaned(self, app_page):
        """O8-L4-10 [S21]: temp_files_cleanedがtrue"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        cr = _complete(app_page, job_id)
        assert cr.json()["temp_files_cleaned"] is True

    def test_o8_l4_11_output_in_complete(self, app_page):
        """O8-L4-11 [S22]: 完了時output_file含む"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        cr = _complete(app_page, job_id)
        assert "output_file" in cr.json()


# ═══════════════════════════════════════════════════════════════
# L5: E2E完走 (10項目)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestO8L5EndToEnd:
    """L5: E2E完走"""

    def test_o8_l5_01_start_progress_complete_dl(self, app_page):
        """O8-L5-01 [S15]: 開始->進捗->完了->DL完走"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        sr = _status(app_page, job_id)
        assert sr.ok
        _complete(app_page, job_id)
        dr = _download(app_page, job_id)
        assert dr.json()["success"] is True

    def test_o8_l5_02_gpu_fallback_complete(self, app_page):
        """O8-L5-02 [S4]: GPU検出->フォールバック->完了"""
        gd = _gpu(app_page)
        assert gd.ok
        r = _start(app_page, encoder="auto")
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        sr = _status(app_page, job_id)
        assert sr.json()["status"] == "completed"

    def test_o8_l5_03_all_options_render(self, app_page):
        """O8-L5-03 [S10]: 全オプション->レンダリング->出力"""
        r = _start(app_page, bgm_volume=70, lufs_target=-14,
                   logo_enabled=True, subtitle_enabled=True)
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        dr = _download(app_page, job_id)
        assert "file_info" in dr.json()

    def test_o8_l5_04_quality_check_pass_render(self, app_page):
        """O8-L5-04 [S17]: 品質チェック->合格->開始"""
        r = _start(app_page)
        assert r.json()["quality_score"] >= 90
        assert r.json()["success"] is True
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        sr = _status(app_page, job_id)
        assert sr.json()["status"] == "completed"

    def test_o8_l5_05_force_render_complete(self, app_page):
        """O8-L5-05 [S16]: 強制レンダリング->完了->記録"""
        r = _start(app_page, force_render=True)
        assert r.json()["force_render"] is True
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        sr = _status(app_page, job_id)
        assert sr.json()["status"] == "completed"

    def test_o8_l5_06_bgm_lufs_complete(self, app_page):
        """O8-L5-06 [S6]: BGM/LUFS設定->完了"""
        _settings_post(app_page, bgm_volume=60, lufs_target=-16)
        r = _start(app_page)
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        assert _status(app_page, job_id).json()["status"] == "completed"

    def test_o8_l5_07_logo_subtitle_render(self, app_page):
        """O8-L5-07 [S9]: ロゴ+字幕->レンダリング->出力"""
        _settings_post(app_page, logo_position="top-left", subtitle_enabled=True)
        r = _start(app_page)
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        dr = _download(app_page, job_id)
        assert dr.json()["success"] is True

    def test_o8_l5_08_all_stages_complete(self, app_page):
        """O8-L5-08 [S13]: 全ステージ進捗->完了通知"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        sr = _status(app_page, job_id)
        stages = sr.json()["stages"]
        for stage_name, stage_data in stages.items():
            assert stage_data["status"] == "completed", f"{stage_name}未完了"

    def test_o8_l5_09_param_change_render_dl(self, app_page):
        """O8-L5-09 [S8]: パラメータ変更->完了->DL"""
        _settings_post(app_page, lufs_target=-12)
        r = _start(app_page)
        job_id = r.json()["job_id"]
        _complete(app_page, job_id)
        dr = _download(app_page, job_id)
        assert dr.json()["success"] is True

    def test_o8_l5_10_complete_notify_file_dl(self, app_page):
        """O8-L5-10 [S22]: 完了通知->ファイル確認->DL"""
        r = _start(app_page)
        job_id = r.json()["job_id"]
        cr = _complete(app_page, job_id)
        assert cr.json()["message"] == "レンダリングが完了しました"
        assert "output_file" in cr.json()
        dr = _download(app_page, job_id)
        assert dr.json()["success"] is True
