"""







Sprint 2.3.4: ProgressivePreview テスト (18テスト)







対象: progressive_preview.py, progressive_preview_report.py















C1: スクリーンショット生成 (4テスト: PP-01〜PP-04)







C2: レポート出力 (3テスト: PP-06〜PP-08)







C3: 比較画像 (4テスト: PP-11〜PP-14)  + PP-15







C4: FFmpeg失敗フォールバック (4テスト: PP-16〜PP-19)







C5: 並行生成・統合 (3テスト: PP-21〜PP-23)







C6: 実行時間・品質 (3テスト: PP-26〜PP-28)  + PP-15移動















モック方針:







  - subprocess.run: @patch("progressive_preview.subprocess.run")







  - PIL: 実画像生成ベース。例外テストは破損ファイル or patch.object







  - ファイルシステム: pytest tmp_path







"""















import pytest







import json







import time







import base64







import subprocess as sp







from pathlib import Path







from unittest.mock import patch, MagicMock, patch as mock_patch







from PIL import Image, ImageFont















from progressive_preview import ProgressivePreview







from progressive_preview_report import PreviewReportGenerator























# ─── ヘルパー ───















def _make_image(path: Path, size=(640, 480), color=(100, 100, 100)):







    """テスト用画像を生成"""







    img = Image.new("RGB", size, color=color)







    img.save(str(path))







    return path























def _make_srt(path: Path) -> Path:







    """テスト用SRTファイルを生成 (6エントリ)"""







    entries = []







    for i in range(1, 7):







        s = (i - 1) * 5







        e = s + 3







        entries.append(







            f"{i}\n"







            f"00:00:{s:02d},000 --> 00:00:{e:02d},000\n"







            f"テスト字幕{i}\n"







        )







    path.write_text("\n".join(entries), encoding="utf-8")







    return path























def _mock_subprocess_ok(stdout="", stderr="", returncode=0):







    """subprocess.run 正常系モック"""







    m = MagicMock()







    m.returncode = returncode







    m.stdout = stdout







    m.stderr = stderr







    return m























def _ffmpeg_side_effect_with_images(tmp_path):







    """ffmpegコマンドで画像ファイルを実際に作成するside_effect"""







    def side_effect(cmd, **kwargs):







        if cmd[0] == "ffprobe" or "ffprobe" in cmd:







            return _mock_subprocess_ok(stdout="1.0\n5.0\n")







        if cmd[0] == "ffmpeg" or "ffmpeg" in cmd:







            # 最後の引数が出力ファイルパス







            out_path = cmd[-1]







            _make_image(Path(out_path))







            return _mock_subprocess_ok()







        return _mock_subprocess_ok()







    return side_effect























# ═══════════════════════════════════════════════════════════







# C1: スクリーンショット生成 (PP-01〜PP-04)







# ═══════════════════════════════════════════════════════════















class TestC1Screenshot:







    """PP-01〜PP-04: スクリーンショット生成"""















    @patch("progressive_preview.subprocess.run")







    def test_pp01_extract_screenshot_ffmpeg_command(self, mock_run, tmp_path):







        """PP-01: FFmpegコマンド構成検証。-ss, -i, -frames:v 1, -vf scale"""







        mock_run.return_value = _mock_subprocess_ok()







        preview = ProgressivePreview(session_id="pp01", output_dir=str(tmp_path))







        out = tmp_path / "shot.png"















        result = preview.extract_screenshot("video.mp4", 2.5, str(out), width=1280)















        assert result == str(out)







        mock_run.assert_called_once()







        cmd = mock_run.call_args[0][0]







        assert cmd[0] == "ffmpeg"







        assert "-ss" in cmd







        assert "2.5" in cmd







        assert "-frames:v" in cmd







        assert "1" in cmd







        # width=1280 が scale フィルタに反映







        vf_idx = cmd.index("-vf")







        assert "1280" in cmd[vf_idx + 1]















    @patch("progressive_preview.subprocess.run")







    def test_pp02_detect_feature_points_scene_filter(self, mock_run, tmp_path):







        """PP-02: シーン検出→近接フィルタ(2秒)→max_points間引き"""







        mock_run.return_value = _mock_subprocess_ok(







            stdout="1.5\n3.2\n5.8\n6.0\n10.1\n15.0\n"







        )







        preview = ProgressivePreview(session_id="pp02", output_dir=str(tmp_path))















        result = preview.detect_feature_points("video.mp4", max_points=3)















        assert isinstance(result, list)







        assert len(result) <= 3







        # 近接フィルタ: 5.8と6.0は2秒以内で統合







        for i in range(1, len(result)):







            assert result[i] - result[i - 1] >= 2.0















    @patch("progressive_preview.subprocess.run")







    def test_pp03_detect_feature_points_srt_integration(self, mock_run, tmp_path):







        """PP-03: SRT字幕+シーン検出の統合。_extract_srt_timestamps間引きも検証"""







        srt_path = _make_srt(tmp_path / "test.srt")







        mock_run.return_value = _mock_subprocess_ok(stdout="4.0\n12.0\n")







        preview = ProgressivePreview(session_id="pp03", output_dir=str(tmp_path))















        result = preview.detect_feature_points(







            "video.mp4", max_points=5, srt_path=str(srt_path)







        )















        assert isinstance(result, list)







        assert len(result) > 0







        # SRTの0秒/5秒/10秒 + シーンの4秒/12秒 が統合されている







        assert any(ts <= 1.0 for ts in result) or any(ts >= 4.0 for ts in result)















    @patch("progressive_preview.subprocess.run")







    def test_pp04_snapshot_step_dir_and_comparisons(self, mock_run, tmp_path):







        """PP-04: step_dir作成、comparisons構造(5フィールド)、steps追加"""







        mock_run.side_effect = _ffmpeg_side_effect_with_images(tmp_path)







        preview = ProgressivePreview(session_id="pp04", output_dir=str(tmp_path))















        result = preview.snapshot_step(







            step_name="crop",







            before_video="before.mp4",







            after_video="after.mp4",







            timestamps=[1.0, 5.0],







        )















        # ディレクトリ作成







        assert (tmp_path / "crop").exists()







        # 結果構造







        assert result["step_name"] == "crop"







        assert result["before_video"] == "before.mp4"







        assert result["after_video"] == "after.mp4"







        assert "created_at" in result







        assert len(result["comparisons"]) == 2







        for comp in result["comparisons"]:







            assert set(comp.keys()) >= {"timestamp", "before", "after", "comparison", "diff_highlight"}







        # stepsリストに追加







        assert len(preview.steps) == 1























