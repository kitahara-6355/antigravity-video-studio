import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch
import pytest

from core.context import ProductionContext
from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult, register


def test_plugin_metadata():
    """プラグインの基本メタデータ属性を検証"""
    plugin = LightweightScanPlugin()
    assert plugin.name == "lightweight_scan"
    assert plugin.priority == 10


def test_load_constraints_success():
    """制約条件ファイルが正常に読み込める場合のテスト"""
    plugin = LightweightScanPlugin()
    # 正常に読み込まれた場合の値を検証
    assert plugin.max_segments == 6000
    assert plugin.highlight_limit == 50
    assert plugin.chapter_limit == 30


def test_load_constraints_fallback():
    """制約条件ファイルの読み込みで例外が発生した際にデフォルト値にフォールバックすることをテスト"""
    with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
        plugin = LightweightScanPlugin()
        assert plugin.max_segments == 6000
        assert plugin.highlight_limit == 50
        assert plugin.chapter_limit == 30


def test_can_execute():
    """can_execute メソッドの挙動をテスト"""
    plugin = LightweightScanPlugin()
    
    # 1. segments 属性がない場合 -> False
    context_no_segments = ProductionContext()
    if hasattr(context_no_segments, "segments"):
        delattr(context_no_segments, "segments")
    assert plugin.can_execute(context_no_segments) is False

    # 2. segments が空リストの場合 -> False
    context_empty_segments = ProductionContext()
    context_empty_segments.segments = []
    assert plugin.can_execute(context_empty_segments) is False

    # 3. segments に要素がある場合 -> True
    context_with_segments = ProductionContext()
    context_with_segments.segments = [{"text": "hello", "start": 0.0, "end": 1.0}]
    assert plugin.can_execute(context_with_segments) is True


def test_execute_basic():
    """execute メソッドの正常系テスト"""
    plugin = LightweightScanPlugin()
    context = ProductionContext()
    
    # セグメントの準備
    context.segments = [
        {"text": "まず、最初のステップです。", "start": 0.0, "end": 5.0},
        {"text": "これはすごい発見ですね！", "start": 5.0, "end": 10.0},
        {"text": "次に進みます。", "start": 10.0, "end": 15.0},
    ]
    
    result_context = plugin.execute(context)
    
    assert result_context is context
    assert hasattr(result_context, "scan_result")
    
    scan_result = result_context.scan_result
    assert isinstance(scan_result, ScanResult)
    assert scan_result.total_segments == 3
    assert scan_result.total_duration_seconds == 15.0
    assert len(scan_result.highlight_candidates) > 0
    assert len(scan_result.chapter_candidates) > 0
    assert isinstance(scan_result.topic_summary, list)
    assert scan_result.estimated_cut_rate == 0.0
    assert scan_result.processing_time_seconds >= 0.0


def test_execute_exceed_max_segments():
    """max_segmentsを超えるセグメントが与えられた場合にスライスされることをテスト"""
    plugin = LightweightScanPlugin()
    plugin.max_segments = 2  # テスト用に制限を小さくする
    
    context = ProductionContext()
    context.segments = [
        {"text": "セグメント1", "start": 0.0, "end": 2.0},
        {"text": "セグメント2", "start": 2.0, "end": 4.0},
        {"text": "セグメント3", "start": 4.0, "end": 6.0},
    ]
    
    result_context = plugin.execute(context)
    scan_result = result_context.scan_result
    assert scan_result.total_segments == 2
    assert scan_result.total_duration_seconds == 4.0


