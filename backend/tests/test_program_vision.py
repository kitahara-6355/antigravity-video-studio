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
from PIL import Image, ImageFont

from backend.program_package import episode as ep
from backend.program_package import vision as v

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "backend" / "config" / "episode" / "20250922_久木田ヒロノブ.json"


def real_fonts() -> bool:
    return all((ep.th.FONT_DIR / f).exists() for f in ep.th.FONTS.values())


@pytest.fixture
def fonts(monkeypatch):
    if not real_fonts():
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
    assert x0 < 500 and x1 > 600 and y0 <= 300 - 40 and y1 >= 420


def test_head_box_widens_toward_the_back_of_a_turned_head():
    # 鼻が右に寄っている＝右向き。後ろ頭（髪）は左に出るので、左を広く取る
    front = v.head_box([500, 300, 600, 420])
    turned = v.head_box([500, 300, 600, 420], face(500, 300, 600, 420, nose=585)["marks"])
    assert turned[0] < front[0] and turned[2] < front[2]  # 顔の向いている側は狭める
    other = v.head_box([500, 300, 600, 420], face(500, 300, 600, 420, nose=515)["marks"])
    assert other[2] > front[2] and other[0] > front[0]


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


# ---- 実測（久木田回 v62 の地図の抜粋）----

REAL = ROOT / "backend" / "tests" / "fixtures" / "vision" / "20250922_久木田ヒロノブ_v62_抜粋.json"


def test_measured_heads_overlap_the_hand_measured_ones():
    # 人が測った avoid（久木田さん・身を乗り出した久木田さん・美麗さん）のどれにも、機械の測った所が重なる
    guest = next(p for p in spec()["name_pops"] if p["name"] == "久木田ヒロノブ")
    zones = v.head_zones(v.load(REAL), guest["at"], guest["seconds"])
    assert len(zones) == 2  # 左の人と右の人
    for hand in guest["avoid"]:
        assert any(v._iou(hand, z) > 0.2 for z in zones), hand


def test_the_approved_pops_do_not_cover_the_measured_heads(fonts):
    """承認済みの札の形は本番の書体で決まる。書体の無い所でも確かめられるよう、本番の書体で描いた形を控えてある。"""
    pytest.importorskip("cv2")
    m = v.load(REAL)
    for i, pop in enumerate(spec()["name_pops"]):
        kept = np.asarray(Image.open(REAL.parent / f"pop_{i}.png").convert("L"))
        assert v.covered(kept, v.head_mask(m, pop["at"], pop.get("seconds", 7.0))) is None, pop["name"]
        if real_fonts():  # 控えが今の描き方とずれていないか
            live = np.asarray(ep.pop_card(pop))[..., 3] > 0
            assert (live != (kept > 0)).mean() < 0.001, pop["name"]


def test_pops_placed_from_scratch_on_the_real_map_stay_off_the_heads(fonts):
    pytest.importorskip("cv2")
    m = v.load(REAL)
    s = {"name_pops": [{k: x for k, x in p.items() if k not in ("avoid", "avoid_note", "right", "pitch", "size")} | {"y": 300}
                       for p in spec()["name_pops"]]}
    r = v.place(s, m, [])
    assert not r["unplaced"]
    for pop in r["spec"]["name_pops"]:
        assert pop["avoid"] and not ep.pop_hits(pop), pop["name"]
        alpha = np.asarray(ep.pop_card(pop))[..., 3]
        assert v.covered(alpha, v.head_mask(m, pop["at"], pop.get("seconds", 7.0), v.NEAR_MARGIN)) is None


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
    assert [(b["kind"], b["level"]) for b in bad] == [("telop", "掛かる")]
    assert not v.check(s, make_map([[face(300, 300, 370, 400)] for _ in range(20)]), [])


def test_check_tells_a_near_miss_from_a_real_overlap(fonts):
    s = {"telops": [{"at": 1.0, "head": "文房四宝", "body": "筆・墨・硯・紙の4つの道具"}]}
    bottom = ep.telop_card("文房四宝", "筆・墨・硯・紙の4つの道具").getbbox()[3]
    top = bottom + 6  # 頭のてっぺんがテロップのすぐ下
    rows = [[face(590, top + 42, 690, top + 142)] for _ in range(20)]
    assert v.head_box([590, top + 42, 690, top + 142])[1] == top
    found = v.check(s, make_map(rows), [])
    assert [b["level"] for b in found] == ["近い"]


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


def smiling(f, smile=0.0, sharp=100.0, eyes=(20.0, 20.0), low=100):
    """表情を測った顔（smile は happy とほかの最大の差）。"""
    logit = [0.0] * 7
    logit[v.HAPPY] = smile
    return {**f, "expr": {"logit": logit, "sharp": sharp, "eyes": list(eyes), "low": bytes([low] * 168).hex()}}


def look(sharp_and_open, i):
    """(くっきり, 目)。笑顔のコマははっきり写り目も開いている。ほかはばらつかせる。"""
    return (300.0, (60.0, 60.0)) if sharp_and_open else (100.0 + i % 13, (20.0 + i % 11, 20.0))


