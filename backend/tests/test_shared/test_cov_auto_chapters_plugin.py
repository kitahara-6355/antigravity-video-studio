import pytest
import sys
import importlib
from unittest.mock import MagicMock, patch
from plugins.auto_chapters_plugin import AutoChaptersPlugin
from core.context import ProductionContext

def test_auto_chapters_plugin_can_execute():
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    
    # segmentsが無い場合
    ctx.segments = []
    assert not plugin.can_execute(ctx)
    
    # segmentsがある場合
    ctx.segments = [{"start": 0, "end": 10, "text": "test"}]
    assert plugin.can_execute(ctx)

def test_auto_chapters_plugin_no_segments():
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = []
    
    # 実行してもスキップされる
    res = plugin.execute(ctx)
    assert res == ctx
    # chaptersなどの拡張が存在しないことを確認
    assert ctx.get_extension("chapters") is None

def test_auto_chapters_plugin_normal_execution():
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    # 30秒以上の間隔を持つセグメントをいくつか定義してチャプター候補が生成されるようにする
    ctx.segments = [
        {"start": 0, "end": 5, "text": "オープニングですよ"},
        {"start": 35, "end": 40, "text": "ポイントはここです"},
        {"start": 70, "end": 75, "text": "結論を言います"}
    ]
    
    res = plugin.execute(ctx)
    
    # コンテキストにchaptersがセットされているか
    chapters = res.get_extension("chapters")
    assert chapters is not None
    assert len(chapters) > 0
    
    # youtube_chapters説明文がフォーマットされているか
    youtube_chapters = res.get_extension("youtube_chapters")
    assert youtube_chapters is not None
    assert "0:00" in youtube_chapters
    
    # chapters_countが一致するか
    assert res.get_extension("chapters_count") == len(chapters)

def test_auto_chapters_plugin_format_youtube_numeric():
    plugin = AutoChaptersPlugin()
    chapters = [
        {"index": 0, "time": 0, "title": "Intro"},
        {"index": 1, "time": 95.5, "title": "Deep Dive"},
        {"index": 2, "time": 185, "title": "Conclusion"}
    ]
    formatted = plugin._format_for_youtube(chapters)
    assert "0:00 Intro" in formatted
    assert "1:35 Deep Dive" in formatted
    assert "3:05 Conclusion" in formatted