def test_extract_highlight_candidates():
    """ハイライト候補抽出とスコアリング、およびソート・上限制限のテスト"""
    plugin = LightweightScanPlugin()
    plugin.highlight_limit = 2  # テスト用に制限
    
    # 感情キーワードを含むセグメント
    segments = [
        {"text": "普通のセグメント", "start": 0.0, "end": 2.0},
        {"text": "これはすごい！まさか！", "start": 2.0, "end": 4.0},  # 「驚き」キーワード: すごい, まさか, ! (weight 20)
        {"text": "結論を言うと、これが重要です。", "start": 4.0, "end": 6.0},  # 「結論」キーワード: 結論, 重要 (weight 17/18)
        {"text": "なぜこのような結果になるのか？", "start": 6.0, "end": 8.0},  # 「質問」キーワード: なぜ, ？ (weight 16)
    ]
    
    candidates = plugin._extract_highlight_candidates(segments)
    
    # highlight_limitが2なので、上位2件が返される
    assert len(candidates) == 2
    
    # スコアで降順ソートされていることを確認
    assert candidates[0]["score"] >= candidates[1]["score"]
    
    # 感情タイプやキーワードが正しく設定されていることを確認
    types = [c["type"] for c in candidates]
    assert "驚き" in types or "発見" in types or "結論" in types


def test_extract_chapter_candidates():
    """チャプター候補抽出、オープニングの自動追加、しきい値チェックのテスト"""
    plugin = LightweightScanPlugin()
    plugin.chapter_limit = 3
    
    # 1. 空のセグメントリスト -> オープニングのみ
    assert plugin._extract_chapter_candidates([]) == [{
        "timestamp": 0,
        "title": "オープニング",
        "marker": None,
        "adopted": True
    }]
    
    # 2. しきい値（min_interval）未満での無視と、しきい値以上での追加
    # total_duration = 120秒 のとき、min_interval = max(30, 120/40) = 30秒
    segments = [
        {"text": "まず開始します。", "start": 0.0, "end": 5.0},
        {"text": "続いてすぐに次のトピックです。", "start": 10.0, "end": 15.0},  # start=10.0 はオープニング(0.0)から10秒 < 30秒なので無視されるべき
        {"text": "ここでのポイントは重要です。", "start": 40.0, "end": 45.0},  # start=40.0 はオープニングから40秒 > 30秒なので追加される
        {"text": "マーカーのない無関係な発言です。", "start": 75.0, "end": 80.0},  # start=75.0 は 40.0 から 35秒 > 30秒だが、マーカーがないため追加されない (174->167 ブランチのテスト)
        {"text": "まとめになります。", "start": 110.0, "end": 120.0},  # start=110.0 は前回の追加(40.0)から70秒 > 30秒で、マーカーがあるので追加される
    ]
    
    chapters = plugin._extract_chapter_candidates(segments)
    
    # 期待される結果:
    # 1. オープニング (0.0)
    # 2. 「ポイント」 (40.0) (「ここでのポイント」の"ここで"にマッチ)
    # 3. 「まとめ」 (110.0) (「まとめになります」の"まとめ"にマッチ)
    assert len(chapters) == 3
    assert chapters[0]["title"] == "オープニング"
    assert chapters[0]["timestamp"] == 0
    
    assert chapters[1]["timestamp"] == 40.0
    assert chapters[1]["marker"] in ["ここで", "ポイント", "重要"]
    
    assert chapters[2]["timestamp"] == 110.0
    assert chapters[2]["marker"] == "まとめ"


def test_generate_topic_summary():
    """トピック要約キーワード抽出のフィルタリングと重複除外テスト"""
    plugin = LightweightScanPlugin()
    
    # ループ抜けとフィルタ（長さ2未満、common_words、重複）を網羅する
    # "の", "を" -> common_words
    # "あ" -> 長さ2未満 (len < 2)
    # "Python" -> 重複 (word not in keywords が False)
    segments = [
        {"text": "Python の 開発 あ テスト Python 自動化 効率 改善 を 速度 品質 分析 運用 設計 構築"}
    ]
    
    summary = plugin._generate_topic_summary(segments)
    
    # 期待されるキーワード
    assert "Python" in summary
    assert "開発" in summary
    assert "の" not in summary
    assert "を" not in summary
    assert "あ" not in summary
    # 重複していない
    assert summary.count("Python") == 1
    # ちょうど10件
    assert len(summary) == 10


