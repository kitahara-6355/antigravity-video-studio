"""
test_pipeline_e2e.py — E2E パイプライン統合テスト
"""

import os
import subprocess
import shutil
import pytest
from unittest.mock import patch, MagicMock

from backend.video_pipeline.pipeline_coordinator import (
    PipelineCoordinator,
    STAGE_ORDER,
)


@pytest.fixture(scope="module")
def sample_video_file(tmp_path_factory):
    """FFmpeg を使用して5秒のテスト用ダミー動画（音声・動画トラック含む）を動的生成する fixture。

    FFmpegが利用できない場合はバイナリダミーファイルをフォールバック生成。
    """
    tmp_dir = tmp_path_factory.mktemp("e2e_data")
    audio_path = tmp_dir / "test_audio.wav"
    video_path = tmp_dir / "test_video.mp4"

    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        try:
            # 1. 音声ファイルの生成
            cmd_audio = [
                ffmpeg_bin, "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                "-f", "lavfi", "-i", "anullsrc=duration=2",
                "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1",
                str(audio_path)
            ]
            subprocess.run(cmd_audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            # 2. 動画ファイルの生成
            cmd_video = [
                ffmpeg_bin, "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=5",
                "-i", str(audio_path),
                "-c:v", "libx264", "-shortest",
                str(video_path)
            ]
            subprocess.run(cmd_video, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            if video_path.exists():
                return str(video_path)
        except Exception:
            pass

    # FFmpeg非存在/失敗時のフォールバック
    video_path.write_bytes(b"dummy mp4 video bytes header and content")
    return str(video_path)


def test_pipeline_e2e_full_run(tmp_path, sample_video_file):
    """パイプライン全ステージの E2E 実行と動作検証。
    auto-editor, faster-whisper, stable-ts が未インストールでもフォールバックで完走することを検証。
    """
    work_dir = str(tmp_path / "work")
    coordinator = PipelineCoordinator(work_dir=work_dir)

    # 外部依存ツールの内部実行をフォールバックモードにするモック（FFmpeg呼び出しも安全に制御）
    with patch("backend.video_pipeline.auto_editor_wrapper.AutoEditorWrapper.run_smart_cut", side_effect=Exception("auto-editor not installed")), \
         patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper.is_available", return_value=False), \
         patch("backend.video_pipeline.transcription_service.TranscriptionService._is_whisper_available", return_value=False):

        result = coordinator.run_pipeline(sample_video_file)

        assert result.success is True
        assert len(result.stages_completed) == len(STAGE_ORDER)
        assert "smart_cut" in result.stages_completed
        assert "transcribe" in result.stages_completed
        assert "quality_gate" in result.stages_completed


def test_pipeline_smart_cut_fallback(tmp_path, sample_video_file):
    """smart_cut ステージのフォールバック動作を個別に検証"""
    coordinator = PipelineCoordinator(work_dir=str(tmp_path / "work"))

    with patch("backend.video_pipeline.auto_editor_wrapper.AutoEditorWrapper.run_smart_cut", side_effect=Exception("Simulated error")):
        stage_result = coordinator.run_stage("smart_cut", {"input_path": sample_video_file})

        assert stage_result.success is True
        assert stage_result.stage_name == "smart_cut"
        assert "normalized_path" in stage_result.output_data
        assert stage_result.output_data.get("smart_cut_applied") is False


def test_pipeline_transcribe_fallback(tmp_path, sample_video_file):
    """transcribe ステージのフォールバック動作を個別に検証"""
    coordinator = PipelineCoordinator(work_dir=str(tmp_path / "work"))

    with patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper.is_available", return_value=False), \
         patch("backend.video_pipeline.transcription_service.TranscriptionService._is_whisper_available", return_value=False), \
         patch("backend.video_pipeline.transcription_service.TranscriptionService._get_audio_duration", return_value=5.0):

        stage_result = coordinator.run_stage("transcribe", {"audio_path": sample_video_file})

        assert stage_result.success is True
        assert stage_result.stage_name == "transcribe"
        assert "transcript" in stage_result.output_data or "transcript_segments" in stage_result.output_data
