import sys
import os
import json
import subprocess
import pytest
import runpy
from pathlib import Path
from unittest import mock

from backend.generate_full_inspection import (
    calculate_sha256,
    get_git_commit,
    update_previews_metadata,
    get_video_duration,
    extract_frame,
    load_segments_from_cache,
    main,
)

# 1. calculate_sha256
def test_calculate_sha256_success(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_bytes(b"hello world")
    h = calculate_sha256(str(test_file))
    assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

def test_calculate_sha256_error():
    h = calculate_sha256("non_existent_file.txt")
    assert h == "error"

# 2. get_git_commit
@mock.patch("subprocess.run")
def test_get_git_commit_success(mock_run):
    mock_run.return_value = mock.Mock(returncode=0, stdout=" abc123commit \n")
    assert get_git_commit() == "abc123commit"

@mock.patch("subprocess.run")
def test_get_git_commit_failure(mock_run):
    mock_run.return_value = mock.Mock(returncode=1)
    assert get_git_commit() == "unknown"

@mock.patch("subprocess.run")
def test_get_git_commit_exception(mock_run):
    mock_run.side_effect = subprocess.SubprocessError("git error")
    assert get_git_commit() == "unknown"

# 3. update_previews_metadata
def test_update_previews_metadata_new(tmp_path):
    meta_path = tmp_path / "previews_metadata.json"
    update_previews_metadata(
        metadata_path=str(meta_path),
        version="v1.0.0",
        video_file="dummy.mp4",
        video_hash="hash123",
        git_commit="commit123",
        duration=120.0,
        segment_count=5,
        generated_frames=[(10.0, "/path/to/frame.jpg")]
    )
    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["current_version"] == "v1.0.0"
    assert len(data["history"]) == 1
    assert data["history"][0]["version"] == "v1.0.0"

def test_update_previews_metadata_update_existing(tmp_path):
    meta_path = tmp_path / "previews_metadata.json"
    initial_data = {
        "current_version": "v1.0.0",
        "history": [
            {
                "version": "v1.0.0",
                "video_file": "old.mp4",
                "video_hash": "old_hash",
                "timestamp": "2026-06-04T00:00:00",
                "git_commit": "old_commit",
                "duration": 100.0,
                "segment_count": 3,
                "frames": []
            }
        ]
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(initial_data, f)

    update_previews_metadata(
        metadata_path=str(meta_path),
        version="v1.0.0",
        video_file="new.mp4",
        video_hash="new_hash",
        git_commit="new_commit",
        duration=120.0,
        segment_count=5,
        generated_frames=[(10.0, "/path/to/frame.jpg")]
    )

    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["history"]) == 1
    assert data["history"][0]["video_file"] == "new.mp4"

def test_update_previews_metadata_append_existing(tmp_path):
    meta_path = tmp_path / "previews_metadata.json"
    initial_data = {
        "current_version": "v1.0.0",
        "history": [
            {
                "version": "v1.0.0",
                "video_file": "old.mp4",
                "video_hash": "old_hash",
                "timestamp": "2026-06-04T00:00:00",
                "git_commit": "old_commit",
                "duration": 100.0,
                "segment_count": 3,
                "frames": []
            }
        ]
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(initial_data, f)

    update_previews_metadata(
        metadata_path=str(meta_path),
        version="v2.0.0",
        video_file="new.mp4",
        video_hash="new_hash",
        git_commit="new_commit",
        duration=120.0,
        segment_count=5,
        generated_frames=[(10.0, "/path/to/frame.jpg")]
    )

    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["history"]) == 2
    assert data["current_version"] == "v2.0.0"

def test_update_previews_metadata_corrupt_json(tmp_path):
    meta_path = tmp_path / "previews_metadata.json"
    meta_path.write_text("invalid json", encoding="utf-8")

    update_previews_metadata(
        metadata_path=str(meta_path),
        version="v1.0.0",
        video_file="dummy.mp4",
        video_hash="hash123",
        git_commit="commit123",
        duration=120.0,
        segment_count=5,
        generated_frames=[(10.0, "/path/to/frame.jpg")]
    )
    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["current_version"] == "v1.0.0"
    assert len(data["history"]) == 1

# 4. get_video_duration
@mock.patch("subprocess.run")
def test_get_video_duration(mock_run):
    mock_run.return_value = mock.Mock(stdout='{"format": {"duration": "123.45"}}', returncode=0)
    assert get_video_duration("dummy.mp4") == 123.45

# 5. extract_frame
@mock.patch("subprocess.run")
@mock.patch("backend.generate_full_inspection.Path.exists")
def test_extract_frame_success(mock_exists, mock_run):
    mock_exists.return_value = True
    assert extract_frame("dummy.mp4", 10.0, "output.jpg") is True

@mock.patch("subprocess.run")
@mock.patch("backend.generate_full_inspection.Path.exists")
def test_extract_frame_failure(mock_exists, mock_run):
    mock_exists.return_value = False
    assert extract_frame("dummy.mp4", 10.0, "output.jpg") is False

# 6. load_segments_from_cache
@mock.patch("backend.generate_full_inspection.Path.glob")
def test_load_segments_from_cache_no_candidates(mock_glob):
    mock_glob.return_value = []
    assert load_segments_from_cache() == []

@mock.patch("backend.generate_full_inspection.Path.glob")
@mock.patch("builtins.open", new_callable=mock.mock_open, read_data='{"start": 10.0, "end": 12.0}\n{"start": 30.0, "end": 35.0}\n')
def test_load_segments_from_cache_success(mock_open, mock_glob):
    mock_file = mock.Mock()
    mock_file.stat.return_value.st_mtime = 12345
    mock_file.name = "dummy_whisper.jsonl"
    mock_glob.return_value = [mock_file]
    
    segments = load_segments_from_cache()
    assert len(segments) == 2
    assert segments[0]["start"] == 10.0

# 7. main
@mock.patch("backend.generate_full_inspection.get_video_duration")
@mock.patch("backend.generate_full_inspection.load_segments_from_cache")
@mock.patch("backend.generate_full_inspection.extract_frame")
@mock.patch("backend.generate_full_inspection.calculate_sha256")
@mock.patch("backend.generate_full_inspection.get_git_commit")
@mock.patch("backend.generate_full_inspection.update_previews_metadata")
def test_main_with_arguments(
    mock_update, mock_git, mock_sha, mock_extract, mock_load, mock_duration, tmp_path
):
    # フレーム抽出が50枚以上になるようにセグメント数を増やす (199行目の print 処理をカバーするため)
    mock_duration.return_value = 2000.0
    mock_load.return_value = [{"start": float(i * 20), "end": float(i * 20 + 2)} for i in range(60)]
    # 全ての抽出を成功させる
    mock_extract.return_value = True
    mock_sha.return_value = "sha"
    mock_git.return_value = "git"

    output_dir = tmp_path / "output"
    video_path = tmp_path / "video.mp4"
    video_path.touch()

    with mock.patch("sys.argv", [
        "generate_full_inspection.py",
        "--output-dir", str(output_dir),
        "--video-path", str(video_path),
        "--version", "v1.0.0"
    ]):
        main()

    assert output_dir.exists()
    assert (output_dir / "index.json").exists()

@mock.patch("backend.generate_full_inspection.get_video_duration")
@mock.patch("backend.generate_full_inspection.load_segments_from_cache")
@mock.patch("backend.generate_full_inspection.extract_frame")
@mock.patch("backend.generate_full_inspection.calculate_sha256")
@mock.patch("backend.generate_full_inspection.get_git_commit")
@mock.patch("backend.generate_full_inspection.update_previews_metadata")
@mock.patch("glob.glob")
@mock.patch("os.path.exists")
def test_main_no_arguments_glob_success(
    mock_exists, mock_glob, mock_update, mock_git, mock_sha, mock_extract, mock_load, mock_duration, tmp_path
):
    mock_duration.return_value = 60.0
    mock_load.return_value = []
    mock_extract.side_effect = [True, False] # 1枚成功、1枚失敗
    mock_sha.return_value = "sha"
    mock_git.return_value = "git"
    mock_glob.return_value = ["/dummy/preview_001.mp4"]
    mock_exists.return_value = True

    with mock.patch("backend.generate_full_inspection.Path.mkdir") as mock_mkdir:
        with mock.patch("builtins.open", mock.mock_open()) as mock_file:
            with mock.patch("sys.argv", ["generate_full_inspection.py"]):
                main()
            mock_mkdir.assert_called()

@mock.patch("glob.glob")
@mock.patch("os.path.exists")
def test_main_no_previews_no_fallback(mock_exists, mock_glob):
    mock_glob.return_value = []
    mock_exists.return_value = False

    with mock.patch("sys.argv", ["generate_full_inspection.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1

@mock.patch("glob.glob")
@mock.patch("os.path.exists")
@mock.patch("backend.generate_full_inspection.get_video_duration")
@mock.patch("backend.generate_full_inspection.load_segments_from_cache")
def test_main_fallback_exists(
    mock_load, mock_duration, mock_exists, mock_glob
):
    mock_glob.return_value = []
    # os.path.exists が fallback パスに対して True を返すようにする
    def exists_side_effect(path):
        if "soul_narrative_full_v1.mp4" in path:
            return True
        return False
    mock_exists.side_effect = exists_side_effect
    mock_duration.return_value = 10.0
    mock_load.return_value = []

    with mock.patch("backend.generate_full_inspection.Path.mkdir"):
        with mock.patch("backend.generate_full_inspection.extract_frame") as mock_extract:
            mock_extract.return_value = True
            with mock.patch("builtins.open", mock.mock_open()):
                with mock.patch("backend.generate_full_inspection.calculate_sha256"):
                    with mock.patch("backend.generate_full_inspection.get_git_commit"):
                        with mock.patch("backend.generate_full_inspection.update_previews_metadata"):
                            with mock.patch("sys.argv", ["generate_full_inspection.py"]):
                                main()

# 8. run as __main__ (240行目をカバーするため)
@mock.patch("subprocess.run")
@mock.patch("backend.generate_full_inspection.get_video_duration")
@mock.patch("backend.generate_full_inspection.load_segments_from_cache")
@mock.patch("backend.generate_full_inspection.extract_frame")
@mock.patch("backend.generate_full_inspection.calculate_sha256")
@mock.patch("backend.generate_full_inspection.get_git_commit")
@mock.patch("backend.generate_full_inspection.update_previews_metadata")
def test_main_execution_as_main(
    mock_update, mock_git, mock_sha, mock_extract, mock_load, mock_duration, mock_sub_run, tmp_path
):
    mock_duration.return_value = 10.0
    mock_load.return_value = []
    mock_extract.return_value = True
    mock_sha.return_value = "sha"
    mock_git.return_value = "git"
    mock_sub_run.return_value = mock.Mock(stdout='{"format": {"duration": "10.0"}}', returncode=0)
    
    output_dir = tmp_path / "output"
    video_path = tmp_path / "video.mp4"
    video_path.touch()

    with mock.patch("sys.argv", [
        "generate_full_inspection.py",
        "--output-dir", str(output_dir),
        "--video-path", str(video_path)
    ]):
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*found in sys.modules.*")
            run_globals = runpy.run_module("backend.generate_full_inspection", run_name="__main__")
    assert "main" in run_globals


# 9. 例外処理・エラーハンドリング強化の追加テスト

# get_video_duration の例外処理テスト
@mock.patch("subprocess.run")
def test_get_video_duration_returncode_error(mock_run):
    mock_run.return_value = mock.Mock(stdout='{"format": {"duration": "123.45"}}', returncode=1)
    assert get_video_duration("dummy.mp4") == 0.0

@mock.patch("subprocess.run")
def test_get_video_duration_empty_stdout(mock_run):
    mock_run.return_value = mock.Mock(stdout='', returncode=0)
    assert get_video_duration("dummy.mp4") == 0.0

@mock.patch("subprocess.run")
def test_get_video_duration_invalid_json(mock_run):
    mock_run.return_value = mock.Mock(stdout='invalid json', returncode=0)
    assert get_video_duration("dummy.mp4") == 0.0

@mock.patch("subprocess.run")
def test_get_video_duration_missing_keys(mock_run):
    mock_run.return_value = mock.Mock(stdout='{"other_key": {}}', returncode=0)
    assert get_video_duration("dummy.mp4") == 0.0

@mock.patch("subprocess.run")
def test_get_video_duration_invalid_float(mock_run):
    mock_run.return_value = mock.Mock(stdout='{"format": {"duration": "not_a_float"}}', returncode=0)
    assert get_video_duration("dummy.mp4") == 0.0

@mock.patch("subprocess.run")
def test_get_video_duration_subprocess_error(mock_run):
    mock_run.side_effect = subprocess.SubprocessError("subprocess error")
    assert get_video_duration("dummy.mp4") == 0.0


# extract_frame の例外処理テスト
@mock.patch("subprocess.run")
def test_extract_frame_subprocess_error(mock_run):
    mock_run.side_effect = subprocess.SubprocessError("subprocess error")
    assert extract_frame("dummy.mp4", 10.0, "output.jpg") is False

@mock.patch("subprocess.run")
def test_extract_frame_returncode_error(mock_run):
    mock_run.return_value = mock.Mock(returncode=1)
    assert extract_frame("dummy.mp4", 10.0, "output.jpg") is False


# load_segments_from_cache の例外処理テスト
@mock.patch("backend.generate_full_inspection.Path.exists")
def test_load_segments_from_cache_dir_not_exists(mock_exists):
    mock_exists.return_value = False
    assert load_segments_from_cache() == []

@mock.patch("backend.generate_full_inspection.Path.glob")
@mock.patch("backend.generate_full_inspection.Path.exists")
def test_load_segments_from_cache_glob_os_error(mock_exists, mock_glob):
    mock_exists.return_value = True
    mock_glob.side_effect = OSError("glob error")
    assert load_segments_from_cache() == []

@mock.patch("backend.generate_full_inspection.Path.glob")
@mock.patch("backend.generate_full_inspection.Path.exists")
@mock.patch("builtins.open")
def test_load_segments_from_cache_open_os_error(mock_open, mock_exists, mock_glob):
    mock_exists.return_value = True
    mock_file = mock.Mock()
    mock_file.stat.return_value.st_mtime = 12345
    mock_file.name = "dummy_whisper.jsonl"
    mock_glob.return_value = [mock_file]
    mock_open.side_effect = OSError("open error")
    
    assert load_segments_from_cache() == []

@mock.patch("backend.generate_full_inspection.Path.glob")
@mock.patch("backend.generate_full_inspection.Path.exists")
@mock.patch("builtins.open", new_callable=mock.mock_open, read_data='{"start": 10.0, "end": 12.0}\ncorrupt json line\n{"start": 30.0, "end": 35.0}\n')
def test_load_segments_from_cache_partial_corrupt_json(mock_open, mock_exists, mock_glob):
    mock_exists.return_value = True
    mock_file = mock.Mock()
    mock_file.stat.return_value.st_mtime = 12345
    mock_file.name = "dummy_whisper.jsonl"
    mock_glob.return_value = [mock_file]
    
    segments = load_segments_from_cache()
    # 正常な2行のみロードされ、破損行はスキップされる
    assert len(segments) == 2
    assert segments[0]["start"] == 10.0
    assert segments[1]["start"] == 30.0


# update_previews_metadata の書き込み例外処理テスト
@mock.patch("builtins.open")
def test_update_previews_metadata_write_failure(mock_open, tmp_path):
    meta_path = tmp_path / "previews_metadata.json"
    # 読み込みは成功（空のファイル）、書き込み時にエラーを投げる
    mock_open.side_effect = [mock.mock_open(read_data="{}").return_value, OSError("write error")]
    
    # 呼び出しても例外でクラッシュせず正常終了する
    update_previews_metadata(
        metadata_path=str(meta_path),
        version="v1.0.0",
        video_file="dummy.mp4",
        video_hash="hash123",
        git_commit="commit123",
        duration=120.0,
        segment_count=5,
        generated_frames=[(10.0, "/path/to/frame.jpg")]
    )


# main の動画尺 <= 0 判定テスト
@mock.patch("backend.generate_full_inspection.get_video_duration")
def test_main_invalid_duration(mock_duration):
    mock_duration.return_value = 0.0
    with mock.patch("sys.argv", ["generate_full_inspection.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1

