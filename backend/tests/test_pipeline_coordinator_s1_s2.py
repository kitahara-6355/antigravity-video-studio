import os
import sys
import time
from pathlib import Path
from unittest.mock import patch
import pytest

# パス設定
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from backend.video_pipeline.pipeline_coordinator import PipelineCoordinator

FIXTURE_DIR = Path(backend_dir) / "tests" / "fixtures" / "raw_videos"
TEST_SHORT = FIXTURE_DIR / "test_short_15s.mp4"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 実FFmpeg実行統合テスト (@pytest.mark.slow)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@pytest.mark.slow
def test_pipeline_s1_s2_integration_real(tmp_path):
    """
    S1(ingest) -> S2(audio_extract) の実FFmpeg実行統合テスト。
    15秒動画 of 処理が60秒以内に完了し、WAVが抽出されることを検証する。
    """
    if not TEST_SHORT.exists():
        pytest.skip(f"テスト用の実動画ファイルが存在しません: {TEST_SHORT}")

    # 一時ディレクトリを作業ディレクトリとして使用
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    coordinator = PipelineCoordinator(work_dir=str(work_dir))

    # 時間計測開始
    start_time = time.time()

    # S1(ingest) -> S2(audio_extract) のみを実行
    result = coordinator.run_pipeline(str(TEST_SHORT), stages=["ingest", "audio_extract"])

    elapsed = time.time() - start_time

    # 1. 成功することの検証
    assert result.success is True
    assert result.error_message == ""
    assert result.stages_completed == ["ingest", "audio_extract"]

    # 2. 処理時間の検証 (15秒動画の処理が60秒以内に完了)
    assert elapsed < 60.0
    assert result.duration_seconds < 60.0

    # 3. データ受け渡し（パスの整合性）の検証
    job_id = result.job_id
    job_dir = work_dir / job_id

    # S1出力（正規化MP4）の存在確認
    normalized_video_path = job_dir / f"{TEST_SHORT.stem}_normalized.mp4"
    assert normalized_video_path.exists()
    assert normalized_video_path.stat().st_size > 0

    # S2出力（WAV抽出）の存在確認
    extracted_audio_path = job_dir / f"{normalized_video_path.stem}_audio.wav"
    assert extracted_audio_path.exists()
    assert extracted_audio_path.stat().st_size > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. safe_popen_mock を使用したモックテスト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def test_pipeline_s1_s2_integration_mock(tmp_path, safe_popen_mock):
    """
    safe_popen_mock を使用して、実際のFFmpeg呼び出しを行わずに
    S1(ingest) -> S2(audio_extract) の連携フローを検証する。
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    coordinator = PipelineCoordinator(work_dir=str(work_dir))

    dummy_input = tmp_path / "dummy_short.mp4"
    dummy_input.write_bytes(b"\x00" * 10)

    # subprocess.Popenのサイドエフェクト。
    # コマンドの出力ファイル引数（通常最後の引数）を取得し、ダミーファイルを生成する。
    def popen_side_effect(*args, **kwargs):
        cmd = args[0]
        print(f"\nDEBUG popen_side_effect cmd: {cmd}")
        # コマンドの最後の引数が出力ファイルパスの可能性があるため、ダミーファイルを書き出す
        output_file = cmd[-1]
        if not output_file.startswith("-") and ("/" in output_file or "\\" in output_file):
            out_path = Path(output_file)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if not out_path.exists():
                out_path.write_bytes(b"\x00" * 10)

        # コマンドに応じてモックオブジェクトを返却
        proc = safe_popen_mock(returncode=0)
        proc.__enter__.return_value = proc  # subprocess.run()でのwith Popen対策

        if "ffprobe" in cmd[0]:
            proc.communicate.return_value = (
                '{"streams":[{"codec_type":"audio","duration":"15.0","sample_rate":"44100","channels":2}]}',
                ""
            )
            return proc
        else:
            proc.communicate.return_value = ("", "")
            return proc

    with patch("subprocess.Popen", side_effect=popen_side_effect) as mock_popen:
        result = coordinator.run_pipeline(str(dummy_input), stages=["ingest", "audio_extract"])

        # 1. 成功することの検証
        assert result.success is True
        assert result.error_message == ""
        assert result.stages_completed == ["ingest", "audio_extract"]

        # 2. Popenが呼び出されたことの検証
        assert mock_popen.call_count >= 2

        # 3. 生成されたはずのダミーファイルの存在を確認
        job_id = result.job_id
        job_dir = work_dir / job_id
        
        normalized_path = job_dir / "dummy_short_normalized.mp4"
        assert normalized_path.exists()

        audio_path = job_dir / "dummy_short_normalized_audio.wav"
        assert audio_path.exists()
