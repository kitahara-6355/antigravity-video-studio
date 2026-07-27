import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from core import ProductionContext
from plugins.report_generator_plugin import ReportGeneratorPlugin

def test_report_generator_plugin_can_execute():
    plugin = ReportGeneratorPlugin()
    context = ProductionContext()
    assert plugin.can_execute(context) is True

def test_report_generator_plugin_execute_full(tmp_path):
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(
        task_id="task_full_test",
        video_paths=["test_video.mp4"],
        mood="elegant",
        output_name="test_output",
        output_dir=tmp_path,
        thumbnail_candidates=["thumb1.jpg", "thumb2.jpg"],
        opening="opening.mp4",
        ending="ending.mp4",
        mood_settings={"primary_color": "#FF0000", "font_style": "serif"},
        quality_score=95.5,
        quality_report={
            "score": 95.5,
            "level": "S",
            "issues": ["Issue 1", "Issue 2"]
        }
    )
    
    context.set_extension("music_layer", "bgm.mp3")
    context.set_extension("music_style", "classical")
    context.set_extension("music_volume", 0.5)
    context.set_extension("music_ducking", {"enabled": True, "duck_level": 0.2})
    context.set_extension("chapters", [{"start": 0, "title": "Intro"}])
    context.set_extension("youtube_chapters", "00:00 Intro")
    context.set_extension("chapters_count", 1)
    
    res = plugin.execute(context)
    assert res == context
    
    report_file = tmp_path / "generation_report.md"
    assert report_file.exists()
    
    content = report_file.read_text(encoding="utf-8")
    assert "# 🎬 生成物レポート" in content
    assert "task_full_test" in content
    assert "elegant" in content
    assert "2枚" in content
    assert "thumb1.jpg" in content
    assert "thumb2.jpg" in content
    assert "<!-- slide -->" in content
    assert "オープニング" in content
    assert "エンディング" in content
    assert "bgm.mp3" in content
    assert "classical" in content
    assert "50%" in content
    assert "ダッキング" in content
    assert "20%" in content
    assert "00:00 Intro" in content
    assert "primary_color" in content
    assert "95.5/100" in content
    assert "S" in content
    assert "問題点" in content
    
    assert context.get_extension("report_path") == str(report_file)

def test_report_generator_plugin_thumbnail_variations(tmp_path):
    plugin = ReportGeneratorPlugin()
    
    # thumbnail が空
    context_empty = ProductionContext(output_dir=tmp_path)
    report_empty = plugin._generate_report(context_empty)
    assert "## 🖼️ サムネイル候補" not in report_empty
    
    # thumbnail が1件のみ
    context_one = ProductionContext(output_dir=tmp_path, thumbnail_candidates=["thumb1.jpg"])
    report_one = plugin._generate_report(context_one)
    assert "## 🖼️ サムネイル候補" in report_one
    assert "thumb1.jpg" in report_one
    assert "<!-- slide -->" not in report_one

def test_report_generator_plugin_op_ed_variations(tmp_path):
    plugin = ReportGeneratorPlugin()
    
    # OPのみ
    context_op = ProductionContext(output_dir=tmp_path, opening="op.mp4")
    report_op = plugin._generate_report(context_op)
    assert "### オープニング" in report_op
    assert "### エンディング" not in report_op
    
    # EDのみ
    context_ed = ProductionContext(output_dir=tmp_path, ending="ed.mp4")
    report_ed = plugin._generate_report(context_ed)
    assert "### オープニング" not in report_ed
    assert "### エンディング" in report_ed

def test_report_generator_plugin_bgm_variations(tmp_path):
    plugin = ReportGeneratorPlugin()
    
    # music_layerなし
    context_no_bgm = ProductionContext(output_dir=tmp_path)
    report_no_bgm = plugin._generate_report(context_no_bgm)
    assert "## 🎵 BGM設定" not in report_no_bgm
    
    # music_layerあり、その他情報なし (デフォルト値フォールバック)
    context_fallback = ProductionContext(output_dir=tmp_path)
    context_fallback.set_extension("music_layer", "some_bgm.mp3")
    report_fallback = plugin._generate_report(context_fallback)
    assert "## 🎵 BGM設定" in report_fallback
    assert "some_bgm.mp3" in report_fallback
    assert "30%" in report_fallback
    assert "ダッキング" not in report_fallback
    
    # music_ducking が辞書ではない、またはenabled: False
    context_ducking_disabled = ProductionContext(output_dir=tmp_path)
    context_ducking_disabled.set_extension("music_layer", "bgm.mp3")
    context_ducking_disabled.set_extension("music_ducking", {"enabled": False})
    report_ducking_disabled = plugin._generate_report(context_ducking_disabled)
    assert "ダッキング" not in report_ducking_disabled

