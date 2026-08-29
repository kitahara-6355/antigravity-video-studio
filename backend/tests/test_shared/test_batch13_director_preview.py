"""
Batch 13: director_engine残り + interactive_preview残り
M2.6 カバレッジ 63% → 70% (Batch 13/14)

合計: ~55テスト
"""
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# ============================================================
# Part 1: director_engine 残り (30 tests)
# ============================================================

class TestDirectorBrainRouting:
    """DirectorBrain — route_to_agents, consult, chat_session"""

    @pytest.fixture
    def mock_brain(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '{"intent":"test","agents":["Director"],"confidence":0.9,"rationale":"test"}'
        mock_client.models.generate_content.return_value = mock_resp
        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_resp
        mock_client.chats.create.return_value = mock_chat

        with patch("director_engine.get_gemini_client", return_value=mock_client):
            with patch("director_engine.get_model", return_value="gemini-2.5-flash"):
                with patch("director_engine.branding_manager") as mock_bm:
                    mock_bm.constitution = {"channel_name": "Test", "brand_personality": {"tone": "f"}, "visual_identity": {"style_prompt": "s"}}
                    mock_bm.user_model = {"ranks": {"biz_rank": {"level": "Novice"}, "tech_rank": {"level": "Novice"}}, "automation_settings": {"auto_pilot_ratio": 0.9}}
                    mock_bm.get_context_block.return_value = "context"
                    mock_bm.get_deep_context.return_value = "deep"
                    from director_engine import DirectorBrain
                    brain = DirectorBrain()
                    return brain

    def test_de_01_route_to_agents_director(self, mock_brain):
        result = mock_brain.route_to_agents("もっとエモくして")
        assert "dispatch" in result
        assert "responses" in result

    def test_de_02_route_to_agents_strategist(self, mock_brain):
        mock_brain.client.models.generate_content.return_value.text = json.dumps({
            "intent": "収益化", "agents": ["Strategist"], "confidence": 0.9, "rationale": "biz"
        })
        result = mock_brain.route_to_agents("数字伸ばしたい")
        assert "Strategist" in result["responses"]

    def test_de_03_route_to_agents_analyst(self, mock_brain):
        mock_brain.client.models.generate_content.return_value.text = json.dumps({
            "intent": "分析", "agents": ["Analyst"], "confidence": 0.8, "rationale": "data"
        })
        result = mock_brain.route_to_agents("品質チェックして")
        assert "Analyst" in result["responses"]

    def test_de_04_route_to_agents_all(self, mock_brain):
        mock_brain.client.models.generate_content.return_value.text = json.dumps({
            "intent": "曖昧", "agents": ["Strategist", "Director", "Analyst"], "confidence": 0.5, "rationale": "all"
        })
        result = mock_brain.route_to_agents("なんかイマイチ")
        assert len(result["responses"]) == 3

    def test_de_05_get_analyst_response(self, mock_brain):
        mock_brain.client.models.generate_content.return_value.text = "分析結果テスト"
        result = mock_brain._get_analyst_response("品質はどう？")
        assert isinstance(result, str)

    def test_de_06_get_analyst_error(self, mock_brain):
        mock_brain.client.models.generate_content.side_effect = Exception("API err")
        result = mock_brain._get_analyst_response("test")
        assert "分析エラー" in result
        mock_brain.client.models.generate_content.side_effect = None

    def test_de_07_consult(self, mock_brain):
        result = mock_brain.consult([], "戦略を教えて")
        assert isinstance(result, str)

    def test_de_08_consult_error(self, mock_brain):
        mock_brain.client.chats.create.side_effect = Exception("chat err")
        result = mock_brain.consult([], "test")
        assert "Error" in result
        mock_brain.client.chats.create.side_effect = None

    def test_de_09_chat_session(self, mock_brain):
        result = mock_brain.chat_session([], "演出提案して")
        assert isinstance(result, str)

    def test_de_10_chat_session_error(self, mock_brain):
        mock_brain.client.chats.create.side_effect = Exception("chat err")
        result = mock_brain.chat_session([], "test")
        assert "Error" in result
        mock_brain.client.chats.create.side_effect = None

    def test_de_11_system_instruction_consult(self, mock_brain):
        inst = mock_brain._get_system_instruction(mode="consult")
        assert "左脳" in inst or "戦略" in inst or "AUTO-PILOT" in inst

    def test_de_12_system_instruction_director(self, mock_brain):
        inst = mock_brain._get_system_instruction(mode="director")
        assert "右脳" in inst or "技術" in inst or "AUTO-PILOT" in inst


class TestDirectorBrainGeneration:
    """DirectorBrain — image/storyboard/batch generation"""

    @pytest.fixture
    def mock_brain(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "test response"
        mock_client.models.generate_content.return_value = mock_resp

        with patch("director_engine.get_gemini_client", return_value=mock_client):
            with patch("director_engine.get_model", return_value="gemini-2.5-flash"):
                with patch("director_engine.branding_manager") as mock_bm:
                    mock_bm.constitution = {"visual_identity": {"style_prompt": "modern"}}
                    mock_bm.user_model = {"ranks": {"biz_rank": {"level": "Novice"}, "tech_rank": {"level": "Novice"}}, "automation_settings": {"auto_pilot_ratio": 0.9}}
                    mock_bm.get_context_block.return_value = "ctx"
                    mock_bm.get_deep_context.return_value = "deep"
                    from director_engine import DirectorBrain
                    return DirectorBrain()

    def test_de_13_generate_image_success(self, mock_brain):
        mock_img = MagicMock()
        mock_img.image.image_bytes = b"img_data"
        mock_brain.client.models.generate_images.return_value = MagicMock(generated_images=[mock_img])
        result = mock_brain.generate_image("test prompt")
        assert len(result) > 0

    def test_de_14_generate_image_error(self, mock_brain):
        mock_brain.client.models.generate_images.side_effect = Exception("API err")
        result = mock_brain.generate_image("test")
        assert result == []
        mock_brain.client.models.generate_images.side_effect = None

    def test_de_15_process_image_task_success(self, mock_brain):
        from director_engine import task_manager
        tid = task_manager.create_task()
        mock_img = MagicMock()
        mock_img.image.image_bytes = b"PNG"
        mock_brain.client.models.generate_images.return_value = MagicMock(generated_images=[mock_img])
        mock_brain.process_image_task(tid, "test prompt")
        assert task_manager.get_task(tid)["status"] == "completed"

    def test_de_16_process_image_task_no_images(self, mock_brain):
        from director_engine import task_manager
        tid = task_manager.create_task()
        mock_brain.client.models.generate_images.return_value = MagicMock(generated_images=[])
        mock_brain.process_image_task(tid, "test")
        assert task_manager.get_task(tid)["status"] == "failed"

    def test_de_17_process_image_task_exception(self, mock_brain):
        from director_engine import task_manager
        tid = task_manager.create_task()
        mock_brain.client.models.generate_images.side_effect = Exception("boom")
        mock_brain.process_image_task(tid, "test")
        assert task_manager.get_task(tid)["status"] == "failed"
        mock_brain.client.models.generate_images.side_effect = None

    def test_de_18_generate_storyboard_plan(self, mock_brain):
        mock_brain.client.models.generate_content.return_value.text = json.dumps([
            {"index": 0, "source_type": "AI", "rationale": "test", "visual_prompt": "p", "asset_suggestion": None}
        ])
        result = mock_brain.generate_storyboard_plan("script", [{"name": "s1", "description": "d"}], {"name": "style", "visual_prompt": "vp", "description": "desc"})
        assert isinstance(result, str)

    def test_de_19_generate_storyboard_error(self, mock_brain):
        mock_brain.client.models.generate_content.side_effect = Exception("err")
        result = mock_brain.generate_storyboard_plan("script", [{"name": "s1", "description": "d"}], {"name": "s", "visual_prompt": "v", "description": "d"})
        data = json.loads(result)
        assert data[0]["source_type"] == "AI"
        mock_brain.client.models.generate_content.side_effect = None

    def test_de_20_process_batch_image_task(self, mock_brain):
        from director_engine import task_manager
        tid = task_manager.create_task()
        mock_img = MagicMock()
        mock_img.image.image_bytes = b"PNG"
        mock_brain.client.models.generate_images.return_value = MagicMock(generated_images=[mock_img])
        with patch("director_engine.time.sleep"):
            mock_brain.process_batch_image_task(tid, [{"name": "s1", "description": "d"}], "style")
        assert task_manager.get_task(tid)["status"] == "completed"

    def test_de_21_process_batch_image_task_error(self, mock_brain):
        """generate_imageが内部でexceptionをcatchし空リスト返却→ループは正常完了"""
        from director_engine import task_manager
        tid = task_manager.create_task()
        mock_brain.client.models.generate_images.side_effect = Exception("batch err")
        with patch("director_engine.time.sleep"):
            mock_brain.process_batch_image_task(tid, [{"name": "s1", "description": "d"}], "style")
        # generate_image catches the exception internally → returns [] → loop completes
        assert task_manager.get_task(tid)["status"] == "completed"
        mock_brain.client.models.generate_images.side_effect = None

    def test_de_22_generate_production_report(self, mock_brain):
        mock_brain.client.models.generate_content.return_value.text = json.dumps({
            "summary": "ok", "success_factor": "f", "issue_detected": "i", "xp_grant": 50
        })
        result = mock_brain.generate_production_report([], {}, "Novice")
        assert isinstance(result, str)

    def test_de_23_generate_production_report_error(self, mock_brain):
        mock_brain.client.models.generate_content.side_effect = Exception("err")
        result = mock_brain.generate_production_report([], {})
        data = json.loads(result)
        assert data["xp_grant"] == 50
        mock_brain.client.models.generate_content.side_effect = None

    def test_de_24_verify_production_quality(self, mock_brain):
        mock_brain.client.models.generate_content.return_value.text = json.dumps({
            "is_ready": True, "score": 90, "critical_issues": [], "suggestions": [], "final_verdict": "OK"
        })
        result = mock_brain.verify_production_quality("text", [{"name": "s1", "source_type": "AI"}], [{"text": "t"}])
        assert isinstance(result, str)

    def test_de_25_verify_production_quality_error(self, mock_brain):
        mock_brain.client.models.generate_content.side_effect = Exception("err")
        result = mock_brain.verify_production_quality("text", [], [])
        data = json.loads(result)
        # **検査が落ちたら「進行可能」と言わない**（R1.5-C4）。旧 `is_ready: True` を置換
        assert data["is_ready"] is False
        assert data["score"] is None
        mock_brain.client.models.generate_content.side_effect = None

    def test_de_26_analyze_resource_needs(self, mock_brain):
        mock_brain.client.models.generate_content.return_value.text = json.dumps([
            {"id": "a1", "name": "Logo", "category": "Logo", "reason": "test"}
        ])
        result = mock_brain.analyze_resource_needs("script mentioning Uniqlo")
        assert isinstance(result, str)

    def test_de_27_analyze_resource_needs_error(self, mock_brain):
        mock_brain.client.models.generate_content.side_effect = Exception("err")
        result = mock_brain.analyze_resource_needs("test")
        assert json.loads(result) == []
        mock_brain.client.models.generate_content.side_effect = None

    def test_de_28_calculate_quality_score(self, mock_brain):
        mock_brain.client.models.generate_content.return_value.text = json.dumps({
            "score": 85, "rank": "A", "comment": "good", "advice": "none", "is_acceptable": True
        })
        result = mock_brain.calculate_quality_score([], "Novice")
        assert isinstance(result, str)

    def test_de_29_calculate_quality_score_error(self, mock_brain):
        mock_brain.client.models.generate_content.side_effect = Exception("err")
        result = mock_brain.calculate_quality_score([])
        data = json.loads(result)
        # **採点が落ちたら点も合格も名乗らない**（R1.5-C4）。旧 `rank: "C"` を置換
        assert data["rank"] is None
        assert data["is_acceptable"] is False
        mock_brain.client.models.generate_content.side_effect = None

    def test_de_30_analyze_script_fallback(self, mock_brain):
        mock_brain.client.models.generate_content.side_effect = Exception("err")
        result = mock_brain.analyze_script("test script")
        data = json.loads(result)
        assert len(data) == 3
        assert data[0]["id"] == "style_a"
        mock_brain.client.models.generate_content.side_effect = None


# ============================================================
# Part 2: interactive_preview 残り (25 tests)
# ============================================================

class TestTelopSuggester:
    """TelopSuggester — テロップ提案"""

    def test_ip_01_parse_json_block(self):
        from interactive_preview import TelopSuggester
        s = TelopSuggester()
        text = '```json\n[{"timestamp":"00:01:00","duration":3.0,"text":"テスト","reason":"r","position":"top"}]\n```'
        result = s._parse_response(text, "scene1")
        assert len(result) == 1
        assert result[0].text == "テスト"

    def test_ip_02_parse_raw_json(self):
        from interactive_preview import TelopSuggester
        s = TelopSuggester()
        text = '[{"timestamp":"00:02:00","duration":2.0,"text":"raw","reason":"r","position":"bottom"}]'
        result = s._parse_response(text, "scene2")
        assert len(result) == 1
        assert result[0].position == "bottom"

    def test_ip_03_parse_no_json(self):
        from interactive_preview import TelopSuggester
        s = TelopSuggester()
        result = s._parse_response("no json here", "scene3")
        assert result == []

    def test_ip_04_parse_invalid_json(self):
        from interactive_preview import TelopSuggester
        s = TelopSuggester()
        result = s._parse_response("[{invalid json}]", "scene4")
        assert result == []

    def test_ip_05_parse_type_error(self):
        from interactive_preview import TelopSuggester
        s = TelopSuggester()
        # duration as non-numeric
        result = s._parse_response('[{"timestamp":"00:00:00","duration":"bad","text":"t","reason":"r"}]', "s")
        # Should handle gracefully (ValueError on float conversion)
        assert isinstance(result, list)


class TestTelopPreviewRendererExtended:
    """TelopPreviewRenderer — 追加パス"""

    def test_ip_06_render_success(self, tmp_path):
        from interactive_preview import TelopPreviewRenderer, TelopSuggestion
        renderer = TelopPreviewRenderer(tmp_path)
        telop = TelopSuggestion(id="t1", timestamp="00:00:05", duration=3.0, text="テスト", reason="r", position="bottom")
        output_path = tmp_path / "test.jpg"
        output_path.write_bytes(b"fake jpg")
        mock_result = MagicMock(returncode=0)
        with patch("interactive_preview.subprocess.run", return_value=mock_result):
            result = renderer.render(tmp_path / "video.mp4", telop, "test", "emphasis")
            assert result is not None

    def test_ip_07_render_ffmpeg_error(self, tmp_path):
        from interactive_preview import TelopPreviewRenderer, TelopSuggestion
        renderer = TelopPreviewRenderer(tmp_path)
        telop = TelopSuggestion(id="t2", timestamp="00:00:05", duration=3.0, text="テスト", reason="r")
        mock_result = MagicMock(returncode=1, stderr="ffmpeg error")
        with patch("interactive_preview.subprocess.run", return_value=mock_result):
            result = renderer.render(tmp_path / "fake.mp4", telop, "fail_test")
            assert result is None

    def test_ip_08_render_generic_exception(self, tmp_path):
        from interactive_preview import TelopPreviewRenderer, TelopSuggestion
        renderer = TelopPreviewRenderer(tmp_path)
        telop = TelopSuggestion(id="t3", timestamp="00:00:05", duration=3.0, text="テスト", reason="r")
        with patch("interactive_preview.subprocess.run", side_effect=RuntimeError("unexpected")):
            result = renderer.render(tmp_path / "fake.mp4", telop, "err_test")
            assert result is None


class TestTelopConfigExtended:
    """TelopConfig — save/load追加"""

    def test_ip_09_save_load_roundtrip(self, tmp_path):
        from interactive_preview import TelopConfig
        config = TelopConfig(scene_name="scene_test", telops=[{"text": "t"}], confirmations=[])
        path = tmp_path / "config.json"
        config.save(path)
        loaded = TelopConfig.load(path)
        assert loaded.scene_name == "scene_test"
        assert len(loaded.telops) == 1

    def test_ip_10_load_missing_file(self, tmp_path):
        from interactive_preview import TelopConfig
        with pytest.raises(FileNotFoundError):
            TelopConfig.load(tmp_path / "missing.json")


class TestTelopStylesManagement:
    """load_telop_styles / save_telop_styles"""

    def test_ip_11_load_default_styles(self):
        from interactive_preview import load_telop_styles
        styles = load_telop_styles(None)
        assert "default" in styles
        assert "emphasis" in styles

    def test_ip_12_load_custom_styles(self, tmp_path):
        from interactive_preview import load_telop_styles
        custom = tmp_path / "styles.json"
        custom.write_text('{"custom_style": {"fontsize": 50}}', encoding="utf-8")
        styles = load_telop_styles(custom)
        assert "custom_style" in styles
        assert "default" in styles

    def test_ip_13_load_invalid_custom(self, tmp_path):
        from interactive_preview import load_telop_styles
        bad = tmp_path / "bad.json"
        bad.write_text("{invalid}", encoding="utf-8")
        styles = load_telop_styles(bad)
        assert "default" in styles

    def test_ip_14_save_styles(self, tmp_path):
        from interactive_preview import save_telop_styles
        path = tmp_path / "saved.json"
        save_telop_styles({"test": {"fontsize": 20}}, path)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["test"]["fontsize"] == 20


class TestIntegratedReportGeneratorExtended:
    """IntegratedReportGenerator — 全パターン"""

    @pytest.fixture
    def gen(self):
        from interactive_preview import IntegratedReportGenerator
        return IntegratedReportGenerator()

    def test_ip_15_empty_report(self, gen):
        md = gen.generate("s1", "Scene1", [], [], {}, [])
        assert "s1" in md
        assert "Scene1" in md

    def test_ip_16_with_confirmations(self, gen):
        from interactive_preview import ConfirmationItem
        items = [ConfirmationItem(id="c1", timestamp="00:01:00", original_text="テスト文字列", concern="誤字の可能性", category="typo", suggestion="修正案")]
        md = gen.generate("s2", "Scene2", items, [], {}, [])
        assert "AI字幕確認" in md
        assert "c1" in md

    def test_ip_17_with_telop_suggestions(self, gen):
        from interactive_preview import TelopSuggestion
        telops = [TelopSuggestion(id="t1", timestamp="00:02:00", duration=3.0, text="テロップテスト", reason="重要", position="top")]
        md = gen.generate("s3", "Scene3", [], telops, {}, [])
        assert "テロップ提案" in md
        assert "テロップテスト" in md

    def test_ip_18_with_telop_previews(self, gen, tmp_path):
        from interactive_preview import TelopSuggestion
        telops = [TelopSuggestion(id="t1", timestamp="00:02:00", duration=3.0, text="Preview", reason="test")]
        preview_path = tmp_path / "preview.jpg"
        preview_path.write_bytes(b"fake")
        md = gen.generate("s4", "Scene4", [], telops, {"t1": preview_path}, [])
        assert "Telop Preview" in md

    def test_ip_19_with_screenshots(self, gen):
        screenshots = [{"path": "C:\\test\\screenshot.jpg", "timestamp": "00:01:30"}]
        md = gen.generate("s5", "Scene5", [], [], {}, screenshots)
        assert "字幕プレビュー" in md
        assert "carousel" in md

    def test_ip_20_screenshots_with_related_confirmations(self, gen):
        from interactive_preview import ConfirmationItem
        items = [ConfirmationItem(id="c1", timestamp="00:01:30", original_text="テスト", concern="check", category="uncertain")]
        screenshots = [{"path": "C:\\test\\ss.jpg", "timestamp": "00:01:30"}]
        md = gen.generate("s6", "Scene6", items, [], {}, screenshots)
        assert "確認事項" in md

    def test_ip_21_multiple_slides(self, gen):
        screenshots = [
            {"path": "C:\\test\\s1.jpg", "timestamp": "00:00:30"},
            {"path": "C:\\test\\s2.jpg", "timestamp": "00:01:00"},
            {"path": "C:\\test\\s3.jpg", "timestamp": "00:01:30"},
        ]
        md = gen.generate("s7", "Scene7", [], [], {}, screenshots)
        assert md.count("slide") == 2  # 2 separators for 3 slides


class TestRunFullPipeline:
    """run_full_pipeline — 統合パイプライン"""

    def test_ip_22_full_pipeline_no_srt(self, tmp_path):
        from interactive_preview import run_full_pipeline
        scenes = [{"name": "test_scene", "video": str(tmp_path / "fake.mp4")}]
        with patch("interactive_preview.SubtitleConfirmationChecker.analyze", return_value=[]):
            with patch("interactive_preview.TelopSuggester.suggest", return_value=[]):
                report = run_full_pipeline(scenes, tmp_path)
                assert "インタラクティブプレビュー" in report

    def test_ip_23_full_pipeline_with_srt(self, tmp_path):
        from interactive_preview import run_full_pipeline, ConfirmationItem, TelopSuggestion
        srt_file = tmp_path / "test.srt"
        srt_file.write_text("1\n00:00:00,000 --> 00:00:05,000\nテスト字幕\n", encoding="utf-8")
        scenes = [{"name": "test_scene", "scene_id": "s1", "video": str(tmp_path / "fake.mp4"), "subtitle": str(srt_file)}]
        mock_conf = [ConfirmationItem(id="c1", timestamp="00:00:01", original_text="t", concern="c", category="typo")]
        mock_telop = [TelopSuggestion(id="t1", timestamp="00:00:02", duration=3.0, text="telop", reason="r")]
        with patch("interactive_preview.SubtitleConfirmationChecker.analyze", return_value=mock_conf):
            with patch("interactive_preview.TelopSuggester.suggest", return_value=mock_telop):
                report = run_full_pipeline(scenes, tmp_path)
                assert "確認完了後" in report

    def test_ip_24_full_pipeline_config_saved(self, tmp_path):
        from interactive_preview import run_full_pipeline
        scenes = [{"name": "test_scene", "scene_id": "s_config", "video": str(tmp_path / "fake.mp4")}]
        with patch("interactive_preview.SubtitleConfirmationChecker.analyze", return_value=[]):
            with patch("interactive_preview.TelopSuggester.suggest", return_value=[]):
                run_full_pipeline(scenes, tmp_path)
                config_file = tmp_path / "s_config_config.json"
                assert config_file.exists()

    def test_ip_25_confirmation_item_dataclass(self):
        from interactive_preview import ConfirmationItem
        item = ConfirmationItem(
            id="test", timestamp="00:00:00", original_text="orig",
            concern="issue", category="proper_noun",
            suggestion="fix", status="pending", modified_text=None
        )
        assert item.id == "test"
        assert item.status == "pending"
