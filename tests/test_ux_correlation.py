import json
from pathlib import Path
import pytest
from backend.ux_verification.correlation import (
    StoryScene,
    CorrelationResult,
    CorrelationAnalyzer,
    STORIES_DIR
)


def test_story_scene_fallback():
    # linked_itemsが指定されない場合のPost Init
    scene = StoryScene(id="S1", text="Sample text")
    assert scene.linked_items == []


def test_correlation_result_fallback():
    # uncovered_scene_idsやuncorrelated_item_idsが指定されない場合のPost Init
    res = CorrelationResult(
        ux_story="O-2",
        total_items=0,
        correlated_items=0,
        uncorrelated_items=0,
        correlation_rate=0.0,
        total_scenes=0,
        covered_scenes=0,
        scene_coverage=0.0
    )
    assert res.uncovered_scene_ids == []
    assert res.uncorrelated_item_ids == []


def test_analyzer_default_stories_dir():
    # stories_dirが指定されない場合、デフォルトのSTORIES_DIRになること
    analyzer = CorrelationAnalyzer()
    assert analyzer.stories_dir == STORIES_DIR


def test_load_story_normalization_and_security(tmp_path):
    # o2_transcription.jsonというファイルを一時ディレクトリに作成
    story_dir = tmp_path / "stories"
    story_dir.mkdir()
    
    dummy_story = {
        "ux_story": "O-2",
        "scenes": [
            {"id": "S1", "text": "Scene 1", "linked_items": ["item1"]}
        ]
    }
    
    story_file = story_dir / "o2_transcription.json"
    with open(story_file, "w", encoding="utf-8") as f:
        json.dump(dummy_story, f)
        
    analyzer = CorrelationAnalyzer(stories_dir=story_dir)
    
    # 正常ケース (ID正規化 O-2 -> o2)
    loaded = analyzer.load_story("O-2")
    assert loaded == dummy_story
    
    # セキュリティ: 非英数字が含まれる場合 None を返すこと
    assert analyzer.load_story("../evil") is None
    assert analyzer.load_story("o2*") is None
    
    # 存在しないストーリーID
    assert analyzer.load_story("O-99") is None


def test_analyze_with_story(tmp_path):
    story_dir = tmp_path / "stories"
    story_dir.mkdir()
    
    dummy_story = {
        "ux_story": "O-2",
        "scenes": [
            {"id": "S1", "text": "Scene 1", "linked_items": []},
            {"id": "S2", "text": "Scene 2", "linked_items": []}
        ]
    }
    with open(story_dir / "o2_transcription.json", "w", encoding="utf-8") as f:
        json.dump(dummy_story, f)
        
    analyzer = CorrelationAnalyzer(stories_dir=story_dir)
    
    items = [
        {"id": "item1", "ux_story": "O-2", "story_scene": "S1"},
        {"id": "item2", "ux_story": "O-2", "story_scene": None},
        {"id": "item3", "ux_story": "O-3", "story_scene": "S1"} # 別のID
    ]
    
    res = analyzer.analyze("O-2", items)
    assert res.ux_story == "O-2"
    assert res.total_items == 2 # item1, item2 が対象
    assert res.correlated_items == 1 # item1
    assert res.uncorrelated_items == 1 # item2
    assert res.correlation_rate == 50.0
    assert res.total_scenes == 2
    assert res.covered_scenes == 1
    assert res.scene_coverage == 50.0
    assert res.uncovered_scene_ids == ["S2"]
    assert res.uncorrelated_item_ids == ["item2"]


def test_analyze_zero_items(tmp_path):
    analyzer = CorrelationAnalyzer(stories_dir=tmp_path)
    res = analyzer.analyze("O-2", [])
    assert res.total_items == 0
    assert res.correlation_rate == 0.0
    assert res.scene_coverage == 0.0


def test_analyze_all(tmp_path):
    story_dir = tmp_path / "stories"
    story_dir.mkdir()
    
    # ダミーファイルを2つ作成
    with open(story_dir / "o2_transcription.json", "w", encoding="utf-8") as f:
        json.dump({"scenes": []}, f)
    with open(story_dir / "o3_transcription.json", "w", encoding="utf-8") as f:
        json.dump({"scenes": []}, f)
        
    analyzer = CorrelationAnalyzer(stories_dir=story_dir)
    items = [
        {"id": "item1", "ux_story": "O-2", "story_scene": "S1"},
        {"id": "item2", "ux_story": "O-3", "story_scene": "S1"}
    ]
    
    results = analyzer.analyze_all(items)
    assert "O-2" in results
    assert "O-3" in results


def test_validate_minimum_correlation(tmp_path):
    story_dir = tmp_path / "stories"
    story_dir.mkdir()
    with open(story_dir / "o2_transcription.json", "w", encoding="utf-8") as f:
        json.dump({"scenes": []}, f)
    with open(story_dir / "o3_transcription.json", "w", encoding="utf-8") as f:
        json.dump({"scenes": []}, f)
        
    analyzer = CorrelationAnalyzer(stories_dir=story_dir)
    
    # すべて合格するケース (連動率 100%)
    items_pass = [
        {"id": "item1", "ux_story": "O-2", "story_scene": "S1"},
        {"id": "item2", "ux_story": "O-3", "story_scene": "S1"}
    ]
    passed, violations = analyzer.validate_minimum_correlation(items_pass, minimum=85.0)
    assert passed is True
    assert len(violations) == 0
    
    # 違反が発生するケース
    items_fail = [
        {"id": "item1", "ux_story": "O-2", "story_scene": "S1"},
        {"id": "item2", "ux_story": "O-3", "story_scene": None} # 連動率 0%
    ]
    passed, violations = analyzer.validate_minimum_correlation(items_fail, minimum=85.0)
    assert passed is False
    assert len(violations) == 1
    assert "O-3" in violations[0]