def smile_map(left_smiles, right_smiles=None, seconds=600, fps=2.0):
    """left_smiles/right_smiles は {時刻: 笑顔の差}。それ以外のコマは笑っていない。"""
    right_smiles = right_smiles or {}
    rows = []
    for i in range(int(seconds * fps)):
        t = i / fps
        ls = left_smiles.get(t, (i % 7) * 0.1)
        rs = right_smiles.get(t, (i % 5) * 0.1)
        rows.append([smiling(face(300, 200, 400, 340), ls, *look(t in left_smiles, i)),
                     smiling(face(900, 200, 1000, 340), rs, *look(t in right_smiles, i))])
    return make_map(rows, fps)


def test_with_expressions_candidates_come_from_the_smiles():
    m = smile_map({100.0: 9.0, 250.0: 8.0, 400.0: 10.0})
    got = v.thumb_candidates(m, "left", n=12)
    assert sorted(c["t"] for c in got) == [100.0, 250.0, 400.0]
    assert got[0]["t"] == 400.0 and all(c["box"][0] < v.W / 2 for c in got)


def test_a_weak_smile_under_the_floor_is_not_a_candidate():
    m = smile_map({100.0: 4.0, 200.0: 4.5})
    assert v.thumb_candidates(m, "left") == []


def test_one_hill_gives_at_most_two_frames_three_seconds_apart():
    hill = {100.0 + k * 0.5: 9.0 for k in range(13)}   # 100〜106秒 ずっと笑っている
    got = v.thumb_candidates(smile_map(hill), "left", n=12)
    assert len(got) == 2 and len({c["hill"] for c in got}) == 1
    assert abs(got[0]["t"] - got[1]["t"]) >= 3


def test_at_most_three_frames_come_from_one_minute():
    smiles = {120.0 + k * 10: 9.0 for k in range(5)}   # 2分台に離れた笑顔が5つ
    got = v.thumb_candidates(smile_map(smiles), "left", n=12)
    assert len(got) == 3 and all(120 <= c["t"] < 180 for c in got)


def test_scene_cut_and_board_frames_are_dropped():
    m = smile_map({100.0: 9.0, 200.0: 9.0, 300.0: 9.0})
    for r in m["frames"]:
        if r["t"] == 100.0:
            r["motion"] = v.CUT_MOTION + 0.1
        if r["t"] == 200.0:
            r["board"] = [500, 100, 800, 500]
    assert [c["t"] for c in v.thumb_candidates(m, "left")] == [300.0]


def test_a_covered_lower_face_is_dropped():
    m = smile_map({100.0: 9.0, 200.0: 9.5})
    for r in m["frames"]:
        if r["t"] == 200.0:
            r["faces"][0]["expr"]["low"] = bytes([250] * 168).hex()   # 顔の下が手で白く隠れた
    assert [c["t"] for c in v.thumb_candidates(m, "left")] == [100.0]


def test_both_smiling_ranks_higher_and_makes_a_pair():
    m = smile_map({100.0: 9.0, 300.0: 9.0}, {300.5: 9.0})
    left = v.thumb_candidates(m, "left")
    assert left[0]["t"] == 300.0 and left[0]["both"] and not left[1]["both"]
    right = v.thumb_candidates(m, "right")
    assert [(a["t"], b["t"]) for a, b in v.pairs(left, right)] == [(300.0, 300.5)]


def test_thumb_spec_is_what_thumbnail_options_reads():
    left = [{"t": 10.0}, {"t": 20.0}]
    right = [{"t": 30.0}]
    assert v.thumb_spec(left, right) == {"left": {"L1": 10.0, "L2": 20.0}, "right": {"R1": 30.0}}


def test_board_candidates_pick_one_steady_frame_per_board_span():
    rows = [[] for _ in range(100)]
    m = make_map(rows)
    for r in m["frames"]:
        if 10 <= r["t"] < 14:
            r["board"] = [400, 100, 700, 500] if r["t"] != 12.0 else [380, 80, 720, 520]
        if 30 <= r["t"] < 31.5:
            r["board"] = [400, 100, 700, 500]
    got = v.board_candidates(m)
    assert [c["t"] for c in got] == [12.0, 30.0]


def test_thumbs_command_writes_the_options_spec(tmp_path, capsys):
    mp = tmp_path / "map.json"
    mp.write_text(json.dumps(smile_map({100.0: 9.0}, {100.5: 9.0})))
    out = tmp_path / "opts.json"
    assert v.main(["thumbs", "--map", str(mp), "--spec", str(out)]) == 0
    assert json.loads(out.read_text()) == {"left": {"L1": 100.0}, "right": {"R1": 100.5}}
    assert "二人とも: 100.0+100.5" in capsys.readouterr().out


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


def test_expression_model_is_in_the_repository():
    assert v.EXPR_MODEL.exists() and 4_000_000 < v.EXPR_MODEL.stat().st_size < 6_000_000


def test_expr_measures_seven_expressions_for_a_face():
    pytest.importorskip("cv2")
    im = np.full((540, 960, 3), (150, 130, 176), np.uint8)
    e = v.Expr().measure(im, face(500, 200, 640, 380))
    assert len(e["logit"]) == 7 and len(bytes.fromhex(e["low"])) == 168 and len(e["eyes"]) == 2


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


def test_trim_keeps_only_the_body():
    from backend.program_package import vision as v
    m = {"fps": 2.0, "frames": [{"t": x / 2, "faces": [], "motion": 0.0} for x in range(20)]}
    got = v.trim(m, 2.0, 8.0)
    assert [r["t"] for r in got["frames"]][0] == 2.0 and got["frames"][-1]["t"] == 7.5
    assert len(m["frames"]) == 20 and v.trim(m)["frames"] == m["frames"]
