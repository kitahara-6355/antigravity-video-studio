"""







Sprint 2.3.4: PreviewSystem テスト (12テスト)







対象: preview_system.py, routers/preview.py, services/preview_report_generator.py















PP-05: capture_with_subtitle







PP-09: markdown report (generate)







PP-10: report save







PP-20: validate_video_path







PP-24: generate_scene_previews







PP-25: capture_without_subtitle + telop







PP-29: services risk_color







PP-30: services retention report html















テスト構成:







  TestSubtitleCapture (2)     # PP-05, PP-25







  TestMarkdownReport (2)      # PP-09, PP-10







  TestScenePreview (2)        # PP-24 + 追加







  TestRouterValidation (2)    # PP-20 + 追加







  TestServicesReport (4)      # PP-29, PP-30 + 追加







"""















import pytest







import json







from pathlib import Path







from unittest.mock import patch, MagicMock







from dataclasses import asdict















from preview_system import (







    SubtitlePreviewGenerator,







    TelopPreviewGenerator,







    PreviewReportGenerator as SystemReportGenerator,







    PreviewReport,







    ScenePreview,







    create_preview_system,







)























# ─── ヘルパー ───















def _mock_subprocess_ok(stdout="", stderr="", returncode=0):







    m = MagicMock()







    m.returncode = returncode







    m.stdout = stdout







    m.stderr = stderr







    return m























# ═══════════════════════════════════════════════════════════







# PP-05, PP-25: 字幕・テロップキャプチャ







# ═══════════════════════════════════════════════════════════















class TestSubtitleCapture:







    """PP-05, PP-25: 字幕付き/なしスクショ、テロップ"""















    @patch("preview_system.subprocess.run")







    def test_pp05_capture_with_subtitle_success_and_failure(self, mock_run, tmp_path):







        """PP-05: 字幕付きスクショ成功→パス返却、失敗→None"""







        gen = SubtitlePreviewGenerator(tmp_path / "previews")















        # 成功: returncode=0 + ファイル作成







        def success_side_effect(cmd, **kwargs):







            out_path = cmd[-1]







            Path(out_path).write_bytes(b"FAKE_JPEG_DATA")







            return _mock_subprocess_ok()















        mock_run.side_effect = success_side_effect







        srt_path = tmp_path / "test.srt"







        srt_path.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello\n", encoding="utf-8")















        result = gen.capture_with_subtitle(







            tmp_path / "video.mp4", srt_path, "00:00:02", "test_frame"







        )







        assert result is not None







        assert result.exists()















        # -ss が -i の後にあること（字幕同期のため重要）







        cmd = mock_run.call_args[0][0]







        i_idx = cmd.index("-i")







        ss_idx = cmd.index("-ss")







        assert ss_idx > i_idx, "-ss は -i の後であるべき"















        # 失敗: returncode != 0







        mock_run.side_effect = None







        mock_run.return_value = _mock_subprocess_ok(returncode=1, stderr="error")







        result_fail = gen.capture_with_subtitle(







            tmp_path / "video.mp4", srt_path, "00:00:02", "fail_frame"







        )







        assert result_fail is None















    @patch("preview_system.subprocess.run")







    def test_pp25_capture_without_and_telop(self, mock_run, tmp_path):







        """PP-25: 字幕なしスクショ + テロップ(top/bottom)"""







        # 字幕なしスクショ







        sub_gen = SubtitlePreviewGenerator(tmp_path / "sub_previews")















        def create_file(cmd, **kwargs):







            Path(cmd[-1]).write_bytes(b"FAKE")







            return _mock_subprocess_ok()















        mock_run.side_effect = create_file







        result = sub_gen.capture_without_subtitle(







            tmp_path / "video.mp4", "00:01:00", "no_sub"







        )







        assert result is not None







        assert result.exists()















        # 失敗→None







        mock_run.side_effect = Exception("crash")







        result_fail = sub_gen.capture_without_subtitle(







            tmp_path / "video.mp4", "00:01:00", "fail"







        )







        assert result_fail is None















        # テロップ: top位置







        mock_run.side_effect = create_file







        telop_gen = TelopPreviewGenerator(tmp_path / "telop_previews")







        result_top = telop_gen.generate_telop_preview(







            tmp_path / "video.mp4", "00:00:10", "テスト", "top_frame", position="top"







        )







        assert result_top is not None







        cmd = mock_run.call_args[0][0]







        vf_str = " ".join(cmd)







        assert "50" in vf_str  # y_pos = "50" for top















        # テロップ: bottom位置







        result_bottom = telop_gen.generate_telop_preview(







            tmp_path / "video.mp4", "00:00:10", "テスト", "bottom_frame", position="bottom"







        )







        assert result_bottom is not None















        # テロップ失敗→None







        mock_run.side_effect = None







        mock_run.return_value = _mock_subprocess_ok(returncode=1)







        result_telop_fail = telop_gen.generate_telop_preview(







            tmp_path / "video.mp4", "00:00:10", "テスト", "fail_telop"







        )







        assert result_telop_fail is None

    @patch("preview_system.subprocess.run")
    def test_ffmpeg_parameter_order_and_variables(self, mock_run, tmp_path):
        """Verify -ss parameter is placed after -i, and y_pos uses text_h instead of th"""
        sub_gen = SubtitlePreviewGenerator(tmp_path / "sub_previews")
        telop_gen = TelopPreviewGenerator(tmp_path / "telop_previews")

        def create_file(cmd, **kwargs):
            Path(cmd[-1]).write_bytes(b"FAKE")
            return _mock_subprocess_ok()

        mock_run.side_effect = create_file

        # capture_without_subtitle
        sub_gen.capture_without_subtitle(tmp_path / "video.mp4", "00:01:00", "no_sub")
        cmd_no_sub = mock_run.call_args[0][0]
        idx_i_nosub = cmd_no_sub.index("-i")
        idx_ss_nosub = cmd_no_sub.index("-ss")
        assert idx_ss_nosub > idx_i_nosub, f"-ss should be after -i: {cmd_no_sub}"

        mock_run.reset_mock()

        # generate_telop_preview top
        telop_gen.generate_telop_preview(tmp_path / "video.mp4", "00:01:00", "Telop Text", "top_frame", position="top")
        cmd_telop = mock_run.call_args[0][0]
        idx_i_telop = cmd_telop.index("-i")
        idx_ss_telop = cmd_telop.index("-ss")
        assert idx_ss_telop > idx_i_telop, f"-ss should be after -i: {cmd_telop}"

        mock_run.reset_mock()

        # generate_telop_preview bottom
        telop_gen.generate_telop_preview(tmp_path / "video.mp4", "00:01:00", "Telop Text", "bottom_frame", position="bottom")
        cmd_telop_bottom = mock_run.call_args[0][0]
        vf_arg = cmd_telop_bottom[cmd_telop_bottom.index("-vf") + 1]
        assert "y=h-text_h-50" in vf_arg, f"y_pos should use text_h: {vf_arg}"























