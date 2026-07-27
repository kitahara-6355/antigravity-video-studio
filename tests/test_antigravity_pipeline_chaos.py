import sys
from unittest.mock import MagicMock

# インポートハングの防止（モジュールロード時のGemini初期化をバイパス）
#
# 2026-07-25: 差し替えたまま復元していなかったため、このモジュールが収集された
# 時点以降、他テストから見える model_registry.get_model が MagicMock のままになり、
# backend/tests/test_fitness_functions.py の FF9（registry と governance の
# 委譲一致検証）が全体実行時のみ失敗していた。
# 対象の import が終わった時点で sys.modules を元に戻す。
_MOCKED_FOR_IMPORT = ("gemini_client_factory", "model_registry")
_saved_modules = {name: sys.modules.get(name) for name in _MOCKED_FOR_IMPORT}

sys.modules["gemini_client_factory"] = MagicMock()
sys.modules["gemini_client_factory"].get_gemini_client.return_value = None
sys.modules["model_registry"] = MagicMock()
sys.modules["model_registry"].get_model.return_value = MagicMock()

import pytest
from pathlib import Path
from unittest.mock import patch

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.antigravity_pipeline import AntigravityPipeline

# import が完了したのでモックを撤去する。対象モジュールが import 時に束縛した
# 参照はそのまま残るため、このモジュールのテスト自体は影響を受けない。
for _name, _original in _saved_modules.items():
    if _original is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _original
del _saved_modules, _MOCKED_FOR_IMPORT


@pytest.fixture(autouse=True)
def _mock_heavy_modules_during_tests():
    """このモジュールのテスト実行中だけ重量モジュールをモックする。

    pytest は全モジュールを収集（import）してから実行するため、モジュール
    レベルで sys.modules を差し替えたままにすると、他ファイルのテストにも
    そのモックが見えてしまう（FF9 の失敗原因だった）。
    そのため import 直後に撤去し、実行時はこの fixture で再適用する。
    patch.dict は終了時に自動で元へ戻すので汚染は残らない。
    """
    factory = MagicMock()
    factory.get_gemini_client.return_value = None
    registry = MagicMock()
    registry.get_model.return_value = MagicMock()
    with patch.dict(sys.modules, {
        "gemini_client_factory": factory,
        "model_registry": registry,
    }):
        yield

# テスト用のSRTデータ
MOCK_SRT_CONTENT = """1
00:00:01,000 --> 00:00:05,000
こんにちは、北原美麗です。

2
00:00:06,000 --> 00:00:10,000
本日は山田太郎先生をお招きしています。
"""

@pytest.fixture
def temp_srt_file(tmp_path):
    srt_path = tmp_path / "test_input.srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(MOCK_SRT_CONTENT)
    return srt_path


@pytest.fixture(autouse=True)
def mock_external_services():
    """このテストモジュール内の全テストで外部サービスを自動的にMockする"""
    mock_store = MagicMock()
    mock_store.topics = ["Topic 1"]
    mock_store.key_moments = ["Moment 1"]
    
    mock_report = MagicMock()
    mock_report.overall_score = 90
    mock_report.overall_grade = "Excellent"
    mock_report.to_dict.return_value = {"overall_score": 90}

    with patch("semantic_store.create_semantic_store", return_value=mock_store), \
         patch("telop_proposal_engine.extract_telops", return_value=[{"text": "telop"}]), \
         patch("telop_proposal_engine.propose_scenes", return_value=[{"scene": "scene"}]), \
         patch("asset_library.get_assets_for", return_value={"available": ["a"], "missing": []}), \
         patch("services.nhk_quality_scorer.NHKQualityScorer.score", return_value=mock_report), \
         patch("agents.orchestration.OrchestrationHub.trigger_quality_fix", return_value="Fix triggered"):
        yield


def test_pipeline_normal_run(temp_srt_file, tmp_path):
    """正常な入力でパイプラインが最後まで実行されることをテスト"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    result = pipeline.process_srt(temp_srt_file)
    
    assert result["input"] == str(temp_srt_file)
    assert "phases" in result
    assert result["phases"]["phase_1"]["status"] == "completed"
    assert result["phases"]["phase_2"]["status"] == "completed"
    assert result["phases"]["phase_3"]["status"] == "completed"
    assert result["phases"]["phase_4"]["status"] == "completed"
    assert result["phases"]["srt_export"]["status"] == "completed"
    assert result["phases"]["proposals_export"]["status"] == "completed"
    
    # 出力ファイル確認
    assert Path(result["outputs"]["srt"]).exists()
    assert Path(result["outputs"]["proposals"]).exists()


def test_pipeline_phase_failure_fallback(temp_srt_file, tmp_path):
    """フェーズ2（Semantic分析）で例外が発生しても、他の処理が継続されることをテスト"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    # create_semantic_store で例外を発生させる
    with patch("semantic_store.create_semantic_store", side_effect=RuntimeError("Semantic database failure")):
        result = pipeline.process_srt(temp_srt_file)
        
        # フェーズ2は失敗状態
        assert result["phases"]["phase_2"]["status"] == "failed"
        assert "Semantic database failure" in result["phases"]["phase_2"]["error"]
        
        # 他のフェーズは完了していること（自己修復・フォールバック）
        assert result["phases"]["phase_1"]["status"] == "completed"
        assert result["phases"]["phase_3"]["status"] == "completed"
        assert result["phases"]["srt_export"]["status"] == "completed"
        assert Path(result["outputs"]["srt"]).exists()


