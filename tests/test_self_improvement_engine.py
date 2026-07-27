"""
test_self_improvement_engine.py — self_improvement_engine.py の例外ハンドリング検証用ユニットテスト
"""
import pytest
import json
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

# プロジェクトルートと backend を sys.path に追加
project_root = Path(__file__).resolve().parents[1]
backend_dir = project_root / "backend"
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.self_improvement_engine import SelfImprovementEngine


def test_generate_youtube_metadata_fallback_exception_handling():
    """_generate_youtube_metadata_fallback で例外が発生した場合に、
    例外が適切にキャッチされて空の辞書が返されることを検証。
    """
    engine = SelfImprovementEngine()
    
    # generate_metadata の呼び出しで ImportError をシミュレート
    with patch("backend.self_improvement_engine.get_gemini_client") as mock_client:
        # metadata_generator のインポートや generate_metadata 実行時に例外を投げるようにモック
        with patch("sys.path", MagicMock(side_effect=ImportError("Simulated import error"))):
            result = engine._generate_youtube_metadata_fallback([])
            assert result == {}


def test_load_whisper_segments_exception_handling(tmp_path):
    """_load_whisper_segments で format_segments が例外を投げた場合に、
    例外が適切にキャッチされて整形前のセグメントが返されることを検証。
    """
    engine = SelfImprovementEngine(merged_dir=tmp_path)
    
    # テスト用の whisper キャッシュファイルを作成
    cache_file = tmp_path / "_whisper_test.jsonl"
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write('{"start": 0.0, "end": 2.0, "text": "テストセグメント"}\n')
        
    # format_segments が ValueError を投げるようにモックする
    with patch("subtitle_engine.text_formatter.format_segments", side_effect=ValueError("Simulated format error")):
        result = engine._load_whisper_segments()
        
        # 例外がキャッチされ、フォーマットされていない生セグメントが返されることを検証
        assert len(result) == 1
        assert result[0]["text"] == "テストセグメント"


def test_load_whisper_segments_malformed_line(tmp_path):
    """一部の行が壊れたJSONLファイルを読み込んだ場合に、
    壊れた行のみがスキップされて正常な行が読み込めることを検証。
    """
    engine = SelfImprovementEngine(merged_dir=tmp_path)
    
    # 2行目が壊れているJSONLファイルを作成
    cache_file = tmp_path / "_whisper_test.jsonl"
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write('{"start": 0.0, "end": 2.0, "text": "正常行1"}\n')
        f.write('{"start": 2.0, "end": 4.0, "text": "壊れた行"（不正なJSON\n')
        f.write('{"start": 4.0, "end": 6.0, "text": "正常行2"}\n')
        
    result = engine._load_whisper_segments()
    
    # 正常行1と2が読み込まれていることを検証
    assert len(result) == 2
    assert result[0]["text"] == "正常行1"
    assert result[1]["text"] == "正常行2"


def test_save_results_io_error_handling(tmp_path):
    """レポート保存時または履歴保存時に OSError や TypeError が発生した場合に、
    クラッシュせずに適切にログ出力されることを検証。
    """
    engine = SelfImprovementEngine(artifacts_dir=tmp_path)
    
    # 正常なデータ
    analysis_data = {
        "scores": {
            "total_score": 95,
            "stability": 90,
            "core": 90,
            "template": 95,
            "broadcast": 95,
            "youtube": 95
        },
        "passed": True,
        "feedback": []
    }
    
    # open が OSError を投げるようにモックする
    with patch("builtins.open", side_effect=OSError("Simulated IO error")):
        # クラッシュせずに処理が戻ってくることを確認
        engine.save_results(analysis_data)


def test_auto_remediate_unicode_decode_error(tmp_path):
    """設定ファイル読み込み時に UnicodeDecodeError が発生した場合に、
    クラッシュせずに False を返すことを検証。
    """
    engine = SelfImprovementEngine()
    
    # template_config.py 読み込み時に例外をシミュレート
    with patch("backend.self_improvement_engine.TEMPLATE_CONFIG_PATH", tmp_path / "non_existent_config.py"):
        with patch("pathlib.Path.read_text", side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "Simulated decode error")):
            result = engine.auto_remediate({
                "scores": {"total_score": 50},
                "feedback": [],
                "plugin_results": {}
            })
            assert result is False


