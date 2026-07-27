import os
import json
import sys
import pytest
from unittest import mock
import subprocess
import runpy

# テスト対象をインポートできるようにパスを調整
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

import scratch.verify_video_quality_matrix as vqm

# 固有名詞辞書のモック用のダミークラス
class DummyEntry:
    def __init__(self, correct):
        self.correct = correct

class DummyProperNounDict:
    def __init__(self, entries):
        self.entries = entries


@pytest.fixture
def setup_dirs(tmp_path):
    # 各種ディレクトリパスのモック
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    
    graded_dir = tmp_path / "graded"
    graded_dir.mkdir()
    
    latest_dir = graded_dir / "latest"
    latest_dir.mkdir()
    
    # グローバル変数をモック
    orig_raw = vqm.RAW_VIDEOS_DIR
    orig_graded = vqm.GRADED_PREVIEWS_DIR
    orig_latest = vqm.LATEST_PREVIEWS_DIR
    orig_root = vqm.PROJECT_ROOT
    orig_base = vqm.BASE_DIR
    
    vqm.RAW_VIDEOS_DIR = str(raw_dir)
    vqm.GRADED_PREVIEWS_DIR = str(graded_dir)
    vqm.LATEST_PREVIEWS_DIR = str(latest_dir)
    vqm.PROJECT_ROOT = str(tmp_path)
    vqm.BASE_DIR = str(tmp_path / "backend")
    
    # backend ディレクトリを作成
    (tmp_path / "backend").mkdir(exist_ok=True)
    
    yield tmp_path, raw_dir, graded_dir, latest_dir
    
    # 元に戻す
    vqm.RAW_VIDEOS_DIR = orig_raw
    vqm.GRADED_PREVIEWS_DIR = orig_graded
    vqm.LATEST_PREVIEWS_DIR = orig_latest
    vqm.PROJECT_ROOT = orig_root
    vqm.BASE_DIR = orig_base


def test_run_command_success():
    # 正常にコマンド実行できる場合
    code, stdout, stderr = vqm.run_command("echo hello")
    assert code == 0
    assert "hello" in stdout


def test_run_command_exception():
    # コマンド実行で例外が発生する場合
    with mock.patch("subprocess.run", side_effect=OSError("Dummy error")):
        code, stdout, stderr = vqm.run_command("invalid_command_here")
        assert code == -1
        assert "Dummy error" in stderr


def test_parse_srt_time():
    # 正常系
    assert vqm.parse_srt_time("00:01:23,450") == 83.450
    # 異常系 (parts の長さが 4 でない場合)
    assert vqm.parse_srt_time("invalid_time") == 0.0