def test_pipeline_fatal_error(tmp_path):
    """ファイルが存在しない場合の致命的エラーハンドリング"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    non_existent = tmp_path / "does_not_exist.srt"
    
    with pytest.raises(FileNotFoundError):
        pipeline.process_srt(non_existent)


def test_pipeline_status_robustness():
    """get_pipeline_status で依存モジュールがエラーを投げても、堅牢にデフォルト値を返すことをテスト"""
    pipeline = AntigravityPipeline()
    from proper_noun_dict import proper_noun_dict
    from asset_library import asset_library
    from learning_loop import learning_loop
    
    mock_assets = MagicMock()
    mock_assets.__len__.side_effect = OSError("Asset index missing")
    
    with patch.object(proper_noun_dict, "get_all_entries", side_effect=OSError("Database locked")), \
         patch.object(asset_library, "assets", mock_assets), \
         patch.object(learning_loop, "get_pending_proposals", side_effect=RuntimeError("Timeout")):
        
        status = pipeline.get_pipeline_status()
        
        # 例外が発生した項目は 0 にフォールバックされる
        assert status["proper_noun_entries"] == 0
        assert status["pending_confirmations"] == 0
        assert status["available_assets"] == 0
        assert status["pending_proposals"] == 0


def test_pipeline_phase_1_failure_fallback(temp_srt_file, tmp_path):
    """Phase 1 (固有表現辞書適用) で例外が発生した場合のフォールバック動作テスト"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("proper_noun_dict.apply_dictionary", side_effect=ValueError("Dictionary failure")):
        result = pipeline.process_srt(temp_srt_file)
        assert result["phases"]["phase_1"]["status"] == "failed"
        assert "Dictionary failure" in result["phases"]["phase_1"]["error"]
        assert result["phases"]["phase_2"]["status"] == "completed"


def test_pipeline_phase_3_failure_fallback(temp_srt_file, tmp_path):
    """Phase 3 (テロップ提案) で例外が発生した場合のフォールバック動作テスト"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("telop_proposal_engine.extract_telops", side_effect=RuntimeError("Telop extraction failure")):
        result = pipeline.process_srt(temp_srt_file)
        assert result["phases"]["phase_3"]["status"] == "failed"
        assert "Telop extraction failure" in result["phases"]["phase_3"]["error"]


def test_pipeline_phase_4_failure_fallback(temp_srt_file, tmp_path):
    """Phase 4 (アセット参照) で例外が発生した場合のフォールバック動作テスト"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("asset_library.get_assets_for", side_effect=RuntimeError("Asset system failure")):
        result = pipeline.process_srt(temp_srt_file)
        assert result["phases"]["phase_4"]["status"] == "failed"
        assert "Asset system failure" in result["phases"]["phase_4"]["error"]


def test_pipeline_srt_export_failure_fallback(temp_srt_file, tmp_path):
    """SRT出力で例外が発生した場合のフォールバック動作テスト"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("subtitle_normalizer.SRTExporter.export", side_effect=OSError("Export failure")):
        result = pipeline.process_srt(temp_srt_file)
        assert result["phases"]["srt_export"]["status"] == "failed"
        assert "Export failure" in result["phases"]["srt_export"]["error"]


def test_pipeline_proposals_export_failure_fallback(temp_srt_file, tmp_path):
    """提案レポート出力で例外が発生した場合のフォールバック動作テスト"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    original_open = open
    def mock_open(file, *args, **kwargs):
        if "proposals" in str(file) and (any(m in args for m in ('w', 'a', 'x')) or kwargs.get('mode', '') in ('w', 'a', 'x')):
            raise OSError("Write failure")
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open):
        result = pipeline.process_srt(temp_srt_file)
        assert result["phases"]["proposals_export"]["status"] == "failed"
        assert "Write failure" in result["phases"]["proposals_export"]["error"]


def test_parse_srt_read_error(tmp_path):
    """_parse_srt での読み込みエラー例外テスト"""
    pipeline = AntigravityPipeline()
    bad_file = tmp_path / "locked.srt"
    bad_file.write_text("dummy", encoding="utf-8")
    
    with patch("builtins.open", side_effect=IOError("Permission denied")):
        with pytest.raises(IOError) as exc_info:
            pipeline._parse_srt(bad_file)
        assert "Permission denied" in str(exc_info.value)