def test_estimate_cut_rate():
    """推定カット率計算のテスト"""
    plugin = LightweightScanPlugin()
    
    # 3600秒（1時間）以下の場合は 0.0
    assert plugin._estimate_cut_rate(3600.0) == 0.0
    assert plugin._estimate_cut_rate(1800.0) == 0.0
    
    # 3600秒を超える場合は正のカット率を計算
    # 7200秒（2時間）の場合、目標3600秒なので (7200-3600)/7200 * 100 = 50.0%
    assert plugin._estimate_cut_rate(7200.0) == 50.0


def test_load_constraints_invalid_json():
    """制約条件ファイルが不正なJSONの場合にデフォルト値にフォールバックすることをテスト"""
    invalid_json_data = "{ invalid_json: "
    with patch("builtins.open", mock_open(read_data=invalid_json_data)):
        plugin = LightweightScanPlugin()
        assert plugin.max_segments == 6000
        assert plugin.highlight_limit == 50
        assert plugin.chapter_limit == 30


def test_load_constraints_missing_keys():
    """制約条件ファイルに必要なキーが存在しない場合にデフォルト値にフォールバックすることをテスト"""
    missing_keys_json = json.dumps({"processing": {}})
    with patch("builtins.open", mock_open(read_data=missing_keys_json)):
        plugin = LightweightScanPlugin()
        assert plugin.max_segments == 6000
        assert plugin.highlight_limit == 50
        assert plugin.chapter_limit == 30


def test_register():
    """register関数のテスト"""
    mock_registry = MagicMock()
    register(mock_registry)
    mock_registry.register.assert_called_once()
    assert isinstance(mock_registry.register.call_args[0][0], LightweightScanPlugin)


def test_extract_highlight_candidates_no_keywords():
    """感情キーワードが含まれない場合のテスト"""
    plugin = LightweightScanPlugin()
    segments = [
        {"text": "これは普通の文です。", "start": 0.0, "end": 2.0},
        {"text": "特に何もありません。", "start": 2.0, "end": 4.0},
    ]
    candidates = plugin._extract_highlight_candidates(segments)
    assert candidates == []


def test_extract_highlight_candidates_exceed_limit():
    """ハイライト候補が制限値を超える場合の優先順位と制限のテスト"""
    plugin = LightweightScanPlugin()
    plugin.highlight_limit = 3
    
    # 感情キーワードを含むセグメントを多数用意し、スコアが異なるようにする
    segments = [
        {"text": "これはすごいです！", "start": 0.0, "end": 2.0},    # 驚き: weight 20
        {"text": "実はこれがコツです。", "start": 2.0, "end": 4.0},   # 発見: weight 18
        {"text": "つまり、まとめると", "start": 4.0, "end": 6.0},   # 結論: weight 17
        {"text": "なぜでしょうか？", "start": 6.0, "end": 8.0},     # 質問: weight 16
        {"text": "10倍になります。", "start": 8.0, "end": 10.0},    # 数値: weight 14
    ]
    
    candidates = plugin._extract_highlight_candidates(segments)
    
    # highlight_limitである3件のみ抽出されることを確認
    assert len(candidates) == 3
    
    # スコアの高い順（驚き[20] -> 発見[18] -> 結論[17]）に並んでいることを確認
    assert candidates[0]["type"] == "驚き"
    assert candidates[1]["type"] == "発見"
    assert candidates[2]["type"] == "結論"


def test_extract_chapter_candidates_non_zero_start():
    """セグメントが0秒以外から開始する場合のチャプター候補のテスト"""
    plugin = LightweightScanPlugin()
    # min_intervalは最低30秒であるため、startが30秒以上である必要がある
    segments = [
        {"text": "まず開始します。", "start": 30.0, "end": 35.0},
    ]
    
    chapters = plugin._extract_chapter_candidates(segments)
    
    # 0秒時点のオープニングが常に設定されることを確認
    assert len(chapters) == 2
    assert chapters[0]["timestamp"] == 0
    assert chapters[0]["title"] == "オープニング"
    
    # 最初のセグメントが追加されていることを確認
    assert chapters[1]["timestamp"] == 30.0
    assert chapters[1]["marker"] == "まず"