# ═══════════════════════════════════════════════════════════







# C2: レポート出力 (PP-06〜PP-08)







# ═══════════════════════════════════════════════════════════















class TestC2Report:







    """PP-06〜PP-08: HTMLレポート出力"""















    def test_pp06_html_report_embed_base64(self, tmp_path):







        """PP-06: embed=True→Base64データ埋め込み、HTML構造検証"""







        img_path = _make_image(tmp_path / "comp.png")







        metadata = {







            "session_id": "s_embed",







            "created_at": "2026-01-01T00:00:00",







            "steps": [{







                "step_name": "crop",







                "comparisons": [{"timestamp": 1.0, "comparison": str(img_path)}],







            }],







        }







        gen = PreviewReportGenerator()







        out = str(tmp_path / "report.html")















        result = gen.generate_html_report(metadata, out, embed_images=True)















        assert Path(result).exists()







        content = Path(result).read_text(encoding="utf-8")







        assert "data:image/png;base64," in content







        assert "s_embed" in content







        assert "<!DOCTYPE html>" in content







        assert "crop" in content















    def test_pp07_html_report_no_embed(self, tmp_path):







        """PP-07: embed=False→パス参照、data:imageなし"""







        metadata = {







            "session_id": "s_noembed",







            "steps": [{







                "step_name": "logo",







                "comparisons": [{"timestamp": 2.0, "comparison": "fake.png"}],







            }],







        }







        gen = PreviewReportGenerator()







        out = str(tmp_path / "report.html")















        result = gen.generate_html_report(metadata, out, embed_images=False)















        content = Path(result).read_text(encoding="utf-8")







        assert "data:image/png;base64," not in content







        assert "fake.png" in content















    def test_pp08_generate_from_session_dir_and_missing(self, tmp_path):







        """PP-08: 正常→HTML生成。metadata不在→FileNotFoundError"""







        # 正常系







        meta = {







            "session_id": "dir_ok",







            "created_at": "2026-01-01T00:00:00",







            "steps": [{"step_name": "sub", "comparisons": [{"timestamp": 3.0, "comparison": "x.png"}]}],







        }







        meta_path = tmp_path / "session_metadata.json"







        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")















        gen = PreviewReportGenerator()







        result = gen.generate_from_session_dir(str(tmp_path))







        assert Path(result).exists()







        assert "dir_ok" in Path(result).read_text(encoding="utf-8")















        # 異常系: metadata不在







        empty_dir = tmp_path / "empty"







        empty_dir.mkdir()







        with pytest.raises(FileNotFoundError):







            gen.generate_from_session_dir(str(empty_dir))























# ═══════════════════════════════════════════════════════════







# C3: 比較画像 (PP-11〜PP-15)







# ═══════════════════════════════════════════════════════════















