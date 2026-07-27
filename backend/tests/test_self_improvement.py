"""
test_self_improvement.py — 新自己改善サイクル（自律検品）テスト

M4.7.1 T-471-01〜05 の検証。
"""
import pytest
import os
import sys
import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

# パス設定
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from self_improvement_engine import SelfImprovementEngine


@pytest.fixture
def temp_workspace(tmp_path):
    """テスト用の一時ワークスペースディレクトリ群を作成"""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    # ダミーのプレビュー画像ディレクトリ
    inspection_dir = artifacts_dir / "full_inspection"
    inspection_dir.mkdir(parents=True, exist_ok=True)
    
    # ダミーのプレビュー画像
    (inspection_dir / "frame_0000_0.0s.jpg").write_bytes(b"dummy_image_data")
    (inspection_dir / "frame_0001_10.5s.jpg").write_bytes(b"dummy_image_data")
    
    # ダミーのindex.json
    index_data = {
        "video": "preview_test.mp4",
        "duration": 15.0,
        "total_frames": 2,
        "segment_count": 2,
        "frames": [
            {"timestamp": 0.0, "path": "frame_0000_0.0s.jpg"},
            {"timestamp": 10.5, "path": "frame_0001_10.5s.jpg"}
        ]
    }
    with open(inspection_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
        
    # ダミーのWhisperキャッシュ
    merged_dir = tmp_path / "vault-outputs" / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)
    
    whisper_data = [
        {"start": 0.0, "end": 4.5, "text": "こんにちは、山田です。今日は書道について話します。"},
        {"start": 10.5, "end": 15.0, "text": "とても長い文で、15文字制限を完全にオーバーしてしまっているダミーの字幕です。"}
    ]
    latest_whisper = merged_dir / "_whisper_test.jsonl"
    with open(latest_whisper, "w", encoding="utf-8") as f:
        for item in whisper_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    return {
        "workspace": tmp_path,
        "artifacts_dir": artifacts_dir,
        "inspection_dir": inspection_dir,
        "merged_dir": merged_dir
    }