def test_extract_chapter_candidates_min_interval_boundary():
    """min_interval（最小間隔）の境界値におけるテスト"""
    plugin = LightweightScanPlugin()
    plugin.chapter_limit = 5
    
    # total_duration = 120秒 のとき、min_interval = max(30, 120/40) = 30秒
    # 境界値をテストするため、30秒ぴったりおよび30秒未満の間隔を設定する
    segments = [
        {"text": "まず、1つ目。", "start": 0.0, "end": 10.0},
        {"text": "次に、2つ目（間隔29秒、30秒未満なのでスキップ）。", "start": 29.0, "end": 35.0},
        {"text": "続いて、3つ目（間隔30秒、ちょうど30秒なので追加）。", "start": 30.0, "end": 40.0},
        {"text": "ところで、4つ目（間隔30秒、追加）。", "start": 60.0, "end": 70.0},
    ]
    
    chapters = plugin._extract_chapter_candidates(segments)
    
    # 期待されるチャプター:
    # 1. オープニング (timestamp: 0.0)
    # 2. 続いて (timestamp: 30.0)
    # 3. ところで (timestamp: 60.0)
    # ※ start: 29.0 の「次に」は間隔が29秒（< 30秒）なのでスキップされる
    assert len(chapters) == 3
    timestamps = [c["timestamp"] for c in chapters]
    assert 0 in timestamps
    assert 30.0 in timestamps
    assert 60.0 in timestamps
    assert 29.0 not in timestamps


def test_generate_topic_summary_exceed_100_segments():
    """セグメント数が100を超える場合のトピック要約の動作テスト"""
    plugin = LightweightScanPlugin()
    
    # 101個のセグメントを作成。101個目だけに特有のキーワードを入れる
    segments = [{"text": f"テストワード{i}"} for i in range(100)]
    segments.append({"text": "特別キーワード"})
    
    summary = plugin._generate_topic_summary(segments)
    
    # 100件目までから抽出されるため、101件目の「特別キーワード」は含まれないことを確認
    assert "特別キーワード" not in summary
    assert len(summary) == 10


def test_generate_topic_summary_less_keywords():
    """セグメントから抽出されるキーワードが10未満の場合のテスト"""
    plugin = LightweightScanPlugin()
    
    # 重複ワードと一般的な言葉のみのセグメント
    segments = [
        {"text": "Python の の の"},
        {"text": "テスト を を を"},
    ]
    
    summary = plugin._generate_topic_summary(segments)
    
    # 有効なキーワードは "Python" と "テスト" の2つのみになるはず
    assert len(summary) == 2
    assert "Python" in summary
    assert "テスト" in summary


def test_estimate_cut_rate_boundary():
    """推定カット率計算の境界値テスト"""
    plugin = LightweightScanPlugin()
    
    # 3600.0秒（ちょうど1時間）
    assert plugin._estimate_cut_rate(3600.0) == 0.0
    
    # 3600.01秒（1時間をわずかに超える）
    rate_above = plugin._estimate_cut_rate(3600.01)
    assert rate_above > 0.0
    assert rate_above == (3600.01 - 3600) / 3600.01 * 100
    
    # 3599.9秒（1時間未満）
    assert plugin._estimate_cut_rate(3599.9) == 0.0


def test_estimate_cut_rate_validation():
    """推定カット率計算の入力値バリデーションテスト"""
    plugin = LightweightScanPlugin()
    
    # 無効な型の場合に TypeError が発生することを確認
    with pytest.raises(TypeError, match="total_duration must be int or float"):
        plugin._estimate_cut_rate("invalid")
    
    # 負の値の場合に ValueError が発生することを確認
    with pytest.raises(ValueError, match="total_duration must be non-negative"):
        plugin._estimate_cut_rate(-1.0)


