import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 動的パス解決: テストファイルの位置からプロジェクトルート（backend）を追加
test_dir = Path(__file__).resolve().parent
backend_dir = test_dir.parent
sys.path.insert(0, str(backend_dir.parent))
sys.path.insert(0, str(backend_dir))

from backend.core import ProductionContext, ProductionPhase
from backend.plugins.report_generator_plugin import ReportGeneratorPlugin


def test_report_generator_plugin_execute_success(tmp_path):
    """すべてのデータが正しく設定されている場合、正常にレポートが生成され、内容が妥当であること"""
    context = ProductionContext(
        task_id="T-test-001",
        mood="elegant",
        output_dir=tmp_path
    )
    context.thumbnail_candidates = ["thumbs/thumb1.png", "thumbs/thumb2.png"]
    context.opening = "opening.mp4"
    context.ending = "ending.mp4"
    # **「測った」は値ではなく旗で表す**（R1.5-C4・10周目 N-3）
    context.quality_scored = True
    context.quality_score = 92.5
    context.quality_report = {
        "score": 92.5,
        "level": "A",
        "issues": [{"desc": "minor issue"}]
    }
    
    # 拡張データの設定
    context.set_extension("music_layer", "assets/music/piano.mp3")
    context.set_extension("music_volume", 0.4)
    context.set_extension("music_style", "classical")
    context.set_extension("music_ducking", {"enabled": True, "duck_level": 0.2})
    context.set_extension("chapters", [{"time": 0, "title": "Start"}])
    context.set_extension("youtube_chapters", "00:00 Intro")
    
    plugin = ReportGeneratorPlugin()
    updated_context = plugin.execute(context)
    
    report_path_str = updated_context.get_extension("report_path")
    assert report_path_str is not None
    
    report_path = Path(report_path_str)
    assert report_path.exists()
    
    content = report_path.read_text(encoding="utf-8")
    
    # レポート内容の検証
    assert "# 🎬 生成物レポート" in content
    assert "タスクID: `T-test-001`" in content
    assert "ムード: **elegant**" in content
    assert "サムネイル候補 | 2枚" in content
    assert "品質スコア | 92.5/100" in content
    assert "carousel" in content
    assert "thumbs/thumb1.png" in content
    assert "opening.mp4" in content
    assert "ending.mp4" in content
    assert "BGM設定" in content
    assert "piano.mp3" in content
    assert "音量 | 40%" in content
    assert "ダッキング | 有効（20%）" in content
    assert "00:00 Intro" in content
    assert "品質チェック結果" in content
    assert "問題点**: 1件" in content


def test_report_generator_plugin_robustness_with_null_and_invalid_data(tmp_path):
    """データがNoneや不正な型である場合でもクラッシュせず、正常にフォールバックされること"""
    context = ProductionContext(
        task_id="T-test-robustness",
        mood="dynamic",
        output_dir=tmp_path
    )
    
    # 不正な型を注入
    context.thumbnail_candidates = None  # 本来は list
    context.quality_score = "invalid_score"  # 本来は float
    context.quality_report = "not_a_dict"  # 本来は dict
    
    plugin = ReportGeneratorPlugin()
    updated_context = plugin.execute(context)
    
    report_path_str = updated_context.get_extension("report_path")
    assert report_path_str is not None
    
    report_path = Path(report_path_str)
    assert report_path.exists()
    
    content = report_path.read_text(encoding="utf-8")
    assert "サムネイル候補 | 0枚" in content
    assert "品質スコア | **未計測**" in content
    assert "品質チェック結果" not in content  # dict 以外はスキップされること
    assert "carousel" not in content  # リスト以外はスキップされること


def test_report_generator_plugin_quality_report_malformed_fields(tmp_path):
    """quality_report の個々のフィールド値が None や不正な型である場合のフォールバック検証"""
    context = ProductionContext(
        task_id="T-test-malformed-fields",
        output_dir=tmp_path
    )
    # フィールド値の型異常
    context.quality_report = {
        "score": None,          # 本来は float
        "level": 1234,          # 本来は str
        "issues": "not_a_list"  # 本来は list
    }
    
    plugin = ReportGeneratorPlugin()
    updated_context = plugin.execute(context)
    
    report_path_str = updated_context.get_extension("report_path")
    assert report_path_str is not None
    
    content = Path(report_path_str).read_text(encoding="utf-8")
    assert "スコア**: 0.0/100" in content
    assert "レベル**: 1234" in content
    assert "問題点" not in content  # リスト以外はスキップされること


def test_report_generator_plugin_write_failure(tmp_path):
    """書き込み時に OSError (I/Oエラー) が発生した場合、ログに記録され、例外が上流を破壊しないこと"""
    context = ProductionContext(
        task_id="T-test-io-error",
        output_dir=tmp_path
    )
    
    plugin = ReportGeneratorPlugin()
    
    # ファイル書き込みを OSError で失敗させる
    with patch("pathlib.Path.write_text", side_effect=OSError("Write permission denied")):
        updated_context = plugin.execute(context)
        assert updated_context.get_extension("report_path") is None


def test_report_generator_plugin_can_execute():
    """can_execute が常に True を返すこと"""
    plugin = ReportGeneratorPlugin()
    assert plugin.can_execute(None) is True
    assert plugin.can_execute(ProductionContext()) is True


def test_未計測の品質スコアを0点として出さない(tmp_path):
    """**測っていないことを、0点という測定結果に見せない**（R1.5-C4）。

    `backend/core/context.py` の経路には品質ゲートが繋がっておらず、
    dataclass の既定値 `0.0` がそのまま「0.0/100」と表示されていた。
    **0点で落ちたのか、そもそも測っていないのかが区別できない。**
    """
    context = ProductionContext(task_id="T-c4-001", mood="elegant",
                                output_dir=tmp_path)

    ReportGeneratorPlugin().execute(context)

    本文 = (tmp_path / "generation_report.md").read_text(encoding="utf-8")

    assert "未計測" in 本文, 本文[:400]
    assert "0.0/100" not in 本文, 本文[:400]
