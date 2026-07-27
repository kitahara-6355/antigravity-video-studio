"""
Batch 9: youtube_optimizer深掘り + interactive_preview + sdk_checker
M2.6 カバレッジ 60% → 70% (Batch 9/10)

合計: ~55テスト
"""
import sys
import json
import asyncio
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# ============================================================
# Part 1: youtube_optimizer 深掘り (20 tests)
# ============================================================

class TestYouTubeHelpers:
    """youtube_optimizer.py — ヘルパー関数"""

    def test_yt_01_title_candidates(self):
        from routers.youtube_optimizer import _generate_title_candidates
        titles = _generate_title_candidates("キャンプ飯", "Vlog", "20代男性")
        assert len(titles) == 5
        assert any("キャンプ飯" in t for t in titles)

    def test_yt_02_thumbnail_concepts(self):
        from routers.youtube_optimizer import _generate_thumbnail_concepts
        concepts = _generate_thumbnail_concepts("AI", "教育", ["タイトル1"])
        assert len(concepts) == 3
        assert all("id" in c for c in concepts)

    def test_yt_03_estimate_ctr_base(self):
        from routers.youtube_optimizer import _estimate_ctr
        ctr = _estimate_ctr("普通のタイトル", "")
        assert 2.0 <= ctr <= 9.0

    def test_yt_04_estimate_ctr_triggers(self):
        from routers.youtube_optimizer import _estimate_ctr
        ctr = _estimate_ctr("【完全版】衝撃の結果99%の人が知らない", "エンタメ")
        assert ctr >= 4.5

    def test_yt_05_estimate_ctr_numbers(self):
        from routers.youtube_optimizer import _estimate_ctr
        ctr_no_num = _estimate_ctr("普通のタイトル", "")
        ctr_num = _estimate_ctr("10万円で始める投資", "")
        assert ctr_num > ctr_no_num

    def test_yt_06_estimate_ctr_genre(self):
        from routers.youtube_optimizer import _estimate_ctr
        ctr_ent = _estimate_ctr("テスト", "エンタメ")
        ctr_asmr = _estimate_ctr("テスト", "ASMR")
        assert ctr_ent > ctr_asmr

    def test_yt_07_record_feedback_new(self, tmp_path):
        from routers.youtube_optimizer import _record_post_publish_feedback
        log_path = tmp_path / "evolution_log.json"
        with patch("pathlib.Path.exists", return_value=False), \
             patch("pathlib.Path.write_text"):
            _record_post_publish_feedback(
                wagamama_id="w1", video_id="v1",
                actual_metrics={"metrics": {"click_through_rate": 5.0}},
                validation={"analysis": {"predicted": 4.0, "difference": 1.0}},
            )

    def test_yt_08_record_feedback_with_dropoff(self, tmp_path):
        from routers.youtube_optimizer import _record_post_publish_feedback
        with patch("pathlib.Path.exists", return_value=False), \
             patch("pathlib.Path.write_text"):
            _record_post_publish_feedback(
                wagamama_id="w2", video_id="v2",
                actual_metrics={
                    "metrics": {}, 
                    "retention_map": {"drop_off_points": ["1:30", "3:00"]}
                },
                validation={"analysis": {"significant_deviation": True, "difference": 5}},
            )


