"""
Batch 11: youtube_optimizer_plugin + phase1_full_processing + disk_manager
M2.6 カバレッジ 63% → 70% (Batch 11/14)

合計: ~55テスト
"""
import sys
import json
import asyncio
import pytest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock, mock_open
from datetime import datetime

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# ============================================================
# Part 1: youtube_optimizer_plugin (35 tests)
# ============================================================

class TestYouTubeOptimizerPluginHook:
    """YouTubeOptimizerPlugin._evaluate_hook — 10種フックパターン"""

    @pytest.fixture
    def plugin(self):
        with patch("plugins.youtube_optimizer_plugin._resolve_model", return_value="gemini-2.5-flash"):
            from plugins.youtube_optimizer_plugin import YouTubeOptimizerPlugin
            return YouTubeOptimizerPlugin()

    def test_yp_01_question_hook(self, plugin):
        score, typ, _ = plugin._evaluate_hook("なぜこれが重要なのか？")
        assert score > 0
        assert typ == "question"

    def test_yp_02_specificity_hook(self, plugin):
        score, typ, _ = plugin._evaluate_hook("3つのポイントを解説します")
        assert score > 0
        assert typ == "specificity"

    def test_yp_03_surprise_hook(self, plugin):
        score, typ, _ = plugin._evaluate_hook("まさかの結果！")
        assert score > 0

    def test_yp_04_promise_hook(self, plugin):
        score, typ, _ = plugin._evaluate_hook("これで簡単にできるようになります")
        assert score > 0
        assert typ == "promise"

    def test_yp_05_controversy_hook(self, plugin):
        score, typ, _ = plugin._evaluate_hook("実はこれは全部嘘でした")
        assert score > 0

    def test_yp_06_urgency_hook(self, plugin):
        score, typ, _ = plugin._evaluate_hook("今すぐ確認してください")
        assert score > 0

    def test_yp_07_story_hook(self, plugin):
        score, typ, _ = plugin._evaluate_hook("私はある日突然気づきました")
        assert score > 0

    def test_yp_08_benefit_hook(self, plugin):
        score, typ, _ = plugin._evaluate_hook("これで得する方法を無料で教えます")
        assert score > 0

    def test_yp_09_fear_hook(self, plugin):
        score, typ, _ = plugin._evaluate_hook("危険！これは注意してください")
        assert score > 0

    def test_yp_10_authority_hook(self, plugin):
        score, typ, _ = plugin._evaluate_hook("プロの専門家が10年間の経験者として解説")
        assert score > 0

    def test_yp_11_neutral_hook(self, plugin):
        score, typ, _ = plugin._evaluate_hook("あ")
        assert typ == "neutral"

    def test_yp_12_education_genre_bonus(self, plugin):
        score_gen, _, _ = plugin._evaluate_hook("3つのポイントを教えます", genre="general")
        score_edu, _, _ = plugin._evaluate_hook("3つのポイントを教えます", genre="education")
        assert score_edu > score_gen

    def test_yp_13_entertainment_genre_bonus(self, plugin):
        score_gen, _, _ = plugin._evaluate_hook("まさかの衝撃ストーリー！", genre="general")
        score_ent, _, _ = plugin._evaluate_hook("まさかの衝撃ストーリー！", genre="entertainment")
        assert score_ent > score_gen

    def test_yp_14_business_genre_bonus(self, plugin):
        score_gen, _, _ = plugin._evaluate_hook("プロの節約術", genre="general")
        score_biz, _, _ = plugin._evaluate_hook("プロの節約術", genre="business")
        assert score_biz > score_gen

    def test_yp_15_suggestions_low_score(self, plugin):
        _, _, suggestions = plugin._evaluate_hook("あ", genre="general")
        assert len(suggestions) > 0

    def test_yp_16_suggestions_education(self, plugin):
        _, _, suggestions = plugin._evaluate_hook("テスト", genre="education")
        assert any("数字" in s for s in suggestions)

    def test_yp_17_suggestions_entertainment(self, plugin):
        _, _, suggestions = plugin._evaluate_hook("テスト", genre="entertainment")
        assert any("驚き" in s or "ストーリー" in s for s in suggestions)

    def test_yp_18_score_cap_100(self, plugin):
        # Many hook triggers combined
        text = "なぜ？まさか！今すぐプロの3つの衝撃の真実を無料で教えます！危険な経験者がある日語る"
        score, _, _ = plugin._evaluate_hook(text)
        assert score <= 100