def test_parse_srt_corrupt_blocks(tmp_path):
    """不正なブロックを含むSRTファイルのパーステスト"""
    pipeline = AntigravityPipeline()
    corrupt_srt = tmp_path / "corrupt.srt"
    corrupt_srt.write_text("1\nnot_a_timestamp\nText\n\n2\n00:00:01,000 --> 00:00:02,000\nOK", encoding="utf-8")
    
    segments = pipeline._parse_srt(corrupt_srt)
    assert len(segments) == 1
    assert segments[0]["id"] == "seg_002"


def test_main_cli_no_args():
    """引数不足時の main 関挙動"""
    from antigravity_pipeline import main
    with patch.object(sys, "argv", ["antigravity_pipeline.py"]):
        with patch("builtins.print") as mock_print:
            main()
            mock_print.assert_called_with("使用方法: python -m backend.antigravity_pipeline <input_srt>")


def test_main_cli_file_not_found():
    """指定ファイルが存在しない場合の main 関挙動"""
    from antigravity_pipeline import main
    with patch.object(sys, "argv", ["antigravity_pipeline.py", "does_not_exist.srt"]):
        with patch("builtins.print") as mock_print:
            main()
            mock_print.assert_called_with("ファイルが見つかりません: does_not_exist.srt")


def test_main_cli_success(temp_srt_file, tmp_path):
    """正常系 main 関数の実行"""
    import runpy
    if "antigravity_pipeline" in sys.modules:
        del sys.modules["antigravity_pipeline"]
        
    with patch.object(sys, "argv", ["antigravity_pipeline.py", str(temp_srt_file)]):
        with patch("builtins.print") as mock_print:
            runpy.run_module("antigravity_pipeline", run_name="__main__")
            mock_print.assert_any_call("\n=== 処理結果 ===")


def test_pipeline_empty_srt_value_error(tmp_path):
    """空のSRTファイルを処理した際のValueErrorとPhase 1のフォールバック動作"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    empty_srt = tmp_path / "empty.srt"
    empty_srt.write_text("", encoding="utf-8")
    
    result = pipeline.process_srt(empty_srt)
    # ValueErrorが発生してPhase 1がfailedになること
    assert result["phases"]["phase_1"]["status"] == "failed"
    assert "No valid subtitle segments" in result["phases"]["phase_1"]["error"]


def test_parse_srt_file_not_found_directly():
    """_parse_srt に直接存在しないファイルを渡した場合の FileNotFoundError"""
    pipeline = AntigravityPipeline()
    with pytest.raises(FileNotFoundError):
        pipeline._parse_srt(Path("non_existent_file.srt"))


def test_parse_srt_index_value_error(tmp_path):
    """インデックスが整数でない場合の ValueError パース例外の通過検証"""
    pipeline = AntigravityPipeline()
    corrupt_srt = tmp_path / "index_corrupt.srt"
    corrupt_srt.write_text("not_an_int\n00:00:01,000 --> 00:00:02,000\nOK", encoding="utf-8")
    
    segments = pipeline._parse_srt(corrupt_srt)
    assert len(segments) == 0  # 例外がキャッチされて空リストが返る


def test_pipeline_status_pending_confirmations_error():
    """proper_noun_dict.get_pending で例外が発生した場合のステータス堅牢性"""
    pipeline = AntigravityPipeline()
    from proper_noun_dict import proper_noun_dict
    from asset_library import asset_library
    from learning_loop import learning_loop
    
    with patch.object(proper_noun_dict, "get_all_entries", return_value=[{"term": "A"}]), \
         patch.object(proper_noun_dict, "get_pending", side_effect=OSError("Pending list locked")), \
         patch.object(asset_library, "assets", []), \
         patch.object(learning_loop, "get_pending_proposals", return_value=[]):
         
        status = pipeline.get_pipeline_status()
        assert status["proper_noun_entries"] == 0
        assert status["pending_confirmations"] == 0



def test_pipeline_phase_1_fallback_reparse_failure(temp_srt_file, tmp_path):
    """Phase 1 で例外が発生し、かつフォールバック再パースでも例外が発生したケース"""
    import sys
    from backend import antigravity_pipeline
    
    kls = antigravity_pipeline.AntigravityPipeline
    pipeline = kls(output_dir=tmp_path / "output")
    
    original_parse = kls._parse_srt
    original_apply = antigravity_pipeline.apply_dictionary
    
    parse_calls = [0]
    def mock_parse(self, srt_path):
        parse_calls[0] += 1
        if parse_calls[0] == 1:
            return [{"id": "seg_001", "start": 0.0, "end": 1.0, "text": "Hello"}]
        else:
            raise ValueError("Fallback re-parse failure")
            
    def mock_apply(text):
        raise ValueError("First dict failure")
        
    kls._parse_srt = mock_parse
    antigravity_pipeline.apply_dictionary = mock_apply
    
    if "backend.antigravity_pipeline" in sys.modules:
        backend_module = sys.modules["backend.antigravity_pipeline"]
        backend_module.apply_dictionary = mock_apply
        backend_module.AntigravityPipeline._parse_srt = mock_parse
        
    try:
        result = pipeline.process_srt(temp_srt_file)
        assert result["phases"]["phase_1"]["status"] == "failed"
        assert "First dict failure" in result["phases"]["phase_1"]["error"]
        assert result["outputs"]["srt"] is None
    finally:
        kls._parse_srt = original_parse
        antigravity_pipeline.apply_dictionary = original_apply
        if "backend.antigravity_pipeline" in sys.modules:
            sys.modules["backend.antigravity_pipeline"].apply_dictionary = original_apply
            sys.modules["backend.antigravity_pipeline"].AntigravityPipeline._parse_srt = original_parse


def test_pipeline_quality_feedback_trigger_failure(temp_srt_file, tmp_path):
    """NHKスコアリングは成功するが、OrchestrationHubでのトリガーで例外が発生するケース"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("services.nhk_quality_scorer.NHKQualityScorer") as mock_scorer, \
         patch("agents.orchestration.OrchestrationHub") as mock_hub_class:
        
        mock_score_report = MagicMock()
        mock_score_report.overall_score = 80
        mock_score_report.overall_grade = "Good"
        mock_score_report.to_dict.return_value = {"overall_score": 80}
        mock_scorer.return_value.score.return_value = mock_score_report
        
        mock_hub_instance = mock_hub_class.return_value
        mock_hub_instance.trigger_quality_fix.side_effect = RuntimeError("Hub trigger error")
        
        result = pipeline.process_srt(temp_srt_file)
        assert "quality_score" in result
        assert "quality_feedback" not in result


