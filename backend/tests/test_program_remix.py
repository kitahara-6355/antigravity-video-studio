"""仕上げ版の音だけを差し替える道具（backend/program_package/remix.py・2026-11-12）。

映像は写すだけ。番組 OP の曲の入れ替え・BGM（話している間は下げる）・音割れ止めを実測で確かめる。
"""
import re
import subprocess

import pytest

from backend.program_package import remix

SPEC = {"recording": "rec"}
TL = {"program": 4.0, "body": 6.0}


def _ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True, timeout=120)


@pytest.fixture
def episode(tmp_path):
    """12 秒の仕上げ版。頭 4 秒は前の曲（440Hz）、8 秒目までは無音、8 秒目から話し声の代わり（440Hz）。
    話し声は +6 dBFS まで出る（v62 の 7:34 の音割れの再現）。"""
    path = tmp_path / "ep.mp4"
    _ff("-f", "lavfi", "-i", "testsrc=size=320x180:rate=30", "-f", "lavfi",
        "-i", "aevalsrc='if(lt(t,4)+gte(t,8),2*sin(2*PI*440*t),0)':s=48000:c=stereo",
        "-t", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(path))
    return path


@pytest.fixture
def tone(tmp_path):
    def make(freq, name):
        p = tmp_path / name
        _ff("-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000", "-t", "5", "-c:a", "aac", str(p))
        return p
    return make


@pytest.fixture(autouse=True)
def fixed_timeline(monkeypatch):
    monkeypatch.setattr(remix, "timeline", lambda spec: TL)


def level(path, a, b, band=None):
    """a〜b 秒の音の大きさ（dBFS の RMS）。band を付けるとその周波数の辺りだけ。"""
    f = f"atrim={a}:{b}" + (f",bandpass=f={band}:w=60" if band else "") + ",astats=metadata=0"
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "info", "-i", str(path), "-af", f, "-f", "null", "-"],
                       capture_output=True, text=True, check=True)
    m = re.findall(r"RMS level dB: (-?[\d.]+|-inf)", r.stderr)[-1]
    return -200.0 if m == "-inf" else float(m)


def peak(path):
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "info", "-i", str(path), "-af", "astats=metadata=0", "-f", "null",
                        "-"], capture_output=True, text=True, check=True)
    return float(re.findall(r"Peak level dB: (-?[\d.]+)", r.stderr)[-1])


def test_the_limiter_alone_stops_the_clipping_and_copies_the_picture(tmp_path, episode):
    assert peak(episode) > 3.0
    dst = remix.remix(SPEC, episode, {"op_music": None, "bgm": None}, "v67", tmp_path / "out")
    assert peak(dst) <= -0.5
    v = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=codec_name,nb_frames",
                        "-of", "csv=p=0", str(dst)], capture_output=True, text=True, check=True).stdout
    src = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                          "stream=codec_name,nb_frames", "-of", "csv=p=0", str(episode)],
                         capture_output=True, text=True, check=True).stdout
    assert v == src
    assert abs(remix.duration(dst) - remix.duration(episode)) < 0.1


def test_the_op_music_is_replaced_only_in_the_program_opening(tmp_path, episode, tone):
    dst = remix.remix(SPEC, episode, {"op_music": {"path": str(tone(1000, "op.m4a")), "volume": 0.5}}, "v67",
                      tmp_path / "out")
    assert level(dst, 0.5, 3.0, band=440) < -50        # 前の曲は消えた
    assert level(dst, 0.5, 3.0, band=1000) > -40       # 新しい曲が入った（sine は -21 dBFS・音量 0.5）
    assert level(dst, 9.0, 11.0, band=440) > -15       # 本編の声はそのまま
    assert level(dst, 9.0, 11.0, band=1000) < level(episode, 9.0, 11.0, band=1000) + 2  # 曲は番組 OP の外に出ない


def test_bgm_sits_under_the_body_and_ducks_while_someone_speaks(tmp_path, episode, tone):
    audio = {"bgm": {"path": str(tone(1000, "bgm.m4a")), "volume_db": -12, "fade": 0.5, "ranges": [[0.5, 5.8]]}}
    dst = remix.remix(SPEC, episode, audio, "v67", tmp_path / "out")
    quiet = level(dst, 7.0, 7.8, band=1000)     # 本編 1.0〜1.8 秒・誰も話していない
    talk = level(dst, 9.5, 11.0, band=1000)     # 本編 3.5〜5.0 秒・話している
    assert -45 < quiet < -25   # sine -21 dBFS に -12 dB
    assert talk < quiet - 6
    assert level(dst, 0.5, 3.0, band=1000) < level(episode, 0.5, 3.0, band=1000) + 2  # 番組 OP には敷かない