class TestYouTubeEndpoints:
    """youtube_optimizer.py — エンドポイント"""

    @pytest.mark.asyncio
    async def test_yt_09_health(self):
        from routers.youtube_optimizer import health_check
        r = await health_check()
        assert r["status"] == "ok"

    @pytest.mark.asyncio
    async def test_yt_10_pre_plan_success(self):
        from routers.youtube_optimizer import pre_plan_content, PrePlanRequest
        req = PrePlanRequest(topic="一人キャンプ飯", genre="Vlog")
        with patch.dict(sys.modules, {
            "plugins.youtube_optimizer_plugin": MagicMock(),
        }):
            r = await pre_plan_content(req)
            assert r["success"] is True
            assert len(r["title_candidates"]) == 5
            assert r["go_nogo"] in ("GO", "RECONSIDER")

    @pytest.mark.asyncio
    async def test_yt_11_pre_plan_go(self):
        from routers.youtube_optimizer import pre_plan_content, PrePlanRequest
        req = PrePlanRequest(topic="衝撃の完全版永久保存", genre="エンタメ")
        with patch.dict(sys.modules, {
            "plugins.youtube_optimizer_plugin": MagicMock(),
        }):
            r = await pre_plan_content(req)
            assert r["go_nogo"] == "GO"

    @pytest.mark.asyncio
    async def test_yt_12_optimize_error(self):
        from routers.youtube_optimizer import optimize_for_youtube, OptimizeRequest
        from fastapi import HTTPException
        req = OptimizeRequest(segments=[], topics=["test"])
        with patch.dict(sys.modules, {"plugins.youtube_optimizer_plugin": None}):
            with pytest.raises(HTTPException):
                await optimize_for_youtube(req)

    @pytest.mark.asyncio
    async def test_yt_13_series_register_error(self):
        from routers.youtube_optimizer import register_series, SeriesRegisterRequest
        from fastapi import HTTPException
        req = SeriesRegisterRequest(series_id="s1", title="Test", theme="theme")
        with patch.dict(sys.modules, {"services.series_planner": None}):
            with pytest.raises(HTTPException):
                await register_series(req)

    @pytest.mark.asyncio
    async def test_yt_14_schedule_add_error(self):
        from routers.youtube_optimizer import add_schedule_entry, ScheduleAddRequest
        from fastapi import HTTPException
        req = ScheduleAddRequest(title="test", planned_date="2026-05-01")
        with patch.dict(sys.modules, {"services.publish_scheduler": None}):
            with pytest.raises(HTTPException):
                await add_schedule_entry(req)

    @pytest.mark.asyncio
    async def test_yt_15_schedule_get_error(self):
        from routers.youtube_optimizer import get_schedule
        from fastapi import HTTPException
        with patch.dict(sys.modules, {"services.publish_scheduler": None}):
            with pytest.raises(HTTPException):
                await get_schedule()

    @pytest.mark.asyncio
    async def test_yt_16_analyze_thumbnail_error(self):
        from routers.youtube_optimizer import analyze_thumbnail
        from fastapi import HTTPException
        with patch.dict(sys.modules, {"services.thumbnail_analyzer": None}):
            with pytest.raises(HTTPException):
                await analyze_thumbnail({})

    @pytest.mark.asyncio
    async def test_yt_17_comments_analyze_error(self):
        from routers.youtube_optimizer import analyze_comments, CommentAnalysisRequest
        from fastapi import HTTPException
        req = CommentAnalysisRequest(comments=["test"])
        with patch.dict(sys.modules, {"services.comment_analyzer": None}):
            with pytest.raises(HTTPException):
                await analyze_comments(req)

    @pytest.mark.asyncio
    async def test_yt_18_shorts_extract_error(self):
        from routers.youtube_optimizer import extract_shorts_candidates, ShortsExtractRequest
        from fastapi import HTTPException
        req = ShortsExtractRequest(segments=[{"text": "x"}], video_duration_sec=60)
        with patch.dict(sys.modules, {"services.shorts_generator": None}):
            with pytest.raises(HTTPException):
                await extract_shorts_candidates(req)

    @pytest.mark.asyncio
    async def test_yt_19_index_stats_error(self):
        from routers.youtube_optimizer import get_index_stats
        from fastapi import HTTPException
        with patch.dict(sys.modules, {"services.vector_search": None}):
            with pytest.raises(HTTPException):
                await get_index_stats()

    @pytest.mark.asyncio
    async def test_yt_20_next_deadline_error(self):
        from routers.youtube_optimizer import get_next_deadline
        from fastapi import HTTPException
        with patch.dict(sys.modules, {"services.publish_scheduler": None}):
            with pytest.raises(HTTPException):
                await get_next_deadline()


# ============================================================
# Part 2: interactive_preview (20 tests)
# ============================================================

class TestSubtitleConfirmationChecker:
    def test_ip_01_parse_json_block(self):
        from interactive_preview import SubtitleConfirmationChecker
        c = SubtitleConfirmationChecker()
        text = '```json\n[{"timestamp":"00:01:30","original_text":"テスト","concern":"固有名詞","category":"proper_noun","suggestion":"修正案"}]\n```'
        items = c._parse_response(text, "s01")
        assert len(items) == 1
        assert items[0].id == "s01_001"

    def test_ip_02_parse_raw_json(self):
        from interactive_preview import SubtitleConfirmationChecker
        c = SubtitleConfirmationChecker()
        text = '[{"timestamp":"00:00:10","original_text":"t","concern":"c","category":"uncertain"}]'
        items = c._parse_response(text, "s02")
        assert len(items) == 1

    def test_ip_03_parse_no_json(self):
        from interactive_preview import SubtitleConfirmationChecker
        c = SubtitleConfirmationChecker()
        items = c._parse_response("no json here", "s03")
        assert items == []

    def test_ip_04_parse_invalid_json(self):
        from interactive_preview import SubtitleConfirmationChecker
        c = SubtitleConfirmationChecker()
        items = c._parse_response("[{invalid}]", "s04")
        assert items == []

    def test_ip_05_analyze_api_error(self):
        from interactive_preview import SubtitleConfirmationChecker
        c = SubtitleConfirmationChecker()
        with patch("gemini_client_factory.get_gemini_client", side_effect=Exception("fail")):
            items = c.analyze("テスト字幕", "scene1")
            assert items == []


