"""
M2.5: Interactive Preview テスト — 22テスト

interactive_preview.py (280 stmts, 280 missed → 0%) のカバレッジ改善。
Phase 4-7 の各クラスを網羅: SubtitleConfirmationChecker, TelopSuggester,
TelopPreviewRenderer, TelopConfig, IntegratedReportGenerator, スタイル管理。

外部依存: Gemini API → モック, FFmpeg → モック。
"""

import pytest
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from dataclasses import asdict

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from interactive_preview import (
    ConfirmationItem,
    SubtitleConfirmationChecker,
    TelopSuggestion,
    TelopSuggester,
    TelopPreviewRenderer,
    TelopConfig,
    IntegratedReportGenerator,
    TELOP_STYLES,
    load_telop_styles,
    save_telop_styles,
)


# ============================================================
# ConfirmationItem / SubtitleConfirmationChecker テスト
# ============================================================

class TestSubtitleConfirmationChecker:
    """Phase 4: AI字幕確認"""

    def test_parse_response_json_block(self):
        """_parse_response: ```json ... ``` 形式"""
        checker = SubtitleConfirmationChecker()
        text = '```json\n[{"timestamp":"00:01:30","original_text":"テスト","concern":"固有名詞","category":"proper_noun","suggestion":"修正"}]\n```'
        items = checker._parse_response(text, "scene1")
        assert len(items) == 1
        assert items[0].id == "scene1_001"
        assert items[0].original_text == "テスト"
        assert items[0].category == "proper_noun"

    def test_parse_response_bare_json(self):
        """_parse_response: ベアJSON形式"""
        checker = SubtitleConfirmationChecker()
        text = '[{"timestamp":"00:00:10","original_text":"ABC","concern":"略称","category":"uncertain"}]'
        items = checker._parse_response(text, "s1")
        assert len(items) == 1
        assert items[0].concern == "略称"

    def test_parse_response_invalid_json(self):
        """_parse_response: 不正JSON → 空リスト"""
        checker = SubtitleConfirmationChecker()
        items = checker._parse_response("This is not JSON", "s1")
        assert items == []

    def test_parse_response_no_json(self):
        """_parse_response: JSONなし → 空リスト"""
        checker = SubtitleConfirmationChecker()
        items = checker._parse_response("No JSON here at all", "s1")
        assert items == []

    def test_analyze_api_failure(self):
        """analyze: API失敗 → 空リスト"""
        checker = SubtitleConfirmationChecker()
        with patch("gemini_client_factory.get_gemini_client", side_effect=RuntimeError("no API")):
            items = checker.analyze("テスト字幕", "scene1")
        assert items == []


# ============================================================
# TelopSuggestion / TelopSuggester テスト
# ============================================================

class TestTelopSuggester:
    """Phase 5: テロップ提案"""

    def test_parse_response_valid(self):
        """_parse_response: 正常なJSON"""
        suggester = TelopSuggester()
        text = '```json\n[{"timestamp":"00:00:30","duration":3.0,"text":"テロップ","reason":"重要","position":"top"}]\n```'
        suggestions = suggester._parse_response(text, "s1")
        assert len(suggestions) == 1
        assert suggestions[0].text == "テロップ"
        assert suggestions[0].duration == 3.0

    def test_parse_response_invalid(self):
        """_parse_response: 不正JSON → 空リスト"""
        suggester = TelopSuggester()
        suggestions = suggester._parse_response("invalid", "s1")
        assert suggestions == []

    def test_suggest_api_failure(self):
        """suggest: API失敗 → 空リスト"""
        suggester = TelopSuggester()
        with patch("gemini_client_factory.get_gemini_client", side_effect=RuntimeError):
            suggestions = suggester.suggest("字幕テスト", "scene1")
        assert suggestions == []


# ============================================================
# TelopPreviewRenderer テスト
# ============================================================