def test_save_results_malformed_history_json(tmp_path):
    """weakness_analysis_history.jsonがリスト型ではなく辞書型など不正な形式の場合、
    save_resultsがクラッシュせずに新規履歴として処理されることを検証。
    """
    engine = SelfImprovementEngine(artifacts_dir=tmp_path)
    
    # 履歴ファイルを不正な形式（辞書）で作成
    history_file = tmp_path / "weakness_analysis_history.json"
    with open(history_file, "w", encoding="utf-8") as f:
        f.write('{"invalid_history": "not a list"}')
        
    analysis_data = {
        "scores": {
            "total_score": 95,
            "stability": 90,
            "core": 90,
            "template": 95,
            "broadcast": 95,
            "youtube": 95
        },
        "passed": True,
        "feedback": []
    }
    
    # クラッシュせずに処理が完了することを確認
    engine.save_results(analysis_data)
    
    # 履歴ファイルが正しくリスト形式で再作成され、1件登録されていることを確認
    import json
    with open(history_file, "r", encoding="utf-8") as f:
        history = json.load(f)
    assert isinstance(history, list)
    assert len(history) == 1
    assert history[0]["scores"]["total_score"] == 95


def test_analyze_weaknesses_plugin_execution_exception():
    """run_all_plugins 実行時に例外が発生した場合に、
    analyze_weaknesses がクラッシュせずに適切にキャッチし、
    _fallback_analysis にフォールバックすることを検証。
    """
    engine = SelfImprovementEngine()
    
    # run_all_plugins が ValueError を投げるようにモックする
    with patch("quality_gate_plugins.run_all_plugins", side_effect=ValueError("Simulated execution error")):
        result = engine.analyze_weaknesses([])
        
        # _fallback_analysis の結果が得られること
        assert "scores" in result
        assert result["passed"] is False


def test_run_loop_pipeline_callback_exception():
    """pipeline_callback が例外を投げた場合に、
    run_loop がクラッシュせずに False を返すことを検証。
    """
    engine = SelfImprovementEngine()
    
    # pipeline_callback が ValueError を投げるようにモックする
    def mock_callback():
        raise ValueError("Simulated pipeline callback error")
        
    result = engine.run_loop(mock_callback, max_iterations=1)
    assert result is False


def test_load_whisper_segments_no_template_config(tmp_path):
    """_load_template_config が None を返す場合でも、
    _load_whisper_segments がクラッシュせずにデフォルトの最大文字数で format_segments を適用することを検証。
    """
    engine = SelfImprovementEngine(merged_dir=tmp_path)
    
    cache_file = tmp_path / "_whisper_test.jsonl"
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write('{"start": 0.0, "end": 2.0, "text": "テストセグメント文字列"}\n')
        
    with patch.object(engine, "_load_template_config", return_value=None):
        result = engine._load_whisper_segments()
        
        # 整形処理が実行され、結果が取得できること
        assert len(result) == 1
        assert result[0]["text"] == "テストセグメント文字列"


def test_fallback_analysis_non_string_text():
    """セグメントの text が文字列型でない場合（Noneなど）に、
    _fallback_analysis がクラッシュせずに安全に処理できることを検証。
    """
    engine = SelfImprovementEngine()
    
    # text が None と数値のセグメントを作成
    segments = [
        {"start": 0.0, "end": 2.0, "text": None},
        {"start": 2.0, "end": 4.0, "text": 12345}
    ]
    
    result = engine._fallback_analysis([], segments)
    
    # クラッシュせずに結果が返ることを確認
    assert "scores" in result
    assert result["scores"]["template"] == 100  # 違反なしとみなされる（またはクラッシュしない）