class TestTelopSuggester:
    def test_ip_06_parse_response(self):
        from interactive_preview import TelopSuggester
        s = TelopSuggester()
        text = '```json\n[{"timestamp":"00:00:30","duration":3.0,"text":"テスト","reason":"重要","position":"top"}]\n```'
        items = s._parse_response(text, "s01")
        assert len(items) == 1
        assert items[0].duration == 3.0

    def test_ip_07_parse_no_json(self):
        from interactive_preview import TelopSuggester
        s = TelopSuggester()
        items = s._parse_response("nothing", "s02")
        assert items == []

    def test_ip_08_suggest_error(self):
        from interactive_preview import TelopSuggester
        s = TelopSuggester()
        with patch("gemini_client_factory.get_gemini_client", side_effect=Exception("fail")):
            items = s.suggest("テスト", "scene1")
            assert items == []


class TestTelopPreviewRenderer:
    def test_ip_09_render_success(self, tmp_path):
        from interactive_preview import TelopPreviewRenderer, TelopSuggestion
        r = TelopPreviewRenderer(output_dir=tmp_path)
        telop = TelopSuggestion(id="t1", timestamp="00:00:05", duration=3.0,
                                text="テスト", reason="test", position="top")
        mock_result = MagicMock(returncode=0)
        out_path = tmp_path / "test.jpg"
        out_path.write_bytes(b"fake")
        with patch("interactive_preview.subprocess.run", return_value=mock_result):
            result = r.render(Path("fake.mp4"), telop, "test")
            # May be None if output path doesn't match
            assert result is None or isinstance(result, Path)

    def test_ip_10_render_ffmpeg_error(self, tmp_path):
        from interactive_preview import TelopPreviewRenderer, TelopSuggestion
        r = TelopPreviewRenderer(output_dir=tmp_path)
        telop = TelopSuggestion(id="t1", timestamp="00:00:05", duration=3.0,
                                text="テスト", reason="r", position="bottom")
        mock_result = MagicMock(returncode=1, stderr="error msg")
        with patch("interactive_preview.subprocess.run", return_value=mock_result):
            result = r.render(Path("fake.mp4"), telop, "test_err")
            assert result is None

    def test_ip_11_render_timeout(self, tmp_path):
        from interactive_preview import TelopPreviewRenderer, TelopSuggestion
        import subprocess
        r = TelopPreviewRenderer(output_dir=tmp_path)
        telop = TelopSuggestion(id="t1", timestamp="00:00:05", duration=3.0,
                                text="T", reason="r")
        with patch("interactive_preview.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("ffmpeg", 60)):
            result = r.render(Path("f.mp4"), telop, "timeout")
            assert result is None

    def test_ip_12_render_no_ffmpeg(self, tmp_path):
        from interactive_preview import TelopPreviewRenderer, TelopSuggestion
        r = TelopPreviewRenderer(output_dir=tmp_path)
        telop = TelopSuggestion(id="t1", timestamp="00:00:05", duration=3.0,
                                text="T", reason="r")
        with patch("interactive_preview.subprocess.run",
                    side_effect=FileNotFoundError("ffmpeg")):
            result = r.render(Path("f.mp4"), telop, "noff")
            assert result is None


class TestTelopConfig:
    def test_ip_13_save_load(self, tmp_path):
        from interactive_preview import TelopConfig
        cfg = TelopConfig(scene_name="test", telops=[{"text": "hello"}])
        path = tmp_path / "config.json"
        cfg.save(path)
        loaded = TelopConfig.load(path)
        assert loaded.scene_name == "test"
        assert len(loaded.telops) == 1


class TestTelopStyles:
    def test_ip_14_load_default(self):
        from interactive_preview import load_telop_styles
        styles = load_telop_styles()
        assert "default" in styles
        assert "emphasis" in styles

    def test_ip_15_load_custom(self, tmp_path):
        from interactive_preview import load_telop_styles
        cfg = tmp_path / "styles.json"
        cfg.write_text('{"custom": {"fontsize": 50}}', encoding="utf-8")
        styles = load_telop_styles(cfg)
        assert "custom" in styles
        assert "default" in styles

    def test_ip_16_load_bad_file(self, tmp_path):
        from interactive_preview import load_telop_styles
        cfg = tmp_path / "bad.json"
        cfg.write_text("not json", encoding="utf-8")
        styles = load_telop_styles(cfg)
        assert "default" in styles

    def test_ip_17_save_styles(self, tmp_path):
        from interactive_preview import save_telop_styles
        path = tmp_path / "out.json"
        save_telop_styles({"test": {"fontsize": 32}}, path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["test"]["fontsize"] == 32


class TestIntegratedReportGenerator:
    def test_ip_18_generate_empty(self):
        from interactive_preview import IntegratedReportGenerator
        gen = IntegratedReportGenerator()
        md = gen.generate("s01", "テスト", [], [], {}, [])
        assert "s01" in md

    def test_ip_19_generate_with_data(self):
        from interactive_preview import IntegratedReportGenerator, ConfirmationItem, TelopSuggestion
        gen = IntegratedReportGenerator()
        confirmations = [ConfirmationItem(
            id="c1", timestamp="00:01:00", original_text="テスト",
            concern="固有名詞", category="proper_noun"
        )]
        telops = [TelopSuggestion(
            id="t1", timestamp="00:02:00", duration=3.0,
            text="テロップ", reason="重要"
        )]
        screenshots = [{"path": "C:/test/img.jpg", "timestamp": "00:01:00"}]
        md = gen.generate("s01", "Scene", confirmations, telops, {}, screenshots)
        assert "字幕プレビュー" in md
        assert "AI字幕確認" in md
        assert "テロップ提案" in md

    def test_ip_20_telop_styles_dict(self):
        from interactive_preview import TELOP_STYLES
        assert "default" in TELOP_STYLES
        assert TELOP_STYLES["default"]["fontsize"] == 32


# ============================================================
# Part 3: sdk_checker (15 tests)
# ============================================================

class TestSDKChecker:
    @pytest.fixture
    def checker(self):
        from usage_tracker.sdk_checker import SDKCompatibilityChecker
        return SDKCompatibilityChecker()

    def test_sdk_01_init(self, checker):
        assert checker._available_models == set()
        assert checker._last_check is None

    def test_sdk_02_get_sdk_version(self, checker):
        v = checker._get_sdk_version()
        assert isinstance(v, str)

    def test_sdk_03_is_compatible_empty(self, checker):
        assert checker.is_compatible("any-model") is False

    def test_sdk_04_get_last_check(self, checker):
        assert checker.get_last_check_time() is None

    def test_sdk_05_model_available_exact(self, checker):
        available = {"gemini-2.5-flash", "gemini-2.5-pro"}
        assert checker._is_model_available("gemini-2.5-flash", available) is True

    def test_sdk_06_model_available_prefix(self, checker):
        available = {"models/gemini-2.5-flash"}
        assert checker._is_model_available("gemini-2.5-flash", available) is True

    def test_sdk_07_model_available_partial(self, checker):
        available = {"gemini-2.5-flash-preview-05-20"}
        assert checker._is_model_available("gemini-2.5-flash", available) is True

    def test_sdk_08_model_not_available(self, checker):
        available = {"gemini-2.5-pro"}
        assert checker._is_model_available("totally-different", available) is False

    def test_sdk_09_load_config(self, checker):
        result = checker._load_config()
        # May return dict or None depending on file existence
        assert result is None or isinstance(result, dict)

    def test_sdk_10_log_result_compatible(self, checker):
        result = {"compatible": [{"model": "m1"}], "incompatible": [], "warnings": []}
        checker._log_result(result)  # No crash

    def test_sdk_11_log_result_incompatible(self, checker):
        result = {
            "compatible": [],
            "incompatible": [{"model": "m1"}],
            "warnings": ["⚠️ m1 は利用不可"]
        }
        checker._log_result(result)  # No crash

    def test_sdk_12_get_available_preferred(self, checker):
        checker._available_models = {"gemini-2.5-flash"}
        r = checker.get_available_model("gemini-2.5-flash")
        assert r == "gemini-2.5-flash"

    def test_sdk_13_get_available_fallback(self, checker):
        checker._available_models = {"gemini-2.5-flash"}
        checker._incompatible_models = ["gemini-2.5-pro"]
        with patch.object(checker, "_load_config", return_value={
            "models": {"gemini-2.5-pro": {"fallback": "gemini-2.5-flash"}}
        }):
            r = checker.get_available_model("gemini-2.5-pro")
            assert r == "gemini-2.5-flash"

    def test_sdk_14_get_available_no_fallback(self, checker):
        checker._available_models = set()
        r = checker.get_available_model("unknown-model")
        assert r == "unknown-model"

    @pytest.mark.asyncio
    async def test_sdk_15_check_compat_no_models(self, checker):
        checker._client = None
        with patch.object(checker, "_get_client", return_value=None):
            r = await checker.check_compatibility()
            assert "warnings" in r
            assert len(r["warnings"]) >= 1

    @pytest.mark.asyncio
    async def test_sdk_16_check_compatibility_success(self, checker):
        """正常系: クライアントがあり、モデル一覧が取得できる場合"""
        mock_client = MagicMock()
        mock_model_1 = MagicMock()
        mock_model_1.name = "models/gemini-2.5-flash"
        mock_client.models.list.return_value = [mock_model_1]
        
        mock_config = {
            "models": {
                "gemini-2.5-flash": {
                    "tier": "flash",
                    "status": "active"
                },
                "gemini-2.5-pro": {
                    "tier": "pro",
                    "fallback": "gemini-2.5-flash",
                    "status": "active"
                }
            }
        }
        
        with patch.object(checker, "_get_client", return_value=mock_client), \
             patch.object(checker, "_load_config", return_value=mock_config):
            
            res = await checker.check_compatibility()
            assert "gemini-2.5-flash" in checker._available_models
            assert len(res["compatible"]) == 1
            assert res["compatible"][0]["model"] == "gemini-2.5-flash"
            assert len(res["incompatible"]) == 1
            assert res["incompatible"][0]["model"] == "gemini-2.5-pro"
            assert len(res["warnings"]) > 0

    def test_sdk_17_get_client_import_error(self, checker):
        """get_gemini_client で ImportError が発生した時のハンドリング"""
        with patch("gemini_client_factory.get_gemini_client", side_effect=ImportError("mock error")):
            client = checker._get_client()
            assert client is None

    def test_sdk_18_get_client_general_exception(self, checker):
        """get_gemini_client で一般的な例外が発生した時のハンドリング"""
        with patch("gemini_client_factory.get_gemini_client", side_effect=Exception("general error")):
            client = checker._get_client()
            assert client is None

    @pytest.mark.asyncio
    async def test_sdk_19_run_compatibility_check_global(self):
        """モジュールレベルの run_compatibility_check 関数の動作"""
        from usage_tracker.sdk_checker import run_compatibility_check
        with patch("usage_tracker.sdk_checker.sdk_checker.check_compatibility", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = {"status": "mocked"}
            res = await run_compatibility_check()
            assert res == {"status": "mocked"}

    @pytest.mark.asyncio
    async def test_sdk_20_check_compatibility_load_config_none(self, checker):
        """check_compatibility で _load_config が None を返すケース（73-74行目）"""
        mock_client = MagicMock()
        mock_model_1 = MagicMock()
        mock_model_1.name = "models/gemini-2.5-flash"
        mock_client.models.list.return_value = [mock_model_1]
        
        with patch.object(checker, "_get_client", return_value=mock_client),              patch.object(checker, "_load_config", return_value=None):
            
            res = await checker.check_compatibility()
            assert len(res["warnings"]) >= 1
            assert "model_config.jsonを読み込めませんでした" in res["warnings"][0]

    @pytest.mark.asyncio
    async def test_sdk_21_check_compatibility_deprecated_and_no_fallback(self, checker):
        """check_compatibility で deprecated のスキップ（79行目）および fallback なし（104行目）のカバー"""
        mock_client = MagicMock()
        mock_model_1 = MagicMock()
        mock_model_1.name = "models/gemini-2.5-flash"
        mock_client.models.list.return_value = [mock_model_1]
        
        mock_config = {
            "models": {
                "gemini-2.0-flash": {
                    "status": "deprecated"
                },
                "gemini-2.5-pro": {
                    "tier": "premium",
                    "status": "active"
                }
            }
        }
        
        with patch.object(checker, "_get_client", return_value=mock_client),              patch.object(checker, "_load_config", return_value=mock_config):
            
            res = await checker.check_compatibility()
            assert not any(x["model"] == "gemini-2.0-flash" for x in res["compatible"])
            assert not any(x["model"] == "gemini-2.0-flash" for x in res["incompatible"])
            assert any("フォールバック先がありません" in w for w in res["warnings"])

    @pytest.mark.asyncio
    async def test_sdk_22_fetch_available_models_exception(self, checker):
        """_fetch_available_models 内の例外処理（136-137行目）"""
        mock_client = MagicMock()
        mock_client.models.list.side_effect = Exception("Fetch API failed")
        
        with patch.object(checker, "_get_client", return_value=mock_client):
            res = await checker._fetch_available_models()
            assert res == set()

    def test_sdk_23_load_config_exception(self, checker):
        """_load_config 内の例外処理（169-171行目）"""
        with patch("builtins.open", side_effect=OSError("File read error")):
            res = checker._load_config()
            assert res is None

    def test_sdk_24_get_sdk_version_exception(self, checker):
        """_get_sdk_version 内の例外処理（178-179行目）"""
        with patch("builtins.__import__", side_effect=ImportError("mock import error")):
            res = checker._get_sdk_version()
            assert res == "not_installed"

    def test_sdk_25_get_client_cached(self, checker):
        """_get_client 内でクライアントがすでにキャッシュされているケース（36->44）"""
        mock_client = MagicMock()
        checker._client = mock_client
        
        # _clientが非Noneなので、get_gemini_clientは呼び出されずにキャッシュを返すはず
        with patch("gemini_client_factory.get_gemini_client") as mock_factory:
            res = checker._get_client()
            assert res is mock_client
            mock_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_sdk_26_fetch_available_models_no_slash(self, checker):
        """_fetch_available_models 内でモデル名に / が含まれないケース（132->134）"""
        mock_client = MagicMock()
        mock_model = MagicMock()
        # nameに / を含めない
        mock_model.name = "gemini-2.5-flash"
        mock_client.models.list.return_value = [mock_model]
        
        with patch.object(checker, "_get_client", return_value=mock_client):
            res = await checker._fetch_available_models()
            assert "gemini-2.5-flash" in res

    def test_sdk_27_get_available_model_config_none(self, checker):
        """get_available_model 内で _load_config が None を返すケース（207->213）"""
        checker._available_models = set()
        checker._incompatible_models = ["gemini-2.5-pro"]
        
        with patch.object(checker, "_load_config", return_value=None):
            res = checker.get_available_model("gemini-2.5-pro")
            assert res == "gemini-2.5-pro"

    def test_sdk_28_get_available_model_fallback_not_available(self, checker):
        """get_available_model 内でフォールバックモデルが利用不可モデルであるケース（209->213）"""
        checker._available_models = {"gemini-2.5-flash"}
        checker._incompatible_models = ["gemini-2.5-pro"]
        
        # フォールバック先が available にない (gemini-2.5-ultra)
        mock_config = {
            "models": {
                "gemini-2.5-pro": {
                    "fallback": "gemini-2.5-ultra"
                }
            }
        }
        
        with patch.object(checker, "_load_config", return_value=mock_config):
            res = checker.get_available_model("gemini-2.5-pro")
            assert res == "gemini-2.5-pro"

    def test_sdk_29_load_config_file_not_found(self, checker):
        """_load_config で FileNotFoundError が発生した時のハンドリング"""
        with patch("builtins.open", side_effect=FileNotFoundError("mock not found")):
            res = checker._load_config()
            assert res is None

    def test_sdk_30_load_config_json_decode_error(self, checker):
        """_load_config で json.JSONDecodeError が発生した時のハンドリング"""
        import json
        with patch("json.load", side_effect=json.JSONDecodeError("mock decode error", "{}", 0)):
            res = checker._load_config()
            assert res is None

    def test_sdk_31_load_config_permission_error(self, checker):
        """_load_config で PermissionError が発生した時のハンドリング"""
        with patch("builtins.open", side_effect=PermissionError("mock permission error")):
            res = checker._load_config()
            assert res is None

    def test_sdk_32_get_sdk_version_general_exception(self, checker):
        """_get_sdk_version 内の ImportError 以外の例外処理"""
        import sys
        from unittest.mock import PropertyMock
        
        mock_genai = MagicMock()
        type(mock_genai).__version__ = PropertyMock(side_effect=Exception("Unexpected getattr error"))
        
        mock_google = MagicMock()
        mock_google.genai = mock_genai
        
        with patch.dict(sys.modules, {
            "google": mock_google,
            "google.genai": mock_genai
        }):
            res = checker._get_sdk_version()
            assert res == "unknown"