def test_verify_macro_all_exist(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    # 1. RAW動画の作成
    raw_files = ["シーン01_前編.mp4", "シーン02_ゲスト書道.mp4", "シーン03_後編01.mp4", "シーン04_後編02.mp4"]
    for f in raw_files:
        (raw_dir / f).write_text("dummy", encoding="utf-8")
        
    # 2. index.json の作成 (duration > 14000)
    index_data = {
        "duration": 15000.0,
        "frames": [{"timestamp": 10.0}]
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)
        
    # 3. youtube_metadata.json の作成
    (graded_dir / "youtube_metadata.json").write_text("{}", encoding="utf-8")
    
    results = vqm.verify_macro()
    assert results["raw_files_exist"] is True
    assert results["index_json_exist"] is True
    assert results["duration_match"] is True
    assert results["frames_count"] == 1
    assert results["youtube_metadata_exist"] is True


def test_verify_macro_missing_files(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    # RAW動画を一部欠損させる
    raw_files = ["シーン01_前編.mp4", "シーン03_後編01.mp4"]
    for f in raw_files:
        (raw_dir / f).write_text("dummy", encoding="utf-8")
        
    # index.json を duration < 14000 で作成
    index_data = {
        "duration": 1000.0,
        "frames": []
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)
        
    results = vqm.verify_macro()
    assert results["raw_files_exist"] is False
    assert results["index_json_exist"] is True
    assert results["duration_match"] is False
    assert results["frames_count"] == 0
    assert results["youtube_metadata_exist"] is False


def test_verify_macro_no_index_json(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    # 1. RAW動画の作成
    raw_files = ["シーン01_前編.mp4", "シーン02_ゲスト書道.mp4", "シーン03_後編01.mp4", "シーン04_後編02.mp4"]
    for f in raw_files:
        (raw_dir / f).write_text("dummy", encoding="utf-8")
        
    # index.json は作成しない
    results = vqm.verify_macro()
    assert results["index_json_exist"] is False
    assert results["duration_match"] is False
    assert results["frames_count"] == 0


def test_verify_mezzo_no_history(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    # weakness_analysis_history.json を作成しない
    results = vqm.verify_mezzo()
    assert results["has_history"] is False


def test_verify_mezzo_empty_history(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    # 空の履歴ファイルを作成
    with open(graded_dir / "weakness_analysis_history.json", "w", encoding="utf-8") as f:
        json.dump([], f)
        
    results = vqm.verify_mezzo()
    assert results["has_history"] is True
    assert "total_score" not in results


def test_verify_mezzo_normal_and_failed_scores(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    # 正常系 (全カテゴリが80点以上)
    history_data = [
        {
            "timestamp": "2026-05-21T10:00:00",
            "scores": {
                "total_score": 90,
                "nhk_compliance": 85,
                "constitution": 95,
                "optional_score": None
            },
            "passed": True,
            "vision_violations": 0
        }
    ]
    with open(graded_dir / "weakness_analysis_history.json", "w", encoding="utf-8") as f:
        json.dump(history_data, f)
        
    results = vqm.verify_mezzo()
    assert results["total_score"] == 90
    assert results.get("passed", False)
    assert results["vision_violations"] == 0
    assert results["all_categories_above_80"] is True
    
    # 異常系 (カテゴリに80点未満がある場合)
    history_data[0]["scores"]["nhk_compliance"] = 75
    history_data[0]["passed"] = False
    with open(graded_dir / "weakness_analysis_history.json", "w", encoding="utf-8") as f:
        json.dump(history_data, f)
        
    results = vqm.verify_mezzo()
    assert results["passed"] is False
    assert results["all_categories_above_80"] is False


def test_verify_micro_no_history_and_no_srt(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    # 履歴ファイルも SRT も作成しない
    results = vqm.verify_micro()
    assert results["vision_overlap_clean"] is True
    assert results["vision_overlap_count"] == 0
    assert results["proper_nouns_present"] is False
    assert results["av_sync_ok"] is False


@pytest.fixture
def mock_proper_noun_dict():
    # proper_noun_dict モジュールをモック
    dummy_dict = DummyProperNounDict([DummyEntry("山田"), DummyEntry("書道")])
    with mock.patch.dict("sys.modules", {"proper_noun_dict": dummy_dict}):
        with mock.patch("proper_noun_dict.proper_noun_dict", dummy_dict, create=True):
            yield dummy_dict


def test_verify_micro_comprehensive(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    # 1. weakness_analysis_history.json の作成 (Vision 違反あり)
    history_data = [
        {
            "timestamp": "2026-05-21T10:00:00",
            "scores": {},
            "passed": True,
            "vision_violations": 2
        }
    ]
    with open(graded_dir / "weakness_analysis_history.json", "w", encoding="utf-8") as f:
        json.dump(history_data, f)
        
    # 2. SRT ファイルの作成 (適用された固有名詞「山田」を含む)
    srt_content = """1
00:00:01,000 --> 00:00:04,500
こんにちは、山田さん。
"""
    # PROJECT_ROOT (tmp_path) 内に soul_narrative 関連の SRT ファイルを作成
    srt_dir = tmp_path / "vault-outputs"
    srt_dir.mkdir()
    (srt_dir / "soul_narrative_subtitles.srt").write_text(srt_content, encoding="utf-8")
    
    # 3. index.json の作成 (動画ファイル名指定)
    index_data = {
        "video": "preview_video.mp4",
        "frames": [
            {"timestamp": 2.0},  # active_speech (1.0 <= 2.0 <= 4.5)
            {"timestamp": 5.0},  # scene_boundary (abs(5.0 - 4.5) <= 2.0)
            {"timestamp": 10.0}  # silent_gap (その他)
        ]
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)
        
    # 4. プレビュー用動画ファイルの作成
    video_dir = tmp_path / "vault-outputs" / "preview"
    video_dir.mkdir()
    (video_dir / "preview_video.mp4").write_text("dummy video data", encoding="utf-8")
    
    # 5. FFmpeg (ffprobe) run_command のモック (A/V Sync 正常: ズレ 10ms)
    def mock_run_command(cmd):
        if "select_streams v:0" in cmd:
            return 0, "0.020000\n0.060000", ""
        elif "select_streams a:0" in cmd:
            return 0, "0.030000\n0.070000", ""
        return 0, "", ""
        
    with mock.patch("scratch.verify_video_quality_matrix.run_command", side_effect=mock_run_command):
        results = vqm.verify_micro()
        
    assert results["vision_overlap_clean"] is False
    assert results["vision_overlap_count"] == 2
    assert results["proper_nouns_present"] is True
    assert results["av_sync_ok"] is True
    assert abs(results["av_start_offset_ms"] - 10.0) < 1e-5
    assert results["clustering_ok"] is True
    assert results["clustering_stats"]["active_speech_count"] == 1
    assert results["clustering_stats"]["scene_boundary_count"] == 1
    assert results["clustering_stats"]["silent_gap_count"] == 1


def test_verify_micro_av_sync_offset_failure(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    # SRT ファイルの作成
    srt_dir = tmp_path / "vault-outputs"
    srt_dir.mkdir(exist_ok=True)
    (srt_dir / "soul_narrative_subtitles.srt").write_text("1\n00:00:01,000 --> 00:00:04,500\n山田\n", encoding="utf-8")
    
    # index.json の作成 (動画ファイル名指定)
    index_data = {
        "video": "preview_video.mp4",
        "frames": []
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)
        
    # 動画ファイルの作成
    (tmp_path / "preview_video.mp4").write_text("dummy video", encoding="utf-8")
    
    # 1. PTS 取得コマンドが失敗する場合
    with mock.patch("scratch.verify_video_quality_matrix.run_command", return_value=(1, "", "probe failed")):
        results = vqm.verify_micro()
        assert results["av_sync_ok"] is False
        assert results["av_start_offset_ms"] == -1
        
    # 2. PTS が空の場合
    with mock.patch("scratch.verify_video_quality_matrix.run_command", return_value=(0, "", "")):
        results = vqm.verify_micro()
        assert results["av_sync_ok"] is False
        assert results["av_start_offset_ms"] == -1
        
    # 3. PTS 解析で例外が発生する場合 (不正な値など)
    with mock.patch("scratch.verify_video_quality_matrix.run_command", return_value=(0, "invalid_pts", "")):
        results = vqm.verify_micro()
        assert results["av_sync_ok"] is False
        assert results["av_start_offset_ms"] == -1


def test_verify_micro_proper_noun_exception(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    # proper_noun_dict のインポートで例外を発生させる
    with mock.patch.dict("sys.modules", {"proper_noun_dict": None}):
        results = vqm.verify_micro()
        assert results["proper_nouns_present"] is False


def test_main_function(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    # 1. RAW動画の作成
    raw_files = ["シーン01_前編.mp4", "シーン02_ゲスト書道.mp4", "シーン03_後編01.mp4", "シーン04_後編02.mp4"]
    for f in raw_files:
        (raw_dir / f).write_text("dummy", encoding="utf-8")
        
    # 2. index.json の作成 (duration > 14000)
    index_data = {
        "video": "preview_video.mp4",
        "duration": 15000.0,
        "frames": [{"timestamp": 2.0}]
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)
        
    # 3. youtube_metadata.json の作成
    (graded_dir / "youtube_metadata.json").write_text("{}", encoding="utf-8")
    
    # 4. weakness_analysis_history.json の作成 (Vision 違反なし, 全カテゴリ 80点以上)
    history_data = [
        {
            "timestamp": "2026-05-21T10:00:00",
            "scores": {
                "total_score": 90,
                "nhk_compliance": 85,
                "constitution": 95
            },
            "passed": True,
            "vision_violations": 0
        }
    ]
    with open(graded_dir / "weakness_analysis_history.json", "w", encoding="utf-8") as f:
        json.dump(history_data, f)
        
    # 5. SRT ファイルの作成
    srt_dir = tmp_path / "vault-outputs"
    srt_dir.mkdir()
    (srt_dir / "soul_narrative_subtitles.srt").write_text("1\n00:00:01,000 --> 00:00:04,500\n山田\n", encoding="utf-8")
    
    # 6. 動画ファイルの作成
    video_dir = tmp_path / "vault-outputs" / "preview"
    video_dir.mkdir()
    (video_dir / "preview_video.mp4").write_text("dummy video", encoding="utf-8")
    
    # 7. run_command のモック (A/V Sync 正常)
    def mock_run_command(cmd):
        return 0, "0.010000", ""
        
    with mock.patch("scratch.verify_video_quality_matrix.run_command", side_effect=mock_run_command):
        vqm.main()
        
    # 結果ファイルが作成されていることを確認
    report_path = graded_dir / "video_quality_verification_matrix.json"
    assert report_path.exists()
    
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    
    assert report["overall_status"] is True
    assert report["macro"]["raw_files_exist"] is True
    assert report["mezzo"]["passed"] is True
    assert report["micro"]["av_sync_ok"] is True


def test_main_as_script(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    # 1. index.json の作成 (duration > 14000)
    index_data = {
        "video": "preview_video.mp4",
        "duration": 15000.0,
        "frames": [{"timestamp": 2.0}]
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)
        
    # 2. youtube_metadata.json の作成
    (graded_dir / "youtube_metadata.json").write_text("{}", encoding="utf-8")
    
    # 3. weakness_analysis_history.json の作成 (Vision 違反なし, 全カテゴリ 80点以上)
    history_data = [
        {
            "timestamp": "2026-05-21T10:00:00",
            "scores": {
                "total_score": 90,
                "nhk_compliance": 85,
                "constitution": 95
            },
            "passed": True,
            "vision_violations": 0
        }
    ]
    with open(graded_dir / "weakness_analysis_history.json", "w", encoding="utf-8") as f:
        json.dump(history_data, f)
        
    # 4. SRT ファイルの作成
    # 固有名詞辞書のチェックをパスするため、プロジェクトルート（tmp_path）以下に soul_narrative 字幕ファイルを作成
    srt_dir = tmp_path / "vault-outputs"
    srt_dir.mkdir()
    (srt_dir / "soul_narrative_subtitles.srt").write_text("1\n00:00:01,000 --> 00:00:04,500\n山田\n", encoding="utf-8")
    
    # 5. 動画ファイルの作成
    video_dir = tmp_path / "vault-outputs" / "preview"
    video_dir.mkdir()
    (video_dir / "preview_video.mp4").write_text("dummy video", encoding="utf-8")
    
    # 6. run_command のモック (A/V Sync 正常)
    def mock_run_command(cmd):
        return 0, "0.010000", ""
        
    # sys.modulesから削除して、runpyで確実に再インポート・再実行されるようにする
    if "scratch.verify_video_quality_matrix" in sys.modules:
        del sys.modules["scratch.verify_video_quality_matrix"]
        
    # __file__ を一時ディレクトリのパスに偽装して runpy.run_path を実行する
    # これにより、PROJECT_ROOT や BASE_DIR, GRADED_PREVIEWS_DIR が一時ディレクトリを指すようになる
    init_globals = {
        "__file__": os.path.join(str(tmp_path), "backend", "scratch", "verify_video_quality_matrix.py")
    }
    
    vqm_file_path = os.path.join(PROJECT_ROOT, "backend", "scratch", "verify_video_quality_matrix.py")
    with mock.patch("scratch.verify_video_quality_matrix.run_command", side_effect=mock_run_command):
        runpy.run_path(
            vqm_file_path,
            init_globals=init_globals,
            run_name="__main__"
        )
        
    # 現在の scratch.verify_video_quality_matrix.GRADED_PREVIEWS_DIR にレポートが書き出されていることを確認
    new_vqm = sys.modules.get("scratch.verify_video_quality_matrix")
    graded_previews_dir = new_vqm.GRADED_PREVIEWS_DIR if new_vqm else vqm.GRADED_PREVIEWS_DIR
    
    report_path = os.path.join(graded_previews_dir, "video_quality_verification_matrix.json")
    try:
        assert os.path.exists(report_path)
    finally:
        # 本物の環境を汚さないようにクリーンアップ
        if os.path.exists(report_path):
            try:
                os.remove(report_path)
            except Exception:
                pass


def test_verify_micro_empty_history_file(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    # weakness_analysis_history.json が存在して中身が空の場合のテスト
    with open(graded_dir / "weakness_analysis_history.json", "w", encoding="utf-8") as f:
        json.dump([], f)
        
    results = vqm.verify_micro()
    assert results["vision_overlap_clean"] is True
    assert results["vision_overlap_count"] == 0


def test_verify_micro_no_video_name_in_index(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    # index.json は存在するが、中に "video" キーが含まれていない場合のテスト
    index_data = {
        # "video" が欠損
        "frames": []
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)
        
    results = vqm.verify_micro()
    assert results["av_sync_ok"] is False
    assert results["av_start_offset_ms"] == -1


def test_verify_macro_invalid_json_index(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    # index.json を壊れた JSON フォーマットで作成
    (latest_dir / "index.json").write_text("{invalid_json", encoding="utf-8")
    results = vqm.verify_macro()
    assert results["index_json_exist"] is False
    assert results["duration_match"] is False
    assert results["frames_count"] == 0


def test_verify_mezzo_invalid_json_history(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    (graded_dir / "weakness_analysis_history.json").write_text("invalid_json", encoding="utf-8")
    results = vqm.verify_mezzo()
    assert results["has_history"] is False


def test_verify_micro_invalid_json_history(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    (graded_dir / "weakness_analysis_history.json").write_text("invalid_json", encoding="utf-8")
    results = vqm.verify_micro()
    assert results["vision_overlap_clean"] is True  # デフォルト値にフォールバック
    assert results["vision_overlap_count"] == 0


def test_verify_micro_invalid_json_index(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    (latest_dir / "index.json").write_text("invalid_json", encoding="utf-8")
    results = vqm.verify_micro()
    assert results["av_sync_ok"] is False
    assert results["av_start_offset_ms"] == -1


def test_verify_micro_srt_read_error(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    # SRT ファイルを配置
    srt_dir = tmp_path / "vault-outputs"
    srt_dir.mkdir(exist_ok=True)
    srt_file = srt_dir / "soul_narrative_subtitles.srt"
    srt_file.write_text("dummy", encoding="utf-8")
    
    # open を mock して、srt_file のオープン時に OSError を投げるようにする
    original_open = open
    def mock_open(file, *args, **kwargs):
        if str(file) == str(srt_file):
            raise OSError("Permission denied")
        return original_open(file, *args, **kwargs)
        
    with mock.patch("builtins.open", side_effect=mock_open):
        results = vqm.verify_micro()
        assert results["clustering_ok"] is False


def test_verify_micro_clustering_type_error(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    srt_dir = tmp_path / "vault-outputs"
    srt_dir.mkdir(exist_ok=True)
    (srt_dir / "soul_narrative_subtitles.srt").write_text("1\n00:00:01,000 --> 00:00:04,500\n山田\n", encoding="utf-8")
    
    # index.json の frames をリストではなく整数値にして例外を発生させる
    index_data = {
        "video": "preview_video.mp4",
        "frames": 12345
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)
        
    results = vqm.verify_micro()
    assert results["clustering_ok"] is False
    assert results["clustering_stats"] == {
        "active_speech_count": 0,
        "scene_boundary_count": 0,
        "silent_gap_count": 0
    }


def test_verify_micro_clustering_non_dict_frame(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    srt_dir = tmp_path / "vault-outputs"
    srt_dir.mkdir(exist_ok=True)
    (srt_dir / "soul_narrative_subtitles.srt").write_text("1\n00:00:01,000 --> 00:00:04,500\n山田\n", encoding="utf-8")
    
    # index.json の frames に辞書ではない値を混ぜる
    index_data = {
        "video": "preview_video.mp4",
        "frames": [
            {"timestamp": 2.0},
            None,
            "invalid_frame",
            {"timestamp": 10.0}
        ]
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)
        
    results = vqm.verify_micro()
    assert results["clustering_ok"] is True
    assert results["clustering_stats"]["active_speech_count"] == 1
    assert results["clustering_stats"]["silent_gap_count"] == 1


def test_main_write_error(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    raw_files = ["シーン01_前編.mp4", "シーン02_ゲスト書道.mp4", "シーン03_後編01.mp4", "シーン04_後編02.mp4"]
    for f in raw_files:
        (raw_dir / f).write_text("dummy", encoding="utf-8")
    index_data = {
        "video": "preview_video.mp4",
        "duration": 15000.0,
        "frames": [{"timestamp": 2.0}]
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)
    (graded_dir / "youtube_metadata.json").write_text("{}", encoding="utf-8")
    
    # open を mock して、レポートファイル書き込み時に例外
    report_file_path = graded_dir / "video_quality_verification_matrix.json"
    original_open = open
    def mock_open(file, mode="r", *args, **kwargs):
        if str(file) == str(report_file_path) and "w" in mode:
            raise OSError("ReadOnly filesystem")
        return original_open(file, mode, *args, **kwargs)
        
    with mock.patch("builtins.open", side_effect=mock_open):
        vqm.main()
        
    assert not report_file_path.exists()


def test_parse_srt_time_robustness():
    # 例外を発生させる入力
    assert vqm.parse_srt_time(None) == 0.0
    assert vqm.parse_srt_time("00:01:23,abc") == 0.0
    assert vqm.parse_srt_time("abc") == 0.0


def test_verify_mezzo_invalid_scores_type(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    # scores が辞書ではない場合
    history_data = [
        {
            "timestamp": "2026-05-21T10:00:00",
            "scores": None,  # dict ではない
            "passed": False,
            "vision_violations": 0
        }
    ]
    with open(graded_dir / "weakness_analysis_history.json", "w", encoding="utf-8") as f:
        json.dump(history_data, f)
        
    results = vqm.verify_mezzo()
    assert results["has_history"] is True
    assert results["all_categories_above_80"] is True  # scores が空として扱われるため True


def test_verify_mezzo_invalid_score_value_type(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    # scores 内に数値以外の値がある場合
    history_data = [
        {
            "timestamp": "2026-05-21T10:00:00",
            "scores": {
                "nhk_compliance": "invalid_score",  # 数値ではない
                "total_score": 90
            },
            "passed": True,
            "vision_violations": 0
        }
    ]
    with open(graded_dir / "weakness_analysis_history.json", "w", encoding="utf-8") as f:
        json.dump(history_data, f)
        
    results = vqm.verify_mezzo()
    assert results["has_history"] is True
    assert results["total_score"] == 90
    assert results["all_categories_above_80"] is True  # nhk_compliance がスキップされるため


def test_verify_micro_invalid_frame_timestamp_type(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    
    srt_dir = tmp_path / "vault-outputs"
    srt_dir.mkdir(exist_ok=True)
    (srt_dir / "soul_narrative_subtitles.srt").write_text("1\n00:00:01,000 --> 00:00:04,500\n山田\n", encoding="utf-8")
    
    # index.json の frames に timestamp が数値ではないフレームを混ぜる
    index_data = {
        "video": "preview_video.mp4",
        "frames": [
            {"timestamp": "invalid_timestamp_string"},  # 数値ではない
            {"timestamp": 2.0}
        ]
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)
        
    results = vqm.verify_micro()
    assert results["clustering_ok"] is True
    assert results["clustering_stats"]["active_speech_count"] == 1


def test_verify_micro_av_sync_large_offset(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs

    # SRT ファイルの作成
    srt_dir = tmp_path / "vault-outputs"
    srt_dir.mkdir(exist_ok=True)
    (srt_dir / "soul_narrative_subtitles.srt").write_text("1\\n00:00:01,000 --> 00:00:04,500\\n山田\\n", encoding="utf-8")

    # index.json の作成 (動画ファイル名指定)
    index_data = {
        "video": "preview_video.mp4",
        "frames": []
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)

    # 動画ファイルの作成
    (tmp_path / "preview_video.mp4").write_text("dummy video", encoding="utf-8")

    # A/V ズレが 60ms (0.06秒) の場合
    def mock_run_command(cmd):
        if "select_streams v:0" in cmd:
            return 0, "0.000000", ""
        elif "select_streams a:0" in cmd:
            return 0, "0.060000", ""
        return 0, "", ""

    with mock.patch("scratch.verify_video_quality_matrix.run_command", side_effect=mock_run_command):
        results = vqm.verify_micro()
        assert results["av_sync_ok"] is False
        assert abs(results["av_start_offset_ms"] - 60.0) < 1e-5


def test_verify_micro_clustering_only_silent_gap(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs

    srt_dir = tmp_path / "vault-outputs"
    srt_dir.mkdir(exist_ok=True)
    # 発話区間が 1秒から4秒
    (srt_dir / "soul_narrative_subtitles.srt").write_text("1\\n00:00:01,000 --> 00:00:04,000\\n山田\\n", encoding="utf-8")

    # フレームが 10.0 秒 (発話区間 1-4 から遠く離れ、境界からも離れているため silent_gap になる)
    index_data = {
        "video": "preview_video.mp4",
        "frames": [
            {"timestamp": 10.0}
        ]
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)

    results = vqm.verify_micro()
    assert results["clustering_ok"] is False
    assert results["clustering_stats"]["active_speech_count"] == 0
    assert results["clustering_stats"]["scene_boundary_count"] == 0
    assert results["clustering_stats"]["silent_gap_count"] == 1


def test_verify_mezzo_invalid_score_value_type_fail(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs

    # 数値ではないスコアと、80未満の有効なスコアが混在している場合
    history_data = [
        {
            "timestamp": "2026-05-21T10:00:00",
            "scores": {
                "nhk_compliance": "invalid_score",  # 数値ではない
                "constitution": 75,  # 80未満
                "total_score": 90
            },
            "passed": False,
            "vision_violations": 0
        }
    ]
    with open(graded_dir / "weakness_analysis_history.json", "w", encoding="utf-8") as f:
        json.dump(history_data, f)

    results = vqm.verify_mezzo()
    assert results["has_history"] is True
    assert results["all_categories_above_80"] is False  # constitution が 80 未満のため


def test_parse_srt_time_extra_cases():
    # ミリ秒が欠落しているフォーマット (partsが3つになるため 0.0 が返る)
    assert vqm.parse_srt_time("00:01:23") == 0.0
    # ミリ秒が2桁の場合 (partsは4つだが、map(int, parts) によりパース可能)
    assert vqm.parse_srt_time("00:01:23,45") == 83.045
    # マイナス記号など数値変換できない文字が入っている場合 (ValueError等で 0.0)
    assert vqm.parse_srt_time("-00:01:23,450") == 83.45
    # 極端に大きい値
    assert vqm.parse_srt_time("99:99:99,999") == 99 * 3600.0 + 99 * 60.0 + 99 + 0.999


def test_verify_micro_proper_noun_empty_dict(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs

    # entries が空リストのダミー固有名詞辞書
    dummy_dict = DummyProperNounDict([])
    with mock.patch.dict("sys.modules", {"proper_noun_dict": dummy_dict}):
        with mock.patch("proper_noun_dict.proper_noun_dict", dummy_dict, create=True):
            # soul_narrative 関連の SRT ファイルを作成
            srt_dir = tmp_path / "vault-outputs"
            srt_dir.mkdir(exist_ok=True)
            (srt_dir / "soul_narrative_subtitles.srt").write_text("1\n00:00:01,000 --> 00:00:04,500\n何かテキスト\n", encoding="utf-8")

            results = vqm.verify_micro()
            # 辞書が空なので、matched_words は空リストになり proper_nouns_present は False
            assert results["proper_nouns_present"] is False


def test_verify_micro_av_sync_invalid_video_keys(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs

    # index.json の video キーが空文字列の場合
    index_data = {
        "video": "",
        "frames": []
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)

    results = vqm.verify_micro()
    assert results["av_sync_ok"] is False
    assert results["av_start_offset_ms"] == -1


def test_verify_micro_av_sync_empty_command_output(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs

    index_data = {
        "video": "preview_video.mp4",
        "frames": []
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)

    # 動画ファイルの作成
    (tmp_path / "preview_video.mp4").write_text("dummy video", encoding="utf-8")

    # ffprobe のコマンド実行結果が空文字列や改行のみの場合
    with mock.patch("scratch.verify_video_quality_matrix.run_command", return_value=(0, "\n\n", "")):
        results = vqm.verify_micro()
        assert results["av_sync_ok"] is False
        assert results["av_start_offset_ms"] == -1


def test_verify_micro_clustering_missing_timestamp_key(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs

    srt_dir = tmp_path / "vault-outputs"
    srt_dir.mkdir(exist_ok=True)
    (srt_dir / "soul_narrative_subtitles.srt").write_text("1\n00:00:01,000 --> 00:00:04,500\n山田\n", encoding="utf-8")

    # frames 内の辞書に "timestamp" キーがないオブジェクトが含まれる場合
    index_data = {
        "video": "preview_video.mp4",
        "frames": [
            {},  # timestamp なし
            {"timestamp": 2.0}
        ]
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)

    results = vqm.verify_micro()
    assert results["clustering_ok"] is True
    assert results["clustering_stats"]["active_speech_count"] == 1


def test_verify_micro_clustering_boundary_ts(setup_dirs, mock_proper_noun_dict):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs

    srt_dir = tmp_path / "vault-outputs"
    srt_dir.mkdir(exist_ok=True)
    # 発話区間: 1.0秒 〜 4.5秒
    (srt_dir / "soul_narrative_subtitles.srt").write_text("1\n00:00:01,000 --> 00:00:04,500\n山田\n", encoding="utf-8")

    # timestamp がちょうど境界値 (1.0秒) のフレーム
    index_data = {
        "video": "preview_video.mp4",
        "frames": [
            {"timestamp": 1.0}
        ]
    }
    with open(latest_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f)

    results = vqm.verify_micro()
    # ちょうど境界値 1.0 秒は 1.0 <= ts <= 4.5 なので active_speech に入るはず
    assert results["clustering_ok"] is True
    assert results["clustering_stats"]["active_speech_count"] == 1
    assert results["clustering_stats"]["scene_boundary_count"] == 0


def test_verify_mezzo_invalid_history_score_element_type(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs

    # scores 自体が辞書型ではなく文字列である場合
    history_data = [
        {
            "timestamp": "2026-05-21T10:00:00",
            "scores": "not_a_dict_score",
            "passed": False,
            "vision_violations": 0
        }
    ]
    with open(graded_dir / "weakness_analysis_history.json", "w", encoding="utf-8") as f:
        json.dump(history_data, f)

    results = vqm.verify_mezzo()
    assert results["has_history"] is True
    # scores が辞書型でないため results に "total_score" 等は入らない
    assert results["total_score"] == 0
    assert results["all_categories_above_80"] is True


def test_verify_micro_proper_noun_attribute_error(setup_dirs):
    tmp_path, raw_dir, graded_dir, latest_dir = setup_dirs
    # entries 属性が存在しないダミーオブジェクトを proper_noun_dict として mock する
    # これにより AttributeError が発生し、except (ImportError, AttributeError, OSError) で処理される
    class InvalidProperNounDict:
        pass

    with mock.patch.dict("sys.modules", {"proper_noun_dict": InvalidProperNounDict}):
        results = vqm.verify_micro()
        assert results["proper_nouns_present"] is False


def test_run_command_subprocess_error():
    # subprocess.SubprocessError を発生させて、run_command が適切に処理するかテスト
    with mock.patch("subprocess.run", side_effect=subprocess.SubprocessError("Subprocess error")):
        code, stdout, stderr = vqm.run_command("invalid_command_here")
        assert code == -1
        assert "Subprocess error" in stderr
