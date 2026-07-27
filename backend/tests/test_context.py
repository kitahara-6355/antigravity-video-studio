import json
import logging
from pathlib import Path
import pytest
from core.context import ProductionContext, ProductionPhase

def test_context_serialization_symmetry(tmp_path):
    # 正常系シリアライズ/デシリアライズのテスト
    ctx = ProductionContext(
        task_id="task_123",
        video_paths=["/path/to/video1.mp4", "/path/to/video2.mp4"],
        mood="vibrant",
        output_name="custom_output",
        output_dir=tmp_path / "custom_out"
    )
    ctx.phase = ProductionPhase.GENERATION
    ctx.progress = 0.75
    ctx.current_step = "レンダリング中"
    ctx.output_path = "/path/to/output.mp4"
    ctx.preview_url = "http://localhost/preview"
    ctx.quality_score = 9.5
    ctx.set_extension("custom_key", {"nested": "value"})

    # シリアライズ
    serialized = ctx.to_dict()
    assert serialized["task_id"] == "task_123"
    assert serialized["video_paths"] == ["/path/to/video1.mp4", "/path/to/video2.mp4"]
    assert serialized["mood"] == "vibrant"
    assert serialized["output_name"] == "custom_output"
    assert serialized["phase"] == "generation"
    assert serialized["progress"] == 0.75
    assert serialized["current_step"] == "レンダリング中"
    assert serialized["output_path"] == "/path/to/output.mp4"
    assert serialized["preview_url"] == "http://localhost/preview"
    assert serialized["quality_score"] == 9.5
    assert serialized["extensions"]["custom_key"] == {"nested": "value"}
    assert serialized["output_dir"] == str(tmp_path / "custom_out")

    # デシリアライズ
    deserialized = ProductionContext.from_dict(serialized)
    assert deserialized.task_id == ctx.task_id
    assert deserialized.video_paths == ctx.video_paths
    assert deserialized.mood == ctx.mood
    assert deserialized.output_name == ctx.output_name
    assert deserialized.phase == ctx.phase
    assert deserialized.progress == ctx.progress
    assert deserialized.current_step == ctx.current_step
    assert deserialized.output_path == ctx.output_path
    assert deserialized.preview_url == ctx.preview_url
    assert deserialized.quality_score == ctx.quality_score
    assert deserialized.get_extension("custom_key") == {"nested": "value"}
    assert deserialized.output_dir == ctx.output_dir

def test_context_from_dict_invalid_phase(caplog):
    # 不正なフェーズ名が指定された場合のフォールバックテスト
    invalid_data = {
        "task_id": "task_abc",
        "phase": "invalid_phase_name_123"
    }
    
    with caplog.at_level(logging.WARNING):
        ctx = ProductionContext.from_dict(invalid_data)
        
    assert ctx.phase == ProductionPhase.INITIALIZATION
    assert any("Invalid phase value" in record.message for record in caplog.records)

def test_load_design_tokens_file_not_found():
    # デザイントークンファイルが存在しない場合のハンドリングテスト
    ctx = ProductionContext(mood="elegant")
    non_existent_path = Path("non_existent_tokens_file_123.json")
    
    # 例外をキャッチして動作し続けることを検証
    ctx.load_design_tokens(tokens_path=str(non_existent_path))
    assert ctx.mood_settings == {}

def test_load_design_tokens_invalid_json(tmp_path):
    # デザイントークンファイルが破損したJSONの場合のハンドリングテスト
    ctx = ProductionContext(mood="elegant")
    invalid_json_file = tmp_path / "corrupted_tokens.json"
    with open(invalid_json_file, "w", encoding="utf-8") as f:
        f.write("{invalid_json_content}")
        
    ctx.load_design_tokens(tokens_path=str(invalid_json_file))
    assert ctx.mood_settings == {}

def test_load_design_tokens_success(tmp_path):
    # 正常なデザイントークンの読み込みテスト
    ctx = ProductionContext(mood="vibrant")
    tokens_file = tmp_path / "valid_tokens.json"
    
    dummy_constitution = {
        "design_tokens": {
            "vibrant": {
                "primary_color": "#ff0055",
                "font_family": "Outfit"
            },
            "elegant": {
                "primary_color": "#000000"
            }
        }
    }
    
    with open(tokens_file, "w", encoding="utf-8") as f:
        json.dump(dummy_constitution, f)
        
    ctx.load_design_tokens(tokens_path=str(tokens_file))
    assert ctx.mood_settings == {"primary_color": "#ff0055", "font_family": "Outfit"}


