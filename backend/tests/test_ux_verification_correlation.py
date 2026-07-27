"""
ux_verification/correlation.py のユニットテスト
"""
import sys
from pathlib import Path

import pytest

# パス設定
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from ux_verification.correlation import (
    StoryScene,
    CorrelationResult,
    CorrelationAnalyzer,
)


def test_story_scene_post_init():
    """StoryScene の __post_init__ をテスト"""
    # linked_items が None の場合は空リストで初期化されること
    scene = StoryScene(id="S1", text="Sample Text", linked_items=None)
    assert scene.linked_items == []

    # linked_items が指定されている場合はそのまま保持されること
    scene_with_items = StoryScene(id="S2", text="Sample Text 2", linked_items=["item1"])
    assert scene_with_items.linked_items == ["item1"]


def test_correlation_result_post_init():
    """CorrelationResult の __post_init__ をテスト"""
    # 各種 _ids が None の場合は空リストで初期化されること
    result = CorrelationResult(
        ux_story="O-2",
        total_items=10,
        correlated_items=8,
        uncorrelated_items=2,
        correlation_rate=80.0,
        total_scenes=5,
        covered_scenes=4,
        scene_coverage=80.0,
        uncovered_scene_ids=None,
        uncorrelated_item_ids=None,
    )
    assert result.uncovered_scene_ids == []
    assert result.uncorrelated_item_ids == []

    # 指定されている場合はそのまま保持されること
    result_with_ids = CorrelationResult(
        ux_story="O-2",
        total_items=10,
        correlated_items=8,
        uncorrelated_items=2,
        correlation_rate=80.0,
        total_scenes=5,
        covered_scenes=4,
        scene_coverage=80.0,
        uncovered_scene_ids=["S1"],
        uncorrelated_item_ids=["I1"],
    )
    assert result_with_ids.uncovered_scene_ids == ["S1"]
    assert result_with_ids.uncorrelated_item_ids == ["I1"]


def test_correlation_analyzer_load_story_non_existent(tmp_path):
    """CorrelationAnalyzer.load_story でストーリーファイルが存在しない場合の挙動をテスト"""
    analyzer = CorrelationAnalyzer(stories_dir=tmp_path)
    result = analyzer.load_story("NON-EXISTENT")
    assert result is None


def test_correlation_analyzer_analyze_empty_items(tmp_path):
    """CorrelationAnalyzer.analyze で検証項目が空の場合のゼロ除算回避をテスト"""
    analyzer = CorrelationAnalyzer(stories_dir=tmp_path)
    # ストーリーファイルが存在しない + items が空
    result = analyzer.analyze("O-2", [])
    assert result.ux_story == "O-2"
    assert result.total_items == 0
    assert result.correlated_items == 0
    assert result.uncorrelated_items == 0
    assert result.correlation_rate == 0.0
    assert result.total_scenes == 0
    assert result.covered_scenes == 0
    assert result.scene_coverage == 0.0
    assert result.uncovered_scene_ids == []
    assert result.uncorrelated_item_ids == []


def test_correlation_analyzer_analyze_with_story(tmp_path):
    """CorrelationAnalyzer.analyze でストーリーファイルが存在する場合の挙動をテスト"""
    # 擬似ストーリーファイルを準備
    story_dir = tmp_path / "stories"
    story_dir.mkdir(parents=True, exist_ok=True)
    
    import json
    story_data = {
        "ux_id": "O-2",
        "scenes": [
            {"id": "S1", "text": "Scene 1", "linked_items": ["item1"]},
            {"id": "S2", "text": "Scene 2", "linked_items": []}
        ]
    }
    with open(story_dir / "o2_transcription.json", "w", encoding="utf-8") as f:
        json.dump(story_data, f)

    analyzer = CorrelationAnalyzer(stories_dir=story_dir)

    # テスト項目
    items = [
        {"id": "item1", "ux_story": "O-2", "story_scene": "S1"},
        {"id": "item2", "ux_story": "O-2", "story_scene": ""}, # 未連動
        {"id": "item3", "ux_story": "O-3", "story_scene": "S1"}, # 別のストーリー
    ]

    result = analyzer.analyze("O-2", items)
    assert result.ux_story == "O-2"
    assert result.total_items == 2 # item1 と item2
    assert result.correlated_items == 1 # item1
    assert result.uncorrelated_items == 1 # item2
    assert result.correlation_rate == 50.0 # 1 / 2 * 100
    assert result.total_scenes == 2
    assert result.covered_scenes == 1 # S1
    assert result.scene_coverage == 50.0
    assert result.uncovered_scene_ids == ["S2"]
    assert result.uncorrelated_item_ids == ["item2"]