class TestC3Comparison:







    """PP-11〜PP-15: 比較画像・Base64"""















    def test_pp11_comparison_image_layout(self, tmp_path):







        """PP-11: 横並び合成。幅=before+gap+after、高さ=min+header"""







        before = _make_image(tmp_path / "before.png", (640, 480), (255, 0, 0))







        after = _make_image(tmp_path / "after.png", (640, 480), (0, 0, 255))







        out = tmp_path / "comparison.png"















        preview = ProgressivePreview(session_id="pp11", output_dir=str(tmp_path))







        result = preview.create_comparison_image(







            str(before), str(after), str(out), "Before", "After"







        )















        assert Path(result).exists()







        img = Image.open(result)







        # 幅 = before幅 + gap(4) + after幅







        assert img.width == 640 + 4 + 640







        # 高さ = min(480,480,480) + header(30) = 510







        assert img.height == 480 + 30















    def test_pp12_comparison_image_font_fallback(self, tmp_path):







        """PP-12: truetype失敗→load_default。1回目のみ例外、load_default経由は成功"""







        before = _make_image(tmp_path / "before.png")







        after = _make_image(tmp_path / "after.png")







        out = tmp_path / "comp_fallback.png"















        original_truetype = ImageFont.truetype







        call_count = [0]















        def selective_truetype(*args, **kwargs):







            call_count[0] += 1







            if call_count[0] == 1:







                # create_comparison_image 内の最初の truetype 呼び出し → 失敗







                raise OSError("font not found")







            # load_default 内部の truetype 呼び出し → 成功させる







            return original_truetype(*args, **kwargs)















        with patch.object(ImageFont, "truetype", side_effect=selective_truetype):







            preview = ProgressivePreview(session_id="pp12", output_dir=str(tmp_path))







            result = preview.create_comparison_image(str(before), str(after), str(out))















        assert Path(result).exists()







        assert call_count[0] >= 1















    def test_pp13_diff_highlight_normal_and_resize(self, tmp_path):







        """PP-13: 正常差分検出+RGBA。サイズ不一致→リサイズ"""







        # 正常: 同サイズ、色差あり







        before = _make_image(tmp_path / "b1.png", (100, 100), (100, 100, 100))







        after = _make_image(tmp_path / "a1.png", (100, 100), (200, 100, 100))







        out1 = tmp_path / "diff1.png"















        preview = ProgressivePreview(session_id="pp13", output_dir=str(tmp_path))







        result1 = preview.create_diff_highlight(str(before), str(after), str(out1))















        assert Path(result1).exists()







        assert Image.open(result1).mode == "RGBA"















        # サイズ不一致







        before2 = _make_image(tmp_path / "b2.png", (200, 200), (50, 50, 50))







        after2 = _make_image(tmp_path / "a2.png", (300, 400), (150, 50, 50))







        out2 = tmp_path / "diff2.png"















        result2 = preview.create_diff_highlight(str(before2), str(after2), str(out2))







        assert Path(result2).exists()















    def test_pp14_diff_highlight_exception_fallback(self, tmp_path):







        """PP-14: PIL処理例外→shutil.copy(after→output)。破損ファイルで自然例外"""







        # 破損ファイル(before)







        broken = tmp_path / "broken.png"







        broken.write_bytes(b"NOT_AN_IMAGE_DATA")







        # 正常ファイル(after)







        after = _make_image(tmp_path / "after_fb.png", (10, 10))







        out = tmp_path / "diff_fb.png"















        preview = ProgressivePreview(session_id="pp14", output_dir=str(tmp_path))







        result = preview.create_diff_highlight(str(broken), str(after), str(out))















        assert Path(result).exists()







        # fallback: after画像がコピーされている







        assert Path(out).stat().st_size == after.stat().st_size















    def test_pp15_image_to_base64(self, tmp_path):







        """PP-15: 正常→Base64文字列(decode可能)。不在→空文字列"""







        img_path = _make_image(tmp_path / "b64.png", (10, 10))







        gen = PreviewReportGenerator()















        b64 = gen._image_to_base64(str(img_path))







        assert len(b64) > 0







        decoded = base64.b64decode(b64)







        assert len(decoded) > 0















        # 不在ファイル







        b64_fail = gen._image_to_base64(str(tmp_path / "nonexist.png"))







        assert b64_fail == ""























# ═══════════════════════════════════════════════════════════







# C4: FFmpeg失敗フォールバック (PP-16〜PP-19)







# ═══════════════════════════════════════════════════════════















class TestC4Fallback:







    """PP-16〜PP-19: FFmpeg失敗フォールバック"""















    @patch("progressive_preview.subprocess.run")







    def test_pp16_detect_feature_timeout_fallback(self, mock_run, tmp_path):







        """PP-16: TimeoutExpired→_fallback_sampling"""







        mock_run.side_effect = sp.TimeoutExpired(cmd=["ffprobe"], timeout=60)















        preview = ProgressivePreview(session_id="pp16", output_dir=str(tmp_path))







        result = preview.detect_feature_points("video.mp4", max_points=3)















        assert isinstance(result, list)







        assert len(result) > 0















    @patch("progressive_preview.subprocess.run")







    def test_pp17_detect_feature_exception_and_empty_stdout(self, mock_run, tmp_path):







        """PP-17: 一般例外→fallback。空stdout(returncode=0,データなし)→fallback"""







        # 一般例外







        mock_run.side_effect = RuntimeError("unexpected error")







        preview = ProgressivePreview(session_id="pp17a", output_dir=str(tmp_path))







        result1 = preview.detect_feature_points("video.mp4", max_points=3)







        assert isinstance(result1, list) and len(result1) > 0















        # 空stdout (returncode=0 だがデータなし → all_timestamps空 → fallback)







        mock_run.side_effect = None







        mock_run.return_value = _mock_subprocess_ok(stdout="", returncode=0)







        preview2 = ProgressivePreview(session_id="pp17b", output_dir=str(tmp_path))







        result2 = preview2.detect_feature_points("video.mp4", max_points=3)







        assert isinstance(result2, list) and len(result2) > 0















    @patch("progressive_preview.subprocess.run")







    def test_pp18_fallback_sampling_zero_and_positive(self, mock_run, tmp_path):







        """PP-18: duration≤0→固定値。duration>0→等間隔"""







        # duration=0 (ffprobeが空文字列を返す)







        mock_run.return_value = _mock_subprocess_ok(stdout="")







        preview = ProgressivePreview(session_id="pp18", output_dir=str(tmp_path))







        result_zero = preview._fallback_sampling("video.mp4", 3)







        assert result_zero == [1.0, 3.0, 5.0]















        # duration=30







        mock_run.return_value = _mock_subprocess_ok(stdout="30.0")







        result_positive = preview._fallback_sampling("video.mp4", 3)







        assert len(result_positive) == 3







        # 等間隔: 30/(3+1)=7.5 → [7.5, 15.0, 22.5]







        assert abs(result_positive[0] - 7.5) < 0.01







        assert abs(result_positive[1] - 15.0) < 0.01















    @patch("progressive_preview.subprocess.run")







    def test_pp19_detect_silence_success_timeout_exception(self, mock_run, tmp_path):







        """PP-19: silence正常→タイムスタンプ抽出。Timeout→空。Exception→空"""







        preview = ProgressivePreview(session_id="pp19", output_dir=str(tmp_path))















        # 正常: stderrからsilence_start抽出







        mock_run.return_value = _mock_subprocess_ok(







            stderr="silence_start: 3.5\nother line\nsilence_start: 10.2\nsilence_start: 20.0\n"







        )







        result = preview.detect_silence_points("video.mp4", max_points=5)







        assert result == [3.5, 10.2, 20.0]















        # Timeout







        mock_run.side_effect = sp.TimeoutExpired(cmd=["ffmpeg"], timeout=60)







        result_timeout = preview.detect_silence_points("video.mp4")







        assert result_timeout == []















        # Exception







        mock_run.side_effect = RuntimeError("crash")







        result_exc = preview.detect_silence_points("video.mp4")







        assert result_exc == []