def test_no_ducking_keeps_the_bgm_level(tmp_path, episode, tone):
    audio = {"bgm": {"path": str(tone(1000, "bgm.m4a")), "volume_db": -12, "fade": 0.5, "ranges": [[0.5, 5.8]],
                     "duck": False}}
    dst = remix.remix(SPEC, episode, audio, "v67", tmp_path / "out")
    assert abs(level(dst, 7.0, 7.8, band=1000) - level(dst, 9.5, 11.0, band=1000)) < 3


def test_a_provisional_song_marks_the_name_and_short_ranges_are_refused(tmp_path, episode, tone):
    assert remix.output_name(SPEC, {"bgm": {"provisional": True}}, "v67") == "rec_v67_仮曲入り.mp4"
    assert remix.output_name(SPEC, {"bgm": {}}, "v67") == "rec_v67.mp4"
    with pytest.raises(ValueError):
        remix.graph({"bgm": {"path": "x", "fade": 3, "ranges": [[0, 4]]}}, TL, 12.0)


def test_clips_and_review_copy(tmp_path, episode):
    dst = remix.remix(SPEC, episode, {}, "v67", tmp_path / "out")
    c = remix.clip(dst, 6.0, 3.0, "0s")
    assert abs(remix.duration(c) - 3.0) < 0.6
    rv = remix.review_copy(dst)
    assert rv.name == "rec_v67_確認用360p.mp4"
    assert abs(remix.duration(rv) - remix.duration(dst)) < 0.2


def test_a_short_song_is_looped_with_a_crossfade_not_a_hard_jump(tmp_path, episode):
    """3 秒の曲（終わりの 0.5 秒で消える）を 5.8 秒の区間に敷くと、継ぎ目で重ねてつなぐ。
    -stream_loop だと継ぎ目で急に頭へ戻る（消えた所がそのまま穴になる）。"""
    song = tmp_path / "short.m4a"
    _ff("-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000", "-t", "3", "-af", "afade=t=out:st=2.5:d=0.5",
        "-c:a", "aac", str(song))
    audio = {"bgm": {"path": str(song), "volume_db": -6, "fade": 0.5, "duck": False, "loop_crossfade": 1.0,
                     "ranges": [[0.0, 5.8]]}}
    _, g = remix.graph({**audio, "bgm": {**audio["bgm"], "_len": 3.0}}, TL, 12.0)
    assert "acrossfade" in g and "stream_loop" not in g
    dst = remix.remix(SPEC, episode, audio, "v67", tmp_path / "out")
    # 曲の終わり（2.5〜3 秒で消える）を重ねてつなぐので、継ぎ目（本編 2.0〜2.5 秒＝仕上げ版 8.0〜8.5）でも鳴っている
    assert level(dst, 8.0, 8.5, band=1000) > -40


def test_ed_music_sits_only_on_the_ending(tmp_path, episode, tone, monkeypatch):
    """ED（最後の 3 秒＝9〜12 秒）だけに曲を敷く。BGM の既定の範囲は ED の手前で終わる。"""
    tl = {**TL, "ed": 3.0}
    monkeypatch.setattr(remix, "timeline", lambda spec: tl)
    audio = {"ed_music": {"path": str(tone(1000, "ed.m4a")), "volume": 0.5, "fade_in": 0.3, "fade_out": 0.5}}
    dst = remix.remix(SPEC, episode, audio, "v67", tmp_path / "out")
    assert level(dst, 9.6, 11.0, band=1000) > -40      # ED に曲が入った
    assert level(dst, 6.0, 8.5, band=1000) < level(episode, 6.0, 8.5, band=1000) + 2  # 本編には出ない
    inputs, _ = remix.graph({"bgm": {"path": "b", "fade": 0.5}, "ed_music": {"path": "e"}}, tl, 12.0)
    assert inputs[inputs.index("b") - 2] == "3.000"     # BGM は本編 0〜3 秒（12 − 6 − 3）
    with pytest.raises(ValueError):
        remix.graph({"ed_music": {"path": "e"}}, TL, 12.0)
