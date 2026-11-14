"""曲を聞いて番組 OP の使い始めを決める（backend/program_package/music.py）。

曲そのものはリポジトリに置かないので、作った音（拍と、途中から大きくなる山）で確かめる。
"""
import shutil
import wave

import numpy as np
import pytest

from backend.program_package import music as mu
from backend.program_package import opening

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg が無い")
SR = 22050


def song(path, seconds=60, bpm=120, loud=((30.0, 50.0, 0.6),), base=0.05):
    """拍ごとに短い音が鳴り、loud の区間（始まり・終わり・大きさ）だけ大きい曲。"""
    t = np.arange(int(seconds * SR)) / SR
    beat = 60 / bpm
    tone = np.sin(2 * np.pi * 440 * t) + 0.5 * np.sin(2 * np.pi * 660 * t)
    env = np.exp(-((t % beat) / 0.08))  # 拍の頭で立ち上がり、すぐ小さくなる
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


def test_速さと山の入りを見つける(tmp_path):
    a = mu.analyze(song(tmp_path / "s.wav"))
    assert abs(a["duration"] - 60) < 0.1
    assert a["bpm"] == pytest.approx(120, abs=3)
    top = a["climaxes"][0]
    assert top["at"] == pytest.approx(30.0, abs=0.1) and top["rise_db"] > 10


def test_山の入りを番組名の出だしに合わせる(tmp_path):
    a = mu.analyze(song(tmp_path / "s.wav"))
    r = mu.fit(a, at=10.5, total=15.0)
    assert r["start"] == pytest.approx(19.5, abs=0.1)


def test_OPの長さが取れない山は使わず次の山にする(tmp_path):
    # いちばん大きい山は 5 秒（番組名の 10.5 秒に合わせると曲の頭より前になる）。次の山は 40 秒
    a = mu.analyze(song(tmp_path / "s.wav", loud=((5.0, 15.0, 0.9), (40.0, 58.0, 0.5))))
    assert a["climaxes"][0]["at"] == pytest.approx(5.0, abs=0.1)
    assert mu.fit(a, at=10.5, total=15.0)["start"] == pytest.approx(29.5, abs=0.1)


def test_山が無い曲は止まる(tmp_path):
    a = mu.analyze(song(tmp_path / "flat.wav", loud=()))
    assert a["climaxes"] == []
    with pytest.raises(mu.MusicError, match="山がありません"):
        mu.fit(a, at=10.5, total=15.0)


def test_書き出した音で番組名の所が上がっているかを測る(tmp_path):
    s = song(tmp_path / "s.wav")
    r = mu.fit(mu.analyze(s), at=10.5, total=15.0)
    good = mu.read(s, r["start"], 15.0)
    bad = mu.read(s, 0.0, 15.0)  # 人が頭から使ってしまった場合（山が来ない）
    for name, x in (("good", good), ("bad", bad)):
        with wave.open(str(tmp_path / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(mu.SR)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    assert mu.check(tmp_path / "good.wav", 10.5)["ok"]
    assert not mu.check(tmp_path / "bad.wav", 10.5)["ok"]


def test_番組名の出る時刻は番組の指定から読む():
    p = opening.load("backend/config/program/美麗の書道対談.json")
    assert mu.title_at(p) == 10.5 and opening.length(p) == 15.0


def test_fitはremixの指定に書く(tmp_path):
    s = song(tmp_path / "s.wav")
    out = tmp_path / "AUDIO.json"
    out.write_text('{"op_music": {"path": "old.m4a", "start": 0, "volume": 0.7}, "bgm": null, "peak_db": -1.5}', encoding="utf-8")
    assert mu.main(["fit", str(s), "--program", "backend/config/program/美麗の書道対談.json", "--write", str(out)]) == 0
    import json
    w = json.loads(out.read_text(encoding="utf-8"))
    assert w["op_music"]["path"] == str(s) and w["op_music"]["start"] == pytest.approx(19.5, abs=0.1)
    assert w["op_music"]["volume"] == 0.7 and w["peak_db"] == -1.5


def test_AIで作った曲は道具と指示文を残して台帳に足し仮の曲として扱う():
    led = {"tracks": {}}
    with pytest.raises(mu.MusicError, match="指示文"):
        mu.add_track(led, "op_vids_01", title="OP 案1", file="a.mp4", source="Google Vids", by="北原", ai_generated=True)
    t = mu.add_track(led, "op_vids_01", title="OP 案1", file="a.mp4", source="Google Vids（info@）", by="北原",
                     ai_generated=True, made_with="Google Vids", prompt="和の雰囲気、ピアノと箏", today="2026-11-14")
    assert t["provisional"] and t["ai_generated"] and t["prompt"] and t["added"] == {"by": "北原", "on": "2026-11-14"}
    with pytest.raises(mu.MusicError, match="もうあります"):
        mu.add_track(led, "op_vids_01", title="x", file="b.mp4", source="s", by="北原")
    ok = mu.add_track(led, "op_free_01", title="無料曲", file="c.mp3", source="OpenTracks", by="北原", cleared="利用規約 2026-11-14 確認")
    assert ok["provisional"] is False and "ai_generated" not in ok