# ═══════════════════════════════════════════════════════════







# PP-09, PP-10: Markdown レポート







# ═══════════════════════════════════════════════════════════















class TestMarkdownReport:







    """PP-09, PP-10: walkthrough.md形式レポート"""















    def test_pp09_markdown_report_full(self, tmp_path):







        """PP-09: proper_noun_warnings, screenshots carousel, telop_suggestions, 確認事項"""







        report = PreviewReport(







            title="テストレポート",







            scenes=[







                ScenePreview(







                    scene_name="シーン1",







                    video_path="video.mp4",







                    subtitle_path="sub.srt",







                    screenshots=[







                        {"timestamp": "00:01:00", "path": "s1.jpg", "with_subtitle": True},







                        {"timestamp": "00:02:00", "path": "s2.jpg", "with_subtitle": False},







                    ],







                    telop_suggestions=[







                        {"timestamp": "00:01:30", "text": "重要ポイント!", "reason": "視聴維持"},







                    ],







                ),







                ScenePreview(







                    scene_name="シーン2",







                    video_path="video.mp4",







                    subtitle_path=None,







                    screenshots=[],







                ),







            ],







            proper_noun_warnings=[







                {"found": "Antigravty", "correct": "Antigravity", "location": "L42"},







            ],







        )















        gen = SystemReportGenerator(tmp_path)







        md = gen.generate(report)















        # 構造検証







        assert "# テストレポート" in md







        assert "技術憲法9条" in md







        assert "⚠️ 誤字警告" in md







        assert "Antigravty" in md







        assert "Antigravity" in md







        assert "````carousel" in md







        assert "<!-- slide -->" in md







        assert "字幕付き" in md







        assert "字幕なし" in md







        assert "テロップ候補" in md







        assert "重要ポイント!" in md







        assert "確認事項" in md







        assert "ドラフト動画" in md







        # シーン2はscreenshots空なのでcarouselなし







        assert md.count("````carousel") == 1















    def test_pp10_report_save_to_file(self, tmp_path):







        """PP-10: generate()→ファイル保存、内容一致"""







        report = PreviewReport(







            title="保存テスト",







            scenes=[







                ScenePreview(







                    scene_name="S1", video_path="v.mp4",







                    subtitle_path=None, screenshots=[],







                ),







            ],







        )















        gen = SystemReportGenerator(tmp_path)







        output_path = gen.save(report, filename="test_walkthrough.md")















        assert output_path.exists()







        content = output_path.read_text(encoding="utf-8")







        expected = gen.generate(report)







        assert content == expected























# ═══════════════════════════════════════════════════════════







# PP-24: シーンプレビュー







# ═══════════════════════════════════════════════════════════