def test_pipeline_nhk_scorer_failure(temp_srt_file, tmp_path):
    """NHKスコアラの初期化または実行自体で例外が発生するケース"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("services.nhk_quality_scorer.NHKQualityScorer", side_effect=RuntimeError("Scorer failed")):
        result = pipeline.process_srt(temp_srt_file)
        assert "quality_score" not in result


def test_pipeline_quality_feedback_trigger_success(temp_srt_file, tmp_path):
    """NHKスコアリングが成功し、OrchestrationHubでのトリガーで正常なフィードバック（真値）が返るケース"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("services.nhk_quality_scorer.NHKQualityScorer") as mock_scorer, \
         patch("agents.orchestration.OrchestrationHub") as mock_hub_class:
        
        mock_score_report = MagicMock()
        mock_score_report.overall_score = 85
        mock_score_report.overall_grade = "Excellent"
        mock_score_report.to_dict.return_value = {"overall_score": 85}
        mock_scorer.return_value.score.return_value = mock_score_report
        
        mock_hub_instance = mock_hub_class.return_value
        mock_hub_instance.trigger_quality_fix.return_value = "Quality fix task successfully triggered"
        
        result = pipeline.process_srt(temp_srt_file)
        assert "quality_score" in result
        assert result["quality_feedback"] == "Quality fix task successfully triggered"


