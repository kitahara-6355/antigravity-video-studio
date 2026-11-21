"""二択の答えから好みを学ぶ（backend/program_package/taste.py）。

曲はリポジトリに置かないので、作った音と作った絵で確かめる。
"""
import json
import shutil
import subprocess
import wave

import numpy as np
import pytest

from backend.program_package import taste

SR = 22050
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg が無い")


def song(path, seconds=40, bpm=120, freq=440, loud=((20.0, 35.0, 0.6),), base=0.08):
    t = np.arange(int(seconds * SR)) / SR
    beat = 60 / bpm
    tone = np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * freq * 1.5 * t)
    env = np.exp(-((t % beat) / 0.08))
    amp = np.full_like(t, base)
    for a, b, v in loud:
        amp[(t >= a) & (t < b)] = v
    x = tone * env * amp
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return path


PROGRAM = {"name": "試しの番組", "slides": ["a", "b", "c"], "slide_seconds": 3.5}


@needs_ffmpeg
def test_見本は番組名で曲の山が来て_大きさがそろう(tmp_path):
    base = tmp_path / "op.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=pink:s=1280x720:d=15", "-f", "lavfi",
                    "-i", "anullsrc", "-t", "15", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(base)], check=True)
    songs = tmp_path / "songs"
    songs.mkdir()
    song(songs / "quiet.wav", freq=330, base=0.02, loud=((20.0, 35.0, 0.15),))
    song(songs / "loud.wav", bpm=90, freq=880, base=0.2, loud=((25.0, 38.0, 0.9),))
    src = [{"file": "quiet.wav", "title": "静かな曲"}, {"file": "loud.wav", "title": "大きな曲"},
           {"file": "none.wav", "skipped": "利用条件が合わない"}]
    pack = taste.make_clips(base, songs, src, PROGRAM, tmp_path / "out", "試し", "どっち？")
    assert [it["id"] for it in pack["items"]] == ["quiet", "loud"]
    q, ld = pack["items"]
    assert q["start"] == pytest.approx(20 - 10.5, abs=0.2)
    assert ld["start"] == pytest.approx(25 - 10.5, abs=0.4)  # 山の入りはいちばん近い拍に寄せる
    assert q["title_rise_db"] > 3 and ld["title_rise_db"] > 3
    assert ld["features"]["brightness"] > q["features"]["brightness"]
    assert q["features"]["bpm"] == pytest.approx(120, abs=4)
    # 大きさがそろっている（元は 6 倍ちがう）
    def lufs(p):
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(p), "-af", "ebur128", "-f", "null", "-"],
                           check=False, capture_output=True, text=True).stderr
        return float(r.rsplit("I:", 1)[1].split("LUFS")[0])
    out = tmp_path / "out"
    assert abs(lufs(out / "quiet.mp4") - lufs(out / "loud.mp4")) < 2.0
    saved = json.loads((out / taste.PACK).read_text(encoding="utf-8"))
    assert saved["at_title"] == 10.5 and saved["seconds"] == pytest.approx(15, abs=0.1)


def test_いつも選ばれる曲が上に来る():
    ids = ["a", "b", "c", "d"]
    ans = [{"a": "a", "b": "b", "pick": "a"}, {"a": "c", "b": "a", "pick": "b"}, {"a": "a", "b": "d", "pick": "a"},
           {"a": "b", "b": "c", "pick": "a"}, {"a": "d", "b": "c", "pick": "both"}, {"a": "b", "b": "d", "pick": "a"}]
    s = taste.bradley_terry(ids, ans)
    assert max(s, key=s.get) == "a"
    assert s["b"] > s["c"] and s["b"] > s["d"]


def test_一度も比べていない曲は真ん中に残る():
    s = taste.bradley_terry(["a", "b", "x"], [{"a": "a", "b": "b", "pick": "a"}] * 3)
    assert s["a"] > s["x"] > s["b"]


def items(**vals):
    return [{"id": k, "features": {"bpm": v[0], "brightness": v[1], "density": 2, "steadiness": 0.8,
                                   "dynamics_db": 10}} for k, v in vals.items()]


def test_勝った曲に共通する特徴を言葉にする():
    its = items(p=(120, 3000), q=(80, 1200), r=(118, 2900), s=(85, 1300))
    ans = [{"a": "p", "b": "q", "pick": "a"}, {"a": "s", "b": "r", "pick": "b"}, {"a": "q", "b": "r", "pick": "b"},
           {"a": "p", "b": "s", "pick": "a"}, {"a": "r", "b": "q", "pick": "a"}]
    t = {x["feature"]: x for x in taste.tendencies(its, ans)}
    assert t["bpm"]["word"] == "速め" and t["bpm"]["share"] == 1.0
    assert t["brightness"]["word"] == "明るくキラキラした音"
    assert "density" not in t  # 差の無い特徴は言わない


def test_答えが少ないときは言い切らない():
    its = items(p=(120, 3000), q=(80, 1200))
    assert taste.tendencies(its, [{"a": "p", "b": "q", "pick": "a"}] * 3) == []


def test_シートのCSVから答えを読み_カルテに未確認で足す(tmp_path):
    rows = [{"a": "p", "b": "q", "pick": "a", "at": "2026-11-14 10:00", "note": "ピアノの入りがいい"},
            {"a": "q", "b": "p", "pick": "b", "decided": "p"}, {"a": "", "b": "q", "pick": "a"}]
    f = tmp_path / "答え.csv"
    with f.open("w", encoding="utf-8", newline="") as fh:
        w = __import__("csv").writer(fh)
        w.writerow(["時刻", "回", "json"])
        for i, r in enumerate(rows):
            w.writerow(["x", i, json.dumps(r, ensure_ascii=False)])
    ans = taste.read_answers(f)
    assert len(ans) == 2
    pack = {"name": "試し", "items": [{"id": "p", "title": "曲P", "features": {}},
                                      {"id": "q", "title": "曲Q", "features": {}}]}
    rep = taste.report(pack, ans)
    assert rep["top3"][0] == "p" and rep["decided"] == "p"
    lines = taste.karte_lines(rep, "OP", "美麗さん", "2026-11-14")
    assert all(x["status"] == "未確認" for x in lines)
    assert any("ピアノの入りがいい" == x["statement"] for x in lines)
    path = taste.add_to_karte("試し", lines, tmp_path)
    taste.add_to_karte("試し", lines, tmp_path)  # 同じ行は二重に足さない
    assert len(json.loads(path.read_text(encoding="utf-8"))["lines"]) == len(lines)


def test_答えが無ければ止まる(tmp_path):
    f = tmp_path / "a.json"
    f.write_text("[]", encoding="utf-8")
    with pytest.raises(taste.TasteError):
        taste.read_answers(f)