class TestYouTubeOptimizerPluginRetention:
    """_predict_retention_impact"""

    @pytest.fixture
    def plugin(self):
        with patch("plugins.youtube_optimizer_plugin._resolve_model", return_value="gemini-2.5-flash"):
            from plugins.youtube_optimizer_plugin import YouTubeOptimizerPlugin
            return YouTubeOptimizerPlugin()

    def test_yp_19_high_retention(self, plugin):
        assert "高" in plugin._predict_retention_impact(85)

    def test_yp_20_mid_retention(self, plugin):
        assert "中" in plugin._predict_retention_impact(65)

    def test_yp_21_low_retention(self, plugin):
        assert "低" in plugin._predict_retention_impact(40)


class TestYouTubeOptimizerCTR:
    """calculate_dynamic_ctr — 静的メソッド"""

    def test_yp_22_base_ctr(self):
        from plugins.youtube_optimizer_plugin import YouTubeOptimizerPlugin
        ctr = YouTubeOptimizerPlugin.calculate_dynamic_ctr("普通のタイトルテスト用の文字列です")
        assert 0.5 <= ctr <= 15.0

    def test_yp_23_exclamation_boost(self):
        from plugins.youtube_optimizer_plugin import YouTubeOptimizerPlugin
        ctr_plain = YouTubeOptimizerPlugin.calculate_dynamic_ctr("テスト用のタイトル文字列テスト")
        ctr_excl = YouTubeOptimizerPlugin.calculate_dynamic_ctr("テスト用のタイトル文字列テスト！")
        assert ctr_excl > ctr_plain

    def test_yp_24_question_boost(self):
        from plugins.youtube_optimizer_plugin import YouTubeOptimizerPlugin
        ctr_plain = YouTubeOptimizerPlugin.calculate_dynamic_ctr("テスト用のタイトル文字列テスト")
        ctr_q = YouTubeOptimizerPlugin.calculate_dynamic_ctr("テスト用のタイトル文字列テスト？")
        assert ctr_q > ctr_plain

    def test_yp_25_optimal_length(self):
        from plugins.youtube_optimizer_plugin import YouTubeOptimizerPlugin
        ctr_short = YouTubeOptimizerPlugin.calculate_dynamic_ctr("短い")
        ctr_optimal = YouTubeOptimizerPlugin.calculate_dynamic_ctr("この長さが最適なYouTubeタイトルです")
        assert ctr_optimal > ctr_short

    def test_yp_26_power_word(self):
        from plugins.youtube_optimizer_plugin import YouTubeOptimizerPlugin
        ctr = YouTubeOptimizerPlugin.calculate_dynamic_ctr("完全版の徹底解説をお届けします！")
        assert ctr >= 5.0  # base + excl + power + length