def test_auto_inspect_normal_heuristic(tmp_path):
    """Vision APIが無効な場合（clientがNone）でも、ヒューリスティックに
    1行15文字を超える違反などを正しく検出し、結果が返ることを検証。
    """
    engine = SelfImprovementEngine(artifacts_dir=tmp_path, merged_dir=tmp_path)
    
    index_dir = tmp_path / "latest"
    index_dir.mkdir(parents=True)
    index_file = index_dir / "index.json"
    
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump({
            "frames": [
                {"timestamp": 1.0, "path": "frame1.jpg"},
                {"timestamp": 5.0, "path": "frame2.jpg"}
            ]
        }, f)
        
    mock_segments = [
        {"start": 0.5, "end": 2.0, "text": "この字幕は非常に長くて15文字を超えていますね"},
        {"start": 4.5, "end": 6.0, "text": "短い字幕"}
    ]
        
    with patch("backend.self_improvement_engine.get_gemini_client", return_value=None):
        with patch.object(engine, "_load_whisper_segments", return_value=mock_segments):
            results = engine.auto_inspect()
            
            assert len(results) == 2
            assert results[0]["timestamp"] == 1.0
            assert results[0]["subtitle_overlap_detected"] is True
            assert "15文字を超えています" in results[0]["improvement_suggestions"]
            
            assert results[1]["timestamp"] == 5.0
            assert results[1]["subtitle_overlap_detected"] is False


def test_auto_inspect_vision_api_normal(tmp_path):
    """Vision APIが有効な場合に、画像検品が実行され、モックのAPI応答
    が正しく解析されて結果リストに追加されることを検証。
    """
    engine = SelfImprovementEngine(artifacts_dir=tmp_path, merged_dir=tmp_path)
    
    index_dir = tmp_path / "latest"
    index_dir.mkdir(parents=True)
    index_file = index_dir / "index.json"
    
    frame_file = index_dir / "frame1.jpg"
    with open(frame_file, "wb") as f:
        f.write(b"fake image data")
        
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump({
            "frames": [
                {"timestamp": 1.0, "path": "frame1.jpg"}
            ]
        }, f)
        
    mock_segments = [
        {"start": 0.5, "end": 2.0, "text": "短い"}
    ]
        
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"subtitle_overlap_detected":false,"subtitle_layout_ok":true,"font_size_appropriate":true,"contrast_ok":true,"improvement_suggestions":""}'
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("backend.self_improvement_engine.get_gemini_client", return_value=mock_client):
        with patch("backend.model_registry.get_model", return_value="gemini-2.5-flash"):
            with patch.object(engine, "_load_whisper_segments", return_value=mock_segments):
                results = engine.auto_inspect()
                
                assert len(results) == 1
                assert results[0]["timestamp"] == 1.0
                assert results[0]["subtitle_overlap_detected"] is False
                assert results[0]["subtitle_layout_ok"] is True


def test_auto_inspect_vision_api_error_handling(tmp_path):
    """Vision API 応答の解析エラー（KeyError、OSErrorなど）が発生した際に、
    クラッシュせずにヒューリスティックによるフォールバック処理が行われることを検証。
    """
    engine = SelfImprovementEngine(artifacts_dir=tmp_path, merged_dir=tmp_path)
    
    index_dir = tmp_path / "latest"
    index_dir.mkdir(parents=True)
    index_file = index_dir / "index.json"
    
    frame_file = index_dir / "frame1.jpg"
    with open(frame_file, "wb") as f:
        f.write(b"fake image data")
        
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump({
            "frames": [
                {"timestamp": 1.0, "path": "frame1.jpg"}
            ]
        }, f)
        
    mock_segments = [
        {"start": 0.5, "end": 2.0, "text": "短い"}
    ]
        
    with patch("backend.self_improvement_engine.get_gemini_client", return_value=MagicMock()):
        with patch("backend.model_registry.get_model", side_effect=KeyError("Model not found")):
            with patch.object(engine, "_load_whisper_segments", return_value=mock_segments):
                results = engine.auto_inspect()
                
                assert len(results) == 1
                assert results[0]["timestamp"] == 1.0
                assert results[0]["subtitle_overlap_detected"] is False