class TestScenePreview:







    """PP-24: generate_scene_previews フォールバック分岐"""















    @patch("preview_system.subprocess.run")







    def test_pp24_scene_preview_subtitle_and_fallback(self, mock_run, tmp_path):







        """PP-24: 字幕付き成功→with_subtitle=True。字幕なし/失敗→fallback"""







        gen = SubtitlePreviewGenerator(tmp_path / "previews")















        def create_file(cmd, **kwargs):







            Path(cmd[-1]).write_bytes(b"FAKE_JPEG")







            return _mock_subprocess_ok()















        mock_run.side_effect = create_file















        # 字幕あり → with_subtitle=True







        srt_path = tmp_path / "test.srt"







        srt_path.write_text("1\n00:00:01,000 --> 00:00:03,000\nHi\n", encoding="utf-8")















        result = gen.generate_scene_previews(







            "test_scene", tmp_path / "video.mp4", srt_path, ["00:00:02"]







        )







        assert result.scene_name == "test_scene"







        assert len(result.screenshots) > 0







        assert any(s["with_subtitle"] for s in result.screenshots)















        # 字幕なし → with_subtitle=False







        result_no_sub = gen.generate_scene_previews(







            "no_sub_scene", tmp_path / "video.mp4", None, ["00:00:05"]







        )







        assert all(not s["with_subtitle"] for s in result_no_sub.screenshots)















    @patch("preview_system.subprocess.run")







    def test_pp24b_scene_preview_capture_failure(self, mock_run, tmp_path):







        """PP-24b: capture全失敗→screenshotsは空"""







        gen = SubtitlePreviewGenerator(tmp_path / "previews")







        mock_run.return_value = _mock_subprocess_ok(returncode=1, stderr="error")















        result = gen.generate_scene_previews(







            "fail_scene", tmp_path / "video.mp4", None, ["00:00:01"]







        )







        assert result.screenshots == []























# ═══════════════════════════════════════════════════════════







# PP-20: Router validate_video_path







# ═══════════════════════════════════════════════════════════















class TestRouterValidation:







    """PP-20: validate_video_path セキュリティ"""















    def test_pp20_validate_video_path_security(self, tmp_path):







        """PP-20: None, パストラバーサル, 不正拡張子, 不在ファイル, 正常"""







        from routers.preview import validate_video_path, ALLOWED_VIDEO_DIR















        # None + allow_none=True → None







        assert validate_video_path(None, allow_none=True) is None















        # None + allow_none=False → ValueError







        with pytest.raises(ValueError, match="required"):







            validate_video_path(None, allow_none=False)















        # パストラバーサル







        with pytest.raises(ValueError, match="outside"):







            validate_video_path("C:/Windows/System32/cmd.exe")















        # 不正拡張子 (ALLOWED_VIDEO_DIR内のファイルだが.txtなど)







        txt_file = ALLOWED_VIDEO_DIR / "test_invalid.txt"







        try:







            txt_file.write_text("test", encoding="utf-8")







            with pytest.raises(ValueError, match="extension"):







                validate_video_path(str(txt_file))







        finally:







            txt_file.unlink(missing_ok=True)















        # 存在しないファイル







        with pytest.raises(FileNotFoundError):







            validate_video_path(str(ALLOWED_VIDEO_DIR / "nonexistent.mp4"))















    def test_pp20b_validate_video_path_valid(self, tmp_path):







        """PP-20b: 正常なパス→resolved Path"""







        from routers.preview import validate_video_path, ALLOWED_VIDEO_DIR















        # 正常ファイル作成







        valid_file = ALLOWED_VIDEO_DIR / "temp" / "test_valid.mp4"







        try:







            valid_file.parent.mkdir(parents=True, exist_ok=True)







            valid_file.write_bytes(b"\x00" * 100)







            result = validate_video_path(str(valid_file))







            assert result is not None







            assert result.exists()







            assert result.suffix == ".mp4"







        finally:







            valid_file.unlink(missing_ok=True)























# ═══════════════════════════════════════════════════════════







# PP-29, PP-30: services/preview_report_generator.py







# ═══════════════════════════════════════════════════════════















