import os
import sys
import json
import pytest
from pathlib import Path
from unittest import mock

# 適切なパスを追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.self_improvement_engine import (
    SelfImprovementEngine,
    QualityGateContext,
    get_gemini_client,
    PASS_TOTAL_SCORE,
    PASS_CATEGORY_SCORE,
    APIError
)

def test_get_gemini_client():
    # gemini_client_factory が存在する場合としない場合の挙動をモック
    with mock.patch("gemini_client_factory.get_gemini_client", return_value="mock_client", create=True):
        assert get_gemini_client() == "mock_client"
    
    # ImportError を再現
    with mock.patch("sys.modules", {"gemini_client_factory": None}):
        # sys.modules の一時的な操作によるインポートエラー
        with mock.patch("builtins.__import__", side_effect=ImportError):
            assert get_gemini_client() is None

def test_quality_gate_context():
    ctx = QualityGateContext(
        segments=[{"text": "hello"}],
        selected_segments=[{"text": "hello"}],
        preview_path="path/to/preview.mp4",
        metadata={"title": "test"}
    )
    assert ctx.segments == [{"text": "hello"}]
    assert ctx.selected_segments == [{"text": "hello"}]
    assert ctx.preview_path == "path/to/preview.mp4"
    assert ctx.metadata == {"title": "test"}

def test_engine_init_and_clear_cache(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    merged_dir = tmp_path / "merged"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir, merged_dir=merged_dir)
    
    assert engine.artifacts_dir == artifacts_dir
    assert engine.merged_dir == merged_dir
    assert artifacts_dir.exists()
    
    engine._cached_segments = [{"text": "cached"}]
    engine.clear_cache()
    assert engine._cached_segments is None

