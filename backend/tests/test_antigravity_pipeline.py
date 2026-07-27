import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile
import shutil
import json
import sys

from backend.antigravity_pipeline import AntigravityPipeline, PROGRAM_ERRORS

class TestAntigravityPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.output_dir = Path(self.temp_dir) / "output"
        self.pipeline = AntigravityPipeline(output_dir=self.output_dir)
        
        # テスト用のSRTファイルを作成
        self.srt_content = """1
00:00:01,000 --> 00:00:04,000
こんにちは、世界！

2
00:00:05,000 --> 00:00:08,000
これは Antigravity パイプラインのテストです。
"""
        self.srt_path = Path(self.temp_dir) / "test.srt"
        with open(self.srt_path, "w", encoding="utf-8") as f:
            f.write(self.srt_content)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @patch("backend.antigravity_pipeline.apply_dictionary")
    @patch("backend.antigravity_pipeline.create_semantic_store")
    @patch("backend.antigravity_pipeline.extract_telops")
    @patch("backend.antigravity_pipeline.propose_scenes")
    @patch("backend.antigravity_pipeline.get_assets_for")
    @patch("backend.antigravity_pipeline.SRTExporter")
    def test_process_srt_success(self, mock_srt_exporter, mock_get_assets, mock_propose_scenes, mock_extract_telops, mock_create_store, mock_apply_dict):
        # apply_dictionary のモック設定 (文字列と変更件数を返す)
        mock_apply_dict.side_effect = lambda text: (text, [{"original": "test", "corrected": "test", "start": 0.0, "end": 1.0}])
        
        # create_semantic_store のモック設定
        mock_store = MagicMock()
        mock_store.topics = ["topic1"]
        mock_store.key_moments = ["moment1"]
        mock_create_store.return_value = mock_store
        
        # extract_telops, propose_scenes のモック設定
        mock_extract_telops.return_value = [{"text": "telop1"}]
        mock_propose_scenes.return_value = [{"scene": "scene1"}]
        
        # get_assets_for のモック設定
        mock_get_assets.return_value = {"available": ["asset1"], "missing": []}
        
        # 実行
        result = self.pipeline.process_srt(self.srt_path)
        
        # 検証
        self.assertIn("input", result)
        self.assertEqual(result["phases"]["phase_1"]["status"], "completed")
        self.assertEqual(result["phases"]["phase_2"]["status"], "completed")
        self.assertEqual(result["phases"]["phase_3"]["status"], "completed")
        self.assertEqual(result["phases"]["phase_4"]["status"], "completed")
        self.assertEqual(result["phases"]["srt_export"]["status"], "completed")
        self.assertEqual(result["phases"]["proposals_export"]["status"], "completed")

    def test_process_srt_file_not_found(self):
        nonexistent_path = Path(self.temp_dir) / "nonexistent.srt"
        with self.assertRaises(FileNotFoundError):
            self.pipeline.process_srt(nonexistent_path)

    def test_process_srt_is_directory(self):
        dir_path = Path(self.temp_dir)
        with self.assertRaises(IsADirectoryError):
            self.pipeline.process_srt(dir_path)

    @patch("backend.antigravity_pipeline.proper_noun_dict_module")
    def test_process_srt_value_error_empty_segments(self, mock_proper_dict_mod):
        # 空のSRTファイルをパースさせた場合
        empty_srt_path = Path(self.temp_dir) / "empty.srt"
        with open(empty_srt_path, "w", encoding="utf-8") as f:
            f.write("")
        
        # parse_srtが空リストを返し、ValueErrorが発生してphase_1がfailedになるのを確認
        # 正常フローではなく、フォールバックも失敗した場合は空リストが返る
        result = self.pipeline.process_srt(empty_srt_path)
        self.assertEqual(result["phases"]["phase_1"]["status"], "failed")

    @patch("backend.antigravity_pipeline.apply_dictionary")
    def test_phase1_program_error_propagation(self, mock_apply_dict):
        # TypeError(PROGRAM_ERRORSに含まれる)が発生した場合、そのままスローされる
        mock_apply_dict.side_effect = TypeError("Mock TypeError")
        with self.assertRaises(TypeError):
            self.pipeline._run_phase1_dictionary_application(self.srt_path, {})

    @patch("backend.antigravity_pipeline.apply_dictionary")
    @patch("backend.antigravity_pipeline.logger")
    def test_phase1_general_error_fallback(self, mock_logger, mock_apply_dict):
        # 一般的な例外(非PROGRAM_ERRORS、例: RuntimeError)が発生した場合、フォールバックしてパースを再試行する
        mock_apply_dict.side_effect = RuntimeError("Mock RuntimeError")
        
        result = {"phases": {}}
        # フォールバック処理で_parse_srtが実行され、結果が返る
        corrected_segments = self.pipeline._run_phase1_dictionary_application(self.srt_path, result)
        self.assertEqual(result["phases"]["phase_1"]["status"], "failed")
        self.assertTrue(len(corrected_segments) > 0)  # 再パースでセグメントが取得できる

    @patch("backend.antigravity_pipeline.apply_dictionary")
    @patch("backend.antigravity_pipeline.AntigravityPipeline._parse_srt")
    def test_phase1_fallback_failure(self, mock_parse, mock_apply_dict):
        # 最初の辞書適用でエラーになり、さらにフォールバックの再パースでもエラー(非PROGRAM_ERRORS)になった場合
        mock_apply_dict.side_effect = RuntimeError("First Error")
        mock_parse.side_effect = RuntimeError("Second Error")
        
        result = {"phases": {}}
        corrected_segments = self.pipeline._run_phase1_dictionary_application(self.srt_path, result)
        self.assertEqual(result["phases"]["phase_1"]["status"], "failed")
        self.assertEqual(corrected_segments, [])

    @patch("backend.antigravity_pipeline.create_semantic_store")
    def test_phase2_program_error_propagation(self, mock_create_store):
        mock_create_store.side_effect = NameError("Mock NameError")
        with self.assertRaises(NameError):
            self.pipeline._run_phase2_semantic_analysis([{"text": "test"}], {})

    @patch("backend.antigravity_pipeline.create_semantic_store")
    def test_phase2_general_error_fallback(self, mock_create_store):
        mock_create_store.side_effect = RuntimeError("Mock RuntimeError")
        result = {"phases": {}}
        store, path = self.pipeline._run_phase2_semantic_analysis([{"text": "test"}], result)
        self.assertIsNone(store)
        self.assertEqual(result["phases"]["phase_2"]["status"], "failed")

    @patch("backend.antigravity_pipeline.extract_telops")
    def test_phase3_program_error_propagation(self, mock_extract_telops):
        mock_extract_telops.side_effect = KeyError("Mock KeyError")
        with self.assertRaises(KeyError):
            self.pipeline._run_phase3_telop_proposal([{"text": "test"}], {})

    @patch("backend.antigravity_pipeline.extract_telops")
    def test_phase3_general_error_fallback(self, mock_extract_telops):
        mock_extract_telops.side_effect = RuntimeError("Mock RuntimeError")
        result = {"phases": {}}
        telops, scenes = self.pipeline._run_phase3_telop_proposal([{"text": "test"}], result)
        self.assertEqual(telops, [])
        self.assertEqual(scenes, [])
        self.assertEqual(result["phases"]["phase_3"]["status"], "failed")

    @patch("backend.antigravity_pipeline.get_assets_for")
    def test_phase4_program_error_propagation(self, mock_get_assets):
        mock_get_assets.side_effect = IndexError("Mock IndexError")
        with self.assertRaises(IndexError):
            self.pipeline._run_phase4_asset_reference({})

    @patch("backend.antigravity_pipeline.get_assets_for")
    def test_phase4_general_error_fallback(self, mock_get_assets):
        mock_get_assets.side_effect = RuntimeError("Mock RuntimeError")
        result = {"phases": {}}
        asset_report = self.pipeline._run_phase4_asset_reference(result)
        self.assertEqual(asset_report, {"available": [], "missing": []})
        self.assertEqual(result["phases"]["phase_4"]["status"], "failed")

    @patch("backend.antigravity_pipeline.SRTExporter.export")
    def test_export_outputs_srt_program_error_propagation(self, mock_export):
        mock_export.side_effect = FileNotFoundError("Mock FileNotFoundError")
        with self.assertRaises(FileNotFoundError):
            self.pipeline._export_outputs(self.srt_path, [{"text": "test"}], [], [], {})

    @patch("backend.antigravity_pipeline.SRTExporter.export")
    def test_export_outputs_srt_general_error_fallback(self, mock_export):
        mock_export.side_effect = RuntimeError("Mock RuntimeError")
        result = {"phases": {}}
        srt_output, proposal_path = self.pipeline._export_outputs(self.srt_path, [{"text": "test"}], [], [], result)
        self.assertIsNone(srt_output)
        self.assertEqual(result["phases"]["srt_export"]["status"], "failed")

    @patch("backend.antigravity_pipeline.SRTExporter.export")
    @patch("backend.antigravity_pipeline.open")
    def test_export_outputs_proposal_general_error_fallback(self, mock_open, mock_export):
        # SRT出力は成功、提案出力で例外(非PROGRAM_ERRORS)
        mock_open.side_effect = RuntimeError("Mock File Open Error")
        result = {"phases": {}}
        srt_output, proposal_path = self.pipeline._export_outputs(self.srt_path, [{"text": "test"}], [], [], result)
        self.assertIsNone(proposal_path)
        self.assertEqual(result["phases"]["proposals_export"]["status"], "failed")

    @patch("services.nhk_quality_scorer.NHKQualityScorer")
    @patch("agents.orchestration.OrchestrationHub")
    def test_nhk_quality_scoring_success(self, mock_hub_class, mock_scorer_class):
        mock_scorer = MagicMock()
        mock_score_report = MagicMock()
        mock_score_report.overall_score = 90
        mock_score_report.overall_grade = "A"
        mock_score_report.to_dict.return_value = {"overall_score": 90}
        mock_scorer.score.return_value = mock_score_report
        mock_scorer_class.return_value = mock_scorer

        mock_hub = MagicMock()
        mock_hub.trigger_quality_fix.return_value = "Triggered Fix"
        mock_hub_class.return_value = mock_hub

        result = {}
        self.pipeline._run_nhk_quality_scoring(self.srt_path, result)
        
        self.assertEqual(result["quality_score"], {"overall_score": 90})
        self.assertEqual(result["quality_feedback"], "Triggered Fix")

    @patch("services.nhk_quality_scorer.NHKQualityScorer")
    def test_nhk_quality_scoring_import_error(self, mock_scorer_class):
        mock_scorer_class.side_effect = ImportError("Mock ImportError")
        result = {}
        # 例外はキャッチされ警告ログのみで、スローされない
        self.pipeline._run_nhk_quality_scoring(self.srt_path, result)
        self.assertNotIn("quality_score", result)

    @patch("services.nhk_quality_scorer.NHKQualityScorer")
    def test_nhk_quality_scoring_general_error(self, mock_scorer_class):
        mock_scorer_class.side_effect = RuntimeError("Mock RuntimeError")
        result = {}
        # 例外はキャッチされ警告ログのみで、スローされない
        self.pipeline._run_nhk_quality_scoring(self.srt_path, result)
        self.assertNotIn("quality_score", result)

    def test_parse_srt_file_not_found(self):
        nonexistent_path = Path(self.temp_dir) / "nonexistent.srt"
        with self.assertRaises(FileNotFoundError):
            self.pipeline._parse_srt(nonexistent_path)

    def test_parse_srt_format_mismatch(self):
        # タイムスタンプフォーマットが違う場合のスキップテスト
        mismatch_content = """1
invalid timestamp format
こんにちは
"""
        mismatch_path = Path(self.temp_dir) / "mismatch.srt"
        with open(mismatch_path, "w", encoding="utf-8") as f:
            f.write(mismatch_content)
        
        segments = self.pipeline._parse_srt(mismatch_path)
        self.assertEqual(segments, [])

    @patch("backend.antigravity_pipeline.proper_noun_dict")
    @patch("backend.antigravity_pipeline.asset_library")
    @patch("backend.antigravity_pipeline.learning_loop")
    def test_get_pipeline_status_success(self, mock_learning_loop, mock_asset_library, mock_proper_dict):
        mock_proper_dict.get_all_entries.return_value = ["entry1", "entry2"]
        mock_proper_dict.get_pending.return_value = ["pending1"]
        mock_asset_library.assets = ["asset1", "asset2", "asset3"]
        mock_learning_loop.get_pending_proposals.return_value = ["prop1"]

        status = self.pipeline.get_pipeline_status()
        self.assertEqual(status["proper_noun_entries"], 2)
        self.assertEqual(status["pending_confirmations"], 1)
        self.assertEqual(status["available_assets"], 3)
        self.assertEqual(status["pending_proposals"], 1)

    @patch("backend.antigravity_pipeline.proper_noun_dict")
    @patch("backend.antigravity_pipeline.asset_library")
    @patch("backend.antigravity_pipeline.learning_loop")
    def test_get_pipeline_status_errors(self, mock_learning_loop, mock_asset_library, mock_proper_dict):
        # 各呼び出しで一般例外が発生したときのフォールバック (0を返す)
        mock_proper_dict.get_all_entries.side_effect = RuntimeError("dict error")
        mock_asset_library.assets = property(lambda self: (_ for _ in ()).throw(RuntimeError("asset error")))
        # プロパティのモック
        type(mock_asset_library).assets = property(lambda self: exec('raise RuntimeError("asset error")'))
        mock_learning_loop.get_pending_proposals.side_effect = RuntimeError("loop error")

        status = self.pipeline.get_pipeline_status()
        self.assertEqual(status["proper_noun_entries"], 0)
        self.assertEqual(status["pending_confirmations"], 0)
        self.assertEqual(status["available_assets"], 0)
        self.assertEqual(status["pending_proposals"], 0)

    def test_normalize_subtitles_for_quality_basic(self):
        # 1行15文字の制限補正テスト
        segments = [{
            "id": "seg_001",
            "start": 1.0,
            "end": 2.0,
            "text": "これはとても長い文章であり十五文字を超えていますので改行されるはずです。"
        }]
        normalized = self.pipeline._normalize_subtitles_for_quality(segments)
        lines = normalized[0]["text"].split("\n")
        for line in lines:
            self.assertTrue(len(line) <= 15)

    def test_normalize_subtitles_for_quality_duration_extension(self):
        # 表示時間が短すぎる場合に延長するテスト (1秒未満で10文字)
        segments = [
            {
                "id": "seg_001",
                "start": 1.0,
                "end": 1.5,  # 0.5s duration
                "text": "短いテキスト"  # 6 chars. target_duration = 6/4.2 = 1.42s
            },
            {
                "id": "seg_002",
                "start": 5.0,  # 十分に離れている
                "end": 5.5,
                "text": "次のテキスト"
            }
        ]
        normalized = self.pipeline._normalize_subtitles_for_quality(segments)
        self.assertGreater(normalized[0]["end"], 1.5)

    def test_normalize_subtitles_for_quality_invalid_input(self):
        # リストでない場合のハンドリング
        self.assertEqual(self.pipeline._normalize_subtitles_for_quality("not a list"), [])
        self.assertEqual(self.pipeline._normalize_subtitles_for_quality([]), [])

    @patch("backend.antigravity_pipeline.AntigravityPipeline")
    @patch("sys.argv", ["antigravity_pipeline.py"])
    @patch("builtins.print")
    def test_main_no_args(self, mock_print, mock_pipeline):
        from backend.antigravity_pipeline import main
        main()
        mock_print.assert_called_with("使用方法: python -m backend.antigravity_pipeline <input_srt>")

    @patch("backend.antigravity_pipeline.AntigravityPipeline")
    @patch("sys.argv", ["antigravity_pipeline.py", "nonexistent.srt"])
    @patch("builtins.print")
    def test_main_file_not_found(self, mock_print, mock_pipeline):
        from backend.antigravity_pipeline import main
        # Path.exists() が False になるように argv のパスが存在しないことをテスト
        main()
        mock_print.assert_called_with("ファイルが見つかりません: nonexistent.srt")

    @patch("backend.antigravity_pipeline.AntigravityPipeline")
    @patch("builtins.print")
    def test_main_success(self, mock_print, mock_pipeline):
        mock_inst = MagicMock()
        mock_inst.process_srt.return_value = {"status": "success"}
        mock_pipeline.return_value = mock_inst
        
        # 存在するファイルへのパスを指定
        with patch("sys.argv", ["antigravity_pipeline.py", str(self.srt_path)]):
            from backend.antigravity_pipeline import main
            main()
            mock_inst.process_srt.assert_called_once()

    @patch("backend.antigravity_pipeline.proper_noun_dict_module.apply_dictionary")
    @patch("backend.antigravity_pipeline.semantic_store_module.create_semantic_store")
    @patch("backend.antigravity_pipeline.telop_proposal_engine.extract_telops")
    @patch("backend.antigravity_pipeline.telop_proposal_engine.propose_scenes")
    @patch("backend.antigravity_pipeline.asset_lib.get_assets_for")
    def test_wrapper_functions(self, mock_get_assets, mock_propose, mock_extract, mock_create, mock_apply):
        from backend.antigravity_pipeline import apply_dictionary, create_semantic_store, extract_telops, propose_scenes, get_assets_for
        
        apply_dictionary("test")
        mock_apply.assert_called_once_with("test")
        
        create_semantic_store([], "path")
        mock_create.assert_called_once_with([], "path")
        
        extract_telops([])
        mock_extract.assert_called_once_with([])
        
        propose_scenes([])
        mock_propose.assert_called_once_with([])
        
        get_assets_for("test")
        mock_get_assets.assert_called_once_with("test")

    @patch("backend.antigravity_pipeline.AntigravityPipeline._run_nhk_quality_scoring")
    @patch("backend.antigravity_pipeline.apply_dictionary")
    @patch("backend.antigravity_pipeline.create_semantic_store")
    @patch("backend.antigravity_pipeline.extract_telops")
    @patch("backend.antigravity_pipeline.propose_scenes")
    @patch("backend.antigravity_pipeline.get_assets_for")
    @patch("backend.antigravity_pipeline.SRTExporter")
    def test_process_srt_nhk_scoring_error(self, mock_srt_exporter, mock_get_assets, mock_propose_scenes, mock_extract_telops, mock_create_store, mock_apply_dict, mock_nhk_scoring):
        mock_apply_dict.side_effect = lambda text: (text, [])
        mock_nhk_scoring.side_effect = RuntimeError("Mock Scoring Error")
        
        # 必要なモックの戻り値を設定
        mock_store = MagicMock()
        mock_store.topics = ["topic1"]
        mock_store.key_moments = ["moment1"]
        mock_create_store.return_value = mock_store
        mock_extract_telops.return_value = [{"text": "telop1"}]
        mock_propose_scenes.return_value = [{"scene": "scene1"}]
        mock_get_assets.return_value = {"available": ["asset1"], "missing": []}
        
        result = self.pipeline.process_srt(self.srt_path)
        self.assertIn("input", result)

    @patch("backend.antigravity_pipeline.AntigravityPipeline._parse_srt")
    def test_phase1_invalid_segment_format(self, mock_parse):
        mock_parse.return_value = ["not_a_dict", {"text": 123}, {"text": "valid"}]
        
        result = {"phases": {}}
        with patch("backend.antigravity_pipeline.apply_dictionary") as mock_apply:
            mock_apply.side_effect = lambda text: (text, [])
            segments = self.pipeline._run_phase1_dictionary_application(self.srt_path, result)
            self.assertEqual(len(segments), 1)
            self.assertEqual(segments[0]["text"], "valid")

    @patch("backend.antigravity_pipeline.apply_dictionary")
    @patch("backend.antigravity_pipeline.AntigravityPipeline._parse_srt")
    def test_phase1_fallback_program_error(self, mock_parse, mock_apply_dict):
        mock_apply_dict.side_effect = RuntimeError("First Error")
        # 1回目の_parse_srt呼び出しは正常なセグメントを返し、
        # フォールバックの2回目で TypeError (PROGRAM_ERRORS) を発生させる
        mock_parse.side_effect = [[{"text": "test"}], TypeError("Fallback TypeError")]
        
        result = {"phases": {}}
        with self.assertRaises(TypeError):
            self.pipeline._run_phase1_dictionary_application(self.srt_path, result)

    @patch("backend.antigravity_pipeline.SRTExporter.export")
    def test_export_outputs_existing_files(self, mock_export):
        srt_output_dir = self.output_dir / "subtitles"
        srt_output_dir.mkdir(parents=True, exist_ok=True)
        srt_output = srt_output_dir / f"{self.srt_path.stem}_processed.srt"
        srt_output.write_text("existing", encoding="utf-8")
        
        def side_effect(segments, path):
            Path(path).write_text("temp content", encoding="utf-8")
        mock_export.side_effect = side_effect
        
        proposal_dir = self.output_dir / "proposals"
        proposal_dir.mkdir(parents=True, exist_ok=True)
        proposal_path = proposal_dir / f"{self.srt_path.stem}_proposals.json"
        proposal_path.write_text("existing", encoding="utf-8")
        
        result = {"phases": {}}
        out_srt, out_prop = self.pipeline._export_outputs(
            self.srt_path, [{"text": "test"}], [], [], result
        )
        
        self.assertEqual(out_srt, srt_output)
        self.assertEqual(out_prop, proposal_path)
        self.assertTrue(srt_output.exists())
        self.assertTrue(proposal_path.exists())
        with open(srt_output, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "temp content")

    @patch("backend.antigravity_pipeline.SRTExporter.export")
    @patch("backend.antigravity_pipeline.json.dump")
    def test_export_outputs_proposal_program_error(self, mock_dump, mock_export):
        mock_dump.side_effect = TypeError("Dump TypeError")
        with self.assertRaises(TypeError):
            self.pipeline._export_outputs(self.srt_path, [{"text": "test"}], [], [], {"phases": {}})

    @patch("services.nhk_quality_scorer.NHKQualityScorer")
    @patch("agents.orchestration.OrchestrationHub")
    def test_nhk_quality_scoring_hub_errors(self, mock_hub_class, mock_scorer_class):
        mock_scorer = MagicMock()
        mock_score_report = MagicMock()
        mock_score_report.to_dict.return_value = {"overall_score": 50}
        mock_scorer.score.return_value = mock_score_report
        mock_scorer_class.return_value = mock_scorer
        
        mock_hub = MagicMock()
        mock_hub.trigger_quality_fix.side_effect = RuntimeError("Hub RuntimeError")
        mock_hub_class.return_value = mock_hub
        
        result = {}
        self.pipeline._run_nhk_quality_scoring(self.srt_path, result)
        self.assertEqual(result["quality_score"], {"overall_score": 50})
        self.assertNotIn("quality_feedback", result)
        
        mock_hub.trigger_quality_fix.side_effect = TypeError("Hub TypeError")
        with self.assertRaises(TypeError):
            self.pipeline._run_nhk_quality_scoring(self.srt_path, result)
            
        mock_scorer.score.side_effect = TypeError("Scorer TypeError")
        with self.assertRaises(TypeError):
            self.pipeline._run_nhk_quality_scoring(self.srt_path, result)

    @patch("builtins.open")
    def test_parse_srt_read_error(self, mock_open):
        mock_open.side_effect = OSError("Mock Read Error")
        with self.assertRaises(OSError):
            self.pipeline._parse_srt(self.srt_path)

    def test_parse_srt_corrupt_block(self):
        corrupt_content = "not_an_int\n00:00:01,000 --> 00:00:04,000\nこんにちは\n"
        corrupt_path = Path(self.temp_dir) / "corrupt.srt"
        with open(corrupt_path, "w", encoding="utf-8") as f:
            f.write(corrupt_content)
        
        segments = self.pipeline._parse_srt(corrupt_path)
        self.assertEqual(segments, [])

    @patch("backend.antigravity_pipeline.proper_noun_dict")
    def test_get_pipeline_status_program_errors(self, mock_proper_dict):
        mock_proper_dict.get_all_entries.side_effect = TypeError("Dict TypeError")
        with self.assertRaises(TypeError):
            self.pipeline.get_pipeline_status()
            
        mock_proper_dict.get_all_entries.side_effect = None
        mock_proper_dict.get_all_entries.return_value = []
        mock_proper_dict.get_pending.return_value = []
        
        with patch("backend.antigravity_pipeline.asset_library") as mock_asset_lib:
            type(mock_asset_lib).assets = property(lambda self: exec('raise TypeError("Asset TypeError")'))
            with self.assertRaises(TypeError):
                self.pipeline.get_pipeline_status()
                
        with patch("backend.antigravity_pipeline.learning_loop") as mock_loop:
            mock_loop.get_pending_proposals.side_effect = TypeError("Loop TypeError")
            with self.assertRaises(TypeError):
                self.pipeline.get_pipeline_status()

    def test_normalize_subtitles_for_quality_validation(self):
        segments = ["not_a_dict"]
        res = self.pipeline._normalize_subtitles_for_quality(segments)
        self.assertEqual(res, ["not_a_dict"])
        
        segments = [{"text": 123}]
        res = self.pipeline._normalize_subtitles_for_quality(segments)
        self.assertEqual(res, [{"text": 123}])
        
        segments = [{"text": "", "start": 1.0, "end": 2.0}]
        res = self.pipeline._normalize_subtitles_for_quality(segments)
        self.assertEqual(res[0]["text"], "")
        
        segments = [{"text": "hello"}]
        res = self.pipeline._normalize_subtitles_for_quality(segments)
        self.assertEqual(res[0]["text"], "hello")
        
        segments = [{"text": "hello", "start": "invalid", "end": 2.0}]
        res = self.pipeline._normalize_subtitles_for_quality(segments)
        self.assertEqual(res[0]["text"], "hello")
        
        segments = [
            {"text": "hello", "start": 1.0, "end": 1.1},
            {"text": "world", "start": "invalid", "end": 3.0}
        ]
        res = self.pipeline._normalize_subtitles_for_quality(segments)
        
        segments = [
            {"text": "hello", "start": 1.0, "end": "invalid"},
            {"text": "world", "start": 2.0, "end": 2.1}
        ]
        res = self.pipeline._normalize_subtitles_for_quality(segments)
        
        class BadStr(str):
            def replace(self, *args, **kwargs):
                raise RuntimeError("Bad Str RuntimeError")
        
        segments = [{"text": BadStr("test"), "start": 1.0, "end": 2.0}]
        res = self.pipeline._normalize_subtitles_for_quality(segments)
        self.assertEqual(res, segments)
        
        class BadList(list):
            def __iter__(self):
                raise TypeError("Bad List TypeError")
        
        segments = BadList([{"text": "test"}])
        with self.assertRaises(TypeError):
            self.pipeline._normalize_subtitles_for_quality(segments)

    def test_main_as_run_module(self):
        import runpy
        with patch("sys.argv", ["antigravity_pipeline.py"]), patch("builtins.print") as mock_print:
            runpy.run_module("backend.antigravity_pipeline", run_name="__main__")
            mock_print.assert_called_with("使用方法: python -m backend.antigravity_pipeline <input_srt>")