def test_auto_remediate_normal(tmp_path):
    """auto_remediate が template_config.py のパラメータを正しく書き換えることを検証。
    """
    engine = SelfImprovementEngine()
    
    config_file = tmp_path / "template_config.py"
    with open(config_file, "w", encoding="utf-8") as f:
        f.write('template_config = {\n')
        f.write('    "chars_per_second": 8,\n')
        f.write('    "max_chars_per_line": 20,\n')
        f.write('    "silence_threshold": 0.5,\n')
        f.write('    "hook_window_seconds": 1,\n')
        f.write('    "target_lufs": -14\n')
        f.write('}\n')
        
    with patch("backend.self_improvement_engine.TEMPLATE_CONFIG_PATH", config_file):
        analysis = {
            "scores": {
                "total_score": 70,
            },
            "plugin_results": {
                "subtitle_speed_check": {
                    "feedback": ["字幕速度超過"]
                },
                "subtitle_line_check": {
                    "feedback": ["長い字幕行"]
                },
                "dead_air_check": {
                    "feedback": ["無音区間超過"]
                },
                "hook_strength_check": {
                    "details": {"hook_score": 30}
                },
                "loudness_check": {
                    "feedback": ["音量が小さすぎる"]
                }
            },
            "feedback": ["様々な違反が発生"]
        }
        
        result = engine.auto_remediate(analysis)
        assert result is True
        
        content = config_file.read_text(encoding="utf-8")
        assert '"chars_per_second": 4' in content
        assert '"max_chars_per_line": 15' in content or '"max_chars_per_line": 13' in content
        assert '"silence_threshold": 1.5' in content
        assert '"hook_window_seconds": 3' in content
        assert '"target_lufs": -20' in content


def test_run_loop_normal():
    """run_loop が正常にイテレーションを実行し、合格した時点で True を返すことを検証。
    """
    engine = SelfImprovementEngine()
    
    mock_callback = MagicMock(return_value=True)
    
    analysis_fail = {
        "scores": {
            "total_score": 70,
            "stability": 80,
            "core": 80,
            "template": 70,
            "broadcast": 80,
            "youtube": 80
        },
        "passed": False,
        "feedback": ["速度超過"]
    }
    analysis_pass = {
        "scores": {
            "total_score": 95,
            "stability": 95,
            "core": 95,
            "template": 95,
            "broadcast": 95,
            "youtube": 95
        },
        "passed": True,
        "feedback": []
    }
    
    with patch.object(engine, "auto_inspect", return_value=[]):
        with patch.object(engine, "analyze_weaknesses", side_effect=[analysis_fail, analysis_pass]):
            with patch.object(engine, "save_results") as mock_save:
                with patch.object(engine, "auto_remediate") as mock_remediate:
                    
                    result = engine.run_loop(mock_callback, max_iterations=3)
                    
                    assert result is True
                    assert mock_callback.call_count == 2
                    assert mock_save.call_count == 2
                    assert mock_remediate.call_count == 1


def test_analyze_weaknesses_plugin_execution_exception_logging():
    """run_all_plugins 実行時に例外が発生した場合に、
    analyze_weaknesses が例外のスタックトレースを logger.exception でログ出力することを検証。
    """
    engine = SelfImprovementEngine()
    
    with patch("quality_gate_plugins.run_all_plugins", side_effect=ValueError("Simulated execution error")):
        with patch("backend.self_improvement_engine.logger") as mock_logger:
            result = engine.analyze_weaknesses([])
            # logger.exception が呼び出されていることを検証
            mock_logger.exception.assert_called_with("❌ 品質ゲートプラグインの実行中に予期せぬエラーが発生しました")
            assert "scores" in result
            assert result["passed"] is False


def test_run_loop_pipeline_callback_exception_logging():
    """pipeline_callback が例外を投げた場合に、
    run_loop が例外のスタックトレースを logger.exception でログ出力することを検証。
    """
    engine = SelfImprovementEngine()
    
    def mock_callback():
        raise ValueError("Simulated pipeline callback error")
        
    with patch("backend.self_improvement_engine.logger") as mock_logger:
        result = engine.run_loop(mock_callback, max_iterations=1)
        assert result is False
        mock_logger.exception.assert_called_with("❌ パイプライン実行中に例外が発生しました")