def test_execute_invalid_segments_type():
    """context.segments がリスト以外の型の場合に安全に空の ScanResult にフォールバックすることをテスト"""
    plugin = LightweightScanPlugin()
    
    # segments が辞書型の場合
    context_dict = ProductionContext()
    context_dict.segments = {"not": "a list"}
    
    result_context = plugin.execute(context_dict)
    assert hasattr(result_context, "scan_result")
    assert result_context.scan_result.total_segments == 0
    assert result_context.scan_result.total_duration_seconds == 0.0
    
    # segments が None の場合
    context_none = ProductionContext()
    context_none.segments = None
    
    result_context = plugin.execute(context_none)
    assert hasattr(result_context, "scan_result")
    assert result_context.scan_result.total_segments == 0


def test_execute_malformed_segment_elements():
    """セグメント要素の型やキーが不正な場合に適切にスキップ・補正されることをテスト"""
    plugin = LightweightScanPlugin()
    context = ProductionContext()
    context.segments = [
        # 1. 正常なセグメント
        {"text": "これは正常な文です。まず開始します。", "start": 0.0, "end": 10.0},
        # 2. 辞書型ではない不正な要素（スキップされるべき）
        "invalid_segment_string",
        # 3. start, end が数値ではないが、数値変換可能なセグメント（補正されるべき）
        {"text": "これはすごいです！", "start": "20.0", "end": "30"},
        # 4. start, end が数値変換不可能なセグメント（フォールバックされるべき）
        {"text": "コツを見つけました。", "start": "invalid", "end": "none"},
        # 5. キーが一部欠損しているセグメント
        {"start": 40.0, "end": 50.0}
    ]
    
    result_context = plugin.execute(context)
    scan_result = result_context.scan_result
    
    # 辞書以外の要素はスキップされ、それ以外は補正されて処理されるため、
    # 正常分: 1(正常), 3(変換), 4(フォールバック), 5(欠損) の合計4件
    assert scan_result.total_segments == 4
    
    # highlight 候補の抽出もエラーなく動作していること
    assert len(scan_result.highlight_candidates) > 0


def test_load_constraints_invalid_type():
    """制約条件ファイル内の値の型や範囲が不正な場合にデフォルト値にフォールバックすることをテスト"""
    # 1. 値が文字列の場合
    invalid_type_json = json.dumps({
        "processing": {
            "stage1_lightweight": {
                "max_segments": "not_an_int",
                "highlight_candidates": 50,
                "chapter_candidates": 30
            }
        }
    })
    with patch("builtins.open", mock_open(read_data=invalid_type_json)):
        plugin = LightweightScanPlugin()
        assert plugin.max_segments == 6000
        assert plugin.highlight_limit == 50
        assert plugin.chapter_limit == 30

    # 2. 値が負の数の場合
    negative_value_json = json.dumps({
        "processing": {
            "stage1_lightweight": {
                "max_segments": 6000,
                "highlight_candidates": -5,
                "chapter_candidates": 30
            }
        }
    })
    with patch("builtins.open", mock_open(read_data=negative_value_json)):
        plugin = LightweightScanPlugin()
        assert plugin.max_segments == 6000
        assert plugin.highlight_limit == 50
        assert plugin.chapter_limit == 30


