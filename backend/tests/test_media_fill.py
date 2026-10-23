"""backend/media_fill.py — 収録の黒い縁を拡大で埋める（2本目の対談・2026-10-23 北原さん「拡大して」）。"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from backend import media_fill
from backend.media_fill import Box

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")


# --- 窓の切り出し ----------------------------------------------------------------


def test_a_wide_box_is_cut_at_the_sides_to_fill_16_9():
    # 美麗さんのワンショット（1140×570 が (24, 74)）
    assert media_fill.fill_window(Box(1140, 570, 24, 74), 1280, 720) == Box(1012, 570, 88, 74)


def test_a_tall_box_is_cut_at_top_and_bottom_to_fill_16_9():
    # 2人の場面（1080×720 が (100, 0)・左右に黒い帯）
    assert media_fill.fill_window(Box(1080, 720, 100, 0), 1280, 720) == Box(1080, 608, 100, 56)


def test_a_box_without_black_edges_is_left_as_it_is():
    assert media_fill.fill_window(Box(1280, 720, 0, 0), 1280, 720) is None
    assert media_fill.fill_window(Box(1276, 716, 2, 2), 1280, 720) is None


# --- 場面のまとめ方 ----------------------------------------------------------------


def _samples(*runs):
    out, t = [], 0.0
    for box, n in runs:
        for _ in range(n):
            out.append((t, box))
            t += 0.5
    return out


SOLO, PAIR, MID = Box(1140, 570, 24, 74), Box(1080, 720, 100, 0), Box(1156, 720, 24, 0)


def test_short_boxes_while_switching_scenes_go_into_the_scene_before():
    scenes = media_fill.scenes_from_samples(_samples((SOLO, 48), (MID, 2), (PAIR, 100)), 75.0, 1280, 720)
    assert [(s.start, s.box) for s in scenes] == [(0.0, SOLO), (25.0, PAIR)]
    assert scenes[0].end == 25.0 and scenes[-1].end == 75.0


def test_a_box_wobbling_by_a_few_pixels_is_the_same_scene():
    wobble = Box(1082, 718, 98, 2)
    scenes = media_fill.scenes_from_samples(_samples((PAIR, 10), (wobble, 10), (PAIR, 10)), 15.0, 1280, 720)
    assert len(scenes) == 1


def test_no_samples_is_an_error():
    with pytest.raises(media_fill.FillError):
        media_fill.scenes_from_samples([], 10.0, 1280, 720)


def test_metadata_print_is_read_as_time_and_box():
    text = ("frame:0    pts:0       pts_time:0\nlavfi.cropdetect.x1=24\nlavfi.cropdetect.w=1140\n"
            "lavfi.cropdetect.h=570\nlavfi.cropdetect.x=24\nlavfi.cropdetect.y=74\n"
            "frame:1    pts:1       pts_time:0.5\nlavfi.cropdetect.w=1080\nlavfi.cropdetect.h=720\n"
            "lavfi.cropdetect.x=100\nlavfi.cropdetect.y=0\n")
    assert media_fill.parse_metadata(text, offset=10) == [(10.0, SOLO), (10.5, PAIR)]


def test_the_graph_cuts_each_scene_and_leaves_full_frames_alone():
    plan = {"width": 1280, "height": 720, "scenes": [
        {"start": 0.0, "end": 24.0, "box": {}, "crop": {"w": 1012, "h": 570, "x": 88, "y": 74}},
        {"start": 24.0, "end": 30.0, "box": {}, "crop": None}]}
    graph = media_fill.filter_graph(plan)
    assert "trim=start=0.0:end=24.0" in graph and "crop=1012:570:88:74,scale=1280:720" in graph
    assert "[s1]trim=start=24.0,setpts=PTS-STARTPTS,setsar=1" in graph  # 最後の場面は終わりまで・拡大なし
    assert graph.endswith("concat=n=2:v=1:a=0[v]")


# --- 実際の素材で ----------------------------------------------------------------


def _boxed(path, seconds, pad):
    """真ん中に絵、周りが黒い素材（pad: 絵の大きさと位置）。"""
    w, h, x, y = pad
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=30:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
         "-vf", f"pad=320:180:{x}:{y}:black", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


@needs_ffmpeg
def test_black_edges_are_found_and_filled_and_the_sound_is_kept(tmp_path):
    a = _boxed(tmp_path / "a.mp4", 3, (240, 180, 40, 0))   # 左右に黒い帯
    b = _boxed(tmp_path / "b.mp4", 3, (320, 180, 0, 0))    # 縁なし
    joined = tmp_path / "joined.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(a), "-i", str(b),
                    "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(joined)], check=True)
    plan = media_fill.detect(joined)
    assert [s["crop"] is not None for s in plan["scenes"]] == [True, False]
    assert plan["scenes"][1]["start"] == pytest.approx(3.0, abs=0.05)

    out = tmp_path / "filled.mp4"
    media_fill.fill(joined, out, plan)
    after = media_fill.detect(out)
    assert all(s["crop"] is None for s in after["scenes"])  # もう黒い縁が無い
    assert after["duration"] == pytest.approx(plan["duration"], abs=0.1)
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                              "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.split()
    assert streams == ["video", "audio"]


@needs_ffmpeg
def test_a_job_with_raw_fill_joins_then_fills_and_keeps_the_scenes(tmp_path):
    from backend import edit_job, media_concat

    raw = tmp_path / "work" / "raw"
    raw.mkdir(parents=True)
    _boxed(raw / "a.mp4", 2, (240, 180, 40, 0))
    _boxed(raw / "b.mp4", 2, (240, 180, 40, 0))
    job = {"name": "fill_test", "material": "joined.mp4", "out": str(tmp_path / "out"),
           "raw": {"folder": None, "parts": ["a.mp4", "b.mp4"], "fill": True},
           "versions": [{"key": "zero"}]}
    runner = edit_job.Runner(job, work=tmp_path / "work", ledger=tmp_path / "l.jsonl",
                             budget=tmp_path / "b.json", runs_dir=tmp_path / "runs", tiers={})
    result = runner.step_join({"key": "join"})
    assert [s["crop"] is not None for s in result["fill"]] == [True]
    assert all(s["crop"] is None for s in media_fill.detect(runner.material)["scenes"])
    saved = media_concat.manifest_path(runner.material).read_text(encoding="utf-8")
    assert '"fill"' in saved
    assert not list((tmp_path / "work" / "material").glob("*.joined.*"))  # 埋める前の素材は残さない

    # 2回目はつないだ物（拡大済み）をそのまま使う
    again = runner.step_join({"key": "join"})
    assert again["size"] == result["size"] and again["fill"] == result["fill"]