def test_has_extension():
    ctx = ProductionContext()
    assert not ctx.has_extension("my_key")
    ctx.set_extension("my_key", "my_value")
    assert ctx.has_extension("my_key")


def test_update_progress():
    ctx = ProductionContext()
    ctx.update_progress(0.5)
    assert ctx.progress == 0.5
    assert ctx.current_step == "初期化中"  # デフォルト値
    
    ctx.update_progress(0.8, "分析中")
    assert ctx.progress == 0.8
    assert ctx.current_step == "分析中"


def test_advance_phase(caplog):
    ctx = ProductionContext()
    ctx.phase = ProductionPhase.INITIALIZATION
    
    with caplog.at_level(logging.INFO):
        ctx.advance_phase(ProductionPhase.ANALYSIS)
        
    assert ctx.phase == ProductionPhase.ANALYSIS
    assert any("Phase transition: initialization -> analysis" in record.message for record in caplog.records)


def test_load_design_tokens_default_path(monkeypatch):
    import builtins
    original_open = builtins.open
    called_path = None
    
    def mock_open(file, mode="r", *args, **kwargs):
        nonlocal called_path
        path_str = str(file)
        if "constitution.json" in path_str:
            called_path = path_str
            import io
            dummy_constitution = {
                "design_tokens": {
                    "elegant": {
                        "primary_color": "#ffffff"
                    }
                }
            }
            return io.StringIO(json.dumps(dummy_constitution))
        return original_open(file, mode, *args, **kwargs)
        
    monkeypatch.setattr(builtins, "open", mock_open)
    
    ctx = ProductionContext(mood="elegant")
    ctx.load_design_tokens(tokens_path=None)
    
    assert called_path is not None
    assert "branding" in called_path
    assert "constitution.json" in called_path
    assert ctx.mood_settings == {"primary_color": "#ffffff"}


def test_context_serialization_symmetry_full():
    # 追加されたすべての解析・生成フィールドのシリアライズ対称性検証
    ctx = ProductionContext(
        subtitle_data=[{"text": "hello", "start": 0.0, "end": 1.0}],
        scene_data=[{"scene_id": 1, "duration": 5.0}],
        semantic_chunks=[{"chunk_id": "c1", "content": "chunk"}],
        hook_analysis={"hook_score": 90},
        thumbnail_candidates=["thumb1.png", "thumb2.png"],
        opening="op.mp4",
        ending="ed.mp4",
        mood_settings={"font_size": 24},
        quality_report={"issues": []}
    )
    
    serialized = ctx.to_dict()
    assert serialized["subtitle_data"] == [{"text": "hello", "start": 0.0, "end": 1.0}]
    assert serialized["scene_data"] == [{"scene_id": 1, "duration": 5.0}]
    assert serialized["semantic_chunks"] == [{"chunk_id": "c1", "content": "chunk"}]
    assert serialized["hook_analysis"] == {"hook_score": 90}
    assert serialized["thumbnail_candidates"] == ["thumb1.png", "thumb2.png"]
    assert serialized["opening"] == "op.mp4"
    assert serialized["ending"] == "ed.mp4"
    assert serialized["mood_settings"] == {"font_size": 24}
    assert serialized["quality_report"] == {"issues": []}
    
    deserialized = ProductionContext.from_dict(serialized)
    assert deserialized.subtitle_data == ctx.subtitle_data
    assert deserialized.scene_data == ctx.scene_data
    assert deserialized.semantic_chunks == ctx.semantic_chunks
    assert deserialized.hook_analysis == ctx.hook_analysis
    assert deserialized.thumbnail_candidates == ctx.thumbnail_candidates
    assert deserialized.opening == ctx.opening
    assert deserialized.ending == ctx.ending
    assert deserialized.mood_settings == ctx.mood_settings
    assert deserialized.quality_report == ctx.quality_report


def test_context_from_dict_partial_keys():
    # data にキーが一部存在しない場合のフォールバックテスト
    partial_data = {
        "task_id": "test_partial",
    }
    
    ctx = ProductionContext.from_dict(partial_data)
    assert ctx.task_id == "test_partial"
    assert ctx.video_paths == []
    assert ctx.mood == "elegant"
    assert ctx.phase == ProductionPhase.INITIALIZATION
    assert ctx.progress == 0.0
    assert ctx.current_step == ""
    assert ctx.subtitle_data is None
    assert ctx.scene_data is None
    assert ctx.thumbnail_candidates == []
    assert ctx.mood_settings == {}
    assert ctx.quality_report is None