def test_correlation_analyzer_analyze_all():
    """CorrelationAnalyzer.analyze_all の一括分析をテスト"""
    # テスト用ダミーアナライザー (stories_dir は空ディレクトリを指すようにする)
    analyzer = CorrelationAnalyzer(stories_dir=Path("/non-existent-dir-for-test"))

    items = [
        {"id": "item1", "ux_story": "O-1", "story_scene": "S1"},
        {"id": "item2", "ux_story": "O-2", "story_scene": "S1"},
        {"id": "item3", "ux_story": "", "story_scene": "S1"}, # ux_story が空
    ]

    results = analyzer.analyze_all(items)
    assert len(results) == 2
    assert "O-1" in results
    assert "O-2" in results
    assert results["O-1"].total_items == 1
    assert results["O-2"].total_items == 1


def test_correlation_analyzer_validate_minimum_correlation():
    """CorrelationAnalyzer.validate_minimum_correlation の挙動をテスト"""
    analyzer = CorrelationAnalyzer(stories_dir=Path("/non-existent-dir-for-test"))

    # すべて基準を満たす場合
    items_pass = [
        {"id": "item1", "ux_story": "O-1", "story_scene": "S1"},
    ]
    passed, violations = analyzer.validate_minimum_correlation(items_pass, minimum=85.0)
    assert passed is True
    assert len(violations) == 0

    # 一部が基準を満たさない場合 (連動率 50% < 85%)
    items_fail = [
        {"id": "item1", "ux_story": "O-1", "story_scene": "S1"},
        {"id": "item2", "ux_story": "O-1", "story_scene": ""}, # 未連動
    ]
    passed, violations = analyzer.validate_minimum_correlation(items_fail, minimum=85.0)
    assert passed is False
    assert len(violations) == 1
    assert "O-1: 連動率 50.0% < 85.0%" in violations[0]


def test_correlation_analyzer_load_story_traversal_protection(tmp_path):
    """CorrelationAnalyzer.load_story で不正なID（パストラバーサルやワイルドカード）が指定された場合の安全性を検証"""
    analyzer = CorrelationAnalyzer(stories_dir=tmp_path)
    # パストラバーサル
    assert analyzer.load_story("../../etc/passwd") is None
    assert analyzer.load_story("..\\..\\win.ini") is None
    # ワイルドカード
    assert analyzer.load_story("*") is None
    assert analyzer.load_story("?") is None


def test_correlation_analyzer_analyze_missing_keys(tmp_path):
    """CorrelationAnalyzer.analyze で検証項目の辞書キーが欠損している場合の安全動作を検証"""
    analyzer = CorrelationAnalyzer(stories_dir=tmp_path)
    
    # 必須キーが欠損した要素を含む items
    items = [
        {"id": "item1"},  # ux_story, story_scene が欠損
        {"ux_story": "O-2"},  # id, story_scene が欠損
        {"story_scene": "S1"},  # id, ux_story が欠損
    ]
    
    result = analyzer.analyze("O-2", items)
    # 例外でクラッシュせずに正しく計算されること
    assert result.ux_story == "O-2"
    assert result.total_items == 1  # 2つ目の要素だけが ux_story == "O-2"
    assert result.correlated_items == 0
    assert result.uncorrelated_items == 1
    assert result.correlation_rate == 0.0
    assert result.uncorrelated_item_ids == [""]  # id が欠損しているのでデフォルトの空文字になる


def test_load_story_corrupted_json(tmp_path):
    """CorrelationAnalyzer.load_story で JSONファイルが破損している場合の挙動をテスト"""
    story_dir = tmp_path / "stories"
    story_dir.mkdir(parents=True, exist_ok=True)
    
    # 破損したJSONファイルを書き込む
    with open(story_dir / "o2_transcription.json", "w", encoding="utf-8") as f:
        f.write("{invalid json}")
        
    analyzer = CorrelationAnalyzer(stories_dir=story_dir)
    result = analyzer.load_story("O-2")
    assert result is None


def test_load_story_os_error():
    """CorrelationAnalyzer.load_story で OSError が発生した場合の挙動をテスト"""
    class BadPath:
        def glob(self, pattern):
            raise OSError("Simulated scan permission error")
            
    analyzer = CorrelationAnalyzer(stories_dir=BadPath())
    result = analyzer.load_story("O-2")
    assert result is None


def test_load_story_file_open_os_error(tmp_path):
    """CorrelationAnalyzer.load_story でファイルオープン時に OSError が発生した場合の挙動をテスト"""
    story_dir = tmp_path / "stories"
    story_dir.mkdir(parents=True, exist_ok=True)
    
    # ダミーのストーリーファイルを作成
    import json
    story_data = {"ux_id": "O-2", "scenes": []}
    with open(story_dir / "o2_transcription.json", "w", encoding="utf-8") as f:
        json.dump(story_data, f)
        
    analyzer = CorrelationAnalyzer(stories_dir=story_dir)
    
    # builtins.open をモック化して OSError を投げさせる
    from unittest.mock import patch
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        result = analyzer.load_story("O-2")
        assert result is None