def test_parse_srt_unicode_decode_error(tmp_path):
    """_parse_srt での文字デコードエラー例外テスト"""
    pipeline = AntigravityPipeline()
    bad_file = tmp_path / "decode_error.srt"
    bad_file.write_text("dummy", encoding="utf-8")
    
    with patch("builtins.open", side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte")):
        with pytest.raises(UnicodeDecodeError) as exc_info:
            pipeline._parse_srt(bad_file)
        assert "invalid start byte" in str(exc_info.value)


def test_parse_srt_index_error(tmp_path):
    """_parse_srt でブロックの行数が不足している（IndexError）場合のスキップテスト"""
    pipeline = AntigravityPipeline()
    corrupt_srt = tmp_path / "index_error.srt"
    corrupt_srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nOK\n\n2", encoding="utf-8")
    
    segments = pipeline._parse_srt(corrupt_srt)
    assert len(segments) == 1
    assert segments[0]["id"] == "seg_001"


def test_pipeline_phase_1_expected_vs_unexpected_exceptions(temp_srt_file, tmp_path):
    """Phase 1 で想定内の例外（ValueError）はキャッチしてフォールバックし、想定外の例外（ZeroDivisionError）は伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    # 1. 想定内の例外 (ValueError)
    with patch("proper_noun_dict.apply_dictionary", side_effect=ValueError("Expected value error")):
        result = pipeline.process_srt(temp_srt_file)
        assert result["phases"]["phase_1"]["status"] == "failed"
        assert "Expected value error" in result["phases"]["phase_1"]["error"]
        # フォールバックして処理は続行される
        assert result["phases"]["phase_2"]["status"] == "completed"

    # 2. 想定外の例外 (ZeroDivisionError) -> 握りつぶされずに raise されること
    with patch("proper_noun_dict.apply_dictionary", side_effect=ZeroDivisionError("Unexpected math error")):
        with pytest.raises(ZeroDivisionError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Unexpected math error" in str(exc_info.value)



def test_pipeline_phase_2_unexpected_exceptions(temp_srt_file, tmp_path):
    """Phase 2 で想定外の例外（TypeError）が発生した場合に伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("semantic_store.create_semantic_store", side_effect=TypeError("Unexpected type error in phase 2")):
        with pytest.raises(TypeError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Unexpected type error in phase 2" in str(exc_info.value)


def test_pipeline_phase_3_unexpected_exceptions(temp_srt_file, tmp_path):
    """Phase 3 で想定外の例外（NameError）が発生した場合に伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("telop_proposal_engine.extract_telops", side_effect=NameError("Unexpected name error in phase 3")):
        with pytest.raises(NameError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Unexpected name error in phase 3" in str(exc_info.value)


def test_pipeline_status_unexpected_exceptions():
    """get_pipeline_status で想定外の例外（AttributeError）が発生した場合に伝播することを検証"""
    pipeline = AntigravityPipeline()
    from proper_noun_dict import proper_noun_dict
    with patch.object(proper_noun_dict, "get_all_entries", side_effect=AttributeError("Unexpected attribute error")):
        with pytest.raises(AttributeError) as exc_info:
            pipeline.get_pipeline_status()
        assert "Unexpected attribute error" in str(exc_info.value)


def test_normalize_subtitles_invalid_elements(temp_srt_file, tmp_path):
    """segments内にNoneや辞書以外のデータが混ざっていても、堅牢に動作することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    # 手動で_normalize_subtitles_for_qualityに不正なデータを渡す
    bad_segments = [
        {"id": "seg_001", "start": 1.0, "end": 2.0, "text": "正常な字幕"},
        None,
        "文字列データ",
        {"id": "seg_002", "start": 3.0, "end": 4.0, "text": 12345},  # textが数値（非文字列）
        {"id": "seg_003", "start": "invalid", "end": 5.0, "text": "スタート時間異常"}
    ]
    
    normalized = pipeline._normalize_subtitles_for_quality(bad_segments)
    
    # クラッシュせずにリストが返ること
    assert isinstance(normalized, list)
    # 元の構造は維持、またはスキップされた上で安全に返る
    assert len(normalized) == 5
    assert normalized[0]["text"] == "正常な字幕"


def test_normalize_subtitles_non_list(tmp_path):
    """segmentsがリストではない場合、空リストが返されることを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    assert pipeline._normalize_subtitles_for_quality("not a list") == []
    assert pipeline._normalize_subtitles_for_quality(None) == []


def test_pipeline_with_broken_segment_data(temp_srt_file, tmp_path):
    """パースされたセグメントに異常値が含まれている場合、パイプライン全体がクラッシュせず正常に継続されることを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    # _parse_srtが壊れた辞書リストを返すようにモックする
    bad_segments = [
        {"id": "seg_001", "start": 1.0, "end": 2.0, "text": "Hello"},
        None,
        {"id": "seg_002", "start": 2.0, "end": 3.0, "text": 456}
    ]
    
    with patch.object(AntigravityPipeline, "_parse_srt", return_value=bad_segments):
        result = pipeline.process_srt(temp_srt_file)
        
        # 途中でクラッシュせず、正常にフェーズ1が完了（または例外があってもフォールバックされて全体が継続）すること
        assert "phases" in result
        assert result["phases"]["phase_1"]["status"] in ("completed", "failed")


def test_pipeline_phase_1_new_propagated_exceptions(temp_srt_file, tmp_path):
    """Phase 1 で新しく伝播対象となった例外（KeyError, IndexError, ImportError）が発生した場合に伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    # 1. KeyError
    with patch("proper_noun_dict.apply_dictionary", side_effect=KeyError("Key not found")):
        with pytest.raises(KeyError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Key not found" in str(exc_info.value)

    # 2. IndexError
    with patch("proper_noun_dict.apply_dictionary", side_effect=IndexError("Index out of range")):
        with pytest.raises(IndexError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Index out of range" in str(exc_info.value)

    # 3. ImportError
    with patch("proper_noun_dict.apply_dictionary", side_effect=ImportError("Import failed")):
        with pytest.raises(ImportError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Import failed" in str(exc_info.value)


def test_normalize_subtitles_propagates_program_errors(tmp_path):
    """_normalize_subtitles_for_quality 内で PROGRAM_ERRORS が発生した場合に、適切に例外が上に伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    # 1. ZeroDivisionError
    with patch("math.ceil", side_effect=ZeroDivisionError("Math error in ceil")):
        with pytest.raises(ZeroDivisionError) as exc_info:
            pipeline._normalize_subtitles_for_quality([{"id": "seg_001", "start": 0.0, "end": 1.0, "text": "テストテキスト"}])
        assert "Math error in ceil" in str(exc_info.value)

    # 2. TypeError
    with patch("math.ceil", side_effect=TypeError("Type error in ceil")):
        with pytest.raises(TypeError) as exc_info:
            pipeline._normalize_subtitles_for_quality([{"id": "seg_001", "start": 0.0, "end": 1.0, "text": "テストテキスト"}])
        assert "Type error in ceil" in str(exc_info.value)

    # 3. KeyError
    with patch("math.ceil", side_effect=KeyError("Key error in ceil")):
        with pytest.raises(KeyError) as exc_info:
            pipeline._normalize_subtitles_for_quality([{"id": "seg_001", "start": 0.0, "end": 1.0, "text": "テストテキスト"}])
        assert "Key error in ceil" in str(exc_info.value)

    # 4. AttributeError
    with patch("math.ceil", side_effect=AttributeError("Attribute error in ceil")):
        with pytest.raises(AttributeError) as exc_info:
            pipeline._normalize_subtitles_for_quality([{"id": "seg_001", "start": 0.0, "end": 1.0, "text": "テストテキスト"}])
        assert "Attribute error in ceil" in str(exc_info.value)


def test_normalize_subtitles_gap_safety_conflict(tmp_path):
    """タイムスタンプが極端に詰まっている競合ケースで、前の字幕との0.05秒のギャップが維持されることを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    segments = [
        {"id": "seg_001", "start": 1.0, "end": 2.0, "text": "前の字幕"},
        {"id": "seg_002", "start": 2.05, "end": 2.1, "text": "非常に長いテキストをここに入れて目標秒数を引き上げることで補正を誘発する"},
        {"id": "seg_003", "start": 2.13, "end": 3.0, "text": "次の字幕"}
    ]
    
    normalized = pipeline._normalize_subtitles_for_quality(segments)
    
    # 補正後の seg_002 の開始時間が、seg_001の終了時間(2.0) + 0.05 = 2.05 秒以上であることを確認
    assert normalized[1]["start"] >= 2.05
    # 時間の逆転が発生していないこと
    assert normalized[1]["start"] < normalized[1]["end"]
    # ギャップが維持され、終了時間が開始時間より0.05秒以上先であることを確認
    assert normalized[1]["end"] >= normalized[1]["start"] + 0.05


def test_pipeline_assertion_error_propagates(temp_srt_file, tmp_path):
    """AssertionError が発生した場合に、握りつぶされずに正しく伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    with patch("proper_noun_dict.apply_dictionary", side_effect=AssertionError("Assert fail in phase 1")):
        with pytest.raises(AssertionError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Assert fail in phase 1" in str(exc_info.value)


def test_pipeline_fatal_error_directory(tmp_path):
    """ディレクトリが指定された場合の致命的エラーハンドリング"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    dir_path = tmp_path / "sub_dir"
    dir_path.mkdir()
    
    with pytest.raises(IsADirectoryError):
        pipeline.process_srt(dir_path)


def test_pipeline_memory_error_propagates(temp_srt_file, tmp_path):
    """MemoryError が発生した場合に、握りつぶされずに正しく伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    with patch("proper_noun_dict.apply_dictionary", side_effect=MemoryError("Out of memory in phase 1")):
        with pytest.raises(MemoryError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Out of memory in phase 1" in str(exc_info.value)


def test_pipeline_system_error_propagates(temp_srt_file, tmp_path):
    """SystemError が発生した場合に、握りつぶされずに正しく伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    with patch("proper_noun_dict.apply_dictionary", side_effect=SystemError("System crash in phase 1")):
        with pytest.raises(SystemError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "System crash in phase 1" in str(exc_info.value)


def test_parse_srt_timestamp_warning(tmp_path):
    """タイムスタンプが不正な場合に警告ログが出力されることを検証"""
    pipeline = AntigravityPipeline()
    corrupt_srt = tmp_path / "timestamp_corrupt.srt"
    corrupt_srt.write_text("1\n00:00:01.000 --> 00:00:02.000\nOK", encoding="utf-8")  # カンマではなくピリオド
    
    with patch("backend.antigravity_pipeline.logger.warning") as mock_warning:
        segments = pipeline._parse_srt(corrupt_srt)
        assert len(segments) == 0
        mock_warning.assert_any_call(
            "SRT block timestamp format mismatch: %s", "00:00:01.000 --> 00:00:02.000"
        )


def test_pipeline_permission_error_propagates(temp_srt_file, tmp_path):
    """PermissionError（致命的エラー）が発生した際、適切に例外が上に伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("builtins.open", side_effect=PermissionError("Access denied")):
        with pytest.raises(PermissionError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Access denied" in str(exc_info.value)


def test_normalize_subtitles_invalid_next_start_guard(tmp_path):
    """次のセグメントの開始時間が極端に早く、max_endが開始時間を下回る場合でも、終了時間が開始時間より前にならないことを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    # 元データ: seg_002 の start=2.0, end=2.1
    # だが next_start=1.0 にモック（極端に早い開始時間）
    segments = [
        {"id": "seg_001", "start": 2.0, "end": 2.1, "text": "非常に長い字幕テキストで補正処理を誘発させます"}
    ]
    
    # 手動で next_start が極端に小さくなるよう、i < len(segments) - 1 の条件などをモックするか、
    # タイムスタンプ補正のループで、次のセグメントの開始時間を 1.0 に設定する
    segments_with_next = [
        {"id": "seg_001", "start": 2.0, "end": 2.1, "text": "非常に長い字幕テキストで補正処理を誘発させます"},
        {"id": "seg_002", "start": 1.0, "end": 1.5, "text": "後続の字幕"}  # next_start が seg_001 の開始時間より前
    ]
    
    normalized = pipeline._normalize_subtitles_for_quality(segments_with_next)
    
    # seg_001 の end が start (2.0) を下回っていないことを検証
    assert normalized[0]["end"] >= normalized[0]["start"]


def test_pipeline_unicode_decode_error_propagates(temp_srt_file, tmp_path):
    """_parse_srt で UnicodeDecodeError が発生した際、適切に例外が上に伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("builtins.open", side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte")):
        with pytest.raises(UnicodeDecodeError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "invalid start byte" in str(exc_info.value)


def test_pipeline_nhk_scorer_program_error_does_not_crash(temp_srt_file, tmp_path):
    """NHKスコアラでプログラムエラー（TypeErrorなど）が発生しても、パイプライン全体がクラッシュせず正常終了することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    with patch("services.nhk_quality_scorer.NHKQualityScorer") as mock_scorer:
        mock_scorer.return_value.score.side_effect = TypeError("Mocked program error in scorer")
        
        # 例外が伝播せず、処理結果が返ってくること
        result = pipeline.process_srt(temp_srt_file)
        assert "quality_score" not in result
        assert result["phases"]["srt_export"]["status"] == "completed"


def test_normalize_subtitles_program_error_fallback(tmp_path):
    """字幕品質補正処理で想定内の例外（RuntimeErrorなど）が発生しても、クラッシュせずに元のsegmentsを返すことを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    segments = [{"id": "seg_001", "start": 0.0, "end": 1.0, "text": "テスト"}]
    
    # math.ceilのモックでRuntimeErrorを発生させる
    with patch("math.ceil", side_effect=RuntimeError("Mocked runtime error")):
        # 例外が伝播せず、元のsegmentsがそのまま返されること
        normalized = pipeline._normalize_subtitles_for_quality(segments)
        assert normalized == segments


def test_normalize_subtitles_empty_list(tmp_path):
    """segmentsが空リストの場合に正しく空リストが返ることを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    assert pipeline._normalize_subtitles_for_quality([]) == []


def test_normalize_subtitles_empty_text(tmp_path):
    """segments内のtextが空文字列である場合に正しくスキップまたは処理されることを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    segments = [
        {"id": "seg_001", "start": 0.0, "end": 1.0, "text": ""}
    ]
    normalized = pipeline._normalize_subtitles_for_quality(segments)
    assert len(normalized) == 1
    assert normalized[0]["text"] == ""


def test_normalize_subtitles_invalid_sibling_timestamps(tmp_path):
    """前後セグメントのタイムスタンプが不正な型である場合に例外が発生せずに処理されることを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    segments = [
        {"id": "seg_001", "start": 0.0, "end": 1.0, "text": "前のテキスト"},
        {"id": "seg_002", "start": 1.05, "end": 1.1, "text": "非常に長いテキストをここに入れて目標秒数を引き上げることで補正を誘発する"},
        {"id": "seg_003", "start": 2.0, "end": 3.0, "text": "次のテキスト"}
    ]
    
    # 前後セグメントのタイムスタンプを意図的に無効な文字列に変更する
    segments[0]["end"] = "invalid_timestamp"
    segments[2]["start"] = "invalid_timestamp"
    
    normalized = pipeline._normalize_subtitles_for_quality(segments)
    
    # エラーが発生せずにリストが返ることを検証
    assert isinstance(normalized, list)
    assert len(normalized) == 3


def test_pipeline_phase_1_fallback_reparse_program_error(temp_srt_file, tmp_path):
    """Phase 1のフォールバック再パースでPROGRAM_ERRORS（ZeroDivisionError）が発生した際に伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    original_parse = AntigravityPipeline._parse_srt
    parse_calls = []
    
    def mock_parse(self, srt_path):
        if not parse_calls:
            parse_calls.append(1)
            return original_parse(self, srt_path)
        raise ZeroDivisionError("Math error in fallback re-parse")
        
    with patch("proper_noun_dict.apply_dictionary", side_effect=ValueError("Dictionary fail")), \
         patch.object(AntigravityPipeline, "_parse_srt", mock_parse):
        with pytest.raises(ZeroDivisionError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Math error in fallback re-parse" in str(exc_info.value)


def test_pipeline_phase_4_program_error(temp_srt_file, tmp_path):
    """Phase 4 で PROGRAM_ERRORS (KeyError) が発生した際に伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("asset_library.get_assets_for", side_effect=KeyError("Asset key not found")):
        with pytest.raises(KeyError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Asset key not found" in str(exc_info.value)


def test_pipeline_srt_export_program_error(temp_srt_file, tmp_path):
    """SRTエクスポートで PROGRAM_ERRORS (TypeError) が発生した際に伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("subtitle_normalizer.SRTExporter.export", side_effect=TypeError("Type error in export")):
        with pytest.raises(TypeError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Type error in export" in str(exc_info.value)


def test_pipeline_proposals_export_program_error(temp_srt_file, tmp_path):
    """提案エクスポートで PROGRAM_ERRORS (ZeroDivisionError) が発生した際に伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    original_open = open
    def mock_open(file, *args, **kwargs):
        file_str = str(file)
        if file_str.endswith("_proposals.json") or file_str.endswith(".tmp_json"):
            raise ZeroDivisionError("Math error during proposal write")
        return original_open(file, *args, **kwargs)
        
    with patch("builtins.open", side_effect=mock_open):
        with pytest.raises(ZeroDivisionError) as exc_info:
            pipeline.process_srt(temp_srt_file)
        assert "Math error during proposal write" in str(exc_info.value)


def test_pipeline_nhk_scoring_trigger_program_error(temp_srt_file, tmp_path):
    """OrchestrationHub でのトリガー時に PROGRAM_ERRORS (ZeroDivisionError) が発生した際、_run_nhk_quality_scoringが正しく例外を伝播することを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    with patch("services.nhk_quality_scorer.NHKQualityScorer") as mock_scorer:
        mock_score_report = MagicMock()
        mock_score_report.overall_score = 80
        mock_score_report.overall_grade = "Good"
        mock_score_report.to_dict.return_value = {"overall_score": 80}
        mock_scorer.return_value.score.return_value = mock_score_report
        
        # クラス全体ではなく、モック対象メソッドを patch.object で直接 side_effect 指定する
        from agents.orchestration import OrchestrationHub
        with patch.object(OrchestrationHub, "trigger_quality_fix", side_effect=ZeroDivisionError("Trigger division by zero")):
            result = {}
            with pytest.raises(ZeroDivisionError) as exc_info:
                pipeline._run_nhk_quality_scoring(temp_srt_file, result)
            assert "Trigger division by zero" in str(exc_info.value)



def test_pipeline_nhk_scoring_importerror(temp_srt_file, tmp_path):
    """services.nhk_quality_scorer モジュールのインポート時に ImportError が発生した際にクラッシュせず処理継続されることを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    with patch.dict("sys.modules", {"services.nhk_quality_scorer": None}):
        result = pipeline.process_srt(temp_srt_file)
        assert result["phases"]["srt_export"]["status"] == "completed"
        assert "quality_score" not in result


def test_pipeline_status_asset_library_program_error():
    """get_pipeline_status で asset_library から PROGRAM_ERRORS (AttributeError) が発生した際に伝播することを検証"""
    pipeline = AntigravityPipeline()
    from asset_library import asset_library
    mock_assets = MagicMock()
    mock_assets.__len__.side_effect = AttributeError("Asset library attribute error")
    
    with patch.object(asset_library, "assets", mock_assets):
        with pytest.raises(AttributeError) as exc_info:
            pipeline.get_pipeline_status()
        assert "Asset library attribute error" in str(exc_info.value)


def test_pipeline_status_learning_loop_program_error():
    """get_pipeline_status で learning_loop から PROGRAM_ERRORS (NameError) が発生した際に伝播することを検証"""
    pipeline = AntigravityPipeline()
    from learning_loop import learning_loop
    with patch.object(learning_loop, "get_pending_proposals", side_effect=NameError("Name loop error")):
        with pytest.raises(NameError) as exc_info:
            pipeline.get_pipeline_status()
        assert "Name loop error" in str(exc_info.value)


def test_normalize_subtitles_none_timestamps(tmp_path):
    """segments 内に start や end が None もしくはキー欠落している場合、正しくスキップされてクラッシュしないことを検証"""
    pipeline = AntigravityPipeline(output_dir=tmp_path / "output")
    
    segments = [
        {"id": "seg_001", "start": 0.0, "end": 1.0, "text": "正常"},
        {"id": "seg_002", "start": None, "end": 2.0, "text": "startがNone"},
        {"id": "seg_003", "start": 1.0, "end": None, "text": "endがNone"},
        {"id": "seg_004", "start": 2.0, "text": "endキー欠落"},
        {"id": "seg_005", "end": 3.0, "text": "startキー欠落"}
    ]
    
    normalized = pipeline._normalize_subtitles_for_quality(segments)
    assert len(normalized) == 5
    assert normalized[0]["text"] == "正常"