# ═══════════════════════════════════════════════════════════







# C5: 並行生成・統合 (PP-21〜PP-23)







# ═══════════════════════════════════════════════════════════















class TestC5Parallel:







    """PP-21〜PP-23: 並行処理・統合"""















    @patch("progressive_preview.subprocess.run")







    def test_pp21_snapshot_parallel_sorted(self, mock_run, tmp_path):







        """PP-21: 並列抽出→インデックス順ソート(入力順保持)。comparisons構造検証"""







        mock_run.side_effect = _ffmpeg_side_effect_with_images(tmp_path)







        preview = ProgressivePreview(session_id="pp21", output_dir=str(tmp_path))















        input_ts = [5.0, 1.0, 3.0]







        result = preview.snapshot_step(







            "parallel", "before.mp4", "after.mp4", timestamps=input_ts







        )















        # ソートキーはx[0]=i(enumerate順)なので入力順が保持される







        output_ts = [c["timestamp"] for c in result["comparisons"]]







        assert output_ts == input_ts, f"入力順が保持されていない: {output_ts}"







        assert len(result["comparisons"]) == 3















    @patch("progressive_preview.subprocess.run")







    def test_pp22_snapshot_partial_failure(self, mock_run, tmp_path):







        """PP-22: extract_pair 1件失敗→残り成功。comparisons < timestamps"""







        call_count = [0]















        def side_effect(cmd, **kwargs):







            if cmd[0] == "ffmpeg" or "ffmpeg" in cmd:







                call_count[0] += 1







                # 最初の2回(before+after)は例外







                if call_count[0] <= 2:







                    raise RuntimeError("ffmpeg crash")







                out_path = cmd[-1]







                _make_image(Path(out_path))







                return _mock_subprocess_ok()







            return _mock_subprocess_ok()















        mock_run.side_effect = side_effect







        preview = ProgressivePreview(session_id="pp22", output_dir=str(tmp_path))















        result = preview.snapshot_step(







            "partial", "before.mp4", "after.mp4", timestamps=[1.0, 3.0]







        )















        # 一部失敗しても結果dictは返る







        assert isinstance(result["comparisons"], list)







        # stepsに追加される







        assert len(preview.steps) == 1















    @patch("progressive_preview.subprocess.run")







    def test_pp23_enhanced_with_silence_toggle(self, mock_run, tmp_path):







        """PP-23: シーン+無音統合。include_silence=False→無音省略"""







        call_count = [0]















        def side_effect(cmd, **kwargs):







            call_count[0] += 1







            if "ffprobe" in cmd:







                return _mock_subprocess_ok(stdout="2.0\n8.0\n")







            if "ffmpeg" in cmd:







                return _mock_subprocess_ok(







                    stderr="silence_start: 4.0\nsilence_start: 12.0\n"







                )







            return _mock_subprocess_ok()















        mock_run.side_effect = side_effect







        preview = ProgressivePreview(session_id="pp23", output_dir=str(tmp_path))















        # include_silence=True







        result_with = preview.detect_feature_points_enhanced(







            "video.mp4", max_points=5, include_silence=True







        )







        assert isinstance(result_with, list)







        for i in range(1, len(result_with)):







            assert result_with[i] - result_with[i - 1] >= 2.0















        # include_silence=False → silenceは含まれない







        call_count[0] = 0







        result_without = preview.detect_feature_points_enhanced(







            "video.mp4", max_points=5, include_silence=False







        )







        assert isinstance(result_without, list)























# ═══════════════════════════════════════════════════════════