class TestServicesReport:







    """PP-29, PP-30: RetentionMap可視化レポート"""















    def test_pp29_risk_color_thresholds(self):







        """PP-29: risk_score閾値 80→赤, 50→黄, 20→緑"""







        from services.preview_report_generator import PreviewReportGenerator















        gen = PreviewReportGenerator()







        # >70 → 赤







        assert gen._get_risk_color(80) == "#ef4444"







        assert gen._get_risk_color(71) == "#ef4444"







        # >40 → 黄







        assert gen._get_risk_color(50) == "#eab308"







        assert gen._get_risk_color(41) == "#eab308"







        # ≤40 → 緑







        assert gen._get_risk_color(40) == "#22c55e"







        assert gen._get_risk_color(20) == "#22c55e"







        assert gen._get_risk_color(0) == "#22c55e"







        # 境界: 70







        assert gen._get_risk_color(70) == "#eab308"















    def test_pp29_risk_color_fallback_and_boundary(self):







        """例外値（None、文字列などの不正な型）や、境界外（負の値、100超）のフォールバック検証"""







        from services.preview_report_generator import PreviewReportGenerator















        gen = PreviewReportGenerator()















        # None の場合 → デフォルト値（緑）







        assert gen._get_risk_color(None) == "#22c55e"















        # 不正な文字列の場合 → デフォルト値（緑）







        assert gen._get_risk_color("invalid") == "#22c55e"















        # 境界外（負の値: -10） → 緑







        assert gen._get_risk_color(-10) == "#22c55e"















        # 境界外（100を超える値: 150） → 赤







        assert gen._get_risk_color(150) == "#ef4444"















        # 小数（45.5） → 整数に変換されて判定（黄）







        assert gen._get_risk_color(45.5) == "#eab308"















    def test_pp30_retention_report_html(self, tmp_path):







        """PP-30: RetentionMapReport→HTML生成。segments, suggestions分岐"""







        from plugins.retention_map_plugin import (







            RetentionMapReport, RetentionSegment, ReengagementSuggestion







        )







        from services.preview_report_generator import PreviewReportGenerator















        gen = PreviewReportGenerator()







        # output_dirをtmp_pathに変更







        gen.output_dir = tmp_path / "reports"







        gen._ensure_dir()







        assert gen.output_dir.exists()















        report = RetentionMapReport(







            video_id="test_vid_001",







            total_duration_sec=30,







            segments=[







                RetentionSegment(







                    start_time=0, end_time=10, risk_score=15,







                    visual_change=True, audio_change=True, text_change=False,







                    dopamine_hit=True,







                ),







                RetentionSegment(







                    start_time=10, end_time=20, risk_score=75,







                    visual_change=False, audio_change=False, text_change=False,







                    dopamine_hit=False,







                ),







                RetentionSegment(







                    start_time=20, end_time=30, risk_score=35,







                    visual_change=True, audio_change=False, text_change=True,







                    dopamine_hit=True,







                ),







            ],







            suggestions=[







                ReengagementSuggestion(







                    timestamp_sec=15,







                    suggestion_type="ジャンプカット",







                    reason="変化なし区間",







                ),







            ],







            overall_risk_assessment="要注意",







        )















        html_path = gen.generate_html_report(report)















        assert Path(html_path).exists()







        content = Path(html_path).read_text(encoding="utf-8")







        # 基本構造







        assert "test_vid_001" in content







        assert "要注意" in content







        # ヒートマップセグメント







        assert "#ef4444" in content  # risk=75 → 赤







        assert "#22c55e" in content  # risk=15 → 緑







        # ドーパミンヒットマーカー







        assert "⭐" in content







        # 提案セクション







        assert "ジャンプカット" in content







        assert "変化なし区間" in content







        assert "15秒付近" in content















    def test_pp30b_retention_report_no_suggestions(self, tmp_path):







        """PP-30b: suggestions空→「提案はありません」表示"""







        from plugins.retention_map_plugin import RetentionMapReport, RetentionSegment







        from services.preview_report_generator import PreviewReportGenerator















        gen = PreviewReportGenerator()







        gen.output_dir = tmp_path / "reports"







        gen._ensure_dir()















        report = RetentionMapReport(







            video_id="no_sug",







            total_duration_sec=10,







            segments=[







                RetentionSegment(







                    start_time=0, end_time=10, risk_score=10,







                    dopamine_hit=True,







                ),







            ],







            suggestions=[],







            overall_risk_assessment="安全",







        )















        html_path = gen.generate_html_report(report)







        content = Path(html_path).read_text(encoding="utf-8")







        assert "追加の演出提案はありません" in content















    def test_pp30c_retention_report_performance_benchmark(self, tmp_path):







        """PP-30c: 大量セグメントに対するHTML生成のパフォーマンスベンチマーク"""







        import time







        from plugins.retention_map_plugin import (







            RetentionMapReport, RetentionSegment, ReengagementSuggestion







        )







        from services.preview_report_generator import PreviewReportGenerator















        gen = PreviewReportGenerator()







        gen.output_dir = tmp_path / "reports"







        gen._ensure_dir()















        # 10,000セグメント、500件の提案を作成







        segments = []







        for i in range(10000):







            segments.append(







                RetentionSegment(







                    start_time=i,







                    end_time=i + 1,







                    risk_score=(i % 100),







                    visual_change=(i % 2 == 0),







                    audio_change=(i % 3 == 0),







                    text_change=(i % 4 == 0),







                    dopamine_hit=(i % 10 == 0),







                )







            )















        suggestions = []







        for i in range(500):







            suggestions.append(







                ReengagementSuggestion(







                    timestamp_sec=i * 20,







                    suggestion_type="カット演出" if i % 2 == 0 else "ズーム",







                    reason="動きが少ないため"







                )







            )















        report = RetentionMapReport(







            video_id="perf_test_vid",







            total_duration_sec=10000,







            segments=segments,







            suggestions=suggestions,







            overall_risk_assessment="高速検証用",







        )















        start_time = time.perf_counter()







        html_path = gen.generate_html_report(report)







        end_time = time.perf_counter()







        duration = end_time - start_time















        print(f"\n[Benchmark] HTML Report Generation took {duration:.4f} seconds for 10000 segments and 500 suggestions.")







        







        assert Path(html_path).exists()







        content = Path(html_path).read_text(encoding="utf-8")







        assert "perf_test_vid" in content







        assert "高速検証用" in content







        assert duration < 1.0















    def test_get_risk_color_additional_edge_cases(self):







        """_get_risk_color の追加エッジケース（数値文字列、浮動小数点数、空文字、不正オブジェクト等）"""







        from services.preview_report_generator import PreviewReportGenerator















        gen = PreviewReportGenerator()















        # 数値文字列







        assert gen._get_risk_color("85") == "#ef4444"







        assert gen._get_risk_color("55") == "#eab308"







        assert gen._get_risk_color("25") == "#22c55e"







        assert gen._get_risk_color("-5") == "#22c55e"







        assert gen._get_risk_color("120") == "#ef4444"















        # 浮動小数点数 (境界値判定)







        assert gen._get_risk_color(40.0) == "#22c55e"







        assert gen._get_risk_color(40.1) == "#22c55e"







        assert gen._get_risk_color(41.0) == "#eab308"







        assert gen._get_risk_color(70.0) == "#eab308"







        assert gen._get_risk_color(70.9) == "#eab308"







        assert gen._get_risk_color(71.0) == "#ef4444"















        # 空文字







        assert gen._get_risk_color("") == "#22c55e"















        # 不正オブジェクト (リスト, 辞書, クラスインスタンスなど)







        assert gen._get_risk_color([]) == "#22c55e"







        assert gen._get_risk_color({}) == "#22c55e"







        assert gen._get_risk_color(object()) == "#22c55e"















    def test_generate_html_report_special_characters_and_types(self, tmp_path):







        """generate_html_report で特殊文字や欠落属性、異常値が渡された場合の挙動"""







        from unittest.mock import MagicMock







        from plugins.retention_map_plugin import (







            RetentionMapReport, RetentionSegment, ReengagementSuggestion







        )







        from services.preview_report_generator import PreviewReportGenerator















        gen = PreviewReportGenerator()







        gen.output_dir = tmp_path / "reports"







        gen._ensure_dir()















        # 有効なオブジェクトを作成してから、内部の値を不正な型に書き換えて検証







        seg1 = RetentionSegment(







            start_time=0, end_time=10, risk_score=10, dopamine_hit=True







        )







        try:







            # Pydantic v2では属性代入でも型チェックが走る場合があるため、Mockオブジェクトでラップするか直接書き換える







            # 安全のためMagicMockを使用







            seg1_mock = MagicMock(spec=RetentionSegment)







            seg1_mock.start_time = 0







            seg1_mock.end_time = 10







            seg1_mock.risk_score = "invalid_score"







            seg1_mock.dopamine_hit = None







            seg1 = seg1_mock







        except Exception:







            pass















        seg2 = RetentionSegment(







            start_time=10, end_time=20, risk_score=999, dopamine_hit=True







        )















        # HTMLタグや特殊文字を含むデータ







        report = RetentionMapReport(







            video_id="special_char_vid_123",







            total_duration_sec=20,







            segments=[seg1, seg2],







            suggestions=[







                ReengagementSuggestion(







                    timestamp_sec=5,







                    suggestion_type="<b>太字演出</b>",







                    reason="\"引用符\" & <script>alert(1)</script>"







                )







            ],







            overall_risk_assessment="<critical>危険</critical>"







        )















        html_path = gen.generate_html_report(report)







        assert Path(html_path).exists()







        content = Path(html_path).read_text(encoding="utf-8")















        # 特殊文字がそのまま埋め込まれる（または適切に処理される）ことを確認







        assert "special_char_vid_123" in content







        assert "<b>太字演出</b>" in content







        assert "\"引用符\" & <script>alert(1)</script>" in content







        assert "<critical>危険</critical>" in content















        # 不正なrisk_scoreに対するデフォルトカラーのフォールバック (#22c55e)







        # 999に対する赤 (#ef4444)







        assert "#22c55e" in content







        assert "#ef4444" in content