class TestYouTubeOptimizerHelpers:
    """ヘルパーメソッド群"""

    @pytest.fixture
    def plugin(self):
        with patch("plugins.youtube_optimizer_plugin._resolve_model", return_value="gemini-2.5-flash"):
            from plugins.youtube_optimizer_plugin import YouTubeOptimizerPlugin
            return YouTubeOptimizerPlugin()

    def test_yp_27_generate_description(self, plugin):
        desc = plugin._generate_description("AI入門", ["AI入門", "機械学習", "深層学習"], "テスト")
        assert "AI入門" in desc
        assert "✅" in desc

    def test_yp_28_generate_expanded_tags(self, plugin):
        tags = plugin._generate_expanded_tags("動画編集", ["動画編集", "テクニック"], "テキスト")
        assert len(tags) >= 10
        assert "動画編集" in tags
        assert tags == list(dict.fromkeys(tags))  # no duplicates

    def test_yp_29_generate_chapters_empty(self, plugin):
        chapters = plugin._generate_chapters([])
        assert chapters == []

    def test_yp_30_generate_chapters_with_markers(self, plugin):
        segments = [
            {"text": "まず最初のポイントです", "start": 0, "end": 5},
            {"text": "次にこちらを見てください", "start": 60, "end": 65},
            {"text": "最後にまとめます", "start": 120, "end": 125},
        ]
        chapters = plugin._generate_chapters(segments)
        assert len(chapters) >= 1
        assert chapters[0]["time"] == "0:00"

    def test_yp_31_generate_chapters_fallback_short(self, plugin):
        """マーカーが少ない場合の均等分割フォールバック"""
        segments = [
            {"text": "普通の文章です", "start": 0, "end": 30},
            {"text": "これも普通です", "start": 30, "end": 60},
            {"text": "まだ普通です", "start": 60, "end": 90},
        ]
        chapters = plugin._generate_chapters(segments)
        # total_duration=90 >= 60 で chapters < 5 → 均等分割
        assert len(chapters) == 5

    def test_yp_32_extract_chapter_title(self, plugin):
        title = plugin._extract_chapter_title("次に重要なのはこの点です", "次に")
        assert len(title) <= 10

    def test_yp_33_extract_chapter_title_marker_only(self, plugin):
        title = plugin._extract_chapter_title("まとめ", "まとめ")
        # snippet after removing marker is empty → returns marker
        assert title == "まとめ"

    def test_yp_34_calculate_importance(self, plugin):
        score = plugin._calculate_importance("AIについて驚きの数字100！？", ["AI"])
        assert score > 0

    def test_yp_35_session_continuation_score(self, plugin):
        result = plugin.calculate_session_continuation_score(
            "vid_001", "series_001",
            has_end_screen=True, has_teaser=True, brand_consistency=80.0
        )
        assert result["score"] <= 100
        assert len(result["factors"]) == 3
        assert "recommendation" in result

    def test_yp_36_session_continuation_no_teaser(self, plugin):
        result = plugin.calculate_session_continuation_score(
            "vid_002", "series_001",
            has_end_screen=False, has_teaser=False, brand_consistency=50.0
        )
        assert result["score"] < 50


class TestYouTubeOptimizerAsync:
    """非同期メソッド群"""

    @pytest.fixture
    def plugin(self):
        with patch("plugins.youtube_optimizer_plugin._resolve_model", return_value="gemini-2.5-flash"):
            from plugins.youtube_optimizer_plugin import YouTubeOptimizerPlugin
            return YouTubeOptimizerPlugin()

    @pytest.mark.asyncio
    async def test_yp_37_analyze_hook(self, plugin):
        segments = [
            {"text": "なぜこれが重要なのか？驚きの事実", "start": 0, "end": 3},
            {"text": "今日はその秘密を教えます", "start": 3, "end": 5},
        ]
        hook = await plugin.analyze_hook(segments)
        assert hook.score > 0
        assert hook.first_5_seconds_text

    @pytest.mark.asyncio
    async def test_yp_38_generate_thumbnail_candidates(self, plugin):
        candidates = await plugin.generate_thumbnail_candidates({"topic": "AI入門"}, count=3)
        assert len(candidates) == 3
        assert all(c.concept for c in candidates)

    @pytest.mark.asyncio
    async def test_yp_39_generate_seo_metadata(self, plugin):
        segments = [{"text": "AI解説動画のテスト", "start": 0, "end": 5}]
        seo = await plugin.generate_seo_metadata(segments, ["AI", "機械学習"], {})
        assert len(seo.title_candidates) == 5
        assert len(seo.hashtags) <= 3
        assert seo.keywords == ["AI", "機械学習"]

    @pytest.mark.asyncio
    async def test_yp_40_detect_highlights(self, plugin):
        segments = [
            {"text": "すごい！これは衝撃的です", "start": 10, "end": 15},
            {"text": "実はここが重要なポイント", "start": 30, "end": 35},
            {"text": "つまり結局こうなります", "start": 60, "end": 65},
            {"text": "普通のテキスト", "start": 90, "end": 95},
        ]
        highlights = await plugin.detect_highlights(segments, ["重要"])
        assert len(highlights) >= 2
        assert all("type" in h for h in highlights)

    @pytest.mark.asyncio
    async def test_yp_41_generate_pre_edit_assets(self, plugin):
        result = await plugin.generate_pre_edit_assets("AI入門講座")
        assert len(result["title_candidates"]) == 5
        assert len(result["thumbnails"]) == 3