class TestTelopPreviewRenderer:
    """Phase 6: テロッププレビュー生成"""

    def test_render_success(self, tmp_path):
        """render: FFmpeg成功 → ファイルパス"""
        renderer = TelopPreviewRenderer(tmp_path)
        telop = TelopSuggestion(
            id="t1", timestamp="00:00:30", duration=3.0,
            text="テスト", reason="理由", position="top",
        )

        output_path = tmp_path / "test.jpg"
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            # ファイルを事前作成して成功をシミュレート
            output_path.write_bytes(b"\xff\xd8\xff\xe0" * 100)
            result = renderer.render(Path("/fake/video.mp4"), telop, "test")

        assert result is not None

    def test_render_ffmpeg_failure(self, tmp_path):
        """render: FFmpeg失敗 → None"""
        renderer = TelopPreviewRenderer(tmp_path)
        telop = TelopSuggestion(
            id="t1", timestamp="00:00:30", duration=3.0,
            text="テスト", reason="理由", position="bottom",
        )
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error details"

        with patch("subprocess.run", return_value=mock_result):
            result = renderer.render(Path("/fake/video.mp4"), telop, "test")
        assert result is None

    def test_render_ffmpeg_not_found(self, tmp_path):
        """render: FFmpeg未インストール → None"""
        renderer = TelopPreviewRenderer(tmp_path)
        telop = TelopSuggestion(
            id="t1", timestamp="00:00:30", duration=3.0,
            text="テスト", reason="理由",
        )
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = renderer.render(Path("/fake/video.mp4"), telop, "test")
        assert result is None

    def test_render_timeout(self, tmp_path):
        """render: タイムアウト → None"""
        import subprocess
        renderer = TelopPreviewRenderer(tmp_path)
        telop = TelopSuggestion(
            id="t1", timestamp="00:00:30", duration=3.0,
            text="テスト", reason="理由",
        )
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 60)):
            result = renderer.render(Path("/fake/video.mp4"), telop, "test")
        assert result is None


# ============================================================
# TelopConfig テスト
# ============================================================

class TestTelopConfig:
    """Phase 7: テロップ設定ファイル"""

    def test_save_and_load(self, tmp_path):
        """save/load: 保存と読み込みの往復"""
        config = TelopConfig(
            scene_name="テストシーン",
            telops=[{"id": "t1", "text": "テロップ"}],
            confirmations=[{"id": "c1", "text": "確認"}],
        )
        config_path = tmp_path / "test_config.json"
        config.save(config_path)

        loaded = TelopConfig.load(config_path)
        assert loaded.scene_name == "テストシーン"
        assert len(loaded.telops) == 1
        assert len(loaded.confirmations) == 1


# ============================================================
# スタイル管理テスト
# ============================================================

class TestTelopStyles:
    """テロップスタイル設定管理"""

    def test_default_styles(self):
        """TELOP_STYLES: デフォルトスタイル"""
        assert "default" in TELOP_STYLES
        assert "emphasis" in TELOP_STYLES
        assert "subtle" in TELOP_STYLES

    def test_load_telop_styles_no_config(self):
        """load_telop_styles: 設定なし → デフォルト"""
        styles = load_telop_styles(None)
        assert styles == TELOP_STYLES

    def test_load_telop_styles_custom(self, tmp_path):
        """load_telop_styles: カスタム設定の読み込み"""
        custom = {"custom_style": {"fontsize": 48, "fontcolor": "red"}}
        config_path = tmp_path / "styles.json"
        config_path.write_text(json.dumps(custom), encoding="utf-8")

        styles = load_telop_styles(config_path)
        assert "custom_style" in styles
        assert "default" in styles  # デフォルトもマージ

    def test_save_telop_styles(self, tmp_path):
        """save_telop_styles: スタイル保存"""
        styles = {"test": {"fontsize": 20}}
        config_path = tmp_path / "styles.json"
        save_telop_styles(styles, config_path)

        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        assert loaded["test"]["fontsize"] == 20


# ============================================================
# IntegratedReportGenerator テスト
# ============================================================

class TestIntegratedReportGenerator:
    """統合レポート生成"""

    def test_generate_basic_report(self):
        """generate: 基本レポート生成"""
        gen = IntegratedReportGenerator()
        report = gen.generate(
            scene_id="scene_01",
            scene_name="テストシーン",
            confirmations=[],
            telop_suggestions=[],
            telop_previews={},
            subtitle_screenshots=[],
        )
        assert "scene_01" in report
        assert "テストシーン" in report

    def test_generate_with_confirmations(self):
        """generate: 確認事項付きレポート"""
        gen = IntegratedReportGenerator()
        confirmations = [
            ConfirmationItem(
                id="c1", timestamp="00:01:30",
                original_text="テスト文字", concern="固有名詞",
                category="proper_noun", suggestion="修正案",
            )
        ]
        report = gen.generate("s1", "シーン", confirmations, [], {}, [])
        assert "AI字幕確認リスト" in report
        assert "固有名詞" in report

    def test_generate_with_telops(self):
        """generate: テロップ提案付きレポート"""
        gen = IntegratedReportGenerator()
        telops = [
            TelopSuggestion(
                id="t1", timestamp="00:00:30", duration=3.0,
                text="重要テロップ", reason="印象的な発言",
            )
        ]
        report = gen.generate("s1", "シーン", [], telops, {}, [])
        assert "テロップ提案" in report
        assert "重要テロップ" in report