class TestSelfImprovementCycle:
    """新自己改善サイクル（自律検品）テストクラス"""

    @patch("self_improvement_engine.get_gemini_client")
    def test_self_improvement_auto_check(self, mock_get_client, temp_workspace):
        """T-471-01: AIプレビュー自動確認の検証"""
        # Gemini Clientのモック作成
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        # Vision API のレスポンスを模倣
        mock_response = MagicMock()
        mock_response.text = """
        ```json
        {
          "subtitle_overlap_detected": true,
          "subtitle_layout_ok": false,
          "font_size_appropriate": false,
          "contrast_ok": true,
          "improvement_suggestions": "字幕サイズが大きすぎて見づらいです。半分にしてください。"
        }
        ```
        """
        mock_client.models.generate_content.return_value = mock_response

        engine = SelfImprovementEngine(
            artifacts_dir=str(temp_workspace["artifacts_dir"]),
            merged_dir=str(temp_workspace["merged_dir"])
        )
        
        results = engine.auto_inspect()
        
        assert len(results) > 0
        assert results[0]["timestamp"] == 0.0
        assert "subtitle_overlap_detected" in results[0]
        # Vision APIが呼び出されていることを確認
        assert mock_client.models.generate_content.called

    @patch("self_improvement_engine.SelfImprovementEngine._find_latest_preview")
    def test_self_improvement_weakness_analysis(self, mock_find_preview, temp_workspace):
        """T-471-02: 4大規格に基づく弱点分析の検証"""
        mock_find_preview.return_value = None
        from template_config import template_config
        template_config.set_overrides({"subtitle_rules": {"max_chars_per_line": 20}})
        try:
            engine = SelfImprovementEngine(
                artifacts_dir=str(temp_workspace["artifacts_dir"]),
                merged_dir=str(temp_workspace["merged_dir"])
            )
            
            # ダミーの検品結果を入力
            inspect_results = [
                {
                    "timestamp": 0.0,
                    "subtitle_overlap_detected": False,
                    "subtitle_layout_ok": True,
                    "font_size_appropriate": True,
                    "contrast_ok": True,
                    "improvement_suggestions": ""
                },
                {
                    "timestamp": 10.5,
                    "subtitle_overlap_detected": True,
                    "subtitle_layout_ok": False,
                    "font_size_appropriate": False,
                    "contrast_ok": False,
                    "improvement_suggestions": "字幕が中央で被っている。15文字を超えている。"
                }
            ]
            
            analysis = engine.analyze_weaknesses(inspect_results)
            
            assert "scores" in analysis
            assert "stability" in analysis["scores"]
            assert "core" in analysis["scores"]
            assert "template" in analysis["scores"]
            assert "broadcast" in analysis["scores"]
            assert "youtube" in analysis["scores"]
            
            # plugin_results から個別の結果が得られていることを確認
            assert "subtitle_line_check" in analysis["plugin_results"]
        finally:
            template_config.clear()

    def test_self_improvement_report_generation(self, temp_workspace):
        """T-471-03: 弱点レポート出力と履歴積上の検証"""
        engine = SelfImprovementEngine(
            artifacts_dir=str(temp_workspace["artifacts_dir"]),
            merged_dir=str(temp_workspace["merged_dir"])
        )
        
        analysis = {
            "scores": {
                "total_score": 78,
                "stability": 91.7,
                "core": 100.0,
                "template": 98.1,
                "broadcast": 97.5,
                "youtube": 87.5
            },
            "passed": False,
            "vision_violations": 0,
            "feedback": ["NHK基準: 1行15文字オーバーあり", "YouTuber基準: 10秒以上の変化なし区間あり"]
        }
        
        engine.save_results(analysis)
        
        # レポートファイルが作られたか
        report_path = Path(temp_workspace["artifacts_dir"]) / "weakness_analysis_report.md"
        assert report_path.exists()
        
        # 履歴ファイルが作られたか
        history_path = Path(temp_workspace["artifacts_dir"]) / "weakness_analysis_history.json"
        assert history_path.exists()
        
        # 履歴が積上可能か（2回目実行）
        engine.save_results(analysis)
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
            assert len(history) == 2

    def test_self_improvement_auto_remediation(self, temp_workspace):
        """T-471-04: 自動パラメータ改善の検証"""
        engine = SelfImprovementEngine(
            artifacts_dir=str(temp_workspace["artifacts_dir"]),
            merged_dir=str(temp_workspace["merged_dir"])
        )
        
        analysis = {
            "scores": {
                "total_score": 78,
                "stability": 91.7,
                "core": 100.0,
                "template": 78.0,
                "broadcast": 97.5,
                "youtube": 87.5
            },
            "plugin_results": {
                "subtitle_speed_check": {
                    "feedback": ["表示字幕速度超過: 10/10件"]
                },
                "subtitle_line_check": {
                    "feedback": ["長い字幕行: 5件が基準を超過"]
                }
            },
            "feedback": ["NHK基準: 1行15文字オーバーあり"]
        }
        
        # ダミーの設定ファイルを生成
        config_file = temp_workspace["workspace"] / "template_config.py"
        config_file.write_text("""
_DEFAULT_SUBTITLE_RULES = {
    "font_size_min_px": 32,
    "max_chars_per_line": 20,
    "chars_per_second": 8,
}
""", encoding="utf-8")
        
        # エンジンの対象ファイルをテスト用にパッチ
        with patch("self_improvement_engine.TEMPLATE_CONFIG_PATH", config_file):
            remediated = engine.auto_remediate(analysis)
            
            assert remediated is True
            # 設定が改善されたことを確認（文字数削減、フォントサイズ縮小など）
            content = config_file.read_text(encoding="utf-8")
            assert '"max_chars_per_line": 13' in content or '"max_chars_per_line": 15' in content
            assert '"font_size_min_px": 16' in content
            assert '"chars_per_second": 4' in content

    @patch("quality_gate_plugins.run_all_plugins")
    @patch("self_improvement_engine.SelfImprovementEngine._find_latest_preview")
    @patch("self_improvement_engine.get_gemini_client")
    @patch("self_improvement_engine.SelfImprovementEngine._load_youtube_metadata")
    def test_self_improvement_loop_convergence(self, mock_load_meta, mock_get_client, mock_find_preview, mock_run_plugins, temp_workspace):
        """T-471-05: 改善ループが合格基準まで実行され、収束することの検証"""
        # run_all_plugins をモック化し、イテレーションごとにNG/OKを切り替えてループ収束をテストする
        mock_plugin_result_ng = {
            "category_scores": {
                "stability": 90,
                "core": 90,
                "template": 75,
                "broadcast": 90,
                "youtube": 90,
            },
            "final_score": 75,
            "feedback": ["NGフィードバック"],
            "category_report": [],
            "plugin_results": {"subtitle_speed_check": {"feedback": ["字幕速度超過"]}}
        }
        mock_plugin_result_ok = {
            "category_scores": {
                "stability": 95,
                "core": 95,
                "template": 95,
                "broadcast": 95,
                "youtube": 95,
            },
            "final_score": 95,
            "feedback": [],
            "category_report": [],
            "plugin_results": {}
        }
        mock_run_plugins.side_effect = [mock_plugin_result_ng, mock_plugin_result_ok, mock_plugin_result_ok]

        # コア品質の FileSizeCheck で減点されないよう、10MB以上のダミープレビュー動画ファイルを作成
        dummy_video = Path(temp_workspace["artifacts_dir"]) / "preview_test.mp4"
        with open(dummy_video, "wb") as f:
            f.seek(10 * 1024 * 1024 + 1024)
            f.write(b"\0")
        mock_find_preview.return_value = dummy_video

        mock_load_meta.return_value = {
            "titles": ["タイトル案1", "タイトル案2", "タイトル案3", "タイトル案4", "タイトル案5"],
            "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5", "タグ6", "タグ7", "タグ8", "タグ9", "タグ10", "タグ11", "タグ12", "タグ13", "タグ14", "タグ15"],
            "description": "これはYouTube用のダミー説明文です。50文字以上必要なので長めに記述します。さらにテストを通過するために100文字以上の長さに引き上げます。これで減点が0になりテストが合格するようになります。"
        }
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        # 初回はNG（弱点あり）、2回目はOK（弱点なし）のVision応答をシミュレート
        mock_response_ng = MagicMock()
        mock_response_ng.text = """
        ```json
        {
          "subtitle_overlap_detected": true,
          "subtitle_layout_ok": false,
          "font_size_appropriate": false,
          "contrast_ok": true,
          "improvement_suggestions": "字幕サイズ調整要"
        }
        ```
        """
        
        mock_response_ok = MagicMock()
        mock_response_ok.text = """
        ```json
        {
          "subtitle_overlap_detected": false,
          "subtitle_layout_ok": true,
          "font_size_appropriate": true,
          "contrast_ok": true,
          "improvement_suggestions": ""
        }
        ```
        """
        
        # side_effect で順番に返す
        mock_client.models.generate_content.side_effect = [
            mock_response_ng,  # イテレーション 1 - フレーム 1
            mock_response_ok,  # イテレーション 2 - フレーム 1
            mock_response_ok,  # イテレーション 2 - フレーム 2
            mock_response_ok,  # 予備
            mock_response_ok,  # 予備
            mock_response_ok   # 予備
        ]
        
        engine = SelfImprovementEngine(
            artifacts_dir=str(temp_workspace["artifacts_dir"]),
            merged_dir=str(temp_workspace["merged_dir"])
        )
        
        # ダミーのパイプライン実行関数を用意
        run_count = 0
        def dummy_pipeline_run():
            nonlocal run_count
            run_count += 1
            # 2回目のループ時、Whisperキャッシュのデータを綺麗にしてNHK違反を解消
            # また、GPUHealthCheck（50文字以上）をパスするように適度に長いテキストにする
            if run_count > 1:
                latest_whisper = Path(temp_workspace["merged_dir"]) / "_whisper_test.jsonl"
                whisper_data = [
                    {"start": 0.0, "end": 4.5, "text": "こんにちは。本日は自動改善ループのテストを行っております。"},
                    {"start": 10.5, "end": 15.0, "text": "テストは順調に推移しており、これで合格判定が出るはずです。完了。"}
                ]
                with open(latest_whisper, "w", encoding="utf-8") as f:
                    for item in whisper_data:
                        f.write(json.dumps(item, ensure_ascii=False) + "\n")
            return True
            
        config_file = temp_workspace["workspace"] / "template_config.py"
        config_file.write_text('_DEFAULT_SUBTITLE_RULES = {"font_size_min_px": 32, "max_chars_per_line": 20}', encoding="utf-8")
        
        with patch("self_improvement_engine.TEMPLATE_CONFIG_PATH", config_file):
            success = engine.run_loop(pipeline_callback=dummy_pipeline_run, max_iterations=3)
            
            assert success is True
            assert run_count >= 2  # 改善ループが回ったことを確認

    @patch("self_improvement_engine.get_gemini_client")
    def test_self_improvement_caching_behavior(self, mock_get_client, temp_workspace):
        """自己改善エンジンにおけるWhisperセグメント読み込みのキャッシュ・I/O削減挙動の検証"""
        # Gemini Clientのモック作成（API呼出し回避用）
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        # Vision API のレスポンスを模倣
        mock_response = MagicMock()
        mock_response.text = '{"subtitle_overlap_detected":false,"subtitle_layout_ok":true,"font_size_appropriate":true,"contrast_ok":true,"improvement_suggestions":""}'
        mock_client.models.generate_content.return_value = mock_response
        
        # ダミーのプレビュー画像を作成してVision APIがスキップされないようにする
        for i in range(3):
            (temp_workspace["inspection_dir"] / f"frame_{i:04d}_{i*5.0:.1f}s.jpg").write_bytes(b"dummy")

        # 3つのフレームを設定して、ループが3回回るようにする
        index_data = {
            "video": "preview_test.mp4",
            "duration": 15.0,
            "total_frames": 3,
            "segment_count": 2,
            "frames": [
                {"timestamp": 0.0, "path": "frame_0000_0.0s.jpg"},
                {"timestamp": 5.0, "path": "frame_0001_5.0s.jpg"},
                {"timestamp": 10.0, "path": "frame_0002_10.0s.jpg"}
            ]
        }
        with open(temp_workspace["inspection_dir"] / "index.json", "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)

        engine = SelfImprovementEngine(
            artifacts_dir=str(temp_workspace["artifacts_dir"]),
            merged_dir=str(temp_workspace["merged_dir"])
        )
        
        # _load_whisper_segments メソッドの呼出し回数をカウントするために spy する
        original_load = engine._load_whisper_segments
        call_count = 0
        
        def spy_load_whisper_segments():
            nonlocal call_count
            call_count += 1
            return original_load()
            
        engine._load_whisper_segments = spy_load_whisper_segments
        
        # 1. 3つのフレームを auto_inspect 実行
        # 改善されていれば、ループ数（3回）に関わらず _load_whisper_segments は1回しか呼ばれない
        results = engine.auto_inspect()
        
        assert len(results) == 3
        assert call_count == 1, f"I/O削減が動作していません。呼出し回数: {call_count} (期待値: 1)"
        
        # 2. キャッシュ機能自体の検証
        # キャッシュが保持されていることを確認
        assert engine._cached_segments is not None
        
        # キャッシュをクリアすると、再読込みが走り、別のリストインスタンスになる
        engine.clear_cache()
        assert engine._cached_segments is None
        
        # 再読込（call_count は 2 になる）
        engine.auto_inspect()
        assert call_count == 2
        assert engine._cached_segments is not None



class TestSelfImprovementMetadataIntegration:
    """YouTubeメタデータの自己改善ループ統合テストクラス"""

    @patch("self_improvement_engine.SelfImprovementEngine._find_latest_preview")
    def test_load_youtube_metadata_success(self, mock_find_preview, temp_workspace):
        """youtube_metadata.json からメタデータが正しくロードされるか検証"""
        mock_find_preview.return_value = None
        
        # ダミーの youtube_metadata.json を用意（説明文は100文字以上に設定）
        meta_data = {
            "titles": ["タイトル案A", "タイトル案B", "タイトル案C", "タイトル案D", "タイトル案E"],
            "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5", "タグ6", "タグ7", "タグ8", "タグ9", "タグ10", "タグ11", "タグ12", "タグ13", "タグ14", "タグ15"],
            "description": "これはYouTube用のダミー説明文です。50文字以上必要なので長めに記述します。さらにテストを通過するために100文字以上の長さに引き上げます。これで減点が0になりテストが合格するようになります。よろしくお願いいたします。"
        }
        meta_path = Path(temp_workspace["artifacts_dir"]) / "youtube_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_data, f, ensure_ascii=False, indent=2)

        engine = SelfImprovementEngine(
            artifacts_dir=str(temp_workspace["artifacts_dir"]),
            merged_dir=str(temp_workspace["merged_dir"])
        )
        
        loaded = engine._load_youtube_metadata()
        assert len(loaded.get("titles", [])) == 5
        assert len(loaded.get("tags", [])) == 15
        assert len(loaded.get("description", "")) > 100

    @patch("self_improvement_engine.SelfImprovementEngine._find_latest_preview")
    def test_analyze_weaknesses_integrates_metadata(self, mock_find_preview, temp_workspace):
        """analyze_weaknesses にてメタデータが正しく品質ゲートコンテキストに統合されるか検証"""
        mock_find_preview.return_value = None
        
        # ダミーの youtube_metadata.json を用意（説明文は100文字以上に設定）
        meta_data = {
            "titles": ["タイトル案1", "タイトル案2", "タイトル案3", "タイトル案4", "タイトル案5"],
            "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5", "タグ6", "タグ7", "タグ8", "タグ9", "タグ10", "タグ11", "タグ12", "タグ13", "タグ14", "タグ15"],
            "description": "これはYouTube用のダミー説明文です。50文字以上必要なので長めに記述します。さらにテストを通過するために100文字以上の長さに引き上げます。これで減点が0になりテストが合格するようになります。よろしくお願いいたします。"
        }
        meta_path = Path(temp_workspace["artifacts_dir"]) / "youtube_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_data, f, ensure_ascii=False, indent=2)

        engine = SelfImprovementEngine(
            artifacts_dir=str(temp_workspace["artifacts_dir"]),
            merged_dir=str(temp_workspace["merged_dir"])
        )

        # 弱点分析を実行
        analysis = engine.analyze_weaknesses([])
        
        # メタデータ関連の減点がない（0である）ことをアサート
        # もしメタデータが適用されていなければ MetadataCompletenessCheck により deductions = 10 が発生する
        meta_completeness_result = analysis["plugin_results"].get("metadata_completeness_check", {})
        assert meta_completeness_result.get("deductions", 0) == 0

    @patch("quality_gate_plugins.run_all_plugins")
    @patch("self_improvement_engine.SelfImprovementEngine._find_latest_preview")
    def test_analyze_weaknesses_general_exception_propagation(self, mock_find_preview, mock_run_plugins, temp_workspace):
        """analyze_weaknesses において run_all_plugins が予期しない例外を投げた場合に、
        適切に例外が呼び出し元に伝播することを検証。
        """
        mock_find_preview.return_value = None
        mock_run_plugins.side_effect = ValueError("Simulated unexpected plugin error")
        
        engine = SelfImprovementEngine(
            artifacts_dir=str(temp_workspace["artifacts_dir"]),
            merged_dir=str(temp_workspace["merged_dir"])
        )
        
        with pytest.raises(ValueError, match="Simulated unexpected plugin error"):
            engine.analyze_weaknesses([])