def test_auto_chapters_plugin_exception_handling(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    # scan_plugin.execute で例外を投げさせる
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    def mock_execute(*args, **kwargs):
        raise ValueError("Simulated scan failure")
    
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    # 例外時、空のチャプターが設定されること
    assert res.get_extension("chapters") == []
    assert res.get_extension("chapters_count") == 0
    assert res.get_extension("youtube_chapters") == ""

def test_auto_chapters_plugin_import_error():
    """model_registry を import できないときの逃げ先。

    **直書きの既定値に逃げない**（R1.5-C6）。2026-08-28 まで
    `gemini-2.5-flash` を直書きしており、2026-10-16 に提供終了する
    モデルが本番の実行経路に居座っていた。正典から引き直す。
    """
    from model_policy import resolve

    # model_registry のインポートを失敗させる
    with patch.dict(sys.modules, {"model_registry": None}):
        import plugins.auto_chapters_plugin
        importlib.reload(plugins.auto_chapters_plugin)
        
        get_model = plugins.auto_chapters_plugin.get_model
        assert get_model("lightweight_scan") == resolve("lightweight_scan").model
        assert not get_model("lightweight_scan").startswith("gemini-2.5")
    
    # テスト後にモジュールを正常に戻しておく
    import plugins.auto_chapters_plugin
    importlib.reload(plugins.auto_chapters_plugin)

def test_auto_chapters_plugin_no_scan_result(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    
    # executeした後に context.scan_result を削除するモック
    original_execute = LightweightScanPlugin.execute
    def mock_execute(self, context):
        context = original_execute(self, context)
        if hasattr(context, "scan_result"):
            delattr(context, "scan_result")
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    # chaptersなどの拡張が空の状態で存在することを確認
    assert res.get_extension("chapters") == []
    assert res.get_extension("chapters_count") == 0
    assert res.get_extension("youtube_chapters") == ""


def test_auto_chapters_plugin_unexpected_exception_handling(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    def mock_execute(*args, **kwargs):
        raise RuntimeError("Unexpected simulated scan failure")
    
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    # 予期しない例外時も、空のチャプターが設定されること
    assert res.get_extension("chapters") == []
    assert res.get_extension("chapters_count") == 0
    assert res.get_extension("youtube_chapters") == ""

def test_auto_chapters_plugin_starts_with_zero(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    # scan_result.chapter_candidates が 0秒開始ではないリストを返すようにモックする
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=3,
            total_duration_seconds=150,
            highlight_candidates=[],
            # 0秒開始ではない3つの候補を定義
            chapter_candidates=[
                {"timestamp": 45, "time_str": "0:45", "title": "第1パート"},
                {"timestamp": 90, "time_str": "1:30", "title": "第2パート"},
                {"timestamp": 140, "time_str": "2:20", "title": "第3パート"}
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    # 4つのチャプターになっている（Intro + 元の3つ）
    assert len(chapters) == 4
    
    # 最初のチャプターが 0:00 (Intro) になっていること
    assert chapters[0]["start_time"] == 0
    assert chapters[0]["time"] == "0:00"
    assert chapters[0]["title"] == "Intro"
    assert chapters[0]["index"] == 0
    
    # 2番目のチャプター以降もスライドしていること
    assert chapters[1]["start_time"] == 45
    assert chapters[1]["time"] == "0:45"
    assert chapters[1]["title"] == "第1パート"
    assert chapters[1]["index"] == 1
    
    # YouTube用の説明文も 0:00 から始まっていること
    youtube_chapters = res.get_extension("youtube_chapters")
    assert youtube_chapters.startswith("0:00 Intro")

def test_auto_chapters_plugin_minimum_three_chapters():
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    # セグメントが1つしかない（あるいはチャプター数が3未満になる）場合
    ctx.segments = [
        {"start": 0, "end": 5, "text": "オープニングのみ"}
    ]
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    # 3つ未満の場合はYouTube仕様に適合しないため、空リストになること
    assert chapters == []
    assert res.get_extension("chapters_count") == 0
    assert res.get_extension("youtube_chapters") == ""

def test_auto_chapters_plugin_format_youtube_hours():
    plugin = AutoChaptersPlugin()
    chapters = [
        {"index": 0, "time": 0, "title": "Intro"},
        {"index": 1, "time": 3665.5, "title": "1 Hour Later"},
        {"index": 2, "time": 7322, "title": "2 Hours Later"}
    ]
    formatted = plugin._format_for_youtube(chapters)
    # H:MM:SS形式になっていることを検証
    assert "0:00 Intro" in formatted
    assert "1:01:05 1 Hour Later" in formatted
    assert "2:02:02 2 Hours Later" in formatted


def test_auto_chapters_plugin_type_error_handling(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    def mock_execute(*args, **kwargs):
        raise TypeError("Simulated type error")
    
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    # TypeError発生時、安全に空のチャプターが設定されること
    assert res.get_extension("chapters") == []
    assert res.get_extension("chapters_count") == 0
    assert res.get_extension("youtube_chapters") == ""


def test_auto_chapters_plugin_index_error_handling(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    def mock_execute(*args, **kwargs):
        raise IndexError("Simulated index error")
    
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    # IndexError発生時、安全に空のチャプターが設定されること
    assert res.get_extension("chapters") == []
    assert res.get_extension("chapters_count") == 0
    assert res.get_extension("youtube_chapters") == ""


def test_auto_chapters_plugin_integration_hours(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=3,
            total_duration_seconds=7500,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": 0, "time_str": "0:00", "title": "Intro"},
                {"timestamp": 3665, "time_str": "61:05", "title": "1 Hour Later"},
                {"timestamp": 7322, "time_str": "122:02", "title": "2 Hours Later"}
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    assert len(chapters) == 3
    
    # 1時間超のチャプターが正しく H:MM:SS にフォーマットされているかを検証
    assert chapters[0]["time"] == "0:00"
    assert chapters[1]["time"] == "1:01:05"
    assert chapters[2]["time"] == "2:02:02"
    
    youtube_chapters = res.get_extension("youtube_chapters")
    assert "0:00 Intro" in youtube_chapters
    assert "1:01:05 1 Hour Later" in youtube_chapters
    assert "2:02:02 2 Hours Later" in youtube_chapters

def test_auto_chapters_plugin_under_ten_seconds_filter(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=4,
            total_duration_seconds=150,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": 0, "time_str": "0:00", "title": "Intro"},
                {"timestamp": 5, "time_str": "0:05", "title": "Short Interval"}, # 10秒未満なので除外されるべき
                {"timestamp": 20, "time_str": "0:20", "title": "Long Interval 1"}, # 20 - 0 = 20 >= 10 なので採用
                {"timestamp": 25, "time_str": "0:25", "title": "Short Interval 2"}, # 25 - 20 = 5 < 10 なので除外されるべき
                {"timestamp": 40, "time_str": "0:40", "title": "Long Interval 2"} # 40 - 20 = 20 >= 10 なので採用
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    # 採用されるのは Intro (0), Long Interval 1 (20), Long Interval 2 (40) の 3つ
    assert len(chapters) == 3
    assert chapters[0]["title"] == "Intro"
    assert chapters[0]["start_time"] == 0
    assert chapters[0]["index"] == 0
    
    assert chapters[1]["title"] == "Long Interval 1"
    assert chapters[1]["start_time"] == 20
    assert chapters[1]["index"] == 1
    
    assert chapters[2]["title"] == "Long Interval 2"
    assert chapters[2]["start_time"] == 40
    assert chapters[2]["index"] == 2


def test_auto_chapters_plugin_max_chapters_hard_limit(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    # 50個以上のチャプター候補を作成
    candidates = []
    # 0秒開始ではないので Intro が挿入されて 51個になるようにする
    for i in range(55):
        candidates.append({
            "timestamp": 20 + i * 20, # 20秒間隔
            "time_str": f"time_{i}",
            "title": f"Part {i+1}"
        })
        
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=100,
            total_duration_seconds=2000,
            highlight_candidates=[],
            chapter_candidates=candidates,
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    # 最大50個に制限されていること
    assert len(chapters) == plugin.MAX_CHAPTERS
    assert chapters[0]["title"] == "Intro"
    assert chapters[0]["start_time"] == 0
    assert chapters[0]["index"] == 0
    assert chapters[plugin.MAX_CHAPTERS - 1]["index"] == plugin.MAX_CHAPTERS - 1


def test_auto_chapters_plugin_invalid_context():
    plugin = AutoChaptersPlugin()
    
    # context が None の場合
    res_none = plugin.execute(None)
    assert res_none is None

    # context が set_extension メソッドを持たない場合
    class BadContext:
        pass
    bad_ctx = BadContext()
    res_bad = plugin.execute(bad_ctx)
    assert res_bad == bad_ctx


def test_auto_chapters_plugin_invalid_segments():
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    
    # segments がリストではない場合
    ctx.segments = "not a list"
    res = plugin.execute(ctx)
    assert res == ctx
    assert ctx.get_extension("chapters") is None


def test_auto_chapters_plugin_invalid_seconds():
    plugin = AutoChaptersPlugin()
    import math

    # None や非数値、不正な値の場合
    assert plugin._seconds_to_time_str(None) == "0:00"
    assert plugin._seconds_to_time_str("invalid") == "0:00"
    assert plugin._seconds_to_time_str(float("nan")) == "0:00"
    assert plugin._seconds_to_time_str(float("inf")) == "0:00"
    assert plugin._seconds_to_time_str(-10) == "0:00"


def test_auto_chapters_plugin_invalid_format_youtube_input():
    plugin = AutoChaptersPlugin()
    
    # chapters がリストではない場合
    assert plugin._format_for_youtube("not a list") == ""
    
    # リスト内に辞書以外の不正なデータがある場合
    chapters = [
        {"time": 0, "title": "Intro"},
        "invalid_item",
        {"time": 95, "title": 12345} # タイトルが文字列でない
    ]
    formatted = plugin._format_for_youtube(chapters)
    assert "0:00 Intro" in formatted
    assert "1:35 12345" in formatted
    assert "invalid_item" not in formatted


def test_auto_chapters_plugin_invalid_candidates(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=3,
            total_duration_seconds=150,
            highlight_candidates=[],
            chapter_candidates=[
                "not a dict", # 辞書でない
                {"timestamp": float("nan"), "title": "NaN Time"}, # nan timestamp
                {"timestamp": float("inf"), "title": "Inf Time"}, # inf timestamp
                {"timestamp": -50, "title": "Negative Time"}, # 負の timestamp
                {"timestamp": 45, "title": ["Not", "String"]}, # タイトルが文字列でない
                {"timestamp": 90, "title": "Valid Section"}
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    
    # 不正な候補はスキップまたはデフォルト値 (0.0) にフォールバックされる
    # リスト内の "not a dict" はスキップされる
    # nan, inf, -50 の timestamp は 0.0 にフォールバックされる
    # タイトルがリストのものは文字列化される
    # 最終的に以下の3つが採用される：
    # 1. NaN Time (0.0)
    # 2. ['Not', 'String'] (45.0)
    # 3. Valid Section (90.0)
    assert len(chapters) == 3
    assert chapters[0]["title"] == "NaN Time"
    assert chapters[0]["start_time"] == 0.0
    assert chapters[1]["title"] == "['Not', 'String']"
    assert chapters[1]["start_time"] == 45.0
    assert chapters[2]["title"] == "Valid Section"
    assert chapters[2]["start_time"] == 90.0

    # 有効なチャプターが足りない（3個未満）場合に空リストになることも検証
    def mock_execute_short(self, context):
        context.scan_result = ScanResult(
            total_segments=1,
            total_duration_seconds=50,
            highlight_candidates=[],
            # 有効なチャプター候補が 1つしかない場合
            chapter_candidates=[
                {"timestamp": 20, "title": "Single Chapter"}
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context

    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute_short)
    
    res_short = plugin.execute(ctx)
    chapters_short = res_short.get_extension("chapters")
    # Introが挿入されて 0秒 と 20秒 の 2つになるが、3つ未満のため空になること
    assert chapters_short == []


def test_auto_chapters_plugin_zero_division_error_handling(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    def mock_execute(*args, **kwargs):
        raise ZeroDivisionError("Simulated zero division error")
    
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    # ZeroDivisionError発生時も、安全に空のチャプターが設定されること
    assert res.get_extension("chapters") == []
    assert res.get_extension("chapters_count") == 0
    assert res.get_extension("youtube_chapters") == ""


def test_auto_chapters_plugin_logging_details_on_exceptions(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    
    # AttributeErrorを投げさせて、ログメッセージと型名を確認
    def mock_execute_attr(*args, **kwargs):
        raise AttributeError("Simulated attribute error")
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute_attr)
    
    # ログキャッチャーを使用してエラーログを検証
    with patch('plugins.auto_chapters_plugin.logger.error') as mock_log_error:
        res = plugin.execute(ctx)
        assert res.get_extension("chapters") == []
        mock_log_error.assert_called_once()
        args, kwargs = mock_log_error.call_args
        assert "AttributeError" in args[0]
        assert "Simulated attribute error" in args[0]


def test_auto_chapters_plugin_logging_details_on_import_error():
    # 依存モジュールのインポートエラーをシミュレート
    with patch.dict(sys.modules, {"plugins.lightweight_scan_plugin": None}):
        plugin = AutoChaptersPlugin()
        ctx = ProductionContext()
        ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
        
        with patch('plugins.auto_chapters_plugin.logger.critical') as mock_log_critical:
            res = plugin.execute(ctx)
            assert res.get_extension("chapters") == []
            mock_log_critical.assert_called_once()
            args, kwargs = mock_log_critical.call_args
            assert "Required module for chapter generation is missing" in args[0]


def test_auto_chapters_plugin_general_exception_handling(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    
    # 以前の捕捉対象外だった AssertionError や NotImplementedError を投げる
    def mock_execute(*args, **kwargs):
        raise NotImplementedError("Simulated not implemented error")
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    with patch('plugins.auto_chapters_plugin.logger.error') as mock_log_error:
        res = plugin.execute(ctx)
        assert res.get_extension("chapters") == []
        assert res.get_extension("chapters_count") == 0
        assert res.get_extension("youtube_chapters") == ""
        mock_log_error.assert_called_once()
        args, kwargs = mock_log_error.call_args
        assert "NotImplementedError" in args[0]
        assert "Simulated not implemented error" in args[0]


def test_auto_chapters_plugin_unsorted_candidates(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    # 時間順になっていない候補リストを準備
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=3,
            total_duration_seconds=300,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": 120, "time_str": "2:00", "title": "Part C"},
                {"timestamp": 0, "time_str": "0:00", "title": "Intro"},
                {"timestamp": 60, "time_str": "1:00", "title": "Part B"}
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    assert len(chapters) == 3
    
    # 昇順にソートされていることを検証
    assert chapters[0]["start_time"] == 0
    assert chapters[0]["title"] == "Intro"
    assert chapters[1]["start_time"] == 60
    assert chapters[1]["title"] == "Part B"
    assert chapters[2]["start_time"] == 120
    assert chapters[2]["title"] == "Part C"


def test_auto_chapters_plugin_title_sanitization(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    # 改行を含む、または空文字列のタイトル候補を準備
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=3,
            total_duration_seconds=300,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": 0, "time_str": "0:00", "title": "Intro\nNext Line"},
                {"timestamp": 60, "time_str": "1:00", "title": "  "},
                {"timestamp": 120, "time_str": "2:00", "title": "Part C\r"}
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    assert len(chapters) == 3
    
    # 改行や空白文字がサニタイズされていることを検証
    assert chapters[0]["title"] == "Intro Next Line"
    assert chapters[1]["title"] == "Section 2"
    assert chapters[2]["title"] == "Part C"


def test_auto_chapters_plugin_format_youtube_fallback():
    plugin = AutoChaptersPlugin()
    
    # timeキーがなく、start_timeのみ存在するチャプター辞書
    chapters = [
        {"index": 0, "start_time": 0, "title": "Intro"},
        {"index": 1, "start_time": 95, "title": "Deep Dive"},
        {"index": 2, "start_time": 185, "title": "Conclusion"}
    ]
    formatted = plugin._format_for_youtube(chapters)
    # timeが自動的に計算されてフォーマットされていることを検証
    assert "0:00 Intro" in formatted
    assert "1:35 Deep Dive" in formatted
    assert "3:05 Conclusion" in formatted


def test_auto_chapters_plugin_format_youtube_sanitization():
    plugin = AutoChaptersPlugin()
    
    # 改行や空白文字を含むタイトルを持つチャプター辞書
    chapters = [
        {"index": 0, "start_time": 0, "title": "Intro\nNext Line"},
        {"index": 1, "start_time": 95, "title": "Part B\r"},
        {"index": 2, "start_time": 185, "title": "  Conclusion  "}
    ]
    formatted = plugin._format_for_youtube(chapters)
    # フォーマット関数内でも適切にサニタイズされていることを検証
    assert "0:00 Intro Next Line" in formatted
    assert "1:35 Part B" in formatted
    assert "3:05 Conclusion" in formatted


def test_auto_chapters_plugin_parse_phase_exceptions(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    
    # getattrで例外を投げるような不適切なscan_resultを定義
    class BadScanResult:
        @property
        def chapter_candidates(self):
            raise ValueError("Simulated parse error during property access")
            
    def mock_execute(self, context):
        context.scan_result = BadScanResult()
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    # パース中に例外が発生しても安全に空チャプターが設定されること
    assert res.get_extension("chapters") == []
    assert res.get_extension("chapters_count") == 0
    assert res.get_extension("youtube_chapters") == ""

def test_auto_chapters_plugin_bool_timestamp(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=3,
            total_duration_seconds=150,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": True, "title": "True Time"},     # bool型
                {"timestamp": False, "title": "False Time"},   # bool型
                {"timestamp": 90, "title": "Valid Section"}
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    # bool型のtimestampは0.0にフォールバックされます。
    # 最終的にTypeErrorが発生せずに処理が完了することを確認します。
    assert isinstance(chapters, list)

def test_auto_chapters_plugin_seconds_to_time_str_bool():
    plugin = AutoChaptersPlugin()
    # bool値を渡した場合、TypeErrorにならず "0:00" を返すことを検証
    assert plugin._seconds_to_time_str(True) == "0:00"
    assert plugin._seconds_to_time_str(False) == "0:00"

def test_auto_chapters_plugin_safe_model_fallback():
    from plugins.auto_chapters_plugin import _get_model_safe
    
    # 正常な場合
    with patch("plugins.auto_chapters_plugin.get_model", return_value="gemini-custom"):
        assert _get_model_safe("lightweight_scan") == "gemini-custom"
        
    # get_modelが例外を投げた場合にデフォルトにフォールバックすること
    def mock_get_model_error(task):
        raise KeyError("Model not configured")
        
    with patch("plugins.auto_chapters_plugin.get_model", mock_get_model_error):
        with patch("logging.Logger.warning") as mock_warn:
            assert _get_model_safe("lightweight_scan", "fallback-model") == "fallback-model"
            mock_warn.assert_called_once()
            assert "Failed to get model" in mock_warn.call_args[0][0]

def test_auto_chapters_plugin_max_chapters_delayed_limit(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 5, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    # 30個のチャプター候補。
    # 奇数番目の候補は timestamp が 10秒 ずつ増加。
    # 偶数番目の候補は直前の奇数番目の候補から 1秒 しか経過していない（＝10秒未満なのでフィルタで除外される）。
    # 早期スライスだと、最初の15個（奇数7個、偶数8個）だけが処理対象になり、
    # 偶数8個が除外され、最終的に奇数7個（＋0秒のIntro）しか残らない。
    # 修正後（遅延スライス）なら、30個すべてを処理した後にスライスするため、
    # 奇数15個（＋0秒のIntro）がしっかりと採用され、合計15個のチャプターが確保されるはず。
    candidates = []
    for i in range(30):
        if i % 2 == 0:
            # 奇数番目の採用候補（0, 2, 4,...）: 20秒間隔
            candidates.append({
                "timestamp": 20 + i * 10,
                "title": f"Adopted {i}"
            })
        else:
            # 偶数番目のスキップ候補（1, 3, 5,...）: 直前から1秒
            candidates.append({
                "timestamp": 20 + (i - 1) * 10 + 1,
                "title": f"Skipped {i}"
            })
            
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=100,
            total_duration_seconds=2000,
            highlight_candidates=[],
            chapter_candidates=candidates,
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    
    assert chapters is not None
    # 遅延制限のおかげで、10秒以上の間隔を持つ候補がしっかりと MAX_CHAPTERS 件採用される
    assert len(chapters) == plugin.MAX_CHAPTERS
    
    # 最初のチャプターが Intro (0s)
    assert chapters[0]["title"] == "Intro"
    assert chapters[0]["start_time"] == 0
    
    # 2番目のチャプター以降は Adopted 0, Adopted 2... のようになる
    assert chapters[1]["title"] == "Adopted 0"
    assert chapters[1]["start_time"] == 20


def test_auto_chapters_plugin_short_title_handling(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 10, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=3,
            total_duration_seconds=150,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": 0, "title": "Intro"},
                {"timestamp": 45, "title": "A"},        # 3文字未満なので Section 2 になるはず
                {"timestamp": 90, "title": "OK"},       # 3文字未満なので Section 3 になるはず
                {"timestamp": 135, "title": "Valid Title"}
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    assert len(chapters) == 4
    assert chapters[0]["title"] == "Intro"
    assert chapters[1]["title"] == "Section 2"
    assert chapters[2]["title"] == "Section 3"
    assert chapters[3]["title"] == "Valid Title"


def test_auto_chapters_plugin_exceed_max_duration(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    # segmentsの最後のendを80秒に設定
    ctx.segments = [
        {"start": 0, "end": 10, "text": "test"},
        {"start": 70, "end": 80, "text": "test2"}
    ]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=3,
            total_duration_seconds=150,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": 0, "title": "Intro"},
                {"timestamp": 45, "title": "Within Duration"},
                {"timestamp": 95, "title": "Exceeds Duration"} # 80秒を超えているのでスキップされるはず
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    # Exceeds Duration が除外されて、IntroとWithin Durationの2つになる
    # しかしYouTube要件で3つ未満の場合は空になるため、結果は空リストになる
    assert chapters == []


def test_auto_chapters_plugin_milliseconds_truncation(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 10, "text": "test"}]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=3,
            total_duration_seconds=150,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": 0.0, "title": "Intro"},
                {"timestamp": 45.9, "title": "Section Two"}, # 45秒に切り捨てられる
                {"timestamp": 90.2, "title": "Section Three"} # 90秒に切り捨てられる
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    assert len(chapters) == 3
    assert chapters[1]["start_time"] == 45.0
    assert chapters[1]["time"] == "0:45"
    assert chapters[2]["start_time"] == 90.0
    assert chapters[2]["time"] == "1:30"


def test_auto_chapters_plugin_get_model_safe_unexpected_exception():
    from plugins.auto_chapters_plugin import _get_model_safe
    
    # get_modelが一般的なExceptionを投げた場合にデフォルトにフォールバックすること
    def mock_get_model_error(task):
        raise RuntimeError("Unexpected registry error")
        
    with patch("plugins.auto_chapters_plugin.get_model", mock_get_model_error):
        with patch("logging.Logger.warning") as mock_warn:
            assert _get_model_safe("lightweight_scan", "fallback-model") == "fallback-model"
            mock_warn.assert_called_once()
            assert "unexpected error" in mock_warn.call_args[0][0]


def test_auto_chapters_plugin_initialization_exception(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 10, "text": "test"}]

    # LightweightScanPluginのインスタンス化で ValueError を発生させる
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    def mock_init(self):
        raise ValueError("Simulated initialization failure")

    monkeypatch.setattr(LightweightScanPlugin, "__init__", mock_init)

    with patch('plugins.auto_chapters_plugin.logger.error') as mock_log_error:
        res = plugin.execute(ctx)
        assert res.get_extension("chapters") == []
        assert res.get_extension("chapters_count") == 0
        assert res.get_extension("youtube_chapters") == ""
        mock_log_error.assert_called_once()
        assert "Failed to initialize LightweightScanPlugin" in mock_log_error.call_args[0][0]

def test_seconds_to_time_str_with_numeric_string():
    plugin = AutoChaptersPlugin()
    # 数値形式の文字列が正しく時間表記文字列に変換されることを検証
    assert plugin._seconds_to_time_str("3665.5") == "1:01:05"
    assert plugin._seconds_to_time_str("120") == "2:00"
    assert plugin._seconds_to_time_str("0.0") == "0:00"

def test_seconds_to_time_str_exception_logging():
    plugin = AutoChaptersPlugin()
    # 不正な入力（bool, 非数値文字列, nan/inf, 負数）のときに警告ログを出して 0:00 にフォールバックすることを検証
    with patch('plugins.auto_chapters_plugin.logger.warning') as mock_log_warn:
        assert plugin._seconds_to_time_str(True) == "0:00"
        mock_log_warn.assert_called_once()
        assert "Invalid seconds value" in mock_log_warn.call_args[0][0]

    with patch('plugins.auto_chapters_plugin.logger.warning') as mock_log_warn:
        assert plugin._seconds_to_time_str("not_a_number") == "0:00"
        mock_log_warn.assert_called_once()
        assert "Invalid seconds value" in mock_log_warn.call_args[0][0]

def test_max_duration_with_numeric_string_and_invalid(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    # segmentsの最後のendに数値に変換可能な文字列や不正な値（boolやNone等）を設定
    ctx.segments = [
        {"start": 0, "end": "100.5", "text": "start_test"},
        {"start": 100.5, "end": True, "text": "invalid_bool_skipped"},
        {"start": 100.5, "end": "invalid_string_skipped", "text": "invalid_skipped"},
        {"start": 100.5, "end": "200.2", "text": "valid_string_end"}
    ]

    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult

    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=4,
            total_duration_seconds=200.2,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": 0, "title": "Intro"},
                {"timestamp": 100, "title": "Section Two"},
                {"timestamp": 200, "title": "Section Three"}
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context

    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)

    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    assert len(chapters) == 3
    # 200秒のチャプターが max_duration (200.2) を超えずに採用されていることを確認
    assert chapters[2]["start_time"] == 200.0


def test_auto_chapters_plugin_execute_initialization_unexpected_exception(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 10, "text": "test"}]

    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    def mock_init(self):
        raise RuntimeError("Simulated unexpected init failure")

    monkeypatch.setattr(LightweightScanPlugin, "__init__", mock_init)

    with patch('plugins.auto_chapters_plugin.logger.error') as mock_log_error:
        res = plugin.execute(ctx)
        assert res.get_extension("chapters") == []
        mock_log_error.assert_called_once()
        log_msg = mock_log_error.call_args[0][0]
        assert "Failed to initialize LightweightScanPlugin due to error (RuntimeError)" in log_msg
        assert "Context segments count: 1" in log_msg


def test_auto_chapters_plugin_execute_scan_unexpected_exception(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [
        {"start": 0, "end": 10, "text": "test"},
        {"start": 10, "end": 20, "text": "test2"}
    ]

    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    def mock_execute(*args, **kwargs):
        raise RuntimeError("Simulated unexpected execute failure")

    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)

    with patch('plugins.auto_chapters_plugin.logger.error') as mock_log_error:
        res = plugin.execute(ctx)
        assert res.get_extension("chapters") == []
        mock_log_error.assert_called_once()
        log_msg = mock_log_error.call_args[0][0]
        assert "Scan plugin execution failed due to error (RuntimeError)" in log_msg
        assert "Context segments count: 2" in log_msg


def test_auto_chapters_plugin_execute_parse_unexpected_exception(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    ctx.segments = [{"start": 0, "end": 10, "text": "test"}]

    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult

    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=1,
            total_duration_seconds=100,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": 0, "title": "Intro"},
                {"timestamp": 30, "title": "Section Two"},
                {"timestamp": 60, "title": "Section Three"}
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context

    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)

    # _seconds_to_time_str がパース中に例外を投げるようにモックして、解析中の unexpected exception を引き起こす
    def mock_seconds_to_time_str(self, seconds):
        if seconds > 0:
            raise RuntimeError("Simulated parse unexpected failure")
        return "0:00"

    monkeypatch.setattr(AutoChaptersPlugin, "_seconds_to_time_str", mock_seconds_to_time_str)

    with patch('plugins.auto_chapters_plugin.logger.error') as mock_log_error:
        res = plugin.execute(ctx)
        assert res.get_extension("chapters") == []
        # mock_log_error は ValueError や RuntimeError など複数回呼ばれる可能性があるが、
        # チャプター生成フェーズのエラーをログ出力していることを検証する
        found_parse_error_log = False
        for call in mock_log_error.call_args_list:
            log_msg = call[0][0]
            if "Chapter generation failed due to error (RuntimeError)" in log_msg:
                assert "Candidates count: 3" in log_msg
                found_parse_error_log = True
                break
        assert found_parse_error_log


def test_auto_chapters_plugin_overflow_and_type_errors_coverage(monkeypatch):
    plugin = AutoChaptersPlugin()
    
    # 1. _seconds_to_time_str() で OverflowError が発生する巨大値
    with patch('plugins.auto_chapters_plugin.logger.warning') as mock_warn:
        assert plugin._seconds_to_time_str(10**310) == "0:00"
        mock_warn.assert_called_once()
        assert "Invalid seconds value" in mock_warn.call_args[0][0]

    # 2. _get_model_safe() で TypeError を発生させる
    from plugins.auto_chapters_plugin import _get_model_safe
    def mock_get_model_type_error(task):
        raise TypeError("Simulated type error in registry")
    
    with patch("plugins.auto_chapters_plugin.get_model", mock_get_model_type_error):
        with patch("logging.Logger.warning") as mock_warn:
            assert _get_model_safe("lightweight_scan", "fallback-model") == "fallback-model"
            mock_warn.assert_called_once()
            assert "Failed to get model" in mock_warn.call_args[0][0]

    # 3. execute() 内で segments の end に OverflowError が発生する巨大値が含まれる場合
    ctx = ProductionContext()
    ctx.segments = [
        {"start": 0, "end": 10**310, "text": "overflow_skipped"},
        {"start": 0, "end": 150.0, "text": "valid_end"}
    ]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=2,
            total_duration_seconds=150.0,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": 0, "title": "Intro"},
                {"timestamp": 50, "title": "Section Two"},
                {"timestamp": 100, "title": "Section Three"}
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context

    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    assert len(chapters) == 3
    assert chapters[2]["start_time"] == 100.0

    # 4. execute() 内で chapter_candidates の timestamp に OverflowError が発生する巨大値が含まれる場合
    ctx_candidates = ProductionContext()
    ctx_candidates.segments = [{"start": 0, "end": 150.0, "text": "valid"}]
    
    def mock_execute_overflow_candidate(self, context):
        context.scan_result = ScanResult(
            total_segments=1,
            total_duration_seconds=150.0,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": 0, "title": "Intro"},
                {"timestamp": 10**310, "title": "Overflow Candidate"},
                {"timestamp": 80, "title": "Section Three"}
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context

    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute_overflow_candidate)
    res_cand = plugin.execute(ctx_candidates)
    chapters_cand = res_cand.get_extension("chapters")
    assert chapters_cand == []


def test_auto_chapters_plugin_get_model_safe_known_exception():
    from plugins.auto_chapters_plugin import _get_model_safe
    
    # get_modelが既知の例外（KeyError）を投げた場合に適切にログが出力され、デフォルト値にフォールバックすること
    def mock_get_model_key_error(task):
        raise KeyError("Simulated known registry key error")
        
    with patch("plugins.auto_chapters_plugin.get_model", mock_get_model_key_error):
        with patch("logging.Logger.warning") as mock_warn:
            assert _get_model_safe("lightweight_scan", "fallback-model") == "fallback-model"
            mock_warn.assert_called_once()
            log_msg = mock_warn.call_args[0][0]
            assert "known configuration error: KeyError" in log_msg



def test_auto_chapters_plugin_extreme_candidate_gap(monkeypatch):
    plugin = AutoChaptersPlugin()
    ctx = ProductionContext()
    # segmentsの最後のendを80秒に設定 (max_duration = 80.0)
    ctx.segments = [
        {"start": 0, "end": 10, "text": "test"},
        {"start": 70, "end": 80, "text": "test2"}
    ]
    
    from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
    
    def mock_execute(self, context):
        context.scan_result = ScanResult(
            total_segments=3,
            total_duration_seconds=150,
            highlight_candidates=[],
            chapter_candidates=[
                {"timestamp": 0, "title": "Intro"},
                {"timestamp": 45, "title": "Within Duration"},
                {"timestamp": 200, "title": "Extreme Candidate"} # max_candidate_time (200.0) > max_duration * 2 (160.0)
            ],
            topic_summary=[],
            estimated_cut_rate=0.0,
            processing_time_seconds=0.1
        )
        return context
        
    monkeypatch.setattr(LightweightScanPlugin, "execute", mock_execute)
    
    res = plugin.execute(ctx)
    chapters = res.get_extension("chapters")
    assert chapters is not None
    # 乖離が極端（2倍超）なため、Exceeds Durationのチェックがスキップされ、Extreme Candidateも採用される
    assert len(chapters) == 3
    assert chapters[2]["title"] == "Extreme Candidate"
    assert chapters[2]["start_time"] == 200.0
