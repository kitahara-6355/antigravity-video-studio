# -*- coding: utf-8 -*-
"""
test_blind_quality_sweep.py — ブラインド品質テストスイープ

新規RAW動画に対する自己改善ループの実行と、
それに伴う検証レポート自動生成機能のテストを担当。
"""
import os
import sys
import json
import pytest
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

# パス設定
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.self_improvement_engine import SelfImprovementEngine
from backend.report_generator import generate_durability_report, load_json_file


@pytest.fixture
def temp_workspace(tmp_path):
    """テスト用の一時ワークスペースディレクトリ群を作成"""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    inspection_dir = artifacts_dir / "full_inspection"
    inspection_dir.mkdir(parents=True, exist_ok=True)
    
    # ダミーのプレビュー画像
    (inspection_dir / "frame_0000_0.0s.jpg").write_bytes(b"dummy_image_data")
    
    index_data = {
        "video": "preview_test.mp4",
        "duration": 10.0,
        "total_frames": 1,
        "segment_count": 1,
        "frames": [
            {"timestamp": 0.0, "path": "frame_0000_0.0s.jpg"}
        ]
    }
    with open(inspection_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
        
    merged_dir = tmp_path / "vault-outputs" / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)
    
    whisper_data = [
        {"start": 0.0, "end": 4.5, "text": "テスト用字幕データです。"}
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


class TestBlindQualitySweep:
    """ブラインド品質テストスイープクラス"""

    @patch("self_improvement_engine.SelfImprovementEngine._find_latest_preview")
    @patch("self_improvement_engine.get_gemini_client")
    @patch("self_improvement_engine.SelfImprovementEngine._load_youtube_metadata")
    @patch("quality_gate_plugins.run_all_plugins")
    def test_blind_quality_sweep_success(self, mock_run_all_plugins, mock_load_meta, mock_get_client, mock_find_preview, temp_workspace):
        """新規RAW動画を用いたブラインド品質テスト自己改善ループの検証"""
        # ダミーのプレビュー動画
        dummy_video = Path(temp_workspace["artifacts_dir"]) / "preview_test.mp4"
        with open(dummy_video, "wb") as f:
            f.seek(10 * 1024 * 1024)
            f.write(b"\0")
        mock_find_preview.return_value = dummy_video

        # YouTubeメタデータのロードをダミー化
        mock_load_meta.return_value = {
            "titles": ["タイトル案1", "タイトル案2", "タイトル案3", "タイトル案4", "タイトル案5"],
            "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5", "タグ6", "タグ7", "タグ8", "タグ9", "タグ10", "タグ11", "タグ12", "タグ13", "タグ14", "タグ15"],
            "description": "これはYouTube用のテスト説明文です。100文字以上の長さに引き上げることで、減点を回避します。" * 2
        }

        # Gemini Client of Vision API
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        # 1回目のイテレーション（NG: 字幕被りあり）、2回目（OK）のレスポンスを設定
        mock_response_ng = MagicMock()
        mock_response_ng.text = json.dumps({
            "subtitle_overlap_detected": True,
            "subtitle_layout_ok": False,
            "font_size_appropriate": False,
            "contrast_ok": True,
            "improvement_suggestions": "字幕レイアウトの改善が必要です。"
        })
        
        mock_response_ok = MagicMock()
        mock_response_ok.text = json.dumps({
            "subtitle_overlap_detected": False,
            "subtitle_layout_ok": True,
            "font_size_appropriate": True,
            "contrast_ok": True,
            "improvement_suggestions": ""
        })

        mock_client.models.generate_content.side_effect = [
            mock_response_ng,
            mock_response_ok,
            mock_response_ok
        ]

        # 22種品質プラグインの戻り値をモック化
        # イテレーション1：不合格 (75点)
        plugin_result_ng = {
            "category_scores": {"stability": 75, "core": 75, "template": 75, "broadcast": 75, "youtube": 75},
            "final_score": 75,
            "feedback": ["NHK基準に未達"],
            "plugin_results": {
                "subtitle_line_check": {"feedback": ["長い字幕行が存在します。"]},
                "subtitle_speed_check": {"feedback": ["字幕速度超過があります。"]}
            }
        }
        # イテレーション2：合格 (90点以上)
        plugin_result_ok = {
            "category_scores": {"stability": 92, "core": 92, "template": 92, "broadcast": 92, "youtube": 92},
            "final_score": 92,
            "feedback": [],
            "plugin_results": {}
        }
        mock_run_all_plugins.side_effect = [
            plugin_result_ng,
            plugin_result_ok,
            plugin_result_ok
        ]

        engine = SelfImprovementEngine(
            artifacts_dir=str(temp_workspace["artifacts_dir"]),
            merged_dir=str(temp_workspace["merged_dir"])
        )

        run_count = 0
        def mock_pipeline_callback():
            nonlocal run_count
            run_count += 1
            return True

        # 設定ファイルのダミー
        config_file = temp_workspace["workspace"] / "template_config.py"
        config_file.write_text('_DEFAULT_SUBTITLE_RULES = {"font_size_min_px": 32, "max_chars_per_line": 20}', encoding="utf-8")

        # 改善ループ実行
        with patch("self_improvement_engine.TEMPLATE_CONFIG_PATH", config_file):
            success = engine.run_loop(pipeline_callback=mock_pipeline_callback, max_iterations=3)
            
            assert success is True
            assert run_count >= 2

        # 履歴からメトリクスを抽出して temp/quality_sweep_metrics.json に保存
        history_path = Path(temp_workspace["artifacts_dir"]) / "weakness_analysis_history.json"
        assert history_path.exists()
        
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
            
        # 出力用メトリクス構造の構築
        iterations_metrics = []
        for idx, hist_item in enumerate(history, 1):
            scores = hist_item.get("scores", {})
            total_score = scores.get("total_score", 0)
            violations = hist_item.get("vision_violations", 0)
            passed = hist_item.get("passed", False)
            iterations_metrics.append({
                "iteration": idx,
                "score": total_score,
                "passed": passed,
                "vision_violations": violations
            })

        final_item = history[-1]
        final_score = final_item.get("scores", {}).get("total_score", 0)
        final_violations = final_item.get("vision_violations", 0)

        # アサーション: スコア80以上かつ警告数0
        assert final_score >= 80
        assert final_violations == 0

        # メトリクス辞書
        metrics_data = {
            "timestamp": final_item.get("timestamp", ""),
            "iterations": iterations_metrics,
            "final_score": final_score,
            "vision_violations": final_violations,
            "passed": True
        }

        # メトリクス保存先 (temp フォルダ)
        temp_dir = Path(temp_workspace["workspace"]) / "backend" / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        metrics_file = temp_dir / "quality_sweep_metrics.json"

        # PythonによるUTF-8書き込み
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump(metrics_data, f, ensure_ascii=False, indent=2)

        assert metrics_file.exists()

        # 2. レポート自動生成機能のテスト
        stability_file = temp_dir / "stability_stress_metrics.json"
        
        # テスト用の stability_stress_metrics.json を準備 (正常系)
        dummy_stability_data = {
            "timestamp": "2026-05-22T17:39:00+09:00",
            "platform": "Windows-Test-Env",
            "memory_metrics": [
                {"timestamp": "17:39:05", "usage_mb": 120.5},
                {"timestamp": "17:39:10", "usage_mb": 122.3}
            ],
            "memory_leak_detected": False,
            "temp_dir_metrics": {
                "initial_size_bytes": 1024000,
                "final_size_bytes": 0,
                "cleanup_success": True
            },
            "ffmpeg_process_metrics": {
                "remaining_child_processes": 0,
                "zombie_processes": 0
            }
        }
        with open(stability_file, "w", encoding="utf-8") as f:
            json.dump(dummy_stability_data, f, ensure_ascii=False, indent=2)

        # レポート出力先
        report_output = Path(temp_workspace["workspace"]) / "Human01_Official Artifact" / "受信トレイ" / "raw_video_durability_report.md"
        report_output.parent.mkdir(parents=True, exist_ok=True)
        
        # 正常な生成
        rep_success = generate_durability_report(
            stability_path=str(stability_file),
            quality_path=str(metrics_file),
            output_path=str(report_output)
        )
        assert rep_success is True
        assert report_output.exists()

        # 内容の読み込みとアサーション (EBVP 準挙: 推測表現の排除)
        with open(report_output, "r", encoding="utf-8") as f:
            report_text = f.read()
            
        assert "可能性があります" not in report_text
        assert "と思われます" not in report_text
        assert "👑 EXCELLENT" in report_text
        assert "✅ 正常（メモリリーク未検出）" in report_text
        assert "✅ クリーンアップ成功" in report_text

        # --- カバレッジ100%のための異常系・警告系データテスト ---

        # (1) ValueError timestamp & memory_leak_detected=True & cleanup_success=False & child_processes>0
        warn_stability_file = temp_workspace["workspace"] / "warn_stability.json"
        warn_stability_data = {
            "timestamp": "invalid-iso-format-timestamp", # ValueError を誘発
            "platform": "Windows-Test-Env",
            "memory_metrics": [
                {"timestamp": "17:39:05", "usage_mb": 120.5}
            ],
            "memory_leak_detected": True, # memory_result = "⚠️ 異常（メモリリーク検出）"
            "temp_dir_metrics": {
                "initial_size_bytes": 1024000,
                "final_size_bytes": 100, # クリーンアップ不完全
                "cleanup_success": False
            },
            "ffmpeg_process_metrics": {
                "remaining_child_processes": 3, # FFmpegプロセス残存
                "zombie_processes": 1
            }
        }
        with open(warn_stability_file, "w", encoding="utf-8") as f:
            json.dump(warn_stability_data, f, ensure_ascii=False, indent=2)

        # quality_sweep_metrics.json (品質不合格ケース)
        fail_quality_file = temp_workspace["workspace"] / "fail_quality.json"
        fail_quality_data = {
            "timestamp": "invalid-iso-format-timestamp",
            "iterations": [
                {"iteration": 1, "score": 75, "passed": False, "vision_violations": 2}
            ],
            "final_score": 75, # 80点未満で不合格
            "vision_violations": 2,
            "passed": False
        }
        with open(fail_quality_file, "w", encoding="utf-8") as f:
            json.dump(fail_quality_data, f, ensure_ascii=False, indent=2)

        warn_report_output = temp_workspace["workspace"] / "warn_report.md"
        rep_warn_success = generate_durability_report(
            stability_path=str(warn_stability_file),
            quality_path=str(fail_quality_file),
            output_path=str(warn_report_output)
        )
        assert rep_warn_success is True
        
        with open(warn_report_output, "r", encoding="utf-8") as f:
            warn_report_text = f.read()
        
        # 警告系テキストのアサーション
        assert "⚠️ 異常（メモリリーク検出）" in warn_report_text
        assert "⚠️ クリーンアップ不完全" in warn_report_text
        assert "⚠️ 異常（残存プロセスあり" in warn_report_text
        assert "⚠️ 不合格" in warn_report_text
        assert "⚠️ WARNING" in warn_report_text

        # (2) エラー/フォールバック系テスト
        # 存在しないパスでの読み込み
        non_existent_file = str(temp_workspace["workspace"] / "no_file.json")
        loaded_empty = load_json_file(non_existent_file)
        assert loaded_empty == {}

        # 破損したJSON
        corrupted_file = temp_workspace["workspace"] / "corrupted.json"
        corrupted_file.write_text("{invalid json", encoding="utf-8")
        loaded_corrupted = load_json_file(str(corrupted_file))
        assert loaded_corrupted == {}

        # 全てフォールバック状態でのレポート生成
        fallback_report_output = temp_workspace["workspace"] / "fallback_report.md"
        rep_success_fb = generate_durability_report(
            stability_path=non_existent_file,
            quality_path=non_existent_file,
            output_path=str(fallback_report_output)
        )
        assert rep_success_fb is True
        assert fallback_report_output.exists()

        # 書き込みエラーのテスト
        invalid_output_path = r"Z:\non_existent_dir_xyz_123\report.md"
        rep_fail = generate_durability_report(
            stability_path=str(stability_file),
            quality_path=str(metrics_file),
            output_path=invalid_output_path
        )
        assert rep_fail is False
