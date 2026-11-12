"""スマホで見る朱入れ画面の小分け動画と控え（review_pack）。"""
import json

import pytest

from subtitle_engine import review_pack as rp

SHEET = {"version": 1, "run": "v62fix", "label": "v62の手直し", "video": "v62_360p.mp4", "duration": 100.0,
         "captions": [{"i": 0, "s": 0.5, "e": 2.0, "src": 3.0, "t": "こんにちは"},
                      {"i": 1, "s": 2.5, "e": 4.0, "src": 5.0, "t": "嘘　23回"}],
         "flags": [{"i": 1, "why": "x"}]}


def test_shift_moves_times_and_applies_fixes():
    out = rp.shift_sheet(SHEET, offset=33.5, fixes=[{"cap": 1, "from": "嘘　23回", "to": "23回"}],
                         run="v67", label="v67", video="v67_360p", duration=140.0)
    assert [c["s"] for c in out["captions"]] == [34.0, 36.0]
    assert out["captions"][1]["t"] == "23回" and out["captions"][0]["t"] == "こんにちは"
    assert out["captions"][0]["src"] == 3.0  # 素材の秒は変えない
    assert out["run"] == "v67" and out["duration"] == 140.0
    assert out["flags"] == []  # 前の版の要確認は持ち越さない
    assert SHEET["captions"][1]["t"] == "嘘　23回"  # 元は変えない


def test_shift_refuses_fix_that_does_not_match():
    with pytest.raises(ValueError):
        rp.shift_sheet(SHEET, offset=0, fixes=[{"cap": 1, "from": "違う字", "to": "x"}],
                       run="r", label="l", video="v", duration=1)


def test_parse_m3u8():
    text = "#EXTM3U\n#EXT-X-TARGETDURATION:7\n#EXTINF:6.006,\nseg_0000.ts\n#EXTINF:4.5,\nseg_0001.ts\n#EXT-X-ENDLIST\n"
    assert rp.parse_m3u8(text) == [{"name": "seg_0000.ts", "dur": 6.006}, {"name": "seg_0001.ts", "dur": 4.5}]


def test_pack_has_what_the_page_reads():
    p = rp.pack(SHEET, [{"name": "seg_0000.ts", "dur": 6.0}])
    assert p["kind"] == rp.KIND and p["run"] == "v62fix" and len(p["captions"]) == 2
    assert p["segments"][0]["name"] == "seg_0000.ts"
    json.dumps(p, ensure_ascii=False)


def test_segment_command_copies_without_reencode(tmp_path):
    cmd = rp.segment_cmd("ffmpeg", "in.mp4", tmp_path, 6)
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[-1].endswith("index.m3u8") and "-hls_time" in cmd