def test_execute_unexpected_exception():
    """プラグイン実行中に予期しない重大なエラーが発生した場合でもクラッシュせず安全にフォールバックすることをテスト"""
    plugin = LightweightScanPlugin()
    context = ProductionContext()
    context.segments = [
        {"text": "テストです。", "start": 0.0, "end": 10.0}
    ]
    
    # _extract_highlight_candidates 実行時に例外を投げるようにモックする
    with patch.object(plugin, "_extract_highlight_candidates", side_effect=RuntimeError("Unexpected error")):
        result_context = plugin.execute(context)
        
        # 例外をキャッチし、デフォルトの ScanResult でフォールバックされること
        assert hasattr(result_context, "scan_result")
        scan_result = result_context.scan_result
        assert scan_result.total_segments == 0
        assert scan_result.total_duration_seconds == 0.0
        assert scan_result.highlight_candidates == []
        assert scan_result.chapter_candidates == []
        assert scan_result.topic_summary == []
        assert scan_result.estimated_cut_rate == 0.0



def test_execute_context_none_handling():
    """context が None の場合に AttributeError で二次クラッシュせず、ValueError が適切に再送出されることをテスト"""
    plugin = LightweightScanPlugin()
    with pytest.raises(ValueError, match="ProductionContext is None"):
        plugin.execute(None)


def test_generate_topic_summary_japanese():
    """スペース区切りのない日本語テキストから、主要なキーワードが正しく抽出されることをテスト"""
    plugin = LightweightScanPlugin()
    
    segments = [
        {"text": "これはテスト用の日本語文章です。"},
        {"text": "動画自動化システムの開発を行っています。"},
        {"text": "効率的な処理と品質の向上を目指します。"}
    ]
    
    summary = plugin._generate_topic_summary(segments)
    
    # ひらがなのみ、または1文字の単語は除外され、主要な名詞が抽出されていること
    assert "テスト" in summary
    assert "日本語文章" in summary
    assert "動画自動化" in summary
    assert "システム" in summary
    assert "開発" in summary
    assert "効率的" in summary
    assert "処理" in summary
    assert "品質" in summary
    assert "向上" in summary
    
    # 助詞や助動詞などは含まれていないこと
    assert "の" not in summary
    assert "に" not in summary
    assert "は" not in summary
    assert "です" not in summary


def test_load_constraints_permission_error():
    """制約条件ファイル読み込み時に PermissionError が発生した際に、デフォルト値にフォールバックすることをテスト"""
    from unittest.mock import patch
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        plugin = LightweightScanPlugin()
        assert plugin.max_segments == 6000
        assert plugin.highlight_limit == 50
        assert plugin.chapter_limit == 30


def test_execute_attribute_error_handling():
    """execute メソッド実行中に AttributeError が発生した場合に、デフォルトの ScanResult でフォールバックされることをテスト"""
    from unittest.mock import patch
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    from core.context import ProductionContext
    plugin = LightweightScanPlugin()
    context = ProductionContext()
    context.segments = [
        {"text": "テストです。", "start": 0.0, "end": 10.0}
    ]
    
    # _extract_highlight_candidates 実行時に AttributeError を投げるようにモックする
    with patch.object(plugin, "_extract_highlight_candidates", side_effect=AttributeError("Mocked attribute error")):
        result_context = plugin.execute(context)
        
        # 例外をキャッチし、デフォルトの ScanResult でフォールバックされること
        assert hasattr(result_context, "scan_result")
        scan_result = result_context.scan_result
        assert scan_result.total_segments == 0
        assert scan_result.total_duration_seconds == 0.0


def test_execute_fatal_exception_propagation():
    """execute メソッド実行中に SystemExit などの致命的なエラーが発生した場合、キャッチされずに伝播することをテスト"""
    from unittest.mock import patch
    from plugins.lightweight_scan_plugin import LightweightScanPlugin
    from core.context import ProductionContext
    import pytest
    plugin = LightweightScanPlugin()
    context = ProductionContext()
    context.segments = [
        {"text": "テストです。", "start": 0.0, "end": 10.0}
    ]
    
    # _extract_highlight_candidates 実行時に SystemExit を投げるようにモックする
    with patch.object(plugin, "_extract_highlight_candidates", side_effect=SystemExit(1)):
        with pytest.raises(SystemExit):
            plugin.execute(context)