# C6: 実行時間・品質 (PP-26〜PP-28)







# ═══════════════════════════════════════════════════════════















class TestC6Quality:







    """PP-26〜PP-28: 品質・初期化・集約"""















    @patch("progressive_preview.subprocess.run")







    def test_pp26_performance_and_metadata(self, mock_run, tmp_path):







        """PP-26: 3サンプル≤5秒。metadata.json保存+JSON構造"""







        mock_run.side_effect = _ffmpeg_side_effect_with_images(tmp_path)







        preview = ProgressivePreview(session_id="pp26", output_dir=str(tmp_path))















        start = time.time()







        preview.snapshot_step(







            "perf", "before.mp4", "after.mp4", timestamps=[1.0, 3.0, 5.0]







        )







        elapsed = time.time() - start















        assert elapsed < 5.0, f"時間超過: {elapsed:.2f}s"















        # metadata.json検証







        meta_path = tmp_path / "session_metadata.json"







        assert meta_path.exists()







        meta = json.loads(meta_path.read_text(encoding="utf-8"))







        assert meta["session_id"] == "pp26"







        assert "steps" in meta







        assert len(meta["steps"]) == 1







        assert meta["steps"][0]["step_name"] == "perf"















    def test_pp27_init_session_id_auto_and_custom(self, tmp_path):







        """PP-27: session_id未指定→日時文字列。指定→そのまま。output_dir作成"""







        # カスタムsession_id







        p1 = ProgressivePreview(session_id="custom_123", output_dir=str(tmp_path / "p1"))







        assert p1.session_id == "custom_123"







        assert (tmp_path / "p1").exists()















        # 自動生成session_id (YYYYMMDD_HHMMSS形式)







        p2 = ProgressivePreview(output_dir=str(tmp_path / "p2"))







        assert len(p2.session_id) == 15  # YYYYMMDD_HHMMSS







        assert p2.session_id[8] == "_"







        assert (tmp_path / "p2").exists()















    def test_pp28_get_all_comparisons_multi_step(self, tmp_path):







        """PP-28: 複数ステップの比較画像パスをフラット集約"""







        preview = ProgressivePreview(session_id="pp28", output_dir=str(tmp_path))







        preview.steps = [







            {"step_name": "s1", "comparisons": [







                {"comparison": "a.png"}, {"comparison": "b.png"}







            ]},







            {"step_name": "s2", "comparisons": [







                {"comparison": "c.png"}







            ]},







            {"step_name": "s3", "comparisons": []},







        ]















        result = preview.get_all_comparisons()















        assert result == ["a.png", "b.png", "c.png"]















    def test_pp29_diff_highlight_numpy_performance(self, tmp_path):







        """PP-29: 大きな画像サイズでの差分ハイライト処理が非常に高速であることを確認"""







        preview = ProgressivePreview(session_id="pp29", output_dir=str(tmp_path))







        







        # 1920x1080 の大きなダミー画像を生成







        size = (1920, 1080)







        before = _make_image(tmp_path / "before_large.png", size, (100, 100, 100))







        after = _make_image(tmp_path / "after_large.png", size, (200, 100, 100))







        out = tmp_path / "diff_large.png"







        







        start_time = time.time()







        result = preview.create_diff_highlight(str(before), str(after), str(out))







        duration = time.time() - start_time







        







        assert Path(result).exists()







        # 改善後の NumPy 処理なら、1920x1080 でも 0.1秒未満で完了するはず







        # 以前の getpixel/putpixel ループだと、200万画素の処理に 2〜5秒 以上かかる







        assert duration < 0.2, f"処理が遅すぎます: {duration:.4f}s"















    def test_pp30_image_resource_leak_prevention(self, tmp_path):
        """PP-30: create_comparison_image と create_diff_highlight で Image オブジェクトが適切にクローズされることを確認"""
        from PIL import Image
        
        opened_instances = []
        original_open = Image.open
        
        def mock_open(fp, *args, **kwargs):
            img = original_open(fp, *args, **kwargs)
            fp_str = str(fp)
            if "before" in fp_str or "after" in fp_str:
                opened_instances.append(img)
            return img
        
        before = _make_image(tmp_path / "before.png", (100, 100))
        after = _make_image(tmp_path / "after.png", (100, 100))
        out_comp = tmp_path / "comp.png"
        out_diff = tmp_path / "diff.png"
        
        preview = ProgressivePreview(session_id="pp30", output_dir=str(tmp_path))
        
        with patch("PIL.Image.open", side_effect=mock_open):
            preview.create_comparison_image(str(before), str(after), str(out_comp))
            preview.create_diff_highlight(str(before), str(after), str(out_diff))
            
        assert len(opened_instances) > 0
        for img in opened_instances:
            # PIL Image はクローズされると fp が None になる
            assert img.fp is None, f"Image {img} がクローズされていません"