def test_report_generator_plugin_chapter_variations(tmp_path):
    plugin = ReportGeneratorPlugin()
    
    # chaptersあり、youtube_chaptersなし
    context_chapters = ProductionContext(output_dir=tmp_path)
    context_chapters.set_extension("chapters", [{"start": 0, "title": "Intro"}])
    report_chapters = plugin._generate_report(context_chapters)
    assert "## 📑 自動チャプター" in report_chapters
    
    # chaptersなし
    context_no_chapters = ProductionContext(output_dir=tmp_path)
    report_no_chapters = plugin._generate_report(context_no_chapters)
    assert "## 📑 自動チャプター" not in report_no_chapters

def test_report_generator_plugin_quality_report_variations(tmp_path):
    plugin = ReportGeneratorPlugin()
    
    # quality_reportなし
    context_no_qr = ProductionContext(output_dir=tmp_path)
    report_no_qr = plugin._generate_report(context_no_qr)
    assert "## ✅ 品質チェック結果" not in report_no_qr
    
    # quality_reportあり、issuesなし
    context_no_issues = ProductionContext(output_dir=tmp_path, quality_report={"score": 80.0, "level": "A"})
    report_no_issues = plugin._generate_report(context_no_issues)
    assert "## ✅ 品質チェック結果" in report_no_issues
    assert "問題点" not in report_no_issues

def test_report_generator_plugin_io_error(tmp_path):
    plugin = ReportGeneratorPlugin()
    # mkdirで確実にOSErrorを発生させるために、すでにファイルが存在するパスを指定
    file_path = tmp_path / "exist_file"
    file_path.write_text("dummy")
    
    # すでにファイルが存在するパスをoutput_dirとして渡し、その下のサブディレクトリを作成させようとすることでOSErrorを期待
    invalid_dir = file_path / "subdir"
    context = ProductionContext(
        output_dir=invalid_dir,
    )
    
    res = plugin.execute(context)
    assert res == context
    assert context.get_extension("report_path") is None

def test_report_generator_plugin_thumbnail_none(tmp_path):
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(
        output_dir=tmp_path,
        thumbnail_candidates=None  # 防衛的プログラミングにより例外を投げない
    )
    report = plugin._generate_report(context)
    assert "## 🖼️ サムネイル候補" not in report
    assert "0枚" in report

def test_report_generator_plugin_youtube_chapters_none(tmp_path):
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(
        output_dir=tmp_path,
    )
    context.set_extension("chapters", [{"start": 0, "title": "Intro"}])
    context.set_extension("youtube_chapters", None)  # 防衛的プログラミングにより例外を投げない
    report = plugin._generate_report(context)
    assert "## 📑 自動チャプター" in report

def test_report_generator_plugin_music_ducking_invalid_type(tmp_path):
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(
        output_dir=tmp_path,
    )
    context.set_extension("music_layer", "bgm.mp3")
    context.set_extension("music_ducking", "disabled")  # 防衛的プログラミングにより例外を投げない
    report = plugin._generate_report(context)
    assert "## 🎵 BGM設定" in report
    assert "ダッキング" not in report

def test_report_generator_plugin_quality_report_invalid_type(tmp_path):
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(
        output_dir=tmp_path,
        quality_report="failed"  # 防衛的プログラミングにより例外を投げない
    )
    report = plugin._generate_report(context)
    assert "## ✅ 品質チェック結果" not in report

def test_report_generator_plugin_quality_report_score_none(tmp_path):
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(
        output_dir=tmp_path,
        quality_report={"score": None, "level": "S"}  # 防衛的プログラミングにより例外を投げない
    )
    report = plugin._generate_report(context)
    assert "## ✅ 品質チェック結果" in report
    assert "- **スコア**: 0.0/100" in report

def test_report_generator_plugin_unexpected_exception_safety(tmp_path):
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(
        output_dir=tmp_path,
    )
    
    # execute メソッドが予期せぬ例外に対しても安全に動作することをアサート
    with patch.object(plugin, "_generate_report", side_effect=RuntimeError("Unexpected crash")):
        res = plugin.execute(context)
        assert res == context
        assert context.get_extension("report_path") is None