def test_analyze_invalid_story_structure(tmp_path):
    """CorrelationAnalyzer.analyze でストーリーデータの構造が不正な場合の挙動をテスト"""
    story_dir = tmp_path / "stories"
    story_dir.mkdir(parents=True, exist_ok=True)
    
    import json
    # scenes キーがリストではなく文字列
    story_data_invalid_scenes = {
        "ux_id": "O-2",
        "scenes": "not a list"
    }
    with open(story_dir / "o2_transcription.json", "w", encoding="utf-8") as f:
        json.dump(story_data_invalid_scenes, f)
        
    analyzer = CorrelationAnalyzer(stories_dir=story_dir)
    # scenes がリストでない場合にクラッシュしないこと
    result = analyzer.analyze("O-2", [])
    assert result.total_scenes == 0
    
    # ストーリーデータ自体が辞書ではなくリスト
    with open(story_dir / "o2_transcription.json", "w", encoding="utf-8") as f:
        json.dump(["not a dict"], f)
        
    # story_data が辞書でない場合にクラッシュしないこと
    result = analyzer.analyze("O-2", [])
    assert result.total_scenes == 0


def test_analyze_invalid_scene_format(tmp_path):
    """CorrelationAnalyzer.analyze でシーンの形式が不正な場合の挙動をテスト"""
    story_dir = tmp_path / "stories"
    story_dir.mkdir(parents=True, exist_ok=True)
    
    import json
    # シーンの中に辞書でない要素や、必要なキーが欠けている要素を混ぜる
    story_data = {
        "ux_id": "O-2",
        "scenes": [
            "not a dict",
            {"id": "S1"},  # text キーがない
            {"text": "Sample Text"},  # id キーがない
            {"id": "S2", "text": "Valid Scene"}  # 有効
        ]
    }
    with open(story_dir / "o2_transcription.json", "w", encoding="utf-8") as f:
        json.dump(story_data, f)
        
    analyzer = CorrelationAnalyzer(stories_dir=story_dir)
    result = analyzer.analyze("O-2", [])
    assert result.total_scenes == 1  # 有効な S2 だけがカウントされること


def test_analyze_invalid_item_type(tmp_path):
    """CorrelationAnalyzer.analyze で items がリストでない、または辞書以外の要素が含まれる場合の挙動をテスト"""
    analyzer = CorrelationAnalyzer(stories_dir=tmp_path)
    
    # items 内に辞書でない不正なオブジェクトが含まれている場合
    items = [
        "not a dict",
        None,
        {"id": "item1", "ux_story": "O-2", "story_scene": "S1"}
    ]
    
    result = analyzer.analyze("O-2", items)
    # 正常な要素だけがカウントされること
    assert result.total_items == 1
    assert result.correlated_items == 1
    
    # items 自体がリストでない場合
    result_invalid_items = analyzer.analyze("O-2", "not a list")
    assert result_invalid_items.total_items == 0


def test_correlation_analyzer_load_story_invalid_type():
    """load_story に None や非文字列の ux_id を渡したときの安全な挙動をテスト"""
    analyzer = CorrelationAnalyzer()
    # AttributeError にならず、None を返すこと
    assert analyzer.load_story(None) is None
    assert analyzer.load_story(123) is None
    assert analyzer.load_story([]) is None


def test_correlation_analyzer_analyze_invalid_ux_id_type():
    """analyze に None や非文字列の ux_id を渡したときの安全な挙動をテスト"""
    analyzer = CorrelationAnalyzer()
    # AttributeError にならず、CorrelationResult が返り、total_items が 0 になること
    result = analyzer.analyze(None, [])
    assert result.ux_story is None
    assert result.total_items == 0

    result = analyzer.analyze(123, [])
    assert result.ux_story == 123
    assert result.total_items == 0


def test_correlation_analyzer_analyze_all_invalid_items_type():
    """analyze_all に None や非リストの items を渡したときの安全な挙動をテスト"""
    analyzer = CorrelationAnalyzer()
    # TypeError にならず、空の辞書を返すこと
    assert analyzer.analyze_all(None) == {}
    assert analyzer.analyze_all("not a list") == {}


def test_correlation_analyzer_analyze_all_items_with_non_dict_elements():
    """analyze_all の items 内に非辞書の要素が含まれる場合の安全な挙動をテスト"""
    analyzer = CorrelationAnalyzer()
    items = [
        "not a dict",
        None,
        {"id": "item1", "ux_story": "O-2", "story_scene": "S1"}
    ]
    # 例外にならず、有効な項目のみで分析結果が得られること
    results = analyzer.analyze_all(items)
    assert "O-2" in results
    assert results["O-2"].total_items == 1


def test_correlation_analyzer_validate_minimum_correlation_invalid_minimum_type():
    """validate_minimum_correlation に無効な minimum の型や値を渡したときに例外を投げることをテスト"""
    analyzer = CorrelationAnalyzer()
    
    # minimum に数値以外を渡した場合に TypeError / ValueError が発生すること
    with pytest.raises((TypeError, ValueError)):
        analyzer.validate_minimum_correlation([], minimum="invalid")
        
    with pytest.raises((TypeError, ValueError)):
        analyzer.validate_minimum_correlation([], minimum=None)

    with pytest.raises(ValueError):
        analyzer.validate_minimum_correlation([], minimum=-10.0)

    with pytest.raises(ValueError):
        analyzer.validate_minimum_correlation([], minimum=105.0)