# ============================================================
# Part 2: phase1_full_processing (10 tests)
# ============================================================

class TestPhase1FullProcessing:
    """phase1_full_processing.py — FFmpegパイプライン (全モック)"""

    def test_p1_01_get_short_path_exists(self, tmp_path):
        """既存ファイルのショートパス取得"""
        f = tmp_path / "test.txt"
        f.write_text("hello")
        # Windows APIのモック
        with patch("phase1_full_processing._GetShortPathNameW") as mock_api:
            mock_api.return_value = 10
            from phase1_full_processing import get_short_path
            result = get_short_path(str(f))
            # パスが返ることを確認（モック環境ではWindowsBufferの値かフォールバック）
            assert isinstance(result, str)

    def test_p1_02_get_short_path_not_exists(self):
        from phase1_full_processing import get_short_path
        result = get_short_path("/nonexistent/path/video.mp4")
        assert result.endswith("video.mp4")

    def test_p1_03_run_ffmpeg_success(self):
        from phase1_full_processing import run_ffmpeg_with_retry
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("phase1_full_processing.subprocess.run", return_value=mock_result):
            success, _, error = run_ffmpeg_with_retry(["ffmpeg", "-version"], "test")
            assert success is True
            assert error is None

    def test_p1_04_run_ffmpeg_fail_then_succeed(self):
        from phase1_full_processing import run_ffmpeg_with_retry
        fail_result = MagicMock(returncode=1, stderr="error")
        ok_result = MagicMock(returncode=0)
        with patch("phase1_full_processing.subprocess.run", side_effect=[fail_result, ok_result]):
            with patch("phase1_full_processing.time.sleep"):
                success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=2)
                assert success is True

    def test_p1_05_run_ffmpeg_all_fail(self):
        from phase1_full_processing import run_ffmpeg_with_retry
        fail_result = MagicMock(returncode=1, stderr="error msg")
        with patch("phase1_full_processing.subprocess.run", return_value=fail_result):
            with patch("phase1_full_processing.time.sleep"):
                success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=2)
                assert success is False
                assert "Failed after" in error

    def test_p1_06_run_ffmpeg_timeout(self):
        from phase1_full_processing import run_ffmpeg_with_retry
        import subprocess
        with patch("phase1_full_processing.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 10)):
            success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=1)
            assert success is False

    def test_p1_07_run_ffmpeg_exception(self):
        from phase1_full_processing import run_ffmpeg_with_retry
        with patch("phase1_full_processing.subprocess.run", side_effect=OSError("disk full")):
            success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=1)
            assert success is False

    def test_p1_08_process_chunk(self, tmp_path):
        from phase1_full_processing import process_chunk
        output = tmp_path / "chunk.mp4"
        mock_result = MagicMock(returncode=0)
        with patch("phase1_full_processing.subprocess.run", return_value=mock_result):
            # process_chunk checks file exists after run, so create it
            output.write_bytes(b"fake video data")
            result = process_chunk("/fake/input.mp4", output, 0, 300, "test chunk")
            assert result is True

    def test_p1_09_concat_videos(self, tmp_path):
        from phase1_full_processing import concat_videos
        f1 = tmp_path / "a.mp4"
        f2 = tmp_path / "b.mp4"
        f1.write_bytes(b"fake1")
        f2.write_bytes(b"fake2")
        output = tmp_path / "out.mp4"
        mock_result = MagicMock(returncode=0)
        with patch("phase1_full_processing.subprocess.run", return_value=mock_result):
            output.write_bytes(b"concatenated")
            result = concat_videos([f1, f2], output)
            assert result is True

    def test_p1_10_concat_videos_fail(self, tmp_path):
        from phase1_full_processing import concat_videos
        f1 = tmp_path / "a.mp4"
        f1.write_bytes(b"fake")
        output = tmp_path / "out.mp4"
        fail_result = MagicMock(returncode=1, stderr="concat error")
        with patch("phase1_full_processing.subprocess.run", return_value=fail_result):
            with patch("phase1_full_processing.time.sleep"):
                result = concat_videos([f1], output)
                assert result is False