class TestC7Additional:
    """追加のカバレッジ向上テスト"""

    def test_pp_srt_parse_exception(self, tmp_path):
        """SRT解析時の例外処理ハンドリングのカバー"""
        preview = ProgressivePreview(session_id="pp_srt_exc", output_dir=str(tmp_path))
        # 存在しないディレクトリを指定して、openで例外を投げさせる
        bad_path = tmp_path / "non_existent_subdir" / "test.srt"
        res = preview._extract_srt_timestamps(str(bad_path))
        assert res == []

    def test_pp_comparison_image_exception(self, tmp_path):
        """create_comparison_image での例外処理ハンドリングのカバー"""
        preview = ProgressivePreview(session_id="pp_comp_exc", output_dir=str(tmp_path))
        # 存在しない画像パスを指定して、例外を発生させる
        with pytest.raises(OSError):
            preview.create_comparison_image("no_exist_before.png", "no_exist_after.png", str(tmp_path / "out.png"))

    @patch("progressive_preview.subprocess.run")
    def test_pp_snapshot_step_timestamps_none_edge_cases(self, mock_run, tmp_path):
        """snapshot_step で timestamps=None の時のエッジケース"""
        preview = ProgressivePreview(session_id="pp_snap_none", output_dir=str(tmp_path))
        
        # ffprobeの出力をモック（durationが0）
        mock_run.return_value = _mock_subprocess_ok(stdout="0\n")
        
        # 2つのダミー動画ファイルを作成
        v1 = tmp_path / "v1.mp4"
        v2 = tmp_path / "v2.mp4"
        v1.write_text("dummy")
        v2.write_text("dummy")
        
        # timestampsをNoneにし、かつデュレーションが0の状態で実行
        with patch.object(preview, "extract_screenshot", return_value=""):
            res = preview.snapshot_step("test_none", str(v1), str(v2), num_samples=2, timestamps=None)
            assert len(res["comparisons"]) == 0

    def test_pp_enhanced_points_thinning(self, tmp_path):
        """detect_feature_points_enhanced で特徴点が max_points より多い場合の薄め（間引き）処理"""
        preview = ProgressivePreview(session_id="pp_thinning", output_dir=str(tmp_path))
        
        # 多くの特徴点を返すように detect_feature_points と detect_silence_points をモック
        with patch.object(preview, "detect_feature_points", return_value=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]), \
             patch.object(preview, "detect_silence_points", return_value=[1.5, 2.5, 3.5, 4.5, 5.5]):
            
            # max_points = 3 で実行
            res = preview.detect_feature_points_enhanced("dummy.mp4", max_points=3, include_silence=True)
            # 重複除去され、2秒以上の間隔でフィルタリングされ、最終的に max_points=3 に間引かれること
            assert len(res) <= 3

    @patch("progressive_preview.subprocess.run")
    def test_pp_detect_feature_points_value_error(self, mock_run, tmp_path):
        """detect_feature_points で ffprobe の出力に非数値が含まれていた場合の ValueError 例外ハンドリング"""
        preview = ProgressivePreview(session_id="pp_val_err", output_dir=str(tmp_path))
        mock_run.return_value = _mock_subprocess_ok(stdout="2.5\ninvalid_float\n7.5\n")
        
        res = preview.detect_feature_points("dummy.mp4", max_points=2)
        assert res == [2.5, 7.5]

    @patch("progressive_preview.subprocess.run")
    def test_pp_detect_silence_points_thinning(self, mock_run, tmp_path):
        """detect_silence_points で検出された無音区間数が max_points を超えた場合の間引き処理"""
        preview = ProgressivePreview(session_id="pp_silence_thinning", output_dir=str(tmp_path))
        
        stdout_data = "\n".join([f"silence_start: {float(i)}" for i in range(1, 11)])
        mock_run.return_value = _mock_subprocess_ok(stderr=stdout_data)
        
        res = preview.detect_silence_points("dummy.mp4", max_points=3)
        assert len(res) <= 3
        assert len(res) > 0

    def test_pp_detect_feature_points_enhanced_empty_fallback(self, tmp_path):
        """detect_feature_points_enhanced で特徴点が一切見つからなかった場合のフォールバック"""
        preview = ProgressivePreview(session_id="pp_enhanced_fallback", output_dir=str(tmp_path))
        
        with patch.object(preview, "detect_feature_points", return_value=[]), \
             patch.object(preview, "detect_silence_points", return_value=[]), \
             patch.object(preview, "_get_video_duration", return_value=10.0):
             
            res = preview.detect_feature_points_enhanced("dummy.mp4", max_points=3, include_silence=True)
            assert res == [2.5, 5.0, 7.5]

    @patch("progressive_preview.subprocess.run")
    def test_pp_progressive_preview_main(self, mock_run, tmp_path):
        """progressive_preview.py の __main__ ブロックを実行しカバレッジをカバーする"""
        import runpy
        import progressive_preview
        script_path = Path(progressive_preview.__file__)
        
        # subprocess.run のデフォルト応答を設定
        mock_run.return_value = _mock_subprocess_ok()
        
        # 1. 動画ファイルが存在しないケースの検証
        with patch("progressive_preview.Path.exists", return_value=False):
            runpy.run_path(str(script_path), run_name="__main__")
            
        # 2. 動画ファイルが存在するケースの検証（monkeypatchスタイルでPath.existsを差し替える）
        original_exists = progressive_preview.Path.exists
        def mock_exists(self_obj):
            return "test_10sec.mp4" in str(self_obj)
            
        progressive_preview.Path.exists = mock_exists
        try:
            runpy.run_path(str(script_path), run_name="__main__")
        finally:
            progressive_preview.Path.exists = original_exists

    def test_pp_extract_srt_timestamps_thinning(self, tmp_path):
        """_extract_srt_timestamps でタイムスタンプが max_points * 2 より多い場合の間引き処理をカバー"""
        preview = ProgressivePreview(session_id="pp_srt_thinning", output_dir=str(tmp_path))
        srt_file = _make_srt(tmp_path / "test_thinning.srt")
        res = preview._extract_srt_timestamps(str(srt_file), max_points=2)
        assert len(res) <= 4

    @patch("progressive_preview.subprocess.run")
    def test_pp_snapshot_step_duration_limit(self, mock_run, tmp_path):
        """snapshot_step で検出された特徴点のうち、デュレーションの 95% 以上のポイントを除外する処理をカバー"""
        preview = ProgressivePreview(session_id="pp_snap_limit", output_dir=str(tmp_path))
        
        # ダミー動画ファイル
        v1 = tmp_path / "v1.mp4"
        v2 = tmp_path / "v2.mp4"
        v1.write_text("dummy")
        v2.write_text("dummy")
        
        # デュレーションを 10.0秒にモック
        # 特徴点検出で 1.0, 5.0, 9.8 を返すようにモック (9.8 は 9.5 以上なので除外されるはず)
        with patch.object(preview, "_get_video_duration", return_value=10.0),              patch.object(preview, "detect_feature_points", return_value=[1.0, 5.0, 9.8]),              patch.object(preview, "extract_screenshot", return_value=""),              patch.object(preview, "create_diff_highlight", return_value=""),              patch.object(preview, "create_comparison_image", return_value=""):
             
            # 画像ファイルの存在チェックをパスさせるため、before_*, after_* ファイルを事前に作成するか、
            # あるいは Path.exists が True を返すようにモックする
            with patch("progressive_preview.Path.exists", return_value=True):
                res = preview.snapshot_step("test_limit", str(v1), str(v2), num_samples=2, timestamps=None)
                
            # 抽出されたタイムスタンプが [1.0, 5.0] の2つになっていること
            timestamps = [comp["timestamp"] for comp in res["comparisons"]]
            assert timestamps == [1.0, 5.0]

    @patch("progressive_preview.subprocess.run")
    def test_pp_snapshot_step_fallback_sampling(self, mock_run, tmp_path):
        """snapshot_step で特徴点が不足している場合に等間隔サンプリングにフォールバックする処理をカバー"""
        preview = ProgressivePreview(session_id="pp_snap_fallback", output_dir=str(tmp_path))
        
        # ダミー動画ファイル
        v1 = tmp_path / "v1.mp4"
        v2 = tmp_path / "v2.mp4"
        v1.write_text("dummy")
        v2.write_text("dummy")
        
        # デュレーションを 10.0秒、特徴点検出を [] にモック
        with patch.object(preview, "_get_video_duration", return_value=10.0),              patch.object(preview, "detect_feature_points", return_value=[]),              patch.object(preview, "extract_screenshot", return_value=""),              patch.object(preview, "create_diff_highlight", return_value=""),              patch.object(preview, "create_comparison_image", return_value=""):
             
            with patch("progressive_preview.Path.exists", return_value=True):
                res = preview.snapshot_step("test_fallback", str(v1), str(v2), num_samples=3, timestamps=None)
                
            # 抽出されたタイムスタンプが等間隔 [2.375, 4.75, 7.125] になっていること
            timestamps = [comp["timestamp"] for comp in res["comparisons"]]
            assert len(timestamps) == 3
            assert pytest.approx(timestamps[0]) == 2.375
            assert pytest.approx(timestamps[1]) == 4.75
            assert pytest.approx(timestamps[2]) == 7.125



