def test_auto_inspect_no_index(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    results = engine.auto_inspect()
    assert results == []

def test_auto_inspect_json_error(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    
    # 壊れたJSONを書き込む
    index_file.write_text("invalid json", encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    results = engine.auto_inspect()
    assert results == []

def test_auto_inspect_no_frames(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    index_file.write_text('{"frames": []}', encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    results = engine.auto_inspect()
    assert results == []

def test_auto_inspect_heuristic_violation(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    
    # Whisperキャッシュのモック
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    whisper_file = merged_dir / "_whisper_123.jsonl"
    # NHK基準の15文字を超えるセグメントを書き込む
    whisper_file.write_text('{"start": 1.0, "end": 2.0, "text": "これは１５文字を超える非常に長い字幕テストです。"}\n', encoding="utf-8")
    
    index_file = latest_dir / "index.json"
    index_file.write_text('{"frames": [{"timestamp": 1.0, "path": "frame_1.jpg"}]}', encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir, merged_dir=merged_dir)
    
    # format_segments をモックして整形処理をスキップさせる（15文字超えを維持するため）
    with mock.patch("subtitle_engine.text_formatter.format_segments", side_effect=lambda segs, **kw: segs):
        results = engine.auto_inspect()
    
    assert len(results) == 1
    assert results[0]["subtitle_overlap_detected"] is True
    assert results[0]["subtitle_layout_ok"] is False
    assert "1行が15文字を超えています" in results[0]["improvement_suggestions"]

def test_auto_inspect_vision_api_success(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    
    index_file = latest_dir / "index.json"
    index_file.write_text('{"frames": [{"timestamp": 1.0, "path": "frame_1.jpg"}]}', encoding="utf-8")
    
    frame_img = latest_dir / "frame_1.jpg"
    frame_img.write_bytes(b"dummy image data")
    
    # Whisperキャッシュは空（15文字超えなし）
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    whisper_file = merged_dir / "_whisper_123.jsonl"
    whisper_file.write_text('{"start": 1.0, "end": 2.0, "text": "短い字幕"}\n', encoding="utf-8")
    
    # Geminiクライアントのモック
    mock_client = mock.MagicMock()
    mock_response = mock.MagicMock()
    mock_response.text = '```json\n{"subtitle_overlap_detected":false,"subtitle_layout_ok":true,"font_size_appropriate":true,"contrast_ok":true,"improvement_suggestions":""}\n```'
    mock_client.models.generate_content.return_value = mock_response
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir, merged_dir=merged_dir)
    
    with mock.patch("backend.self_improvement_engine.get_gemini_client", return_value=mock_client), \
         mock.patch("backend.model_registry.get_model", return_value="gemini-2.5-flash"):
        results = engine.auto_inspect()
        
    assert len(results) == 1
    assert results[0]["subtitle_overlap_detected"] is False
    assert results[0]["timestamp"] == 1.0

def test_auto_inspect_vision_api_quota_exhausted(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    
    index_file = latest_dir / "index.json"
    index_file.write_text('{"frames": [{"timestamp": 1.0, "path": "frame_1.jpg"}]}', encoding="utf-8")
    frame_img = latest_dir / "frame_1.jpg"
    frame_img.write_bytes(b"dummy image data")
    
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    
    mock_client = mock.MagicMock()
    # 429 エラー（Quota Exhausted）を発生させる
    mock_client.models.generate_content.side_effect = APIError(429, {"message": "ResourceExhausted: 429 Queta exceeded"})
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir, merged_dir=merged_dir)
    
    with mock.patch("backend.self_improvement_engine.get_gemini_client", return_value=mock_client):
        results = engine.auto_inspect()
        
    assert engine._vision_api_exhausted is True
    # フォールバックされた結果が入る
    assert len(results) == 1
    assert results[0]["timestamp"] == 1.0

def test_analyze_weaknesses_success(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    
    # Whisperキャッシュ
    whisper_file = merged_dir / "_whisper_123.jsonl"
    whisper_file.write_text('{"start": 1.0, "end": 2.0, "text": "テスト"}\n', encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir, merged_dir=merged_dir)
    
    # youtube_metadata.json のモック
    meta_path = artifacts_dir / "youtube_metadata.json"
    meta_path.write_text('{"title": "テスト動画"}', encoding="utf-8")
    
    # run_all_plugins のモック
    mock_plugin_result = {
        "category_scores": {
            "stability": 95,
            "core": 90,
            "template": 85,
            "broadcast": 85,
            "youtube": 90,
        },
        "final_score": 90,
        "feedback": ["フィードバック1"],
        "category_report": [],
        "plugin_results": {"plugin_a": {}}
    }
    
    inspect_results = [{"timestamp": 1.0, "subtitle_overlap_detected": True, "improvement_suggestions": "被りあり"}]
    
    with mock.patch("quality_gate_plugins.run_all_plugins", return_value=mock_plugin_result):
        analysis = engine.analyze_weaknesses(inspect_results)
        
    assert analysis["scores"]["total_score"] == 75  # Vision減点15が適用される (90 - 15)
    assert analysis["vision_violations"] == 1
    assert any("字幕被り検出 - 被りあり" in f for f in analysis["feedback"])
    assert analysis["passed"] is False  # vision_violations があるため False

def test_analyze_weaknesses_fallback(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    
    whisper_file = merged_dir / "_whisper_123.jsonl"
    whisper_file.write_text('{"start": 1.0, "end": 2.0, "text": "テスト"}\n', encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir, merged_dir=merged_dir)
    
    # run_all_plugins のインポートエラーを起こす
    import builtins
    orig_import = builtins.__import__
    def mock_import(name, *args, **kwargs):
        if name == "quality_gate_plugins":
            raise ImportError("mock error")
        return orig_import(name, *args, **kwargs)
        
    with mock.patch("builtins.__import__", side_effect=mock_import):
        analysis = engine.analyze_weaknesses([])
        
    assert analysis["scores"]["total_score"] == 100
    assert analysis["passed"] is False

def test_save_results(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    analysis = {
        "scores": {
            "total_score": 85,
            "stability": 80,
            "core": 85,
            "template": 75,
            "broadcast": 85,
            "youtube": 90,
        },
        "passed": False,
        "vision_violations": 0,
        "feedback": ["テンプレート基準違反"]
    }
    
    # 履歴JSONを初期状態として作成しておく
    history_file = artifacts_dir / "weakness_analysis_history.json"
    history_file.write_text("[]", encoding="utf-8")
    
    engine.save_results(analysis)
    
    report_file = artifacts_dir / "weakness_analysis_report.md"
    assert report_file.exists()
    report_content = report_file.read_text(encoding="utf-8")
    assert "テンプレート基準違反" in report_content
    
    assert history_file.exists()
    history_content = json.loads(history_file.read_text(encoding="utf-8"))
    assert len(history_content) == 1
    assert history_content[0]["scores"]["total_score"] == 85

def test_auto_remediate_passed_no_action(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    # 総合スコアが合格ライン以上の場合は何もしない
    analysis = {
        "scores": {"total_score": 95}
    }
    
    assert engine.auto_remediate(analysis) is False

def test_auto_remediate_template_not_found(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    analysis = {
        "scores": {"total_score": 80},
        "plugin_results": {},
        "feedback": []
    }
    
    # template_config.py が見つからない
    with mock.patch("backend.self_improvement_engine.TEMPLATE_CONFIG_PATH", tmp_path / "nonexistent.py"):
        assert engine.auto_remediate(analysis) is False

def test_auto_remediate_apply_fixes(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    # ダミーの template_config.py
    config_file = tmp_path / "template_config.py"
    config_content = """
    "chars_per_second": 8.0,
    "max_chars_per_line": 20,
    "font_size_min_px": 12,
    "border_style": 1,
    "alignment": 1,
    "silence_threshold": 0.5,
    "dead_air_max_seconds": 5.0,
    "hook_window_seconds": 10,
    "target_lufs": -14
    """
    config_file.write_text(config_content, encoding="utf-8")
    
    analysis = {
        "scores": {
            "total_score": 75,
            "stability": 90,
            "core": 90,
            "template": 70,
            "broadcast": 75,
            "youtube": 80
        },
        "plugin_results": {
            "subtitle_speed_check": {"feedback": ["字幕速度超過: 8.0cps"]},
            "subtitle_line_check": {"feedback": ["長い字幕行"]},
            "dead_air_check": {"feedback": ["無音区間超過"]},
            "hook_strength_check": {"details": {"hook_score": 30}},
            "loudness_check": {"feedback": ["音量が小さすぎる"]}
        },
        "feedback": ["複数違反"]
    }
    
    with mock.patch("backend.self_improvement_engine.TEMPLATE_CONFIG_PATH", config_file):
        remediated = engine.auto_remediate(analysis)
        
    assert remediated is True
    updated_content = config_file.read_text(encoding="utf-8")
    assert '"chars_per_second": 4' in updated_content
    assert '"max_chars_per_line": 15' in updated_content  # 13に置換された後、長い字幕行で15に上書きされる
    assert '"font_size_min_px": 16' in updated_content
    assert '"border_style": 4' in updated_content
    assert '"alignment": 2' in updated_content
    assert '"silence_threshold": 1.5' in updated_content
    assert '"dead_air_max_seconds": 2.0' in updated_content
    assert '"hook_window_seconds": 3' in updated_content
    assert '"target_lufs": -20' in updated_content

def test_run_loop(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir, merged_dir=merged_dir)
    
    # モックの設定
    # auto_inspect -> []
    # analyze_weaknesses -> 最初は不合格、2回目で合格
    analysis_fail = {
        "scores": {"total_score": 75},
        "passed": False,
        "vision_violations": 0,
        "feedback": []
    }
    analysis_pass = {
        "scores": {"total_score": 95},
        "passed": True,
        "vision_violations": 0,
        "feedback": []
    }
    
    # sequenceで返すようにモック
    with mock.patch.object(engine, "auto_inspect", return_value=[]), \
         mock.patch.object(engine, "analyze_weaknesses", side_effect=[analysis_fail, analysis_pass]), \
         mock.patch.object(engine, "save_results"), \
         mock.patch.object(engine, "auto_remediate") as mock_remediate:
         
        pipeline_calls = []
        def pipeline_callback():
            pipeline_calls.append(True)
            return True
            
        success = engine.run_loop(pipeline_callback, max_iterations=3)
        
    assert success is True
    assert len(pipeline_calls) == 2
    mock_remediate.assert_called_once_with(analysis_fail)

def test_run_loop_pipeline_fail(tmp_path):
    engine = SelfImprovementEngine(artifacts_dir=tmp_path / "artifacts")
    def pipeline_callback():
        return False
        
    success = engine.run_loop(pipeline_callback, max_iterations=3)
    assert success is False


# =========================================================================
# 追加された堅牢性・ガード処理およびカバレッジ100%検証テスト
# =========================================================================

def test_engine_init_type_error():
    with pytest.raises(TypeError):
        SelfImprovementEngine(artifacts_dir=123)
    with pytest.raises(TypeError):
        SelfImprovementEngine(merged_dir=123)

def test_engine_init_mkdir_os_error(tmp_path):
    # artifacts_dir がファイルとして存在する場合、mkdirはOSErrorを投げる
    dummy_file = tmp_path / "dummy_file"
    dummy_file.write_text("dummy", encoding="utf-8")
    with pytest.raises(OSError):
        SelfImprovementEngine(artifacts_dir=dummy_file)

def test_auto_inspect_invalid_index_type(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    
    # 辞書型ではないJSON（リスト型）を書き込む
    index_file.write_text("[]", encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    results = engine.auto_inspect()
    assert results == []

def test_auto_inspect_invalid_frames_type(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    
    # framesが辞書型（不正な型）のJSONを書き込む
    index_file.write_text('{"frames": {}}', encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    results = engine.auto_inspect()
    assert results == []

def test_auto_inspect_frame_type_error(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    
    # framesの要素が辞書型ではないJSONを書き込む
    index_file.write_text('{"frames": ["invalid_frame"]}', encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    results = engine.auto_inspect()
    assert results == []

def test_auto_inspect_timestamp_conversion_error(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    
    # timestampが数値に変換できない文字列
    index_file.write_text('{"frames": [{"timestamp": "not_a_number", "path": "frame_1.jpg"}]}', encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    results = engine.auto_inspect()
    # ヒューリスティックにフォールバックして処理されるはず（timestampは0.0になる）
    assert len(results) == 1
    assert results[0]["timestamp"] == 0.0

def test_auto_inspect_vision_api_parse_error(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    index_file.write_text('{"frames": [{"timestamp": 1.0, "path": "frame_1.jpg"}]}', encoding="utf-8")
    
    frame_img = latest_dir / "frame_1.jpg"
    frame_img.write_bytes(b"dummy")
    
    mock_client = mock.MagicMock()
    mock_response = mock.MagicMock()
    # JSONではない無効な文字列を応答として設定
    mock_response.text = "invalid json response"
    mock_client.models.generate_content.return_value = mock_response
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    with mock.patch("backend.self_improvement_engine.get_gemini_client", return_value=mock_client),          mock.patch("backend.model_registry.get_model", return_value="gemini-2.5-flash"):
        results = engine.auto_inspect()
        
    # パースエラーのためフォールバックされる
    assert len(results) == 1
    assert results[0]["timestamp"] == 1.0

def test_auto_inspect_vision_api_missing_keys(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    index_file.write_text('{"frames": [{"timestamp": 1.0, "path": "frame_1.jpg"}]}', encoding="utf-8")
    
    frame_img = latest_dir / "frame_1.jpg"
    frame_img.write_bytes(b"dummy")
    
    mock_client = mock.MagicMock()
    mock_response = mock.MagicMock()
    # キーが一部足りないJSON
    mock_response.text = '{"subtitle_overlap_detected": true}'
    mock_client.models.generate_content.return_value = mock_response
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    with mock.patch("backend.self_improvement_engine.get_gemini_client", return_value=mock_client),          mock.patch("backend.model_registry.get_model", return_value="gemini-2.5-flash"):
        results = engine.auto_inspect()
        
    assert len(results) == 1
    assert results[0]["subtitle_overlap_detected"] is True
    # 欠損キーが補完されていることを確認
    assert results[0]["subtitle_layout_ok"] is True
    assert results[0]["improvement_suggestions"] == ""

def test_auto_inspect_vision_api_unexpected_exception(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    index_file.write_text('{"frames": [{"timestamp": 1.0, "path": "frame_1.jpg"}]}', encoding="utf-8")
    
    frame_img = latest_dir / "frame_1.jpg"
    frame_img.write_bytes(b"dummy")
    
    mock_client = mock.MagicMock()
    # 429以外の予期しない例外を発生させる
    mock_client.models.generate_content.side_effect = APIError(500, {"message": "Unexpected internal error"})
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    mock_debt_store = mock.MagicMock()
    
    with mock.patch("backend.self_improvement_engine.get_gemini_client", return_value=mock_client),          mock.patch("backend.model_registry.get_model", return_value="gemini-2.5-flash"),          mock.patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_debt_store):
        results = engine.auto_inspect()
        
    # TechnicalDebtStore.register_debt が呼び出されたことを確認
    mock_debt_store.register_debt.assert_called_once()
    assert len(results) == 1

def test_analyze_weaknesses_invalid_inspect_results_type(tmp_path):
    engine = SelfImprovementEngine(artifacts_dir=tmp_path / "artifacts")
    # inspect_results がリストではない場合
    mock_plugin_result = {
        "category_scores": {"stability": 90, "core": 90, "template": 90, "broadcast": 90, "youtube": 90},
        "final_score": 90,
        "feedback": [],
        "category_report": [],
        "plugin_results": {}
    }
    with mock.patch("quality_gate_plugins.run_all_plugins", return_value=mock_plugin_result), \
         mock.patch("backend.self_improvement_engine.get_gemini_client", return_value=None):
        analysis = engine.analyze_weaknesses(inspect_results=123)
    assert isinstance(analysis, dict)

def test_save_results_invalid_analysis_type(tmp_path):
    engine = SelfImprovementEngine(artifacts_dir=tmp_path / "artifacts")
    # 保存をスキップして終了する（例外が出ないことを確認）
    engine.save_results(analysis=None)
    engine.save_results(analysis={})
    engine.save_results(analysis={"scores": 123})

def test_auto_remediate_invalid_analysis_type(tmp_path):
    engine = SelfImprovementEngine(artifacts_dir=tmp_path / "artifacts")
    assert engine.auto_remediate(analysis=None) is False
    assert engine.auto_remediate(analysis={}) is False
    assert engine.auto_remediate(analysis={"scores": 123}) is False

def test_load_whisper_segments_invalid_format_line(tmp_path):
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    whisper_file = merged_dir / "_whisper_123.jsonl"
    # dictではない形式の行を書き込む
    whisper_file.write_text('[]\n"not_a_dict"\n{"start": 1.0, "end": 2.0, "text": "OK"}\n', encoding="utf-8")
    
    engine = SelfImprovementEngine(merged_dir=merged_dir)
    segments = engine._load_whisper_segments()
    assert len(segments) == 1
    assert segments[0]["text"] == "OK"

def test_load_whisper_segments_cache_hit(tmp_path):
    engine = SelfImprovementEngine(merged_dir=tmp_path / "merged")
    engine._cached_segments = [{"text": "cached"}]
    # キャッシュが存在する場合はそのまま返す
    assert engine._load_whisper_segments() == [{"text": "cached"}]

def test_save_results_feedback_empty(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    analysis = {
        "scores": {
            "total_score": 95,
            "stability": 95,
            "core": 95,
            "template": 95,
            "broadcast": 95,
            "youtube": 95
        },
        "passed": True,
        "vision_violations": 0,
        "feedback": [] # feedback が空
    }
    engine.save_results(analysis)
    report_file = artifacts_dir / "weakness_analysis_report.md"
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "弱点は検出されませんでした" in content

def test_save_results_category_low_score(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    analysis = {
        "scores": {
            "total_score": 75,
            "stability": 90,
            "core": 90,
            "template": 75,  # 合格ライン未満
            "broadcast": 75, # 合格ライン未満
            "youtube": 75    # 合格ライン未満
        },
        "passed": False,
        "vision_violations": 0,
        "feedback": ["低スコア"]
    }
    engine.save_results(analysis)
    report_file = artifacts_dir / "weakness_analysis_report.md"
    content = report_file.read_text(encoding="utf-8")
    assert "テンプレート基準: 字幕速度・フック強度・維持率の改善が必要" in content
    assert "放送品質: ラウドネス・解像度・ビットレートの調整が必要" in content
    assert "YouTube最適化: チャプター・メタデータ・CTR準備の改善が必要" in content

def test_save_results_history_decode_error(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    history_file = artifacts_dir / "weakness_analysis_history.json"
    # 壊れたJSONファイルを書き込む
    history_file.write_text("broken json", encoding="utf-8")
    
    analysis = {
        "scores": {"total_score": 90},
        "passed": True,
        "vision_violations": 0,
        "feedback": []
    }
    # 例外が内部でキャッチされ、新規履歴として書き出される
    engine.save_results(analysis)
    assert history_file.exists()

def test_auto_remediate_read_write_os_error(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    analysis = {
        "scores": {"total_score": 70},
        "plugin_results": {},
        "feedback": []
    }
    
    # 1. 存在しない設定ファイルの読み込みOSError
    with mock.patch("backend.self_improvement_engine.TEMPLATE_CONFIG_PATH", tmp_path / "nonexistent" / "config.py"):
        assert engine.auto_remediate(analysis) is False

    # 2. 書き込み時のOSError
    config_file = tmp_path / "template_config.py"
    config_file.write_text('"target_lufs": -14', encoding="utf-8")
    
    # read_textは成功するが、write_textでOSErrorを投げるようにモックする
    def mock_write_text(self, content, encoding=None):
        raise OSError("Permission denied")
        
    with mock.patch("backend.self_improvement_engine.TEMPLATE_CONFIG_PATH", config_file),          mock.patch("pathlib.Path.write_text", mock_write_text):
        analysis_with_feedback = {
            "scores": {"total_score": 70},
            "plugin_results": {
                "loudness_check": {"feedback": ["音量が小さすぎる"]}
            },
            "feedback": ["音量エラー"]
        }
        # 例外がキャッチされてFalseが返る
        assert engine.auto_remediate(analysis_with_feedback) is False

def test_auto_remediate_loudness_high(tmp_path):
    config_file = tmp_path / "template_config.py"
    config_file.write_text('"target_lufs": -14', encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=tmp_path / "artifacts")
    analysis = {
        "scores": {"total_score": 70},
        "plugin_results": {
            "loudness_check": {"feedback": ["音量が大きすぎる"]}
        },
        "feedback": ["音量大"]
    }
    
    with mock.patch("backend.self_improvement_engine.TEMPLATE_CONFIG_PATH", config_file):
        assert engine.auto_remediate(analysis) is True
    
    updated = config_file.read_text(encoding="utf-8")
    assert '"target_lufs": -24' in updated

def test_run_loop_max_iterations(tmp_path):
    engine = SelfImprovementEngine(artifacts_dir=tmp_path / "artifacts")
    
    # 常に不合格を返す
    analysis_fail = {
        "scores": {"total_score": 70},
        "passed": False,
        "vision_violations": 0,
        "feedback": []
    }
    
    with mock.patch.object(engine, "auto_inspect", return_value=[]),          mock.patch.object(engine, "analyze_weaknesses", return_value=analysis_fail),          mock.patch.object(engine, "save_results"),          mock.patch.object(engine, "auto_remediate"):
         
        success = engine.run_loop(lambda: True, max_iterations=2)
        assert success is False

def test_load_youtube_metadata_decode_error(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    meta_file = artifacts_dir / "youtube_metadata.json"
    meta_file.write_text("broken json", encoding="utf-8")
    
    # BACKEND_DIRをダミーに変更し、実環境のメタデータファイルを読み込ませないようにする
    with mock.patch("backend.self_improvement_engine.BACKEND_DIR", tmp_path / "dummy_backend"):
        # 読み込み失敗時に空の辞書が返されることを確認
        assert engine._load_youtube_metadata() == {}

def test_generate_youtube_metadata_fallback(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    mock_metadata = {"title": "fallback title", "tags": [], "chapters": []}
    mock_generate = mock.MagicMock(return_value=mock_metadata)
    
    with mock.patch("metadata_generator.generate_metadata", mock_generate),          mock.patch.object(engine, "_find_latest_preview", return_value=tmp_path / "preview.mp4"):
        res = engine._generate_youtube_metadata_fallback([])
        
    assert res["titles"] == ["fallback title"]
    assert (artifacts_dir / "youtube_metadata.json").exists()

def test_load_whisper_segments_json_decode_error(tmp_path):
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    whisper_file = merged_dir / "_whisper_123.jsonl"
    whisper_file.write_text("broken json line", encoding="utf-8")
    
    engine = SelfImprovementEngine(merged_dir=merged_dir)
    # 例外がキャッチされ、空リストが返る
    assert engine._load_whisper_segments() == []

def test_load_whisper_segments_format_segments_exception(tmp_path):
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    whisper_file = merged_dir / "_whisper_123.jsonl"
    whisper_file.write_text('{"text": "test"}\n', encoding="utf-8")
    
    engine = SelfImprovementEngine(merged_dir=merged_dir)
    
    # format_segmentsで例外を発生させる
    with mock.patch("subtitle_engine.text_formatter.format_segments", side_effect=ValueError("format error")):
        segments = engine._load_whisper_segments()
        
    # 整形前のオリジナルセグメントが返される
    assert len(segments) == 1
    assert segments[0]["text"] == "test"

def test_find_latest_preview(tmp_path):
    engine = SelfImprovementEngine(artifacts_dir=tmp_path / "artifacts")
    
    # globでヒットする場合
    preview_dir = tmp_path / "vault-outputs" / "preview"
    preview_dir.mkdir(parents=True)
    p_file = preview_dir / "preview_123.mp4"
    p_file.write_text("dummy", encoding="utf-8")
    
    with mock.patch("backend.self_improvement_engine.BASE_DIR", tmp_path):
        res = engine._find_latest_preview()
        assert res == p_file
        
    # globでヒットせず、soul_narrative_full_v1.mp4が存在する場合
    p_file.unlink()
    fallback_file = tmp_path / "soul_narrative_full_v1.mp4"
    fallback_file.write_text("dummy fallback", encoding="utf-8")
    
    with mock.patch("backend.self_improvement_engine.BASE_DIR", tmp_path):
        res = engine._find_latest_preview()
        assert res == fallback_file

def test_load_template_config_import_error():
    engine = SelfImprovementEngine()
    import builtins
    orig_import = builtins.__import__
    def mock_import(name, *args, **kwargs):
        if name == "template_config":
            raise ImportError("Import template_config failed")
        return orig_import(name, *args, **kwargs)
        
    with mock.patch("builtins.__import__", side_effect=mock_import):
        res = engine._load_template_config()
        assert res is None

def test_fallback_analysis_violations(tmp_path):
    engine = SelfImprovementEngine(merged_dir=tmp_path / "merged")
    
    segments = [
        # NHK基準違反 (15文字超)
        {"start": 1.0, "end": 2.0, "text": "これは非常に長い字幕テキストで１５文字を超えています。"},
        # YouTuber基準違反 (10秒以上の変化なし)
        {"start": 20.0, "end": 21.0, "text": "次のセグメント"}
    ]
    
    res = engine._fallback_analysis([], segments)
    assert res["scores"]["total_score"] < 100
    assert any("NHK基準違反" in f for f in res["feedback"])
    assert any("YouTuber基準違反" in f for f in res["feedback"])



def test_auto_inspect_img_name_not_str(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    index_file.write_text('{"frames": [{"timestamp": 1.0, "path": 123}]}', encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    results = engine.auto_inspect()
    assert len(results) == 1
    assert results[0]["timestamp"] == 1.0

def test_auto_inspect_vision_api_not_dict_response(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    index_file.write_text('{"frames": [{"timestamp": 1.0, "path": "frame_1.jpg"}]}', encoding="utf-8")
    
    frame_img = latest_dir / "frame_1.jpg"
    frame_img.write_bytes(b"dummy")
    
    mock_client = mock.MagicMock()
    mock_response = mock.MagicMock()
    mock_response.text = '```json\n["not", "a", "dict"]\n```'
    mock_client.models.generate_content.return_value = mock_response
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    with mock.patch("backend.self_improvement_engine.get_gemini_client", return_value=mock_client), \
         mock.patch("backend.model_registry.get_model", return_value="gemini-2.5-flash"):
        results = engine.auto_inspect()
        
    assert len(results) == 1
    assert results[0]["timestamp"] == 1.0

def test_auto_inspect_vision_api_unexpected_exception_debt_store_fails(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    index_file.write_text('{"frames": [{"timestamp": 1.0, "path": "frame_1.jpg"}]}', encoding="utf-8")
    
    frame_img = latest_dir / "frame_1.jpg"
    frame_img.write_bytes(b"dummy")
    
    mock_client = mock.MagicMock()
    mock_client.models.generate_content.side_effect = APIError(500, {"message": "Vision error"})
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    with mock.patch("backend.self_improvement_engine.get_gemini_client", return_value=mock_client), \
         mock.patch("backend.model_registry.get_model", return_value="gemini-2.5-flash"), \
         mock.patch("backend.agents.memory.technical_debt.TechnicalDebtStore", side_effect=OSError("Store failure")):
        results = engine.auto_inspect()
        
    assert len(results) == 1
    assert results[0]["timestamp"] == 1.0

def test_auto_inspect_fallback_long_subtitle(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    latest_dir = artifacts_dir / "latest"
    latest_dir.mkdir(parents=True)
    index_file = latest_dir / "index.json"
    index_file.write_text('{"frames": [{"timestamp": 1.0, "path": "frame_1.jpg"}]}', encoding="utf-8")
    
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    whisper_file = merged_dir / "_whisper_123.jsonl"
    whisper_file.write_text('{"start": 1.0, "end": 2.0, "text": "こんにちは、テスト改善を実行中。"}\n', encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir, merged_dir=merged_dir)
    
    with mock.patch("subtitle_engine.text_formatter.format_segments", side_effect=lambda segs, **kw: segs), \
         mock.patch("backend.self_improvement_engine.get_gemini_client", return_value=None):
        results = engine.auto_inspect()
        
    assert len(results) == 1
    assert results[0]["subtitle_overlap_detected"] is True
    assert results[0]["subtitle_layout_ok"] is False
    assert "1行が15文字を超えています" in results[0]["improvement_suggestions"]

def test_analyze_weaknesses_no_metadata_with_segments(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    
    whisper_file = merged_dir / "_whisper_123.jsonl"
    whisper_file.write_text('{"start": 1.0, "end": 2.0, "text": "テスト"}\n', encoding="utf-8")
    
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir, merged_dir=merged_dir)
    
    mock_plugin_result = {
        "category_scores": {"stability": 90, "core": 90, "template": 90, "broadcast": 90, "youtube": 90},
        "final_score": 90,
        "feedback": [],
        "category_report": [],
        "plugin_results": {}
    }
    
    mock_metadata = {"title": "fallback title", "tags": [], "chapters": []}
    
    with mock.patch("quality_gate_plugins.run_all_plugins", return_value=mock_plugin_result), \
         mock.patch.object(engine, "_load_youtube_metadata", return_value={}), \
         mock.patch.object(engine, "_generate_youtube_metadata_fallback", return_value=mock_metadata) as mock_fallback:
        analysis = engine.analyze_weaknesses([])
        
    mock_fallback.assert_called_once()

def test_auto_remediate_invalid_types_handled(tmp_path):
    engine = SelfImprovementEngine(artifacts_dir=tmp_path / "artifacts")
    
    analysis = {
        "scores": {"total_score": 75},
        "plugin_results": "not_a_dict",
        "feedback": "not_a_list"
    }
    
    with mock.patch("backend.self_improvement_engine.TEMPLATE_CONFIG_PATH", tmp_path / "nonexistent.py"):
        assert engine.auto_remediate(analysis) is False

def test_auto_remediate_read_os_error_actual(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    engine = SelfImprovementEngine(artifacts_dir=artifacts_dir)
    
    analysis = {
        "scores": {"total_score": 70},
        "plugin_results": {},
        "feedback": []
    }
    
    with mock.patch("backend.self_improvement_engine.TEMPLATE_CONFIG_PATH", tmp_path):
        assert engine.auto_remediate(analysis) is False

def test_generate_youtube_metadata_fallback_exception(tmp_path):
    engine = SelfImprovementEngine(artifacts_dir=tmp_path / "artifacts")
    
    with mock.patch("metadata_generator.generate_metadata", side_effect=ValueError("Generator failed")):
        res = engine._generate_youtube_metadata_fallback([])
        
    assert res == {}