# ═══════════════════════════════════════════════════════════







# 構成テスト







# ═══════════════════════════════════════════════════════════















class TestFactory:







    """create_preview_system"""















    def test_create_preview_system_returns_dict(self, tmp_path):







        """ファクトリー関数→3コンポーネントのdict"""







        result = create_preview_system(tmp_path)















        assert "subtitle_generator" in result







        assert "telop_generator" in result







        assert "report_generator" in result







        assert isinstance(result["subtitle_generator"], SubtitlePreviewGenerator)







        assert isinstance(result["telop_generator"], TelopPreviewGenerator)







        assert isinstance(result["report_generator"], SystemReportGenerator)























# ═══════════════════════════════════════════════════════════







# サムネイル生成・検証および StageBoundAgent 連携のテスト







# ═══════════════════════════════════════════════════════════















class TestServicesReportThumbnail:







    """PreviewReportGenerator のサムネイル生成・検証および StageBoundAgent 連携のテスト"""















    def test_thumbnail_generation_and_validation_success(self, tmp_path):







        from services.preview_report_generator import PreviewReportGenerator







        







        gen = PreviewReportGenerator()







        gen.output_dir = tmp_path / "reports"







        gen._ensure_dir()







        







        thumb_path = gen.output_dir / "test_thumb.png"







        gen.generate_thumbnail(thumb_path, text="Test Success")







        







        # 検証が成功すること







        result = gen.validate_thumbnail(thumb_path)







        assert result["width"] == 1280







        assert result["height"] == 720







        assert result["size_bytes"] > 0







        assert Path(result["path"]) == thumb_path















    def test_thumbnail_validation_failures(self, tmp_path):







        from services.preview_report_generator import PreviewReportGenerator







        







        gen = PreviewReportGenerator()







        gen.output_dir = tmp_path / "reports"







        gen._ensure_dir()







        







        # 1. 存在しないファイル







        with pytest.raises(FileNotFoundError):







            gen.validate_thumbnail(gen.output_dir / "nonexistent.png")







            







        # 2. 解像度不足 (1280x720 未満)







        small_path = gen.output_dir / "small.png"







        gen.generate_thumbnail(small_path, width=800, height=600)







        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):







            gen.validate_thumbnail(small_path)







            







        # 3. アスペクト比が 16:9 でない







        bad_aspect_path = gen.output_dir / "bad_aspect.png"







        gen.generate_thumbnail(bad_aspect_path, width=1280, height=800)







        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):







            gen.validate_thumbnail(bad_aspect_path)







            







        # 4. 破損画像







        corrupt_path = gen.output_dir / "corrupt.png"







        corrupt_path.write_bytes(b"INVALID_IMAGE_DATA")







        with pytest.raises(ValueError, match="Image is corrupted"):







            gen.validate_thumbnail(corrupt_path)







            







        # 5. ファイルサイズ制限 (4MB以上)







        large_path = gen.output_dir / "large.png"







        gen.generate_thumbnail(large_path)







        # モックでファイルサイズを大きく見せる







        with patch.object(Path, "stat") as mock_stat:







            mock_stat.return_value.st_size = 5 * 1024 * 1024







            with pytest.raises(ValueError, match="File size exceeds 4MB limit"):







                gen.validate_thumbnail(large_path)















    def test_thumbnail_validation_failed_to_load_for_resolution_check(self, tmp_path):







        from services.preview_report_generator import PreviewReportGenerator







        from PIL import Image















        gen = PreviewReportGenerator()







        gen.output_dir = tmp_path / "reports"







        gen._ensure_dir()















        dummy_path = gen.output_dir / "dummy.png"







        gen.generate_thumbnail(dummy_path)















        original_open = Image.open







        calls = []















        def mock_open(*args, **kwargs):







            calls.append(args)







            if len(calls) == 1:







                return original_open(*args, **kwargs)







            else:







                raise OSError("Simulated load failure for resolution check")















        with patch("PIL.Image.open", side_effect=mock_open):







            with pytest.raises(ValueError, match="Failed to load image for resolution check"):







                gen.validate_thumbnail(dummy_path)















    @pytest.mark.asyncio







    async def test_stage_bound_agent_integration_success(self, tmp_path):







        import asyncio







        from services.preview_report_generator import PreviewReportGenerator







        from agents.stage_bound_agent import StageBoundAgent







        







        db_path = str(tmp_path / "tasks.db")







        gen = PreviewReportGenerator()







        gen.output_dir = tmp_path / "reports"







        gen._ensure_dir()







        







        # エージェント構築







        agent = StageBoundAgent(stage_name="thumbnail_gen", db_path=db_path)







        







        # タスク登録







        task_id = "task_001"







        await agent.register_task(task_id, initial_status="READY")







        







        # エージェント実行







        await agent.start(process_func=gen.resolve_thumbnail_task)







        







        # タスク完了を待つ (タイムアウト 2秒)







        for _ in range(40):







            status = await agent.get_task_status(task_id)







            if status == "COMPLETED":







                break







            await asyncio.sleep(0.05)







            







        status = await agent.get_task_status(task_id)







        assert status == "COMPLETED"







        







        # 結果の確認







        conn = agent._get_conn()







        cursor = conn.execute("SELECT result, error FROM tasks WHERE id = ?", (task_id,))







        row = cursor.fetchone()







        assert row is not None







        result_str = row[0]







        error_str = row[1]







        assert error_str is None







        







        result_data = json.loads(result_str)







        assert result_data["width"] == 1280







        assert result_data["height"] == 720
        conn.close()







        







        await agent.stop()















    @pytest.mark.asyncio







    async def test_stage_bound_agent_integration_retry_and_fail(self, tmp_path):







        import asyncio







        from services.preview_report_generator import PreviewReportGenerator







        from agents.stage_bound_agent import StageBoundAgent







        







        db_path = str(tmp_path / "tasks.db")







        gen = PreviewReportGenerator()







        







        agent = StageBoundAgent(stage_name="thumbnail_gen", db_path=db_path)







        







        # 常に失敗するタスクハンドラ







        async def fail_task(task_id):







            raise RuntimeError("Simulation Failure")







            







        task_id = "task_fail_002"







        # max_retries = 2 で登録 (計3回実行されるはず)







        await agent.register_task(task_id, initial_status="READY", max_retries=2)







        







        await agent.start(process_func=fail_task)







        







        # 失敗して FAILED になるのを待つ







        for _ in range(40):







            status = await agent.get_task_status(task_id)







            if status == "FAILED":







                break







            await asyncio.sleep(0.05)







            







        status = await agent.get_task_status(task_id)







        assert status == "FAILED"







        







        # リトライ回数とエラーの確認







        conn = agent._get_conn()







        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))







        row = cursor.fetchone()







        assert row is not None







        retry_count = row[0]







        error_str = row[1]







        assert retry_count == 2







        assert "Simulation Failure" in error_str
        conn.close()







        







        await agent.stop()















    def test_thumbnail_generation_with_long_text_autoscaling(self, tmp_path):







        from services.preview_report_generator import PreviewReportGenerator







        







        gen = PreviewReportGenerator()







        gen.output_dir = tmp_path / "reports"







        gen._ensure_dir()







        







        # 1. 非常に長いテキストの自動スケーリング検証







        long_text = "This is an extremely long preview text that will definitely exceed the standard 85% width boundary of the thumbnail image, triggering the auto-scaling loop."







        thumb_path = gen.output_dir / "long_text_thumb.png"







        gen.generate_thumbnail(thumb_path, text=long_text)







        







        result = gen.validate_thumbnail(thumb_path)







        assert result["width"] == 1280







        assert result["height"] == 720







        assert (result["width"] / result["height"]) == 16 / 9







        assert result["size_bytes"] < 4 * 1024 * 1024







        







        # 2. text=None の安全なフォールバック







        none_thumb = gen.output_dir / "none_thumb.png"







        gen.generate_thumbnail(none_thumb, text=None)







        result_none = gen.validate_thumbnail(none_thumb)







        assert result_none["width"] == 1280







        







        # 3. text が文字列以外（例: 辞書型）の場合の安全なフォールバック







        dict_thumb = gen.output_dir / "dict_thumb.png"







        gen.generate_thumbnail(dict_thumb, text={"key": "val"})







        result_dict = gen.validate_thumbnail(dict_thumb)







        assert result_dict["width"] == 1280















    def test_thumbnail_generation_invalid_output_path(self, tmp_path):

        from services.preview_report_generator import PreviewReportGenerator

        

        gen = PreviewReportGenerator()

        gen.output_dir = tmp_path / "reports"

        gen._ensure_dir()

        

        # ディレクトリパスを指定した際のエラー送出確認

        with pytest.raises(ValueError, match="Output path cannot be a directory"):

            gen.generate_thumbnail(gen.output_dir, text="Should Fail")



    def test_thumbnail_generation_invalid_dimensions(self, tmp_path):

        from services.preview_report_generator import PreviewReportGenerator

        gen = PreviewReportGenerator()

        out = tmp_path / "fail.png"



        # 非整数

        with pytest.raises(ValueError, match="must be integers"):

            gen.generate_thumbnail(out, width="invalid")

        with pytest.raises(ValueError, match="must be integers"):

            gen.generate_thumbnail(out, height=None)



        # 負の数 / 0

        with pytest.raises(ValueError, match="must be positive integers"):

            gen.generate_thumbnail(out, width=-10)

        with pytest.raises(ValueError, match="must be positive integers"):

            gen.generate_thumbnail(out, height=0)



    @patch("os.path.exists", return_value=False)

    def test_thumbnail_generation_no_fonts_fallback(self, mock_exists, tmp_path):

        from services.preview_report_generator import PreviewReportGenerator

        gen = PreviewReportGenerator()

        out = tmp_path / "default_font.png"

        gen.generate_thumbnail(out, text="Default Font Test")

        assert out.exists()



    def test_thumbnail_generation_font_load_oserror_fallback(self, tmp_path):

        from services.preview_report_generator import PreviewReportGenerator

        from PIL import ImageFont

        gen = PreviewReportGenerator()

        out = tmp_path / "oserror_font.png"

        

        original_truetype = ImageFont.truetype



        def mock_truetype(fp, *args, **kwargs):

            if isinstance(fp, str):

                raise OSError("Load failed for path")

            return original_truetype(fp, *args, **kwargs)

        

        with patch("os.path.exists", return_value=True),              patch("PIL.ImageFont.truetype", side_effect=mock_truetype):

            gen.generate_thumbnail(out, text="OS Error Font Test")

        assert out.exists()



    def test_thumbnail_generation_textbbox_attribute_error_with_getsize(self, tmp_path):

        from services.preview_report_generator import PreviewReportGenerator

        from PIL import ImageFont

        gen = PreviewReportGenerator()

        out = tmp_path / "ae_getsize.png"



        real_default_font = ImageFont.load_default()



        class FontProxyWithGetSize:

            def __init__(self, real_font):

                self._real_font = real_font

            def getsize(self, text):

                return (100, 20)

            def __getattr__(self, name):

                return getattr(self._real_font, name)



        proxy_font = FontProxyWithGetSize(real_default_font)



        with patch("PIL.ImageDraw.ImageDraw.textbbox", side_effect=AttributeError),              patch("PIL.ImageFont.load_default", return_value=proxy_font),              patch("os.path.exists", return_value=False):

            gen.generate_thumbnail(out, text="AE GetSize Test")

        

        assert out.exists()



    def test_thumbnail_generation_textbbox_attribute_error_no_getsize(self, tmp_path):

        from services.preview_report_generator import PreviewReportGenerator

        from PIL import ImageFont

        gen = PreviewReportGenerator()

        out = tmp_path / "ae_no_getsize.png"



        real_default_font = ImageFont.load_default()



        class FontProxyNoGetSize:

            def __init__(self, real_font):

                self._real_font = real_font

            def __getattr__(self, name):

                if name == "getsize":

                    raise AttributeError("getsize not available")

                return getattr(self._real_font, name)



        proxy_font = FontProxyNoGetSize(real_default_font)



        with patch("PIL.ImageDraw.ImageDraw.textbbox", side_effect=AttributeError),              patch("PIL.ImageFont.load_default", return_value=proxy_font),              patch("os.path.exists", return_value=False):

            gen.generate_thumbnail(out, text="AE No GetSize Test")

        

        assert out.exists()



    def test_thumbnail_generation_resize_loop_errors(self, tmp_path):

        from services.preview_report_generator import PreviewReportGenerator

        gen = PreviewReportGenerator()

        out = tmp_path / "resize_error.png"

        long_text = "A" * 500



        from PIL import ImageFont

        original_truetype = ImageFont.truetype

        call_count = 0



        def mock_truetype(fp, size, *args, **kwargs):

            nonlocal call_count

            call_count += 1

            if call_count > 1:

                raise OSError("Resize load failed")

            return original_truetype(fp, size, *args, **kwargs)



        with patch("os.path.exists", return_value=True),              patch("PIL.ImageFont.truetype", side_effect=mock_truetype):

            gen.generate_thumbnail(out, text=long_text)

        

        assert out.exists()



    def test_thumbnail_generation_resize_loop_font_not_loaded_break(self, tmp_path):

        from services.preview_report_generator import PreviewReportGenerator

        gen = PreviewReportGenerator()

        out = tmp_path / "resize_break.png"

        long_text = "A" * 500



        from PIL import ImageFont

        original_truetype = ImageFont.truetype

        call_count = 0



        def mock_truetype(fp, size, *args, **kwargs):

            nonlocal call_count

            call_count += 1

            if call_count == 1:

                return original_truetype(fp, size, *args, **kwargs)

            raise OSError("Resize failed completely")



        with patch("os.path.exists", return_value=True),              patch("PIL.ImageFont.truetype", side_effect=mock_truetype):

            gen.generate_thumbnail(out, text=long_text)

        

        assert out.exists()



    def test_thumbnail_generation_overwrite_existing(self, tmp_path):

        from services.preview_report_generator import PreviewReportGenerator

        gen = PreviewReportGenerator()

        out = tmp_path / "overwrite.png"

        

        out.write_bytes(b"EXISTING_DATA")

        assert out.exists()

        

        gen.generate_thumbnail(out, text="Overwrite Test")

        assert out.exists()

        

        result = gen.validate_thumbnail(out)

        assert result["size_bytes"] > 13



    def test_thumbnail_generation_save_oserror(self, tmp_path):

        from services.preview_report_generator import PreviewReportGenerator

        gen = PreviewReportGenerator()

        out = tmp_path / "save_fail.png"



        with patch("PIL.Image.Image.save", side_effect=OSError("Disk full")):

            with pytest.raises(OSError, match="Disk full"):

                gen.generate_thumbnail(out, text="Save Fail Test")



    def test_thumbnail_generation_cleanup_exception_on_save_error(self, tmp_path):

        from services.preview_report_generator import PreviewReportGenerator

        gen = PreviewReportGenerator()

        out = tmp_path / "cleanup_fail.png"



        original_unlink = Path.unlink



        def mock_save(*args, **kwargs):

            # argsの中から一時ファイルのPathオブジェクトを見つける

            from pathlib import Path

            temp_path = None

            for arg in args:

                if isinstance(arg, (Path, str)) and arg != "PNG":

                    temp_path = Path(arg)

                    break

            if temp_path:

                temp_path.write_bytes(b"")

            raise OSError("Save failed")



        def mock_unlink(self_path, *args, **kwargs):

            if ".tmp" in self_path.name:

                raise OSError("Unlink failed")

            return original_unlink(self_path, *args, **kwargs)



        with patch("PIL.Image.Image.save", side_effect=mock_save),              patch.object(Path, "unlink", mock_unlink):

            with pytest.raises(OSError, match="Save failed"):

                gen.generate_thumbnail(out, text="Cleanup Fail Test")

    def test_report_generator_path_uri_conversion(self, tmp_path):
        import os
        from preview_system import PreviewReportGenerator, ScenePreview, PreviewReport
        
        gen = PreviewReportGenerator(tmp_path)
        
        # 絶対パスをシミュレート
        abs_path = "C:/absolute/path/to/image.jpg" if os.name == 'nt' else "/absolute/path/to/image.jpg"
        
        scene = ScenePreview(
            scene_name="scene1",
            video_path="video.mp4",
            subtitle_path="subtitle.srt",
            screenshots=[
                {"timestamp": "00:01:00", "path": abs_path, "with_subtitle": True}
            ]
        )
        report = PreviewReport(title="Path Conversion Test", scenes=[scene])
        
        md_content = gen.generate(report)
        assert "file://" in md_content
        assert "image.jpg" in md_content