def test_video_paths_containing_path_objects(tmp_path):
    ctx = ProductionContext(
        video_paths=[tmp_path / "video1.mp4", tmp_path / "video2.mp4"]
    )
    serialized = ctx.to_dict()
    assert serialized["video_paths"] == [str(tmp_path / "video1.mp4"), str(tmp_path / "video2.mp4")]
    
    deserialized = ProductionContext.from_dict(serialized)
    assert deserialized.video_paths == [str(tmp_path / "video1.mp4"), str(tmp_path / "video2.mp4")]


def test_from_dict_malformed_extensions():
    # extensions が dict ではない場合
    ctx = ProductionContext.from_dict({"extensions": ["not", "a", "dict"]})
    assert ctx._extensions == {}
    
    ctx2 = ProductionContext.from_dict({"extensions": None})
    assert ctx2._extensions == {}


def test_load_design_tokens_non_dict_json(tmp_path):
    # json が dict でない場合
    ctx = ProductionContext(mood="elegant")
    tokens_file = tmp_path / "list_tokens.json"
    with open(tokens_file, "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
    
    ctx.load_design_tokens(tokens_path=str(tokens_file))
    assert ctx.mood_settings == {}


def test_advance_phase_robustness():
    ctx = ProductionContext()
    
    # 文字列でのフェーズ遷移
    ctx.advance_phase("analysis")
    assert ctx.phase == ProductionPhase.ANALYSIS
    
    # 無効な文字列でのフェーズ遷移
    ctx.advance_phase("invalid_phase")
    assert ctx.phase == ProductionPhase.ANALYSIS  # 遷移しない
    
    # 無効な型でのフェーズ遷移
    ctx.advance_phase(123)
    assert ctx.phase == ProductionPhase.ANALYSIS  # 遷移しない


def test_update_progress_clamping_and_robustness():
    ctx = ProductionContext()
    
    # 正常範囲
    ctx.update_progress(0.5)
    assert ctx.progress == 0.5
    
    # クランプ（上限）
    ctx.update_progress(1.5)
    assert ctx.progress == 1.0
    
    # クランプ（下限）
    ctx.update_progress(-0.5)
    assert ctx.progress == 0.0
    
    # 文字列から float への変換
    ctx.update_progress("0.75")
    assert ctx.progress == 0.75
    
    # 無効な値
    ctx.update_progress("not_a_float")
    assert ctx.progress == 0.75  # 変わらない


def test_from_dict_non_dict_input(caplog):
    # from_dict に辞書以外の値を渡した場合のフォールバックテスト
    with caplog.at_level(logging.WARNING):
        ctx = ProductionContext.from_dict("not a dict")
    assert ctx.task_id == ""
    assert any("from_dict received non-dict data" in record.message for record in caplog.records)


def test_from_dict_video_paths_non_list():
    # video_paths がリストではなく、かつ真の値と偽の値の場合のフォールバックテスト
    ctx = ProductionContext.from_dict({"video_paths": None})
    assert ctx.video_paths == []

    ctx2 = ProductionContext.from_dict({"video_paths": "/path/to/video.mp4"})
    assert ctx2.video_paths == ["/path/to/video.mp4"]


def test_from_dict_invalid_output_dir_type(caplog):
    # output_dir に Path に変換できない不正な型が指定された場合の例外ハンドリングテスト
    with caplog.at_level(logging.WARNING):
        ctx = ProductionContext.from_dict({"output_dir": {"invalid": "type"}})
    assert ctx.output_dir == Path("output")
    assert any("Invalid output_dir" in record.message for record in caplog.records)


def test_load_design_tokens_non_dict_tokens_key(tmp_path):
    # constitution.json 内の design_tokens キーの値が辞書ではない場合のフォールバックテスト
    ctx = ProductionContext(mood="elegant")
    tokens_file = tmp_path / "invalid_design_tokens_key.json"
    dummy_constitution = {
        "design_tokens": "this is not a dict"
    }
    with open(tokens_file, "w", encoding="utf-8") as f:
        json.dump(dummy_constitution, f)
        
    ctx.load_design_tokens(tokens_path=str(tokens_file))
    assert ctx.mood_settings == {}