# ============================================================
# Part 3: disk_manager (10 tests)
# ============================================================

class TestDiskManager:
    """disk_manager.py — ディスク容量管理"""

    def test_dm_01_get_drive_root_default(self):
        from disk_manager import get_drive_root
        root = get_drive_root()
        assert isinstance(root, str)
        assert len(root) >= 1

    def test_dm_02_get_drive_root_custom(self, tmp_path):
        from disk_manager import get_drive_root
        root = get_drive_root(tmp_path)
        assert isinstance(root, str)

    def test_dm_03_get_free_gb(self):
        from disk_manager import get_free_gb
        with patch("disk_manager.shutil.disk_usage", return_value=(100_000_000_000, 50_000_000_000, 50_000_000_000)):
            gb = get_free_gb()
            assert abs(gb - 50_000_000_000 / (1024**3)) < 0.1

    def test_dm_04_estimate_needed_gb(self, tmp_path):
        from disk_manager import estimate_needed_gb
        f = tmp_path / "test.mp4"
        f.write_bytes(b"x" * 1_000_000)
        gb = estimate_needed_gb([str(f)], multiplier=2.5)
        expected = (1_000_000 * 2.5) / (1024**3)
        assert abs(gb - expected) < 0.001

    def test_dm_05_estimate_needed_nonexistent(self):
        from disk_manager import estimate_needed_gb
        gb = estimate_needed_gb(["/nonexistent/file.mp4"])
        assert gb == 0.0

    def test_dm_06_calc_timeout(self, tmp_path):
        from disk_manager import calc_timeout
        f = tmp_path / "big.mp4"
        f.write_bytes(b"x" * (1024**3))  # 1 GB
        timeout = calc_timeout([str(f)])
        assert 300 <= timeout <= 7200

    def test_dm_07_cleanup_intermediates_empty(self, tmp_path):
        from disk_manager import cleanup_intermediates
        freed = cleanup_intermediates(tmp_path, dry_run=True)
        assert freed == 0.0

    def test_dm_08_cleanup_intermediates_with_files(self, tmp_path):
        from disk_manager import cleanup_intermediates
        # Create intermediate directories with files
        merged = tmp_path / "merged"
        merged.mkdir()
        for i in range(3):
            (merged / f"video_{i}.mp4").write_bytes(b"x" * 10000)
        # Create a concat list file
        (merged / "concat_list.txt").write_text("file 'test.mp4'")
        # Create preview dir with smartcut parts
        preview = tmp_path / "preview"
        preview.mkdir()
        (preview / "_smartcut_part_001.mp4").write_bytes(b"x" * 5000)
        # Create tmp file
        (tmp_path / "test.tmp.mp4").write_bytes(b"x" * 2000)

        freed = cleanup_intermediates(tmp_path, keep_latest=1, dry_run=False)
        assert freed > 0

    def test_dm_09_ensure_disk_space_sufficient(self, tmp_path):
        from disk_manager import ensure_disk_space
        with patch("disk_manager.get_free_gb", return_value=100.0):
            result = ensure_disk_space([], min_free_gb=10.0, outputs_dir=tmp_path)
            assert result is True

    def test_dm_10_ensure_disk_space_insufficient_then_cleanup(self, tmp_path):
        from disk_manager import ensure_disk_space
        # First call: insufficient (5GB), after cleanup: sufficient (15GB)
        with patch("disk_manager.get_free_gb", side_effect=[5.0, 15.0]):
            with patch("disk_manager.cleanup_intermediates", return_value=10.0):
                with patch("disk_manager.estimate_needed_gb", return_value=5.0):
                    result = ensure_disk_space([], min_free_gb=10.0, outputs_dir=tmp_path)
                    assert result is True

    def test_dm_11_import_error_fallback(self):
        # safe_io をインポート不可にし、disk_manager を再ロードして ImportError 分岐をカバー
        import sys
        with patch.dict(sys.modules, {'safe_io': None}):
            if 'disk_manager' in sys.modules:
                del sys.modules['disk_manager']
            import disk_manager
            assert disk_manager.VAULT_OUTPUTS_DIR.name == "vault-outputs"
        
        # 元の状態に戻す
        if 'disk_manager' in sys.modules:
            del sys.modules['disk_manager']
        import disk_manager

    def test_dm_12_cleanup_intermediates_exceptions(self, tmp_path):
        from disk_manager import cleanup_intermediates
        # テスト用のディレクトリ構造を作成
        merged = tmp_path / "merged"
        merged.mkdir()
        video_file = merged / "video_0.mp4"
        video_file.write_bytes(b"x" * 100)
        concat_file = merged / "concat_test.txt"
        concat_file.write_text("file 'x.mp4'")

        preview = tmp_path / "preview"
        preview.mkdir()
        smartcut_file = preview / "_smartcut_part_001.mp4"
        smartcut_file.write_bytes(b"x" * 100)
        
        tmp_file = tmp_path / "test.tmp.mp4"
        tmp_file.write_bytes(b"x" * 100)

        # Path.unlink が OSError を発生させるように mock
        with patch.object(Path, "unlink", side_effect=OSError("Access denied")):
            # keep_latest=0 で全ての動画を削除対象にする
            freed = cleanup_intermediates(tmp_path, keep_latest=0, dry_run=False)
            # 例外が発生したため、正常に解放されたバイト数 freed_bytes には加算されない
            assert freed == 0.0

    def test_dm_13_ensure_disk_space_insufficient_even_after_cleanup(self, tmp_path):
        from disk_manager import ensure_disk_space
        # クリーンアップ後も 5.0GB しかなく、必要な 10.0GB を満たさない場合
        with patch("disk_manager.get_free_gb", side_effect=[3.0, 5.0]):
            with patch("disk_manager.cleanup_intermediates", return_value=2.0):
                with patch("disk_manager.estimate_needed_gb", return_value=5.0):
                    result = ensure_disk_space([], min_free_gb=10.0, outputs_dir=tmp_path)
                    assert result is False


