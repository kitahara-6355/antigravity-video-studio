"""素材の音を映像と同じ時間軸で読む（media_timeline）。"""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import media_timeline  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg が無い")


def _beeps_with_a_gap(path):
    """毎秒ちょうどに 50ms 鳴る音。1.5〜1.6 秒の音を時刻ごと抜く（時刻は詰めない）。

    結合した素材のつなぎ目と同じ形（素材の 29分58秒は音が 65ms 欠けて、時刻はその分飛んでいた）。
    """
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc=exprs='if(lt(mod(t,1),0.05),0.8*sin(2*PI*1000*t),0)':s=48000:d=4",
                    "-af", "aselect='not(between(t,1.5,1.6))'", "-c:a", "aac", str(path)], check=True)


def _onsets(pcm: bytes, rate: int) -> list[float]:
    loud = np.flatnonzero(np.abs(np.frombuffer(pcm, dtype=np.int16).astype(float)) > 8000)
    starts = [loud[0]] + [b for a, b in zip(loud, loud[1:]) if b - a > rate // 4]
    return [round(s / rate, 2) for s in starts]


@needs_ffmpeg
def test_the_sound_is_read_on_the_timeline_of_the_picture(tmp_path):
    """詰めて読むと、欠けの後ろの音が欠けの分だけ早く読める（43分の素材で最大 0.165 秒・2026-10-18）。"""
    src = tmp_path / "beeps.m4a"
    _beeps_with_a_gap(src)
    plain = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-ac", "1", "-ar", "16000",
                            "-f", "s16le", "-"], capture_output=True, check=True).stdout
    assert _onsets(plain, 16000)[2:] != [2.0, 3.0]  # 詰めて読むと、2秒・3秒の音が早い

    assert _onsets(media_timeline.read_pcm(src, 16000), 16000) == [0.0, 1.0, 2.0, 3.0]


@needs_ffmpeg
def test_the_gaps_are_measured_and_put_back_into_the_times(tmp_path):
    src = tmp_path / "beeps.m4a"
    _beeps_with_a_gap(src)
    gaps = media_timeline.audio_gaps(src)
    assert len(gaps) == 1 and gaps[0][0] == pytest.approx(1.5, abs=0.03)
    assert gaps[0][1] == pytest.approx(0.1, abs=0.03)

    plain = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-ac", "1", "-ar", "16000",
                            "-f", "s16le", "-"], capture_output=True, check=True).stdout
    assert media_timeline.to_source_times(_onsets(plain, 16000), gaps) == pytest.approx(
        [0.0, 1.0, 2.0, 3.0], abs=0.01)


@needs_ffmpeg
def test_a_file_without_gaps_has_none(tmp_path):
    src = tmp_path / "beeps.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=1000:d=2:sample_rate=48000",
                    "-c:a", "aac", str(src)], check=True)
    assert media_timeline.audio_gaps(src) == []


def test_each_time_gets_the_gaps_before_it():
    gaps = [(10.0, 0.065), (20.0, -0.02)]
    assert media_timeline.to_source_times([5.0, 10.0, 15.0, 20.0, 25.0], gaps) == [
        5.0, 10.065, 15.065, 20.045, 25.045]
    assert media_timeline.to_source_times([1.0, 2.0], []) == [1.0, 2.0]


@needs_ffmpeg
def test_a_file_that_cannot_be_read_is_an_error(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"x")
    with pytest.raises((OSError, ValueError, subprocess.SubprocessError)):
        media_timeline.audio_gaps(bad)
    with pytest.raises(RuntimeError):
        media_timeline.read_pcm(bad)
