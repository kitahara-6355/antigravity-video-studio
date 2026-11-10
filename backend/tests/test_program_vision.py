"""映像を見る目（backend/program_package/vision.py）: 顔と頭を測り、飾りの置き場を決める。

人物の写真はリポジトリに置かないので、顔の検出そのものは合成の絵（顔なし）と
測った数字（地図）で確かめる。実写での確かめは PR の本文と knowledge に残す。
"""
import json
import shutil
import subprocess
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from PIL import ImageFont

from backend.program_package import episode as ep
from backend.program_package import vision as v

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "backend" / "config" / "episode" / "20250922_久木田ヒロノブ.json"


@pytest.fixture
def fonts(monkeypatch):
    if not all((ep.th.FONT_DIR / f).exists() for f in ep.th.FONTS.values()):
        monkeypatch.setattr(ep.th, "font", lambda key, size: ImageFont.load_default(size))


def spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


def face(x0, y0, x1, y1, score=0.9, nose=None):
    cx = (x0 + x1) // 2 if nose is None else nose
    ey = y0 + (y1 - y0) // 3
    my = y0 + (y1 - y0) * 3 // 4
    w = x1 - x0
    return {"box": [x0, y0, x1, y1], "score": score,
            "marks": [x0 + w // 4, ey, x1 - w // 4, ey, cx, (ey + my) // 2, x0 + w // 3, my, x1 - w // 3, my]}


def make_map(rows, fps=2.0):
    return {"version": v.MAP_VERSION, "video": "test.mp4", "source_size": [640, 360], "size": [v.W, v.H],
            "fps": fps, "duration": len(rows) / fps,
            "frames": [{"t": i / fps, "faces": f, "motion": 0.01} for i, f in enumerate(rows)]}


# ---- 頭の矩形 ----

def test_head_box_covers_the_hair_above_and_beside_the_face():
    x0, y0, x1, y1 = v.head_box([500, 300, 600, 420])
    assert x0 < 500 and x1 > 600 and y0 <= 300 - 60 and y1 >= 420


def test_head_box_widens_toward_the_back_of_a_turned_head():
    # 鼻が右に寄っている＝右向き。後ろ頭（髪）は左に出るので、左を広く取る
    front = v.head_box([500, 300, 600, 420])
    turned = v.head_box([500, 300, 600, 420], face(500, 300, 600, 420, nose=585)["marks"])
    assert turned[0] < front[0] and turned[2] == front[2]
    other = v.head_box([500, 300, 600, 420], face(500, 300, 600, 420, nose=515)["marks"])
    assert other[2] > front[2] and other[0] == front[0]


# ---- 頭の来る所 ----

def test_head_zones_merge_small_moves_and_keep_a_far_lean_separate():
    rows = [[face(280, 200, 350, 300), face(930, 170, 1030, 310)] for _ in range(8)]
    rows += [[face(290, 205, 360, 305), face(760, 250, 860, 390)] for _ in range(8)]  # 右の人が身を乗り出す
    zones = v.head_zones(make_map(rows), 0, 8)
    assert len(zones) == 3
    assert all(z[3] >= v.FLOOR for z in zones)  # 頭の下（体）まで含める
    lefts = sorted(z[0] for z in zones)
    assert lefts[0] < 280 and 700 < lefts[1] < 760 and lefts[2] > 860


def test_a_single_frame_false_face_is_ignored():
    rows = [[face(280, 200, 350, 300)] for _ in range(10)]
    rows[4] = rows[4] + [face(600, 400, 650, 470, score=0.7)]  # 花などの誤検出が1コマだけ
    zones = v.head_zones(make_map(rows), 0, 5)
    assert len(zones) == 1 and zones[0][2] < 500


def test_zones_only_use_the_asked_time_window():
    rows = [[face(280, 200, 350, 300)] for _ in range(10)] + [[face(900, 200, 1000, 300)] for _ in range(10)]
    assert all(z[2] < 600 for z in v.head_zones(make_map(rows), 0, 3))
    assert all(z[0] > 600 for z in v.head_zones(make_map(rows), 7, 3))


def test_people_are_named_by_the_side_of_the_picture():
    rows = [[face(280, 200, 350, 300), face(930, 170, 1030, 310)] for _ in range(6)]
    who = v.people(make_map(rows), 0, 3)
    assert set(who) == {"left", "right"} and who["left"][2] < v.W / 2 < who["right"][0]


# ---- 名前のポップ ----

def test_guest_pop_is_placed_off_the_hand_measured_heads(fonts):
    # 正解は 2026-10-23 に人が測った avoid（3つ）。置き場を消してから機械に置かせる
    guest = next(p for p in spec()["name_pops"] if p["name"] == "久木田ヒロノブ")
    blank = {k: x for k, x in guest.items() if k not in ("y", "right", "pitch", "size")} | {"y": 300}
    placed = v.place_pop(blank, guest["avoid"], target=[880, 125, 1030, 300])
    assert placed is not None
    assert not ep.pop_hits(placed)
    x0, y0, x1, y1 = ep.pop_card(placed).getbbox()
    fx0, fy0, fx1, _ = ep.th.FRAME
    assert fx0 <= x0 and x1 <= fx1 and fy0 <= y0 and y1 <= v.FLOOR


def test_pop_keeps_clear_of_other_overlays(fonts):
    pop = {"at": 0, "lines": ["書家"], "name": "北原美麗", "y": 42}
    busy = [[600, 37, 1163, 140]]  # 右上に章の見出しがある
    placed = v.place_pop(pop, [[240, 150, 420, 560]], target=[260, 160, 400, 330], busy=busy)
    assert placed is not None
    a = np.asarray(ep.pop_card(placed))[..., 3]
    assert not a[37:140, 600:1163].any() and not a[150:560, 240:420].any()


def test_pop_with_no_room_is_reported_not_forced(fonts):
    pop = {"at": 0, "lines": ["書家"], "name": "北原美麗", "y": 42}
    assert v.place_pop(pop, [[0, 0, v.W, v.H]]) is None


def test_place_rewrites_avoid_from_the_map_and_moves_a_pop_that_hits(fonts):
    s = {"name_pops": [{"at": 0.0, "seconds": 4.0, "y": 150, "right": 1100, "lines": ["書家"], "name": "北原美麗"}]}
    rows = [[face(930, 170, 1030, 310)] for _ in range(12)]  # ポップの真下に頭がある
    r = v.place(s, make_map(rows), [])
    new = r["spec"]["name_pops"][0]
    assert r["changes"] and not r["unplaced"]
    assert new["avoid"] and "自動" in new["avoid_note"]
    assert not ep.pop_hits(new)
    assert s["name_pops"][0].get("avoid") is None  # 元の指定は書き換えない


def test_place_leaves_a_pop_alone_when_no_face_is_seen(fonts):
    s = {"name_pops": [{"at": 0.0, "seconds": 4.0, "y": 150, "lines": ["書家"], "name": "北原美麗"}]}
    r = v.place(s, make_map([[] for _ in range(12)]), [])
    assert r["spec"]["name_pops"][0] == s["name_pops"][0]
    assert r["unplaced"]


# ---- 章の見出し・テロップ ----

def test_chapter_heading_moves_to_the_right_when_a_head_is_at_the_top_left(fonts):
    body = [(0.0, "オープニング"), (10.0, "二人の話")]
    rows = [[face(150, 60, 260, 200)] for _ in range(20)]       # 一人の場面。頭が左上
    rows += [[face(300, 220, 370, 320), face(930, 220, 1030, 340)] for _ in range(20)]
    s = {"chapter_seconds": 4.0}
    r = v.place(s, make_map(rows), body)
    assert r["spec"]["chapters_right"] == [1]
    assert any("右上" in c for c in r["changes"])
    assert not v.check(r["spec"], make_map(rows), body)


def test_check_lists_an_overlay_that_covers_a_head(fonts):
    s = {"telops": [{"at": 1.0, "head": "文房四宝", "body": "筆・墨・硯・紙の4つの道具"}]}
    rows = [[face(560, 70, 680, 210)] for _ in range(20)]  # 上の真ん中に頭
    bad = v.check(s, make_map(rows), [])
    assert [b["kind"] for b in bad] == ["telop"]
    assert not v.check(s, make_map([[face(300, 300, 370, 400)] for _ in range(20)]), [])


# ---- 地図 ----

def test_spans_join_nearby_times_and_drop_blips():
    assert v.spans([1.0, 1.5, 2.0, 10.0, 30.0, 30.5, 31.0], 0.5) == [[1.0, 2.5], [30.0, 31.5]]


def test_thumbnail_candidates_are_spread_in_time_and_per_side():
    rows = [[face(300, 200, 400, 340), face(900, 200, 1000, 340, score=0.95)] for _ in range(200)]
    m = make_map(rows)
    left = v.thumb_candidates(m, "left", n=4, apart=20)
    assert len(left) == 4 and all(c["box"][0] < v.W / 2 for c in left)
    ts = sorted(c["t"] for c in left)
    assert all(b - a >= 20 for a, b in pairwise(ts))


def test_a_bigger_front_facing_smile_scores_higher():
    small_side = face(300, 200, 360, 280, nose=352)
    big_front = face(300, 200, 420, 360)
    assert v.face_quality(big_front) > v.face_quality(small_side)


def test_old_map_version_is_refused(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"version": 0, "frames": []}))
    with pytest.raises(v.VisionError):
        v.load(p)