# ============================================================
# Part 4: YouTubeOptimizedContext dataclass (4 tests)
# ============================================================

class TestYouTubeOptimizedContext:
    """YouTubeOptimizedContext データクラスとto_dict"""

    def test_yp_42_context_to_dict(self):
        from plugins.youtube_optimizer_plugin import YouTubeOptimizedContext
        ctx = YouTubeOptimizedContext(task_id="test_001")
        d = ctx.to_dict()
        assert d["task_id"] == "test_001"
        assert d["hook_score"] == 0.0
        assert d["hook_analysis"] is None
        assert d["seo_metadata"] is None

    def test_yp_43_context_with_hook(self):
        from plugins.youtube_optimizer_plugin import YouTubeOptimizedContext, HookAnalysis
        hook = HookAnalysis(score=85, attention_grabber="question",
                           first_5_seconds_text="テスト", improvement_suggestions=[],
                           predicted_retention_impact="高")
        ctx = YouTubeOptimizedContext(task_id="test_002", hook_analysis=hook, hook_score=85)
        d = ctx.to_dict()
        assert d["hook_analysis"]["score"] == 85

    def test_yp_44_context_with_seo(self):
        from plugins.youtube_optimizer_plugin import YouTubeOptimizedContext, SEOMetadata
        seo = SEOMetadata(
            title_candidates=["t1"], description="desc", tags=["tag"],
            hashtags=["#h"], chapters=[], category="教育", keywords=["kw"]
        )
        ctx = YouTubeOptimizedContext(task_id="test_003", seo_metadata=seo)
        d = ctx.to_dict()
        assert d["seo_metadata"]["category"] == "教育"

    def test_yp_45_context_with_thumbnails(self):
        from plugins.youtube_optimizer_plugin import YouTubeOptimizedContext, ThumbnailCandidate
        tc = ThumbnailCandidate(id="t1", concept="好奇心", target_emotion="好奇心",
                                text_overlay="テスト", predicted_ctr=5.0)
        ctx = YouTubeOptimizedContext(task_id="test_004", thumbnail_candidates=[tc])
        d = ctx.to_dict()
        assert len(d["thumbnail_candidates"]) == 1
        assert d["thumbnail_candidates"][0]["predicted_ctr"] == 5.0
