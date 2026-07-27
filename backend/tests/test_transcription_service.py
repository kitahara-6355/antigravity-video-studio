"""
test_transcription_service.py — TranscriptionService のユニットテスト

このテストは、音声文字起こしステージ (TranscriptionService) の仕様を検証します。
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from video_pipeline.transcription_service import TranscriptionService, TranscriptSegment, TranscriptResult


@pytest.mark.parametrize(
    "test_id, audio_exists, whisper_available, language, model_name, ffprobe_stdout, ffprobe_returncode, expected_success, expected_seg_len, expected_lang",
    [
        # 1. 正常系: Whisper利用可能 (ja)
        ("normal_whisper_ja", True, True, "ja", "base", "", 0, True, 2, "ja"),
        # 2. 正常系: Whisper利用可能 (en)
        ("normal_whisper_en", True, True, "en", "small", "", 0, True, 2, "en"),
        # 3. 正常系: Whisper未インストール (ja) -> フォールバック (音声長30s)
        ("normal_fallback_30s", True, False, "ja", "base", '{"format": {"duration": "30.0"}}', 0, True, 3, "ja"),
        # 4. 正常系: Whisper未インストール (en) -> フォールバック (音声長15.5s)
        ("normal_fallback_en_15s", True, False, "en", "base", '{"format": {"duration": "15.5"}}', 0, True, 2, "en"),
        # 5. 境界値: フォールバック (音声長0s)
        ("boundary_fallback_0s", True, False, "ja", "base", '{"format": {"duration": "0.0"}}', 0, True, 0, "ja"),
        # 6. 境界値: フォールバック (音声長0.5s)
        ("boundary_fallback_short", True, False, "ja", "base", '{"format": {"duration": "0.5"}}', 0, True, 1, "ja"),
        # 7. 境界値: 音声の長さがちょうど10.0秒
        ("boundary_fallback_exact_10s", True, False, "ja", "base", '{"format": {"duration": "10.0"}}', 0, True, 1, "ja"),
        # 8. 異常系: 音声ファイルが存在しない (不正な音声パス)
        ("error_file_not_found", False, False, "ja", "base", "", 0, False, 0, "ja"),
        # 9. 異常系: ffprobeがエラーを返す (音声長取得不可)
        ("error_ffprobe_failed", True, False, "ja", "base", "", 1, True, 0, "ja"),
    ]
)
def test_transcribe_parameterized(
    safe_popen_mock,
    test_id,
    audio_exists,
    whisper_available,
    language,
    model_name,
    ffprobe_stdout,
    ffprobe_returncode,
    expected_success,
    expected_seg_len,
    expected_lang
):
    """TranscriptionService.transcribe のパラメータ化テスト (9ケース)"""
    service = TranscriptionService(model_name=model_name, language=language)

    dummy_whisper_segs = [
        TranscriptSegment(start=0.0, end=2.0, text="こんにちは", confidence=0.9),
        TranscriptSegment(start=2.0, end=4.5, text="テストです", confidence=0.8)
    ]
    with patch("os.path.exists", return_value=audio_exists), \
         patch.object(service, "_is_stable_ts_available", return_value=False), \
         patch.object(service, "_is_whisper_available", return_value=whisper_available), \
         patch.object(service, "_transcribe_with_whisper", return_value=dummy_whisper_segs) as mock_transcribe_whisper:
        
        proc = safe_popen_mock(returncode=ffprobe_returncode, stdout_text=ffprobe_stdout)
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = (ffprobe_stdout, "")

        with patch("subprocess.Popen", return_value=proc) as mock_popen:
            result = service.transcribe("dummy_audio.wav")

            # 検証
            assert result.success == expected_success
            assert result.language == expected_lang

            if expected_success:
                assert len(result.segments) == expected_seg_len
                # タイムスタンプの連続性検証: 前のend <= 次のstart
                for i in range(len(result.segments) - 1):
                    assert result.segments[i].end <= result.segments[i+1].start

            # 呼び出し回数の確認
            if whisper_available and audio_exists:
                mock_transcribe_whisper.assert_called_once_with("dummy_audio.wav")
            else:
                mock_transcribe_whisper.assert_not_called()


def test_segments_timestamp_continuity(safe_popen_mock):
    """フォールバック生成時におけるセグメントタイムスタンプの連続性 (前のend <= 次のstart) の単独検証"""
    service = TranscriptionService(language="ja")
    with patch("os.path.exists", return_value=True), \
         patch.object(service, "_is_stable_ts_available", return_value=False), \
         patch.object(service, "_is_whisper_available", return_value=False):

        # 音声長 25.0 秒
        proc = safe_popen_mock(returncode=0)
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ('{"format": {"duration": "25.0"}}', "")
        with patch("subprocess.Popen", return_value=proc):
            result = service.transcribe("dummy.wav")
            assert result.success is True
            assert len(result.segments) == 3  # 0-10, 10-20, 20-25

            # タイムスタンプの連続性を検証
            for i in range(len(result.segments) - 1):
                assert result.segments[i].end <= result.segments[i+1].start
                # 今回のロジックでは前のendと次のstartが一致するはず
                assert result.segments[i].end == result.segments[i+1].start


def test_transcribe_stable_ts_priority():
    """stable-ts が利用可能な場合に最優先で使用され、refine も自動適用されることを検証"""
    service = TranscriptionService(model_name="base", language="ja", refine_enabled=True)
    dummy_segs = [TranscriptSegment(start=0.0, end=1.5, text="テスト", confidence=0.95)]
    refined_segs = [TranscriptSegment(start=0.1, end=1.4, text="テスト", confidence=0.95)]

    mock_wrapper = MagicMock()
    mock_wrapper.refine_timestamps.return_value = refined_segs

    with patch("os.path.exists", return_value=True), \
         patch.object(service, "_is_stable_ts_available", return_value=True), \
         patch.object(service, "_transcribe_with_stable_ts", return_value=dummy_segs) as mock_stable_ts, \
         patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper", return_value=mock_wrapper), \
         patch.object(service, "_is_whisper_available", return_value=True) as mock_whisper_avail:

        result = service.transcribe("dummy_audio.wav")

        assert result.success is True
        assert result.model_used == "stable-ts/base+refined"
        assert len(result.segments) == 1
        assert result.segments[0].start == 0.1
        assert result.segments[0].text == "テスト"
        mock_stable_ts.assert_called_once_with("dummy_audio.wav")
        mock_wrapper.refine_timestamps.assert_called_once_with("dummy_audio.wav", dummy_segs)
        mock_whisper_avail.assert_not_called()


def test_transcribe_refine_disabled():
    """refine_enabled=False 時は refine_timestamps が呼ばれず +refined も付与されないことを検証"""
    service = TranscriptionService(model_name="base", language="ja", refine_enabled=False)
    dummy_segs = [TranscriptSegment(start=0.0, end=1.5, text="テスト", confidence=0.95)]

    mock_wrapper = MagicMock()

    with patch("os.path.exists", return_value=True), \
         patch.object(service, "_is_stable_ts_available", return_value=True), \
         patch.object(service, "_transcribe_with_stable_ts", return_value=dummy_segs), \
         patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper", return_value=mock_wrapper):

        result = service.transcribe("dummy_audio.wav")

        assert result.success is True
        assert result.model_used == "stable-ts/base"
        assert len(result.segments) == 1
        assert result.segments[0].start == 0.0
        mock_wrapper.refine_timestamps.assert_not_called()


def test_transcribe_refine_failure_fallback():
    """refine_timestamps 実行時に例外が発生した場合は元の segments を保持しフォールバックすることを検証"""
    service = TranscriptionService(model_name="base", language="ja", refine_enabled=True)
    dummy_segs = [TranscriptSegment(start=0.0, end=1.5, text="テスト", confidence=0.95)]

    mock_wrapper = MagicMock()
    mock_wrapper.refine_timestamps.side_effect = RuntimeError("refine failed")

    with patch("os.path.exists", return_value=True), \
         patch.object(service, "_is_stable_ts_available", return_value=True), \
         patch.object(service, "_transcribe_with_stable_ts", return_value=dummy_segs), \
         patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper", return_value=mock_wrapper):

        result = service.transcribe("dummy_audio.wav")

        assert result.success is True
        assert result.model_used == "stable-ts/base"
        assert len(result.segments) == 1
        assert result.segments[0].start == 0.0
        mock_wrapper.refine_timestamps.assert_called_once_with("dummy_audio.wav", dummy_segs)


def test_transcribe_fallback_chain(safe_popen_mock):
    """stable-ts 不可 -> faster-whisper 不可 -> dummy フォールバックのチェーン検証"""
    service = TranscriptionService(model_name="small", language="ja")

    # safe_popen_mock で ffprobe の応答を設定 (10秒)
    proc = safe_popen_mock(returncode=0)
    proc.__enter__.return_value = proc
    proc.__exit__.return_value = False
    proc.communicate.return_value = ('{"format": {"duration": "10.0"}}', "")

    with patch("os.path.exists", return_value=True), \
         patch.object(service, "_is_stable_ts_available", return_value=False), \
         patch.object(service, "_is_whisper_available", return_value=False), \
         patch("subprocess.Popen", return_value=proc):

        result = service.transcribe("dummy_audio.wav")

        assert result.success is True
        assert result.model_used == "fallback/dummy"
        assert len(result.segments) == 1
        assert result.segments[0].text == "[文字起こし未実行]"