def test_report_generator_plugin_mood_settings_variations(tmp_path):
    plugin = ReportGeneratorPlugin()
    
    # mood_settings が None
    context_none = ProductionContext(output_dir=tmp_path, mood_settings=None)
    report_none = plugin._generate_report(context_none)
    assert "## 🎨 適用デザイントークン" not in report_none

    # mood_settings が空辞書
    context_empty = ProductionContext(output_dir=tmp_path, mood_settings={})
    report_empty = plugin._generate_report(context_empty)
    assert "## 🎨 適用デザイントークン" not in report_empty

    # mood_settings が有効なデータ
    context_valid = ProductionContext(output_dir=tmp_path, mood_settings={"theme": "dark"})
    report_valid = plugin._generate_report(context_valid)
    assert "## 🎨 適用デザイントークン" in report_valid
    assert '"theme": "dark"' in report_valid



def test_report_generator_plugin_ducking_level_fallback(tmp_path):
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(output_dir=tmp_path)
    context.set_extension("music_layer", "bgm.mp3")
    context.set_extension("music_ducking", {"enabled": True})  # duck_levelなし
    report = plugin._generate_report(context)
    assert "ダッキング" in report
    assert "15%" in report  # デフォルト値 0.15 * 100


def test_report_generator_plugin_quality_report_fallback(tmp_path):
    plugin = ReportGeneratorPlugin()
    
    # 空辞書の場合、品質チェック結果は表示されないことを検証
    context_empty = ProductionContext(output_dir=tmp_path, quality_report={})
    report_empty = plugin._generate_report(context_empty)
    assert "## ✅ 品質チェック結果" not in report_empty

    # 部分的にキーが欠損したデータ（しかし空ではない）の場合、デフォルト値でフォールバックされることを検証
    context_partial = ProductionContext(output_dir=tmp_path, quality_report={"score": 85.0})
    report_partial = plugin._generate_report(context_partial)
    assert "## ✅ 品質チェック結果" in report_partial
    assert "85.0/100" in report_partial
    assert "**レベル**: -" in report_partial


def test_report_generator_plugin_empty_context_fields(tmp_path):
    plugin = ReportGeneratorPlugin()
    context = ProductionContext(
        output_dir=tmp_path,
        task_id="",
        mood=""
    )
    report = plugin._generate_report(context)
    assert "タスクID: ``" in report
    assert "ムード: ****" in report


def test_report_generator_plugin_path_encoding(tmp_path):
    from urllib.parse import quote
    plugin = ReportGeneratorPlugin()
    
    # 日本語、スペース、Windowsのバックスラッシュを含むパス
    complex_thumb = "C:\\path\\to\\サムネイル 画像.jpg"
    complex_op = "C:\\path\\to\\オープニング 動画.mp4"
    complex_ed = "C:\\path\\to\\エンディング 動画.mp4"
    
    context = ProductionContext(
        task_id="task_path_encoding",
        output_dir=tmp_path,
        thumbnail_candidates=[complex_thumb],
        opening=complex_op,
        ending=complex_ed
    )
    
    res = plugin.execute(context)
    assert res == context
    
    report_file = tmp_path / "generation_report.md"
    assert report_file.exists()
    
    content = report_file.read_text(encoding="utf-8")
    
    # 期待されるエンコード済みの file:/// 形式の URL
    expected_thumb_url = "file:///C:/path/to/%E3%82%B5%E3%83%A0%E3%83%8D%E3%82%A4%E3%83%AB%20%E7%94%BB%E5%83%8F.jpg"
    expected_op_url = "file:///C:/path/to/%E3%82%AA%E3%83%BC%E3%83%97%E3%83%8B%E3%83%B3%E3%82%B0%20%E5%8B%95%E7%94%BB.mp4"
    expected_ed_url = "file:///C:/path/to/%E3%82%A8%E3%83%B3%E3%83%87%E3%82%A3%E3%83%B3%E3%82%B0%20%E5%8B%95%E7%94%BB.mp4"
    
    assert expected_thumb_url in content
    assert expected_op_url in content
    assert expected_ed_url in content


def test_report_generator_plugin_already_url(tmp_path):
    plugin = ReportGeneratorPlugin()
    
    # すでに file:/// または http:// の形式になっているURL
    already_file_url = "file:///C:/already/encoded%20path.jpg"
    already_http_url = "http://example.com/images/thumb.png"
    
    context = ProductionContext(
        task_id="task_already_url",
        output_dir=tmp_path,
        thumbnail_candidates=[already_file_url],
        opening=already_http_url
    )
    
    res = plugin.execute(context)
    assert res == context
    
    report_file = tmp_path / "generation_report.md"
    assert report_file.exists()
    
    content = report_file.read_text(encoding="utf-8")
    
    # そのまま維持されていることを検証
    assert already_file_url in content
    assert already_http_url in content