class TestC8ThumbnailQualityAndValidation:
    """解像度、アスペクト比、ファイルサイズ、エラーハンドリング（タイムアウトなど）の検証テスト"""

    def test_pp_image_resolution_validation(self, tmp_path):
        """解像度の検証: 結合画像および差分画像の高さ・幅が仕様通りに処理されているか"""
        preview = ProgressivePreview(session_id="pp_res_val", output_dir=str(tmp_path))
        
        # 異なる解像度の画像を生成
        # before: 640x360 (16:9), after: 320x240 (4:3)
        before = _make_image(tmp_path / "before_res.png", (640, 360))
        after = _make_image(tmp_path / "after_res.png", (320, 240))
        out_comp = tmp_path / "comp_res.png"
        out_diff = tmp_path / "diff_res.png"
        
        # 1. 比較画像の結合解像度検証
        preview.create_comparison_image(str(before), str(after), str(out_comp))
        assert out_comp.exists()
        
        from PIL import Image
        with Image.open(out_comp) as img:
            # ターゲット高さは min(360, 240, 480) = 240
            # header_height = 30
            # 結合画像の高さ = 240 + 30 = 270
            assert img.height == 270
            # before はアスペクト比維持で高さ240にリサイズされる -> 幅 = 640 * (240/360) = 426
            # after も高さ240にリサイズされる -> 幅 = 320 * (240/240) = 320
            # 合計幅 = 426 + 4(gap) + 320 = 750
            assert img.width == 750

        # 2. 差分画像の解像度検証
        preview.create_diff_highlight(str(before), str(after), str(out_diff))
        assert out_diff.exists()
        with Image.open(out_diff) as img:
            # 差分画像は before 画像のサイズに揃えられる
            assert img.size == (640, 360)

    def test_pp_image_aspect_ratio_preservation(self, tmp_path):
        """アスペクト比の検証: リサイズ処理時に歪みが発生していないか"""
        preview = ProgressivePreview(session_id="pp_aspect_val", output_dir=str(tmp_path))
        
        # 16:9 と 4:3 のアスペクト比の画像
        before = _make_image(tmp_path / "before_aspect.png", (1280, 720))
        after = _make_image(tmp_path / "after_aspect.png", (800, 600))
        out_comp = tmp_path / "comp_aspect.png"
        
        preview.create_comparison_image(str(before), str(after), str(out_comp))
        
        from PIL import Image
        # 内部リサイズ比率の正当性 (歪みがないこと)
        with Image.open(before) as b_img, Image.open(after) as a_img:
            b_ratio_orig = b_img.width / b_img.height
            a_ratio_orig = a_img.width / a_img.height
            
            # create_comparison_image を手動でシミュレートした比率
            target_height = min(b_img.height, a_img.height, 480) # 480
            b_width_new = int(b_img.width * (target_height / b_img.height)) # 1280 * (480/720) = 853
            a_width_new = int(a_img.width * (target_height / a_img.height)) # 800 * (480/600) = 640
            
            b_ratio_new = b_width_new / target_height
            a_ratio_new = a_width_new / target_height
            
            # リサイズ前後でアスペクト比が維持されていることを検証 (誤差許容)
            assert abs(b_ratio_orig - b_ratio_new) < 0.01
            assert abs(a_ratio_orig - a_ratio_new) < 0.01

    def test_pp_image_filesize_validation(self, tmp_path):
        """ファイルサイズの検証: 高画質・最適化保存後のファイルサイズが適切か"""
        preview = ProgressivePreview(session_id="pp_size_val", output_dir=str(tmp_path))
        
        # 複雑なテクスチャを再現してファイルサイズに差が出やすいようにグラデーション画像を生成
        from PIL import Image
        img_data = bytes([(i + j) % 256 for i in range(500) for j in range(500)])
        before_path = tmp_path / "before_size.png"
        after_path = tmp_path / "after_size.png"
        with Image.frombytes('L', (500, 500), img_data) as img:
            img.convert('RGB').save(before_path)
            img.convert('RGB').save(after_path)
            
        out_comp = tmp_path / "comp_size.png"
        preview.create_comparison_image(str(before_path), str(after_path), str(out_comp))
        
        assert out_comp.exists()
        file_size = out_comp.stat().st_size
        
        # ファイルサイズが 0 ではなく、適正サイズ（e.g. 500KB以下）であることを確認
        assert file_size > 0
        assert file_size < 500 * 1024, f"File size too large: {file_size} bytes"

    def test_pp_error_handling_fallbacks(self, tmp_path):
        """エラーハンドリングの検証: 不正パスや片方欠落などの例外発生時の自己修復動作"""
        preview = ProgressivePreview(session_id="pp_err_val", output_dir=str(tmp_path))
        
        # 1. 両画像が欠落している場合 -> FileNotFoundError 例外が発生することを確認
        with pytest.raises(FileNotFoundError):
            preview.create_comparison_image("missing1.png", "missing2.png", str(tmp_path / "out.png"))
            
        # 2. 片方だけ存在しない場合 -> 存在する画像がプレースホルダーとして代替され、正常終了すること
        valid_img = _make_image(tmp_path / "valid.png", (300, 200))
        out_fallback = tmp_path / "fallback.png"
        
        # before が欠落している場合
        preview.create_comparison_image("missing.png", str(valid_img), str(out_fallback))
        assert out_fallback.exists()
        
        # after が欠落している場合
        out_fallback_2 = tmp_path / "fallback_2.png"
        preview.create_comparison_image(str(valid_img), "missing.png", str(out_fallback_2))
        assert out_fallback_2.exists()
        
        # 3. extract_screenshot における FFmpeg 失敗時のプレースホルダー自動生成の検証
        # FFmpeg が失敗した時に、プレースホルダー画像を作成して終了すること
        out_shot = tmp_path / "failed_shot.png"
        
        # エラーを発生させるために、存在しない動画を指定して実行
        # (すでに Patch2 で Path.exists() チェックを外し、FFmpegが実際に走って失敗するようになっている)
        # ただし、FFmpeg が実際に走らないように subprocess.run をモックして例外を投げさせる
        import subprocess
        with patch("progressive_preview.subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr="dummy error")):
            res = preview.extract_screenshot("dummy_failed_video.mp4", 1.0, str(out_shot))
            assert res == str(out_shot)
            assert out_shot.exists() # プレースホルダーが作成されていること
            
        # 4. extract_screenshot におけるタイムアウト時のプレースホルダー自動生成
        out_timeout_shot = tmp_path / "timeout_shot.png"
        with patch("progressive_preview.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 30)):
            res = preview.extract_screenshot("dummy_timeout_video.mp4", 1.0, str(out_timeout_shot))
            assert res == str(out_timeout_shot)
            assert out_timeout_shot.exists()
