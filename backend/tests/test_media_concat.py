"""backend/media_concat.py — 取り込んだ素材を順につないで1本にする（フェーズ1・2026-10-18）。

守りたい性質:

1. 形のそろった 1080p までの素材は、つなぐだけ（再エンコードしない）
2. 4K・形がそろわない・コマの間隔が一定でない素材は、1080p・一定のコマに直してつなぐ
3. 各素材が、つないだ1本のどこから始まるかを控えに残す（時間の対応づけと出どころ）
4. 空きが足りなければ、何も書かずに止まる

ffmpeg で小さな試しの動画を作って確かめる（ローカル・無料）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading

import pytest

from backend import media_concat

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")


def _clip(path, seconds, size="320x240", rate=25, tone=440):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(path)],
        check=True)
    return path


def _info(**over):
    base = {"duration": 10.0, "video_duration": 10.0, "codec": "h264", "width": 1920, "height": 1080,
            "fps": "30000/1001", "avg_fps": "30000/1001", "pix_fmt": "yuv420p",
            "audio_codec": "aac", "sample_rate": 48000, "channels": 2}
    base.update(over)
    return base


# --- 1・2. つなぎ方の決め方 ------------------------------------------------------


def test_matching_clips_up_to_1080p_are_joined_as_they_are():
    assert media_concat.plan([_info(), _info()]).mode == "copy"


@pytest.mark.parametrize("other, why", [
    (_info(width=3840, height=2160), "1080"),
    (_info(codec="hevc"), "形"),
    (_info(fps="25/1", avg_fps="25/1"), "形"),
    (_info(avg_fps="2850/100"), "コマ"),  # 平均が 28.5 コマ（スマホの可変コマ）
    (_info(sample_rate=44100), "形"),
])
def test_clips_that_are_large_or_do_not_match_are_made_into_1080p(other, why):
    plan = media_concat.plan([_info(), other])

    assert plan.mode == "transcode"
    assert why in plan.reason
    assert plan.height <= 1080


def test_a_4k_clip_is_fitted_into_1080p_keeping_its_shape():
    plan = media_concat.plan([_info(width=3840, height=2160), _info(width=3840, height=2160)])

    assert (plan.width, plan.height) == (1920, 1080)


def test_a_vertical_clip_among_landscape_clips_is_fitted_into_the_landscape_frame():
    # 大きさの最大を縦と横で別の素材から取ると、1920x1920 を縮めた正方形（1080x1080）になっていた
    plan = media_concat.plan([_info(), _info(width=1080, height=1920)])

    assert plan.mode == "transcode"
    assert (plan.width, plan.height) == (1920, 1080)


def test_clips_already_smaller_than_1080p_are_not_enlarged():
    plan = media_concat.plan([_info(width=1280, height=720, codec="hevc"), _info(width=1280, height=720)])

    assert plan.mode == "transcode"
    assert (plan.width, plan.height) == (1280, 720)


# --- 3. つないだ1本と控え ----------------------------------------------------------


def test_join_copies_matching_clips_and_records_where_each_starts(tmp_path):
    a = _clip(tmp_path / "a.mp4", 2)
    b = _clip(tmp_path / "b.mp4", 3, tone=660)
    out = tmp_path / "joined.mp4"

    manifest = media_concat.join([a, b], out)

    assert manifest["mode"] == "copy"
    assert [p["name"] for p in manifest["parts"]] == ["a.mp4", "b.mp4"]
    assert manifest["parts"][0]["start"] == 0
    assert manifest["parts"][1]["start"] == pytest.approx(2.0, abs=0.1)
    assert media_concat.probe(out)["duration"] == pytest.approx(5.0, abs=0.15)
    saved = json.loads(media_concat.manifest_path(out).read_text(encoding="utf-8"))
    assert saved["parts"] == manifest["parts"]


def test_join_makes_large_clips_into_1080p_with_sound_as_long_as_the_picture(tmp_path):
    a = _clip(tmp_path / "a.mp4", 1, size="1920x1440", rate=30)
    b = _clip(tmp_path / "b.mp4", 1, size="1920x1440", rate=30, tone=660)
    out = tmp_path / "joined.mp4"

    manifest = media_concat.join([a, b], out)

    info = media_concat.probe(out)
    assert manifest["mode"] == "transcode"
    assert info["height"] == 1080 and info["width"] % 2 == 0
    assert info["video_duration"] == pytest.approx(2.0, abs=0.05)
    assert info["duration"] == pytest.approx(2.0, abs=0.06)  # 音が映像より長くも短くもならない
    assert manifest["parts"][1]["start"] == pytest.approx(1.0, abs=0.04)


def test_join_keeps_the_order_it_was_given(tmp_path):
    a = _clip(tmp_path / "a.mp4", 1)
    b = _clip(tmp_path / "b.mp4", 2)

    manifest = media_concat.join([b, a], tmp_path / "joined.mp4")

    assert [p["name"] for p in manifest["parts"]] == ["b.mp4", "a.mp4"]
    assert manifest["parts"][1]["start"] == pytest.approx(2.0, abs=0.1)


def test_a_long_error_output_does_not_stop_the_join_halfway(tmp_path):
    # ffmpeg のエラーの出力（壊れたコマが続くと長くなる）を、進み具合を読み終わるまで溜めていると、
    # 溜め場（64KB）が埋まった所で ffmpeg も待ちに入り、どちらも進まなくなる
    script = ("import sys\n"
              "sys.stderr.write('[h264] error while decoding\\n' * 20000)\n"
              "print('out_time_us=1500000', flush=True)\n")
    seen = []
    worker = threading.Thread(
        target=media_concat._run, args=([sys.executable, "-c", script, str(tmp_path / "out.mp4")], 3.0,
                                        lambda done, total: seen.append((done, total))),
        daemon=True)

    worker.start()
    worker.join(timeout=20)

    assert not worker.is_alive()
    assert seen == [(1.5, 3.0)]


def test_a_failing_join_says_what_ffmpeg_said_last(tmp_path):
    script = ("import sys\n"
              "sys.stderr.write('[h264] error while decoding\\n' * 20000)\n"
              "sys.stderr.write('Conversion failed!\\n')\n"
              "sys.exit(1)\n")

    with pytest.raises(media_concat.JoinError) as exc:
        media_concat._run([sys.executable, "-c", script, str(tmp_path / "out.mp4")], 1.0, None)

    assert "Conversion failed!" in str(exc.value)


# --- 4. 空き -------------------------------------------------------------------------


def test_join_stops_before_writing_when_the_disk_is_too_small(tmp_path):
    a = _clip(tmp_path / "a.mp4", 1)
    out = tmp_path / "joined.mp4"

    with pytest.raises(media_concat.JoinError) as exc:
        media_concat.join([a], out, free_bytes=lambda _: 10)

    assert "空き" in str(exc.value)
    assert not out.exists()


def test_join_refuses_an_empty_list(tmp_path):
    with pytest.raises(media_concat.JoinError):
        media_concat.join([], tmp_path / "joined.mp4")