# ---- 検出器（OpenCV が要る） ----

def test_model_file_is_in_the_repository():
    assert v.MODEL.exists() and 200_000 < v.MODEL.stat().st_size < 400_000


def test_eye_finds_no_face_in_a_plain_wall():
    pytest.importorskip("cv2")
    wall = np.full((360, 640, 3), (150, 130, 176), np.uint8)
    assert v.Eye().faces(wall) == []


def test_board_is_found_only_when_white_square_with_ink():
    cv2 = pytest.importorskip("cv2")
    im = np.full((360, 640, 3), (150, 130, 176), np.uint8)
    assert v.board_box(im) is None
    cv2.rectangle(im, (200, 60), (420, 300), (245, 245, 245), -1)
    assert v.board_box(im) is None                     # 白いだけ（墨が無い）
    cv2.line(im, (250, 100), (370, 260), (20, 20, 20), 14)
    box = v.board_box(im)
    assert box and abs(box[0] - 400) < 12 and abs(box[2] - 840) < 12
    blob = np.full((360, 640, 3), (150, 130, 176), np.uint8)
    cv2.circle(blob, (320, 180), 110, (245, 245, 245), -1)  # 白い上着のような丸い面
    cv2.line(blob, (300, 150), (340, 210), (20, 20, 20), 10)
    assert v.board_box(blob) is None


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg が要る")
def test_scan_writes_one_row_per_sample_with_cuts(tmp_path):
    pytest.importorskip("cv2")
    clip = tmp_path / "t.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x9682b0:s=320x180:d=2:r=10",
                    "-f", "lavfi", "-i", "color=c=white:s=320x180:d=2:r=10", "-filter_complex", "[0][1]concat=n=2",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    m = v.scan(clip, fps=2.0)
    assert len(m["frames"]) == 8 and m["size"] == [1280, 720] and m["source_size"] == [320, 180]
    assert all(r["faces"] == [] for r in m["frames"])
    assert v.cuts(m) == [2.0]  # 壁の色 → 白 の切れ目
